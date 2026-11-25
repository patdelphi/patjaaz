"""程序说明：提取当前画布上的文字框脚本、画框结构、形状组合及已有图像/视频文件引用，供对话智能体直接感知画布上下文。"""
from typing import Any, Dict, List, Optional

MAX_TEXT_ITEMS = 20
MAX_TEXT_CHARS = 500
MAX_MEDIA_ITEMS = 20


def _extract_filename_from_url(url_value: Any) -> str:
    """从 /api/file/xxx.ext URL 中提取真实文件名。"""
    raw = str(url_value or "").strip()
    if "/api/file/" in raw:
        return raw.split("/api/file/", 1)[1].split("?", 1)[0].strip()
    return ""


def _extract_filename_from_file_entry(file_entry: Any) -> str:
    """从画布 files 字典项的 dataURL (/api/file/xxx.png) 中提取真实文件名。"""
    if not isinstance(file_entry, dict):
        return ""
    return _extract_filename_from_url(file_entry.get("dataURL"))


def build_canvas_scene_context(canvas_data: Optional[Dict[str, Any]]) -> str:
    """将画布当前可见元素整理为紧凑上下文片段，支持直接按画布文字框脚本生图/生视频及按序引用已有作品。"""
    if not isinstance(canvas_data, dict):
        return ""
    raw_elements = canvas_data.get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        return ""
    files_map = canvas_data.get("files") if isinstance(canvas_data.get("files"), dict) else {}

    active = [
        e for e in raw_elements if isinstance(e, dict) and not e.get("isDeleted")
    ]
    if not active:
        return ""

    by_id: Dict[str, Dict[str, Any]] = {
        str(e.get("id")): e for e in active if e.get("id")
    }

    text_lines: List[str] = []
    frame_lines: List[str] = []
    media_lines: List[str] = []
    shape_counts: Dict[str, int] = {}

    sorted_active = sorted(
        active,
        key=lambda e: (float(e.get("y") or 0), float(e.get("x") or 0)),
    )

    for elem in sorted_active:
        etype = str(elem.get("type") or "")
        x = round(float(elem.get("x") or 0))
        y = round(float(elem.get("y") or 0))
        w = round(float(elem.get("width") or 0))
        h = round(float(elem.get("height") or 0))

        if etype == "text":
            txt = str(elem.get("text") or elem.get("originalText") or "").strip()
            if not txt or len(text_lines) >= MAX_TEXT_ITEMS:
                continue
            if len(txt) > MAX_TEXT_CHARS:
                txt = txt[:MAX_TEXT_CHARS] + "…"
            container_id = str(elem.get("containerId") or "")
            container = by_id.get(container_id) if container_id else None
            prefix = (
                f"图形({container.get('type')})内文字"
                if container is not None
                else "文字框"
            )
            frame_id = str(elem.get("frameId") or (container or {}).get("frameId") or "")
            frame_obj = by_id.get(frame_id) if frame_id else None
            frame_tag = (
                f" [所属画框: {frame_obj.get('name') or frame_id}]"
                if frame_obj is not None
                else ""
            )
            escaped = txt.replace("\n", " / ")
            text_lines.append(
                f"- {prefix}#{len(text_lines) + 1}{frame_tag} @(x={x}, y={y}): \"{escaped}\""
            )
        elif etype == "frame":
            fname = str(elem.get("name") or elem.get("id") or "Frame")
            frame_lines.append(f"- 画框 \"{fname}\" @(x={x}, y={y}, {w}×{h})")
        elif etype in ("image", "video", "audio", "embeddable"):
            if len(media_lines) >= MAX_MEDIA_ITEMS:
                continue
            fid = str(elem.get("fileId") or elem.get("id") or "")
            real_name = _extract_filename_from_file_entry(files_map.get(fid)) or _extract_filename_from_url(elem.get("link"))
            if not real_name:
                continue
            lower_name = real_name.lower()
            if etype == "image":
                kind_cn = "图像"
            elif etype == "audio" or lower_name.endswith((".mp3", ".wav", ".flac", ".m4a", ".aac")):
                kind_cn = "音频"
            else:
                kind_cn = "视频"
            media_lines.append(
                f"- 画布{kind_cn}#{len(media_lines) + 1}: file_id=\"{real_name}\" ({w}×{h}, @(x={x}, y={y}))"
            )
        else:
            custom = elem.get("customData") if isinstance(elem.get("customData"), dict) else {}
            if custom.get("jaazType") == "blockArrow":
                label = f"blockArrow({custom.get('variant', 'straight')})"
            else:
                label = etype or "shape"
            shape_counts[label] = shape_counts.get(label, 0) + 1

    sections: List[str] = []
    if frame_lines:
        sections.append("画框区域:\n" + "\n".join(frame_lines))
    if shape_counts:
        summary = ", ".join(f"{k}×{v}" for k, v in sorted(shape_counts.items()))
        sections.append(f"画布图形元素统计: {summary}")
    if text_lines:
        sections.append("画布上的文字框/脚本内容（按从上到下、从左到右排序）:\n" + "\n".join(text_lines))
    if media_lines:
        sections.append("画布上已有的图像/视频作品（可直接将其 file_id 传入编辑或图生视频工具）:\n" + "\n".join(media_lines))

    if not sections:
        return ""

    return (
        "\n\n<canvas_scene_context>\n"
        "以下为当前画布上的实时内容摘要。当用户提到画布上的文字框、分镜脚本、标题、图形布局或已有图片/视频（即使未附带 <input_images> 标签）时，"
        "请直接读取下方对应的文字脚本与真实 file_id 进行规划、生成或持续修改：\n"
        + "\n\n".join(sections)
        + "\n</canvas_scene_context>\n"
    )
