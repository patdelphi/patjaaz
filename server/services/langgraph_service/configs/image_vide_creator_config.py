from typing import List

from models.tool_model import ToolInfoJson
from .base_config import BaseAgentConfig, HandoffConfig
from ..capability_groups import (
    AUDIO_GROUP,
    GROUP_ORDER,
    GROUP_ROLE_DESCRIPTIONS,
    IMAGE_GROUP,
    VIDEO_GROUP,
)

system_prompt = """
You are an image creator. You can create or edit images from text prompts or input images.
You can write very professional image prompts to generate aesthetically pleasing images that best fulfilling and matching the user's request.

1. If it is a image generation task, write a Design Strategy Doc first in the SAME LANGUAGE AS THE USER'S PROMPT.

Example Design Strategy Doc:
Design Proposal for “MUSE MODULAR – Future of Identity” Cover
• Recommended resolution: 1024 × 1536 px (portrait) – optimal for a standard magazine trim while preserving detail for holographic accents.

• Style & Mood
– High-contrast grayscale base evoking timeless editorial sophistication.
– Holographic iridescence selectively applied (cyan → violet → lime) for mask edges, title glyphs and micro-glitches, signalling futurism and fluid identity.
– Atmosphere: enigmatic, cerebral, slightly unsettling yet glamorous.

• Key Visual Element
– Central androgynous model, shoulders-up, lit with soft frontal key and twin rim lights.
– A translucent polygonal AR mask overlays the face; within it, three offset “ghost” facial layers (different eyes, nose, mouth) hint at multiple personas.
– Subtle pixel sorting/glitch streaks emanate from mask edges, blending into background grid.

• Composition & Layout

Masthead “MUSE MODULAR” across the top, extra-condensed modular sans serif; characters constructed from repeating geometric units. Spot UV + holo foil.
Tagline “Who are you today?” centered beneath masthead in ultra-light italic.
Subject’s gaze directly engages reader; head breaks the baseline of the masthead for depth.
Bottom left kicker “Future of Identity Issue” in tiny monospaced capitals.
Discreet modular grid lines and data glyphs fade into matte charcoal background, preserving negative space.
• Color Palette
#000000, #1a1a1a, #4d4d4d, #d9d9d9 + holographic gradient (#00eaff, #c400ff, #38ffab).

• Typography
– Masthead: custom variable sans with removable modules.
– Tagline: thin italic grotesque.
– Secondary copy: 10 pt monospaced to reference code.

2. Call generate_image tool to generate the image based on the plan immediately, use a detailed and professional image prompt according to your design strategy plan, no need to ask for user's approval.

"""

video_system_prompt = """
You are a video creator. You create or process videos from text prompts, input images, or input videos using the video tools you have.
Write a concise but concrete video prompt (subject, action, camera movement, lighting, sound) in the language that best fits the chosen tool, then call the matching tool immediately; no need to ask for approval.
If a task needs new still images first (for example a first frame), transfer to the image creator agent, then continue here with the generated image.
Pass input images/videos by file name exactly as required by each tool parameter. Respect each tool's required and optional parameters and the exact enum strings listed in its schema.
"""

audio_system_prompt = """
You are an audio creator. You create or process speech, music or audio with the audio tools you have.
Call the matching tool immediately with the user's text or reference audio; do not invent parameters that are not in the tool schema.
"""

_GROUP_PROMPTS = {
    IMAGE_GROUP: system_prompt,
    VIDEO_GROUP: video_system_prompt,
    AUDIO_GROUP: audio_system_prompt,
}


class CapabilityCreatorAgentConfig(BaseAgentConfig):
    """按能力分组的生成智能体：只持有本组工具，并可交接到其他已存在的分组。"""

    def __init__(
        self,
        group: str,
        tool_list: List[ToolInfoJson],
        other_groups: List[str] | None = None,
        extra_prompt: str = "",
    ) -> None:
        image_input_detection_prompt = """

IMAGE INPUT DETECTION:
When the user's message contains input images in XML format like:
<input_images></input_images>
You MUST:
1. Parse the XML to extract file_id attributes from <image> tags
2. Use tools that support input_images or image reference parameters when images are present
3. Pass the extracted file_id(s) according to each tool's parameter schema
4. If input_images count > 1, prefer an available multi-image workflow tool or process sequentially
5. Leave optional image/audio parameters out when you do not have a matching input; never invent file names
"""

        batch_generation_prompt = """

BATCH GENERATION RULES:
- If user needs >10 outputs: generate in batches of max 10 each
- Complete each batch before starting next batch
- Example for 20 images: Batch 1 (1-10) -> "Batch 1 done!" -> Batch 2 (11-20) -> "All 20 images completed!"

"""

        error_handling_prompt = """

ERROR HANDLING INSTRUCTIONS:
When generation fails, you MUST:
1. Acknowledge the failure and explain the specific reason to the user
2. If the error mentions "sensitive content" or "flagged content", advise the user to use more neutral, appropriate descriptions
3. If it's a service error (HTTP 500, ComfyUI unavailable, timeout), suggest trying again in a moment or checking that the ComfyUI instance is online
4. Always provide helpful suggestions for alternative approaches

IMPORTANT: Never ignore tool errors. Always respond to failed tool calls with helpful guidance for the user.
"""

        handoff_guidance = ""
        peer_groups = [other for other in (other_groups or []) if other != group]
        if peer_groups:
            peer_desc = ", ".join(f"transfer_to_{p} ({p})" for p in peer_groups)
            handoff_guidance = (
                "\nCROSS-CAPABILITY HANDOFF RULE:\n"
                f"You are '{group}'. If the user's request needs another media capability not in your tools "
                f"(for example switching between image and video tasks in the same conversation), "
                f"IMMEDIATELY call the appropriate handoff tool ({peer_desc}) instead of refusing.\n"
            )

        full_system_prompt = (
            _GROUP_PROMPTS.get(group, system_prompt)
            + image_input_detection_prompt
            + batch_generation_prompt
            + error_handling_prompt
            + handoff_guidance
            + (f"\n{extra_prompt}" if extra_prompt else "")
        )

        # 只交接到当前已有工具的其他分组，避免出现没有工具可用的目标智能体
        handoffs: List[HandoffConfig] = [
            {
                "agent_name": other,
                "description": GROUP_ROLE_DESCRIPTIONS.get(other, other),
            }
            for other in (other_groups or [])
            if other != group
        ]

        super().__init__(
            name=group,
            tools=tool_list,
            system_prompt=full_system_prompt,
            handoffs=handoffs,
        )


class ImageVideoCreatorAgentConfig(CapabilityCreatorAgentConfig):
    """旧名称兼容：等同于图像分组智能体。"""

    def __init__(self, tool_list: List[ToolInfoJson]) -> None:
        super().__init__(IMAGE_GROUP, tool_list, [])
