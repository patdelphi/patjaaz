"""程序说明：阶段 4（鉴权补强）同步与异步回归测试，覆盖访问码长度、限流与代理信任边界、HMAC 签名令牌、Socket 断连跟踪与安全响应头。"""
from http.cookies import SimpleCookie
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.responses import Response

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import main as server_main
from routers import auth as auth_router
from services.auth_service import (
    SESSION_COOKIE_NAME,
    AccessCodeAuth,
    LoginRateLimiter,
    extract_client_ip,
)
from services import websocket_state


class Stage4AuthTests(unittest.TestCase):
    def test_access_code_minimum_length_enforced_at_startup(self):
        short_auth = AccessCodeAuth(access_code="short-code", salt="test-salt")
        with self.assertRaisesRegex(RuntimeError, "too short"):
            short_auth.require_configured()

        missing_auth = AccessCodeAuth(access_code="", salt="test-salt")
        with self.assertRaisesRegex(RuntimeError, "missing"):
            missing_auth.require_configured()

        strong_auth = AccessCodeAuth(access_code="strong-access-code-16+", salt="test-salt")
        strong_auth.require_configured()

    def test_hmac_session_persists_across_restarts_and_invalidates_on_code_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            salt_path = Path(tmp) / ".auth_salt"
            auth1 = AccessCodeAuth(access_code="first-strong-access-code", salt_path=salt_path)
            token = auth1.create_session(now=1000.0)
            self.assertTrue(salt_path.exists())

            # 模拟服务重启：新实例读取同一持久化盐和访问码，原令牌依然有效
            auth2 = AccessCodeAuth(access_code="first-strong-access-code", salt_path=salt_path)
            self.assertTrue(auth2.is_valid_session(token, now=1010.0))

            # 篡改签名或过期后均无效
            tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
            self.assertFalse(auth2.is_valid_session(tampered, now=1010.0))
            self.assertFalse(
                auth2.is_valid_session(token, now=1000.0 + auth2.session_ttl_seconds + 1)
            )

            # 更换访问码后，旧签名令牌全部自动失效
            rotated = AccessCodeAuth(access_code="rotated-strong-access-code", salt_path=salt_path)
            self.assertFalse(rotated.is_valid_session(token, now=1010.0))

            # 撤销后失效并返回 nonce
            nonce = auth2.revoke_session(token)
            self.assertIsNotNone(nonce)
            self.assertFalse(auth2.is_valid_session(token, now=1010.0))

    def test_login_rate_limiter_locks_after_5_failures_and_resets_on_success(self):
        limiter = LoginRateLimiter(
            max_failures=5, window_seconds=900, lock_seconds=900, global_max_failures=50
        )
        t = 10000.0
        for i in range(4):
            allowed, _ = limiter.check_allowed("203.0.113.9", now=t + i)
            self.assertTrue(allowed)
            limiter.record_failure("203.0.113.9", now=t + i)

        # 第 5 次失败后触发 15 分钟锁定
        limiter.record_failure("203.0.113.9", now=t + 4)
        allowed, retry_after = limiter.check_allowed("203.0.113.9", now=t + 10)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

        # 不影响其他来源 IP
        other_allowed, _ = limiter.check_allowed("203.0.113.10", now=t + 10)
        self.assertTrue(other_allowed)

        # 超过锁定期后恢复允许，并在登录成功后清空记录
        allowed_after_lock, _ = limiter.check_allowed("203.0.113.9", now=t + 4 + 901)
        self.assertTrue(allowed_after_lock)
        limiter.record_success("203.0.113.9")
        allowed_after_reset, _ = limiter.check_allowed("203.0.113.9", now=t + 906)
        self.assertTrue(allowed_after_reset)

    def test_extract_client_ip_trusts_xff_only_from_local_proxy(self):
        # 直连来自本机反向代理时采用 X-Forwarded-For 第一段
        self.assertEqual(extract_client_ip("127.0.0.1", "198.51.100.7, 10.0.0.1"), "198.51.100.7")
        self.assertEqual(extract_client_ip("::1", "2001:db8::5"), "2001:db8::5")
        # 直连来自公网 IP 时忽略伪造的 X-Forwarded-For
        self.assertEqual(extract_client_ip("198.51.100.20", "127.0.0.1"), "198.51.100.20")

    def test_websocket_state_tracks_session_nonce_and_expiry(self):
        saved = dict(websocket_state.active_connections)
        try:
            websocket_state.active_connections.clear()
            websocket_state.add_connection(
                "sid-1", {}, session_nonce="nonce-a", session_expires_at=1000.0
            )
            websocket_state.add_connection(
                "sid-2", {}, session_nonce="nonce-a", session_expires_at=2000.0
            )
            websocket_state.add_connection(
                "sid-3", {}, session_nonce="nonce-b", session_expires_at=3000.0
            )

            self.assertEqual(
                set(websocket_state.get_sids_by_session_nonce("nonce-a")),
                {"sid-1", "sid-2"},
            )
            self.assertEqual(websocket_state.get_expired_sids(now=1500.0), ["sid-1"])
            self.assertEqual(
                set(websocket_state.get_expired_sids(now=2500.0)),
                {"sid-1", "sid-2"},
            )
        finally:
            websocket_state.active_connections.clear()
            websocket_state.active_connections.update(saved)

    def test_security_headers_applied_to_pages_and_api(self):
        page_resp = server_main.apply_security_headers(Response("ok"), "/")
        self.assertEqual(page_resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(page_resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors 'none'", page_resp.headers.get("Content-Security-Policy", ""))

        api_resp = server_main.apply_security_headers(Response("{}"), "/api/canvas/list")
        self.assertEqual(api_resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(api_resp.headers.get("X-Content-Type-Options"), "nosniff")


class Stage4AsyncAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_session_sockets_and_expired_sockets(self):
        saved = dict(websocket_state.active_connections)
        disconnect_mock = AsyncMock()
        try:
            websocket_state.active_connections.clear()
            websocket_state.add_connection(
                "sid-1", {}, session_nonce="nonce-a", session_expires_at=1000.0
            )
            websocket_state.add_connection(
                "sid-2", {}, session_nonce="nonce-a", session_expires_at=1000.0
            )
            websocket_state.add_connection(
                "sid-3", {}, session_nonce="nonce-b", session_expires_at=100.0
            )

            with patch.object(websocket_state.sio, "disconnect", disconnect_mock):
                disconnected_session = await websocket_state.disconnect_session_sockets("nonce-a")
                self.assertEqual(disconnected_session, 2)
                disconnect_mock.assert_any_await("sid-1")
                disconnect_mock.assert_any_await("sid-2")

                disconnected_expired = await websocket_state.disconnect_expired_sockets(now=200.0)
                self.assertEqual(disconnected_expired, 1)
                disconnect_mock.assert_any_await("sid-3")
                self.assertEqual(websocket_state.get_connection_count(), 0)
        finally:
            websocket_state.active_connections.clear()
            websocket_state.active_connections.update(saved)

    async def test_login_route_rate_limit_429_and_logout_disconnects_socket(self):
        isolated_auth = AccessCodeAuth(
            access_code="test-strong-access-code-1234",
            salt="isolated-test-salt",
        )
        disconnect_mock = AsyncMock(return_value=1)

        def make_request(ip: str, code: str = "", cookies: dict | None = None):
            return SimpleNamespace(
                client=SimpleNamespace(host=ip),
                headers={},
                url=SimpleNamespace(scheme="http"),
                cookies=cookies or {},
                json=AsyncMock(return_value={"code": code}),
            )

        with (
            patch.object(auth_router, "auth_service", isolated_auth),
            patch.object(auth_router, "disconnect_session_sockets", disconnect_mock),
        ):
            # 同一来源连续 5 次错误密码后第 6 次触发 429 锁定
            for _ in range(5):
                with self.assertRaises(HTTPException) as ctx:
                    await auth_router.login(make_request("198.51.100.77", "wrong"), Response())
                self.assertEqual(ctx.exception.status_code, 401)

            with self.assertRaises(HTTPException) as locked_ctx:
                await auth_router.login(
                    make_request("198.51.100.77", "test-strong-access-code-1234"),
                    Response(),
                )
            self.assertEqual(locked_ctx.exception.status_code, 429)
            self.assertIn("Retry-After", locked_ctx.exception.headers)

            # 另一来源正常登录签发 Cookie，并在登出时吊销令牌和断开对应 Socket
            login_resp = Response()
            result = await auth_router.login(
                make_request("198.51.100.88", "test-strong-access-code-1234"),
                login_resp,
            )
            self.assertEqual(result, {"authenticated": True})

            cookie = SimpleCookie()
            cookie.load(login_resp.headers.get("set-cookie", ""))
            token = cookie[SESSION_COOKIE_NAME].value
            session_info = isolated_auth.parse_session(token)
            self.assertIsNotNone(session_info)

            logout_res = await auth_router.logout(
                make_request("198.51.100.88", cookies={SESSION_COOKIE_NAME: token}),
                Response(),
            )
            self.assertEqual(logout_res, {"authenticated": False})
            self.assertFalse(isolated_auth.is_valid_session(token))
            disconnect_mock.assert_awaited_once_with(session_info.nonce)


if __name__ == "__main__":
    unittest.main()
