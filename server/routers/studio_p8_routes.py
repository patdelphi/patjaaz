"""程序说明：阶段 P8 创作工作台扩展子路由（一键剧本拆镜铺排与画布媒体完整性健康巡检）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.canvas_health_service import inspect_canvas_media_health
from services.storyboard_planner_service import plan_and_layout_storyboard_on_canvas
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)
router = APIRouter()


class PlanStoryboardRequest(BaseModel):
    canvas_id: str
    film_title: str = "短片分镜企划"
    character_anchor_desc: str = ""
    raw_script: str = ""
    shots: Optional[List[Dict[str, Any]]] = None
    shot_duration_sec: float = 15.0
    session_id: str = ""


@router.post("/plan_storyboard")
async def post_plan_storyboard_endpoint(req: PlanStoryboardRequest):
    """解析多行剧本或结构化分镜列表并在目标画布一键铺排角色框与分镜泳道矩阵（P8-1）。"""
    try:
        return await plan_and_layout_storyboard_on_canvas(
            req.canvas_id,
            film_title=req.film_title,
            character_anchor_desc=req.character_anchor_desc,
            raw_script=req.raw_script,
            shots=req.shots,
            shot_duration_sec=req.shot_duration_sec,
            session_id=req.session_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("一键剧本拆镜铺板失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/canvas_health/{canvas_id}")
async def get_canvas_health_endpoint(canvas_id: str):
    """巡检指定画布全部媒体元素的本地落盘存在性、血缘覆盖与云盘映射状态（P8-3）。"""
    try:
        return await inspect_canvas_media_health(canvas_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("巡检画布健康状态失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
