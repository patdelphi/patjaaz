from typing import List
from .base_config import BaseAgentConfig, HandoffConfig
from ..capability_groups import GROUP_ROLE_DESCRIPTIONS, IMAGE_GROUP


class PlannerAgentConfig(BaseAgentConfig):
    """规划智能体 - 负责制定执行计划
    """

    def __init__(
        self,
        groups: List[str] | None = None,
        extra_prompt: str = "",
    ) -> None:
        # groups 为当前有可用工具的能力分组智能体名称；缺省仅图像组
        group_names = list(groups) if groups else [IMAGE_GROUP]
        group_lines = "\n".join(
            f"            - {name}: {GROUP_ROLE_DESCRIPTIONS.get(name, name)}" for name in group_names
        )
        system_prompt = f"""
            You are a design planning writing agent. Answer and write plan in the SAME LANGUAGE as the user's prompt. You should do:
            - Step 1. If it is a complex task requiring multiple steps, write a execution plan for the user's request using the SAME LANGUAGE AS THE USER'S PROMPT. You should breakdown the task into high level steps for the other agents to execute.
            - Step 2. If it is a generation or editing task, transfer the task to the matching creator agent IMMEDIATELY based on the plan, no need to ask for user's approval. Available creator agents:
{group_lines}
            For tasks that need several kinds of output (for example images first, then a video), transfer to the first creator; it can hand off to the next one.

            IMPORTANT RULES:
            1. You MUST complete the write_plan tool call and wait for its result BEFORE attempting to transfer to another agent
            2. Do NOT call multiple tools simultaneously
            3. Always wait for the result of one tool call before making another

            ALWAYS PAY ATTENTION TO IMAGE QUANTITY!
            - If user specifies a number (like "20 images", "generate 15 pictures"), you MUST include this exact number in your plan
            - When transferring to a creator agent, clearly communicate the required quantity
            - NEVER ignore or change the user's specified quantity
            - If no quantity is specified, assume 1 image

            For example, if the user ask to 'Generate a ads video for a lipstick product', the example plan is :
            ```
            [{{
                "title": "Design the video script",
                "description": "Design the video script for the ads video"
            }}, {{
                "title": "Generate the images",
                "description": "Design image prompts, generate the images for the story board"
            }}, {{
                "title": "Generate the video clips",
                "description": "Generate the video clips from the images"
            }}]
            ```
            """

        handoffs: List[HandoffConfig] = [
            {
                'agent_name': name,
                'description': f"Transfer user to {name}. About this agent: {GROUP_ROLE_DESCRIPTIONS.get(name, name)}",
            }
            for name in group_names
        ]

        if extra_prompt:
            system_prompt = f"{system_prompt}\n{extra_prompt}"

        super().__init__(
            name='planner',
            tools=[{'id': 'write_plan', 'provider': 'system'}],
            system_prompt=system_prompt,
            handoffs=handoffs
        )
