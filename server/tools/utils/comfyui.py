"""程序说明：提供 ComfyUI 基础生成、工作流运行及输出媒体类型识别与落盘工具。"""
import copy
import json
import mimetypes
import os
import random
import sys
import traceback
from typing import Optional

import aiofiles

from routers.comfyui_execution import execute
from services.config_service import (
    FILES_DIR,
    IMAGE_FORMATS,
    VIDEO_FORMATS,
    config_service,
)
from services.file_mapping_service import parse_comfy_view_url, record_file_mapping
from tools.video_generation.video_canvas_utils import get_video_info_and_save
from utils.http_client import HttpClient
from .image_utils import generate_image_id, get_image_info_and_save

AUDIO_FORMATS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac")


async def detect_file_type_comprehensive(
    url: str, headers: Optional[dict[str, str]] = None
) -> str:
    """综合通过 Content-Type 与扩展名判断 ComfyUI 输出媒体类型（image/video/audio）。"""
    lower_url = url.lower()
    try:
        async with HttpClient.create() as client:
            response = await client.head(url, headers=headers or None)
            content_type = response.headers.get("content-type", "").lower()

            if content_type.startswith("image/"):
                return "image"
            if content_type.startswith("video/"):
                return "video"
            if content_type.startswith("audio/"):
                return "audio"

        if any(fmt in lower_url for fmt in IMAGE_FORMATS):
            return "image"
        if any(fmt in lower_url for fmt in VIDEO_FORMATS):
            return "video"
        if any(fmt in lower_url for fmt in AUDIO_FORMATS):
            return "audio"

        return "image"
    except Exception:
        if any(fmt in lower_url for fmt in AUDIO_FORMATS):
            return "audio"
        return "image" if any(fmt in lower_url for fmt in IMAGE_FORMATS) else "video"


async def get_audio_info_and_save(
    url: str,
    file_path_without_extension: str,
    headers: Optional[dict[str, str]] = None,
) -> tuple[str, int, int, str]:
    """流式下载并原子保存 ComfyUI 输出的音频文件。"""
    ext = "wav"
    lower_url = url.lower()
    for candidate in AUDIO_FORMATS:
        if candidate in lower_url:
            ext = candidate.lstrip(".")
            break

    out_path = f"{file_path_without_extension}.{ext}"
    part_path = f"{out_path}.part"
    try:
        async with HttpClient.create_aiohttp() as session:
            async with session.get(url, headers=headers or None) as response:
                response.raise_for_status()
                async with aiofiles.open(part_path, "wb") as out_file:
                    async for chunk in response.content.iter_chunked(1024 * 64):
                        if chunk:
                            await out_file.write(chunk)
        os.replace(part_path, out_path)
    finally:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
    mime_type = mimetypes.types_map.get(f".{ext}", f"audio/{ext}")
    return mime_type, 0, 0, ext


def get_asset_path(filename: str) -> str:
    """解析服务端内置工作流资产路径（兼容打包模式与源码运行）。"""
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    return os.path.join(base_path, "asset", filename)


class ComfyUIGenerator:
    """ComfyUI 内置文生图执行器。"""

    def __init__(self):
        asset_dir = get_asset_path("flux_comfy_workflow.json")
        basic_comfy_t2i_workflow = get_asset_path("default_comfy_t2i_workflow.json")

        self.flux_comfy_workflow = None
        self.basic_comfy_t2i_workflow = None
        self.comfy_websocket_client = None

        try:
            with open(asset_dir, "r", encoding="utf-8") as f:
                self.flux_comfy_workflow = json.load(f)
            with open(basic_comfy_t2i_workflow, "r", encoding="utf-8") as f:
                self.basic_comfy_t2i_workflow = json.load(f)
        except Exception:
            traceback.print_exc()

    async def generate(
        self,
        prompt: str,
        model: str,
        aspect_ratio: str = "1:1",
        input_image: Optional[str] = None,
        **kwargs,
    ) -> tuple[str, int, int, str]:
        """执行默认文生图 ComfyUI 工作流。"""
        if not self.flux_comfy_workflow:
            raise FileNotFoundError("Flux workflow json not found")

        ctx = kwargs.get("ctx", {})
        api_url = str(
            config_service.app_config.get("comfyui", {}).get("url", "")
        ).rstrip("/")

        pixel_count = 1024**2 if "flux" in model else 768**2
        w_ratio, h_ratio = map(int, aspect_ratio.split(":"))
        factor = (pixel_count / (w_ratio * h_ratio)) ** 0.5
        width = int((factor * w_ratio) / 64) * 64
        height = int((factor * h_ratio) / 64) * 64

        if "flux" in model:
            workflow = copy.deepcopy(self.flux_comfy_workflow)
            workflow["6"]["inputs"]["text"] = prompt
            workflow["30"]["inputs"]["ckpt_name"] = model
            workflow["27"]["inputs"]["width"] = width
            workflow["27"]["inputs"]["height"] = height
            workflow["31"]["inputs"]["seed"] = random.randint(1, 2**32)
        else:
            workflow = copy.deepcopy(self.basic_comfy_t2i_workflow)
            workflow["6"]["inputs"]["text"] = prompt
            workflow["4"]["inputs"]["ckpt_name"] = model
            workflow["5"]["inputs"]["width"] = width
            workflow["5"]["inputs"]["height"] = height
            workflow["3"]["inputs"]["seed"] = random.randint(1, 2**32)

        execution = await execute(workflow, api_url, ctx=ctx)
        print("🦄image execution outputs", execution.outputs)
        url = execution.outputs[0]

        image_id = generate_image_id()
        mime_type, width, height, extension = await get_image_info_and_save(
            url, os.path.join(FILES_DIR, f"{image_id}")
        )
        filename = f"{image_id}.{extension}"
        return mime_type, width, height, filename


async def download_outputs(
    urls: list[str], headers: Optional[dict[str, str]] = None
) -> list[tuple[str, int, int, str]]:
    """把 ComfyUI 输出 URL 逐个下载保存到 FILES_DIR，返回 (mime, width, height, filename) 列表。"""
    results: list[tuple[str, int, int, str]] = []
    for url in urls:
        image_id = generate_image_id()
        file_type = await detect_file_type_comprehensive(url, headers=headers)
        if file_type == "video":
            get_info_func = get_video_info_and_save
        elif file_type == "audio":
            get_info_func = get_audio_info_and_save
        else:
            get_info_func = get_image_info_and_save

        mime_type, width, height, extension = await get_info_func(
            url, os.path.join(FILES_DIR, f"{image_id}"), headers=headers
        )
        results.append((mime_type, width, height, f"{image_id}.{extension}"))
    return results


class ComfyUIWorkflowRunner:
    """通用动态 ComfyUI 工作流运行器，支持多实例鉴权头与图片、视频、音频输出落盘。"""

    def __init__(
        self,
        workflow_dict: dict,
        base_url: str,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
        instance_id: Optional[str] = None,
    ):
        self.workflow = workflow_dict
        self.base_url = base_url
        self.headers = dict(headers or {})
        # 为空表示不限时，适配耗时很长的视频生成
        self.timeout = float(timeout) if timeout and timeout > 0 else None
        self.instance_id = instance_id

    async def generate(
        self,
        **kwargs,
    ) -> list[tuple[str, int, int, str]]:
        """提交自定义工作流并将全部输出下载保存到 FILES_DIR。"""
        ctx = kwargs.get("ctx", {})

        execution = await execute(
            self.workflow,
            self.base_url,
            local_paths=True,
            timeout=self.timeout,
            ctx=ctx,
            headers=self.headers,
            instance_id=self.instance_id,
        )
        print("🦄workflow execution outputs", execution.outputs)

        results = []
        for url in execution.outputs:
            image_id = generate_image_id()
            file_type = await detect_file_type_comprehensive(url, headers=self.headers)
            if file_type == "video":
                get_info_func = get_video_info_and_save
            elif file_type == "audio":
                get_info_func = get_audio_info_and_save
            else:
                get_info_func = get_image_info_and_save

            mime_type, width, height, extension = await get_info_func(
                url, os.path.join(FILES_DIR, f"{image_id}"), headers=self.headers
            )

            filename = f"{image_id}.{extension}"
            parsed_src = parse_comfy_view_url(url)
            if isinstance(ctx, dict):
                ctx.setdefault("remote_file_map", {})[filename] = parsed_src
            try:
                record_file_mapping(
                    filename,
                    source_url=url,
                    canvas_id=str(ctx.get("canvas_id") or "") if isinstance(ctx, dict) else "",
                    session_id=str(ctx.get("session_id") or "") if isinstance(ctx, dict) else "",
                    workflow_name=str(ctx.get("workflow_name") or "") if isinstance(ctx, dict) else "",
                    note="ComfyUI 自动下载映射",
                )
            except Exception:
                pass
            results.append((mime_type, width, height, filename))

        return results
