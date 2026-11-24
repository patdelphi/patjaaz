"""程序说明：提供受限图片上传、本地资产文件读取与受白名单约束的 ComfyUI object_info 代理。"""
from io import BytesIO
import os
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
import httpx
from PIL import Image, UnidentifiedImageError
from common import DEFAULT_PORT
from services.config_service import FILES_DIR, config_service
from tools.utils.image_canvas_utils import generate_file_id
from utils.http_client import HttpClient
from utils.path_security import (
    PathSecurityError,
    safe_file_id_path,
    validate_comfyui_proxy_target,
)

MAX_UPLOAD_IMAGE_BYTES = 30 * 1024 * 1024
MAX_UPLOAD_IMAGE_PIXELS = 40_000_000
ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/x-ms-bmp",
}
ALLOWED_PIL_FORMATS = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
    "TIFF": "tiff",
}

# 防止 Pillow 打开超大解压炸弹图像耗尽内存。
Image.MAX_IMAGE_PIXELS = MAX_UPLOAD_IMAGE_PIXELS

router = APIRouter(prefix="/api")
os.makedirs(FILES_DIR, exist_ok=True)


def validate_uploaded_image(
    content: bytes,
    content_type: str | None = None,
    max_bytes: int = MAX_UPLOAD_IMAGE_BYTES,
    max_pixels: int = MAX_UPLOAD_IMAGE_PIXELS,
) -> tuple[str, int, int]:
    """校验上传图片的字节大小、MIME 白名单、图像格式与像素总数，返回 (扩展名, 宽, 高)。"""
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded image exceeds limit ({max_bytes // (1024 * 1024)}MB)",
        )

    if content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime and mime != "application/octet-stream" and mime not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported image MIME type: {mime}")

    try:
        with Image.open(BytesIO(content)) as img:
            img_format = (img.format or "").upper()
            width, height = img.size
            if width <= 0 or height <= 0 or width * height > max_pixels:
                raise HTTPException(status_code=400, detail="Image pixel count exceeds allowed limit")
            if img_format not in ALLOWED_PIL_FORMATS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported image format: {img_format or 'unknown'}",
                )
            img.verify()
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {exc}") from exc

    return ALLOWED_PIL_FORMATS[img_format], width, height


@router.post("/upload_image")
async def upload_image(file: UploadFile = File(...), max_size_mb: float = 3.0):
    """上传并校验图片；超过 max_size_mb 时按比例压缩为 JPEG。"""
    file_id = generate_file_id()

    try:
        content = await file.read(MAX_UPLOAD_IMAGE_BYTES + 1)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {e}")

    extension, width, height = validate_uploaded_image(content, file.content_type)
    original_size_mb = len(content) / (1024 * 1024)

    with Image.open(BytesIO(content)) as img:
        if original_size_mb > max_size_mb:
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            compressed_content = compress_image(img, max_size_mb)
            extension = "jpg"
            file_path = os.path.join(FILES_DIR, f"{file_id}.{extension}")
            with Image.open(BytesIO(compressed_content)) as compressed_img:
                width, height = compressed_img.size
                await run_in_threadpool(
                    compressed_img.save, file_path, format="JPEG", quality=95, optimize=True
                )
        else:
            file_path = os.path.join(FILES_DIR, f"{file_id}.{extension}")
            save_format = "JPEG" if extension.lower() in ["jpg", "jpeg"] else extension.upper()
            if save_format == "JPEG" and img.mode != "RGB":
                img = img.convert("RGB")
            await run_in_threadpool(img.save, file_path, format=save_format)

    return {
        "file_id": f"{file_id}.{extension}",
        "url": f"/api/file/{file_id}.{extension}",
        "width": width,
        "height": height,
    }


def compress_image(img: Image.Image, max_size_mb: float) -> bytes:
    """将图像压缩至不超过指定 MB 大小。"""
    quality = 95
    while quality > 10:
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        if len(buffer.getvalue()) / (1024 * 1024) <= max_size_mb:
            return buffer.getvalue()
        quality -= 10

    original_width, original_height = img.size
    scale_factor = 0.8
    resized_img = img
    while scale_factor > 0.3:
        new_width = max(1, int(original_width * scale_factor))
        new_height = max(1, int(original_height * scale_factor))
        resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        resized_img.save(buffer, format="JPEG", quality=70, optimize=True)
        if len(buffer.getvalue()) / (1024 * 1024) <= max_size_mb:
            return buffer.getvalue()
        scale_factor -= 0.1

    buffer = BytesIO()
    resized_img.save(buffer, format="JPEG", quality=30, optimize=True)
    return buffer.getvalue()


@router.get("/file/{file_id}")
async def get_file(file_id: str):
    """读取 FILES_DIR 内的媒体文件，拒绝路径穿越。"""
    try:
        file_path = safe_file_id_path(FILES_DIR, file_id)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.post("/comfyui/object_info")
async def get_object_info(data: dict):
    """向已配置的 ComfyUI 实例请求 /api/object_info 并自动透传鉴权头。"""
    from services.comfy_instance_service import comfy_instance_service
    from utils.path_security import validate_comfyui_proxy_target_multi

    allowed_urls = await comfy_instance_service.get_allowed_proxy_urls()
    requested_url = data.get("url")
    try:
        target_url = validate_comfyui_proxy_target_multi(
            allowed_urls, requested_url, "/api/object_info"
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    base_target = requested_url or (allowed_urls[0] if allowed_urls else "")
    headers = await comfy_instance_service.find_headers_for_url(base_target)
    try:
        timeout = httpx.Timeout(10.0)
        async with HttpClient.create(timeout=timeout) as client:
            response = await client.get(target_url, headers=headers or None)
            if response.status_code == 200:
                return response.json()
            raise HTTPException(
                status_code=response.status_code,
                detail=f"ComfyUI server returned status {response.status_code}",
            )
    except HTTPException:
        raise
    except Exception as e:
        if "ConnectError" in str(type(e)) or "timeout" in str(e).lower():
            raise HTTPException(
                status_code=503,
                detail="ComfyUI server is not available. Please make sure ComfyUI is running.",
            )
        raise HTTPException(status_code=500, detail=f"Failed to connect to ComfyUI: {str(e)}")
