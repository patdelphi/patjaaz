# services/chat_service.py

# Import necessary modules
import asyncio
from utils.log_sanitizer import get_sanitized_logger
_logger = get_sanitized_logger(__name__)
import json
from typing import Dict, Any, List, Optional

# Import service modules
from models.tool_model import ToolInfoJson
from services.db_service import db_service
from services.langgraph_service import langgraph_multi_agent
from services.settings_service import settings_service
from services.websocket_service import send_to_websocket
from services.stream_service import (
    add_stream_task,
    release_stream_session,
    remove_stream_task,
    reserve_stream_session,
)
from models.config_model import ModelInfo


async def handle_chat(data: Dict[str, Any]) -> None:
    """
    Handle an incoming chat request.

    Workflow:
    - Parse incoming chat data.
    - Optionally inject system prompt.
    - Save chat session and messages to the database.
    - Launch langgraph_agent task to process chat.
    - Manage stream task lifecycle (add, remove).
    - Notify frontend via WebSocket when stream is done.

    Args:
        data (dict): Chat request data containing:
            - messages: list of message dicts
            - session_id: unique session identifier
            - canvas_id: canvas identifier (contextual use)
            - text_model: text model configuration
            - tool_list: list of tool model configurations (images/videos)
    """
    # Extract fields from incoming data
    messages: List[Dict[str, Any]] = data.get('messages', [])
    session_id: str = data.get('session_id', '')
    canvas_id: str = data.get('canvas_id', '')
    text_model: ModelInfo = data.get('text_model', {})
    tool_list: List[ToolInfoJson] = data.get('tool_list', [])

    _logger.info('👇 chat_service got tool_list', tool_list)
    # 若请求未传自定义系统提示词，则回退读取服务端 settings 持久化配置
    system_prompt: Optional[str] = data.get('system_prompt')
    if not system_prompt:
        saved_prompt = settings_service.get_raw_settings().get('system_prompt')
        if isinstance(saved_prompt, str) and saved_prompt.strip():
            system_prompt = saved_prompt.strip()

    # 空消息列表（例如仅新建空白画布）无需启动智能体会话。
    if not messages:
        return

    # 任务运行中收到相同会话的重复提交时直接复用当前任务。
    if not reserve_stream_session(session_id):
        return

    try:
        # If there is only one message, create a new chat session
        if len(messages) == 1:
            prompt = messages[0].get('content', '')
            await db_service.create_chat_session(
                session_id,
                text_model.get('model'),
                text_model.get('provider'),
                canvas_id,
                prompt[:200] if isinstance(prompt, str) else '',
            )

        if messages:
            await db_service.create_message(
                session_id, messages[-1].get('role', 'user'), json.dumps(messages[-1])
            )

        # 模型和 ComfyUI 任务可能持续数分钟，交给后台执行，避免代理关闭长时间 HTTP 请求。
        task = asyncio.create_task(
            _run_chat_task(
                messages, canvas_id, session_id, text_model, tool_list, system_prompt
            ),
            name=f"chat:{session_id}",
        )
        if not add_stream_task(session_id, task):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        release_stream_session(session_id)


async def _run_chat_task(
    messages: List[Dict[str, Any]],
    canvas_id: str,
    session_id: str,
    text_model: ModelInfo,
    tool_list: List[ToolInfoJson],
    system_prompt: Optional[str],
) -> None:
    """后台运行聊天智能体，并通过 Socket.IO 通知前端完成或失败。"""
    terminal_state = "completed"
    error_message: Optional[str] = None
    try:
        await langgraph_multi_agent(
            messages, canvas_id, session_id, text_model, tool_list, system_prompt
        )
    except asyncio.CancelledError:
        terminal_state = "cancelled"
        _logger.info(f"🛑Session {session_id} cancelled during stream")
    except Exception as error:
        terminal_state = "failed"
        error_message = str(error)
        _logger.info(f"Chat session {session_id} failed: {error}")
        await send_to_websocket(session_id, {
            'type': 'error',
            'error': error_message,
        })
    finally:
        remove_stream_task(session_id, terminal_state, error_message)
        await send_to_websocket(session_id, {
            'type': 'done'
        })
