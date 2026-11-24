"""程序说明：导出统一媒体能力提供方抽象（CapabilityProvider）、ComfyUI 默认实现与全局能力注册表。"""
from .base import (
    AssetRef,
    CancelToken,
    Capability,
    CapabilityInvokeRequest,
    CapabilityInvokeResult,
    CapabilityProvider,
    HttpApiCapabilityProvider,
    OutputKind,
    ProgressCallback,
    ProgressUpdate,
)
from .comfyui_provider import ComfyUICapabilityProvider
from .registry import CapabilityRegistry, capability_registry

capability_registry.register(ComfyUICapabilityProvider())

__all__ = [
    "AssetRef",
    "CancelToken",
    "Capability",
    "CapabilityInvokeRequest",
    "CapabilityInvokeResult",
    "CapabilityProvider",
    "CapabilityRegistry",
    "ComfyUICapabilityProvider",
    "HttpApiCapabilityProvider",
    "OutputKind",
    "ProgressCallback",
    "ProgressUpdate",
    "capability_registry",
]
