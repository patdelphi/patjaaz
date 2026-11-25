"""程序说明：提供 ComfyUI API JSON 草稿配置自动生成、面向 Agent 的节点摘要提取与数据库记录成对导出功能。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

SUMMARY_MAX_STRING_LEN = 200

from services.comfy_pack_common import (
    WorkflowPackValidationError,
    _sanitize_workflow_name,
    validate_api_json,
)


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



def _truncate_summary_value(value: Any) -> Any:
    """截断摘要中的超长字符串，保留长度信息，避免内置提示词模板撑爆 LLM 上下文。"""
    if isinstance(value, str) and len(value) > SUMMARY_MAX_STRING_LEN:
        return f"{value[:SUMMARY_MAX_STRING_LEN]}…(共 {len(value)} 字符，已截断)"
    return value


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

            entry: Dict[str, Any] = {"value": _truncate_summary_value(input_val)}
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

