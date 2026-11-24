"""程序说明：Jaaz 后端 FastAPI + Socket.IO 入口，负责鉴权中间件、安全响应头与过期 Socket 定期清理。"""
import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import io
import os
import sys

# Ensure stdout and stderr use utf-8 encoding to prevent emoji logs from crashing python server
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
print('Importing websocket_router')
from routers.websocket_router import *  # DO NOT DELETE THIS LINE, OTHERWISE, WEBSOCKET WILL NOT WORK
print('Importing routers')
from routers import auth as auth_router, comfyui_router, config_router, image_router, root_router, workspace, canvas, ssl_test, chat_router, settings, tool_confirmation
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import socketio  # type: ignore
from starlette.responses import JSONResponse, Response
from starlette.types import Scope

print('Importing websocket_state')
from services.websocket_state import disconnect_expired_sockets, sio
print('Importing websocket_service')
from services.websocket_service import broadcast_init_done
print('Importing config_service')
from services.config_service import config_service
print('Importing tool_service')
from services.tool_service import tool_service
from services.auth_service import SESSION_COOKIE_NAME, auth_service
from services.comfy_workflow_pack import sync_workflows_dir_to_db

BASE_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "worker-src 'self' blob:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


def apply_security_headers(response: Response, path: str = "/") -> Response:
    """为 HTTP 响应统一注入防点击劫持、防 MIME 嗅探及基础 CSP 策略头。"""
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    if not (path == "/api" or path.startswith("/api/")):
        response.headers.setdefault("Content-Security-Policy", BASE_CSP_POLICY)
    return response


async def _expired_socket_reaper() -> None:
    """定期扫描并断开会话已过期的 Socket.IO 连接。"""
    while True:
        await asyncio.sleep(60)
        try:
            await disconnect_expired_sockets()
        except Exception as exc:
            print(f"Error reaping expired sockets: {exc}")


async def initialize():
    print('Initializing config_service')
    await config_service.initialize()
    print('Initializing broadcast_init_done')
    await broadcast_init_done()


root_dir = os.path.dirname(__file__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # onstartup
    auth_service.require_configured()
    await initialize()
    try:
        await sync_workflows_dir_to_db()
    except Exception as sync_exc:
        print(f"Warning syncing workflows/ directory on startup: {sync_exc}")
    await tool_service.initialize()
    reaper_task = asyncio.create_task(_expired_socket_reaper())
    try:
        yield
    finally:
        # onshutdown
        reaper_task.cancel()
        with suppress(asyncio.CancelledError):
            await reaper_task


print('Creating FastAPI app')
app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def require_access_code(request: Request, call_next):
    """保护所有 API（/api/auth/* 除外），并附加安全响应头。"""
    path = request.url.path
    is_auth_route = path == "/api/auth" or path.startswith("/api/auth/")
    is_api_route = path == "/api" or path.startswith("/api/")
    if is_api_route and not is_auth_route:
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        if not auth_service.is_valid_session(session_token):
            return apply_security_headers(
                JSONResponse(status_code=401, content={"detail": "Login required"}),
                path,
            )
    response = await call_next(request)
    return apply_security_headers(response, path)


# Include routers
print('Including routers')
app.include_router(auth_router.router)
app.include_router(config_router.router)
app.include_router(comfyui_router.router)
app.include_router(settings.router)
app.include_router(root_router.router)
app.include_router(canvas.router)
app.include_router(workspace.router)
app.include_router(image_router.router)
app.include_router(ssl_test.router)
app.include_router(chat_router.router)
app.include_router(tool_confirmation.router)

# Mount the React build directory
react_build_dir = os.environ.get(
    'UI_DIST_DIR', os.path.join(os.path.dirname(root_dir), "react", "dist")
)


# 无缓存静态文件类
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


static_site = os.path.join(react_build_dir, "assets")
if os.path.exists(static_site):
    app.mount("/assets", NoCacheStaticFiles(directory=static_site), name="assets")


@app.get("/")
async def serve_react_app():
    response = FileResponse(os.path.join(react_build_dir, "index.html"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


print('Creating socketio app')
socket_app = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path='/socket.io')

if __name__ == "__main__":
    # bypass localhost request for proxy, fix ollama proxy issue
    _bypass = {"127.0.0.1", "localhost", "::1"}
    current = set(os.environ.get("no_proxy", "").split(",")) | set(
        os.environ.get("NO_PROXY", "").split(","))
    os.environ["no_proxy"] = os.environ["NO_PROXY"] = ",".join(
        sorted(_bypass | current - {""}))

    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=57988,
                        help='Port to run the server on')
    args = parser.parse_args()
    import uvicorn
    print("🌟Starting server, UI_DIST_DIR:", os.environ.get('UI_DIST_DIR'))

    uvicorn.run(socket_app, host="127.0.0.1", port=args.port)
