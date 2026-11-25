"""程序说明：提供 workflows/source/ 原始导出文件的哈希计算、断连/缺失原语检测修复与增量扫描。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from services.comfy_pack_common import (
    WorkflowPackValidationError,
    is_comfy_ui_graph_json,
    validate_api_json,
)


def compute_file_sha256(file_path: str) -> str:
    """计算本地文件二进制内容的 SHA-256 摘要，用于源文件去重与变更识别。"""
    digest = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def compute_api_json_sha256(api_json: Dict[str, Any]) -> str:
    """计算标准化 ComfyUI API JSON 内容的 SHA-256 摘要。"""
    canonical = json.dumps(
        api_json,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_link_ref(val: Any) -> bool:
    """判断节点输入值是否为 ComfyUI 节点连线引用 [node_id, slot_index]。"""
    return (
        isinstance(val, list)
        and len(val) == 2
        and isinstance(val[0], (str, int))
        and isinstance(val[1], int)
    )


def detect_api_json_issues(api_json_raw: Any) -> Dict[str, Any]:
    """检测 ComfyUI API JSON 中缺少 class_type、断连或空媒体占位的节点问题。"""
    api_json = (
        json.loads(api_json_raw)
        if isinstance(api_json_raw, str)
        else api_json_raw
    )
    if not isinstance(api_json, dict) or is_comfy_ui_graph_json(api_json):
        return {
            "is_ui_graph": is_comfy_ui_graph_json(api_json),
            "missing_class_type_nodes": [],
            "broken_links": [],
            "none_media_nodes": [],
        }

    missing_class_type_nodes: List[Dict[str, Any]] = []
    broken_links: List[str] = []
    none_media_nodes: List[Dict[str, Any]] = []

    for node_id, node in api_json.items():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        has_ct = isinstance(ct, str) and bool(ct.strip())
        title = str((node.get("_meta") or {}).get("title") or "").strip()
        node_inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}

        if not has_ct:
            missing_class_type_nodes.append(
                {
                    "node_id": str(node_id),
                    "title": title,
                    "inputs": node_inputs,
                }
            )
            continue

        for k, v in node_inputs.items():
            if _is_link_ref(v):
                ref_id = str(v[0])
                ref_node = api_json.get(ref_id)
                if not isinstance(ref_node, dict):
                    broken_links.append(f"{node_id}.{k} -> 缺失节点 {ref_id}")
                else:
                    ref_ct = ref_node.get("class_type")
                    if not isinstance(ref_ct, str) or not ref_ct.strip():
                        broken_links.append(f"{node_id}.{k} -> 缺失 class_type 节点 {ref_id}")

        if ct in ("LoadImage", "LoadVideo", "LoadAudio"):
            for media_key in ("image", "file", "audio"):
                if media_key in node_inputs:
                    raw_val = node_inputs[media_key]
                    if isinstance(raw_val, str) and raw_val.strip().lower() in ("", "none"):
                        none_media_nodes.append(
                            {
                                "node_id": str(node_id),
                                "class_type": ct,
                                "input_name": media_key,
                                "value": raw_val,
                            }
                        )

    return {
        "is_ui_graph": False,
        "missing_class_type_nodes": missing_class_type_nodes,
        "broken_links": broken_links,
        "none_media_nodes": none_media_nodes,
    }


def repair_missing_primitive_nodes(
    api_json_raw: Any,
) -> Tuple[Dict[str, Any], List[str]]:
    """仅对工作流副本修复导出时丢失 class_type 的 UNKNOWN 标量占位节点，不改动源文件。"""
    api_json = (
        json.loads(api_json_raw)
        if isinstance(api_json_raw, str)
        else copy.deepcopy(api_json_raw)
    )
    if not isinstance(api_json, dict):
        return {}, []

    notes: List[str] = []
    # 仅统计有效上游节点对其他节点的连线，忽略无效节点自身引用
    downstream_refs: Dict[str, List[Tuple[str, str]]] = {}
    for dst_id, dst_node in api_json.items():
        if not isinstance(dst_node, dict):
            continue
        dst_ct = dst_node.get("class_type")
        if not isinstance(dst_ct, str) or not dst_ct.strip():
            continue
        dst_inputs = dst_node.get("inputs") if isinstance(dst_node.get("inputs"), dict) else {}
        for dst_key, val in dst_inputs.items():
            if _is_link_ref(val):
                downstream_refs.setdefault(str(val[0]), []).append(
                    (str(dst_id), str(dst_key))
                )

    for node_id in list(api_json.keys()):
        node = api_json.get(node_id)
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type")
        if isinstance(ct, str) and ct.strip():
            continue

        refs = downstream_refs.get(str(node_id), [])
        node_inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        title = str((node.get("_meta") or {}).get("title") or "").strip()

        if not refs:
            api_json.pop(node_id, None)
            notes.append(f"移除无下游引用的失效节点 {node_id}" + (f"（{title}）" if title else ""))
            continue

        if "UNKNOWN" not in node_inputs:
            continue

        val = node_inputs["UNKNOWN"]
        if (
            isinstance(val, int)
            and not isinstance(val, bool)
            and all(
                str((api_json.get(dst_id) or {}).get("class_type") or "") == "RandomNoise"
                and dst_key == "noise_seed"
                for dst_id, dst_key in refs
            )
        ):
            for dst_id, dst_key in refs:
                api_json[dst_id]["inputs"][dst_key] = val
            api_json.pop(node_id, None)
            notes.append(f"将失效种子节点 {node_id} 内联写回 RandomNoise.noise_seed 并清理")
            continue

        if isinstance(val, bool):
            primitive_cls = "PrimitiveBoolean"
        elif isinstance(val, int):
            primitive_cls = "PrimitiveInt"
        elif isinstance(val, float):
            primitive_cls = "PrimitiveFloat"
        elif isinstance(val, str):
            primitive_cls = "PrimitiveStringMultiline"
        else:
            continue

        api_json[node_id] = {
            "inputs": {"value": val},
            "class_type": primitive_cls,
            "_meta": {
                "title": title or f"Repaired Primitive ({node_id})",
                "cnr_id": "comfy-core",
            },
        }
        notes.append(
            f"将缺失 class_type 的节点 {node_id}"
            + (f"（{title}）" if title else "")
            + f" 修复为 {primitive_cls}"
        )

    return api_json, notes


def scan_source_workflows_dir(
    source_dir: Optional[str] = None,
    workflows_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """扫描 workflows/source/ 下的原始 API JSON，识别新增、已导入、已更新和无效文件（带 mtime 缓存）。"""
    import services.comfy_workflow_pack as _pkg
    if source_dir is None:
        source_dir = _pkg.SOURCE_WORKFLOWS_DIR
    if workflows_dir is None:
        workflows_dir = _pkg.WORKFLOWS_DIR
    scan_workflows_dir = _pkg.scan_workflows_dir
    _compute_dir_signature = _pkg._compute_dir_signature
    _SCAN_SOURCE_CACHE = _pkg._SCAN_SOURCE_CACHE
    result: Dict[str, Any] = {
        "source_dir": source_dir,
        "new": [],
        "updated": [],
        "already_imported": [],
        "invalid": [],
    }
    if not os.path.isdir(source_dir):
        return result

    cache_key = f"{os.path.abspath(source_dir)}|{os.path.abspath(workflows_dir)}"
    combined_sig = (
        _compute_dir_signature(source_dir, include_subdirs=False),
        _compute_dir_signature(workflows_dir, include_subdirs=True),
    )
    cached_src = _SCAN_SOURCE_CACHE.get(cache_key)
    if cached_src is not None and cached_src[0] == combined_sig:
        return copy.deepcopy(cached_src[1])

    existing_packs = scan_workflows_dir(workflows_dir).get("valid", [])
    known_source_hashes: set[str] = set()
    known_api_hashes: Dict[str, str] = {}
    known_by_source_file: Dict[str, Dict[str, str]] = {}

    for pack in existing_packs:
        cfg = pack.get("config_json") or {}
        wf_name = str(cfg.get("name") or "")
        src_file = str(cfg.get("source_file") or "").strip()
        src_sha = str(cfg.get("source_sha256") or "").strip()
        api_sha = compute_api_json_sha256(pack.get("api_json") or {})
        if src_sha:
            known_source_hashes.add(src_sha)
        if wf_name:
            known_api_hashes[api_sha] = wf_name
        if src_file:
            known_by_source_file[src_file] = {
                "workflow_name": wf_name,
                "source_sha256": src_sha,
            }

    for entry in sorted(os.listdir(source_dir)):
        if entry.startswith(".") or not entry.lower().endswith(".json"):
            continue
        full_path = os.path.join(source_dir, entry)
        if not os.path.isfile(full_path):
            continue

        file_sha = compute_file_sha256(full_path)
        try:
            with open(full_path, "r", encoding="utf-8-sig") as f:
                raw_payload = json.load(f)
        except Exception as exc:
            result["invalid"].append(
                {
                    "filename": entry,
                    "path": full_path,
                    "source_sha256": file_sha,
                    "reason": f"JSON 解析失败: {exc}",
                }
            )
            continue

        if is_comfy_ui_graph_json(raw_payload):
            result["invalid"].append(
                {
                    "filename": entry,
                    "path": full_path,
                    "source_sha256": file_sha,
                    "reason": "检测到 ComfyUI 编辑器画布 JSON（含 nodes/links），请用 Dev Mode -> Export (API) 重新导出",
                }
            )
            continue

        if not isinstance(raw_payload, dict) or not raw_payload:
            result["invalid"].append(
                {
                    "filename": entry,
                    "path": full_path,
                    "source_sha256": file_sha,
                    "reason": "API JSON 必须为非空节点字典对象",
                }
            )
            continue

        api_sha = compute_api_json_sha256(raw_payload)
        if file_sha in known_source_hashes or api_sha in known_api_hashes:
            matched_name = (
                known_by_source_file.get(entry, {}).get("workflow_name")
                or known_api_hashes.get(api_sha, "")
            )
            result["already_imported"].append(
                {
                    "filename": entry,
                    "path": full_path,
                    "source_sha256": file_sha,
                    "workflow_name": matched_name,
                }
            )
            continue

        validation_errors = validate_api_json(raw_payload)
        repair_notes: List[str] = []
        if validation_errors:
            repaired_api, repair_notes = repair_missing_primitive_nodes(raw_payload)
            repaired_errors = validate_api_json(repaired_api)
            if repaired_errors:
                result["invalid"].append(
                    {
                        "filename": entry,
                        "path": full_path,
                        "source_sha256": file_sha,
                        "reason": "；".join(repaired_errors),
                    }
                )
                continue
            repaired_sha = compute_api_json_sha256(repaired_api)
            if repaired_sha in known_api_hashes:
                result["already_imported"].append(
                    {
                        "filename": entry,
                        "path": full_path,
                        "source_sha256": file_sha,
                        "workflow_name": known_api_hashes[repaired_sha],
                    }
                )
                continue

        item = {
            "filename": entry,
            "path": full_path,
            "source_sha256": file_sha,
            "repair_notes": repair_notes,
        }
        if entry in known_by_source_file:
            item["previous_workflow_name"] = known_by_source_file[entry]["workflow_name"]
            result["updated"].append(item)
        else:
            result["new"].append(item)

    _SCAN_SOURCE_CACHE[cache_key] = (combined_sig, copy.deepcopy(result))
    return result
