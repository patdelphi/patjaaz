"""程序说明：阶段 P5 创作工作台扩展子路由（长视频分块断点超分、视频抽帧接力、Colab 换址热续跑与孤立临时切片扫描清理）。"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from services.gpu_compatibility_guard import hot_resume_colab_instance
from services.local_audio_service import extract_audio_from_video
from services.long_video_pipeline_service import (
    extract_video_anchor_frame,
    list_upscale_jobs,
    upscale_long_video_chunked,
)
from services.project_bundle_service import build_canvas_project_bundle_zip
from services.storage_cleanup_service import (
    delete_confirmed_orphan_files,
    scan_orphan_media_files,
)
from utils.log_sanitizer import get_sanitized_logger
from utils.path_security import PathSecurityError

_logger = get_sanitized_logger(__name__)
router = APIRouter()


class ExtractFrameRequest(BaseModel):
    video_file: str
    mode: str = "last"
    timestamp_sec: float = 0.0
    place_on_canvas: bool = True
    canvas_id: str = ""
    session_id: str = ""


class UpscaleChunkedRequest(BaseModel):
    video_file: str = ""
    job_id: Optional[str] = None
    scale_multiplier: float = 2.0
    slice_seconds: Optional[float] = None
    canvas_id: str = ""
    session_id: str = ""


class HotResumeColabRequest(BaseModel):
    new_base_url: str
    instance_id: Optional[str] = None
    resume_job_id: Optional[str] = None


class CleanupOrphansRequest(BaseModel):
    filenames: List[str]
    confirm: bool = False


class ExtractAudioRequest(BaseModel):
    video_file: str
    normalize_loudness: bool = False
    canvas_id: str = ""
    session_id: str = ""


@router.get("/upscale_jobs")
async def get_upscale_jobs_endpoint():
    """返回全部分块超分任务的进度与断点状态列表。"""
    try:
        jobs = await asyncio.to_thread(list_upscale_jobs)
        return {"jobs": jobs}
    except Exception as exc:
        _logger.error("读取分块超分任务列表失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/upscale_chunked")
async def post_upscale_chunked_endpoint(req: UpscaleChunkedRequest):
    """启动或从断点恢复长视频 SeedVR2 分块超分任务。"""
    try:
        return await upscale_long_video_chunked(
            video_file=req.video_file,
            job_id=req.job_id,
            scale_multiplier=req.scale_multiplier,
            slice_seconds=req.slice_seconds,
            canvas_id=req.canvas_id,
            session_id=req.session_id,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("分块超分接口异常: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/extract_frame")
async def post_extract_frame_endpoint(req: ExtractFrameRequest):
    """提取指定视频的首帧、尾帧或关键帧 PNG 并可选写入画布血缘。"""
    try:
        return await extract_video_anchor_frame(
            req.video_file,
            mode=req.mode,
            timestamp_sec=req.timestamp_sec,
            place_on_canvas=req.place_on_canvas,
            canvas_id=req.canvas_id,
            session_id=req.session_id,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("视频抽帧接口异常: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/hot_resume_colab")
async def post_hot_resume_colab_endpoint(req: HotResumeColabRequest):
    """热更新远端 Colab ComfyUI 隧道地址、清空旧上传缓存、探测硬件并列出待续跑任务。"""
    try:
        info = await hot_resume_colab_instance(
            req.new_base_url, instance_id=req.instance_id
        )
        jobs = await asyncio.to_thread(list_upscale_jobs)
        paused_jobs = [j for j in jobs if j.get("status") in ("paused_offline", "failed")]
        resumed_result = None
        if req.resume_job_id and info.get("online"):
            resumed_result = await upscale_long_video_chunked(job_id=req.resume_job_id)
        return {
            **info,
            "resumable_jobs": paused_jobs,
            "resumed_result": resumed_result,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("Colab 换址热续跑失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/orphan_files")
async def get_orphan_files_endpoint():
    """只读扫描未被任何画布或未完成任务引用的孤立临时切片与媒体文件。"""
    try:
        return await scan_orphan_media_files()
    except Exception as exc:
        _logger.error("扫描孤立文件失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cleanup_orphans")
async def post_cleanup_orphans_endpoint(req: CleanupOrphansRequest):
    """在显式二次确认（confirm=true）且核验无画布引用后删除指定孤立文件。"""
    try:
        return await delete_confirmed_orphan_files(
            req.filenames, confirm=req.confirm
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("清理孤立文件失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/extract_audio")
async def post_extract_audio_endpoint(req: ExtractAudioRequest):
    """从指定视频剥离 48kHz 立体声 MP3 音频卡片并可选写入画布（P6-2）。"""
    try:
        return await extract_audio_from_video(
            req.video_file,
            normalize_loudness=req.normalize_loudness,
            canvas_id=req.canvas_id,
            session_id=req.session_id,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("视频音轨剥离失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/export_bundle/{canvas_id}")
async def get_export_project_bundle_endpoint(
    canvas_id: str,
    include_media: bool = True,
):
    """将指定画布的制片单、云盘路径映射、字幕草稿与媒体文件打包为单个 ZIP 归档下载（P6-4）。"""
    try:
        bundle = await build_canvas_project_bundle_zip(
            canvas_id, include_media=include_media
        )
        return Response(
            content=bundle["zip_bytes"],
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{bundle["filename"]}"'
            },
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("导出制片工程包失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
