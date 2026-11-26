"""程序说明：将数据库中的 ComfyUI 工作流动态注册为 LangChain 工具，完成参数校验、多实例调度、上传去重、种子策略与加锁画布写入。"""
from __future__ import annotations

import copy
import inspect
from io import BytesIO
import json
import os
import random
import time
import traceback
from typing import Annotated, Any, Callable, Dict, List, Optional
import uuid

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from pydantic import BaseModel, Field, create_model

from routers.comfyui_execution import upload_image
from services.comfy_instance_service import (
    comfy_instance_service,
    infer_workflow_model_family,
)
from services.config_service import FILES_DIR, IMAGE_FORMATS, VIDEO_FORMATS
from services.db_service import db_service
from services.gpu_compatibility_guard import (
    ensure_fresh_instance_health,
    evaluate_workflow_hardware_guard,
)
from services.websocket_service import broadcast_session_update, send_to_websocket
from tools.video_generation.video_canvas_utils import (
    generate_new_audio_element,
    generate_new_video_element,
)
from utils.canvas_lock import canvas_lock_manager
from utils.comfyui_history import require_generation_outputs
from utils.path_security import PathSecurityError, safe_file_id_path

from .utils.comfyui import ComfyUIWorkflowRunner
from .utils.image_canvas_utils import (
    generate_file_id,
    generate_new_image_element,
)

SEED_FIELD_NAMES = ("seed", "noise_seed")
AUDIO_FORMATS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac")
ALL_VIDEO_FORMATS = VIDEO_FORMATS + (".webm",)
LOAD_MEDIA_NODE_TYPES = ("LoadImage", "LoadAudio", "LoadVideo")
STALE_UPLOAD_ERROR_MARKERS = (
    "invalid image file",
    "invalid audio file",
    "invalid video file",
    "no such file or directory",
    "filenotfounderror",
    "does not exist",
    "cannot identify image file",
)


def is_stale_upload_execution_error(
    error_text: str, cached_remote_names: List[str]
) -> bool:
    """判断 ComfyUI 执行报错是否由远端重启清空 input/ 目录导致旧缓存文件名失效引起。"""
    if not cached_remote_names or not error_text:
        return False
    lowered = error_text.lower()
    if any(name and name.lower() in lowered for name in cached_remote_names):
        return True
    return any(marker in lowered for marker in STALE_UPLOAD_ERROR_MARKERS)


def _allowed_extensions_for_media_kind(media_kind: Optional[str]) -> tuple[str, ...]:
    """按参数类型返回允许解析并上传到 ComfyUI 的本地媒体后缀列表。"""
    kind = str(media_kind or "image").strip().lower()
    if kind == "video":
        return ALL_VIDEO_FORMATS
    if kind == "audio":
        return AUDIO_FORMATS
    if kind == "any":
        return IMAGE_FORMATS + ALL_VIDEO_FORMATS + AUDIO_FORMATS
    return IMAGE_FORMATS


def resolve_comfy_input_media_path(
    value: Any,
    files_dir: str = FILES_DIR,
    media_kind: Optional[str] = None,
) -> Optional[str]:
    """校验 ComfyUI 工作流传入的本地图片/视频/音频文件名并解析到 files_dir 内，禁止越界或忽略缺失文件。"""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() == "none":
        return None

    allowed_exts = _allowed_extensions_for_media_kind(media_kind)
    if not stripped.lower().endswith(allowed_exts):
        return None

    if stripped.startswith("/api/file/"):
        filename = stripped[len("/api/file/") :]
    elif stripped.startswith(("http://", "https://")) and "/api/file/" in stripped:
        filename = stripped.split("/api/file/", 1)[1]
    else:
        filename = stripped

    media_path = safe_file_id_path(files_dir, filename)
    if not os.path.exists(media_path) or not os.path.isfile(media_path):
        raise FileNotFoundError(f"Input media not found: {filename}")
    return media_path


def resolve_comfy_input_image_path(
    value: Any, files_dir: str = FILES_DIR
) -> Optional[str]:
    """校验 ComfyUI 工作流传入的本地图像文件名（向下兼容别名）。"""
    return resolve_comfy_input_media_path(value, files_dir=files_dir, media_kind="image")


def _prune_unused_optional_media_node(updated: Dict[str, Any], node_key: str) -> None:
    """当可选 LoadImage/LoadAudio/LoadVideo 节点未传值时，移除下游连线并删除该节点。"""
    node_obj = updated.get(node_key)
    if not isinstance(node_obj, dict):
        return
    if str(node_obj.get("class_type") or "") not in LOAD_MEDIA_NODE_TYPES:
        return

    for other_id, other_node in updated.items():
        if other_id == node_key or not isinstance(other_node, dict):
            continue
        other_inputs = other_node.get("inputs")
        if not isinstance(other_inputs, dict):
            continue
        keys_to_remove = [
            k
            for k, v in other_inputs.items()
            if isinstance(v, list)
            and len(v) == 2
            and str(v[0]) == str(node_key)
            and isinstance(v[1], int)
        ]
        for k in keys_to_remove:
            other_inputs.pop(k, None)

    updated.pop(node_key, None)


def _restore_integer_value(param: Dict[str, Any], value: Any) -> Any:
    """number 参数默认值为整数且传入值是整数值的浮点数时，写回整数，避免 ComfyUI INT 输入收到 736.0。"""
    default_val = param.get("default_value")
    if (
        isinstance(default_val, int)
        and not isinstance(default_val, bool)
        and isinstance(value, float)
        and value.is_integer()
    ):
        return int(value)
    return value


def apply_workflow_inputs_and_seeds(
    workflow_dict: Dict[str, Any],
    input_defs: List[Dict[str, Any]],
    required_data: Dict[str, Any],
    seed_generator: Optional[Callable[[], int]] = None,
    seed_strategy: str = "random",
) -> Dict[str, Any]:
    """注入用户参数、裁剪未传入的可选媒体节点，并按 seed_strategy 处理节点 seed / noise_seed。"""
    updated = copy.deepcopy(workflow_dict)
    explicit_node_fields: set[tuple[str, str]] = set()

    for param in input_defs:
        param_name = param.get("name")
        param_type = str(param.get("type") or "string").strip().lower()
        is_required = bool(param.get("required", False))
        node_id = param.get("node_id")
        node_input_name = param.get("node_input_name")

        if not (param_name and node_id and node_input_name):
            continue

        node_key = str(node_id)
        val = required_data.get(param_name)
        is_empty_media = val is None or (
            isinstance(val, str) and val.strip().lower() in ("", "none")
        )

        if not is_required and param_type in ("image", "audio", "video") and is_empty_media:
            _prune_unused_optional_media_node(updated, node_key)
            continue

        effective_val = val
        if (
            effective_val is None
            and param_type not in ("image", "audio", "video")
            and param.get("default_value") is not None
        ):
            effective_val = param.get("default_value")

        if effective_val is not None and (param_name in required_data or param.get("default_value") is not None):
            if node_key in updated and isinstance(updated[node_key], dict):
                node_inputs = updated[node_key].get("inputs")
                if isinstance(node_inputs, dict) and node_input_name in node_inputs:
                    node_inputs[node_input_name] = _restore_integer_value(param, effective_val)
                    if param_name in required_data and val is not None:
                        explicit_node_fields.add((node_key, str(node_input_name)))

    if seed_strategy == "random":
        rng = seed_generator or (lambda: random.randint(1, (1 << 32) - 1))
        for node_id, node in updated.items():
            if not isinstance(node, dict):
                continue
            node_inputs = node.get("inputs")
            if not isinstance(node_inputs, dict):
                continue
            for seed_key in SEED_FIELD_NAMES:
                if (
                    seed_key in node_inputs
                    and not isinstance(node_inputs[seed_key], list)
                    and (str(node_id), seed_key) not in explicit_node_fields
                ):
                    node_inputs[seed_key] = rng()
            # 兼容使用独立 PrimitiveInt 种子节点（如 SenseNova 的 "Int (Seed)"）的工作流
            if str(node.get("class_type") or "") == "PrimitiveInt":
                meta_title = str((node.get("_meta") or {}).get("title") or "").lower()
                if (
                    ("seed" in meta_title or "种子" in meta_title)
                    and "value" in node_inputs
                    and isinstance(node_inputs["value"], int)
                    and not isinstance(node_inputs["value"], bool)
                    and (str(node_id), "value") not in explicit_node_fields
                ):
                    node_inputs["value"] = rng()

    return updated


def _python_type(param_type: str, default: Any):
    """Map simple param types to Python types."""
    if param_type == "number":
        # 统一用 float 接收，避免默认值为整数时 Agent 传入小数（如 7.5 秒）校验失败；写回节点时再还原整数
        return float
    if param_type == "boolean" or param_type == "bool":
        return bool
    return str


def _build_input_schema(wf: Dict[str, Any]) -> type[BaseModel]:
    """
    Build a Pydantic model named '<WorkflowName>Input' from workflow['inputs'].
    """
    try:
        input_defs: List[Dict[str, Any]] = (
            wf["inputs"] if isinstance(wf["inputs"], list) else json.loads(wf["inputs"])
        )
    except Exception:
        input_defs = []

    fields: Dict[str, tuple] = {}
    for param in input_defs:
        name = param.get("name")
        if not name:
            continue
        py_t = _python_type(str(param.get("type") or "string"), param.get("default_value"))
        default_val = param.get("default_value")
        desc = str(param.get("description") or "")
        options = param.get("options")
        if isinstance(options, list) and options:
            desc = f"{desc} Allowed options: {', '.join(str(x) for x in options)}."
        is_required = param.get("required", False)

        if is_required:
            desc = f"Required. {desc}"
            fields[name] = (py_t, Field(description=desc))
        else:
            desc = f"Optional. {desc}"
            fields[name] = (
                Optional[py_t],
                Field(default=default_val, description=desc),
            )
    fields["tool_call_id"] = (
        Annotated[str, InjectedToolCallId],
        Field(description="Tool call identifier"),
    )

    model_name = f"{wf['name'].title().replace(' ', '')}InputSchema"
    return create_model(model_name, __base__=BaseModel, **fields)


def build_tool(wf: Dict[str, Any]) -> BaseTool:
    """Return an @tool function for the given workflow record."""
    input_schema = _build_input_schema(wf)

    @tool(
        wf["name"],
        description=wf.get("description") or f"Run ComfyUI workflow {wf['id']}",
        args_schema=input_schema,
    )
    async def _run(
        config: RunnableConfig,
        tool_call_id: Annotated[str, InjectedToolCallId],
        **kwargs,
    ) -> str:
        """运行动态注册的 ComfyUI 工作流，并将生成的媒体文件写入画布或返回访问链接。"""
        print("🛠️ tool_call_id", tool_call_id)
        ctx = config.get("configurable", {})
        canvas_id = ctx.get("canvas_id", "")
        session_id = ctx.get("session_id", "")
        print("🛠️canvas_id", canvas_id, "session_id", session_id)
        ctx["tool_call_id"] = tool_call_id

        try:
            resolve_fn = comfy_instance_service.resolve_instance
            resolve_kwargs: Dict[str, Any] = {"capability": wf.get("capability")}
            if "workflow_name" in inspect.signature(resolve_fn).parameters:
                resolve_kwargs["workflow_name"] = str(wf.get("name") or "")
            instance = await resolve_fn(wf.get("instance_id"), **resolve_kwargs)
        except Exception as exc:
            await send_to_websocket(session_id, {"type": "error", "error": str(exc)})
            return f"image generation failed: {str(exc)}"

        api_url = str(instance["base_url"]).rstrip("/")
        auth_headers = dict(instance.get("headers") or {})
        instance_id = str(instance.get("id") or "default")
        # 生成任务不设总超时（视频可能很久）；实例的 timeout_sec 字段仅保留兼容，不再参与执行
        max_concurrency = int(instance.get("max_concurrency") or 1)
        # 上传缓存键同时包含实例 ID 与地址，实例改地址后不会误命中旧文件引用
        upload_cache_key = f"{instance_id}|{api_url}"

        try:
            input_defs: List[Dict[str, Any]] = (
                wf["inputs"]
                if isinstance(wf["inputs"], list)
                else json.loads(wf["inputs"])
            )
        except Exception:
            input_defs = []
        param_type_by_name = {
            str(p.get("name") or ""): str(p.get("type") or "string").strip().lower()
            for p in input_defs
            if isinstance(p, dict) and p.get("name")
        }

        required_data = dict(kwargs)
        base_workflow_dict = await db_service.get_comfy_workflow(wf["id"])
        health_metrics = await ensure_fresh_instance_health(instance)
        hw_guard = evaluate_workflow_hardware_guard(
            str(wf.get("name") or ""),
            base_workflow_dict,
            required_data,
            health_metrics,
        )
        if hw_guard.get("blocked"):
            reason = str(hw_guard.get("reason") or "远端显卡规格不兼容")
            await send_to_websocket(session_id, {"type": "error", "error": reason})
            return f"image generation failed: {reason}"
        if hw_guard.get("adjusted_params"):
            required_data.update(hw_guard["adjusted_params"])

        # 提取原始输入媒体文件名与提示词参数，供生成元素写入 customData 血缘谱系（C9）
        lineage_parent_files: List[str] = []
        lineage_prompt = ""
        lineage_scalar_params: Dict[str, Any] = {}
        for k_raw, v_raw in kwargs.items():
            if k_raw == "tool_call_id" or v_raw is None:
                continue
            p_kind = param_type_by_name.get(k_raw, "string")
            if p_kind in ("image", "video", "audio") and isinstance(v_raw, str) and v_raw.strip():
                clean_parent = v_raw.strip().split("/")[-1]
                if clean_parent and clean_parent.lower() != "none":
                    lineage_parent_files.append(clean_parent)
            elif isinstance(v_raw, str) and any(
                pk in k_raw.lower() for pk in ("prompt", "instruction", "text")
            ):
                if not lineage_prompt:
                    lineage_prompt = v_raw.strip()[:1000]
            elif isinstance(v_raw, (int, float, bool, str)):
                lineage_scalar_params[k_raw] = v_raw
        # 记录本次复用 SHA-256 缓存的本地媒体，若远端重启清空了 input/ 可自动失效重传一次
        cached_media_entries: List[tuple[str, str, str, bytes, str, str, str]] = []
        try:
            for key, value in required_data.items():
                p_type = param_type_by_name.get(key, "image")
                media_kind = p_type if p_type in ("image", "video", "audio") else "image"
                media_path = resolve_comfy_input_media_path(
                    value, FILES_DIR, media_kind=media_kind
                )
                if not media_path:
                    continue
                # ComfyUI LoadVideo / LoadAudio 节点的 COMBO 校验仅扫描 input 根目录，不识别子目录前缀
                target_subfolder = "" if media_kind in ("video", "audio") else "jaaz"
                media_cache_key = (
                    upload_cache_key
                    if target_subfolder == "jaaz"
                    else f"{upload_cache_key}|{target_subfolder}"
                )
                filename = os.path.basename(media_path)
                with open(media_path, "rb") as media_file:
                    media_bytes = media_file.read()
                sha256_hex = comfy_instance_service.compute_bytes_sha256(media_bytes)
                cached_name = comfy_instance_service.get_cached_upload(
                    media_cache_key, sha256_hex
                )
                if cached_name:
                    required_data[key] = cached_name
                    cached_media_entries.append(
                        (
                            key,
                            media_cache_key,
                            sha256_hex,
                            media_bytes,
                            filename,
                            cached_name,
                            target_subfolder,
                        )
                    )
                else:
                    media_stream = BytesIO(media_bytes)
                    uploaded_name = await upload_image(
                        media_stream,
                        api_url,
                        filename,
                        subfolder=target_subfolder,
                        headers=auth_headers,
                    )
                    comfy_instance_service.set_cached_upload(
                        media_cache_key, sha256_hex, uploaded_name
                    )
                    required_data[key] = uploaded_name
        except (PathSecurityError, FileNotFoundError) as exc:
            await send_to_websocket(session_id, {"type": "error", "error": str(exc)})
            return f"image generation failed: {str(exc)}"

        seed_strategy = str(wf.get("seed_strategy") or "random")
        workflow_dict = apply_workflow_inputs_and_seeds(
            base_workflow_dict,
            input_defs,
            required_data,
            seed_strategy=seed_strategy,
        )

        job_id = f"job_{uuid.uuid4().hex[:12]}"
        try:
            await db_service.create_job(
                {
                    "id": job_id,
                    "session_id": session_id,
                    "canvas_id": canvas_id,
                    "tool_call_id": tool_call_id,
                    "capability": wf.get("capability") or "t2i",
                    "provider": "comfyui",
                    "instance_id": instance_id,
                    "workflow_id": wf["id"],
                    "status": "running",
                }
            )
        except Exception as job_exc:
            print(f"[comfy_dynamic] Warning creating job record: {job_exc}")
        # 让执行层能把远端 prompt_id 回写到这条任务，并透传显式输出节点配置
        ctx["job_id"] = job_id
        ctx["workflow_name"] = str(wf.get("name") or "")
        if wf.get("outputs"):
            ctx["explicit_outputs"] = wf.get("outputs")
        model_family = infer_workflow_model_family(str(wf.get("name") or ""), workflow_dict)

        try:
            generator = ComfyUIWorkflowRunner(
                workflow_dict,
                api_url,
                headers=auth_headers,
                timeout=None,
                instance_id=instance_id,
            )
            # 按实例 max_concurrency 限流：超出的任务排队等待，而不是同时提交到同一实例
            async with comfy_instance_service.acquire_slot(instance_id, max_concurrency):
                await comfy_instance_service.maybe_free_memory_on_family_switch(
                    instance_id,
                    api_url,
                    model_family,
                    headers=auth_headers,
                )
                try:
                    outputs = await generator.generate(ctx=ctx)
                except Exception as first_exc:
                    cached_names = [entry[5] for entry in cached_media_entries]
                    if not is_stale_upload_execution_error(str(first_exc), cached_names):
                        raise
                    # 远端 ComfyUI 重启清空了 input/，失效对应缓存并重新上传重试一次
                    for (
                        param_key,
                        media_cache_key,
                        sha_hex,
                        raw_bytes,
                        orig_name,
                        _,
                        target_subfolder,
                    ) in cached_media_entries:
                        comfy_instance_service.invalidate_cached_upload(
                            media_cache_key, sha_hex
                        )
                        re_uploaded = await upload_image(
                            BytesIO(raw_bytes),
                            api_url,
                            orig_name,
                            subfolder=target_subfolder,
                            headers=auth_headers,
                        )
                        comfy_instance_service.set_cached_upload(
                            media_cache_key, sha_hex, re_uploaded
                        )
                        required_data[param_key] = re_uploaded
                    retry_workflow = apply_workflow_inputs_and_seeds(
                        base_workflow_dict,
                        input_defs,
                        required_data,
                        seed_strategy=seed_strategy,
                    )
                    generator = ComfyUIWorkflowRunner(
                        retry_workflow,
                        api_url,
                        headers=auth_headers,
                        timeout=None,
                        instance_id=instance_id,
                    )
                    outputs = await generator.generate(ctx=ctx)
            require_generation_outputs(outputs)
            if not isinstance(outputs, list) or (
                outputs and not isinstance(outputs[0], (list, tuple))
            ):
                outputs = [outputs]

            # 写入画布前先获取 canvas_id 互斥锁，避免并发图片/视频工具或用户保存互相覆盖。
            generated_files_info = []
            async with canvas_lock_manager.lock_canvas(canvas_id):
                canvas_data = await db_service.get_canvas_data(canvas_id)
                if canvas_data is None:
                    canvas_data = {"data": {}}
                if "data" not in canvas_data:
                    canvas_data["data"] = {}
                if "elements" not in canvas_data["data"]:
                    canvas_data["data"]["elements"] = []
                if "files" not in canvas_data["data"]:
                    canvas_data["data"]["files"] = {}

                canvas_changed = False
                for output in outputs:
                    mime_type, width, height, filename = output
                    file_id = generate_file_id()
                    url = f"/api/file/{filename}"

                    file_data = {
                        "mimeType": mime_type,
                        "id": file_id,
                        "dataURL": url,
                        "created": int(time.time() * 1000),
                    }

                    new_element = None
                    if mime_type.startswith("image"):
                        new_element = await generate_new_image_element(
                            canvas_id,
                            file_id,
                            {"width": width, "height": height},
                            canvas_data=canvas_data.get("data", {}),
                        )
                    elif mime_type.startswith("video"):
                        new_element = await generate_new_video_element(
                            canvas_id,
                            file_id,
                            {"width": width, "height": height, "url": url},
                            canvas_data=canvas_data.get("data", {}),
                        )
                    elif mime_type.startswith("audio"):
                        new_element = await generate_new_audio_element(
                            canvas_id,
                            file_id,
                            {"width": 360, "height": 108, "url": url},
                            canvas_data=canvas_data.get("data", {}),
                        )

                    if new_element is not None:
                        remote_info = (ctx.get("remote_file_map") or {}).get(filename) or {}
                        existing_cd = (
                            dict(new_element.get("customData"))
                            if isinstance(new_element.get("customData"), dict)
                            else {}
                        )
                        existing_cd.update(
                            {
                                "workflowName": wf["name"],
                                "parentFileIds": lineage_parent_files,
                                "jaazLineage": {
                                    "workflowName": wf["name"],
                                    "displayName": wf.get("display_name") or wf["name"],
                                    "capability": wf.get("capability") or "t2i",
                                    "prompt": lineage_prompt,
                                    "params": lineage_scalar_params,
                                    "parentFileIds": lineage_parent_files,
                                    "comfyOutputPath": remote_info.get("comfy_rel", ""),
                                    "driveFilePath": remote_info.get("drive_path", ""),
                                    "createdAt": int(time.time() * 1000),
                                },
                            }
                        )
                        new_element["customData"] = existing_cd
                        canvas_data["data"]["elements"].append(new_element)
                        canvas_data["data"]["files"][file_id] = file_data
                        canvas_changed = True

                    generated_files_info.append(
                        {
                            "element": new_element,
                            "file": file_data,
                            "url": url,
                            "mime_type": mime_type,
                            "filename": filename,
                        }
                    )

                if canvas_changed:
                    await db_service.save_canvas_data(
                        canvas_id, json.dumps(canvas_data["data"])
                    )

            for file_info in generated_files_info:
                if file_info["element"] is None:
                    continue
                if file_info["mime_type"].startswith("image"):
                    await broadcast_session_update(
                        session_id,
                        canvas_id,
                        {
                            "type": "image_generated",
                            "element": file_info["element"],
                            "file": file_info["file"],
                            "image_url": file_info["url"],
                        },
                    )
                elif file_info["mime_type"].startswith("video"):
                    await broadcast_session_update(
                        session_id,
                        canvas_id,
                        {
                            "type": "video_generated",
                            "element": file_info["element"],
                            "file": file_info["file"],
                            "video_url": file_info["url"],
                        },
                    )
                elif file_info["mime_type"].startswith("audio"):
                    await broadcast_session_update(
                        session_id,
                        canvas_id,
                        {
                            "type": "audio_generated",
                            "element": file_info["element"],
                            "file": file_info["file"],
                            "audio_url": file_info["url"],
                        },
                    )

            try:
                await db_service.update_job_status(
                    job_id,
                    status="completed",
                    progress_pct=100,
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
            except Exception:
                pass

            links = []
            for file_info in generated_files_info:
                if file_info["mime_type"].startswith("audio"):
                    links.append(f"[{file_info['filename']}]({file_info['url']})")
                elif file_info["mime_type"].startswith("video"):
                    links.append(f"![video_id: {file_info['filename']}]({file_info['url']})")
                else:
                    links.append(f"![id: {file_info['filename']}]({file_info['url']})")
            return f"workflow executed successfully {', '.join(links)}"

        except Exception as e:
            err_detail = str(e).strip() or f"{type(e).__name__}"
            print(f"Error generating image: {err_detail}")
            traceback.print_exc()
            try:
                await db_service.update_job_status(
                    job_id,
                    status="failed",
                    error=err_detail,
                    finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
            except Exception:
                pass
            await send_to_websocket(session_id, {"type": "error", "error": str(e)})
            return f"image generation failed: {str(e)}"

    return _run
