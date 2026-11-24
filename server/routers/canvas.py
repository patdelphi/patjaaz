"""程序说明：提供画布的查询、创建、加锁保存、重命名和级联删除接口。"""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request

from services.chat_service import handle_chat
from services.db_service import db_service
from utils.canvas_lock import canvas_lock_manager

router = APIRouter(prefix="/api/canvas")


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
    """在画布锁保护下保存画布内容；未提供缩略图时保留已有缩略图。"""
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise HTTPException(status_code=400, detail="Canvas data is required")

        data_str = json.dumps(payload["data"])
        thumbnail = payload.get("thumbnail") if isinstance(payload.get("thumbnail"), str) else None
        async with canvas_lock_manager.lock_canvas(id):
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
