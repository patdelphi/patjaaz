"""程序说明：面向规划与创作智能体的一键剧本拆镜铺排系统工具（canvas_plan_storyboard，P8-1）。"""
from __future__ import annotations

from typing import List, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.storyboard_planner_service import plan_and_layout_storyboard_on_canvas
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)


class StoryboardShotSpec(BaseModel):
    """单镜分镜脚本规格。"""

    title: str = Field(default="", description="镜头标题，如 '夜雨入巷'")
    visual: str = Field(description="画面主体、动作与光影构图描述")
    camera: str = Field(default="平稳推进", description="镜头运动方式")
    dialogue: str = Field(default="", description="可选角色台词或旁白字幕")
    sfx: str = Field(default="环境同期声", description="环境音效与氛围音乐描述")
    duration_sec: float = Field(default=15.0, description="单镜时长秒数，默认 15.0")


class CanvasPlanStoryboardInput(BaseModel):
    """一键在画布铺排完整短片分镜矩阵的参数定义。"""

    film_title: str = Field(description="短片标题，如 '江南夜雨·一盏江湖'")
    character_anchor_desc: str = Field(
        default="",
        description="全片主角面容、服装、时代道具与整体视觉风格设定。",
    )
    shots: Optional[List[StoryboardShotSpec]] = Field(
        default=None,
        description="结构化分镜列表（推荐传入 3–8 个镜头）。若传入 raw_script 可留空。",
    )
    raw_script: str = Field(
        default="",
        description="可选。按行分隔的分镜脚本大纲（未传 shots 时自动按行解析）。",
    )
    shot_duration_sec: float = Field(
        default=15.0,
        description="默认单镜秒数（默认 15.0s）。",
    )


@tool(
    "canvas_plan_storyboard",
    description=(
        "在当前无限画布上一键创建完整的电影分镜故事板矩阵：包含顶部角色定妆设定框、横向对齐的多幕分镜 Frame 泳道、"
        "结构化脚本卡片（画面/运镜/台词/音效）、递增序号角标与闭合流转块箭头。"
        "适合在策划 30 秒～3 分钟多镜头短片开拍前一次性完成专业分镜排布。"
    ),
    args_schema=CanvasPlanStoryboardInput,
)
async def canvas_plan_storyboard_tool(
    config: RunnableConfig,
    film_title: str,
    character_anchor_desc: str = "",
    shots: Optional[List[StoryboardShotSpec]] = None,
    raw_script: str = "",
    shot_duration_sec: float = 15.0,
) -> str:
    """原子生成多幕分镜泳道与脚本卡并实时同步前端画布。"""
    ctx = (config or {}).get("configurable") or {}
    canvas_id = str(ctx.get("canvas_id") or "")
    session_id = str(ctx.get("session_id") or "")
    if not canvas_id:
        return "canvas_plan_storyboard skipped: missing canvas_id"
    try:
        shots_dicts = [s.model_dump() for s in shots] if shots else None
        res = await plan_and_layout_storyboard_on_canvas(
            canvas_id,
            film_title=film_title,
            character_anchor_desc=character_anchor_desc,
            raw_script=raw_script,
            shots=shots_dicts,
            shot_duration_sec=shot_duration_sec,
            session_id=session_id,
        )
        return (
            f"canvas_plan_storyboard executed successfully: laid out '{res['film_title']}' "
            f"({res['shot_count']} shots, total {res['total_duration_sec']}s, "
            f"frames={res['frame_ids']}, elements_added={res['created_element_count']})."
        )
    except Exception as exc:
        _logger.error("canvas_plan_storyboard 失败: %s", exc)
        return f"canvas_plan_storyboard failed: {exc}"
