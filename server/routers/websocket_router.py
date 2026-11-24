"""程序说明：处理 Socket.IO 连接鉴权并在断开时移除会话连接绑定。"""
from http.cookies import SimpleCookie
from services.auth_service import SESSION_COOKIE_NAME, auth_service
from services.websocket_state import sio, add_connection, remove_connection


@sio.event
async def connect(sid, environ, auth):
    cookies = SimpleCookie()
    cookies.load(environ.get("HTTP_COOKIE", ""))
    session_cookie = cookies.get(SESSION_COOKIE_NAME)
    session_info = auth_service.parse_session(session_cookie.value) if session_cookie else None
    if session_info is None:
        return False

    print(f"Client {sid} connected")

    user_info = auth or {}
    add_connection(
        sid,
        user_info,
        session_nonce=session_info.nonce,
        session_expires_at=session_info.expires_at,
    )

    await sio.emit('connected', {'status': 'connected'}, room=sid)


@sio.event
async def disconnect(sid):
    print(f"Client {sid} disconnected")
    remove_connection(sid)


@sio.event
async def ping(sid, data):
    await sio.emit('pong', data, room=sid)
