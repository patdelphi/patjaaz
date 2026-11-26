"""程序说明：画布媒体离线完整性与血缘/云盘映射覆盖率健康巡检服务（P8-3）。"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from services.config_service import FILES_DIR
from services.db_service import DatabaseService, db_service
from services.file_mapping_service import list_file_mappings
from utils.path_security import safe_file_id_path

_API_FILE_RE = re.compile(r"/api/file/([A-Za-z0-9._-]+)")


async def inspect_canvas_media_health(
    canvas_id: str,
    *,
    files_dir: Optional[str] = None,
    db: Optional[DatabaseService] = None,
    csv_path: Optional[str] = None,
) -> Dict[str, Any]:
    """核验指定画布全部图像、视频、音频元素的本地文件存在性、字节体积、血缘完整性与云盘映射状态。"""
    active_db = db or db_service
    active_files_dir = files_dir or FILES_DIR

    record = await active_db.get_canvas_data(canvas_id)
    if record is None:
        raise FileNotFoundError(f"画布不存在: {canvas_id}")

    data = record.get("data") or {}
    elements = data.get("elements") if isinstance(data.get("elements"), list) else []
    files_map = data.get("files") if isinstance(data.get("files"), dict) else {}
    mappings_by_name = {
        r.get("jaaz_filename", ""): r for r in list_file_mappings(csv_path)
    }

    present_files: List[Dict[str, Any]] = []
    missing_files: List[Dict[str, Any]] = []
    seen_filenames: set[str] = set()
    lineage_count = 0
    drive_mapped_count = 0
    total_bytes = 0

    for el in elements:
        if not isinstance(el, dict) or el.get("isDeleted"):
            continue
        etype = str(el.get("type") or "")
        if etype not in ("image", "video", "audio", "embeddable"):
            continue

        fid = str(el.get("fileId") or "")
        fentry = files_map.get(fid) if fid else None
        raw_url = str((fentry or {}).get("dataURL") or el.get("link") or "")
        m = _API_FILE_RE.search(raw_url)
        if not m:
            continue
        fname = m.group(1)
        if fname in seen_filenames:
            continue
        seen_filenames.add(fname)

        cd = el.get("customData") if isinstance(el.get("customData"), dict) else {}
        has_lineage = isinstance(cd.get("jaazLineage"), dict) or bool(cd.get("workflowName"))
        if has_lineage:
            lineage_count += 1

        mrow = mappings_by_name.get(fname) or {}
        has_drive = bool(str(mrow.get("google_drive_path") or "").strip())
        if has_drive:
            drive_mapped_count += 1

        try:
            fpath = safe_file_id_path(active_files_dir, fname)
            exists = os.path.isfile(fpath)
        except Exception:
            fpath = ""
            exists = False

        if exists:
            sz = int(os.path.getsize(fpath))
            total_bytes += sz
            present_files.append(
                {
                    "filename": fname,
                    "element_id": str(el.get("id") or ""),
                    "size_bytes": sz,
                    "has_lineage": has_lineage,
                    "has_drive_mapping": has_drive,
                }
            )
        else:
            missing_files.append(
                {
                    "filename": fname,
                    "element_id": str(el.get("id") or ""),
                    "drive_fallback": str(mrow.get("google_drive_path") or ""),
                }
            )

    total_media = len(present_files) + len(missing_files)
    return {
        "canvas_id": canvas_id,
        "healthy": len(missing_files) == 0,
        "total_media_elements": total_media,
        "present_count": len(present_files),
        "missing_count": len(missing_files),
        "lineage_covered_count": lineage_count,
        "drive_mapped_count": drive_mapped_count,
        "total_media_bytes": total_bytes,
        "missing_files": missing_files,
        "present_files": present_files,
    }
