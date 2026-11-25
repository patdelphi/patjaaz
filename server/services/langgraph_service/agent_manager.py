from typing import List, Dict, Any, Optional
from utils.log_sanitizer import get_sanitized_logger
_logger = get_sanitized_logger(__name__)
from langgraph.prebuilt import create_react_agent  # type: ignore
from langgraph.graph.graph import CompiledGraph
from langchain_core.tools import BaseTool
from models.tool_model import ToolInfoJson
from services.langgraph_service.capability_groups import group_tools_by_capability
from services.langgraph_service.configs.image_vide_creator_config import CapabilityCreatorAgentConfig
from .configs import PlannerAgentConfig, create_handoff_tool, BaseAgentConfig
from services.tool_service import tool_service


class AgentManager:
    """智能体管理器 - 负责创建和管理所有智能体

    此类负责协调智能体配置的获取和实际 LangGraph 智能体的创建。
    """

    @staticmethod
    def create_agents(
        model: Any,
        tool_list: List[ToolInfoJson],
        system_prompt: str = ""
    ) -> List[CompiledGraph]:
        """创建所有智能体

        Args:
            model: 语言模型实例
            registered_tools: 已注册的工具名称列表
            system_prompt: 系统提示词

        Returns:
            List[Any]: 创建好的智能体列表
        """
        # 按能力把工具分到 image / video / audio 分组，每组由独立智能体持有
        grouped = group_tools_by_capability(tool_list)
        group_names = list(grouped.keys())
        for group_name, group_tools in grouped.items():
            _logger.info(f"🧩 能力分组 {group_name}: {[t.get('id') for t in group_tools]}")
        planner_config = PlannerAgentConfig(group_names, extra_prompt=system_prompt)
        planner_agent = AgentManager._create_langgraph_agent(
            model, planner_config)

        creator_agents: List[CompiledGraph] = []
        for group_name, group_tools in grouped.items():
            creator_config = CapabilityCreatorAgentConfig(
                group_name, group_tools, group_names, extra_prompt=system_prompt)
            creator_agents.append(
                AgentManager._create_langgraph_agent(model, creator_config))

        return [planner_agent, *creator_agents]

    @staticmethod
    def _create_langgraph_agent(
        model: Any,
        config: BaseAgentConfig
    ) -> CompiledGraph:
        """根据配置创建单个 LangGraph 智能体

        Args:
            model: 语言模型实例
            config: 智能体配置字典

        Returns:
            Any: 创建好的 LangGraph 智能体实例
        """
        # 创建智能体间切换工具
        handoff_tools: List[BaseTool] = []
        for handoff in config.handoffs:
            handoff_tool = create_handoff_tool(
                agent_name=handoff['agent_name'],
                description=handoff['description'],
            )
            if handoff_tool:
                handoff_tools.append(handoff_tool)

        # 获取业务工具，并为所有智能体挂载画布原生排版与连线标注系统工具（A2）
        business_tools: List[BaseTool] = []
        seen_tool_ids: set[str] = set()
        for tool_json in config.tools:
            tid = str(tool_json.get('id') or '')
            tool = tool_service.get_tool(tid)
            if tool and tid not in seen_tool_ids:
                business_tools.append(tool)
                seen_tool_ids.add(tid)

        for sys_canvas_tid in ('canvas_arrange_elements', 'canvas_connect_and_badge'):
            if sys_canvas_tid not in seen_tool_ids:
                sys_tool = tool_service.get_tool(sys_canvas_tid)
                if sys_tool:
                    business_tools.append(sys_tool)
                    seen_tool_ids.add(sys_canvas_tid)

        if config.name != 'planner' and 'video_edit_and_stitch' not in seen_tool_ids:
            stitch_tool = tool_service.get_tool('video_edit_and_stitch')
            if stitch_tool:
                business_tools.append(stitch_tool)
                seen_tool_ids.add('video_edit_and_stitch')

        # 创建并返回 LangGraph 智能体
        return create_react_agent(
            name=config.name,
            model=model,
            tools=[*business_tools, *handoff_tools],
            prompt=config.system_prompt
        )

    @staticmethod
    def get_last_active_agent(
        messages: List[Dict[str, Any]],
        agent_names: List[str]
    ) -> Optional[str]:
        """获取最后活跃的智能体

        Args:
            messages: 消息历史
            agent_names: 智能体名称列表

        Returns:
            Optional[str]: 最后活跃的智能体名称，如果没有则返回 None
        """
        for message in reversed(messages):
            if message.get('role') == 'assistant':
                message_name = message.get('name')
                if message_name and message_name in agent_names:
                    return message_name
        return None
