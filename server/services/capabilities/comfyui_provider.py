"""程序说明：将本地/远程 ComfyUI 多实例与已启用工作流包装为默认 CapabilityProvider 实现。"""
from __future__ import annotations

import asyncio
from io import BytesIO
import json
import os
from typing import Any, Dict, List, Optional

from routers.comfyui_execution import upload_image
from services.comfy_instance_service import comfy_instance_service
from services.config_service import FILES_DIR
from services.db_service import db_service
from tools.comfy_dynamic import apply_workflow_inputs_and_seeds, resolve_comfy_input_image_path
from tools.utils.comfyui import ComfyUIWorkflowRunner

from .base import (
    AssetRef,
    CancelToken,
    CapabilityInvokeRequest,
    CapabilityInvokeResult,
    ProgressCallback,
    ProgressUpdate,
)


class ComfyUICapabilityProvider:
    """基于已启用的 ComfyUI 工作流与多实例调度的默认媒体能力提供方。"""

    provider_id: str = "comfyui"
    priority: int = 10

    def supported_capabilities(self) -> set[str]:
        workflows = db_service._list_comfy_workflows_sync(enabled_only=True)
        return {
            str(wf.get("capability") or "t2i")
            for wf in workflows
            if wf.get("enabled", 1)
        }

    def supports(self, capability: str) -> bool:
        return capability in self.supported_capabilities()

    async def health_check(self) -> Dict[str, Any]:
        instances = await comfy_instance_service.list_instances(masked=True)
        return {
            "provider_id": self.provider_id,
            "instances": len(instances),
            "enabled_instances": sum(1 for item in instances if item.get("enabled", 1)),
            "capabilities": sorted(self.supported_capabilities()),
        }

    async def _select_workflow(
        self, request: CapabilityInvokeRequest
    ) -> Dict[str, Any]:
        """仅从 enabled=1 的工作流中选择匹配 workflow_name 或 capability 的工作流。"""
        enabled_wfs = await db_service.list_comfy_workflows(enabled_only=True)
        if request.workflow_name:
            for wf in enabled_wfs:
                if wf.get("name") == request.workflow_name:
                    return wf
            raise ValueError(
                f"ComfyUI workflow '{request.workflow_name}' is not enabled or does not exist"
            )

        for wf in enabled_wfs:
            if (wf.get("capability") or "t2i") == request.capability:
                return wf
        raise ValueError(
            f"No enabled ComfyUI workflow found for capability '{request.capability}'"
        )

    async def invoke(
        self,
        request: CapabilityInvokeRequest,
        on_progress: Optional[ProgressCallback] = None,
        cancel_token: Optional[CancelToken] = None,
    ) -> CapabilityInvokeResult:
        if cancel_token and cancel_token.is_cancelled:
            raise asyncio.CancelledError("ComfyUI capability invocation cancelled")

        wf = await self._select_workflow(request)
        instance = await comfy_instance_service.resolve_instance(
            request.instance_id or wf.get("instance_id")
        )
        base_url = str(instance["base_url"]).rstrip("/")
        headers = dict(instance.get("headers") or {})
        instance_id = str(instance.get("id") or "default")
        timeout_sec = float(instance.get("timeout_sec") or 600)

        raw_inputs = wf.get("inputs") or "[]"
        input_defs: List[Dict[str, Any]] = (
            raw_inputs if isinstance(raw_inputs, list) else json.loads(raw_inputs)
        )
        raw_api = wf.get("api_json") or "{}"
        workflow_dict = json.loads(raw_api) if isinstance(raw_api, str) else dict(raw_api)

        required_data = dict(request.params)
        for key, value in required_data.items():
            image_path = resolve_comfy_input_image_path(value, FILES_DIR)
            if not image_path:
                continue
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            sha256_hex = comfy_instance_service.compute_bytes_sha256(image_bytes)
            cached = comfy_instance_service.get_cached_upload(instance_id, sha256_hex)
            if cached:
                required_data[key] = cached
            else:
                uploaded = await upload_image(
                    BytesIO(image_bytes),
                    base_url,
                    os.path.basename(image_path),
                    headers=headers,
                )
                comfy_instance_service.set_cached_upload(
                    instance_id, sha256_hex, uploaded
                )
                required_data[key] = uploaded

        prepared = apply_workflow_inputs_and_seeds(
            workflow_dict,
            input_defs,
            required_data,
            seed_strategy=str(wf.get("seed_strategy") or "random"),
        )

        if on_progress:
            await on_progress(ProgressUpdate(pct=5.0, text=f"Submitting {wf['name']}"))

        runner = ComfyUIWorkflowRunner(
            prepared,
            base_url,
            headers=headers,
            timeout=timeout_sec,
            instance_id=instance_id,
        )
        ctx = {
            "session_id": request.session_id,
            "canvas_id": request.canvas_id,
            "tool_call_id": request.tool_call_id,
        }
        raw_outputs = await runner.generate(ctx=ctx)

        assets: List[AssetRef] = []
        for idx, item in enumerate(raw_outputs):
            mime_type, width, height, filename = item
            kind: Any = (
                "video"
                if mime_type.startswith("video")
                else "audio"
                if mime_type.startswith("audio")
                else "image"
            )
            assets.append(
                AssetRef(
                    asset_id=f"{wf['name']}_{idx}",
                    kind=kind,
                    file_path=os.path.join(FILES_DIR, filename),
                    mime_type=mime_type,
                    url=f"/api/file/{filename}",
                    width=int(width or 0),
                    height=int(height or 0),
                )
            )

        return CapabilityInvokeResult(
            provider_id=self.provider_id,
            capability=request.capability,
            outputs=assets,
            metadata={"workflow": wf["name"], "instance_id": instance_id},
        )
