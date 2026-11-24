# services/stream_service.py
from typing import Dict, Optional, Any
import asyncio
import time

# Dictionary to store active stream tasks, keyed by session_id
stream_tasks: Dict[str, asyncio.Task[Any]] = {}
stream_statuses: Dict[str, Dict[str, Any]] = {}
reserved_stream_sessions: set[str] = set()
MAX_TERMINAL_STATUSES = 500


def reserve_stream_session(session_id: str) -> bool:
    """同步预占会话 ID，避免并发重复请求重复写消息或启动任务。"""
    task = stream_tasks.get(session_id)
    if session_id in reserved_stream_sessions or (task and not task.done()):
        return False
    reserved_stream_sessions.add(session_id)
    return True


def release_stream_session(session_id: str) -> None:
    """释放聊天请求初始化阶段的会话预占。"""
    reserved_stream_sessions.discard(session_id)

def add_stream_task(
    session_id: str,
    task: asyncio.Task[Any],
    status: str = "Task is running",
) -> bool:
    """
    Add a stream task for the given session_id.

    Args:
        session_id (str): Unique identifier for the session.
        task: The task object to associate with the session.
    """
    existing_task = stream_tasks.get(session_id)
    if existing_task and not existing_task.done():
        return False

    stream_tasks[session_id] = task
    stream_statuses[session_id] = {
        "active": True,
        "status": status,
        "started_at": time.time(),
        "terminal_state": None,
    }
    return True


def update_stream_status(session_id: str, status: str) -> None:
    """更新活跃任务状态快照，供页面重连后恢复显示。"""
    snapshot = stream_statuses.get(session_id)
    if snapshot is not None:
        snapshot["status"] = status


def get_stream_status(session_id: str) -> Dict[str, Any]:
    """获取任务状态；保留最近终态以便前端通过轮询恢复 Socket 漏报。"""
    task = stream_tasks.get(session_id)
    snapshot = stream_statuses.get(session_id)
    if snapshot is None:
        return {"known": False, "active": False}

    status = {
        "known": True,
        "active": bool(task and not task.done() and snapshot.get("active", True)),
        "status": snapshot["status"],
        "started_at": snapshot["started_at"],
        "terminal_state": snapshot.get("terminal_state"),
    }
    if snapshot.get("error"):
        status["error"] = snapshot["error"]
    return status


def remove_stream_task(
    session_id: str,
    terminal_state: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """
    Remove the stream task associated with the given session_id.

    Args:
        session_id (str): Unique identifier for the session.
    """
    stream_tasks.pop(session_id, None)
    snapshot = stream_statuses.get(session_id)
    if terminal_state and snapshot is not None:
        labels = {
            "completed": "Task completed",
            "failed": "Task failed",
            "cancelled": "Task cancelled",
        }
        snapshot.update({
            "active": False,
            "status": labels.get(terminal_state, "Task ended"),
            "terminal_state": terminal_state,
            "finished_at": time.time(),
        })
        if error:
            snapshot["error"] = error
        _prune_terminal_statuses()
    else:
        stream_statuses.pop(session_id, None)


def _prune_terminal_statuses() -> None:
    """限制内存中保留的已结束状态数量，避免长时间运行后无限增长。"""
    terminal_ids = [
        session_id
        for session_id, snapshot in stream_statuses.items()
        if not snapshot.get("active")
    ]
    excess = len(stream_statuses) - MAX_TERMINAL_STATUSES
    if excess <= 0:
        return
    oldest_ids = sorted(
        terminal_ids,
        key=lambda session_id: stream_statuses[session_id].get("finished_at", 0),
    )[:excess]
    for session_id in oldest_ids:
        stream_statuses.pop(session_id, None)

def get_stream_task(session_id: str) -> Optional[asyncio.Task[Any]]:
    """
    Retrieve the stream task associated with the given session_id.

    Args:
        session_id (str): Unique identifier for the session.

    Returns:
        The task object if found, otherwise None.
    """
    return stream_tasks.get(session_id)

# 你也可以加一个 list_stream_tasks() 返回所有 session_id
