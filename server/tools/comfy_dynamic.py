"""程序说明：将数据库中的 ComfyUI 工作流动态注册为 LangChain 工具，完成参数校验、种子保留与加锁画布写入。"""
from __future__ import annotations

import copy
from io import BytesIO
import json
import os
import random
import time
import traceback
from typing import Annotated, Any, Callable, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from pydantic import BaseModel, Field, create_model

from routers.comfyui_execution import upload_image
from services.config_service import FILES_DIR, IMAGE_FORMATS, config_service
from services.db_service import db_service
from services.websocket_service import broadcast_session_update, send_to_websocket
from tools.video_generation.video_canvas_utils import generate_new_video_element
from utils.canvas_lock import canvas_lock_manager
from utils.comfyui_history import require_generation_outputs
from utils.path_security import PathSecurityError, safe_file_id_path

from .utils.comfyui import ComfyUIWorkflowRunner
from .utils.image_canvas_utils import (
    generate_file_id,
    generate_new_image_element,
)

SEED_FIELD_NAMES = ("seed", "noise_seed")


def resolve_comfy_input_image_path(value: Any, files_dir: str = FILES_DIR) -> Optional[str]:
    """校验 ComfyUI 工作流传入的本地图像文件名并解析到 files_dir 内，禁止越界或静默忽略缺失文件。"""
    if not isinstance(value, str) or not value.lower().endswith(IMAGE_FORMATS):
        return None

    stripped = value.strip()
    if stripped.startswith("/api/file/"):
        filename = stripped[len("/api/file/"):]
    elif stripped.startswith(("http://", "https://")) and "/api/file/" in stripped:
        filename = stripped.split("/api/file/", 1)[1]
    else:
        filename = stripped

    image_path = safe_file_id_path(files_dir, filename)
    if not os.path.exists(image_path) or not os.path.isfile(image_path):
        raise FileNotFoundError(f"Input image not found: {filename}")
    return image_path


def apply_workflow_inputs_and_seeds(
    workflow_dict: Dict[str, Any],
    input_defs: List[Dict[str, Any]],
    required_data: Dict[str, Any],
    seed_generator: Optional[Callable[[], int]] = None,
) -> Dict[str, Any]:
    """注入用户参数并按节点精确随机化未显式指定的 seed / noise_seed。"""
    updated = copy.deepcopy(workflow_dict)
    explicit_node_fields: set[tuple[str, str]] = set()

    for param in input_defs:
        param_name = param.get("name")
        node_id = param.get("node_id")
        node_input_name = param.get("node_input_name")

        if not (param_name and node_id and node_input_name):
            continue

        if param_name in required_data and required_data[param_name] is not None:
            value = required_data[param_name]
            node_key = str(node_id)
            if node_key in updated and isinstance(updated[node_key], dict):
                node_inputs = updated[node_key].get("inputs")
                if isinstance(node_inputs, dict) and node_input_name in node_inputs:
                    node_inputs[node_input_name] = value
                    explicit_node_fields.add((node_key, str(node_input_name)))

    rng = seed_generator or (lambda: random.randint(1, (1 << 32) - 1))
    for node_id, node in updated.items():
        if not isinstance(node, dict):
            continue
        node_inputs = node.get("inputs")
        if not isinstance(node_inputs, dict):
            continue
        for seed_key in SEED_FIELD_NAMES:
            if seed_key in node_inputs and (str(node_id), seed_key) not in explicit_node_fields:
                node_inputs[seed_key] = rng()

    return updated


def _python_type(param_type: str, default: Any):
    """Map simple param types to Python types."""
    if param_type == "number":
        if isinstance(default, int):
            return int
        return float
    if param_type == "boolean" or param_type == "bool":
        return bool
    return str


def _build_input_schema(wf: Dict[str, Any]) -> type[BaseModel]:
    """
    Build a Pydantic model named '<WorkflowName>Input' from workflow['inputs'].
    The `inputs` column is stored in DB as JSON text -> parse first.
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
        py_t = _python_type(param.get("type"), param.get("default_value"))
        default_val = param.get("default_value")
        desc = param.get("description", "")
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
        """运行动态注册的 ComfyUI 工作流，并将生成的媒体文件写入画布。"""
        print("🛠️ tool_call_id", tool_call_id)
        ctx = config.get("configurable", {})
        canvas_id = ctx.get("canvas_id", "")
        session_id = ctx.get("session_id", "")
        print("🛠️canvas_id", canvas_id, "session_id", session_id)
        ctx["tool_call_id"] = tool_call_id
        api_url = str(
            config_service.app_config.get("comfyui", {}).get("url", "")
        ).rstrip("/")

        required_data = dict(kwargs)
        try:
            for key, value in required_data.items():
                image_path = resolve_comfy_input_image_path(value, FILES_DIR)
                if not image_path:
                    continue
                filename = os.path.basename(image_path)
                with open(image_path, "rb") as image_file:
                    image_bytes = image_file.read()
                image_stream = BytesIO(image_bytes)
                image_name = await upload_image(image_stream, api_url, filename)
                required_data[key] = image_name
        except (PathSecurityError, FileNotFoundError) as exc:
            await send_to_websocket(session_id, {"type": "error", "error": str(exc)})
            return f"image generation failed: {str(exc)}"

        workflow_dict = await db_service.get_comfy_workflow(wf["id"])

        try:
            input_defs: List[Dict[str, Any]] = (
                wf["inputs"]
                if isinstance(wf["inputs"], list)
                else json.loads(wf["inputs"])
            )
        except Exception:
            input_defs = []

        workflow_dict = apply_workflow_inputs_and_seeds(
            workflow_dict, input_defs, required_data
        )

        try:
            generator = ComfyUIWorkflowRunner(workflow_dict, api_url)
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
                            {"width": width, "height": height},
                            canvas_data=canvas_data.get("data", {}),
                        )

                    if new_element is not None:
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

            markdown_images = [
                f"![id: {file_info['filename']}]({file_info['url']})"
                for file_info in generated_files_info
            ]
            return f"workflow executed successfully {', '.join(markdown_images)}"

        except Exception as e:
            print(f"Error generating image: {str(e)}")
            traceback.print_exc()
            await send_to_websocket(session_id, {"type": "error", "error": str(e)})
            return f"image generation failed: {str(e)}"

    return _run
