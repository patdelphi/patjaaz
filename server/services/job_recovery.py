"""程序说明：服务重启后接管仍在 ComfyUI 上执行的任务，轮询 /history 取回产出并写回原画布，避免长视频任务因重启丢失结果。"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Tuple

import httpx

from services.comfy_instance_service import build_comfy_http_url, comfy_instance_service
from services.db_service import db_service
from services.websocket_service import broadcast_session_update
from tools.utils.comfyui import download_outputs
from tools.utils.image_canvas_utils import generate_file_id, generate_new_image_element
from tools.video_generation.video_canvas_utils import generate_new_video_element
from utils.canvas_lock import canvas_lock_manager
from utils.comfyui_history import history_output_urls
from utils.http_client import HttpClient

POLL_INTERVAL_SEC = 10.0
# 远端连续不可达的最大次数（约 10 分钟）；超过则放弃并标为 interrupted
MAX_UNREACHABLE_POLLS = 60
# 既不在 history 也不在队列里的确认次数，避免 history 写入延迟造成误判
LOST_CONFIRM_POLLS = 3


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def append_outputs_to_canvas(
    canvas_id: str,
    session_id: str,
    outputs: List[Tuple[str, int, int, str]],
) -> int:
    """把下载好的图片/视频作为元素写入画布（持画布锁），并向在线会话广播；返回写入的元素数。"""
    added: List[Dict[str, Any]] = []
    async with canvas_lock_manager.lock_canvas(canvas_id):
        canvas = await db_service.get_canvas_data(canvas_id)
        data = (canvas or {}).get("data") or {}
        data.setdefault("elements", [])
        data.setdefault("files", {})

        for mime_type, width, height, filename in outputs:
            file_id = generate_file_id()
            url = f"/api/file/{filename}"
            file_data = {
                "mimeType": mime_type,
                "id": file_id,
                "dataURL": url,
                "created": int(time.time() * 1000),
            }
            element = None
            size = {"width": width, "height": height}
            if mime_type.startswith("image"):
                element = await generate_new_image_element(
                    canvas_id, file_id, size, canvas_data=data
                )
            elif mime_type.startswith("video"):
                element = await generate_new_video_element(
                    canvas_id, file_id, {**size, "url": url}, canvas_data=data
                )
            if element is None:
                continue
            data["elements"].append(element)
            data["files"][file_id] = file_data
            added.append(
                {"element": element, "file": file_data, "url": url, "mime": mime_type}
            )

        if added:
            await db_service.save_canvas_data(canvas_id, json.dumps(data))

    # 客户端此刻在线时即时刷新；不在线则下次打开画布从数据库读取
    for item in added:
        kind = "image" if item["mime"].startswith("image") else "video"
        try:
            await broadcast_session_update(
                session_id,
                canvas_id,
                {
                    "type": f"{kind}_generated",
                    "element": item["element"],
                    "file": item["file"],
                    f"{kind}_url": item["url"],
                },
            )
        except Exception as exc:
            print(f"[job_recovery] broadcast failed: {exc}")
    return len(added)


async def _probe(
    base_url: str, headers: Dict[str, str], prompt_id: str
) -> Tuple[str, Any]:
    """查询远端任务状态：done(history 记录) / pending / lost / unreachable。"""
    try:
        async with HttpClient.create(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(
                build_comfy_http_url(base_url, f"/history/{prompt_id}"),
                headers=headers or None,
            )
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, dict) and prompt_id in body:
                    return "done", body[prompt_id]

            queue_resp = await client.get(
                build_comfy_http_url(base_url, "/queue"), headers=headers or None
            )
            if queue_resp.status_code == 200:
                queue = queue_resp.json()
                if prompt_id in json.dumps(queue, ensure_ascii=False):
                    return "pending", None
                return "lost", None
            return "unreachable", None
    except Exception:
        return "unreachable", None


async def recover_job(job: Dict[str, Any]) -> str:
    """接管一条重启前仍在远端执行的任务，直到取回产出、失败或放弃；返回最终状态。"""
    job_id = str(job["id"])
    prompt_id = str(job.get("remote_prompt_id") or "")
    canvas_id = str(job.get("canvas_id") or "")
    session_id = str(job.get("session_id") or "")

    try:
        instance = await comfy_instance_service.resolve_instance(job.get("instance_id"))
    except Exception as exc:
        await db_service.update_job_status(
            job_id, status="interrupted", error=f"Cannot resolve ComfyUI instance: {exc}",
            finished_at=_now_iso(),
        )
        return "interrupted"

    base_url = str(instance["base_url"])
    headers = dict(instance.get("headers") or {})
    unreachable = 0
    lost = 0

    while True:
        state, record = await _probe(base_url, headers, prompt_id)

        if state == "done":
            status_str = ((record or {}).get("status") or {}).get("status_str")
            if status_str == "error":
                await db_service.update_job_status(
                    job_id, status="failed", error="ComfyUI reported an execution error",
                    finished_at=_now_iso(),
                )
                return "failed"
            urls = history_output_urls(record, base_url)
            if not urls:
                await db_service.update_job_status(
                    job_id, status="failed", error="ComfyUI finished without outputs",
                    finished_at=_now_iso(),
                )
                return "failed"
            try:
                outputs = await download_outputs(urls, headers)
                added = await append_outputs_to_canvas(canvas_id, session_id, outputs)
            except Exception as exc:
                await db_service.update_job_status(
                    job_id, status="failed", error=f"Recovery failed: {exc}",
                    finished_at=_now_iso(),
                )
                return "failed"
            await db_service.update_job_status(
                job_id,
                status="completed",
                progress_pct=100,
                progress_text=f"Recovered {added} output(s) after server restart",
                finished_at=_now_iso(),
            )
            print(f"[job_recovery] job {job_id} recovered {added} output(s) into canvas {canvas_id}")
            return "completed"

        if state == "pending":
            unreachable = 0
            lost = 0
        elif state == "lost":
            lost += 1
            if lost >= LOST_CONFIRM_POLLS:
                await db_service.update_job_status(
                    job_id, status="interrupted",
                    error="Remote prompt no longer in queue or history",
                    finished_at=_now_iso(),
                )
                return "interrupted"
        else:
            unreachable += 1
            if unreachable >= MAX_UNREACHABLE_POLLS:
                await db_service.update_job_status(
                    job_id, status="interrupted",
                    error="ComfyUI instance unreachable during recovery",
                    finished_at=_now_iso(),
                )
                return "interrupted"

        await asyncio.sleep(POLL_INTERVAL_SEC)


async def recover_jobs(jobs: List[Dict[str, Any]]) -> None:
    """并行接管所有可恢复任务；单个任务失败不影响其他任务。"""
    results = await asyncio.gather(
        *(recover_job(job) for job in jobs), return_exceptions=True
    )
    for job, result in zip(jobs, results):
        if isinstance(result, Exception):
            print(f"[job_recovery] job {job.get('id')} crashed: {result}")
