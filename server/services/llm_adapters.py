"""程序说明：提供零新增依赖的三协议（OpenAI / Anthropic 原生 / Gemini REST / OpenAI-compatible）大模型适配器与连通性测试。"""
from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Tuple
import uuid

import anthropic
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from services.config_service import (
    config_service,
    infer_provider_protocol,
    merge_masked_secrets,
)
from utils.http_client import HttpClient

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

    return AIMessage(content="".join(text_chunks), tool_calls=tool_calls)


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
    """解析 Gemini REST generateContent JSON 响应为 LangChain AIMessage。"""
    candidates = payload.get("candidates") or []
    if not candidates:
        return AIMessage(content="")

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

    return AIMessage(content="".join(text_chunks), tool_calls=tool_calls)


def _ai_message_to_chunk(ai_msg: AIMessage) -> AIMessageChunk:
    """将完整 AIMessage 转为带 tool_call_chunks 的流式块，兼容 StreamProcessor。"""
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
    )


class AnthropicNativeChatModel(BaseChatModel):
    """基于已安装 anthropic SDK 的轻量 Anthropic 原生协议对话适配器。"""

    model: str
    api_key: str
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout: float = 300.0

    @property
    def _llm_type(self) -> str:
        return "anthropic-native"

    def _normalized_base_url(self) -> Optional[str]:
        raw = str(self.base_url or "").strip().rstrip("/")
        if raw.endswith("/v1"):
            raw = raw[:-3]
        return raw or None

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Runnable:
        specs = _normalize_tool_specs(tools)
        anthropic_tools = [
            {
                "name": item["name"],
                "description": item["description"],
                "input_schema": item["parameters"],
            }
            for item in specs
        ]
        bind_kwargs: Dict[str, Any] = {**kwargs, "tools": anthropic_tools}
        if tool_choice:
            bind_kwargs["tool_choice"] = (
                {"type": tool_choice}
                if tool_choice in ("auto", "any")
                else {"type": "tool", "name": tool_choice}
            )
        return self.bind(**bind_kwargs)

    def _build_request_kwargs(
        self,
        messages: Sequence[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        system_prompt, msg_list = convert_messages_to_anthropic(messages)
        req: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(kwargs.get("max_tokens") or self.max_tokens),
            "messages": msg_list,
        }
        if system_prompt:
            req["system"] = system_prompt
        if stop:
            req["stop_sequences"] = stop
        if kwargs.get("tools"):
            req["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            req["tool_choice"] = kwargs["tool_choice"]
        return req

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self._normalized_base_url(),
            timeout=self.timeout,
        )
        req = self._build_request_kwargs(messages, stop=stop, **kwargs)
        resp = client.messages.create(**req)
        ai_msg = parse_anthropic_response(resp)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self._normalized_base_url(),
            timeout=self.timeout,
        )
        req = self._build_request_kwargs(messages, stop=stop, **kwargs)
        resp = await client.messages.create(**req)
        ai_msg = parse_anthropic_response(resp)
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        result = await self._agenerate(messages, stop=stop, **kwargs)
        msg = result.generations[0].message
        chunk = _ai_message_to_chunk(msg)  # type: ignore[arg-type]
        yield ChatGenerationChunk(message=chunk)


class GeminiNativeChatModel(BaseChatModel):
    """基于 httpx 的轻量 Gemini REST API 原生协议对话适配器（密钥走请求头不进 URL）。"""

    model: str
    api_key: str
    base_url: str = "https://generativelanguage.googleapis.com"
    max_tokens: int = 8192
    temperature: float = 0.0
    timeout: float = 300.0

    @property
    def _llm_type(self) -> str:
        return "gemini-native"

    def _endpoint_url(self) -> str:
        base = str(self.base_url or "https://generativelanguage.googleapis.com").strip().rstrip("/")
        if not base.endswith("/v1beta") and not base.endswith("/v1"):
            base = f"{base}/v1beta"
        return f"{base}/models/{self.model}:generateContent"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Runnable:
        specs = _normalize_tool_specs(tools)
        declarations = [
            {
                "name": item["name"],
                "description": item["description"],
                "parameters": _sanitize_gemini_schema(item["parameters"]),
            }
            for item in specs
        ]
        bind_kwargs: Dict[str, Any] = {
            **kwargs,
            "tools": [{"functionDeclarations": declarations}],
        }
        return self.bind(**bind_kwargs)

    def _build_payload(
        self,
        messages: Sequence[BaseMessage],
        stop: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        sys_inst, contents = convert_messages_to_gemini(messages)
        gen_cfg: Dict[str, Any] = {
            "maxOutputTokens": int(kwargs.get("max_tokens") or self.max_tokens),
            "temperature": float(self.temperature),
        }
        if stop:
            gen_cfg["stopSequences"] = stop

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": gen_cfg,
        }
        if sys_inst:
            payload["systemInstruction"] = sys_inst
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        return payload

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(messages, stop=stop, **kwargs)
        with HttpClient.create_sync(timeout=self.timeout) as client:
            resp = client.post(
                self._endpoint_url(), json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            ai_msg = parse_gemini_response(resp.json())
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(messages, stop=stop, **kwargs)
        async with HttpClient.create(timeout=self.timeout) as client:
            resp = await client.post(
                self._endpoint_url(), json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            ai_msg = parse_gemini_response(resp.json())
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        result = await self._agenerate(messages, stop=stop, **kwargs)
        msg = result.generations[0].message
        yield ChatGenerationChunk(message=_ai_message_to_chunk(msg))  # type: ignore[arg-type]


def create_chat_model(
    text_model: Dict[str, Any],
    provider_config: Optional[Dict[str, Any]] = None,
) -> Any:
    """按协议配置创建对应的 LangChain 对话模型实例（支持 OpenAI/Anthropic/Gemini/Compatible）。"""
    model = str(text_model.get("model") or "")
    provider = str(text_model.get("provider") or "")
    stored_cfg = (
        provider_config
        if provider_config is not None
        else config_service.app_config.get(provider, {})
    )
    if not isinstance(stored_cfg, dict):
        stored_cfg = {}

    url = str(text_model.get("url") or stored_cfg.get("url") or "").strip()
    api_key = str(stored_cfg.get("api_key") or "")
    max_tokens = int(text_model.get("max_tokens") or stored_cfg.get("max_tokens") or 8192)
    protocol = infer_provider_protocol(
        provider,
        {
            "protocol": text_model.get("protocol") or stored_cfg.get("protocol"),
            "url": url,
        },
    )

    if provider == "ollama":
        return ChatOllama(
            model=model,
            base_url=url or "http://localhost:11434",
        )
    if protocol == "anthropic":
        return AnthropicNativeChatModel(
            model=model,
            api_key=api_key,
            base_url=url or "https://api.anthropic.com",
            max_tokens=max_tokens,
        )
    if protocol == "google":
        return GeminiNativeChatModel(
            model=model,
            api_key=api_key,
            base_url=url or "https://generativelanguage.googleapis.com",
            max_tokens=max_tokens,
        )

    http_client = HttpClient.create_sync_client()
    http_async_client = HttpClient.create_async_client()
    return ChatOpenAI(
        model=model,
        api_key=api_key,  # type: ignore[arg-type]
        timeout=300,
        base_url=url or None,
        temperature=0,
        http_client=http_client,
        http_async_client=http_async_client,
    )


def _sanitize_error_text(text: str, secret: str) -> str:
    """在任何错误详情中清除明文 API Key，防止向前端或日志泄漏。"""
    cleaned = str(text or "")
    if secret and len(secret) >= 4:
        cleaned = cleaned.replace(secret, "***")
    return cleaned


async def test_llm_connection(
    provider_name: str,
    provider_config: Dict[str, Any],
    model_name: str = "",
) -> Dict[str, Any]:
    """按目标协议测试大模型接口连通性与鉴权有效性，返回延迟与脱敏结果。"""
    merged_wrapper = merge_masked_secrets(
        {provider_name: provider_config}, config_service.app_config
    )
    resolved_cfg = merged_wrapper.get(provider_name, provider_config)
    url = str(resolved_cfg.get("url") or "").strip().rstrip("/")
    api_key = str(resolved_cfg.get("api_key") or "").strip()
    protocol = infer_provider_protocol(provider_name, resolved_cfg)

    if not url:
        return {
            "ok": False,
            "protocol": protocol,
            "latency_ms": 0,
            "message": "请先填写 API 地址",
        }
    if provider_name != "ollama" and not api_key:
        return {
            "ok": False,
            "protocol": protocol,
            "latency_ms": 0,
            "message": "请先填写 API 密钥",
        }

    started = time.perf_counter()
    try:
        async with HttpClient.create(timeout=12.0) as client:
            if provider_name == "ollama":
                resp = await client.get(f"{url}/api/tags")
            elif protocol == "anthropic":
                base = url[:-3] if url.endswith("/v1") else url
                resp = await client.get(
                    f"{base}/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
            elif protocol == "google":
                base = url if url.endswith(("/v1beta", "/v1")) else f"{url}/v1beta"
                resp = await client.get(
                    f"{base}/models",
                    headers={"x-goog-api-key": api_key},
                )
            else:
                resp = await client.get(
                    f"{url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            latency_ms = round((time.perf_counter() - started) * 1000)
            if 200 <= resp.status_code < 300:
                return {
                    "ok": True,
                    "protocol": protocol,
                    "latency_ms": latency_ms,
                    "message": f"连接成功 ({protocol}, {latency_ms}ms)",
                }
            detail = _sanitize_error_text(resp.text[:300], api_key)
            return {
                "ok": False,
                "protocol": protocol,
                "latency_ms": latency_ms,
                "message": f"HTTP {resp.status_code}: {detail}",
            }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "protocol": protocol,
            "latency_ms": latency_ms,
            "message": _sanitize_error_text(str(exc), api_key),
        }
