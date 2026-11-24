"""程序说明：实现媒体能力注册表与按优先级排序、故障自动转移的调度路由器。"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from routers.comfyui_execution import ComfyUIUnavailableError
from utils.path_security import PathSecurityError

from .base import (
    CancelToken,
    CapabilityInvokeRequest,
    CapabilityInvokeResult,
    CapabilityProvider,
    ProgressCallback,
)

# 仅在目标不可达/网络中断时尝试切换下一个支持同能力的提供方，避免参数错误掩盖真实问题
_FALLBACK_EXCEPTIONS = (
    ComfyUIUnavailableError,
    ConnectionError,
    TimeoutError,
    OSError,
)


class CapabilityRegistry:
    """集中维护已注册的 CapabilityProvider 并按 capability + priority 执行路由。"""

    def __init__(self) -> None:
        self._providers: Dict[str, CapabilityProvider] = {}

    def register(self, provider: CapabilityProvider) -> None:
        self._providers[provider.provider_id] = provider

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def get(self, provider_id: str) -> Optional[CapabilityProvider]:
        return self._providers.get(provider_id)

    def list_providers(self) -> List[Dict[str, Any]]:
        """列出全部提供方及其当前支持的能力集合。"""
        ordered = sorted(
            self._providers.values(),
            key=lambda p: (getattr(p, "priority", 100), p.provider_id),
        )
        return [
            {
                "provider_id": p.provider_id,
                "priority": getattr(p, "priority", 100),
                "capabilities": sorted(p.supported_capabilities()),
            }
            for p in ordered
        ]

    def list_capabilities(self) -> Dict[str, List[str]]:
        """按能力汇总可用提供方列表。"""
        mapping: Dict[str, List[str]] = {}
        ordered = sorted(
            self._providers.values(),
            key=lambda p: (getattr(p, "priority", 100), p.provider_id),
        )
        for provider in ordered:
            for cap in sorted(provider.supported_capabilities()):
                mapping.setdefault(cap, []).append(provider.provider_id)
        return mapping

    def resolve_candidates(
        self,
        capability: str,
        preferred_provider: Optional[str] = None,
    ) -> List[CapabilityProvider]:
        """按首选提供方与优先级顺序返回支持指定能力的提供方候选列表。"""
        candidates = [
            provider
            for provider in self._providers.values()
            if provider.supports(capability)
        ]
        candidates.sort(
            key=lambda p: (
                0 if preferred_provider and p.provider_id == preferred_provider else 1,
                getattr(p, "priority", 100),
                p.provider_id,
            )
        )
        return candidates

    async def invoke(
        self,
        request: CapabilityInvokeRequest,
        *,
        preferred_provider: Optional[str] = None,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> CapabilityInvokeResult:
        """按候选顺序执行能力调用，发生服务不可用故障时自动回退下一候选提供方。"""
        candidates = self.resolve_candidates(
            request.capability, preferred_provider=preferred_provider
        )
        if not candidates:
            raise LookupError(
                f"No registered CapabilityProvider supports capability '{request.capability}'"
            )

        last_error: Optional[Exception] = None
        for idx, provider in enumerate(candidates):
            if cancel_token and cancel_token.is_cancelled:
                raise asyncio.CancelledError("Capability invocation cancelled")
            try:
                return await provider.invoke(
                    request, on_progress=on_progress, cancel_token=cancel_token
                )
            except (asyncio.CancelledError, PathSecurityError, ValueError, FileNotFoundError):
                raise
            except _FALLBACK_EXCEPTIONS as exc:
                last_error = exc
                if idx == len(candidates) - 1:
                    raise
                continue

        assert last_error is not None
        raise last_error


capability_registry = CapabilityRegistry()
