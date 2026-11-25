"""程序说明：提供零新增依赖的三协议（OpenAI / Anthropic 原生 / Gemini REST / OpenAI-compatible）大模型适配器与连通性测试。"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Sequence, Tuple
import uuid

import anthropic
import httpx
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
from utils.log_sanitizer import get_sanitized_logger, redact_secrets

_logger = get_sanitized_logger(__name__)
_ANTHROPIC_SYNC_CLIENTS: Dict[Tuple[Optional[str], str, float], anthropic.Anthropic] = {}
_ANTHROPIC_ASYNC_CLIENTS: Dict[Tuple[int, Optional[str], str, float], anthropic.AsyncAnthropic] = {}


def _get_anthropic_sync_client(
    api_key: str, base_url: Optional[str], timeout: float
) -> anthropic.Anthropic:
    key = (base_url, api_key, float(timeout))
    client = _ANTHROPIC_SYNC_CLIENTS.get(key)
    if client is None:
        client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=_MAX_ATTEMPTS,
        )
        _ANTHROPIC_SYNC_CLIENTS[key] = client
    return client


def _get_anthropic_async_client(
    api_key: str, base_url: Optional[str], timeout: float
) -> anthropic.AsyncAnthropic:
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = 0
    key = (loop_id, base_url, api_key, float(timeout))
    client = _ANTHROPIC_ASYNC_CLIENTS.get(key)
    if client is None:
        client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=_MAX_ATTEMPTS,
        )
        _ANTHROPIC_ASYNC_CLIENTS[key] = client
    return client

_DATA_URI_RE = re.compile(r"^data:([^;]+);base64,(.+)$", re.DOTALL)

# Gemini REST 可重试状态码与最大尝试次数（Anthropic SDK 自带重试，由 max_retries 控制）
_GEMINI_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def _retry_delay(attempt: int) -> float:
    """指数退避加少量抖动：约 1s、2s。"""
    return (2 ** attempt) + random.uniform(0, 0.4)



from services.llm_message_converters import (
    _ai_message_to_chunk,
    _extract_text_blocks,
    _normalize_tool_specs,
    _sanitize_gemini_schema,
    convert_messages_to_anthropic,
    convert_messages_to_gemini,
    parse_anthropic_response,
    parse_gemini_response,
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
        client = _get_anthropic_sync_client(
            self.api_key, self._normalized_base_url(), self.timeout
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
        client = _get_anthropic_async_client(
            self.api_key, self._normalized_base_url(), self.timeout
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
        # 真流式：文本增量即时输出，工具调用与 usage_metadata 在流结束时补齐；流在产出内容前失败则回退非流式
        emitted = False
        try:
            client = _get_anthropic_async_client(
                self.api_key, self._normalized_base_url(), self.timeout
            )
            req = self._build_request_kwargs(messages, stop=stop, **kwargs)
            async with client.messages.stream(**req) as stream:
                async for text in stream.text_stream:
                    if text:
                        emitted = True
                        yield ChatGenerationChunk(message=AIMessageChunk(content=text))
                final_message = await stream.get_final_message()
            final_ai = parse_anthropic_response(final_message)
            if final_ai.tool_calls or getattr(final_ai, "usage_metadata", None):
                tool_chunk = _ai_message_to_chunk(final_ai)
                tool_chunk.content = ""
                yield ChatGenerationChunk(message=tool_chunk)
            return
        except Exception as stream_exc:
            if emitted:
                raise
            _logger.warning(
                "Anthropic 流式请求失败，回退非流式: %s: %s",
                type(stream_exc).__name__,
                redact_secrets(stream_exc, [self.api_key]),
            )

        result = await self._agenerate(messages, stop=stop, **kwargs)
        msg = result.generations[0].message
        yield ChatGenerationChunk(message=_ai_message_to_chunk(msg))  # type: ignore[arg-type]


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
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    resp = client.post(
                        self._endpoint_url(), json=payload, headers=self._headers()
                    )
                    status = getattr(resp, "status_code", 200)
                    if (
                        isinstance(status, int)
                        and status in _GEMINI_RETRY_STATUS
                        and attempt < _MAX_ATTEMPTS
                    ):
                        time.sleep(_retry_delay(attempt))
                        continue
                    resp.raise_for_status()
                    break
                except httpx.TransportError:
                    if attempt >= _MAX_ATTEMPTS:
                        raise
                    time.sleep(_retry_delay(attempt))
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
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    resp = await client.post(
                        self._endpoint_url(), json=payload, headers=self._headers()
                    )
                    status = getattr(resp, "status_code", 200)
                    if (
                        isinstance(status, int)
                        and status in _GEMINI_RETRY_STATUS
                        and attempt < _MAX_ATTEMPTS
                    ):
                        await asyncio.sleep(_retry_delay(attempt))
                        continue
                    resp.raise_for_status()
                    break
                except httpx.TransportError:
                    if attempt >= _MAX_ATTEMPTS:
                        raise
                    await asyncio.sleep(_retry_delay(attempt))
            ai_msg = parse_gemini_response(resp.json())
        return ChatResult(generations=[ChatGeneration(message=ai_msg)])

    async def _astream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        # 真流式（SSE）：文本增量即时输出，functionCall 与 usage_metadata 在末尾输出；产出内容前失败则回退非流式
        emitted = False
        try:
            payload = self._build_payload(messages, stop=stop, **kwargs)
            url = self._endpoint_url().replace(":generateContent", ":streamGenerateContent")
            tool_calls: List[Dict[str, Any]] = []
            last_usage: Optional[Dict[str, int]] = None
            async with HttpClient.create(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", f"{url}?alt=sse", json=payload, headers=self._headers()
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        part_msg = parse_gemini_response(json.loads(raw))
                        if getattr(part_msg, "usage_metadata", None):
                            last_usage = part_msg.usage_metadata  # type: ignore[assignment]
                        text = _extract_text_blocks(part_msg.content)
                        if text:
                            emitted = True
                            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
                        tool_calls.extend(part_msg.tool_calls or [])
            if tool_calls or last_usage:
                tool_chunk = _ai_message_to_chunk(
                    AIMessage(content="", tool_calls=tool_calls, usage_metadata=last_usage)  # type: ignore[arg-type]
                )
                yield ChatGenerationChunk(message=tool_chunk)
            return
        except Exception as stream_exc:
            if emitted:
                raise
            _logger.warning(
                "Gemini 流式请求失败，回退非流式: %s: %s",
                type(stream_exc).__name__,
                redact_secrets(stream_exc, [self.api_key]),
            )

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
        # 提供商限流（429）时 SDK 自动指数退避重试，减少并发配额瞬时超限造成的失败
        max_retries=5,
        base_url=url or None,
        temperature=0,
        http_client=http_client,
        http_async_client=http_async_client,
    )


def _sanitize_error_text(text: str, secret: str) -> str:
    """在任何错误详情中清除明文 API Key 与常见凭据，防止向前端或日志泄漏。"""
    return redact_secrets(text, [secret])


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
