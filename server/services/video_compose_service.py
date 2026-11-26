"""程序说明：基于本机 ffmpeg / ffprobe 的多镜头自动裁剪、原生立体声音轨拼接、转场淡入淡出、旁白混音与字幕合成服务。"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from pymediainfo import MediaInfo

from services.config_service import FILES_DIR
from services.db_service import db_service
from services.video_finishing_service import (
    build_post_concat_finishing_filters,
    build_srt_content,
    format_srt_timestamp,
)
from services.websocket_service import broadcast_session_update
from tools.utils.image_canvas_utils import generate_file_id
from tools.video_generation.video_canvas_utils import generate_new_video_element
from utils.canvas_lock import canvas_lock_manager
from utils.log_sanitizer import get_sanitized_logger
from utils.path_security import safe_file_id_path

_logger = get_sanitized_logger(__name__)
PROJECT_BIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"
)


def _windows_registry_path_dirs() -> List[str]:
    """在 Windows 下读取用户级与系统级注册表 Path，确保进程启动后新增的环境变量目录也能被即时识别。"""
    if os.name != "nt":
        return []
    dirs: List[str] = []
    try:
        import winreg

        for hive, subkey in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
        ):
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    raw_val, _ = winreg.QueryValueEx(key, "Path")
                    if isinstance(raw_val, str):
                        for seg in raw_val.split(";"):
                            expanded = os.path.expandvars(seg.strip())
                            if expanded and expanded not in dirs:
                                dirs.append(expanded)
            except OSError:
                continue
    except Exception:
        pass
    return dirs


def resolve_ffmpeg_binary() -> str:
    """优先使用项目内置 server/bin/ffmpeg，其次查找环境变量与系统路径。"""
    bundled_exe = os.path.join(
        PROJECT_BIN_DIR, "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    )
    if os.path.isfile(bundled_exe):
        return bundled_exe

    env_bin = os.getenv("FFMPEG_PATH", "").strip()
    if env_bin:
        if os.path.isfile(env_bin):
            return env_bin
        cand_in_dir = os.path.join(env_bin, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if os.path.isfile(cand_in_dir):
            return cand_in_dir

    found = shutil.which("ffmpeg")
    if found and os.path.isfile(found):
        return found

    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for reg_dir in _windows_registry_path_dirs():
        cand = os.path.join(reg_dir, exe_name)
        if os.path.isfile(cand):
            return cand

    candidates: List[str] = [
        r"C:\ffmpeg-9.1-full_build\bin\ffmpeg.exe",
        *sorted(glob.glob(r"C:\ffmpeg*\bin\ffmpeg.exe"), reverse=True),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path

    try:
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass

    raise RuntimeError("未检测到 ffmpeg 可执行文件，请安装 ffmpeg 或配置 FFMPEG_PATH 环境变量")


def resolve_ffprobe_binary(ffmpeg_bin: Optional[str] = None) -> Optional[str]:
    """优先使用项目内置 server/bin/ffprobe，其次根据 ffmpeg 同级目录或系统环境定位。"""
    bundled_probe = os.path.join(
        PROJECT_BIN_DIR, "ffprobe.exe" if os.name == "nt" else "ffprobe"
    )
    if os.path.isfile(bundled_probe):
        return bundled_probe

    env_probe = os.getenv("FFPROBE_PATH", "").strip()
    if env_probe and os.path.isfile(env_probe):
        return env_probe

    if ffmpeg_bin:
        sibling = os.path.join(
            os.path.dirname(ffmpeg_bin),
            "ffprobe.exe" if os.name == "nt" else "ffprobe",
        )
        if os.path.isfile(sibling):
            return sibling

    found = shutil.which("ffprobe")
    if found and os.path.isfile(found):
        return found

    exe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    for reg_dir in _windows_registry_path_dirs():
        cand = os.path.join(reg_dir, exe_name)
        if os.path.isfile(cand):
            return cand
    return None


def probe_video_clip_info(file_path: str, ffmpeg_bin: Optional[str] = None) -> Dict[str, Any]:
    """探测单个视频文件的精确时长、宽高、帧率与是否包含音频流。"""
    info: Dict[str, Any] = {
        "duration": 0.0,
        "width": 1280,
        "height": 720,
        "fps": 24.0,
        "has_audio": False,
        "video_codec": "",
        "audio_codec": "",
    }
    ffprobe_bin = resolve_ffprobe_binary(ffmpeg_bin)
    if ffprobe_bin:
        try:
            proc = subprocess.run(
                [ffprobe_bin, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                payload = json.loads(proc.stdout)
                fmt = payload.get("format") or {}
                if fmt.get("duration"):
                    info["duration"] = round(float(fmt["duration"]), 3)
                for st in payload.get("streams") or []:
                    ctype = st.get("codec_type")
                    if ctype == "video" and not info["video_codec"]:
                        info["video_codec"] = str(st.get("codec_name") or "")
                        info["width"] = int(st.get("width") or info["width"])
                        info["height"] = int(st.get("height") or info["height"])
                        r_fr = str(st.get("avg_frame_rate") or st.get("r_frame_rate") or "24/1")
                        if "/" in r_fr:
                            num, den = r_fr.split("/", 1)
                            if float(den or 0) > 0:
                                info["fps"] = round(float(num) / float(den), 2)
                        if not info["duration"] and st.get("duration"):
                            info["duration"] = round(float(st["duration"]), 3)
                    elif ctype == "audio":
                        info["has_audio"] = True
                        info["audio_codec"] = str(st.get("codec_name") or "")
                return info
        except Exception as exc:
            _logger.warning("ffprobe 解析失败，回退至 MediaInfo: %s", exc)

    try:
        mi = MediaInfo.parse(file_path)
        for tr in mi.tracks:
            if tr.track_type == "Video":
                info["width"] = int(tr.width or info["width"])
                info["height"] = int(tr.height or info["height"])
                if tr.duration:
                    info["duration"] = round(float(tr.duration) / 1000.0, 3)
            elif tr.track_type == "Audio":
                info["has_audio"] = True
    except Exception:
        pass
    return info


def build_ffmpeg_compose_command(
    ffmpeg_bin: str,
    clip_paths: List[str],
    output_path: str,
    *,
    narration_path: Optional[str] = None,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.28,
    enable_audio_ducking: bool = True,
    srt_path: Optional[str] = None,
    target_width: int = 1344,
    target_height: int = 768,
    fps: int = 24,
    clip_specs: Optional[List[Dict[str, Any]]] = None,
    preserve_clip_audio: bool = False,
    transition_fade_sec: float = 0.0,
    normalize_audio_loudness: bool = False,
    burn_subtitles: bool = False,
    intro_title: Optional[str] = None,
    fade_out_outro_sec: float = 0.0,
) -> List[str]:
    """构建安全的参数数组形式 ffmpeg 自动裁剪与拼接命令，支持立体声音轨、配乐闪避、响度均衡、硬烧录字幕与片头片尾精装。"""
    if not clip_paths:
        raise ValueError("clip_paths cannot be empty")

    w = max(64, int(target_width) - (int(target_width) % 2))
    h = max(64, int(target_height) - (int(target_height) % 2))
    fps_int = max(1, int(round(fps or 24)))
    fade_d = max(0.0, round(float(transition_fade_sec or 0.0), 3))

    cmd: List[str] = [ffmpeg_bin, "-y"]
    for cp in clip_paths:
        cmd.extend(["-i", cp])

    narration_idx: Optional[int] = None
    if narration_path:
        narration_idx = len(clip_paths)
        cmd.extend(["-i", narration_path])

    bgm_idx: Optional[int] = None
    if bgm_path:
        bgm_idx = len(clip_paths) + (1 if narration_path else 0)
        cmd.extend(["-i", bgm_path])

    srt_idx: Optional[int] = None
    if srt_path and not burn_subtitles:
        srt_idx = len(clip_paths) + (1 if narration_path else 0) + (1 if bgm_path else 0)
        cmd.extend(["-i", srt_path])

    scale_pad = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps_int},format=yuv420p"
    )

    filter_parts: List[str] = []
    use_audio_concat = bool(preserve_clip_audio and clip_specs and len(clip_specs) == len(clip_paths))
    total_eff_dur = 0.0

    for i in range(len(clip_paths)):
        spec = clip_specs[i] if (clip_specs and i < len(clip_specs)) else {}
        t_start, t_end = spec.get("trim_start"), spec.get("trim_end")
        raw_dur = float(spec.get("duration") or 0.0)

        s_val = max(0.0, float(t_start)) if t_start is not None else 0.0
        e_val = float(t_end) if (t_end is not None and float(t_end) > s_val) else None
        eff_dur = (e_val - s_val) if e_val is not None else max(0.0, raw_dur - s_val)
        total_eff_dur += eff_dur if eff_dur > 0 else 5.0

        v_chain: List[str] = []
        if s_val > 0.0 or e_val is not None:
            v_chain.append(
                f"trim=start={s_val:.3f}:end={e_val:.3f},setpts=PTS-STARTPTS"
                if e_val is not None
                else f"trim=start={s_val:.3f},setpts=PTS-STARTPTS"
            )
        v_chain.append(scale_pad)

        if fade_d > 0.0 and eff_dur > fade_d * 2.5:
            if i > 0:
                v_chain.append(f"fade=t=in:st=0:d={fade_d:.3f}")
            if i < len(clip_paths) - 1:
                v_chain.append(f"fade=t=out:st={max(0.0, eff_dur - fade_d):.3f}:d={fade_d:.3f}")

        filter_parts.append(f"[{i}:v]{','.join(v_chain)}[v{i}]")

        if use_audio_concat:
            if bool(spec.get("has_audio", False)):
                a_chain: List[str] = []
                if s_val > 0.0 or e_val is not None:
                    a_chain.append(
                        f"atrim=start={s_val:.3f}:end={e_val:.3f},asetpts=PTS-STARTPTS"
                        if e_val is not None
                        else f"atrim=start={s_val:.3f},asetpts=PTS-STARTPTS"
                    )
                a_chain.append("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo")
                if fade_d > 0.0 and eff_dur > fade_d * 2.5:
                    af_d = min(fade_d, 0.25)
                    if i > 0:
                        a_chain.append(f"afade=t=in:st=0:d={af_d:.3f}")
                    if i < len(clip_paths) - 1:
                        a_chain.append(f"afade=t=out:st={max(0.0, eff_dur - af_d):.3f}:d={af_d:.3f}")
                filter_parts.append(f"[{i}:a]{','.join(a_chain)}[a{i}]")
            else:
                sil_dur = max(0.1, eff_dur if eff_dur > 0 else 5.0)
                filter_parts.append(
                    f"anullsrc=r=48000:cl=stereo:d={sil_dur:.3f},aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
                )

    if use_audio_concat:
        va_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(clip_paths)))
        if narration_idx is not None:
            filter_parts.append(f"{va_inputs}concat=n={len(clip_paths)}:v=1:a=1[vout][aclip]")
            filter_parts.append(
                f"[aclip]volume=0.35[abg];[{narration_idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=1.0[anar];"
                f"[abg][anar]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
        else:
            filter_parts.append(f"{va_inputs}concat=n={len(clip_paths)}:v=1:a=1[vout][aout]")
        extra_clauses, v_map, a_map = build_post_concat_finishing_filters(
            "[vout]",
            "[aout]",
            total_duration_sec=total_eff_dur,
            bgm_input_idx=bgm_idx,
            bgm_volume=bgm_volume,
            enable_audio_ducking=enable_audio_ducking,
            burn_srt_path=srt_path if burn_subtitles else None,
            intro_title=intro_title,
            fade_out_outro_sec=fade_out_outro_sec,
            normalize_audio_loudness=normalize_audio_loudness,
        )
        filter_parts.extend(extra_clauses)
        cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", v_map, "-map", a_map or "[aout]", "-c:a", "aac", "-b:a", "192k"])
    else:
        v_inputs = "".join(f"[v{i}]" for i in range(len(clip_paths)))
        filter_parts.append(f"{v_inputs}concat=n={len(clip_paths)}:v=1:a=0[vout]")
        extra_clauses, v_map, a_only_map = build_post_concat_finishing_filters(
            "[vout]",
            None,
            total_duration_sec=total_eff_dur,
            bgm_input_idx=bgm_idx if narration_idx is None else None,
            bgm_volume=bgm_volume,
            enable_audio_ducking=False,
            burn_srt_path=srt_path if burn_subtitles else None,
            intro_title=intro_title,
            fade_out_outro_sec=fade_out_outro_sec,
            normalize_audio_loudness=normalize_audio_loudness,
        )
        filter_parts.extend(extra_clauses)
        cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", v_map])
        if narration_idx is not None:
            cmd.extend(["-map", f"{narration_idx}:a:0", "-c:a", "aac", "-shortest"])
        elif a_only_map:
            cmd.extend(["-map", a_only_map, "-c:a", "aac", "-b:a", "192k"])
        elif len(clip_paths) == 1:
            cmd.extend(["-map", "0:a?", "-c:a", "aac"])

    if srt_idx is not None:
        cmd.extend(["-map", f"{srt_idx}:s:0", "-c:s", "mov_text"])

    cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path])
    return cmd


def _clean_media_ref(raw_ref: str) -> str:
    """仅剥离合法的 /api/file/ URL 前缀，保留任何非法路径分隔符交由 safe_file_id_path 拦截。"""
    s = str(raw_ref or "").strip().split("?", 1)[0]
    if s.startswith("/api/file/"):
        return s[len("/api/file/") :]
    return s


async def compose_storyboard_clips(
    video_files: Optional[List[str]] = None,
    *,
    clip_edits: Optional[List[Dict[str, Any]]] = None,
    target_clip_duration: Optional[float] = None,
    transition_fade_sec: float = 0.2,
    preserve_clip_audio: bool = True,
    target_width: int = 0,
    target_height: int = 0,
    narration_audio: Optional[str] = None,
    bgm_audio: Optional[str] = None,
    bgm_volume: float = 0.28,
    enable_audio_ducking: bool = True,
    subtitles: Optional[List[Dict[str, Any]]] = None,
    normalize_audio_loudness: bool = False,
    burn_subtitles: bool = False,
    intro_title: Optional[str] = None,
    fade_out_outro_sec: float = 0.0,
    canvas_id: str = "",
    session_id: str = "",
    files_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """校验本地视频与裁剪参数，执行 ffmpeg 自动剪辑拼接，并将成片落盘至 files_dir 及目标画布。"""
    active_files_dir = files_dir or FILES_DIR
    normalized_edits: List[Dict[str, Any]] = []
    if clip_edits:
        normalized_edits = [
            {"file": _clean_media_ref(str(it["file"])), "trim_start": it.get("trim_start"), "trim_end": it.get("trim_end")}
            for it in clip_edits
            if isinstance(it, dict) and str(it.get("file") or "").strip()
        ]
    if not normalized_edits and video_files:
        normalized_edits = [
            {"file": _clean_media_ref(str(vf)), "trim_start": None, "trim_end": None}
            for vf in video_files
            if str(vf or "").strip()
        ]
    if not normalized_edits:
        raise ValueError("至少需要提供 1 个待剪辑拼接的视频文件名")

    resolved_clips: List[str] = []
    for ed in normalized_edits:
        cp = safe_file_id_path(active_files_dir, ed["file"])
        if not os.path.isfile(cp):
            raise FileNotFoundError(f"视频文件不存在: {ed['file']}")
        resolved_clips.append(cp)

    resolved_narration: Optional[str] = None
    if narration_audio and narration_audio.strip():
        resolved_narration = safe_file_id_path(active_files_dir, _clean_media_ref(narration_audio))
        if not os.path.isfile(resolved_narration):
            raise FileNotFoundError(f"配音文件不存在: {os.path.basename(resolved_narration)}")

    resolved_bgm: Optional[str] = None
    if bgm_audio and bgm_audio.strip():
        resolved_bgm = safe_file_id_path(active_files_dir, _clean_media_ref(bgm_audio))
        if not os.path.isfile(resolved_bgm):
            raise FileNotFoundError(f"背景音乐文件不存在: {os.path.basename(resolved_bgm)}")

    ffmpeg_bin = resolve_ffmpeg_binary()

    # 探测每段输入视频的元数据并组装精确裁剪规格
    clip_specs: List[Dict[str, Any]] = []
    for idx, cp in enumerate(resolved_clips):
        meta = await asyncio.to_thread(probe_video_clip_info, cp, ffmpeg_bin)
        t_start = normalized_edits[idx].get("trim_start")
        t_end = normalized_edits[idx].get("trim_end")
        s_f = max(0.0, float(t_start)) if t_start is not None else 0.0
        if t_end is not None:
            e_f: Optional[float] = float(t_end)
        elif target_clip_duration is not None and float(target_clip_duration) > 0:
            raw_d = float(meta.get("duration") or 0.0)
            target_e = s_f + float(target_clip_duration)
            e_f = target_e if (raw_d <= 0.0 or raw_d > target_e + 0.02) else None
        else:
            e_f = None

        clip_specs.append(
            {
                "duration": float(meta.get("duration") or 0.0),
                "width": int(meta.get("width") or 1280),
                "height": int(meta.get("height") or 720),
                "fps": float(meta.get("fps") or 24.0),
                "has_audio": bool(meta.get("has_audio", False)),
                "trim_start": s_f if s_f > 0 else None,
                "trim_end": e_f,
            }
        )

    out_w = int(target_width) if int(target_width or 0) > 0 else clip_specs[0]["width"]
    out_h = int(target_height) if int(target_height or 0) > 0 else clip_specs[0]["height"]
    out_fps = int(round(clip_specs[0]["fps"] or 24))

    out_id = f"composed_{generate_file_id()}"
    out_filename = f"{out_id}.mp4"
    out_path = os.path.join(active_files_dir, out_filename)

    srt_temp_path: Optional[str] = None
    try:
        if subtitles:
            srt_text = build_srt_content(subtitles)
            if srt_text.strip():
                fd, srt_temp_path = tempfile.mkstemp(suffix=".srt", text=True)
                with os.fdopen(fd, "w", encoding="utf-8") as sf:
                    sf.write(srt_text)

        cmd = build_ffmpeg_compose_command(
            ffmpeg_bin,
            resolved_clips,
            out_path,
            narration_path=resolved_narration,
            bgm_path=resolved_bgm,
            bgm_volume=bgm_volume,
            enable_audio_ducking=enable_audio_ducking,
            srt_path=srt_temp_path,
            target_width=out_w,
            target_height=out_h,
            fps=out_fps,
            clip_specs=clip_specs,
            preserve_clip_audio=preserve_clip_audio,
            transition_fade_sec=transition_fade_sec,
            normalize_audio_loudness=normalize_audio_loudness,
            burn_subtitles=burn_subtitles,
            intro_title=intro_title,
            fade_out_outro_sec=fade_out_outro_sec,
        )
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0 or not os.path.isfile(out_path):
            _logger.error("ffmpeg 合片失败: %s", (proc.stderr or "")[-800:])
            raise RuntimeError(f"ffmpeg 合成失败: {(proc.stderr or '')[-300:]}")
    finally:
        if srt_temp_path and os.path.exists(srt_temp_path):
            try:
                os.remove(srt_temp_path)
            except OSError:
                pass

    out_meta = await asyncio.to_thread(probe_video_clip_info, out_path, ffmpeg_bin)
    width = int(out_meta.get("width") or out_w)
    height = int(out_meta.get("height") or out_h)
    duration_sec = float(out_meta.get("duration") or 0.0)
    has_audio = bool(out_meta.get("has_audio", False))

    url = f"/api/file/{out_filename}"
    created_element_id = ""
    if canvas_id:
        file_id = generate_file_id()
        file_data = {
            "mimeType": "video/mp4",
            "id": file_id,
            "dataURL": url,
            "created": int(time.time() * 1000),
        }
        parent_files = [os.path.basename(p) for p in resolved_clips]
        async with canvas_lock_manager.lock_canvas(canvas_id):
            canvas = await db_service.get_canvas_data(canvas_id)
            data = (canvas or {}).get("data") or {}
            data.setdefault("elements", [])
            data.setdefault("files", {})
            new_elem = await generate_new_video_element(
                canvas_id,
                file_id,
                {"width": width, "height": height, "url": url},
                canvas_data=data,
            )
            created_element_id = str(new_elem.get("id") or "")
            new_elem["customData"] = {
                "workflowName": "video_edit_and_stitch",
                "parentFileIds": parent_files,
                "jaazLineage": {
                    "workflowName": "video_edit_and_stitch",
                    "capability": "video_compose",
                    "prompt": f"FFmpeg 自动剪辑拼接 {len(resolved_clips)} 段分镜 -> {duration_sec:.2f}s 成片",
                    "seed": None,
                    "parentFileIds": parent_files,
                    "params": {
                        "clip_count": len(resolved_clips),
                        "duration_sec": duration_sec,
                        "target_clip_duration": target_clip_duration,
                        "transition_fade_sec": transition_fade_sec,
                    },
                    "createdAt": int(time.time() * 1000),
                },
            }
            data["elements"].append(new_elem)
            data["files"][file_id] = file_data
            await db_service.save_canvas_data(canvas_id, json.dumps(data))

        if session_id:
            await broadcast_session_update(
                session_id,
                canvas_id,
                {
                    "type": "video_generated",
                    "element": new_elem,
                    "file": file_data,
                    "video_url": url,
                },
            )

    return {
        "file_id": out_filename,
        "element_id": created_element_id,
        "url": url,
        "width": width,
        "height": height,
        "duration_sec": duration_sec,
        "has_audio": has_audio,
        "clip_count": len(resolved_clips),
    }
