"""程序说明：面向 LangGraph 智能体的多源中文/英文旁白配音合成工具（synthesize_speech_narration）与视频音轨剥离工具（extract_video_audio）。"""
from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.local_audio_service import (
    extract_audio_from_video,
    synthesize_narration_speech,
)
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)


class SynthesizeNarrationInput(BaseModel):
    """旁白或角色台词语音合成参数。"""

    text: str = Field(description="需要合成为语音的中英文台词或旁白文本")
    voice: str = Field(
        default="Cherry",
        description="可选。音色标识（如 DashScope 的 Cherry / Ethan 或 OpenAI 的 alloy；离线回退自动选用中文语音）。",
    )


class ExtractVideoAudioInput(BaseModel):
    """从已有视频中剥离独立音频卡片参数。"""

    video_file: str = Field(description="源视频文件名，如 'clip1.mp4'")
    normalize_loudness: bool = Field(
        default=False,
        description="是否对提取出的音频做 EBU R128 响度均衡（默认 false）。",
    )


@tool(
    "synthesize_speech_narration",
    description=(
        "将中文或英文旁白、独白或角色台词合成为 48kHz 立体声 MP3 音频卡片并写入当前画布。"
        "自动优先调用已配置的 DashScope Qwen-TTS / OpenAI 语音服务，无可用云端接口时自动无缝回退本机离线中文语音引擎。"
        "生成的音频可直接传入 video_edit_and_stitch 的 narration_audio 或 ref2video_multimodal 的参考音频。"
    ),
    args_schema=SynthesizeNarrationInput,
)
async def synthesize_speech_narration_tool(
    config: RunnableConfig,
    text: str,
    voice: str = "Cherry",
) -> str:
    """合成旁白语音并返回音频文件链接。"""
    ctx = (config or {}).get("configurable") or {}
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    try:
        res = await synthesize_narration_speech(
            text,
            voice=voice,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        fid = res["file_id"]
        return (
            f"synthesize_speech_narration executed successfully [{fid}](/api/file/{fid}) "
            f"(duration={res['duration_sec']}s, backend={res['backend']})"
        )
    except Exception as exc:
        _logger.error("synthesize_speech_narration 失败: %s", exc)
        return f"synthesize_speech_narration failed: {exc}"


@tool(
    "extract_video_audio",
    description=(
        "使用内置 FFmpeg 从指定画布视频中剥离独立的 48kHz 立体声 MP3 音频卡片并写入画布，"
        "适合将某一段视频生成的环境音、乐曲或台词作为后续镜头的参考音频（<Audio 1>）或全片背景音复用。"
    ),
    args_schema=ExtractVideoAudioInput,
)
async def extract_video_audio_tool(
    config: RunnableConfig,
    video_file: str,
    normalize_loudness: bool = False,
) -> str:
    """从视频剥离音频轨道并写入画布。"""
    ctx = (config or {}).get("configurable") or {}
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    try:
        res = await extract_audio_from_video(
            video_file,
            normalize_loudness=normalize_loudness,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        fid = res["file_id"]
        return (
            f"extract_video_audio executed successfully [{fid}](/api/file/{fid}) "
            f"(duration={res['duration_sec']}s, source={res['source_video']})"
        )
    except Exception as exc:
        _logger.error("extract_video_audio 失败: %s", exc)
        return f"extract_video_audio failed: {exc}"
