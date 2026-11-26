"""程序说明：扫描并显式二次确认清理未绑定任何画布、聊天记录或进行中任务的孤立临时切片与媒体文件（P5-5）。"""
from __future__ import annotations

from datetime import datetime
import os
import re
from typing import Any, Dict, List, Optional, Set

from services.config_service import FILES_DIR, USER_DATA_DIR
from services.db_service import DatabaseService, db_service
from services.long_video_pipeline_service import list_upscale_jobs
from utils.path_security import safe_file_id_path

_TEMP_SLICE_PREFIXES = ("src_slice_", "tmp_slice_", "chunk_tmp_")
_API_FILE_REF_RE = re.compile(r"/api/file/([A-Za-z0-9._-]+)")


def _extract_filenames_from_canvas_payload(data: Any) -> Set[str]:
    """收集单个画布 JSON 中所有元素（含已软删除可撤销元素）与血缘关联引用的文件名集合。"""
    referenced: Set[str] = set()
    if not isinstance(data, dict):
        return referenced

    files_map = data.get("files")
    if isinstance(files_map, dict):
        for fentry in files_map.values():
            if not isinstance(fentry, dict):
                continue
            durl = str(fentry.get("dataURL") or "")
            for m in _API_FILE_REF_RE.findall(durl):
                referenced.add(m)

    elements = data.get("elements")
    if isinstance(elements, list):
        for el in elements:
            if not isinstance(el, dict):
                continue
            link = str(el.get("link") or "")
            for m in _API_FILE_REF_RE.findall(link):
                referenced.add(m)
            cd = el.get("customData")
            if isinstance(cd, dict):
                for pid in cd.get("parentFileIds") or []:
                    if isinstance(pid, str) and pid.strip():
                        referenced.add(pid.strip().split("/")[-1])
                lineage = cd.get("jaazLineage")
                if isinstance(lineage, dict):
                    for pid in lineage.get("parentFileIds") or []:
                        if isinstance(pid, str) and pid.strip():
                            referenced.add(pid.strip().split("/")[-1])
    return referenced


async def collect_all_referenced_media_filenames(
    db: Optional[DatabaseService] = None,
    jobs_dir: Optional[str] = None,
) -> Set[str]:
    """跨全量 SQLite 画布数据与未完成的分块超分任务收集所有受保护文件名。"""
    active_db = db or db_service
    referenced: Set[str] = set()

    canvases = await active_db.list_canvases()
    for cv in canvases:
        cid = str(cv.get("id") or "")
        if not cid:
            continue
        detail = await active_db.get_canvas_data(cid)
        data = (detail or {}).get("data") or {}
        referenced.update(_extract_filenames_from_canvas_payload(data))

    active_jobs_dir = jobs_dir or os.path.join(USER_DATA_DIR, "upscale_jobs")
    for job in list_upscale_jobs(active_jobs_dir):
        src = str(job.get("source_video") or "").strip()
        out = str(job.get("output_file") or "").strip()
        if src:
            referenced.add(src)
        if out:
            referenced.add(out)

    return referenced


async def scan_orphan_media_files(
    *,
    files_dir: Optional[str] = None,
    db: Optional[DatabaseService] = None,
    jobs_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """只读扫描 files_dir 中未被任何画布或任务引用的孤立文件，优先标注临时切片文件。"""
    active_files_dir = files_dir or FILES_DIR
    if not os.path.isdir(active_files_dir):
        return {
            "total_files_scanned": 0,
            "referenced_count": 0,
            "orphan_count": 0,
            "orphan_total_bytes": 0,
            "orphans": [],
        }

    referenced = await collect_all_referenced_media_filenames(db=db, jobs_dir=jobs_dir)
    orphans: List[Dict[str, Any]] = []
    total_scanned = 0
    referenced_present = 0

    for fname in os.listdir(active_files_dir):
        if fname.startswith("."):
            continue
        full_p = os.path.join(active_files_dir, fname)
        if not os.path.isfile(full_p):
            continue
        total_scanned += 1
        if fname in referenced:
            referenced_present += 1
            continue

        st = os.stat(full_p)
        is_temp_slice = fname.lower().startswith(_TEMP_SLICE_PREFIXES)
        orphans.append(
            {
                "filename": fname,
                "category": "temp_slice" if is_temp_slice else "unreferenced_media",
                "size_bytes": int(st.st_size),
                "modified_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "url": f"/api/file/{fname}",
            }
        )

    # 临时切片排在最前，其余按修改时间倒序
    orphans.sort(
        key=lambda item: (0 if item["category"] == "temp_slice" else 1, item["filename"])
    )
    orphan_bytes = sum(item["size_bytes"] for item in orphans)

    return {
        "total_files_scanned": total_scanned,
        "referenced_count": referenced_present,
        "orphan_count": len(orphans),
        "orphan_total_bytes": orphan_bytes,
        "orphans": orphans,
    }


async def delete_confirmed_orphan_files(
    filenames: List[str],
    *,
    confirm: bool = False,
    files_dir: Optional[str] = None,
    db: Optional[DatabaseService] = None,
    jobs_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """在显式 confirm=True 且二次核验零画布引用的前提下，安全清理用户勾选的孤立文件。"""
    if confirm is not True:
        raise ValueError("删除操作必须显式传入 confirm=true 二次确认")

    active_files_dir = files_dir or FILES_DIR
    scan_res = await scan_orphan_media_files(
        files_dir=active_files_dir, db=db, jobs_dir=jobs_dir
    )
    allowed_orphans = {item["filename"] for item in scan_res["orphans"]}

    deleted: List[str] = []
    skipped_referenced: List[str] = []
    missing: List[str] = []
    freed_bytes = 0

    for raw_name in filenames or []:
        clean_name = str(raw_name or "").strip()
        if not clean_name:
            continue
        target_path = safe_file_id_path(active_files_dir, clean_name)
        if clean_name not in allowed_orphans:
            skipped_referenced.append(clean_name)
            continue
        if not os.path.isfile(target_path):
            missing.append(clean_name)
            continue
        sz = os.path.getsize(target_path)
        os.remove(target_path)
        deleted.append(clean_name)
        freed_bytes += int(sz)

    return {
        "deleted": deleted,
        "deleted_count": len(deleted),
        "freed_bytes": freed_bytes,
        "skipped_referenced": skipped_referenced,
        "missing": missing,
    }
