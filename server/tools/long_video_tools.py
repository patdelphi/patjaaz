"""程序说明：面向 LangGraph 智能体的长视频自动分块断点超分工具（video_upscale_chunked）与关键帧/尾帧接力提取工具（extract_video_frame）。"""
from __future__ import annotations

from typing import Literal, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.long_video_pipeline_service import (
    extract_video_anchor_frame,
    upscale_long_video_chunked,
)
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)


class ExtractVideoFrameInput(BaseModel):
    """提取视频首帧、尾帧或指定时刻关键帧的参数定义。"""

    video_file: str = Field(
        description="画布或本地工作区中的源视频文件名，如 'clip1.mp4'"
    )
    mode: Literal["last", "first", "timestamp"] = Field(
        default="last",
        description="抽帧模式：'last' 提取干净尾帧用于下一段视频首帧无缝接力，'first' 提取首帧，'timestamp' 按 timestamp_sec 指定秒数抽帧。",
    )
    timestamp_sec: float = Field(
        default=0.0,
        description="当 mode='timestamp' 时提取的秒数位置。",
    )
    place_on_canvas: bool = Field(
        default=True,
        description="是否将提取出的 PNG 锚点帧写入当前画布并记录血缘（默认 true）。",
    )


class VideoUpscaleChunkedInput(BaseModel):
    """长视频按内存安全分块 SeedVR2 超分与断点续跑参数定义。"""

    video_file: str = Field(
        default="",
        description="待超分的视频文件名（如 'composed_xxx.mp4'）。若通过 job_id 断点续跑可留空。",
    )
    job_id: Optional[str] = Field(
        default=None,
        description="可选。指定之前断线挂起（paused_offline）的分块超分任务 ID 继续执行。",
    )
    scale_multiplier: float = Field(
        default=2.0,
        description="分辨率放大倍数（默认 2.0 倍，如 928x512 -> 1856x1024）。",
    )
    slice_seconds: Optional[float] = Field(
        default=None,
        description="可选。单段切片秒数；默认不填则根据远端可用内存自动计算安全秒数（如 10.0s 或 15.0s）。",
    )


@tool(
    "extract_video_frame",
    description=(
        "使用内置 FFmpeg 从指定画布视频中提取高清 PNG 尾帧、首帧或任意秒数关键帧并写入画布。"
        "适合在制作 1～3 分钟多镜头长片时抽取上一段视频尾帧，传给下一段 image2video_first_frame 或 ref2video_dual 锁定人物面容、服饰与光影衔接。"
    ),
    args_schema=ExtractVideoFrameInput,
)
async def extract_video_frame_tool(
    config: RunnableConfig,
    video_file: str,
    mode: str = "last",
    timestamp_sec: float = 0.0,
    place_on_canvas: bool = True,
) -> str:
    """提取视频关键帧并返回可供后续图像/视频工作流直接引用的文件名。"""
    ctx = (config or {}).get("configurable") or {}
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    try:
        res = await extract_video_anchor_frame(
            video_file,
            mode=mode,
            timestamp_sec=timestamp_sec,
            place_on_canvas=place_on_canvas,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        fid = res["file_id"]
        return (
            f"extract_video_frame executed successfully ![id: {fid}](/api/file/{fid}) "
            f"(element_id={res.get('element_id')}, resolution={res['width']}x{res['height']}, "
            f"mode={res['mode']}, timestamp={res['timestamp_sec']}s)"
        )
    except Exception as exc:
        _logger.error("extract_video_frame 执行失败: %s", exc)
        return f"extract_video_frame failed: {exc}"


@tool(
    "video_upscale_chunked",
    description=(
        "对超过 8 秒的长视频（如 15 秒单镜或 60 秒成片）执行自动安全分块 SeedVR2 超分、断点续跑，并无损合流原视频完整立体声音轨写回画布。"
        "可避免整段长视频一次性超分引发远端百 GB 内存溢出；若 Colab 中途断线，重新调用会自动跳过已完成的切片继续超分。"
    ),
    args_schema=VideoUpscaleChunkedInput,
)
async def video_upscale_chunked_tool(
    config: RunnableConfig,
    video_file: str = "",
    job_id: Optional[str] = None,
    scale_multiplier: float = 2.0,
    slice_seconds: Optional[float] = None,
) -> str:
    """按安全切片秒数分块执行 SeedVR2 超分并合成高清有声长视频。"""
    ctx = (config or {}).get("configurable") or {}
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    try:
        res = await upscale_long_video_chunked(
            video_file=video_file,
            job_id=job_id,
            scale_multiplier=scale_multiplier,
            slice_seconds=slice_seconds,
            canvas_id=canvas_id,
            session_id=session_id,
        )
        if res.get("status") == "paused_offline":
            return (
                f"video_upscale_chunked paused_offline (job_id={res['job_id']}, "
                f"progress={res['completed_chunks']}/{res['total_chunks']}, error={res.get('error')}). "
                "远端实例恢复在线后传入相同 video_file 或 job_id 即可从断点继续超分。"
            )
        fid = res["file_id"]
        return (
            f"video_upscale_chunked executed successfully ![video_id: {fid}](/api/file/{fid}) "
            f"(job_id={res['job_id']}, resolution={res['width']}x{res['height']}, "
            f"duration={res['duration_sec']}s, chunks={res['completed_chunks']}/{res['total_chunks']}, "
            f"has_audio={res['has_audio']})"
        )
    except Exception as exc:
        _logger.error("video_upscale_chunked 执行失败: %s", exc)
        return f"video_upscale_chunked failed: {exc}"
