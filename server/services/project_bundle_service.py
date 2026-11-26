"""程序说明：短片制片工程包一键归档导出服务（打包 canvas.json、UTF-8 BOM+CRLF 制片单、云盘映射 CSV、SRT 字幕与关联媒体为 ZIP，P6-4）。"""
from __future__ import annotations

import csv
from datetime import datetime
import io
import json
import os
import re
from typing import Any, Dict, List, Optional
import zipfile

from services.config_service import FILES_DIR
from services.db_service import DatabaseService, db_service
from services.file_mapping_service import CSV_HEADERS, list_file_mappings
from services.video_finishing_service import build_srt_content
from utils.path_security import safe_file_id_path

_API_FILE_RE = re.compile(r"/api/file/([A-Za-z0-9._-]+)")
_SAFE_ARCHIVE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utf8_bom_crlf_bytes(text: str) -> bytes:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    return b"\xef\xbb\xbf" + normalized.encode("utf-8")


def _collect_canvas_assets_and_texts(canvas_data: Dict[str, Any]) -> Dict[str, Any]:
    """提取画布内的有效分镜框、脚本文字卡与媒体元素及完整血缘信息。"""
    elements = canvas_data.get("elements") if isinstance(canvas_data.get("elements"), list) else []
    files_map = canvas_data.get("files") if isinstance(canvas_data.get("files"), dict) else {}

    frames: List[str] = []
    text_cards: List[str] = []
    media_items: List[Dict[str, Any]] = []
    seen_files: List[str] = []

    for el in elements:
        if not isinstance(el, dict) or el.get("isDeleted"):
            continue
        etype = str(el.get("type") or "")
        if etype == "frame":
            nm = str(el.get("name") or "").strip()
            if nm:
                frames.append(nm)
            continue
        if etype == "text":
            txt = str(el.get("text") or "").strip()
            if txt:
                text_cards.append(txt)
            continue

        fid = str(el.get("fileId") or "")
        fentry = files_map.get(fid) if fid else None
        raw_url = str((fentry or {}).get("dataURL") or el.get("link") or "")
        m = _API_FILE_RE.search(raw_url)
        if not m:
            continue
        filename = m.group(1)
        if filename not in seen_files:
            seen_files.append(filename)

        cd = el.get("customData") if isinstance(el.get("customData"), dict) else {}
        lineage = cd.get("jaazLineage") if isinstance(cd.get("jaazLineage"), dict) else {}
        media_items.append(
            {
                "element_id": str(el.get("id") or ""),
                "filename": filename,
                "type": etype,
                "width": int(el.get("width") or 0),
                "height": int(el.get("height") or 0),
                "workflow_name": str(lineage.get("workflowName") or cd.get("workflowName") or ""),
                "capability": str(lineage.get("capability") or ""),
                "prompt": str(lineage.get("prompt") or ""),
                "parent_files": list(lineage.get("parentFileIds") or cd.get("parentFileIds") or []),
                "params": lineage.get("params") if isinstance(lineage.get("params"), dict) else {},
            }
        )
        for p_fn in media_items[-1]["parent_files"]:
            if isinstance(p_fn, str) and p_fn.strip() and p_fn not in seen_files:
                seen_files.append(p_fn.strip())

    return {
        "frames": frames,
        "text_cards": text_cards,
        "media_items": media_items,
        "referenced_files": seen_files,
    }


def _build_production_sheet_markdown(
    canvas_id: str,
    canvas_name: str,
    summary: Dict[str, Any],
) -> str:
    """生成 UTF-8 Markdown 制片清单，记录分镜结构与全部媒体的生成血缘。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        f"# 《{canvas_name or canvas_id}》制片工程归档单",
        "",
        f"- **画布 ID**：`{canvas_id}`",
        f"- **导出时间**：{now_str}",
        f"- **分镜画框数**：{len(summary['frames'])}",
        f"- **媒体资产数**：{len(summary['media_items'])}",
        "",
    ]

    if summary["frames"]:
        lines.append("## 1. 分镜泳道与篇章结构")
        lines.append("")
        for idx, fnm in enumerate(summary["frames"], 1):
            lines.append(f"{idx}. {fnm}")
        lines.append("")

    if summary["text_cards"]:
        lines.append("## 2. 画布脚本与批注文本")
        lines.append("")
        for idx, txt in enumerate(summary["text_cards"][:40], 1):
            single = " / ".join(s.strip() for s in txt.splitlines() if s.strip())
            lines.append(f"- **文本 #{idx}**：{single[:300]}")
        lines.append("")

    lines.append("## 3. 媒体资产与生成血缘明细")
    lines.append("")
    if not summary["media_items"]:
        lines.append("（当前画布暂无绑定媒体资产）")
    else:
        for idx, item in enumerate(summary["media_items"], 1):
            parents = ", ".join(item["parent_files"]) if item["parent_files"] else "无"
            params_json = json.dumps(item["params"], ensure_ascii=False) if item["params"] else "{}"
            lines.extend(
                [
                    f"### 3.{idx} `{item['filename']}`",
                    f"- **工作流**：`{item['workflow_name'] or 'upload/manual'}`（能力：`{item['capability'] or item['type']}`）",
                    f"- **画布尺寸**：`{item['width']} × {item['height']}`",
                    f"- **上游父资产**：`{parents}`",
                    f"- **关键参数**：`{params_json}`",
                    f"- **提示词**：{item['prompt'] or '—'}",
                    "",
                ]
            )
    return "\n".join(lines)


async def build_canvas_project_bundle_zip(
    canvas_id: str,
    *,
    include_media: bool = True,
    files_dir: Optional[str] = None,
    db: Optional[DatabaseService] = None,
    csv_path: Optional[str] = None,
) -> Dict[str, Any]:
    """将指定画布的场景 JSON、制片血缘单、云盘映射表、字幕草案与本地媒体打包为内存或临时文件 ZIP。"""
    active_db = db or db_service
    active_files_dir = files_dir or FILES_DIR

    canvas_record = await active_db.get_canvas_data(canvas_id)
    if canvas_record is None:
        raise FileNotFoundError(f"画布不存在: {canvas_id}")

    all_canvases = await active_db.list_canvases()
    canvas_name = canvas_id
    for c in all_canvases:
        if str(c.get("id") or "") == canvas_id:
            canvas_name = str(c.get("name") or canvas_id)
            break

    data = canvas_record.get("data") or {}
    summary = _collect_canvas_assets_and_texts(data)
    sheet_md = _build_production_sheet_markdown(canvas_id, canvas_name, summary)

    # 筛选与本画布相关的云盘映射行
    all_mappings = list_file_mappings(csv_path)
    ref_set = set(summary["referenced_files"])
    matched_rows = [
        r
        for r in all_mappings
        if r.get("canvas_id") == canvas_id or r.get("jaaz_filename") in ref_set
    ]
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=CSV_HEADERS, lineterminator="\r\n")
    writer.writeheader()
    for row in matched_rows:
        writer.writerow({k: str(row.get(k) or "") for k in CSV_HEADERS})

    # 若画布包含文本卡片，自动按 4 秒一段生成可编辑的 SRT 字幕草稿模板
    srt_entries = [
        {
            "start": idx * 4.0,
            "end": (idx + 1) * 4.0,
            "text": " ".join(t.splitlines()).strip()[:80],
        }
        for idx, t in enumerate(summary["text_cards"][:30])
        if t.strip()
    ]
    srt_content = build_srt_content(srt_entries) if srt_entries else ""

    safe_prefix = _SAFE_ARCHIVE_ID_RE.sub("_", canvas_id).strip("_") or "canvas"
    zip_filename = f"jaaz_bundle_{safe_prefix}.zip"
    zip_buffer = io.BytesIO()
    packaged_media: List[str] = []

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "canvas.json",
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        zf.writestr("production_sheet.md", _utf8_bom_crlf_bytes(sheet_md))
        zf.writestr(
            "file_mappings.csv",
            b"\xef\xbb\xbf" + csv_buf.getvalue().encode("utf-8"),
        )
        if srt_content:
            zf.writestr("subtitles_draft.srt", _utf8_bom_crlf_bytes(srt_content))

        if include_media:
            for fn in summary["referenced_files"]:
                try:
                    m_path = safe_file_id_path(active_files_dir, fn)
                except Exception:
                    continue
                if os.path.isfile(m_path):
                    zf.write(m_path, arcname=f"media/{fn}")
                    packaged_media.append(fn)

    zip_bytes = zip_buffer.getvalue()
    return {
        "filename": zip_filename,
        "zip_bytes": zip_bytes,
        "size_bytes": len(zip_bytes),
        "media_count": len(packaged_media),
        "packaged_media": packaged_media,
    }
