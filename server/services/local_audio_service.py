"""程序说明：多源语音合成（OpenAI / DashScope Qwen-TTS / 本机离线中文 SAPI + FFmpeg 兜底）与视频立体声音轨提取服务（P6-2）。"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

import httpx

from services.config_service import FILES_DIR, config_service
from services.db_service import db_service
from services.file_mapping_service import record_file_mapping
from services.video_compose_service import (
    _clean_media_ref,
    probe_video_clip_info,
    resolve_ffmpeg_binary,
)
from services.websocket_service import broadcast_session_update
from tools.utils.image_canvas_utils import generate_file_id
from tools.video_generation.video_canvas_utils import generate_new_audio_element
from utils.canvas_lock import canvas_lock_manager
from utils.http_client import HttpClient
from utils.log_sanitizer import get_sanitized_logger
from utils.path_security import safe_file_id_path

_logger = get_sanitized_logger(__name__)

DASHSCOPE_MULTIMODAL_TTS_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
)


async def _write_audio_to_canvas(
    out_filename: str,
    mime_type: str,
    *,
    canvas_id: str,
    session_id: str,
    workflow_name: str,
    prompt_desc: str,
    parent_files: list[str],
) -> str:
    """加锁将生成的音频卡片写入指定画布并广播实时事件。"""
    if not canvas_id:
        return ""
    url = f"/api/file/{out_filename}"
    fid = generate_file_id()
    file_data = {
        "mimeType": mime_type,
        "id": fid,
        "dataURL": url,
        "created": int(time.time() * 1000),
    }
    element_id = ""
    async with canvas_lock_manager.lock_canvas(canvas_id):
        canvas = await db_service.get_canvas_data(canvas_id)
        data = (canvas or {}).get("data") or {}
        data.setdefault("elements", [])
        data.setdefault("files", {})
        audio_el = await generate_new_audio_element(
            canvas_id, fid, {"width": 360, "height": 108, "url": url}, canvas_data=data
        )
        element_id = str(audio_el.get("id") or "")
        audio_el["customData"] = {
            "jaazMediaType": "audio",
            "workflowName": workflow_name,
            "parentFileIds": parent_files,
            "jaazLineage": {
                "workflowName": workflow_name,
                "capability": "tts" if "tts" in workflow_name else "audio_extract",
                "prompt": prompt_desc[:500],
                "parentFileIds": parent_files,
                "createdAt": int(time.time() * 1000),
            },
        }
        data["elements"].append(audio_el)
        data["files"][fid] = file_data
        await db_service.save_canvas_data(canvas_id, json.dumps(data))

    if session_id:
        await broadcast_session_update(
            session_id,
            canvas_id,
            {
                "type": "audio_generated",
                "element": audio_el,
                "file": file_data,
                "audio_url": url,
            },
        )
    return element_id


async def _try_dashscope_qwen_tts(text: str, api_key: str, voice: str) -> Optional[bytes]:
    """调用阿里云百炼原生 qwen-tts 接口合成语音并下载音频字节。"""
    ds_voice = voice if voice in ("Cherry", "Serena", "Ethan", "Chelsie") else "Cherry"
    try:
        async with HttpClient.create(timeout=httpx.Timeout(45.0)) as client:
            resp = await client.post(
                DASHSCOPE_MULTIMODAL_TTS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "qwen-tts",
                    "input": {"text": text[:600], "voice": ds_voice},
                },
            )
            if resp.status_code >= 400:
                return None
            payload = resp.json()
            audio_url = (
                ((payload.get("output") or {}).get("audio") or {}).get("url") or ""
            )
            if not audio_url:
                return None
            dl = await client.get(audio_url)
            if dl.status_code == 200 and dl.content:
                return dl.content
    except Exception as exc:
        _logger.debug("DashScope qwen-tts 未命中，将回退本机语音: %s", exc)
    return None


async def _try_openai_speech_tts(
    text: str, base_url: str, api_key: str, model: str, voice: str
) -> Optional[bytes]:
    """调用 OpenAI 兼容 /audio/speech 端点获取音频字节。"""
    try:
        async with HttpClient.create(timeout=httpx.Timeout(45.0)) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/audio/speech",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model or "tts-1",
                    "input": text[:2000],
                    "voice": voice or "alloy",
                },
            )
            if resp.status_code == 200 and resp.content:
                return resp.content
    except Exception as exc:
        _logger.debug("OpenAI /audio/speech 未命中: %s", exc)
    return None


def _synthesize_windows_sapi_mp3_sync(
    text: str, out_mp3_path: str, ffmpeg_bin: str
) -> None:
    """在 Windows 下调用内置 System.Speech 中文/英文引擎输出 WAV，并经内置 ffmpeg 响度均衡转码为 MP3。"""
    if os.name != "nt":
        raise RuntimeError("非 Windows 环境未配置可用云端 TTS 密钥")

    fd_txt, txt_path = tempfile.mkstemp(suffix=".txt", text=True)
    fd_wav, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd_wav)
    try:
        with os.fdopen(fd_txt, "w", encoding="utf-8") as tf:
            tf.write(text[:2000])

        ps_script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$zh = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'zh*' } | Select-Object -First 1; "
            "if ($zh) { $s.SelectVoice($zh.VoiceInfo.Name) }; "
            "$txt = [System.IO.File]::ReadAllText($env:JAAZ_TTS_TXT, [System.Text.Encoding]::UTF8); "
            "$s.SetOutputToWaveFile($env:JAAZ_TTS_WAV); "
            "$s.Speak($txt); "
            "$s.Dispose();"
        )
        env = dict(os.environ)
        env["JAAZ_TTS_TXT"] = txt_path
        env["JAAZ_TTS_WAV"] = wav_path
        ps_proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if ps_proc.returncode != 0 or not os.path.isfile(wav_path) or os.path.getsize(wav_path) < 256:
            raise RuntimeError(f"本机语音合成失败: {(ps_proc.stderr or '')[-200:]}")

        ff_proc = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                wav_path,
                "-af",
                "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                out_mp3_path,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if ff_proc.returncode != 0 or not os.path.isfile(out_mp3_path):
            raise RuntimeError(f"语音转码 MP3 失败: {(ff_proc.stderr or '')[-200:]}")
    finally:
        for p in (txt_path, wav_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


async def synthesize_narration_speech(
    text: str,
    *,
    voice: str = "alloy",
    provider: str = "",
    model: str = "tts-1",
    allow_local_fallback: bool = True,
    canvas_id: str = "",
    session_id: str = "",
    files_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """按优先级调用 OpenAI 兼容端点、DashScope 原生 qwen-tts 或本机离线中文语音 + FFmpeg 合成旁白 MP3。"""
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("配音文本不能为空")

    active_files_dir = files_dir or FILES_DIR
    os.makedirs(active_files_dir, exist_ok=True)
    ffmpeg_bin = resolve_ffmpeg_binary()

    cfg = config_service.get_config()
    audio_bytes: Optional[bytes] = None
    backend_used = ""

    # 1. 若显式指定或配置了非 DashScope 的 OpenAI 兼容语音提供商，优先请求 /audio/speech
    candidates = [provider] if provider else ["openai", "dashscope"]
    for pname in candidates:
        pc = cfg.get(pname) if isinstance(cfg, dict) else None
        if not isinstance(pc, dict) or not pc.get("api_key"):
            continue
        api_key = str(pc["api_key"])
        base_url = str(pc.get("url") or "")
        if pname == "dashscope" or "dashscope.aliyuncs.com" in base_url:
            raw_ds = await _try_dashscope_qwen_tts(clean_text, api_key, voice)
            if raw_ds:
                audio_bytes = raw_ds
                backend_used = "dashscope_qwen_tts"
                break
        elif base_url:
            raw_oa = await _try_openai_speech_tts(clean_text, base_url, api_key, model, voice)
            if raw_oa:
                audio_bytes = raw_oa
                backend_used = f"{pname}_audio_speech"
                break

    out_filename = f"tts_{generate_file_id()}.mp3"
    out_path = os.path.join(active_files_dir, out_filename)

    if audio_bytes:
        # 统一经内置 ffmpeg 规范化为 48kHz 立体声 MP3（兼容 qwen-tts 返回 WAV 的情况）
        fd_in, raw_in_path = tempfile.mkstemp(suffix=".audio")
        try:
            with os.fdopen(fd_in, "wb") as rf:
                rf.write(audio_bytes)
            proc = await asyncio.to_thread(
                subprocess.run,
                [
                    ffmpeg_bin,
                    "-y",
                    "-i",
                    raw_in_path,
                    "-af",
                    "aresample=48000,aformat=channel_layouts=stereo",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    out_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0 or not os.path.isfile(out_path):
                with open(out_path, "wb") as af:
                    af.write(audio_bytes)
        finally:
            if os.path.exists(raw_in_path):
                try:
                    os.remove(raw_in_path)
                except OSError:
                    pass
    elif allow_local_fallback:
        await asyncio.to_thread(
            _synthesize_windows_sapi_mp3_sync, clean_text, out_path, ffmpeg_bin
        )
        backend_used = "local_windows_sapi"
    else:
        raise RuntimeError("未检测到可用的云端语音合成提供商，且已禁用本机离线语音兜底")

    meta = await asyncio.to_thread(probe_video_clip_info, out_path, ffmpeg_bin)
    duration_sec = float(meta.get("duration") or 0.0)

    await asyncio.to_thread(
        record_file_mapping,
        out_filename,
        canvas_id=canvas_id,
        session_id=session_id,
        workflow_name="synthesize_speech_narration",
        note=f"TTS 语音合成 ({backend_used})",
    )

    elem_id = await _write_audio_to_canvas(
        out_filename,
        "audio/mpeg",
        canvas_id=canvas_id,
        session_id=session_id,
        workflow_name="synthesize_speech_narration",
        prompt_desc=clean_text,
        parent_files=[],
    )
    return {
        "file_id": out_filename,
        "element_id": elem_id,
        "url": f"/api/file/{out_filename}",
        "duration_sec": duration_sec,
        "backend": backend_used,
    }


async def extract_audio_from_video(
    video_file: str,
    *,
    normalize_loudness: bool = False,
    canvas_id: str = "",
    session_id: str = "",
    files_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """从画布或本地视频中剥离 48kHz 立体声 MP3 音轨卡片，供多模态音频参考生视频或旁白混音复用。"""
    active_files_dir = files_dir or FILES_DIR
    clean_src = _clean_media_ref(video_file)
    src_path = safe_file_id_path(active_files_dir, clean_src)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"源视频文件不存在: {clean_src}")

    ffmpeg_bin = resolve_ffmpeg_binary()
    meta = await asyncio.to_thread(probe_video_clip_info, src_path, ffmpeg_bin)
    if not meta.get("has_audio"):
        raise ValueError(f"视频 `{clean_src}` 不包含可提取的音频轨道")

    out_filename = f"audio_{generate_file_id()}.mp3"
    out_path = os.path.join(active_files_dir, out_filename)
    af_chain = "aresample=48000,aformat=channel_layouts=stereo"
    if normalize_loudness:
        af_chain += ",loudnorm=I=-16:TP=-1.5:LRA=11"

    proc = await asyncio.to_thread(
        subprocess.run,
        [
            ffmpeg_bin,
            "-y",
            "-i",
            src_path,
            "-vn",
            "-af",
            af_chain,
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            out_path,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(f"提取音轨失败: {(proc.stderr or '')[-240:]}")

    out_meta = await asyncio.to_thread(probe_video_clip_info, out_path, ffmpeg_bin)
    duration_sec = float(out_meta.get("duration") or meta.get("duration") or 0.0)

    await asyncio.to_thread(
        record_file_mapping,
        out_filename,
        canvas_id=canvas_id,
        session_id=session_id,
        workflow_name="extract_video_audio",
        note=f"从 {clean_src} 剥离立体声音轨",
    )

    elem_id = await _write_audio_to_canvas(
        out_filename,
        "audio/mpeg",
        canvas_id=canvas_id,
        session_id=session_id,
        workflow_name="extract_video_audio",
        prompt_desc=f"提取音频 <- {clean_src}",
        parent_files=[clean_src],
    )
    return {
        "file_id": out_filename,
        "element_id": elem_id,
        "url": f"/api/file/{out_filename}",
        "duration_sec": duration_sec,
        "source_video": clean_src,
    }
