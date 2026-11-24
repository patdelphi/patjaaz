"""程序说明：管理 Socket.IO 服务实例、受限跨域来源校验及绑定会话生命周期的活跃连接。"""
import os
import time
from typing import Any, Dict, List, Optional
import socketio

DEFAULT_SOCKET_ORIGINS = {
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:57988",
    "http://127.0.0.1:57988",
}


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def _same_origin_candidates(environ: Optional[Dict[str, Any]]) -> set[str]:
    """根据当前请求或反代头部提取同源 Origin 列表（用于隧道或本机代理访问）。"""
    candidates: set[str] = set()
    if not isinstance(environ, dict):
        return candidates

    scheme = str(environ.get("wsgi.url_scheme", "")).strip().lower()
    host = str(environ.get("HTTP_HOST", "")).strip()
    if scheme and host:
        candidates.add(_normalize_origin(f"{scheme}://{host}"))

    scope = environ.get("asgi.scope")
    client = scope.get("client") if isinstance(scope, dict) else None
    client_ip = client[0] if isinstance(client, (tuple, list)) and client else None
    # 仅在未提供 client 或来自本机反向代理时采信 X-Forwarded-*。
    if client_ip in (None, "127.0.0.1", "::1"):
        fwd_proto = str(environ.get("HTTP_X_FORWARDED_PROTO", "")).split(",", 1)[0].strip().lower()
        fwd_host = str(environ.get("HTTP_X_FORWARDED_HOST", "")).split(",", 1)[0].strip()
        effective_scheme = fwd_proto or scheme
        effective_host = fwd_host or host
        if effective_scheme and effective_host:
            candidates.add(_normalize_origin(f"{effective_scheme}://{effective_host}"))

    return candidates


def is_allowed_socket_origin(
    origin: Optional[str],
    environ: Optional[Dict[str, Any]] = None,
    extra_origins: Optional[list[str]] = None,
) -> bool:
    """校验 Socket.IO 握手 Origin 是否在本地默认源、配置白名单或当前同源内。"""
    if not isinstance(origin, str) or not origin.strip():
        return False

    normalized = _normalize_origin(origin)
    allowed = {_normalize_origin(item) for item in DEFAULT_SOCKET_ORIGINS}

    env_origins = os.getenv("JAAZ_ALLOWED_ORIGINS", "")
    for item in env_origins.split(","):
        if item.strip():
            allowed.add(_normalize_origin(item))

    if extra_origins:
        for item in extra_origins:
            if isinstance(item, str) and item.strip():
                allowed.add(_normalize_origin(item))

    allowed.update(_same_origin_candidates(environ))
    return normalized in allowed


sio = socketio.AsyncServer(
    cors_allowed_origins=is_allowed_socket_origin,
    async_mode="asgi",
)

active_connections: Dict[str, dict] = {}


def add_connection(
    socket_id: str,
    user_info: Optional[dict] = None,
    *,
    session_nonce: Optional[str] = None,
    session_expires_at: Optional[float] = None,
) -> None:
    """登记 Socket.IO 连接及其所属认证会话的 nonce 和过期时间。"""
    entry = dict(user_info) if isinstance(user_info, dict) else {}
    if session_nonce:
        entry["session_nonce"] = session_nonce
    if session_expires_at is not None:
        entry["session_expires_at"] = float(session_expires_at)
    active_connections[socket_id] = entry
    print(f"New connection added: {socket_id}, total connections: {len(active_connections)}")


def remove_connection(socket_id: str) -> None:
    if socket_id in active_connections:
        del active_connections[socket_id]
        print(f"Connection removed: {socket_id}, total connections: {len(active_connections)}")


def get_sids_by_session_nonce(session_nonce: str) -> List[str]:
    """查找属于指定会话 nonce 的全部活跃 socket ID。"""
    if not session_nonce:
        return []
    return [
        sid
        for sid, info in active_connections.items()
        if isinstance(info, dict) and info.get("session_nonce") == session_nonce
    ]


def get_expired_sids(now: Optional[float] = None) -> List[str]:
    """查找关联会话已过期的全部活跃 socket ID。"""
    current_time = time.time() if now is None else float(now)
    expired: List[str] = []
    for sid, info in active_connections.items():
        if not isinstance(info, dict):
            continue
        exp = info.get("session_expires_at")
        if isinstance(exp, (int, float)) and exp <= current_time:
            expired.append(sid)
    return expired


async def disconnect_session_sockets(session_nonce: str) -> int:
    """在会话登出时主动断开关联的 Socket.IO 连接。"""
    sids = get_sids_by_session_nonce(session_nonce)
    for sid in sids:
        try:
            await sio.disconnect(sid)
        except Exception as exc:
            print(f"Failed to disconnect session socket {sid}: {exc}")
        finally:
            remove_connection(sid)
    return len(sids)


async def disconnect_expired_sockets(now: Optional[float] = None) -> int:
    """定时清理已过期的 Socket.IO 会话连接。"""
    sids = get_expired_sids(now=now)
    for sid in sids:
        try:
            await sio.disconnect(sid)
        except Exception as exc:
            print(f"Failed to disconnect expired socket {sid}: {exc}")
        finally:
            remove_connection(sid)
    return len(sids)


def get_all_socket_ids():
    return list(active_connections.keys())


def get_connection_count():
    return len(active_connections)
