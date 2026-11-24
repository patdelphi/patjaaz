"""程序说明：提供访问码登录状态、登录和退出接口。"""
from fastapi import APIRouter, HTTPException, Request, Response

from services.auth_service import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    auth_service,
)

router = APIRouter(prefix="/api/auth")


@router.get("/status")
async def auth_status(request: Request):
    """返回是否已配置访问码及当前浏览器的会话状态。"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return {
        "enabled": auth_service.enabled,
        "authenticated": auth_service.is_valid_session(token),
    }


@router.post("/login")
async def login(request: Request, response: Response):
    """验证单一访问码，并用 HttpOnly Cookie 保存短期会话。"""
    payload = await request.json()
    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(code, str) or not auth_service.verify_access_code(code):
        raise HTTPException(status_code=401, detail="Invalid access code")

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


@router.post("/logout")
async def logout(request: Request, response: Response):
    """撤销当前浏览器的登录会话。"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    auth_service.revoke_session(token)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"authenticated": False}
