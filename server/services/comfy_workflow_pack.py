"""程序说明：解析、严格校验、自动生成草稿、扫描同步并导出项目 workflows/ 目录下的 ComfyUI 成对工作流文件。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from utils.path_security import PathSecurityError, safe_join

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
WORKFLOWS_DIR = os.path.join(REPO_ROOT, "workflows")

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
    for node_id, node in api_json.items():
        if isinstance(node, dict) and isinstance(node.get("class_type"), str):
            valid_nodes += 1
            if "inputs" in node and not isinstance(node["inputs"], dict):
                return [f"节点 {node_id} 的 inputs 必须为对象"]

    if valid_nodes == 0:
        return ["API JSON 中未找到任何包含 class_type 的有效 ComfyUI 节点"]
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
    """将用户输入名称规范为合法的纯英文数字下划线工具标识。"""
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", (raw_name or "").strip()).strip("_")
    return cleaned or "custom_workflow"


def validate_workflow_pack(
    api_json_raw: Any, config_json_raw: Any
) -> Dict[str, Any]:
    """严格校验一组 API JSON + Jaaz 配置文件，返回校验结果与标准化字段。"""
    errors: List[str] = []

    if isinstance(api_json_raw, str):
        try:
            api_json = json.loads(api_json_raw)
        except json.JSONDecodeError as exc:
            return {"valid": False, "errors": [f"API JSON 语法错误: {exc}"], "normalized": None}
    else:
        api_json = api_json_raw

    if isinstance(config_json_raw, str):
        try:
            config_json = json.loads(config_json_raw)
        except json.JSONDecodeError as exc:
            return {
                "valid": False,
                "errors": [f"Jaaz 配置文件 JSON 语法错误: {exc}"],
                "normalized": None,
            }
    else:
        config_json = config_json_raw

    errors.extend(validate_api_json(api_json))
    if not isinstance(config_json, dict):
        errors.append("Jaaz 配置文件必须为 JSON 对象")
        return {"valid": False, "errors": errors, "normalized": None}

    schema_ver = config_json.get("schema_version", 1)
    if schema_ver != 1:
        errors.append(f"不支持的 schema_version: {schema_ver}（当前仅支持 1）")

    name = str(config_json.get("name") or "").strip()
    if not name or not WORKFLOW_NAME_RE.fullmatch(name):
        errors.append("工作流 name 必须非空且只能包含字母、数字与下划线（例如 text2image_moss）")

    display_name = str(config_json.get("display_name") or name).strip()
    description = str(config_json.get("description") or "").strip()
    if not description:
        errors.append("工作流 description 不能为空，需说明用途和参数调用方式供 Agent 理解")

    capability = str(config_json.get("capability") or "t2i").strip().lower()
    if capability not in ALLOWED_CAPABILITIES:
        errors.append(f"不支持的 capability: {capability}")

    output_kind = str(config_json.get("output_kind") or "image").strip().lower()
    if output_kind not in ALLOWED_OUTPUT_KINDS:
        errors.append(f"不支持的 output_kind: {output_kind}（仅允许 image/video/audio）")

    seed_strategy = str(config_json.get("seed_strategy") or "random").strip().lower()
    if seed_strategy not in ALLOWED_SEED_STRATEGIES:
        errors.append(f"不支持的 seed_strategy: {seed_strategy}（仅允许 random/fixed/param）")

    enabled = bool(config_json.get("enabled", True))
    instance_id_raw = config_json.get("instance_id")
    instance_id = str(instance_id_raw).strip() if instance_id_raw else None

    inputs_raw = config_json.get("inputs", [])
    if not isinstance(inputs_raw, list):
        errors.append("配置项 inputs 必须为参数数组")
        inputs_raw = []

    seen_param_names: set[str] = set()
    normalized_inputs: List[Dict[str, Any]] = []
    api_valid = isinstance(api_json, dict) and not is_comfy_ui_graph_json(api_json)

    for idx, param in enumerate(inputs_raw):
        if not isinstance(param, dict):
            errors.append(f"inputs[{idx}] 必须为对象")
            continue

        param_name = str(param.get("name") or "").strip()
        param_type = str(param.get("type") or "string").strip().lower()
        node_id = str(param.get("node_id") or "").strip()
        node_input_name = str(param.get("node_input_name") or "").strip()
        required = bool(param.get("required", False))
        default_value = param.get("default_value")
        param_desc = str(param.get("description") or "").strip()
        options = param.get("options")

        if not param_name or not WORKFLOW_NAME_RE.fullmatch(param_name):
            errors.append(f"inputs[{idx}].name '{param_name}' 仅允许字母、数字与下划线")
        elif param_name in seen_param_names:
            errors.append(f"输入参数名重复: {param_name}")
        else:
            seen_param_names.add(param_name)

        if param_type not in ALLOWED_PARAM_TYPES:
            errors.append(f"参数 '{param_name}' 类型无效: {param_type}")

        if options is not None and not isinstance(options, list):
            errors.append(f"参数 '{param_name}' 的 options 必须为数组")

        if not node_id or not node_input_name:
            errors.append(f"参数 '{param_name or idx}' 缺少 node_id 或 node_input_name")
        elif api_valid:
            node_obj = api_json.get(node_id)
            if not isinstance(node_obj, dict):
                errors.append(
                    f"参数 '{param_name}' 引用的 node_id '{node_id}' 在 API JSON 中不存在"
                )
            else:
                node_inputs = node_obj.get("inputs")
                if not isinstance(node_inputs, dict) or node_input_name not in node_inputs:
                    errors.append(
                        f"参数 '{param_name}' 引用的节点输入 '{node_id}.{node_input_name}' "
                        "在 API JSON 中不存在"
                    )

        item: Dict[str, Any] = {
            "name": param_name,
            "type": param_type,
            "required": required,
            "node_id": node_id,
            "node_input_name": node_input_name,
            "default_value": default_value,
            "description": param_desc,
        }
        if isinstance(options, list):
            item["options"] = options
        normalized_inputs.append(item)

    if errors:
        return {"valid": False, "errors": errors, "normalized": None}

    normalized_config: Dict[str, Any] = {
        "schema_version": 1,
        "name": name,
        "display_name": display_name,
        "capability": capability,
        "output_kind": output_kind,
        "enabled": enabled,
        "instance_id": instance_id or "",
        "seed_strategy": seed_strategy,
        "description": description,
        "inputs": normalized_inputs,
        "outputs": config_json.get("outputs"),
    }
    checksum = compute_pack_checksum(api_json, normalized_config)
    return {
        "valid": True,
        "errors": [],
        "normalized": {
            "api_json": api_json,
            "config_json": normalized_config,
            "checksum": checksum,
        },
    }


def generate_draft_config(
    api_json_raw: Any, suggested_name: str = "custom_workflow"
) -> Dict[str, Any]:
    """基于单个 ComfyUI API JSON 自动识别常见可调节点，生成标准 jaaz.workflow.json 草稿。"""
    if isinstance(api_json_raw, str):
        api_json = json.loads(api_json_raw)
    else:
        api_json = api_json_raw

    api_errors = validate_api_json(api_json)
    if api_errors:
        raise WorkflowPackValidationError(api_errors)

    safe_name = _sanitize_workflow_name(suggested_name)
    has_load_image = False
    has_video_out = False
    has_audio_out = False
    inputs: List[Dict[str, Any]] = []
    used_names: set[str] = set()

    def _add_param(
        base_name: str,
        param_type: str,
        node_id: str,
        input_key: str,
        default_val: Any,
        required: bool,
        desc: str,
    ) -> None:
        candidate = base_name
        if candidate in used_names:
            candidate = f"{base_name}_{node_id}"
        used_names.add(candidate)
        inputs.append(
            {
                "name": candidate,
                "type": param_type,
                "required": required,
                "node_id": str(node_id),
                "node_input_name": input_key,
                "default_value": default_val,
                "description": desc,
            }
        )

    for node_id, node in api_json.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        cls_lower = class_type.lower()
        node_inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = str((node.get("_meta") or {}).get("title") or "").lower()

        if "video" in cls_lower or "vhs_videocombine" in cls_lower:
            has_video_out = True
        if "audio" in cls_lower:
            has_audio_out = True

        if "loadimage" in cls_lower and "image" in node_inputs and not isinstance(node_inputs["image"], list):
            has_load_image = True
            _add_param(
                "source_image",
                "image",
                str(node_id),
                "image",
                str(node_inputs["image"]),
                True,
                "待处理的输入图像文件名（由画布或用户上传提供）",
            )
            continue

        if ("cliptextencode" in cls_lower or "text" in cls_lower) and isinstance(
            node_inputs.get("text"), str
        ):
            is_negative = "neg" in title or "负面" in title
            _add_param(
                "negative_prompt" if is_negative else "positive_prompt",
                "string",
                str(node_id),
                "text",
                node_inputs["text"],
                not is_negative,
                "负面排除提示词" if is_negative else "正向画面/语音生成提示词",
            )
            continue

        for key in ("width", "height"):
            val = node_inputs.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool) and ("latent" in cls_lower or "size" in cls_lower):
                _add_param(
                    key,
                    "number",
                    str(node_id),
                    key,
                    int(val),
                    False,
                    f"输出{'宽度' if key == 'width' else '高度'}像素",
                )

        if isinstance(node_inputs.get("aspect_ratio"), str):
            _add_param(
                "aspect_ratio",
                "string",
                str(node_id),
                "aspect_ratio",
                node_inputs["aspect_ratio"],
                False,
                "输出画幅比例配置值",
            )

    if has_audio_out:
        output_kind = "audio"
        capability = "tts"
    elif has_video_out:
        output_kind = "video"
        capability = "i2v" if has_load_image else "t2v"
    else:
        output_kind = "image"
        capability = "i2i" if has_load_image else "t2i"

    return {
        "schema_version": 1,
        "name": safe_name,
        "display_name": safe_name.replace("_", " "),
        "capability": capability,
        "output_kind": output_kind,
        "enabled": True,
        "instance_id": "",
        "seed_strategy": "random",
        "description": (
            f"使用 ComfyUI 工作流 {safe_name} 执行"
            f"{'图像编辑' if capability == 'i2i' else '视频生成' if output_kind == 'video' else '音频生成' if output_kind == 'audio' else '图像生成'}任务。"
        ),
        "inputs": inputs,
    }


def save_pack_to_workflows_dir(
    api_json_raw: Any,
    config_json_raw: Any,
    workflows_dir: str = WORKFLOWS_DIR,
) -> Dict[str, Any]:
    """校验并将工作流成对文件写入项目固定 workflows/<name>/ 目录。"""
    validation = validate_workflow_pack(api_json_raw, config_json_raw)
    if not validation["valid"]:
        raise WorkflowPackValidationError(validation["errors"])

    normalized = validation["normalized"]
    api_json = normalized["api_json"]
    config_json = normalized["config_json"]
    wf_name = config_json["name"]

    os.makedirs(workflows_dir, exist_ok=True)
    target_dir = safe_join(workflows_dir, wf_name)
    os.makedirs(target_dir, exist_ok=True)

    api_path = safe_join(target_dir, "workflow.api.json")
    cfg_path = safe_join(target_dir, "jaaz.workflow.json")

    with open(api_path, "w", encoding="utf-8") as f:
        json.dump(api_json, f, ensure_ascii=False, indent=2)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config_json, f, ensure_ascii=False, indent=2)

    return {
        "source_mode": "pack_dir",
        "source_path": wf_name,
        "api_path": api_path,
        "config_path": cfg_path,
        "api_json": api_json,
        "config_json": config_json,
        "checksum": normalized["checksum"],
    }


def update_pack_enabled_flag(
    source_path: str,
    enabled: bool,
    workflows_dir: str = WORKFLOWS_DIR,
) -> bool:
    """将工作流启停状态回写到项目 workflows/ 目录对应的配置文件中。"""
    if not source_path:
        return False
    try:
        resolved = safe_join(workflows_dir, source_path)
    except PathSecurityError:
        return False

    cfg_path: Optional[str] = None
    if os.path.isdir(resolved):
        candidate = safe_join(resolved, "jaaz.workflow.json")
        if os.path.isfile(candidate):
            cfg_path = candidate
    elif resolved.endswith(".jaaz.json") and os.path.isfile(resolved):
        cfg_path = resolved
    elif resolved.endswith(".api.json"):
        prefix = resolved[: -len(".api.json")]
        if os.path.isfile(f"{prefix}.jaaz.json"):
            cfg_path = f"{prefix}.jaaz.json"

    if not cfg_path:
        return False

    with open(cfg_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return False
    payload["enabled"] = bool(enabled)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return True


def _load_json_pair(
    api_path: str,
    cfg_path: str,
    source_mode: str,
    source_path: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """读取并校验单组成对文件，返回 (有效条目, 错误条目)。"""
    try:
        with open(api_path, "r", encoding="utf-8-sig") as f:
            api_json = json.load(f)
        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            config_json = json.load(f)
    except Exception as exc:
        return None, {
            "source_path": source_path,
            "errors": [f"读取工作流文件失败: {exc}"],
        }

    validation = validate_workflow_pack(api_json, config_json)
    if not validation["valid"]:
        return None, {
            "source_path": source_path,
            "errors": validation["errors"],
        }

    normalized = validation["normalized"]
    return {
        "source_mode": source_mode,
        "source_path": source_path,
        "api_json": normalized["api_json"],
        "config_json": normalized["config_json"],
        "checksum": normalized["checksum"],
    }, None


def scan_workflows_dir(workflows_dir: str = WORKFLOWS_DIR) -> Dict[str, Any]:
    """扫描项目 workflows/ 目录下的所有子目录包与平铺成对文件，并逐一校验。"""
    os.makedirs(workflows_dir, exist_ok=True)
    valid_packs: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    entries = sorted(os.listdir(workflows_dir))
    # 1. 子目录形式: workflows/<dir>/{workflow.api.json, jaaz.workflow.json}
    for entry in entries:
        full = os.path.join(workflows_dir, entry)
        if not os.path.isdir(full):
            continue
        api_path = os.path.join(full, "workflow.api.json")
        cfg_path = os.path.join(full, "jaaz.workflow.json")
        if os.path.isfile(api_path) and os.path.isfile(cfg_path):
            pack, err = _load_json_pair(api_path, cfg_path, "pack_dir", entry)
            if pack:
                valid_packs.append(pack)
            if err:
                errors.append(err)
        elif os.path.isfile(api_path) or os.path.isfile(cfg_path):
            errors.append(
                {
                    "source_path": entry,
                    "errors": ["目录缺少配对文件（需要同时包含 workflow.api.json 与 jaaz.workflow.json）"],
                }
            )

    # 2. 平铺成对形式: workflows/<prefix>.api.json + workflows/<prefix>.jaaz.json
    api_files = {
        entry[: -len(".api.json")]: entry
        for entry in entries
        if os.path.isfile(os.path.join(workflows_dir, entry))
        and entry.endswith(".api.json")
    }
    cfg_files = {
        entry[: -len(".jaaz.json")]: entry
        for entry in entries
        if os.path.isfile(os.path.join(workflows_dir, entry))
        and entry.endswith(".jaaz.json")
    }

    for prefix in sorted(set(api_files.keys()) | set(cfg_files.keys())):
        if prefix not in api_files:
            errors.append(
                {
                    "source_path": cfg_files[prefix],
                    "errors": [f"缺少配对文件 {prefix}.api.json"],
                }
            )
            continue
        if prefix not in cfg_files:
            errors.append(
                {
                    "source_path": api_files[prefix],
                    "errors": [f"缺少配对文件 {prefix}.jaaz.json"],
                }
            )
            continue
        pack, err = _load_json_pair(
            os.path.join(workflows_dir, api_files[prefix]),
            os.path.join(workflows_dir, cfg_files[prefix]),
            "pack_pair",
            cfg_files[prefix],
        )
        if pack:
            valid_packs.append(pack)
        if err:
            errors.append(err)

    return {
        "workflows_dir": workflows_dir,
        "valid": valid_packs,
        "errors": errors,
    }


def summarize_api_json_for_agent(
    api_json_raw: Any,
    object_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """将 ComfyUI API JSON 压缩为供 AI Agent 分析的节点摘要，并按需融合 /object_info 枚举可选项。"""
    if isinstance(api_json_raw, str):
        api_json = json.loads(api_json_raw)
    else:
        api_json = api_json_raw

    api_errors = validate_api_json(api_json)
    if api_errors:
        raise WorkflowPackValidationError(api_errors)

    nodes_summary: List[Dict[str, Any]] = []
    for node_id, node in api_json.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "").strip()
        if not class_type:
            continue
        title = str((node.get("_meta") or {}).get("title") or "").strip()
        node_inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}

        obj_node = (
            object_info.get(class_type, {})
            if isinstance(object_info, dict)
            else {}
        )
        obj_input = obj_node.get("input") if isinstance(obj_node, dict) else {}
        required_spec = obj_input.get("required") if isinstance(obj_input, dict) else {}
        optional_spec = obj_input.get("optional") if isinstance(obj_input, dict) else {}

        literal_inputs: Dict[str, Any] = {}
        for input_name, input_val in node_inputs.items():
            # 过滤节点间连线 [source_node_id, slot_index]，只保留直接值供 AI 判断可调参数
            if (
                isinstance(input_val, list)
                and len(input_val) == 2
                and isinstance(input_val[0], (str, int))
                and isinstance(input_val[1], int)
            ):
                continue

            entry: Dict[str, Any] = {"value": input_val}
            spec = None
            if isinstance(required_spec, dict) and input_name in required_spec:
                spec = required_spec[input_name]
            elif isinstance(optional_spec, dict) and input_name in optional_spec:
                spec = optional_spec[input_name]

            if isinstance(spec, list) and spec:
                first = spec[0]
                if isinstance(first, list):
                    entry["input_type"] = "enum"
                    entry["options"] = first[:50]
                elif first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                    opts = spec[1].get("options")
                    if isinstance(opts, list):
                        entry["input_type"] = "enum"
                        entry["options"] = opts[:50]
                elif isinstance(first, str):
                    entry["input_type"] = first

            literal_inputs[str(input_name)] = entry

        nodes_summary.append(
            {
                "node_id": str(node_id),
                "class_type": class_type,
                "title": title,
                "literal_inputs": literal_inputs,
            }
        )

    return {
        "node_count": len(nodes_summary),
        "nodes": nodes_summary,
    }


async def sync_workflows_dir_to_db(
    db: Any = None,
    workflows_dir: str = WORKFLOWS_DIR,
) -> Dict[str, Any]:
    """扫描项目 workflows/ 目录并将有效成对工作流增量同步到 SQLite 数据库。"""
    if db is None:
        from services.db_service import db_service

        db = db_service

    scan_result = scan_workflows_dir(workflows_dir)
    existing_rows = await db.list_comfy_workflows(enabled_only=False)
    existing_by_name = {str(r.get("name") or ""): r for r in existing_rows}

    synced: List[Dict[str, Any]] = []
    changed = False

    for pack in scan_result["valid"]:
        cfg = pack["config_json"]
        name = str(cfg["name"])
        prev = existing_by_name.get(name)
        desired_enabled = 1 if cfg["enabled"] else 0

        # 仅在新增或校验和/启停状态/来源变更时写库并标记 changed，避免无谓写操作
        if (
            prev is None
            or str(prev.get("checksum") or "") != str(pack["checksum"])
            or int(prev.get("enabled", 1)) != desired_enabled
            or str(prev.get("source_mode") or "") != str(pack["source_mode"])
            or str(prev.get("source_path") or "") != str(pack["source_path"])
        ):
            res = await db.upsert_comfy_workflow_by_name(
                name=name,
                api_json=json.dumps(pack["api_json"], ensure_ascii=False),
                description=cfg["description"],
                inputs=json.dumps(cfg["inputs"], ensure_ascii=False),
                outputs=json.dumps(cfg.get("outputs"), ensure_ascii=False)
                if cfg.get("outputs") is not None
                else None,
                display_name=cfg["display_name"],
                capability=cfg["capability"],
                output_kind=cfg["output_kind"],
                instance_id=cfg["instance_id"] or None,
                source_mode=pack["source_mode"],
                source_path=pack["source_path"],
                seed_strategy=cfg["seed_strategy"],
                schema_version=cfg["schema_version"],
                enabled=desired_enabled,
                checksum=pack["checksum"],
            )
            synced.append({"id": res["id"], "name": name, "created": res["created"]})
            changed = True
        else:
            synced.append({"id": prev["id"], "name": name, "created": False})

    return {
        "workflows_dir": scan_result["workflows_dir"],
        "synced": synced,
        "errors": scan_result["errors"],
        "changed": changed,
    }


def build_export_pack(wf_record: Dict[str, Any]) -> Dict[str, Any]:
    """将数据库记录（含历史旧工作流）转换为标准 workflow.api.json + jaaz.workflow.json 成对格式。"""
    raw_api = wf_record.get("api_json")
    api_json = json.loads(raw_api) if isinstance(raw_api, str) else (raw_api or {})
    raw_inputs = wf_record.get("inputs")
    inputs = json.loads(raw_inputs) if isinstance(raw_inputs, str) else (raw_inputs or [])
    raw_outputs = wf_record.get("outputs")
    if isinstance(raw_outputs, str) and raw_outputs.strip():
        try:
            outputs = json.loads(raw_outputs)
        except json.JSONDecodeError:
            outputs = raw_outputs
    else:
        outputs = raw_outputs

    name = str(wf_record.get("name") or "workflow")
    config_json: Dict[str, Any] = {
        "schema_version": int(wf_record.get("schema_version") or 1),
        "name": name,
        "display_name": str(wf_record.get("display_name") or name),
        "capability": str(wf_record.get("capability") or "t2i"),
        "output_kind": str(wf_record.get("output_kind") or "image"),
        "enabled": bool(wf_record.get("enabled", 1)),
        "instance_id": str(wf_record.get("instance_id") or ""),
        "seed_strategy": str(wf_record.get("seed_strategy") or "random"),
        "description": str(wf_record.get("description") or ""),
        "inputs": inputs if isinstance(inputs, list) else [],
    }
    if outputs is not None:
        config_json["outputs"] = outputs

    return {"api_json": api_json, "config_json": config_json}
