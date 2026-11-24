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
from tools.video_generation.video_canvas_utils import get_video_info_and_save
from utils.http_client import HttpClient
from .image_utils import generate_image_id, get_image_info_and_save

AUDIO_FORMATS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac")


async def detect_file_type_comprehensive(url: str) -> str:
    """综合通过 Content-Type 与扩展名判断 ComfyUI 输出媒体类型（image/video/audio）。"""
    lower_url = url.lower()
    try:
        async with HttpClient.create() as client:
            response = await client.head(url)
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
    url: str, file_path_without_extension: str
) -> tuple[str, int, int, str]:
    """下载并保存 ComfyUI 输出的音频文件。"""
    ext = "wav"
    lower_url = url.lower()
    for candidate in AUDIO_FORMATS:
        if candidate in lower_url:
            ext = candidate.lstrip(".")
            break

    async with HttpClient.create_aiohttp() as session:
        async with session.get(url) as response:
            audio_content = await response.read()

    out_path = f"{file_path_without_extension}.{ext}"
    async with aiofiles.open(out_path, "wb") as out_file:
        await out_file.write(audio_content)
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


class ComfyUIWorkflowRunner:
    """通用动态 ComfyUI 工作流运行器，支持图片、视频与音频输出落盘。"""

    def __init__(self, workflow_dict: dict, base_url: str):
        self.workflow = workflow_dict
        self.base_url = base_url

    async def generate(
        self,
        **kwargs,
    ) -> list[tuple[str, int, int, str]]:
        """提交自定义工作流并将全部输出下载保存到 FILES_DIR。"""
        ctx = kwargs.get("ctx", {})

        execution = await execute(
            self.workflow, self.base_url, local_paths=True, ctx=ctx
        )
        print("🦄workflow execution outputs", execution.outputs)

        results = []
        for url in execution.outputs:
            image_id = generate_image_id()
            file_type = await detect_file_type_comprehensive(url)
            if file_type == "video":
                get_info_func = get_video_info_and_save
            elif file_type == "audio":
                get_info_func = get_audio_info_and_save
            else:
                get_info_func = get_image_info_and_save

            mime_type, width, height, extension = await get_info_func(
                url, os.path.join(FILES_DIR, f"{image_id}")
            )

            filename = f"{image_id}.{extension}"
            results.append((mime_type, width, height, filename))

        return results
