"""程序说明：从 ComfyUI 任务历史中恢复媒体输出，并阻止空输出被当作成功。"""
from urllib.parse import urlencode


def history_output_urls(history_record, base_url):
    """从单个 ComfyUI 历史记录中提取图像和动图的 /view 地址。"""
    if not isinstance(history_record, dict):
        return []

    node_outputs = history_record.get("outputs", {})
    if not isinstance(node_outputs, dict):
        return []

    urls = []
    for node_output in node_outputs.values():
        if not isinstance(node_output, dict):
            continue
        for output_type in ("images", "gifs"):
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
