"""程序说明：定义可插拔媒体生成能力协议（CapabilityProvider）、标准资产引用与外部 HTTP API 基类。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Protocol, runtime_checkable

Capability = Literal[
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
]

OutputKind = Literal["image", "video", "audio", "text"]


@dataclass
class AssetRef:
    """跨工作流与扩展能力流转的标准本地资产引用。"""

    asset_id: str
    kind: Literal["image", "video", "audio", "mask"]
    file_path: str
    mime_type: str
    url: str = ""
    width: int = 0
    height: int = 0
    duration_ms: int = 0


@dataclass
class ProgressUpdate:
    """统一的任务进度汇报结构。"""

    pct: float
    text: str
    queue_ahead: Optional[int] = None


ProgressCallback = Callable[[ProgressUpdate], Awaitable[None]]


class CancelToken:
    """异步任务取消令牌，供 CapabilityProvider 轮询或等待取消信号。"""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    async def wait_cancelled(self) -> None:
        await self._event.wait()


@dataclass
class CapabilityInvokeRequest:
    """调用具体能力提供方的统一请求载体。"""

    capability: str
    params: Dict[str, Any] = field(default_factory=dict)
    inputs: List[AssetRef] = field(default_factory=list)
    workflow_name: Optional[str] = None
    instance_id: Optional[str] = None
    session_id: str = ""
    canvas_id: str = ""
    tool_call_id: str = ""


@dataclass
class CapabilityInvokeResult:
    """能力执行完成后的标准返回载体。"""

    provider_id: str
    capability: str
    outputs: List[AssetRef] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CapabilityProvider(Protocol):
    """媒体能力提供方统一协议（ComfyUI 及未来外部 TTS/ASR/音乐 API 均实现此接口）。"""

    provider_id: str
    priority: int

    def supported_capabilities(self) -> set[str]:
        ...

    def supports(self, capability: str) -> bool:
        ...

    async def health_check(self) -> Dict[str, Any]:
        ...

    async def invoke(
        self,
        request: CapabilityInvokeRequest,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> CapabilityInvokeResult:
        ...


class HttpApiCapabilityProvider:
    """面向未来 TTS / ASR / 音乐等外部 HTTP API 能力提供方的抽象基类。"""

    def __init__(
        self,
        provider_id: str,
        capabilities: set[str],
        *,
        base_url: str = "",
        api_key: str = "",
        priority: int = 200,
        timeout_sec: float = 60.0,
    ) -> None:
        self.provider_id = provider_id
        self._capabilities = set(capabilities)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.priority = priority
        self.timeout_sec = timeout_sec

    def supported_capabilities(self) -> set[str]:
        return set(self._capabilities)

    def supports(self, capability: str) -> bool:
        return capability in self._capabilities

    async def health_check(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "configured": bool(self.base_url and self.api_key),
            "capabilities": sorted(self._capabilities),
        }

    async def invoke(
        self,
        request: CapabilityInvokeRequest,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> CapabilityInvokeResult:
        if not self.supports(request.capability):
            raise ValueError(
                f"Provider '{self.provider_id}' does not support capability '{request.capability}'"
            )
        if cancel_token and cancel_token.is_cancelled:
            raise asyncio.CancelledError("Capability invocation cancelled before start")
        return await self._execute_http(request, on_progress=on_progress, cancel_token=cancel_token)

    async def _execute_http(
        self,
        request: CapabilityInvokeRequest,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> CapabilityInvokeResult:
        raise NotImplementedError("Subclasses must implement _execute_http")
