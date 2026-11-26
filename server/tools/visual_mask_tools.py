"""程序说明：面向图像智能体的局部涂抹遮罩转视觉高亮引导图工具（prepare_visual_mask_guide，P7-2）。"""
from __future__ import annotations

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from services.visual_mask_guide_service import prepare_visual_mask_guide
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)


class PrepareVisualMaskGuideInput(BaseModel):
    """原图与涂抹遮罩合成视觉引导图输入参数。"""

    source_image: str = Field(description="原始底图文件名，如 'orig.png'")
    mask_image: str = Field(description="涂抹生成的遮罩 PNG 文件名，如 'mask_xxx.png'")


@tool(
    "prepare_visual_mask_guide",
    description=(
        "当用户提供了一张原图与一张画笔涂抹遮罩图要求局部重绘（Inpaint）时，先调用本工具生成带红色半透明选区与红框的视觉引导图。"
        "随后将原图作为 reference_image_1（<Picture 1>）、返回的高亮引导图作为 reference_image_2（<Picture 2>）传入 image_edit_multiref_minimax_h3，"
        "在 edit_instruction 中指明仅修改 <Picture 2> 红色高亮框定区域、其余部分严格保持 <Picture 1> 不变。"
    ),
    args_schema=PrepareVisualMaskGuideInput,
)
async def prepare_visual_mask_guide_tool(
    source_image: str,
    mask_image: str,
) -> str:
    """生成局部重绘视觉引导图并返回引导图文件名与选区坐标方位。"""
    try:
        res = await prepare_visual_mask_guide(source_image, mask_image)
        gid = res["guide_file_id"]
        return (
            f"prepare_visual_mask_guide executed successfully: guide_file_id={gid} "
            f"![id: {gid}](/api/file/{gid}) "
            f"(source={res['source_file_id']}, region={res['region_label']}, "
            f"x={res['x_pct'][0]}%~{res['x_pct'][1]}%, y={res['y_pct'][0]}%~{res['y_pct'][1]}%). "
            f"Next call image_edit_multiref_minimax_h3 with reference_image_1='{res['source_file_id']}' (<Picture 1>) "
            f"and reference_image_2='{gid}' (<Picture 2>)."
        )
    except Exception as exc:
        _logger.error("prepare_visual_mask_guide 失败: %s", exc)
        return f"prepare_visual_mask_guide failed: {exc}"
