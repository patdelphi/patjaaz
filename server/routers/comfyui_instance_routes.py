"""程序说明：提供 ComfyUI 多实例增删改查、健康检查探测、只读代理以及草稿/源文件设置与导出子路由。"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
import httpx
from pydantic import BaseModel

from services.comfy_instance_service import (
    comfy_instance_service,
    mask_instance_record,
    merge_masked_instance_secret,
    normalize_comfy_base_url,
)
from services.comfy_workflow_pack import (
    WorkflowPackValidationError,
    build_export_pack,
    generate_draft_config,
    get_auto_import_source_enabled,
    save_pack_to_workflows_dir,
    set_auto_import_source_enabled,
)
from services.config_service import config_service
from services.db_service import db_service
from services.tool_service import tool_service
from utils.http_client import HttpClient
from utils.path_security import PathSecurityError, validate_comfyui_proxy_target_multi

instance_router = APIRouter()


class DraftConfigRequest(BaseModel):
    api_json: Any
    name: Optional[str] = "custom_workflow"


class ExportWorkflowRequest(BaseModel):
    save_to_dir: bool = False


class SourceSettingsRequest(BaseModel):
    auto_import_source: bool


class ComfyInstancePayload(BaseModel):
    id: Optional[str] = None
    name: str
    base_url: str
    auth_type: str = "none"
    auth_header_name: str = ""
    auth_secret: str = ""
    max_concurrency: int = 1
    timeout_sec: int = 300
    enabled: bool = True
    priority: int = 100
    capabilities: Optional[List[str]] = None



async def _sync_primary_comfy_url_to_config() -> None:
    """将首个启用的实例地址同步回 config_service，兼容旧版单 URL 配置读路径。"""
    instances = await db_service.list_comfy_instances(enabled_only=True)
    primary_url = str(instances[0]["base_url"]) if instances else ""
    cfg = config_service.get_config()
    comfy_cfg = cfg.setdefault("comfyui", {"models": {}, "url": "", "api_key": ""})
    if comfy_cfg.get("url", "") != primary_url:
        comfy_cfg["url"] = primary_url
        await config_service.update_config(cfg)


@instance_router.get("/instances")
async def list_instances():
    """列出全部已配置的 ComfyUI 实例（敏感凭证已掩码）。"""
    try:
        items = await comfy_instance_service.list_instances(masked=True)
        return {"instances": items}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.post("/instances")
async def upsert_instance(payload: ComfyInstancePayload):
    """新增或更新 ComfyUI 实例配置（支持反代子路径与鉴权信息）。"""
    try:
        raw_id = (payload.id or payload.name).strip().lower().replace(" ", "_")
        if not raw_id:
            raise HTTPException(status_code=400, detail="实例 ID 或名称不能为空")
        try:
            normalized_url = normalize_comfy_base_url(payload.base_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        existing = await db_service.get_comfy_instance(raw_id)
        data: Dict[str, Any] = {
            "id": raw_id,
            "name": payload.name.strip() or raw_id,
            "base_url": normalized_url,
            "auth_type": payload.auth_type,
            "auth_header_name": payload.auth_header_name,
            "auth_secret": payload.auth_secret,
            "max_concurrency": payload.max_concurrency,
            "timeout_sec": payload.timeout_sec,
            "enabled": 1 if payload.enabled else 0,
            "priority": payload.priority,
            "capabilities_json": payload.capabilities or ["t2i", "i2i", "t2v", "i2v", "tts"],
        }
        data = merge_masked_instance_secret(data, existing)
        saved = await db_service.upsert_comfy_instance(data)
        await _sync_primary_comfy_url_to_config()
        await tool_service.initialize()
        return {"instance": mask_instance_record(saved)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.put("/instances/{instance_id}")
async def update_instance(instance_id: str, payload: ComfyInstancePayload):
    """更新指定 ID 的 ComfyUI 实例配置。"""
    payload_copy = payload.model_copy(update={"id": instance_id})
    return await upsert_instance(payload_copy)


@instance_router.delete("/instances/{instance_id}")
async def delete_instance(instance_id: str):
    """删除指定 ComfyUI 实例并刷新工具注册。"""
    try:
        deleted = await db_service.delete_comfy_instance(instance_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="ComfyUI 实例不存在")
        await _sync_primary_comfy_url_to_config()
        await tool_service.initialize()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.post("/instances/{instance_id}/health")
async def check_instance_health(instance_id: str):
    """触发指定 ComfyUI 实例健康检查并刷新缓存状态。"""
    try:
        snapshot = await comfy_instance_service.probe_instance_health(instance_id)
        return {"instance_id": instance_id, "health": snapshot}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc



@instance_router.post("/proxy")
async def comfyui_proxy(request: Request):
    """向白名单内的已配置 ComfyUI 实例转发只读查询并自动附带鉴权头。"""
    try:
        data = await request.json()
        requested_url = data.get("url")
        path = data.get("path", "")
        allowed_urls = await comfy_instance_service.get_allowed_proxy_urls()

        try:
            full_url = validate_comfyui_proxy_target_multi(
                allowed_urls, requested_url, path
            )
        except PathSecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        base_target = requested_url or (allowed_urls[0] if allowed_urls else "")
        headers = await comfy_instance_service.find_headers_for_url(base_target)
        async with HttpClient.create(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(full_url, headers=headers or None)
            response.raise_for_status()
            return response.json()
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"ComfyUI server returned status {exc.response.status_code}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Proxy request failed: {str(exc)}"
        ) from exc


@instance_router.get("/workflows/source_settings")
async def get_source_settings():
    """读取 workflows/source/ 自动导入开关（默认关闭）。"""
    try:
        return {"auto_import_source": get_auto_import_source_enabled()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.put("/workflows/source_settings")
async def update_source_settings(request: SourceSettingsRequest):
    """手动开启或关闭服务启动时自动导入 workflows/source/。"""
    try:
        enabled = set_auto_import_source_enabled(request.auto_import_source)
        return {"auto_import_source": enabled}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.post("/workflows/draft_config")
async def draft_workflow_config(request: DraftConfigRequest):
    """根据上传的单个 ComfyUI API JSON 自动生成标准 jaaz.workflow.json 模板草稿。"""
    try:
        draft = generate_draft_config(
            request.api_json, suggested_name=request.name or "custom_workflow"
        )
        return {"config_json": draft}
    except WorkflowPackValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"API JSON 无法解析: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.get("/workflows/{workflow_id}/export")
async def export_workflow_get(workflow_id: int):
    """获取数据库工作流对应的标准成对文件内容。"""
    try:
        record = await db_service.get_comfy_workflow_record(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="工作流不存在")
        return build_export_pack(record)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@instance_router.post("/workflows/{workflow_id}/export")
async def export_workflow_post(
    workflow_id: int, request: ExportWorkflowRequest = ExportWorkflowRequest()
):
    """将已有工作流导出为标准文件对，可选同步保存至项目 workflows/<name>/ 目录。"""
    import routers.comfyui_router as _cr

    try:
        record = await db_service.get_comfy_workflow_record(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="工作流不存在")
        pack = build_export_pack(record)
        saved_path = ""
        if request.save_to_dir:
            saved_info = save_pack_to_workflows_dir(
                pack["api_json"], pack["config_json"], _cr.WORKFLOWS_DIR
            )
            saved_path = saved_info["source_path"]
            updated = await db_service.update_comfy_workflow(
                workflow_id,
                {
                    "source_mode": saved_info["source_mode"],
                    "source_path": saved_path,
                    "checksum": saved_info["checksum"],
                },
            )
            if updated is not None:
                record = updated
        return {
            "success": True,
            "saved_path": saved_path,
            "workflow": _cr._enrich_workflow_record(record),
            **pack,
        }
    except HTTPException:
        raise
    except WorkflowPackValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

