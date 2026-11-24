"""程序说明：提供聊天发起、任务状态查询与会话取消（含远端 ComfyUI 中断联动）API 路由。"""
from fastapi import APIRouter, HTTPException, Request
from services.chat_service import handle_chat
from services.comfy_instance_service import comfy_instance_service
from services.stream_service import get_stream_status, get_stream_task

router = APIRouter(prefix="/api")


@router.post("/chat")
async def chat(request: Request):
    """接收聊天请求并启动后台智能体流。"""
    try:
        data = await request.json()
        await handle_chat(data)
        return {"status": "accepted", "session_id": data.get("session_id", "")}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/chat/status/{session_id}")
async def chat_status(session_id: str):
    """返回活跃聊天任务状态，供页面刷新或重连后恢复进度。"""
    return get_stream_status(session_id)


@router.post("/cancel/{session_id}")
async def cancel_chat(session_id: str):
    """取消指定会话的进行中后台任务，并联动中止对应的远端 ComfyUI 队列/生成。"""
    task = get_stream_task(session_id)
    local_cancelled = False
    if task and not task.done():
        task.cancel()
        local_cancelled = True

    remote_cancelled = await comfy_instance_service.cancel_session_prompts(session_id)
    if local_cancelled or remote_cancelled:
        return {"status": "cancelled", "remote_cancelled": remote_cancelled}
    return {"status": "not_found_or_done"}
