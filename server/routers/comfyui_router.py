"""程序说明：提供 ComfyUI 多实例配置、健康检测与项目 workflows/ 目录工作流包管理及启停开关路由。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.comfy_instance_service import (
    comfy_instance_service,
    mask_instance_record,
    merge_masked_instance_secret,
    normalize_comfy_base_url,
)
from services.comfy_workflow_ai_importer import (
    auto_import_new_source_workflows,
    fetch_comfy_object_info,
    generate_workflow_config_with_ai,
)
from services.comfy_workflow_pack import (
    SOURCE_WORKFLOWS_DIR,
    WORKFLOWS_DIR,
    WorkflowPackValidationError,
    build_export_pack,
    generate_draft_config,
    get_auto_import_source_enabled,
    save_pack_to_workflows_dir,
    scan_source_workflows_dir,
    set_auto_import_source_enabled,
    summarize_api_json_for_agent,
    sync_workflows_dir_to_db,
    update_pack_enabled_flag,
    validate_workflow_pack,
)
from services.config_service import config_service
from services.db_service import db_service
from services.tool_service import tool_service
from utils.http_client import HttpClient
from utils.path_security import PathSecurityError, validate_comfyui_proxy_target_multi

router = APIRouter(prefix="/api/settings/comfyui")


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


class CreateWorkflowRequest(BaseModel):
    name: str
    api_json: dict
    description: str
    inputs: list
    outputs: Optional[Any] = None
    display_name: Optional[str] = ""
    capability: Optional[str] = "t2i"
    output_kind: Optional[str] = "image"
    instance_id: Optional[str] = None
    seed_strategy: Optional[str] = "random"
    enabled: bool = True


class ImportPairRequest(BaseModel):
    api_json: Any
    config_json: Any
    save_to_dir: bool = True


class DraftConfigRequest(BaseModel):
    api_json: Any
    name: Optional[str] = "custom_workflow"


class InspectWorkflowRequest(BaseModel):
    api_json: Any
    instance_id: Optional[str] = None


class AiImportWorkflowRequest(BaseModel):
    api_json: Any
    name: Optional[str] = ""
    user_hint: Optional[str] = ""
    instance_id: Optional[str] = None
    provider: Optional[str] = ""
    model: Optional[str] = ""
    auto_save: bool = False
    save_to_dir: bool = True


class ToggleWorkflowEnabledRequest(BaseModel):
    enabled: bool


class UpdateWorkflowRequest(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    capability: Optional[str] = None
    output_kind: Optional[str] = None
    instance_id: Optional[str] = None
    seed_strategy: Optional[str] = None
    enabled: Optional[bool] = None
    api_json: Optional[Any] = None
    inputs: Optional[Any] = None
    outputs: Optional[Any] = None


class ExportWorkflowRequest(BaseModel):
    save_to_dir: bool = False


class SyncSourceRequest(BaseModel):
    instance_id: Optional[str] = None
    provider: Optional[str] = ""
    model: Optional[str] = ""
    fallback_to_draft: bool = False


class SourceSettingsRequest(BaseModel):
    auto_import_source: bool


async def _sync_primary_comfy_url_to_config() -> None:
    """将首个启用的实例地址同步回 config_service，兼容旧版单 URL 配置读路径。"""
    instances = await db_service.list_comfy_instances(enabled_only=True)
    primary_url = str(instances[0]["base_url"]) if instances else ""
    cfg = config_service.get_config()
    comfy_cfg = cfg.setdefault("comfyui", {"models": {}, "url": "", "api_key": ""})
    if comfy_cfg.get("url", "") != primary_url:
        comfy_cfg["url"] = primary_url
        await config_service.update_config(cfg)


@router.get("/instances")
async def list_instances():
    """列出全部已配置的 ComfyUI 实例（敏感凭证已掩码）。"""
    try:
        items = await comfy_instance_service.list_instances(masked=True)
        return {"instances": items}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/instances")
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


@router.put("/instances/{instance_id}")
async def update_instance(instance_id: str, payload: ComfyInstancePayload):
    """更新指定 ID 的 ComfyUI 实例配置。"""
    payload_copy = payload.model_copy(update={"id": instance_id})
    return await upsert_instance(payload_copy)


@router.delete("/instances/{instance_id}")
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


@router.post("/instances/{instance_id}/health")
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


def _enrich_workflow_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """为前端管理端组装包含解析后参数、校验状态与完整元数据的响应对象。"""
    raw_api = row.get("api_json")
    raw_inputs = row.get("inputs")
    try:
        parsed_api = json.loads(raw_api) if isinstance(raw_api, str) else (raw_api or {})
    except json.JSONDecodeError:
        parsed_api = {}
    try:
        parsed_inputs = (
            json.loads(raw_inputs) if isinstance(raw_inputs, str) else (raw_inputs or [])
        )
    except json.JSONDecodeError:
        parsed_inputs = []

    pack_validation = validate_workflow_pack(
        parsed_api,
        {
            "schema_version": row.get("schema_version") or 1,
            "name": row.get("name") or "",
            "display_name": row.get("display_name") or row.get("name") or "",
            "capability": row.get("capability") or "t2i",
            "output_kind": row.get("output_kind") or "image",
            "enabled": bool(row.get("enabled", 1)),
            "instance_id": row.get("instance_id") or "",
            "seed_strategy": row.get("seed_strategy") or "random",
            "description": row.get("description") or "",
            "inputs": parsed_inputs if isinstance(parsed_inputs, list) else [],
        },
    )

    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row.get("display_name") or row["name"],
        "description": row.get("description") or "",
        "capability": row.get("capability") or "t2i",
        "output_kind": row.get("output_kind") or "image",
        "instance_id": row.get("instance_id") or "",
        "source_mode": row.get("source_mode") or "db",
        "source_path": row.get("source_path") or "",
        "seed_strategy": row.get("seed_strategy") or "random",
        "schema_version": row.get("schema_version") or 1,
        "enabled": bool(row.get("enabled", 1)),
        "checksum": row.get("checksum") or "",
        "inputs": parsed_inputs if isinstance(parsed_inputs, list) else [],
        "api_json": parsed_api,
        "outputs": row.get("outputs"),
        "validation_errors": pack_validation["errors"],
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.get("/workflows")
async def list_workflows_rich(auto_sync: bool = True):
    """列出全部 ComfyUI 工作流及其元数据和校验结果，并报告 workflows/source/ 中待导入的新文件。"""
    try:
        if auto_sync:
            sync_res = await sync_workflows_dir_to_db(
                db=db_service, workflows_dir=WORKFLOWS_DIR
            )
            if sync_res.get("changed"):
                await tool_service.initialize()

        source_dir = os.path.join(WORKFLOWS_DIR, "source")
        source_scan = scan_source_workflows_dir(
            source_dir=source_dir, workflows_dir=WORKFLOWS_DIR
        )
        rows = await db_service.list_comfy_workflows(enabled_only=False)
        return {
            "workflows_dir": WORKFLOWS_DIR,
            "source_dir": source_scan["source_dir"],
            "pending_source_files": list(source_scan.get("new", []))
            + list(source_scan.get("updated", [])),
            "invalid_source_files": source_scan.get("invalid", []),
            "workflows": [_enrich_workflow_record(r) for r in rows],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/list_workflows")
async def list_workflows():
    """旧版兼容工作流列表端点（返回原始数组）。"""
    try:
        return await db_service.list_comfy_workflows(enabled_only=False)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/workflows/import_pair")
async def import_workflow_pair(request: ImportPairRequest):
    """导入一组 workflow.api.json + jaaz.workflow.json，校验并落盘到项目 workflows/ 目录。"""
    try:
        validation = validate_workflow_pack(request.api_json, request.config_json)
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail="工作流配置校验失败: " + "；".join(validation["errors"]),
            )

        normalized = validation["normalized"]
        api_json = normalized["api_json"]
        cfg = normalized["config_json"]
        checksum = normalized["checksum"]
        source_mode = "db"
        source_path = ""

        if request.save_to_dir:
            saved_dir_info = save_pack_to_workflows_dir(api_json, cfg, WORKFLOWS_DIR)
            source_mode = saved_dir_info["source_mode"]
            source_path = saved_dir_info["source_path"]

        upsert_res = await db_service.upsert_comfy_workflow_by_name(
            name=cfg["name"],
            api_json=json.dumps(api_json, ensure_ascii=False),
            description=cfg["description"],
            inputs=json.dumps(cfg["inputs"], ensure_ascii=False),
            outputs=json.dumps(cfg.get("outputs"), ensure_ascii=False)
            if cfg.get("outputs") is not None
            else None,
            display_name=cfg["display_name"],
            capability=cfg["capability"],
            output_kind=cfg["output_kind"],
            instance_id=cfg["instance_id"] or None,
            source_mode=source_mode,
            source_path=source_path,
            seed_strategy=cfg["seed_strategy"],
            schema_version=cfg["schema_version"],
            enabled=1 if cfg["enabled"] else 0,
            checksum=checksum,
        )
        await tool_service.initialize()
        record = await db_service.get_comfy_workflow_record(upsert_res["id"])
        return {
            "success": True,
            "created": upsert_res["created"],
            "workflow": _enrich_workflow_record(record) if record else None,
        }
    except HTTPException:
        raise
    except WorkflowPackValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/workflows/scan")
async def scan_project_workflows():
    """扫描项目固定 workflows/ 目录并将有效工作流包增量同步到数据库。"""
    try:
        sync_res = await sync_workflows_dir_to_db(
            db=db_service, workflows_dir=WORKFLOWS_DIR
        )
        await tool_service.initialize()
        return {
            "workflows_dir": sync_res["workflows_dir"],
            "synced": sync_res["synced"],
            "errors": sync_res["errors"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/workflows/source_settings")
async def get_source_settings():
    """读取 workflows/source/ 自动导入开关（默认关闭）。"""
    try:
        return {"auto_import_source": get_auto_import_source_enabled()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/workflows/source_settings")
async def update_source_settings(request: SourceSettingsRequest):
    """手动开启或关闭服务启动时自动导入 workflows/source/（开启后会消耗已配置文本模型的 token）。"""
    try:
        enabled = set_auto_import_source_enabled(request.auto_import_source)
        return {"auto_import_source": enabled}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/workflows/sync_source")
async def sync_source_workflows(
    request: SyncSourceRequest = SyncSourceRequest(),
):
    """检测并自动导入 workflows/source/ 中新增或变更的原始 ComfyUI API JSON 文件。"""
    try:
        source_dir = os.path.join(WORKFLOWS_DIR, "source")
        res = await auto_import_new_source_workflows(
            source_dir=source_dir,
            workflows_dir=WORKFLOWS_DIR,
            db=db_service,
            instance_id=request.instance_id,
            provider=request.provider or "",
            model=request.model or "",
            fallback_to_draft=request.fallback_to_draft,
        )
        if res.get("imported"):
            await tool_service.initialize()
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/workflows/inspect")
async def inspect_workflow_api_json(request: InspectWorkflowRequest):
    """为 AI Agent 或设置界面返回过滤连线并融合 /object_info 枚举后的紧凑节点摘要。"""
    try:
        object_info = await fetch_comfy_object_info(request.instance_id)
        summary = summarize_api_json_for_agent(request.api_json, object_info)
        return {
            "used_object_info": bool(object_info),
            **summary,
        }
    except WorkflowPackValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"API JSON 无法解析: {exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/workflows/ai_import")
async def ai_import_workflow(request: AiImportWorkflowRequest):
    """由已配置文本大模型 + ComfyUI /object_info 直接解析 API JSON，生成配置文件并可选一步入库生效。"""
    try:
        ai_res = await generate_workflow_config_with_ai(
            request.api_json,
            suggested_name=request.name or "",
            user_hint=request.user_hint or "",
            instance_id=request.instance_id,
            provider=request.provider or "",
            model=request.model or "",
        )
        config_json = ai_res["config_json"]
        saved_workflow = None

        if request.auto_save:
            api_obj = (
                json.loads(request.api_json)
                if isinstance(request.api_json, str)
                else request.api_json
            )
            import_res = await import_workflow_pair(
                ImportPairRequest(
                    api_json=api_obj,
                    config_json=config_json,
                    save_to_dir=request.save_to_dir,
                )
            )
            saved_workflow = import_res.get("workflow")

        return {
            "success": True,
            "config_json": config_json,
            "model_used": ai_res["model_used"],
            "repaired": ai_res["repaired"],
            "used_object_info": ai_res["used_object_info"],
            "saved": request.auto_save,
            "workflow": saved_workflow,
        }
    except WorkflowPackValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/workflows/draft_config")
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


@router.post("/create_workflow")
async def create_workflow(request: CreateWorkflowRequest):
    """创建工作流（兼容旧接口并附带节点合法性校验）。"""
    if not request.name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not request.api_json:
        raise HTTPException(status_code=400, detail="API JSON is required")
    if not request.description:
        raise HTTPException(status_code=400, detail="Description is required")
    if not request.inputs:
        raise HTTPException(status_code=400, detail="Inputs are required")

    config_payload = {
        "schema_version": 1,
        "name": request.name.replace(" ", "_"),
        "display_name": request.display_name or request.name.replace(" ", "_"),
        "capability": request.capability or "t2i",
        "output_kind": request.output_kind or "image",
        "enabled": request.enabled,
        "instance_id": request.instance_id or "",
        "seed_strategy": request.seed_strategy or "random",
        "description": request.description,
        "inputs": request.inputs,
        "outputs": request.outputs,
    }
    return await import_workflow_pair(
        ImportPairRequest(
            api_json=request.api_json,
            config_json=config_payload,
            save_to_dir=False,
        )
    )


@router.patch("/workflows/{workflow_id}/enabled")
async def toggle_workflow_enabled(
    workflow_id: int, request: ToggleWorkflowEnabledRequest
):
    """启用或停用指定 ComfyUI 工作流；停用后立刻从 Agent 工具注册表移除。"""
    try:
        updated = await db_service.set_comfy_workflow_enabled(
            workflow_id, request.enabled
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="工作流不存在")

        if updated.get("source_mode") in ("pack_dir", "pack_pair") and updated.get("source_path"):
            update_pack_enabled_flag(
                str(updated["source_path"]), bool(request.enabled), WORKFLOWS_DIR
            )

        await tool_service.initialize()
        return {"success": True, "workflow": _enrich_workflow_record(updated)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: int, request: UpdateWorkflowRequest):
    """在单次事务内原地更新工作流配置与元数据，绝不先删再建。"""
    try:
        existing = await db_service.get_comfy_workflow_record(workflow_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="工作流不存在")

        api_json = (
            json.loads(request.api_json)
            if isinstance(request.api_json, str)
            else (request.api_json if request.api_json is not None else json.loads(existing["api_json"]))
        )
        inputs_val = (
            json.loads(request.inputs)
            if isinstance(request.inputs, str)
            else (request.inputs if request.inputs is not None else json.loads(existing["inputs"] or "[]"))
        )
        config_candidate = {
            "schema_version": existing.get("schema_version") or 1,
            "name": request.name if request.name is not None else existing["name"],
            "display_name": (
                request.display_name
                if request.display_name is not None
                else (existing.get("display_name") or existing["name"])
            ),
            "capability": (
                request.capability
                if request.capability is not None
                else (existing.get("capability") or "t2i")
            ),
            "output_kind": (
                request.output_kind
                if request.output_kind is not None
                else (existing.get("output_kind") or "image")
            ),
            "instance_id": (
                request.instance_id
                if request.instance_id is not None
                else (existing.get("instance_id") or "")
            ),
            "seed_strategy": (
                request.seed_strategy
                if request.seed_strategy is not None
                else (existing.get("seed_strategy") or "random")
            ),
            "enabled": (
                request.enabled
                if request.enabled is not None
                else bool(existing.get("enabled", 1))
            ),
            "description": (
                request.description
                if request.description is not None
                else (existing.get("description") or "")
            ),
            "inputs": inputs_val,
            "outputs": request.outputs if request.outputs is not None else existing.get("outputs"),
        }

        validation = validate_workflow_pack(api_json, config_candidate)
        if not validation["valid"]:
            raise HTTPException(
                status_code=400,
                detail="工作流配置校验失败: " + "；".join(validation["errors"]),
            )
        norm_cfg = validation["normalized"]["config_json"]
        updated = await db_service.update_comfy_workflow(
            workflow_id,
            {
                "name": norm_cfg["name"],
                "display_name": norm_cfg["display_name"],
                "description": norm_cfg["description"],
                "capability": norm_cfg["capability"],
                "output_kind": norm_cfg["output_kind"],
                "instance_id": norm_cfg["instance_id"] or None,
                "seed_strategy": norm_cfg["seed_strategy"],
                "enabled": 1 if norm_cfg["enabled"] else 0,
                "api_json": json.dumps(validation["normalized"]["api_json"], ensure_ascii=False),
                "inputs": json.dumps(norm_cfg["inputs"], ensure_ascii=False),
                "checksum": validation["normalized"]["checksum"],
            },
        )
        if existing.get("source_mode") in ("pack_dir", "pack_pair") and updated is not None:
            save_pack_to_workflows_dir(
                validation["normalized"]["api_json"], norm_cfg, WORKFLOWS_DIR
            )

        await tool_service.initialize()
        return {
            "success": True,
            "workflow": _enrich_workflow_record(updated) if updated else None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/export")
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


@router.post("/workflows/{workflow_id}/export")
async def export_workflow_post(
    workflow_id: int, request: ExportWorkflowRequest = ExportWorkflowRequest()
):
    """将已有工作流导出为标准文件对，可选同步保存至项目 workflows/<name>/ 目录。"""
    try:
        record = await db_service.get_comfy_workflow_record(workflow_id)
        if record is None:
            raise HTTPException(status_code=404, detail="工作流不存在")
        pack = build_export_pack(record)
        saved_path = ""
        if request.save_to_dir:
            saved_info = save_pack_to_workflows_dir(
                pack["api_json"], pack["config_json"], WORKFLOWS_DIR
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
            "workflow": _enrich_workflow_record(record),
            **pack,
        }
    except HTTPException:
        raise
    except WorkflowPackValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/workflows/{workflow_id}")
@router.delete("/delete_workflow/{workflow_id}")
async def delete_workflow(workflow_id: int):
    """删除工作流并立即刷新 Agent 工具注册。"""
    try:
        await db_service.delete_comfy_workflow(workflow_id)
        await tool_service.initialize()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/proxy")
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
