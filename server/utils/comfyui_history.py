"""程序说明：从 ComfyUI 任务历史中提取终端保存节点输出（过滤 LoadVideo/LoadImage 等中间预览），并阻止空输出被当作成功。"""
from typing import Any, Dict, Iterable, Optional, Set
from urllib.parse import urlencode

COMFY_OUTPUT_KEYS = ("images", "gifs", "videos", "audio")

# 输入加载与对比预览节点只用于画布调试展示，不应作为生成结果写入 Jaaz 画布
EXCLUDED_LOADER_PREVIEW_NODE_TYPES = frozenset(
    {
        "LoadImage",
        "LoadImageMask",
        "LoadVideo",
        "LoadAudio",
        "VHS_LoadVideo",
        "VHS_LoadAudio",
        "ImageCompare",
        "ImageCompareKJ",
    }
)

# 标准终端结果保存节点；当工作流存在任意此类节点时，仅提取此类节点的输出（自动忽略调试 PreviewImage 等中间节点）
TERMINAL_SAVE_NODE_TYPES = frozenset(
    {
        "SaveImage",
        "SaveVideo",
        "SaveAnimatedWEBP",
        "SaveAnimatedPNG",
        "SaveAudio",
        "SaveAudioMP3",
        "SaveAudioOpus",
        "VHS_VideoCombine",
    }
)


def resolve_allowed_output_node_ids(
    workflow: Optional[Dict[str, Any]] = None,
    explicit_outputs: Optional[Iterable[Any]] = None,
) -> Optional[Set[str]]:
    """根据显式 outputs 白名单或工作流节点类型计算允许落盘的节点 ID 集合；无法推断时返回 None 表示不限制。"""
    if explicit_outputs:
        explicit_set: Set[str] = set()
        for item in explicit_outputs:
            if isinstance(item, dict) and item.get("node_id"):
                explicit_set.add(str(item["node_id"]))
            elif isinstance(item, (str, int)) and str(item).strip():
                explicit_set.add(str(item).strip())
        if explicit_set:
            return explicit_set

    if not isinstance(workflow, dict) or not workflow:
        return None

    non_loader_ids: Set[str] = set()
    terminal_save_ids: Set[str] = set()
    for node_id, node_obj in workflow.items():
        if not isinstance(node_obj, dict):
            continue
        nid = str(node_id)
        class_type = str(node_obj.get("class_type") or "").strip()
        if class_type in EXCLUDED_LOADER_PREVIEW_NODE_TYPES:
            continue
        non_loader_ids.add(nid)
        if class_type in TERMINAL_SAVE_NODE_TYPES or class_type.startswith("Save"):
            terminal_save_ids.add(nid)

    if terminal_save_ids:
        return terminal_save_ids
    return non_loader_ids if non_loader_ids else None


def history_output_urls(
    history_record: Any,
    base_url: str,
    workflow: Optional[Dict[str, Any]] = None,
    explicit_outputs: Optional[Iterable[Any]] = None,
):
    """从单个 ComfyUI 历史记录中提取允许输出节点的图像、动图、视频和音频 /view 地址。"""
    if not isinstance(history_record, dict):
        return []

    node_outputs = history_record.get("outputs", {})
    if not isinstance(node_outputs, dict):
        return []

    allowed_ids = resolve_allowed_output_node_ids(workflow, explicit_outputs)

    urls = []
    for node_id, node_output in node_outputs.items():
        if allowed_ids is not None and str(node_id) not in allowed_ids:
            continue
        if not isinstance(node_output, dict):
            continue
        for output_type in COMFY_OUTPUT_KEYS:
            media_items = node_output.get(output_type, [])
            if not isinstance(media_items, list):
                continue
            for media in media_items:
                if not isinstance(media, dict) or not media.get("filename"):
                    continue
                url = f"{base_url.rstrip('/')}/view?{urlencode(media)}"
                if url not in urls:
                    urls.append(url)
    return urls


def require_generation_outputs(outputs):
    """空结果必须报错，避免向聊天和画布返回虚假的成功状态。"""
    if not outputs:
        raise RuntimeError(
            "ComfyUI 任务结束，但未返回图像或视频文件；"
            "请检查工作流的 SaveImage/SaveVideo 输出节点。"
        )
    return outputs
