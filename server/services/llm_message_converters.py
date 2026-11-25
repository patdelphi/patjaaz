"""程序说明：提供三协议（Anthropic / Gemini / OpenAI）消息、工具 Schema 与流式块纯函数转换器。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.utils.function_calling import convert_to_openai_tool

_DATA_URI_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)


def _extract_text_blocks(content: Any) -> str:
    """将文本或多模态消息列表提取为纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p)
    return str(content or "")


def _normalize_tool_specs(tools: Sequence[Any]) -> List[Dict[str, Any]]:
    """统一将 BaseTool/Pydantic/OpenAI dict 转换为标准函数描述。"""
    specs: List[Dict[str, Any]] = []
    for item in tools:
        converted = convert_to_openai_tool(item)
        fn = converted.get("function") if isinstance(converted, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        specs.append(
            {
                "name": name,
                "description": str(fn.get("description") or ""),
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return specs


def _sanitize_gemini_schema(schema: Any) -> Any:
    """移除 Gemini REST functionDeclarations 不支持的 JSON Schema 扩展字段。"""
    if isinstance(schema, list):
        return [_sanitize_gemini_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    forbidden = {"$schema", "additionalProperties", "default", "title"}
    cleaned: Dict[str, Any] = {}
    for key, val in schema.items():
        if key in forbidden:
            continue
        if key == "anyOf" and isinstance(val, list):
            # Gemini 参数模型通常直接取首个非 null 分支
            non_null = [
                sub for sub in val if not (isinstance(sub, dict) and sub.get("type") == "null")
            ]
            if len(non_null) == 1 and isinstance(non_null[0], dict):
                merged = _sanitize_gemini_schema(non_null[0])
                if isinstance(merged, dict):
                    cleaned.update(merged)
                continue
        cleaned[key] = _sanitize_gemini_schema(val)
    return cleaned


def convert_messages_to_anthropic(
    messages: Sequence[BaseMessage],
) -> Tuple[str, List[Dict[str, Any]]]:
    """将 LangChain 消息序列转换为 Anthropic Messages API 的 (system, messages) 结构。"""
    system_parts: List[str] = []
    anthropic_msgs: List[Dict[str, Any]] = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            txt = _extract_text_blocks(msg.content)
            if txt:
                system_parts.append(txt)
            continue

        if isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                content: Any = msg.content
            elif isinstance(msg.content, list):
                blocks: List[Dict[str, Any]] = []
                for part in msg.content:
                    if not isinstance(part, dict):
                        blocks.append({"type": "text", "text": str(part)})
                        continue
                    ptype = part.get("type")
                    if ptype == "text":
                        blocks.append({"type": "text", "text": str(part.get("text") or "")})
                    elif ptype == "image_url":
                        url = str((part.get("image_url") or {}).get("url") or "")
                        match = _DATA_URI_RE.match(url)
                        if match:
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": match.group(1),
                                        "data": match.group(2),
                                    },
                                }
                            )
                        elif url:
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {"type": "url", "url": url},
                                }
                            )
                content = blocks or [{"type": "text", "text": ""}]
            else:
                content = str(msg.content or "")
            anthropic_msgs.append({"role": "user", "content": content})
            continue

        if isinstance(msg, AIMessage):
            blocks = []
            txt = _extract_text_blocks(msg.content)
            if txt:
                blocks.append({"type": "text", "text": txt})
            for tc in getattr(msg, "tool_calls", []) or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(tc.get("id") or f"toolu_{uuid.uuid4().hex[:10]}"),
                        "name": str(tc.get("name") or ""),
                        "input": tc.get("args") if isinstance(tc.get("args"), dict) else {},
                    }
                )
            anthropic_msgs.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
            continue

        if isinstance(msg, ToolMessage):
            tool_block = {
                "type": "tool_result",
                "tool_use_id": str(msg.tool_call_id or ""),
                "content": _extract_text_blocks(msg.content),
            }
            if (
                anthropic_msgs
                and anthropic_msgs[-1]["role"] == "user"
                and isinstance(anthropic_msgs[-1]["content"], list)
                and all(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in anthropic_msgs[-1]["content"]
                )
            ):
                anthropic_msgs[-1]["content"].append(tool_block)
            else:
                anthropic_msgs.append({"role": "user", "content": [tool_block]})
            continue

        anthropic_msgs.append({"role": "user", "content": _extract_text_blocks(msg.content)})

    return "\n\n".join(system_parts), anthropic_msgs


def parse_anthropic_response(response: Any) -> AIMessage:
    """解析 Anthropic Messages API 响应为标准 LangChain AIMessage（含 tool_calls）。"""
    text_chunks: List[str] = []
    tool_calls: List[Dict[str, Any]] = []

    blocks = getattr(response, "content", None)
    if blocks is None and isinstance(response, dict):
        blocks = response.get("content", [])

    for block in blocks or []:
        btype = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if btype == "text":
            txt = getattr(block, "text", None)
            if txt is None and isinstance(block, dict):
                txt = block.get("text", "")
            if txt:
                text_chunks.append(str(txt))
        elif btype == "tool_use":
            bid = getattr(block, "id", None) or (
                block.get("id") if isinstance(block, dict) else None
            )
            bname = getattr(block, "name", None) or (
                block.get("name") if isinstance(block, dict) else ""
            )
            binput = getattr(block, "input", None)
            if binput is None and isinstance(block, dict):
                binput = block.get("input", {})
            tool_calls.append(
                {
                    "id": str(bid or f"toolu_{uuid.uuid4().hex[:10]}"),
                    "name": str(bname or ""),
                    "args": binput if isinstance(binput, dict) else {},
                    "type": "tool_call",
                }
            )

    usage_obj = getattr(response, "usage", None)
    if usage_obj is None and isinstance(response, dict):
        usage_obj = response.get("usage")
    usage_meta: Optional[Dict[str, int]] = None
    if usage_obj is not None:
        in_tok = getattr(usage_obj, "input_tokens", None)
        out_tok = getattr(usage_obj, "output_tokens", None)
        if isinstance(usage_obj, dict):
            in_tok = usage_obj.get("input_tokens", in_tok)
            out_tok = usage_obj.get("output_tokens", out_tok)
        if in_tok is not None or out_tok is not None:
            it = int(in_tok or 0)
            ot = int(out_tok or 0)
            usage_meta = {
                "input_tokens": it,
                "output_tokens": ot,
                "total_tokens": it + ot,
            }

    return AIMessage(
        content="".join(text_chunks),
        tool_calls=tool_calls,
        usage_metadata=usage_meta,  # type: ignore[arg-type]
    )


def convert_messages_to_gemini(
    messages: Sequence[BaseMessage],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """将 LangChain 消息序列转换为 Gemini generateContent 请求体格式。"""
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    id_to_name: Dict[str, str] = {}

    for msg in messages:
        if isinstance(msg, SystemMessage):
            txt = _extract_text_blocks(msg.content)
            if txt:
                system_parts.append(txt)
            continue

        if isinstance(msg, HumanMessage):
            parts: List[Dict[str, Any]] = []
            if isinstance(msg.content, str):
                parts.append({"text": msg.content})
            elif isinstance(msg.content, list):
                for item in msg.content:
                    if not isinstance(item, dict):
                        parts.append({"text": str(item)})
                        continue
                    ptype = item.get("type")
                    if ptype == "text":
                        parts.append({"text": str(item.get("text") or "")})
                    elif ptype == "image_url":
                        url = str((item.get("image_url") or {}).get("url") or "")
                        match = _DATA_URI_RE.match(url)
                        if match:
                            parts.append(
                                {
                                    "inlineData": {
                                        "mimeType": match.group(1),
                                        "data": match.group(2),
                                    }
                                }
                            )
                        elif url:
                            parts.append({"text": url})
            contents.append({"role": "user", "parts": parts or [{"text": ""}]})
            continue

        if isinstance(msg, AIMessage):
            parts = []
            txt = _extract_text_blocks(msg.content)
            if txt:
                parts.append({"text": txt})
            for tc in getattr(msg, "tool_calls", []) or []:
                tc_id = str(tc.get("id") or "")
                tc_name = str(tc.get("name") or "")
                if tc_id and tc_name:
                    id_to_name[tc_id] = tc_name
                parts.append(
                    {
                        "functionCall": {
                            "name": tc_name,
                            "args": tc.get("args") if isinstance(tc.get("args"), dict) else {},
                        }
                    }
                )
            contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            continue

        if isinstance(msg, ToolMessage):
            fn_name = str(getattr(msg, "name", "") or id_to_name.get(msg.tool_call_id or "", "tool"))
            resp_part = {
                "functionResponse": {
                    "name": fn_name,
                    "response": {"result": _extract_text_blocks(msg.content)},
                }
            }
            if (
                contents
                and contents[-1]["role"] == "user"
                and all("functionResponse" in p for p in contents[-1]["parts"])
            ):
                contents[-1]["parts"].append(resp_part)
            else:
                contents.append({"role": "user", "parts": [resp_part]})
            continue

        contents.append({"role": "user", "parts": [{"text": _extract_text_blocks(msg.content)}]})

    system_instruction = (
        {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
    )
    return system_instruction, contents


def parse_gemini_response(payload: Dict[str, Any]) -> AIMessage:
    """解析 Gemini REST generateContent JSON 响应为 LangChain AIMessage（含 usage_metadata）。"""
    usage_raw = payload.get("usageMetadata") if isinstance(payload, dict) else None
    usage_meta: Optional[Dict[str, int]] = None
    if isinstance(usage_raw, dict):
        it = int(usage_raw.get("promptTokenCount") or 0)
        ot = int(usage_raw.get("candidatesTokenCount") or 0)
        tt = int(usage_raw.get("totalTokenCount") or (it + ot))
        usage_meta = {
            "input_tokens": it,
            "output_tokens": ot,
            "total_tokens": tt,
        }

    candidates = payload.get("candidates") or []
    if not candidates:
        return AIMessage(content="", usage_metadata=usage_meta)  # type: ignore[arg-type]

    content_obj = candidates[0].get("content") or {}
    parts = content_obj.get("parts") or []
    text_chunks: List[str] = []
    tool_calls: List[Dict[str, Any]] = []

    for part in parts:
        if not isinstance(part, dict):
            continue
        if "text" in part and part["text"] is not None:
            text_chunks.append(str(part["text"]))
        if "functionCall" in part and isinstance(part["functionCall"], dict):
            fc = part["functionCall"]
            tool_calls.append(
                {
                    "id": f"gemini_tc_{uuid.uuid4().hex[:10]}",
                    "name": str(fc.get("name") or ""),
                    "args": fc.get("args") if isinstance(fc.get("args"), dict) else {},
                    "type": "tool_call",
                }
            )

    return AIMessage(
        content="".join(text_chunks),
        tool_calls=tool_calls,
        usage_metadata=usage_meta,  # type: ignore[arg-type]
    )


def _ai_message_to_chunk(ai_msg: AIMessage) -> AIMessageChunk:
    """将完整 AIMessage 转为带 tool_call_chunks 与 usage_metadata 的流式块，兼容 StreamProcessor。"""
    tool_call_chunks: List[Dict[str, Any]] = []
    for idx, tc in enumerate(ai_msg.tool_calls or []):
        tool_call_chunks.append(
            {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "args": json.dumps(tc.get("args") or {}, ensure_ascii=False),
                "index": idx,
                "type": "tool_call_chunk",
            }
        )
    return AIMessageChunk(
        content=ai_msg.content,
        tool_calls=ai_msg.tool_calls or [],
        tool_call_chunks=tool_call_chunks,
        usage_metadata=getattr(ai_msg, "usage_metadata", None),  # type: ignore[arg-type]
    )

