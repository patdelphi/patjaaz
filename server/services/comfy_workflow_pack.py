"""程序说明：解析、严格校验、扫描同步并导出项目 workflows/ 目录下的 ComfyUI 成对工作流文件（门面与同步主模块）。"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

from services.comfy_pack_common import (
    ALLOWED_CAPABILITIES,
    ALLOWED_OUTPUT_KINDS,
    ALLOWED_PARAM_TYPES,
    ALLOWED_SEED_STRATEGIES,
    REPO_ROOT,
    RESERVED_WORKFLOW_SUBDIRS,
    SOURCE_WORKFLOWS_DIR,
    SUMMARY_MAX_STRING_LEN,
    WORKFLOWS_DIR,
    WORKFLOW_NAME_RE,
    WorkflowPackValidationError,
    _SYNC_LOCK,
    _resolve_workflows_dir,
    _sanitize_workflow_name,
    compute_pack_checksum,
    is_comfy_ui_graph_json,
    unique_pack_name,
    validate_api_json,
)
from services.comfy_pack_draft import (
    _truncate_summary_value,
    build_export_pack,
    generate_draft_config,
    summarize_api_json_for_agent,
)
from services.comfy_pack_source import (
    _is_link_ref,
    compute_api_json_sha256,
    compute_file_sha256,
    detect_api_json_issues,
    repair_missing_primitive_nodes,
    scan_source_workflows_dir,
)
from utils.path_security import PathSecurityError, safe_join


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
    source_file = str(config_json.get("source_file") or "").strip()
    source_sha256 = str(config_json.get("source_sha256") or "").strip()
    if source_file:
        normalized_config["source_file"] = source_file
    if source_sha256:
        normalized_config["source_sha256"] = source_sha256

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

    # 同名目录已属于另一个来源文件时拒绝覆盖，提示调用方改名（自动导入走 unique_pack_name）
    existing_cfg_path = os.path.join(target_dir, "jaaz.workflow.json")
    new_src = str(config_json.get("source_file") or "")
    if new_src and os.path.isfile(existing_cfg_path):
        try:
            with open(existing_cfg_path, "r", encoding="utf-8-sig") as f:
                old_src = str((json.load(f) or {}).get("source_file") or "")
        except Exception:
            old_src = ""
        if old_src and old_src != new_src:
            raise WorkflowPackValidationError(
                [f"工作流名称 '{wf_name}' 已被来源文件 '{old_src}' 占用，请更换 name 后再导入"]
            )

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


_SCAN_WORKFLOWS_CACHE: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}
_SCAN_SOURCE_CACHE: Dict[str, Tuple[Tuple[Any, ...], Dict[str, Any]]] = {}


def _compute_dir_signature(root_dir: str, include_subdirs: bool = True) -> Tuple[Any, ...]:
    """基于文件相对路径、字节数与 mtime_ns 计算轻量目录指纹，未变更时跳过重复 JSON 解析与 SHA-256。"""
    if not os.path.isdir(root_dir):
        return ()
    items: List[Tuple[str, int, int]] = []
    for entry in sorted(os.listdir(root_dir)):
        if entry.startswith("."):
            continue
        full = os.path.join(root_dir, entry)
        try:
            st = os.stat(full)
        except OSError:
            continue
        if os.path.isfile(full):
            items.append((entry, st.st_size, st.st_mtime_ns))
        elif include_subdirs and os.path.isdir(full) and entry not in RESERVED_WORKFLOW_SUBDIRS:
            for sub in sorted(os.listdir(full)):
                if sub.startswith("."):
                    continue
                sub_full = os.path.join(full, sub)
                try:
                    sub_st = os.stat(sub_full)
                except OSError:
                    continue
                if os.path.isfile(sub_full):
                    items.append((f"{entry}/{sub}", sub_st.st_size, sub_st.st_mtime_ns))
    return tuple(items)


def scan_workflows_dir(workflows_dir: str = WORKFLOWS_DIR) -> Dict[str, Any]:
    """扫描项目 workflows/ 目录下的所有子目录包与平铺成对文件，并按 mtime 缓存避免重复磁盘校验。"""
    os.makedirs(workflows_dir, exist_ok=True)
    abs_dir = os.path.abspath(workflows_dir)
    sig = _compute_dir_signature(abs_dir, include_subdirs=True)
    cached = _SCAN_WORKFLOWS_CACHE.get(abs_dir)
    if cached is not None and cached[0] == sig:
        return copy.deepcopy(cached[1])

    valid_packs: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    entries = sorted(os.listdir(workflows_dir))
    # 1. 子目录形式: workflows/<dir>/{workflow.api.json, jaaz.workflow.json}
    for entry in entries:
        if entry.startswith(".") or entry in RESERVED_WORKFLOW_SUBDIRS:
            continue
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

    scan_res = {
        "workflows_dir": workflows_dir,
        "valid": valid_packs,
        "errors": errors,
    }
    _SCAN_WORKFLOWS_CACHE[abs_dir] = (sig, copy.deepcopy(scan_res))
    return scan_res



async def sync_workflows_dir_to_db(
    db: Any = None,
    workflows_dir: str = WORKFLOWS_DIR,
) -> Dict[str, Any]:
    """扫描项目 workflows/ 目录并将有效成对工作流增量同步到 SQLite（同进程内串行，避免启动与页面刷新并发写）。"""
    async with _SYNC_LOCK:
        return await _sync_workflows_dir_to_db_unlocked(db, workflows_dir)


def _workflow_settings_path() -> str:
    """工作流相关用户开关的存放文件（位于 USER_DATA_DIR，不随仓库提交）。"""
    user_data = str(os.getenv("USER_DATA_DIR") or "").strip()
    if not user_data:
        user_data = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_data"
        )
    return os.path.join(user_data, "workflow_settings.json")


def get_auto_import_source_enabled() -> bool:
    """是否允许服务启动时自动调用已配置文本模型导入 workflows/source/（默认关闭）。"""
    try:
        with open(_workflow_settings_path(), "r", encoding="utf-8-sig") as f:
            return bool((json.load(f) or {}).get("auto_import_source", False))
    except Exception:
        return False


def set_auto_import_source_enabled(enabled: bool) -> bool:
    """持久化自动导入开关，使用临时文件加原子替换避免写坏。"""
    path = _workflow_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    payload["auto_import_source"] = bool(enabled)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return bool(enabled)


def seed_bundled_workflows(bundled_dir: str, target_dir: str) -> List[str]:
    """首次启动时把随安装包提供的 workflows/ 默认包复制到用户可写目录；已存在的包不覆盖。"""
    copied: List[str] = []
    if not bundled_dir or not os.path.isdir(bundled_dir):
        return copied
    if os.path.abspath(bundled_dir) == os.path.abspath(target_dir):
        return copied

    os.makedirs(target_dir, exist_ok=True)
    for entry in sorted(os.listdir(bundled_dir)):
        src = os.path.join(bundled_dir, entry)
        dst = os.path.join(target_dir, entry)
        if os.path.exists(dst):
            continue
        if os.path.isdir(src):
            shutil.copytree(src, dst)
            copied.append(entry)
        elif os.path.isfile(src) and entry.lower().endswith((".json", ".md")):
            shutil.copy2(src, dst)
            copied.append(entry)
    return copied


async def _sync_workflows_dir_to_db_unlocked(
    db: Any = None,
    workflows_dir: str = WORKFLOWS_DIR,
) -> Dict[str, Any]:
    """sync_workflows_dir_to_db 的无锁实现。"""
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
