"""程序说明：由内置 AI Agent（已配置 LLM + ComfyUI object_info）直接解析 API JSON、生成并自纠 jaaz.workflow.json 配置。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from services.comfy_instance_service import build_comfy_http_url, comfy_instance_service
from services.comfy_workflow_pack import (
    WorkflowPackValidationError,
    summarize_api_json_for_agent,
    validate_api_json,
    validate_workflow_pack,
)
from services.config_service import config_service
from services.llm_adapters import create_chat_model
from utils.http_client import HttpClient

_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)

_AI_IMPORTER_SYSTEM_PROMPT = """你是 ComfyUI 与 Jaaz 工作流配置专家。
你的唯一任务：根据提供的 ComfyUI API JSON 节点摘要（含可选的 /object_info 枚举项）以及用户补充说明，生成一份严格符合 Jaaz Schema v1 的 JSON 配置对象，使对话 Agent 能够准确调用该工作流。

必须遵守的严格规则：
1. 只输出合法的纯 JSON 对象，不要包含额外解释文字。
2. 顶层必填字段：
   - "schema_version": 固定为 1
   - "name": 英文小写与数字下划线工作流标识（匹配 ^[a-zA-Z0-9_]+$，建议贴合工作流实际用途，如 text2image_moss / image_edit_flux）
   - "display_name": 简洁中文展示名称
   - "capability": 必须为 t2i / i2i / inpaint / outpaint / rembg / upscale / t2v / i2v / tts / asr / music / custom 之一
   - "output_kind": 必须为 image / video / audio 之一
   - "enabled": true
   - "instance_id": ""（保持空字符串由调度器分配，除非用户明确指定）
   - "seed_strategy": "random" | "fixed" | "param"（默认 "random"）
   - "description": 给 Agent 阅读的完整工具说明，务必写明：用途、每个参数的具体含义与必填要求（含枚举可选值）、哪些内部参数（模型/步数/CFG/固定尺寸等）已固定在工作流内部请勿乱传
   - "inputs": 需要让用户或 Agent 动态控制的高层参数列表（数组），每一项格式：
     {
       "name": "英文数字下划线参数名",
       "type": "string | number | boolean | image | audio | video | enum",
       "required": true 或 false,
       "node_id": "摘要中真实存在的节点 ID 字符串",
       "node_input_name": "该节点 literal_inputs 中真实存在的输入键名",
       "default_value": 原默认值,
       "options": ["如该输入在摘要中有 options，必须原样保留枚举列表"],
       "description": "该参数的详细中文说明；若为 enum，说明必须原样传枚举字符串"
     }
3. 不要把固定模型路径（ckpt_name/unet_name/vae_name/lora_name）、默认采样器/scheduler/steps/cfg/denoise 或随机 seed 暴露到 inputs（除非工作流明显需要用户调节或用户说明里要求暴露），以免 Agent 乱传报错。
4. 若摘要显示节点包含 LoadImage / image 输入底图，将该输入映射为 type: "image", required: true，并在 description 中说明需传入用户上传或选中的图片文件名。
5. 每一个 inputs[] 中的 node_id 与 node_input_name 必须能在输入摘要中精确找到对应键值！"""


def extract_json_from_llm_text(text: str) -> Dict[str, Any]:
    """从 LLM 文本或 Markdown 代码块中提取并解析 JSON 对象。"""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("LLM 返回内容为空，未能解析工作流配置 JSON")

    candidates = [raw]
    fence_match = _CODE_FENCE_RE.search(raw)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())

    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        candidates.append(raw[brace_start : brace_end + 1])

    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            last_error = exc
    raise ValueError(f"无法从模型输出解析合法 JSON 对象: {last_error}")


def select_available_text_model(
    preferred_provider: str = "",
    preferred_model: str = "",
) -> Dict[str, Any]:
    """从当前系统配置中选取一个可用的文本大模型配置供工作流 AI 导入使用。"""
    cfg = config_service.get_config()
    if not isinstance(cfg, dict):
        raise RuntimeError("系统模型配置为空，请先配置文本大模型")

    def _build_entry(provider_key: str, model_name: str, prov_cfg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": provider_key,
            "model": model_name,
            "url": str(prov_cfg.get("url") or "").strip(),
            "protocol": prov_cfg.get("protocol", ""),
            "max_tokens": prov_cfg.get("max_tokens", 8192),
        }

    # 1. 优先匹配显式指定
    if preferred_provider and preferred_provider in cfg:
        prov_cfg = cfg[preferred_provider]
        if isinstance(prov_cfg, dict):
            api_key = str(prov_cfg.get("api_key") or "").strip()
            if preferred_provider == "ollama" or api_key:
                models_dict = prov_cfg.get("models") or {}
                chosen_model = preferred_model
                if not chosen_model:
                    for m_name, m_cfg in models_dict.items():
                        if isinstance(m_cfg, dict) and m_cfg.get("type", "text") == "text":
                            chosen_model = m_name
                            break
                if chosen_model:
                    return _build_entry(preferred_provider, chosen_model, prov_cfg)

    # 2. 按顺序查找任意已配置 API Key 的文本大模型提供商
    ordered_keys = ["openai", "anthropic", "google"] + [
        k for k in cfg.keys() if k not in ("comfyui", "ollama", "openai", "anthropic", "google")
    ]
    for provider_key in ordered_keys:
        prov_cfg = cfg.get(provider_key)
        if not isinstance(prov_cfg, dict):
            continue
        if not str(prov_cfg.get("api_key") or "").strip():
            continue
        models_dict = prov_cfg.get("models") or {}
        for m_name, m_cfg in models_dict.items():
            if isinstance(m_cfg, dict) and m_cfg.get("type", "text") == "text":
                return _build_entry(provider_key, m_name, prov_cfg)

    # 3. 兜底检测本地 Ollama（允许显式 preferred_model 或自动发现首个本地模型）
    ollama_cfg = cfg.get("ollama")
    if isinstance(ollama_cfg, dict) and str(ollama_cfg.get("url") or "").strip():
        if preferred_model:
            return _build_entry("ollama", preferred_model, ollama_cfg)
        try:
            from routers.root_router import get_ollama_model_list

            local_models = get_ollama_model_list()
            if local_models:
                return _build_entry("ollama", local_models[0], ollama_cfg)
        except Exception:
            pass

    raise RuntimeError(
        "尚未配置可用的文本大模型（请先在设置中配置 OpenAI / Claude / Gemini / Compatible API 密钥，或直接使用外部 AI Agent 通过 workflow_cli.py 导入）"
    )


async def fetch_comfy_object_info(
    instance_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """尝试从已配置的 ComfyUI 实例拉取 /api/object_info 以补全下拉枚举，失败时降级返回 None。"""
    try:
        instance = await comfy_instance_service.resolve_instance(instance_id)
    except Exception:
        return None

    base_url = str(instance.get("base_url") or "").strip()
    if not base_url:
        return None
    headers = dict(instance.get("headers") or {})
    try:
        async with HttpClient.create(timeout=httpx.Timeout(5.0)) as client:
            for endpoint in ("/api/object_info", "/object_info"):
                resp = await client.get(
                    build_comfy_http_url(base_url, endpoint),
                    headers=headers or None,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
    except Exception:
        return None
    return None


def _msg_to_text(msg: Any) -> str:
    """将 LangChain 响应消息内容统一提取为字符串。"""
    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content or "")


async def generate_workflow_config_with_ai(
    api_json_raw: Any,
    *,
    suggested_name: str = "",
    user_hint: str = "",
    instance_id: Optional[str] = None,
    provider: str = "",
    model: str = "",
    chat_model: Any = None,
    object_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """使用内置 AI Agent 分析 API JSON 并生成通过严格校验的 jaaz.workflow.json 配置，出错时自动纠错一次。"""
    api_json = (
        json.loads(api_json_raw)
        if isinstance(api_json_raw, str)
        else api_json_raw
    )
    api_errors = validate_api_json(api_json)
    if api_errors:
        raise WorkflowPackValidationError(api_errors)

    resolved_object_info = (
        object_info
        if object_info is not None
        else await fetch_comfy_object_info(instance_id)
    )
    summary = summarize_api_json_for_agent(api_json, resolved_object_info)

    model_used = "custom_injected"
    if chat_model is None:
        selected = select_available_text_model(
            preferred_provider=provider, preferred_model=model
        )
        model_used = f"{selected['provider']}:{selected['model']}"
        chat_model = create_chat_model(selected)

    user_prompt = {
        "suggested_name": suggested_name or "",
        "user_hint": user_hint or "",
        "instance_id": instance_id or "",
        "workflow_summary": summary,
    }
    messages: List[Any] = [
        SystemMessage(content=_AI_IMPORTER_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                "请分析以下 ComfyUI API JSON 节点摘要并生成 jaaz.workflow.json：\n"
                + json.dumps(user_prompt, ensure_ascii=False, indent=2)
            )
        ),
    ]

    first_resp = await chat_model.ainvoke(messages)
    first_text = _msg_to_text(first_resp)
    repaired = False

    try:
        candidate_cfg = extract_json_from_llm_text(first_text)
        if instance_id and not candidate_cfg.get("instance_id"):
            candidate_cfg["instance_id"] = instance_id
        validation = validate_workflow_pack(api_json, candidate_cfg)
    except Exception as parse_exc:
        validation = {
            "valid": False,
            "errors": [str(parse_exc)],
            "normalized": None,
        }

    if not validation["valid"]:
        repaired = True
        feedback = (
            "你上一步生成的 jaaz.workflow.json 未通过校验，具体错误如下：\n- "
            + "\n- ".join(validation["errors"])
            + "\n请严格对照原始 workflow_summary 修正后重新输出完整纯 JSON 对象。"
        )
        messages.append(AIMessage(content=first_text))
        messages.append(HumanMessage(content=feedback))
        second_resp = await chat_model.ainvoke(messages)
        second_text = _msg_to_text(second_resp)
        candidate_cfg = extract_json_from_llm_text(second_text)
        if instance_id and not candidate_cfg.get("instance_id"):
            candidate_cfg["instance_id"] = instance_id
        validation = validate_workflow_pack(api_json, candidate_cfg)
        if not validation["valid"]:
            raise WorkflowPackValidationError(validation["errors"])

    normalized = validation["normalized"]
    return {
        "config_json": normalized["config_json"],
        "checksum": normalized["checksum"],
        "model_used": model_used,
        "repaired": repaired,
        "used_object_info": bool(resolved_object_info),
    }
