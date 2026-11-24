"""程序说明：提供访问码登录状态、登录限流、签名 Cookie 签发与登出断连接口。"""
from fastapi import APIRouter, HTTPException, Request, Response

from services.auth_service import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    auth_service,
    extract_client_ip,
)
from services.websocket_state import disconnect_session_sockets

router = APIRouter(prefix="/api/auth")


@router.get("/status")
async def auth_status(request: Request):
    """返回是否已配置访问码及当前浏览器的会话状态。"""
    try:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        return {
            "enabled": auth_service.enabled,
            "authenticated": auth_service.is_valid_session(token),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/login")
async def login(request: Request, response: Response):
    """校验来源限流与单一访问码，并用 HttpOnly Cookie 保存签名短期会话。"""
    try:
        client_host = request.client.host if request.client else None
        client_ip = extract_client_ip(
            client_host, request.headers.get("x-forwarded-for")
        )
        allowed, retry_after = auth_service.rate_limiter.check_allowed(client_ip)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts",
                headers={"Retry-After": str(retry_after)},
            )

        payload = await request.json()
        code = payload.get("code") if isinstance(payload, dict) else None
        if not isinstance(code, str) or not auth_service.verify_access_code(code):
            auth_service.rate_limiter.record_failure(client_ip)
            raise HTTPException(status_code=401, detail="Invalid access code")

        auth_service.rate_limiter.record_success(client_ip)
        token = auth_service.create_session()
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        is_secure = request.url.scheme == "https" or forwarded_proto == "https"
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            secure=is_secure,
            samesite="strict",
            path="/",
        )
        return {"authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/logout")
async def logout(request: Request, response: Response):
    """撤销当前浏览器的登录会话并断开关联 Socket.IO 连接。"""
    try:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        nonce = auth_service.revoke_session(token)
        if nonce:
            await disconnect_session_sockets(nonce)
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        return {"authenticated": False}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
