"""程序说明：管理并过滤后端可用工具注册表，仅注册系统必要工具与已启用的本地生成工作流。"""
import asyncio
from utils.log_sanitizer import get_sanitized_logger
_logger = get_sanitized_logger(__name__)
import traceback
from typing import Dict
from langchain_core.tools import BaseTool
from models.tool_model import ToolInfo
from tools.canvas_tools import (
    canvas_arrange_elements_tool,
    canvas_connect_and_badge_tool,
)
from tools.comfy_dynamic import build_tool
from tools.video_edit_tools import video_edit_and_stitch_tool
from tools.write_plan import write_plan_tool
from services.comfy_instance_service import comfy_instance_service
from services.config_service import config_service
from services.db_service import db_service

# 保留空映射供外部 CapabilityProvider 显式扩展，默认不再注册 Jaaz/第三方闭源云端工具。
TOOL_MAPPING: Dict[str, ToolInfo] = {}


class ToolService:
    def __init__(self):
        self.tools: Dict[str, ToolInfo] = {}
        # 首轮 initialize 完成前接口应等待，避免启动窗口内返回空工具列表
        self.ready = asyncio.Event()
        self._register_required_tools()

    def _register_required_tools(self):
        """注册必须的系统工具（计划制定与画布原生排版标注）"""
        try:
            self.tools["write_plan"] = {
                "provider": "system",
                "tool_function": write_plan_tool,
            }
            self.tools["canvas_arrange_elements"] = {
                "provider": "system",
                "tool_function": canvas_arrange_elements_tool,
            }
            self.tools["canvas_connect_and_badge"] = {
                "provider": "system",
                "tool_function": canvas_connect_and_badge_tool,
            }
            self.tools["video_edit_and_stitch"] = {
                "provider": "system",
                "tool_function": video_edit_and_stitch_tool,
                "display_name": "FFmpeg 视频自动剪辑与拼接",
                "type": "video",
                "capability": "i2v",
            }
        except ImportError as e:
            _logger.info(f"❌ 注册必须工具失败: {e}")
    def register_tool(self, tool_id: str, tool_info: ToolInfo):
        """注册单个工具"""
        if tool_id in self.tools:
            _logger.info(f"🔄 TOOL ALREADY REGISTERED: {tool_id}")
            return

        self.tools[tool_id] = tool_info

    async def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """等待首轮工具注册完成；超时返回 False，调用方可继续使用当前注册表。"""
        try:
            await asyncio.wait_for(self.ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def initialize(self):
        self.clear_tools()
        try:
            for provider_name, provider_config in config_service.app_config.items():
                # register all tools by api provider with api key
                if provider_config.get("api_key", ""):
                    for tool_id, tool_info in TOOL_MAPPING.items():
                        if tool_info.get("provider") == provider_name:
                            self.register_tool(tool_id, tool_info)

            # 存在任意启用的 ComfyUI 实例或旧配置 URL 时，注册已启用的 ComfyUI 工作流工具
            instances = await comfy_instance_service.ensure_default_instance()
            has_enabled_instance = any(item.get("enabled", 1) for item in instances)
            legacy_url = str(
                config_service.app_config.get("comfyui", {}).get("url", "")
            ).strip()
            if has_enabled_instance or legacy_url:
                await register_comfy_tools()
        except Exception as e:
            _logger.info(f"❌ Failed to initialize tool service: {e}")
            traceback.print_stack()
        finally:
            self.ready.set()

    def get_tool(self, tool_name: str) -> BaseTool | None:
        tool_info = self.tools.get(tool_name)
        return tool_info.get("tool_function") if tool_info else None

    def remove_tool(self, tool_id: str):
        self.tools.pop(tool_id)

    def get_all_tools(self) -> Dict[str, ToolInfo]:
        return self.tools.copy()

    def clear_tools(self):
        self.tools.clear()
        # 重新注册必须的工具
        self._register_required_tools()


tool_service = ToolService()


async def register_comfy_tools() -> Dict[str, BaseTool]:
    """仅将数据库中启用状态（enabled=1）的 ComfyUI 工作流注册为 Agent 可选工具。"""
    dynamic_comfy_tools: Dict[str, BaseTool] = {}
    try:
        workflows = await db_service.list_comfy_workflows(enabled_only=True)
    except Exception as exc:  # pragma: no cover
        _logger.info("[comfy_dynamic] Failed to list comfy workflows:", exc)
        traceback.print_stack()
        return {}

    for wf in workflows:
        try:
            if not wf.get("enabled", 1):
                continue
            tool_fn = build_tool(wf)
            unique_name = f"comfyui_{wf['name']}"
            dynamic_comfy_tools[unique_name] = tool_fn
            tool_service.register_tool(
                unique_name,
                {
                    "provider": "comfyui",
                    "tool_function": tool_fn,
                    "display_name": wf.get("display_name") or wf["name"],
                    "type": wf.get("output_kind") or "image",
                    "capability": wf.get("capability") or "t2i",
                },
            )
        except Exception as exc:  # pragma: no cover
            print(
                f"[comfy_dynamic] Failed to create tool for workflow {wf.get('id')}: {exc}"
            )
            traceback.print_exc()

    return dynamic_comfy_tools
