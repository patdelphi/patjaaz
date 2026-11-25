"""程序说明：维护 Jaaz 本地落盘短 ID 文件与远端 ComfyUI 输出路径及本机 Google Drive (H:) 文件的双向映射表（UTF-8 BOM + CRLF CSV）。"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from services.config_service import FILES_DIR, USER_DATA_DIR

_CSV_LOCK = threading.Lock()
MAPPING_CSV_PATH = os.path.join(USER_DATA_DIR, "file_mappings.csv")
CSV_HEADERS = [
    "created_at",
    "jaaz_filename",
    "comfy_output_relpath",
    "google_drive_path",
    "canvas_id",
    "session_id",
    "workflow_name",
    "note",
]


def resolve_drive_output_root() -> Optional[str]:
    """探测本机挂载的 Google Drive ComfyUI output 根目录（支持环境变量覆盖）。"""
    env_root = os.getenv("COMFY_DRIVE_OUTPUT_DIR", "").strip()
    if env_root and os.path.isdir(env_root):
        return env_root
    for cand in (
        r"H:\我的云端硬盘\comfyui\output",
        r"H:\My Drive\comfyui\output",
    ):
        if os.path.isdir(cand):
            return cand
    return None


def parse_comfy_view_url(url: str) -> Dict[str, str]:
    """从 ComfyUI /view?filename=...&subfolder=...&type=output URL 解析远端相对路径与本机云盘路径。"""
    try:
        parsed = urlsplit(str(url or ""))
        qs = parse_qs(parsed.query)
        fname = (qs.get("filename") or [""])[0].strip()
        sub = (qs.get("subfolder") or [""])[0].strip().strip("/\\")
        if not fname:
            return {"comfy_rel": "", "drive_path": ""}
        rel = f"{sub}/{fname}" if sub else fname
        drive_root = resolve_drive_output_root()
        drive_full = (
            os.path.normpath(os.path.join(drive_root, *rel.split("/")))
            if drive_root
            else ""
        )
        return {"comfy_rel": rel, "drive_path": drive_full}
    except Exception:
        return {"comfy_rel": "", "drive_path": ""}


def _read_existing_rows(csv_path: str) -> List[Dict[str, str]]:
    if not os.path.isfile(csv_path):
        return []
    raw = Path(csv_path).read_bytes().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    return [dict(r) for r in reader]


def _write_all_rows_utf8_bom_crlf(csv_path: str, rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS, lineterminator="\r\n")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: str(r.get(k) or "") for k in CSV_HEADERS})
    Path(csv_path).write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))


def record_file_mapping(
    jaaz_filename: str,
    *,
    source_url: str = "",
    comfy_output_relpath: str = "",
    google_drive_path: str = "",
    canvas_id: str = "",
    session_id: str = "",
    workflow_name: str = "",
    note: str = "",
    csv_path: Optional[str] = None,
) -> Dict[str, str]:
    """记录或更新单条 Jaaz 本地文件与 ComfyUI / Google Drive 文件的映射记录。"""
    target_csv = csv_path or MAPPING_CSV_PATH
    parsed = parse_comfy_view_url(source_url) if source_url else {"comfy_rel": "", "drive_path": ""}
    rel = comfy_output_relpath or parsed["comfy_rel"]
    drv = google_drive_path or parsed["drive_path"]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry = {
        "created_at": now_str,
        "jaaz_filename": jaaz_filename,
        "comfy_output_relpath": rel,
        "google_drive_path": drv,
        "canvas_id": canvas_id,
        "session_id": session_id,
        "workflow_name": workflow_name,
        "note": note,
    }
    with _CSV_LOCK:
        rows = _read_existing_rows(target_csv)
        updated = False
        for idx, existing in enumerate(rows):
            if existing.get("jaaz_filename") == jaaz_filename:
                merged = {
                    k: entry[k] if entry[k] else str(existing.get(k) or "")
                    for k in CSV_HEADERS
                }
                rows[idx] = merged
                entry = merged
                updated = True
                break
        if not updated:
            rows.append(entry)
        _write_all_rows_utf8_bom_crlf(target_csv, rows)
    return entry


def list_file_mappings(csv_path: Optional[str] = None) -> List[Dict[str, str]]:
    """读取全部文件映射记录（按时间倒序）。"""
    target_csv = csv_path or MAPPING_CSV_PATH
    with _CSV_LOCK:
        rows = _read_existing_rows(target_csv)
    return list(reversed(rows))


def _sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with fp.open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def backfill_historical_mappings(
    files_dir: Optional[str] = None,
    drive_root: Optional[str] = None,
    csv_path: Optional[str] = None,
) -> Dict[str, int]:
    """扫描现有 Jaaz 本地文件与 H: 云盘 output 目录，按二进制 SHA-256（视频/音频）及像素尺寸+相邻时间戳（PNG重压缩）一次性补全历史映射表。"""
    active_files = Path(files_dir or FILES_DIR)
    active_drive_str = drive_root or resolve_drive_output_root()
    target_csv = csv_path or MAPPING_CSV_PATH
    if not active_files.is_dir():
        return {"total": 0, "matched_drive": 0, "local_only": 0}

    drive_by_size: Dict[int, List[Path]] = {}
    drive_pngs: List[tuple[Path, float, tuple[int, int]]] = []
    if active_drive_str and os.path.isdir(active_drive_str):
        droot = Path(active_drive_str)
        for root, _, fns in os.walk(droot):
            for fn in fns:
                fp = Path(root) / fn
                try:
                    st = fp.stat()
                    drive_by_size.setdefault(st.st_size, []).append(fp)
                    if fp.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        with Image.open(fp) as im:
                            drive_pngs.append((fp, st.st_mtime, im.size))
                except Exception:
                    continue

    existing_map = {r.get("jaaz_filename", ""): r for r in _read_existing_rows(target_csv)}
    matched_cnt = 0
    local_cnt = 0

    for jf in sorted(active_files.iterdir(), key=lambda p: p.stat().st_mtime):
        if not jf.is_file() or jf.name.startswith("."):
            continue
        if jf.name in existing_map and existing_map[jf.name].get("google_drive_path"):
            matched_cnt += 1
            continue

        st = jf.stat()
        created_ts = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        matched_fp: Optional[Path] = None
        note = ""

        if jf.name.startswith("composed_"):
            note = "Jaaz 本机内置 FFmpeg 剪辑拼接生成"
        elif jf.name.startswith("mask_"):
            note = "Jaaz 画布局部重绘遮罩文件"
        else:
            # 1. 优先精确匹配字节大小 + SHA-256（视频/原图）
            cands = drive_by_size.get(st.st_size, [])
            if cands:
                j_sha = _sha256_file(jf)
                for c in cands:
                    if _sha256_file(c) == j_sha:
                        matched_fp = c
                        note = "SHA-256 精确匹配"
                        break
            # 2. PNG 落盘经 PIL 保存可能重压缩导致体积微变，按相同像素尺寸 + 下载时间紧随其后（0~90s）匹配
            if matched_fp is None and jf.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and drive_pngs:
                try:
                    with Image.open(jf) as jim:
                        jsize = jim.size
                    best_dt = 91.0
                    for dp, dmtime, dsize in drive_pngs:
                        dt = st.st_mtime - dmtime
                        if dsize == jsize and -5.0 <= dt <= best_dt:
                            best_dt = dt
                            matched_fp = dp
                            note = f"同尺寸({jsize[0]}x{jsize[1]})+时间戳匹配(Δ{dt:.1f}s)"
                except Exception:
                    pass

        rel_str = ""
        drv_str = ""
        if matched_fp is not None and active_drive_str:
            drv_str = str(matched_fp)
            rel_str = matched_fp.relative_to(Path(active_drive_str)).as_posix()
            matched_cnt += 1
        else:
            local_cnt += 1
            if not note:
                note = "本地上传或云盘未同步"

        row_item = record_file_mapping(
            jf.name,
            comfy_output_relpath=rel_str,
            google_drive_path=drv_str,
            note=note,
            csv_path=target_csv,
        )
        # 保留文件真实落盘时间
        with _CSV_LOCK:
            all_rows = _read_existing_rows(target_csv)
            for r in all_rows:
                if r.get("jaaz_filename") == jf.name:
                    r["created_at"] = created_ts
            _write_all_rows_utf8_bom_crlf(target_csv, all_rows)
        _ = row_item

    return {
        "total": matched_cnt + local_cnt,
        "matched_drive": matched_cnt,
        "local_only": local_cnt,
    }
