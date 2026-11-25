"""程序说明：提供画布的查询、创建、加锁防覆盖合并保存、重命名和级联删除接口。"""
import asyncio
import json
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from services.chat_service import handle_chat
from services.db_service import db_service
from utils.canvas_lock import canvas_lock_manager

router = APIRouter(prefix="/api/canvas")

RECENT_SERVER_MEDIA_GRACE_MS = 120_000


def merge_canvas_data_preserving_unseen_media(
    existing_data: Dict[str, Any] | None,
    incoming_data: Dict[str, Any],
    now_ms: int | None = None,
) -> Dict[str, Any]:
    """合并前端画布快照：保留后台刚落盘但前端快照尚未包含的新生成媒体元素与文件映射。"""
    if not isinstance(existing_data, dict) or not isinstance(incoming_data, dict):
        return incoming_data

    existing_elements = existing_data.get("elements")
    incoming_elements = incoming_data.get("elements")
    if not isinstance(existing_elements, list) or not isinstance(incoming_elements, list):
        return incoming_data

    # Excalidraw 删除元素会保留原 id 并标记 isDeleted=True；完全未出现在 incoming_ids 中说明前端保存时尚未收到该元素
    incoming_ids = {
        str(elem.get("id"))
        for elem in incoming_elements
        if isinstance(elem, dict) and elem.get("id")
    }
    existing_files = (
        existing_data.get("files") if isinstance(existing_data.get("files"), dict) else {}
    )
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms

    missing_server_media = []
    missing_files: Dict[str, Any] = {}
    for elem in existing_elements:
        if not isinstance(elem, dict) or elem.get("isDeleted"):
            continue
        elem_id = str(elem.get("id") or "")
        elem_type = str(elem.get("type") or "")
        if not elem_id or elem_id in incoming_ids:
            continue
        if elem_type not in ("image", "video", "embeddable"):
            continue
        if not (elem_id.startswith("im_") or elem_id.startswith("vi_")):
            continue

        file_id = str(elem.get("fileId") or elem_id)
        file_entry = existing_files.get(file_id)
        # 若前端发来全空数组（例如主动清空），仅保护最近窗口内刚生成的媒体，避免阻挡清空旧画布
        if len(incoming_elements) == 0:
            created_ms = (
                int(file_entry.get("created") or 0) if isinstance(file_entry, dict) else 0
            )
            if current_ms - created_ms > RECENT_SERVER_MEDIA_GRACE_MS:
                continue

        missing_server_media.append(elem)
        if isinstance(file_entry, dict):
            missing_files[file_id] = file_entry

    if not missing_server_media:
        return incoming_data

    merged_files = dict(missing_files)
    if isinstance(incoming_data.get("files"), dict):
        merged_files.update(incoming_data["files"])

    return {
        **incoming_data,
        "elements": [*incoming_elements, *missing_server_media],
        "files": merged_files,
    }


@router.get("/list")
async def list_canvases():
    """列出全部画布。"""
    try:
        return await db_service.list_canvases()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/create")
async def create_canvas(request: Request):
    """先创建画布记录，再异步触发首轮聊天任务。"""
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Invalid request body")

        canvas_id = data.get("canvas_id")
        name = data.get("name")
        if not isinstance(canvas_id, str) or not canvas_id.strip():
            raise HTTPException(status_code=400, detail="canvas_id is required")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=400, detail="name is required")

        # 必须在启动聊天/生图后台任务前先落库画布，避免外键约束或读取失败。
        await db_service.create_canvas(canvas_id, name)
        asyncio.create_task(handle_chat(data))
        return {"id": canvas_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{id}")
async def get_canvas(id: str):
    """获取单个画布详情与关联会话列表。"""
    try:
        canvas = await db_service.get_canvas_data(id)
        if canvas is None:
            raise HTTPException(status_code=404, detail="Canvas not found")
        return canvas
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{id}/save")
async def save_canvas(id: str, request: Request):
    """在画布锁保护下合并并保存画布内容；未提供缩略图时保留已有缩略图。"""
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise HTTPException(status_code=400, detail="Canvas data is required")

        thumbnail = payload.get("thumbnail") if isinstance(payload.get("thumbnail"), str) else None
        async with canvas_lock_manager.lock_canvas(id):
            existing = await db_service.get_canvas_data(id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Canvas not found")
            merged_data = merge_canvas_data_preserving_unseen_media(
                existing.get("data"), payload["data"]
            )
            data_str = json.dumps(merged_data)
            saved = await db_service.save_canvas_data(id, data_str, thumbnail)
        if not saved:
            raise HTTPException(status_code=404, detail="Canvas not found")
        return {"id": id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{id}/rename")
async def rename_canvas(id: str, request: Request):
    """重命名指定画布。"""
    try:
        data = await request.json()
        name = data.get("name") if isinstance(data, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=400, detail="name is required")
        await db_service.rename_canvas(id, name)
        return {"id": id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{id}/delete")
async def delete_canvas(id: str):
    """删除画布并同步清理其关联会话与聊天消息。"""
    try:
        await db_service.delete_canvas(id)
        return {"id": id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
