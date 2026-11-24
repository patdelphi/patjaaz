"""程序说明：按能力（capability）把可用生成工具分组，每组由独立智能体持有，避免把全部工具描述发给同一个模型。"""
from typing import Any, Dict, List, Mapping, Sequence

IMAGE_GROUP = "image_creator"
VIDEO_GROUP = "video_creator"
AUDIO_GROUP = "audio_creator"

# 组内能力清单；upscale / custom 依输出类型归组
_CAPABILITY_TO_GROUP: Dict[str, str] = {
    "t2i": IMAGE_GROUP,
    "i2i": IMAGE_GROUP,
    "inpaint": IMAGE_GROUP,
    "outpaint": IMAGE_GROUP,
    "rembg": IMAGE_GROUP,
    "t2v": VIDEO_GROUP,
    "i2v": VIDEO_GROUP,
    "tts": AUDIO_GROUP,
    "asr": AUDIO_GROUP,
    "music": AUDIO_GROUP,
}
_TYPE_TO_GROUP: Dict[str, str] = {
    "image": IMAGE_GROUP,
    "video": VIDEO_GROUP,
    "audio": AUDIO_GROUP,
}

# 展示给规划智能体与其他智能体的组职责说明
GROUP_ROLE_DESCRIPTIONS: Dict[str, str] = {
    IMAGE_GROUP: "Generate or edit images (text-to-image, image editing, inpaint, remove background).",
    VIDEO_GROUP: "Generate or process videos (text-to-video, image-to-video, video upscale).",
    AUDIO_GROUP: "Generate or process audio (speech, music, transcription).",
}

# 稳定的组顺序，保证规划智能体与交接工具列表可预测
GROUP_ORDER: Sequence[str] = (IMAGE_GROUP, VIDEO_GROUP, AUDIO_GROUP)


def resolve_tool_group(tool: Mapping[str, Any]) -> str:
    """根据工具的 capability 与输出类型决定所属智能体分组。"""
    capability = str(tool.get("capability") or "").strip().lower()
    output_type = str(tool.get("type") or "").strip().lower()
    if capability in _CAPABILITY_TO_GROUP:
        return _CAPABILITY_TO_GROUP[capability]
    if output_type in _TYPE_TO_GROUP:
        return _TYPE_TO_GROUP[output_type]
    return IMAGE_GROUP


def group_tools_by_capability(
    tool_list: Sequence[Mapping[str, Any]],
) -> Dict[str, List[Any]]:
    """把工具列表分到各能力组，只返回非空分组；一个工具都没有时保留空的图像组以便仍可对话。"""
    grouped: Dict[str, List[Any]] = {name: [] for name in GROUP_ORDER}
    for tool in tool_list or []:
        if isinstance(tool, Mapping):
            grouped[resolve_tool_group(tool)].append(tool)

    result = {name: grouped[name] for name in GROUP_ORDER if grouped[name]}
    if not result:
        result[IMAGE_GROUP] = []
    return result
