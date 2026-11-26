"""程序说明：将画布涂抹生成的 RGBA 透明通道遮罩（mask）合成为带半透明红框与高亮蒙版的视觉引导图（<Picture 2>），打通无遮罩槽大模型（SenseNova U1.6 / MiniMax H3 Image）局部精准重绘闭环（P7-2）。"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageDraw

from services.config_service import FILES_DIR
from services.file_mapping_service import record_file_mapping
from services.video_compose_service import _clean_media_ref
from tools.utils.image_canvas_utils import generate_file_id
from utils.path_security import safe_file_id_path


def _describe_bbox_region(
    bbox: Tuple[int, int, int, int], width: int, height: int
) -> Dict[str, Any]:
    """计算遮罩外接矩形的百分比坐标与中文九宫格方位描述。"""
    x0, y0, x1, y1 = bbox
    cx = ((x0 + x1) / 2.0) / max(1, width)
    cy = ((y0 + y1) / 2.0) / max(1, height)

    h_pos = "左侧" if cx < 0.36 else ("右侧" if cx > 0.64 else "水平居中")
    v_pos = "上方" if cy < 0.36 else ("下方" if cy > 0.64 else "垂直居中")
    pos_label = "画面中央" if (h_pos == "水平居中" and v_pos == "垂直居中") else f"{v_pos}{h_pos}"

    return {
        "bbox_px": [int(x0), int(y0), int(x1), int(y1)],
        "x_pct": [round(x0 * 100.0 / max(1, width), 1), round(x1 * 100.0 / max(1, width), 1)],
        "y_pct": [round(y0 * 100.0 / max(1, height), 1), round(y1 * 100.0 / max(1, height), 1)],
        "region_label": pos_label,
    }


def _extract_painted_binary_mask(mask_im: Image.Image, target_size: Tuple[int, int]) -> Image.Image:
    """从透明挖空遮罩（alpha<200 为涂抹区）或黑白遮罩提取单通道 L 选区（255=待重绘，0=保持不变）。"""
    resized = mask_im.resize(target_size, Image.Resampling.NEAREST)
    if "A" in resized.getbands():
        alpha = resized.getchannel("A")
        alpha_extrema = alpha.getextrema()
        # CanvasImageTools 导出的遮罩将涂抹处设为 alpha=0，未涂抹处 alpha=255
        if alpha_extrema and alpha_extrema[0] < 200 and alpha_extrema[1] > 200:
            return alpha.point(lambda a: 255 if a < 200 else 0)

    gray = resized.convert("L")
    return gray.point(lambda v: 255 if v > 127 else 0)


def build_visual_mask_guide_sync(
    source_image: str,
    mask_image: str,
    *,
    files_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """读取原图与遮罩图，生成叠绘半透明亮红色涂抹区及外接红框的视觉引导 PNG。"""
    active_files_dir = files_dir or FILES_DIR
    clean_src = _clean_media_ref(source_image)
    clean_mask = _clean_media_ref(mask_image)

    src_path = safe_file_id_path(active_files_dir, clean_src)
    mask_path = safe_file_id_path(active_files_dir, clean_mask)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"原图文件不存在: {clean_src}")
    if not os.path.isfile(mask_path):
        raise FileNotFoundError(f"遮罩文件不存在: {clean_mask}")

    with Image.open(src_path) as src_raw, Image.open(mask_path) as mask_raw:
        base_rgba = src_raw.convert("RGBA")
        width, height = base_rgba.size
        sel_l = _extract_painted_binary_mask(mask_raw, (width, height))
        bbox = sel_l.getbbox()
        if bbox is None:
            raise ValueError("遮罩图中未检测到有效涂抹选区")

        # 合成半透明鲜红涂抹层 + 4px 红色外接框，供 SenseNova / MiniMax H3 视觉编码器精准定位
        red_fill = Image.new("RGBA", (width, height), (239, 68, 68, 112))
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        overlay.paste(red_fill, (0, 0), mask=sel_l)

        composited = Image.alpha_composite(base_rgba, overlay)
        draw = ImageDraw.Draw(composited)
        pad = max(2, min(width, height) // 160)
        bx0 = max(0, bbox[0] - pad)
        by0 = max(0, bbox[1] - pad)
        bx1 = min(width - 1, bbox[2] + pad)
        by1 = min(height - 1, bbox[3] + pad)
        stroke_w = max(3, min(width, height) // 200)
        draw.rectangle([bx0, by0, bx1, by1], outline=(220, 38, 38, 255), width=stroke_w)

        out_filename = f"guide_{generate_file_id()}.png"
        out_path = os.path.join(active_files_dir, out_filename)
        composited.convert("RGB").save(out_path, format="PNG")

    region_info = _describe_bbox_region(bbox, width, height)
    record_file_mapping(
        out_filename,
        workflow_name="prepare_visual_mask_guide",
        note=f"局部重绘视觉引导图 <- 原图 {clean_src} + 遮罩 {clean_mask}",
    )

    return {
        "guide_file_id": out_filename,
        "guide_url": f"/api/file/{out_filename}",
        "source_file_id": clean_src,
        "mask_file_id": clean_mask,
        "width": width,
        "height": height,
        **region_info,
    }


async def prepare_visual_mask_guide(
    source_image: str,
    mask_image: str,
    *,
    files_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """异步包装视觉引导遮罩合成函数。"""
    return await asyncio.to_thread(
        build_visual_mask_guide_sync,
        source_image,
        mask_image,
        files_dir=files_dir,
    )
