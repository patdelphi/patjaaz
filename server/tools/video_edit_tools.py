"""程序说明：面向 Python LangGraph 智能体的本地 FFmpeg 视频自动裁剪、转场淡入淡出与多段分镜拼接成片工具。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.video_compose_service import compose_storyboard_clips
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)


class ClipEditSpec(BaseModel):
    """单段视频裁剪参数定义。"""

    file: str = Field(description="画布或本地工作区中的视频文件名，如 'abc123.mp4'")
    trim_start: Optional[float] = Field(
        default=None, description="可选。裁剪起始秒数（默认从 0.0 秒开始）"
    )
    trim_end: Optional[float] = Field(
        default=None, description="可选。裁剪结束秒数（不填则保留至结尾或按 target_clip_duration 截齐）"
    )


class SubtitleLineSpec(BaseModel):
    """成片软字幕条目定义。"""

    start: float = Field(description="字幕起始秒数")
    end: float = Field(description="字幕结束秒数")
    text: str = Field(description="字幕文本内容")


class VideoEditAndStitchInput(BaseModel):
    """FFmpeg 视频自动剪辑与拼接工具输入参数。"""

    video_files: List[str] = Field(
        default_factory=list,
        description="按播放先后顺序排列的视频文件名列表（例如 ['clip1.mp4', 'clip2.mp4', 'clip3.mp4', 'clip4.mp4']）。若传入了 clip_edits 可留空。",
    )
    clip_edits: Optional[List[ClipEditSpec]] = Field(
        default=None,
        description="可选。对每段视频单独指定起止裁剪秒数（trim_start / trim_end）的精细剪辑列表。",
    )
    target_clip_duration: Optional[float] = Field(
        default=None,
        description="可选。将每段视频自动截齐至固定秒数（例如 4 段 15.08 秒分镜传 15.0 可精准拼成 60.0 秒整 1 分钟成片）。",
    )
    transition_fade_sec: float = Field(
        default=0.2,
        description="可选。分段衔接处的音视频柔和淡入淡出秒数（默认 0.2 秒消除切镜爆音与跳帧；传 0.0 为硬切）。",
    )
    preserve_clip_audio: bool = Field(
        default=True,
        description="可选。是否保留并拼接每段视频自带的原生立体声音轨（默认 true）。",
    )
    narration_audio: Optional[str] = Field(
        default=None,
        description="可选。叠加混音的全片旁白语音文件名。",
    )
    bgm_audio: Optional[str] = Field(
        default=None,
        description="可选。全片背景音乐文件名（过短时自动无缝循环，默认启用人声自动闪避）。",
    )
    bgm_volume: float = Field(
        default=0.28,
        description="可选。背景音乐基础音量系数（默认 0.28）。",
    )
    enable_audio_ducking: bool = Field(
        default=True,
        description="可选。是否开启人声/对白出现时背景配乐自动压低闪避（sidechaincompress，默认 true）。",
    )
    subtitles: Optional[List[SubtitleLineSpec]] = Field(
        default=None,
        description="可选。时间轴字幕列表（默认写入 MP4 软字幕轨；配合 burn_subtitles=true 可直接硬烧录至画面）。",
    )
    burn_subtitles: bool = Field(
        default=False,
        description="可选。是否将 subtitles 字幕带描边直接硬烧录到视频像素画面中（默认 false）。",
    )
    normalize_audio_loudness: bool = Field(
        default=False,
        description="可选。是否启用 EBU R128 (loudnorm -16 LUFS) 自动均衡多段视频响度差异（默认 false）。",
    )
    intro_title: Optional[str] = Field(
        default=None,
        description="可选。片头淡入叠加显示的电影标题文案。",
    )
    fade_out_outro_sec: float = Field(
        default=0.0,
        description="可选。成片结尾黑场与伴音同步淡出的秒数（如 1.0 秒；默认 0.0）。",
    )
    target_width: int = Field(
        default=0,
        description="可选。输出宽度像素；默认 0 自动继承第一段视频的原生分辨率宽度。",
    )
    target_height: int = Field(
        default=0,
        description="可选。输出高度像素；默认 0 自动继承第一段视频的原生分辨率高度。",
    )


@tool(
    "video_edit_and_stitch",
    description=(
        "使用本机 FFmpeg 对多段画布视频执行自动剪辑（按秒裁剪截齐）、柔和淡入淡出转场、"
        "原生立体声音轨无缝拼接、可选旁白混音与字幕封装，生成完整长视频成片并自动写入当前画布。"
        "适合将多段 15 秒分镜视频自动剪辑拼接为完整的 1 分钟（60 秒）电影短片。"
    ),
    args_schema=VideoEditAndStitchInput,
)
async def video_edit_and_stitch_tool(
    config: RunnableConfig,
    video_files: Optional[List[str]] = None,
    clip_edits: Optional[List[ClipEditSpec]] = None,
    target_clip_duration: Optional[float] = None,
    transition_fade_sec: float = 0.2,
    preserve_clip_audio: bool = True,
    narration_audio: Optional[str] = None,
    bgm_audio: Optional[str] = None,
    bgm_volume: float = 0.28,
    enable_audio_ducking: bool = True,
    subtitles: Optional[List[SubtitleLineSpec]] = None,
    burn_subtitles: bool = False,
    normalize_audio_loudness: bool = False,
    intro_title: Optional[str] = None,
    fade_out_outro_sec: float = 0.0,
    target_width: int = 0,
    target_height: int = 0,
) -> str:
    """调用本地 FFmpeg 完成多段分镜视频自动剪辑与拼接成片。"""
    ctx = (config or {}).get("configurable") or {}
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    _logger.info(
        "🎬 [video_edit_and_stitch] canvas=%s clips=%s",
        canvas_id,
        video_files or [c.file for c in (clip_edits or [])],
    )
    try:
        edits_dicts: Optional[List[Dict[str, Any]]] = (
            [item.model_dump() for item in clip_edits] if clip_edits else None
        )
        subs_dicts: Optional[List[Dict[str, Any]]] = (
            [item.model_dump() for item in subtitles] if subtitles else None
        )
        res = await compose_storyboard_clips(
            video_files=video_files,
            clip_edits=edits_dicts,
            target_clip_duration=target_clip_duration,
            transition_fade_sec=transition_fade_sec,
            preserve_clip_audio=preserve_clip_audio,
            target_width=target_width,
            target_height=target_height,
            narration_audio=narration_audio,
            bgm_audio=bgm_audio,
            bgm_volume=bgm_volume,
            enable_audio_ducking=enable_audio_ducking,
            subtitles=subs_dicts,
            normalize_audio_loudness=normalize_audio_loudness,
            burn_subtitles=burn_subtitles,
            intro_title=intro_title,
            fade_out_outro_sec=fade_out_outro_sec,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        fid = res["file_id"]
        return (
            f"video_edit_and_stitch executed successfully ![video_id: {fid}](/api/file/{fid}) "
            f"(element_id={res.get('element_id')}, duration={res['duration_sec']}s, "
            f"resolution={res['width']}x{res['height']}, clips={res['clip_count']}, has_audio={res['has_audio']})"
        )
    except Exception as exc:
        _logger.error("video_edit_and_stitch 执行失败: %s", exc)
        return f"video_edit_and_stitch failed: {exc}"
