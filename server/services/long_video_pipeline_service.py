"""程序说明：分钟级长片生产流水线服务，提供内置 FFmpeg 视频关键帧/尾帧提取接力（P5-2）与按内存自动分块断点超分合流（P5-1）。"""
from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import subprocess
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from PIL import Image

from services.comfy_instance_service import comfy_instance_service
from services.config_service import FILES_DIR
from services.db_service import db_service
from services.file_mapping_service import record_file_mapping
from services.gpu_compatibility_guard import (
    compute_safe_upscale_slice_sec,
    ensure_fresh_instance_health,
)
from services.upscale_job_store import (
    UPSCALE_JOBS_DIR,
    build_upscale_job_id as _build_job_id,
    default_seedvr2_chunk_upscaler as _default_seedvr2_chunk_upscaler,
    get_upscale_job,
    is_transient_offline_error as _is_transient_offline_error,
    list_upscale_jobs,
    save_upscale_job_state as _save_job_state,
)
from services.video_compose_service import (
    _clean_media_ref,
    probe_video_clip_info,
    resolve_ffmpeg_binary,
)
from services.websocket_service import broadcast_session_update
from tools.utils.image_canvas_utils import generate_file_id, generate_new_image_element
from tools.video_generation.video_canvas_utils import generate_new_video_element
from utils.canvas_lock import canvas_lock_manager
from utils.log_sanitizer import get_sanitized_logger
from utils.path_security import safe_file_id_path

_logger = get_sanitized_logger(__name__)


async def extract_video_anchor_frame(
    video_file: str,
    *,
    mode: str = "last",
    timestamp_sec: float = 0.0,
    place_on_canvas: bool = True,
    canvas_id: str = "",
    session_id: str = "",
    files_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """使用内置 ffmpeg 提取视频首帧、尾帧或指定秒数关键帧，供下一段长视频作首帧或角色锚定图接力。"""
    active_files_dir = files_dir or FILES_DIR
    clean_name = _clean_media_ref(video_file)
    src_path = safe_file_id_path(active_files_dir, clean_name)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"源视频文件不存在: {clean_name}")

    ffmpeg_bin = resolve_ffmpeg_binary()
    meta = await asyncio.to_thread(probe_video_clip_info, src_path, ffmpeg_bin)
    duration = float(meta.get("duration") or 0.0)

    norm_mode = str(mode or "last").strip().lower()
    out_id = f"frame_{generate_file_id()}"
    out_filename = f"{out_id}.png"
    out_path = os.path.join(active_files_dir, out_filename)

    if norm_mode == "first":
        actual_ts = 0.0
        cmd = [ffmpeg_bin, "-y", "-ss", "0.000", "-i", src_path, "-frames:v", "1", out_path]
    elif norm_mode == "timestamp":
        actual_ts = max(0.0, min(float(timestamp_sec or 0.0), max(0.0, duration - 0.04) if duration > 0 else float(timestamp_sec or 0.0)))
        cmd = [ffmpeg_bin, "-y", "-ss", f"{actual_ts:.3f}", "-i", src_path, "-frames:v", "1", out_path]
    else:
        # 默认提取干净尾帧（距离结尾 0.08s），若极短视频未命中则回退精确秒数抽帧
        actual_ts = max(0.0, duration - 0.08)
        cmd = [ffmpeg_bin, "-y", "-sseof", "-0.08", "-i", src_path, "-frames:v", "1", out_path]

    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if (proc.returncode != 0 or not os.path.isfile(out_path)) and norm_mode == "last":
        fallback_cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{max(0.0, duration - 0.12):.3f}",
            "-i",
            src_path,
            "-frames:v",
            "1",
            out_path,
        ]
        proc = await asyncio.to_thread(
            subprocess.run,
            fallback_cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"提取视频关键帧失败: {(proc.stderr or '')[-260:]}")

    with Image.open(out_path) as im:
        width, height = im.size

    await asyncio.to_thread(
        record_file_mapping,
        out_filename,
        canvas_id=canvas_id,
        session_id=session_id,
        workflow_name="extract_video_frame",
        note=f"从 {clean_name} 抽帧 ({norm_mode}@{actual_ts:.2f}s)",
    )

    url = f"/api/file/{out_filename}"
    element_id = ""
    if place_on_canvas and canvas_id:
        fid = generate_file_id()
        file_data = {
            "mimeType": "image/png",
            "id": fid,
            "dataURL": url,
            "created": int(time.time() * 1000),
        }
        async with canvas_lock_manager.lock_canvas(canvas_id):
            canvas = await db_service.get_canvas_data(canvas_id)
            data = (canvas or {}).get("data") or {}
            data.setdefault("elements", [])
            data.setdefault("files", {})
            img_el = await generate_new_image_element(
                canvas_id, fid, {"width": width, "height": height}, canvas_data=data
            )
            element_id = str(img_el.get("id") or "")
            img_el["customData"] = {
                "workflowName": "extract_video_frame",
                "parentFileIds": [clean_name],
                "jaazLineage": {
                    "workflowName": "extract_video_frame",
                    "capability": "frame_extract",
                    "prompt": f"抽帧接力锚点 ({norm_mode} @ {actual_ts:.2f}s) <- {clean_name}",
                    "params": {"mode": norm_mode, "timestamp_sec": round(actual_ts, 3)},
                    "parentFileIds": [clean_name],
                    "createdAt": int(time.time() * 1000),
                },
            }
            data["elements"].append(img_el)
            data["files"][fid] = file_data
            await db_service.save_canvas_data(canvas_id, json.dumps(data))

        if session_id:
            await broadcast_session_update(
                session_id,
                canvas_id,
                {
                    "type": "image_generated",
                    "element": img_el,
                    "file": file_data,
                    "image_url": url,
                },
            )

    return {
        "file_id": out_filename,
        "element_id": element_id,
        "url": url,
        "width": width,
        "height": height,
        "source_video": clean_name,
        "mode": norm_mode,
        "timestamp_sec": round(actual_ts, 3),
    }


async def upscale_long_video_chunked(
    video_file: str = "",
    *,
    job_id: Optional[str] = None,
    scale_multiplier: float = 2.0,
    slice_seconds: Optional[float] = None,
    resume: bool = True,
    cleanup_temp_slices: bool = True,
    canvas_id: str = "",
    session_id: str = "",
    files_dir: Optional[str] = None,
    jobs_dir: Optional[str] = None,
    chunk_upscaler: Optional[Callable[[str, str, float], Awaitable[None]]] = None,
) -> Dict[str, Any]:
    """对长视频执行自适应内存分块超分、断点续跑，并在全部完成后无损合流原视频立体声音轨。"""
    active_files_dir = files_dir or FILES_DIR
    active_jobs_dir = jobs_dir or UPSCALE_JOBS_DIR

    existing_job = get_upscale_job(job_id, active_jobs_dir) if job_id else None
    if existing_job and not video_file:
        video_file = str(existing_job.get("source_video") or "")
        scale_multiplier = float(existing_job.get("scale_multiplier") or scale_multiplier)
        slice_seconds = float(existing_job.get("slice_seconds") or 10.0)
        canvas_id = canvas_id or str(existing_job.get("canvas_id") or "")
        session_id = session_id or str(existing_job.get("session_id") or "")

    clean_src = _clean_media_ref(video_file)
    if not clean_src:
        raise ValueError("必须提供待超分的视频文件名 video_file 或已存在的 job_id")
    src_path = safe_file_id_path(active_files_dir, clean_src)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"待超分视频不存在: {clean_src}")

    ffmpeg_bin = resolve_ffmpeg_binary()
    src_meta = await asyncio.to_thread(probe_video_clip_info, src_path, ffmpeg_bin)
    total_dur = float(src_meta.get("duration") or 0.0)
    if total_dur <= 0.05:
        raise ValueError(f"无法读取有效的视频时长: {clean_src}")

    # 自动依据远端内存计算安全切片时长
    if slice_seconds is None or float(slice_seconds) <= 0:
        ram_bytes = 0
        try:
            inst = await comfy_instance_service.resolve_instance(capability="i2v")
            health = await ensure_fresh_instance_health(inst)
            ram_bytes = int(health.get("ram_free") or health.get("ram_total") or 0)
        except Exception:
            ram_bytes = 0
        eff_slice_sec = compute_safe_upscale_slice_sec(
            int(src_meta.get("width") or 1280),
            int(src_meta.get("height") or 720),
            scale_multiplier=scale_multiplier,
            ram_bytes=ram_bytes,
        )
    else:
        eff_slice_sec = max(2.0, round(float(slice_seconds), 2))

    resolved_job_id = job_id or _build_job_id(clean_src, scale_multiplier, eff_slice_sec)
    if resume and existing_job is None:
        existing_job = get_upscale_job(resolved_job_id, active_jobs_dir)

    job_root = os.path.join(active_jobs_dir, resolved_job_id)
    slices_dir = os.path.join(job_root, "slices")
    upscaled_dir = os.path.join(job_root, "upscaled")
    os.makedirs(slices_dir, exist_ok=True)
    os.makedirs(upscaled_dir, exist_ok=True)

    num_chunks = max(1, int(math.ceil((total_dur - 0.02) / eff_slice_sec)))
    chunks_state: List[Dict[str, Any]] = []
    prev_chunks = (
        {int(c["index"]): c for c in existing_job.get("chunks", []) if isinstance(c, dict) and "index" in c}
        if (resume and isinstance(existing_job, dict))
        else {}
    )

    for idx in range(num_chunks):
        st_s = round(idx * eff_slice_sec, 3)
        seg_d = round(min(eff_slice_sec, total_dur - st_s), 3)
        s_file = os.path.join(slices_dir, f"slice_{idx:03d}.mp4")
        u_file = os.path.join(upscaled_dir, f"up_{idx:03d}.mp4")

        if not os.path.isfile(s_file):
            slice_cmd = [
                ffmpeg_bin,
                "-y",
                "-ss",
                f"{st_s:.3f}",
                "-t",
                f"{seg_d:.3f}",
                "-i",
                src_path,
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "16",
                "-preset",
                "fast",
                "-pix_fmt",
                "yuv420p",
                s_file,
            ]
            s_proc = await asyncio.to_thread(
                subprocess.run, slice_cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if s_proc.returncode != 0 or not os.path.isfile(s_file):
                raise RuntimeError(f"预切分第 {idx + 1} 段失败: {(s_proc.stderr or '')[-240:]}")

        already_done = (
            resume
            and idx in prev_chunks
            and prev_chunks[idx].get("status") == "completed"
            and os.path.isfile(u_file)
            and os.path.getsize(u_file) > 512
        )
        chunks_state.append(
            {
                "index": idx,
                "start_sec": st_s,
                "duration_sec": seg_d,
                "status": "completed" if already_done else "pending",
            }
        )

    job_doc: Dict[str, Any] = {
        "job_id": resolved_job_id,
        "source_video": clean_src,
        "scale_multiplier": float(scale_multiplier),
        "slice_seconds": eff_slice_sec,
        "total_chunks": num_chunks,
        "completed_chunks": sum(1 for c in chunks_state if c["status"] == "completed"),
        "status": "running",
        "canvas_id": canvas_id,
        "session_id": session_id,
        "output_file": "",
        "error": "",
        "chunks": chunks_state,
    }
    _save_job_state(job_doc, active_jobs_dir)

    upscaler_fn = chunk_upscaler or _default_seedvr2_chunk_upscaler
    for ch in chunks_state:
        idx = int(ch["index"])
        if ch["status"] == "completed":
            continue
        s_file = os.path.join(slices_dir, f"slice_{idx:03d}.mp4")
        u_file = os.path.join(upscaled_dir, f"up_{idx:03d}.mp4")
        try:
            await upscaler_fn(s_file, u_file, float(scale_multiplier))
            if not os.path.isfile(u_file):
                raise RuntimeError(f"第 {idx + 1}/{num_chunks} 段超分未生成有效文件")
            ch["status"] = "completed"
            job_doc["completed_chunks"] = sum(
                1 for item in chunks_state if item["status"] == "completed"
            )
            _save_job_state(job_doc, active_jobs_dir)
        except Exception as exc:
            err_msg = str(exc)
            job_doc["error"] = err_msg
            if _is_transient_offline_error(exc):
                job_doc["status"] = "paused_offline"
                _save_job_state(job_doc, active_jobs_dir)
                return {
                    "status": "paused_offline",
                    "job_id": resolved_job_id,
                    "source_video": clean_src,
                    "completed_chunks": job_doc["completed_chunks"],
                    "total_chunks": num_chunks,
                    "slice_seconds": eff_slice_sec,
                    "error": err_msg,
                }
            job_doc["status"] = "failed"
            _save_job_state(job_doc, active_jobs_dir)
            raise

    # 全部切片超分完成，执行无损拼接并回灌原视频完整立体声音轨
    concat_txt = os.path.join(job_root, "concat_list.txt")
    with open(concat_txt, "w", encoding="utf-8") as cf:
        for idx in range(num_chunks):
            u_abs = os.path.abspath(os.path.join(upscaled_dir, f"up_{idx:03d}.mp4")).replace("\\", "/")
            cf.write(f"file '{u_abs}'\n")

    out_filename = f"upscaled_x{int(round(scale_multiplier))}_{generate_file_id()}.mp4"
    out_path = os.path.join(active_files_dir, out_filename)
    has_src_audio = bool(src_meta.get("has_audio", False))

    mux_cmd = [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt]
    if has_src_audio:
        mux_cmd.extend(
            ["-i", src_path, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy", "-shortest"]
        )
    else:
        mux_cmd.extend(["-c:v", "copy"])
    mux_cmd.extend(["-movflags", "+faststart", out_path])

    m_proc = await asyncio.to_thread(
        subprocess.run, mux_cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if m_proc.returncode != 0 or not os.path.isfile(out_path):
        # 若个别切片编码时间戳不一致无法直接 stream copy，回退至高质量重封装
        re_cmd = [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt]
        if has_src_audio:
            re_cmd.extend(
                [
                    "-i",
                    src_path,
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "libx264",
                    "-crf",
                    "17",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "copy",
                    "-shortest",
                ]
            )
        else:
            re_cmd.extend(["-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p"])
        re_cmd.extend(["-movflags", "+faststart", out_path])
        m_proc = await asyncio.to_thread(
            subprocess.run, re_cmd, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if m_proc.returncode != 0 or not os.path.isfile(out_path):
            raise RuntimeError(f"分块超分合并音轨失败: {(m_proc.stderr or '')[-280:]}")

    if cleanup_temp_slices and os.path.isdir(slices_dir):
        shutil.rmtree(slices_dir, ignore_errors=True)

    out_meta = await asyncio.to_thread(probe_video_clip_info, out_path, ffmpeg_bin)
    width = int(out_meta.get("width") or int(src_meta["width"] * scale_multiplier))
    height = int(out_meta.get("height") or int(src_meta["height"] * scale_multiplier))
    out_dur = float(out_meta.get("duration") or total_dur)
    out_audio = bool(out_meta.get("has_audio", False))

    await asyncio.to_thread(
        record_file_mapping,
        out_filename,
        canvas_id=canvas_id,
        session_id=session_id,
        workflow_name="video_upscale_chunked",
        note=f"SeedVR2 分块 {scale_multiplier}x 超分合流 ({num_chunks} 段 <- {clean_src})",
    )

    url = f"/api/file/{out_filename}"
    element_id = ""
    if canvas_id:
        fid = generate_file_id()
        file_data = {
            "mimeType": "video/mp4",
            "id": fid,
            "dataURL": url,
            "created": int(time.time() * 1000),
        }
        async with canvas_lock_manager.lock_canvas(canvas_id):
            canvas = await db_service.get_canvas_data(canvas_id)
            data = (canvas or {}).get("data") or {}
            data.setdefault("elements", [])
            data.setdefault("files", {})
            vid_el = await generate_new_video_element(
                canvas_id, fid, {"width": width, "height": height, "url": url}, canvas_data=data
            )
            element_id = str(vid_el.get("id") or "")
            vid_el["customData"] = {
                "workflowName": "video_upscale_chunked",
                "parentFileIds": [clean_src],
                "jaazLineage": {
                    "workflowName": "video_upscale_chunked",
                    "capability": "video_upscale",
                    "prompt": f"SeedVR2 自动分块 {scale_multiplier}x 超分 ({num_chunks} 段 × {eff_slice_sec}s)",
                    "params": {
                        "scale_multiplier": scale_multiplier,
                        "slice_seconds": eff_slice_sec,
                        "chunks": num_chunks,
                    },
                    "parentFileIds": [clean_src],
                    "createdAt": int(time.time() * 1000),
                },
            }
            data["elements"].append(vid_el)
            data["files"][fid] = file_data
            await db_service.save_canvas_data(canvas_id, json.dumps(data))

        if session_id:
            await broadcast_session_update(
                session_id,
                canvas_id,
                {
                    "type": "video_generated",
                    "element": vid_el,
                    "file": file_data,
                    "video_url": url,
                },
            )

    job_doc["status"] = "completed"
    job_doc["output_file"] = out_filename
    job_doc["error"] = ""
    _save_job_state(job_doc, active_jobs_dir)

    return {
        "status": "completed",
        "job_id": resolved_job_id,
        "file_id": out_filename,
        "element_id": element_id,
        "url": url,
        "width": width,
        "height": height,
        "duration_sec": out_dur,
        "has_audio": out_audio,
        "completed_chunks": num_chunks,
        "total_chunks": num_chunks,
        "slice_seconds": eff_slice_sec,
    }
