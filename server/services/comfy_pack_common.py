"""程序说明：定义 ComfyUI 工作流包路径常量、校验异常类型与基础 API JSON 结构校验函数。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List


def _resolve_workflows_dir() -> str:
    """确定可写的工作流目录：环境变量优先；PyInstaller 冻结时用 USER_DATA_DIR/workflows；源码运行用仓库 workflows/。"""
    env_dir = str(os.getenv("JAAZ_WORKFLOWS_DIR") or "").strip()
    if env_dir:
        return os.path.abspath(env_dir)
    if getattr(sys, "frozen", False):
        user_data = str(os.getenv("USER_DATA_DIR") or "").strip()
        if user_data:
            return os.path.join(os.path.abspath(user_data), "workflows")
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(repo_root, "workflows")


REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
WORKFLOWS_DIR = _resolve_workflows_dir()
SOURCE_WORKFLOWS_DIR = os.path.join(WORKFLOWS_DIR, "source")
RESERVED_WORKFLOW_SUBDIRS = {"source"}
# 摘要中单个字符串值的最大保留长度，避免内置长提示词模板撑大 LLM 上下文
SUMMARY_MAX_STRING_LEN = 200
_SYNC_LOCK = asyncio.Lock()

WORKFLOW_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")

ALLOWED_CAPABILITIES = (
    "t2i",
    "i2i",
    "inpaint",
    "outpaint",
    "rembg",
    "upscale",
    "t2v",
    "i2v",
    "tts",
    "asr",
    "music",
    "custom",
)
ALLOWED_OUTPUT_KINDS = ("image", "video", "audio")
ALLOWED_SEED_STRATEGIES = ("random", "fixed", "param")
ALLOWED_PARAM_TYPES = (
    "string",
    "number",
    "boolean",
    "bool",
    "image",
    "audio",
    "video",
    "enum",
)


class WorkflowPackValidationError(ValueError):
    """ComfyUI 工作流文件对结构或节点引用不合法时抛出的异常。"""

    def __init__(self, errors: List[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def is_comfy_ui_graph_json(payload: Any) -> bool:
    """判断 JSON 是否为 ComfyUI 编辑器画布格式（nodes/links 数组）而非 API Format。"""
    if not isinstance(payload, dict):
        return False
    has_graph_arrays = isinstance(payload.get("nodes"), list) and (
        isinstance(payload.get("links"), list) or "last_node_id" in payload
    )
    if not has_graph_arrays:
        return False
    has_api_nodes = any(
        isinstance(node, dict) and "class_type" in node
        for key, node in payload.items()
        if key not in ("nodes", "links", "groups", "config", "extra")
    )
    return not has_api_nodes


def validate_api_json(api_json: Any) -> List[str]:
    """校验 ComfyUI API JSON 节点图结构，返回中文错误信息列表。"""
    if isinstance(api_json, str):
        try:
            api_json = json.loads(api_json)
        except json.JSONDecodeError as exc:
            return [f"API JSON 格式错误，无法解析: {exc}"]

    if not isinstance(api_json, dict) or not api_json:
        return ["API JSON 必须为非空节点字典对象"]

    if is_comfy_ui_graph_json(api_json):
        return [
            "检测到 ComfyUI 编辑器画布 JSON（含 nodes/links），"
            "请在 ComfyUI 启用 Dev Mode 后选择 Export (API) 导出 API JSON"
        ]

    valid_nodes = 0
    missing_class_nodes: List[str] = []
    for node_id, node in api_json.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        if not isinstance(ct, str) or not ct.strip():
            missing_class_nodes.append(str(node_id))
            continue
        valid_nodes += 1
        if "inputs" in node and not isinstance(node["inputs"], dict):
            return [f"节点 {node_id} 的 inputs 必须为对象"]

    if valid_nodes == 0:
        return ["API JSON 中未找到任何包含 class_type 的有效 ComfyUI 节点"]
    if missing_class_nodes:
        joined = ", ".join(missing_class_nodes[:8])
        return [
            f"节点 {joined} 缺少有效的 class_type（可能导出时缺失插件节点，请修复或重新通过 Export (API) 导出）"
        ]
    return []


def compute_pack_checksum(
    api_json: Dict[str, Any], config_json: Dict[str, Any]
) -> str:
    """计算成对工作流内容（除 enabled 开关外）的确定性 SHA-256 摘要。"""
    config_for_hash = dict(config_json)
    config_for_hash.pop("enabled", None)
    canonical = json.dumps(
        {"api_json": api_json, "config_json": config_for_hash},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sanitize_workflow_name(raw_name: str) -> str:
    """将用户输入名称规范为合法的纯英文数字下划线工具标识；含非 ASCII 字符时追加短哈希避免不同中文名冲突。"""
    raw = (raw_name or "").strip()
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_")
    if raw and any(ord(ch) > 127 for ch in raw):
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
        cleaned = f"{cleaned}_{digest}" if cleaned else f"wf_{digest}"
    return cleaned or "custom_workflow"


def unique_pack_name(
    name: str,
    source_file: str,
    workflows_dir: str = WORKFLOWS_DIR,
) -> str:
    """若 workflows/<name>/ 已被另一个来源文件占用，则追加数字后缀，避免静默覆盖。"""
    candidate = name
    index = 2
    while True:
        cfg_path = os.path.join(workflows_dir, candidate, "jaaz.workflow.json")
        if not os.path.isfile(cfg_path):
            return candidate
        try:
            with open(cfg_path, "r", encoding="utf-8-sig") as f:
                existing_src = str((json.load(f) or {}).get("source_file") or "")
        except Exception:
            existing_src = ""
        if not existing_src or existing_src == source_file:
            return candidate
        candidate = f"{name}_{index}"
        index += 1

