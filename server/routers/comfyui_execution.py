"""程序说明：封装 ComfyUI 工作流执行、图片上传、多实例鉴权头注入、WebSocket 进度监听与 /history 降级恢复。"""
import asyncio
from datetime import timedelta
import inspect
import json
import time
import urllib.parse
import uuid
from typing import Any, Dict, Optional

import httpx
from rich import print as pprint
from rich.progress import BarColumn, Column, Progress, Table, TimeElapsedColumn
import websockets

from services.comfy_instance_service import (
    build_comfy_http_url,
    build_comfy_ws_url,
    comfy_instance_service,
    normalize_comfy_base_url,
)
from services.stream_service import update_stream_status
from services.websocket_service import send_to_websocket
from utils.comfyui_history import COMFY_OUTPUT_KEYS, history_output_urls
from utils.http_client import HttpClient


class ComfyUIUnavailableError(RuntimeError):
    """ComfyUI 服务未启动或不可达时抛出的业务异常。"""


class ComfyUIExecutionError(RuntimeError):
    """ComfyUI 工作流提交、上传或执行失败时抛出的业务异常。"""


def _extract_http_error_detail(exc: httpx.HTTPStatusError) -> str:
    """从 ComfyUI 非 2xx 响应中安全提取错误信息或节点报错详情。"""
    status_code = exc.response.status_code
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            node_errors = body.get("node_errors")
            if isinstance(node_errors, dict) and node_errors:
                return json.dumps(node_errors, indent=2)
            error_info = body.get("error")
            if error_info:
                return json.dumps(error_info, indent=2) if isinstance(error_info, (dict, list)) else str(error_info)
    except ValueError:
        pass
    text = (exc.response.text or "").strip()
    return text or f"ComfyUI HTTP error {status_code}"


async def check_comfy_server_running(
    base_url: str, headers: Optional[Dict[str, str]] = None
) -> bool:
    """检查目标 ComfyUI 服务是否可用（兼容子路径前缀与鉴权头）。"""
    if not base_url:
        return False
    try:
        normalized = normalize_comfy_base_url(base_url)
        async with HttpClient.create(timeout=10) as client:
            for endpoint in ("/api/prompt", "/system_stats"):
                response = await client.get(
                    build_comfy_http_url(normalized, endpoint),
                    headers=headers or None,
                )
                if response.status_code == 200:
                    return True
            return False
    except Exception:
        return False


async def execute(
    workflow: dict,
    base_url: str,
    wait: bool = True,
    verbose: bool = False,
    local_paths: bool = False,
    timeout: Optional[float] = None,
    ctx: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    instance_id: Optional[str] = None,
):
    """提交并等待 ComfyUI 工作流执行完成，支持鉴权头、子路径前缀与取消联动。"""
    ctx = ctx if ctx is not None else {}
    normalized_url = normalize_comfy_base_url(base_url)
    if not await check_comfy_server_running(normalized_url, headers=headers):
        pprint(f"[bold red]ComfyUI not running on specified address ({normalized_url})[/bold red]")
        raise ComfyUIUnavailableError(f"ComfyUI not running on specified address ({normalized_url})")

    progress = None
    start = time.time()
    if wait:
        pprint("Executing comfyui workflow")
        progress = ExecutionProgress()
    else:
        print("Queuing comfyui workflow")

    execution = WorkflowExecution(
        workflow,
        normalized_url,
        verbose,
        progress,
        local_paths,
        timeout,
        ctx=ctx,
        headers=headers,
        instance_id=instance_id,
    )

    session_id = ctx.get("session_id")
    try:
        if wait:
            await execution.connect()
        await execution.queue()
        # 把远端 prompt_id 写入任务记录，服务重启后可据此从 /history 找回产出
        job_id = ctx.get("job_id")
        if job_id and execution.prompt_id:
            try:
                from services.db_service import db_service

                await db_service.update_job_status(
                    job_id, remote_prompt_id=str(execution.prompt_id)
                )
            except Exception as exc:
                print(f"[comfyui_execution] Warning saving remote_prompt_id: {exc}")
        if session_id and execution.prompt_id:
            comfy_instance_service.register_active_prompt(
                session_id,
                normalized_url,
                execution.prompt_id,
                headers=headers,
                instance_id=instance_id,
            )
        if wait:
            await execution.watch_execution()
            end = time.time()
            if progress:
                progress.stop()
                progress = None

            if len(execution.outputs) > 0:
                pprint("[bold green]\nOutputs:[/bold green]")
                for f in execution.outputs:
                    pprint(f)

            elapsed = timedelta(seconds=end - start)
            pprint(f"[bold green]\nWorkflow execution completed ({elapsed})[/bold green]")
        else:
            pprint("[bold green]Workflow queued[/bold green]")
    except asyncio.CancelledError:
        if session_id:
            await comfy_instance_service.cancel_session_prompts(session_id)
        raise
    finally:
        if session_id and execution.prompt_id:
            comfy_instance_service.unregister_active_prompt(session_id, execution.prompt_id)
        if progress:
            progress.stop()
        await execution.close_ws()
    return execution


class ExecutionProgress(Progress):
    """终端富文本进度展示辅助类。"""

    def get_renderables(self):
        table_columns = (
            (
                Column(no_wrap=True)
                if isinstance(_column, str)
                else _column.get_table_column().copy()
            )
            for _column in self.columns
        )

        for task in self.tasks:
            percent = "[progress.percentage]{task.percentage:>3.0f}%".format(task=task)
            if task.fields.get("progress_type") == "overall":
                overall_table = Table.grid(
                    *table_columns, padding=(0, 1), expand=self.expand
                )
                overall_table.add_row(
                    BarColumn().render(task), percent, TimeElapsedColumn().render(task)
                )
                yield overall_table
            else:
                yield self.make_tasks_table([task])


class WorkflowExecution:
    """管理单次 ComfyUI 工作流的排队、WebSocket 监听与输出提取。"""

    def __init__(
        self,
        workflow: Dict[str, Any],
        base_url: str,
        verbose: bool,
        progress: Optional[ExecutionProgress],
        local_paths: bool,
        timeout: Optional[float] = None,
        ctx: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        instance_id: Optional[str] = None,
    ):
        self.workflow = workflow or {}
        self.base_url = str(base_url).rstrip("/")
        self.verbose = verbose
        self.local_paths = local_paths
        self.client_id = str(uuid.uuid4())
        self.outputs: list[str] = []
        self.progress = progress
        self.remaining_nodes = set(self.workflow.keys())
        self.total_nodes = len(self.remaining_nodes)
        self.overall_task = (
            self.progress.add_task("", total=self.total_nodes, progress_type="overall")
            if self.progress
            else None
        )
        self.current_node = None
        self.progress_task = None
        self.progress_node = None
        self.prompt_id = None
        self.ws = None
        self.ws_core = "ws://"
        # timeout 为空或 <=0 表示不限时：视频等长任务由 ComfyUI 自己结束，断线时降级轮询 /history
        self.timeout: Optional[float] = float(timeout) if timeout and timeout > 0 else None
        self.ctx = ctx if ctx is not None else {}
        self.headers = dict(headers or {})
        self.instance_id = instance_id

    async def close_ws(self) -> None:
        """确保关闭 WebSocket 连接，防止句柄泄漏。"""
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            finally:
                self.ws = None

    async def connect(self):
        """建立 ComfyUI /ws 连接（完整保留子路径前缀并透传鉴权请求头）。"""
        ws_url = build_comfy_ws_url(self.base_url, self.client_id)
        self.ws_core = "wss://" if ws_url.startswith("wss://") else "ws://"
        connect_kwargs: Dict[str, Any] = {}
        if self.headers:
            params = inspect.signature(websockets.connect).parameters
            if "additional_headers" in params:
                connect_kwargs["additional_headers"] = self.headers
            elif "extra_headers" in params:
                connect_kwargs["extra_headers"] = self.headers
        self.ws = await websockets.connect(ws_url, **connect_kwargs)

    async def queue(self):
        """提交工作流到 ComfyUI /prompt，并校验响应状态码。"""
        data = {"prompt": self.workflow, "client_id": self.client_id}
        async with HttpClient.create() as client:
            try:
                response = await client.post(
                    build_comfy_http_url(self.base_url, "/prompt"),
                    json=data,
                    headers=self.headers or None,
                )
                response.raise_for_status()
                body = response.json()
                self.prompt_id = body["prompt_id"]
            except httpx.HTTPStatusError as exc:
                message = _extract_http_error_detail(exc)
                if self.progress:
                    self.progress.stop()
                pprint(f"[bold red]Error running workflow\n{message}[/bold red]")
                await send_to_websocket(
                    self.ctx.get("session_id"), {"type": "error", "error": message}
                )
                raise ComfyUIExecutionError(message) from exc

    async def _fetch_history_outputs(self) -> bool:
        """查询 /history/{prompt_id}，若已完成则回填输出 URL 并返回 True；加载大模型阻塞事件循环导致瞬时超时时安全返回 False。"""
        if not self.prompt_id:
            return False
        try:
            async with HttpClient.create(timeout=20.0) as client:
                response = await client.get(
                    build_comfy_http_url(self.base_url, f"/history/{self.prompt_id}"),
                    headers=self.headers or None,
                )
                if response.status_code != 200:
                    return False
                response_body = response.json()
                if isinstance(response_body, dict) and self.prompt_id in response_body:
                    # 反向代理或 WS 断连时从完成记录恢复所有媒体输出
                    for url in history_output_urls(response_body[self.prompt_id], self.base_url):
                        if url not in self.outputs:
                            self.outputs.append(url)
                    return True
        except (httpx.HTTPError, asyncio.TimeoutError, OSError, ValueError) as exc:
            print(
                f"[comfyui_execution] Transient history probe error for {self.prompt_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            return False
        return False

    async def _poll_history_until_done(self, deadline: float) -> None:
        """WebSocket 断开时降级为轮询 /history/{prompt_id} 直到完成或超时。"""
        while time.monotonic() < deadline:
            if await self._fetch_history_outputs():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(2.0, remaining))
        raise TimeoutError(f"ComfyUI execution timed out after {self.timeout}s")

    async def watch_execution(self):
        """监听工作流执行直到完成；带总超时与单帧等待超时，断线自动降级轮询历史。"""
        # 不限时（timeout 为空）时 deadline 为无穷大，只受 ComfyUI 实际结束或取消控制
        deadline = (
            time.monotonic() + self.timeout if self.timeout is not None else float("inf")
        )
        ws_idle_timeout = min(30.0, self.timeout) if self.timeout is not None else 30.0

        try:
            if self.ws is None:
                await self._poll_history_until_done(deadline)
                return

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"ComfyUI execution timed out after {self.timeout}s")

                try:
                    raw_message = await asyncio.wait_for(
                        self.ws.recv(), timeout=min(ws_idle_timeout, remaining)
                    )
                except asyncio.TimeoutError:
                    if await self._fetch_history_outputs():
                        return
                    continue
                except (websockets.ConnectionClosed, websockets.WebSocketException, OSError):
                    if await self._fetch_history_outputs():
                        return
                    await self._poll_history_until_done(deadline)
                    return

                if not isinstance(raw_message, str):
                    continue

                message = json.loads(raw_message)
                msg_type = message.get("type")
                data = message.get("data") if isinstance(message.get("data"), dict) else {}
                if msg_type != "status" and data.get("prompt_id") != self.prompt_id:
                    continue

                if not await self.on_message(message):
                    if await self._fetch_history_outputs():
                        return
        finally:
            await self.close_ws()

    def update_overall_progress(self):
        """更新整体节点完成进度条。"""
        if self.progress and self.overall_task is not None:
            self.progress.update(
                self.overall_task, completed=self.total_nodes - len(self.remaining_nodes)
            )

    def get_node_title(self, node_id: Any) -> str:
        """安全解析节点标题，兼容动态子图 ID（如 12:3）和未知节点 ID。"""
        node = self.workflow.get(node_id)
        if node is None and isinstance(node_id, str) and ":" in node_id:
            node = self.workflow.get(node_id.split(":", 1)[0])
        if not isinstance(node, dict):
            return f"Node {node_id}"
        meta = node.get("_meta")
        if isinstance(meta, dict) and meta.get("title"):
            return str(meta["title"])
        class_type = node.get("class_type")
        if class_type:
            return str(class_type)
        return f"Node {node_id}"

    def log_node(self, kind: str, node_id: Any) -> None:
        """在启用 verbose 时打印当前节点执行日志。"""
        if not self.verbose:
            return

        node = self.workflow.get(node_id)
        if node is None and isinstance(node_id, str) and ":" in node_id:
            node = self.workflow.get(node_id.split(":", 1)[0])
        class_type = node.get("class_type", "") if isinstance(node, dict) else ""
        title = self.get_node_title(node_id)

        if class_type and title != class_type:
            title += f"[bright_black] - {class_type}[/]"
        title += f"[bright_black] ({node_id})[/]"

        pprint(f"{kind} : {title}")

    def format_image_path(self, media: Dict[str, Any]) -> str:
        """拼装 ComfyUI /view 资源地址。"""
        query = urllib.parse.urlencode(media)
        return f"{self.base_url}/view?{query}"

    async def on_message(self, message: Dict[str, Any]) -> bool:
        """分发单条 ComfyUI WebSocket 消息；返回 False 表示执行结束。"""
        msg_type = message.get("type")
        data = message.get("data") if isinstance(message.get("data"), dict) else {}

        # status 事件通常不含 prompt_id，必须先于 prompt_id 过滤处理
        if msg_type == "status":
            return await self.on_status(data)

        if "prompt_id" not in data or data["prompt_id"] != self.prompt_id:
            return True

        if msg_type == "executing":
            return await self.on_executing(data)
        if msg_type == "execution_cached":
            await self.on_cached(data)
        elif msg_type == "progress":
            await self.on_progress(data)
        elif msg_type == "executed":
            await self.on_executed(data)
        elif msg_type == "execution_error":
            await self.on_error(data)

        return True

    async def on_status(self, data: Dict[str, Any]) -> bool:
        """处理排队状态消息，并显式返回 True 以免被误判为完成。"""
        status_info = data.get("status") if isinstance(data.get("status"), dict) else {}
        exec_info = status_info.get("exec_info") if isinstance(status_info.get("exec_info"), dict) else {}
        queue = exec_info.get("queue_remaining")
        if queue is None:
            return True

        status = f"In queue, there's {queue} works ahead..."
        update_stream_status(self.ctx.get("session_id"), status)
        if self.ctx.get("session_id"):
            await send_to_websocket(
                self.ctx.get("session_id"),
                {
                    "type": "tool_call_progress",
                    "tool_call_id": self.ctx.get("tool_call_id"),
                    "session_id": self.ctx.get("session_id"),
                    "update": status,
                },
            )
        return True

    async def on_executing(self, data: Dict[str, Any]) -> bool:
        """处理节点开始或结束执行事件。"""
        if self.progress and self.progress_task is not None:
            self.progress.remove_task(self.progress_task)
            self.progress_task = None

        if data.get("node") is None:
            update_stream_status(
                self.ctx.get("session_id"), "Finalizing generated media..."
            )
            return False

        if self.current_node:
            self.remaining_nodes.discard(self.current_node)
            self.update_overall_progress()
        node_id = data.get("display_node", data.get("node"))

        self.current_node = node_id
        self.log_node("Executing", node_id)
        status = f"Executing {self.get_node_title(node_id)}"
        update_stream_status(self.ctx.get("session_id"), status)
        if self.ctx.get("session_id"):
            await send_to_websocket(
                self.ctx.get("session_id"),
                {
                    "type": "tool_call_progress",
                    "tool_call_id": self.ctx.get("tool_call_id"),
                    "session_id": self.ctx.get("session_id"),
                    "update": status,
                },
            )
        return True

    async def on_cached(self, data: Dict[str, Any]) -> None:
        """处理命中缓存跳过的节点。"""
        for n in data.get("nodes", []):
            self.remaining_nodes.discard(n)
            self.log_node("Cached", n)
        self.update_overall_progress()

    async def on_progress(self, data: Dict[str, Any]) -> None:
        """转发采样步数百分比进度。"""
        node = data.get("node")
        max_val = data.get("max") or 1
        val = data.get("value") or 0
        status = f"Executing {self.get_node_title(node)} {round(val / max_val * 100)}%"
        update_stream_status(self.ctx.get("session_id"), status)
        if self.ctx.get("session_id"):
            await send_to_websocket(
                self.ctx.get("session_id"),
                {
                    "type": "tool_call_progress",
                    "tool_call_id": self.ctx.get("tool_call_id"),
                    "session_id": self.ctx.get("session_id"),
                    "update": status,
                },
            )
        if self.progress:
            if self.progress_node != node:
                self.progress_node = node
                if self.progress_task is not None:
                    self.progress.remove_task(self.progress_task)
                self.progress_task = self.progress.add_task(
                    self.get_node_title(node), total=max_val, progress_type="node"
                )
            if self.progress_task is not None:
                self.progress.update(self.progress_task, completed=val)

    async def on_executed(self, data: Dict[str, Any]) -> None:
        """提取节点输出的图像、动图、视频和音频地址。"""
        node_id = data.get("node")
        if node_id is not None:
            self.remaining_nodes.discard(node_id)
            self.update_overall_progress()

        output = data.get("output")
        if not isinstance(output, dict):
            return

        update_stream_status(
            self.ctx.get("session_id"), "Finishing generated media..."
        )

        for key in COMFY_OUTPUT_KEYS:
            for item in output.get(key, []) or []:
                if isinstance(item, dict) and item.get("filename"):
                    url = self.format_image_path(item)
                    if url not in self.outputs:
                        self.outputs.append(url)

        if self.ctx.get("session_id"):
            await send_to_websocket(
                self.ctx.get("session_id"),
                {
                    "type": "tool_call_progress",
                    "tool_call_id": self.ctx.get("tool_call_id"),
                    "session_id": self.ctx.get("session_id"),
                    "update": "",
                },
            )

    async def on_error(self, data: Dict[str, Any]) -> None:
        """处理 ComfyUI 节点运行期异常并抛出业务异常。"""
        formatted = json.dumps(data, indent=2)
        pprint(f"[bold red]Error running workflow\n{formatted}[/bold red]")
        if self.ctx.get("session_id"):
            await send_to_websocket(
                self.ctx.get("session_id"),
                {"type": "error", "error": formatted},
            )
        raise ComfyUIExecutionError(formatted)


async def upload_image(
    image,
    base_url: str,
    filename=None,
    subfolder="jaaz",
    headers: Optional[Dict[str, str]] = None,
) -> str:
    """上传参考图到 ComfyUI /upload/image，并校验 HTTP 状态码。"""
    normalized_url = normalize_comfy_base_url(base_url)
    files = {"image": (filename, image)}
    data = {"type": "input", "subfolder": subfolder, "overwrite": "false"}
    async with HttpClient.create() as client:
        try:
            response = await client.post(
                build_comfy_http_url(normalized_url, "/upload/image"),
                files=files,
                data=data,
                headers=headers or None,
            )
            response.raise_for_status()
            body = response.json()
            image_name = body["name"]
            return f"{subfolder}/{image_name}"
        except httpx.HTTPStatusError as exc:
            message = _extract_http_error_detail(exc)
            pprint(f"[bold red]Error uploading image\n{message}[/bold red]")
            raise ComfyUIExecutionError(message) from exc
