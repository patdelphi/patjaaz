"""程序说明：使用单一访问码签发短期 HMAC-SHA256 签名会话令牌，并实现登录防爆破限流。"""
import base64
from collections import deque
from dataclasses import dataclass
import hashlib
import hmac
import math
import os
from pathlib import Path
import secrets
import time
from typing import Deque, Dict, Optional

SESSION_COOKIE_NAME = "jaaz_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
MIN_ACCESS_CODE_LENGTH = 16
TOKEN_VERSION = "v1"

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_GLOBAL_MAX_FAILURES = 50


@dataclass(frozen=True)
class SessionInfo:
    """已验签会话的元数据。"""

    nonce: str
    expires_at: float


def _load_access_code() -> Optional[str]:
    """从进程环境或项目/用户数据目录的 .env 读取访问码。"""
    value = os.environ.get("JAAZ_ACCESS_CODE", "").strip()
    if value:
        return value

    candidates = [Path(__file__).resolve().parents[2] / ".env"]
    user_data_dir = os.environ.get("USER_DATA_DIR")
    if user_data_dir:
        candidates.append(Path(user_data_dir) / ".env")
    candidates.append(Path.cwd() / ".env")

    for env_path in candidates:
        try:
            lines = env_path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, raw_value = line.partition("=")
            if separator and key.strip() == "JAAZ_ACCESS_CODE":
                value = raw_value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    return value
    return None


def _default_salt_path() -> Path:
    """返回持久化签名盐的文件路径（位于 user_data 目录，不随进程重启丢失）。"""
    server_dir = Path(__file__).resolve().parents[1]
    user_data_dir = Path(os.environ.get("USER_DATA_DIR") or (server_dir / "user_data"))
    return user_data_dir / ".auth_salt"


def _load_or_create_salt(salt_path: Path) -> str:
    """读取持久化签名盐；若不存在则自动生成并落盘。"""
    try:
        existing = salt_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass

    new_salt = secrets.token_urlsafe(32)
    try:
        salt_path.parent.mkdir(parents=True, exist_ok=True)
        # 优先使用独占创建避免竞态覆盖已有盐文件
        try:
            fd = os.open(str(salt_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_salt)
            return new_salt
        except FileExistsError:
            existing = salt_path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
            salt_path.write_text(new_salt, encoding="utf-8")
            return new_salt
    except OSError:
        return new_salt


def extract_client_ip(
    client_host: Optional[str], x_forwarded_for: Optional[str] = None
) -> str:
    """提取限流源 IP；仅当直连来自本机反向代理（127.0.0.1 / ::1）时采信 X-Forwarded-For。"""
    host = (client_host or "").strip()
    if host in ("127.0.0.1", "::1") and isinstance(x_forwarded_for, str) and x_forwarded_for.strip():
        forwarded_first = x_forwarded_for.split(",", 1)[0].strip()
        if forwarded_first:
            return forwarded_first
    return host or "unknown"


class LoginRateLimiter:
    """基于滑动窗口与临时锁定的登录失败限流器。"""

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        window_seconds: int = LOGIN_WINDOW_SECONDS,
        lock_seconds: int = LOGIN_LOCK_SECONDS,
        global_max_failures: int = LOGIN_GLOBAL_MAX_FAILURES,
    ):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self.global_max_failures = global_max_failures
        self._failures_by_ip: Dict[str, Deque[float]] = {}
        self._locked_until: Dict[str, float] = {}
        self._global_failures: Deque[float] = deque()

    def _prune(self, client_key: str, current_time: float) -> None:
        cutoff = current_time - self.window_seconds
        while self._global_failures and self._global_failures[0] <= cutoff:
            self._global_failures.popleft()

        ip_failures = self._failures_by_ip.get(client_key)
        if ip_failures is not None:
            while ip_failures and ip_failures[0] <= cutoff:
                ip_failures.popleft()
            if not ip_failures:
                self._failures_by_ip.pop(client_key, None)

        locked_until = self._locked_until.get(client_key)
        if locked_until is not None and locked_until <= current_time:
            self._locked_until.pop(client_key, None)

    def check_allowed(
        self, client_key: str, now: Optional[float] = None
    ) -> tuple[bool, int]:
        """校验来源当前是否允许尝试登录，返回 (是否允许, 建议重试等待秒数)。"""
        current_time = time.time() if now is None else float(now)
        self._prune(client_key, current_time)

        locked_until = self._locked_until.get(client_key)
        if locked_until is not None and locked_until > current_time:
            return False, max(1, int(math.ceil(locked_until - current_time)))

        if len(self._global_failures) >= self.global_max_failures:
            oldest = self._global_failures[0]
            retry_after = max(1, int(math.ceil(oldest + self.window_seconds - current_time)))
            return False, retry_after

        return True, 0

    def record_failure(self, client_key: str, now: Optional[float] = None) -> None:
        """记录一次错误访问码尝试，达到阈值后锁定来源。"""
        current_time = time.time() if now is None else float(now)
        self._prune(client_key, current_time)

        self._global_failures.append(current_time)
        ip_failures = self._failures_by_ip.setdefault(client_key, deque())
        ip_failures.append(current_time)
        if len(ip_failures) >= self.max_failures:
            self._locked_until[client_key] = current_time + self.lock_seconds

    def record_success(self, client_key: str) -> None:
        """登录成功后清除该来源的失败计数与锁定状态。"""
        self._failures_by_ip.pop(client_key, None)
        self._locked_until.pop(client_key, None)


class AccessCodeAuth:
    """校验访问码并签发可跨重启验证的无状态 HMAC-SHA256 会话令牌。"""

    def __init__(
        self,
        access_code: Optional[str] = None,
        *,
        salt: Optional[str] = None,
        salt_path: Optional[Path] = None,
        session_ttl_seconds: int = SESSION_TTL_SECONDS,
    ):
        self.access_code = access_code if access_code is not None else _load_access_code()
        self.session_ttl_seconds = session_ttl_seconds
        self._salt_path = salt_path or _default_salt_path()
        self._salt = salt if salt is not None else _load_or_create_salt(self._salt_path)
        self._revoked_nonces: Dict[str, float] = {}
        self.rate_limiter = LoginRateLimiter()

    @property
    def enabled(self) -> bool:
        return bool(self.access_code)

    def require_configured(self) -> None:
        """启动前强制校验访问码已配置且长度不低于 16 个字符。"""
        if not self.enabled or not self.access_code:
            raise RuntimeError(
                "JAAZ_ACCESS_CODE is missing; configure at least 16 characters in .env before starting Jaaz."
            )
        if len(self.access_code.strip()) < MIN_ACCESS_CODE_LENGTH:
            raise RuntimeError(
                f"JAAZ_ACCESS_CODE is too short (< {MIN_ACCESS_CODE_LENGTH} chars); configure a stronger access code in .env."
            )

    def verify_access_code(self, provided_code: str) -> bool:
        return bool(
            self.access_code
            and provided_code
            and hmac.compare_digest(self.access_code, provided_code)
        )

    def _signing_key(self) -> bytes:
        """基于持久化盐和当前访问码派生签名密钥，更换访问码后旧令牌自动失效。"""
        code = self.access_code or ""
        return hmac.new(
            self._salt.encode("utf-8"),
            code.encode("utf-8"),
            hashlib.sha256,
        ).digest()

    def _compute_signature(self, payload: str) -> str:
        digest = hmac.new(self._signing_key(), payload.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def _parse_signed_parts(self, token: Optional[str]) -> Optional[tuple[str, int]]:
        if not isinstance(token, str) or not token or not self.access_code:
            return None

        parts = token.split(".")
        if len(parts) != 4:
            return None

        version, expires_raw, nonce, signature = parts
        if version != TOKEN_VERSION or not expires_raw.isdigit() or not nonce or not signature:
            return None

        payload = f"{version}.{expires_raw}.{nonce}"
        expected_sig = self._compute_signature(payload)
        if not hmac.compare_digest(signature, expected_sig):
            return None

        return nonce, int(expires_raw)

    def _prune_revoked(self, current_time: float) -> None:
        expired = [nonce for nonce, exp in self._revoked_nonces.items() if exp <= current_time]
        for nonce in expired:
            self._revoked_nonces.pop(nonce, None)

    def create_session(self, now: Optional[float] = None) -> str:
        """签发带过期时间戳与随机 nonce 的签名会话令牌。"""
        if not self.access_code:
            raise RuntimeError("Cannot issue session token without JAAZ_ACCESS_CODE configured")
        current_time = time.time() if now is None else float(now)
        expires_at = int(current_time + self.session_ttl_seconds)
        nonce = secrets.token_urlsafe(16)
        payload = f"{TOKEN_VERSION}.{expires_at}.{nonce}"
        signature = self._compute_signature(payload)
        return f"{payload}.{signature}"

    def parse_session(
        self, token: Optional[str], now: Optional[float] = None
    ) -> Optional[SessionInfo]:
        """校验证书签名、有效期与撤销状态；合法时返回 SessionInfo。"""
        parsed = self._parse_signed_parts(token)
        if parsed is None:
            return None

        nonce, expires_at = parsed
        current_time = time.time() if now is None else float(now)
        self._prune_revoked(current_time)

        if expires_at <= current_time:
            return None
        if nonce in self._revoked_nonces:
            return None
        return SessionInfo(nonce=nonce, expires_at=float(expires_at))

    def is_valid_session(self, token: Optional[str], now: Optional[float] = None) -> bool:
        """判断会话令牌当前是否有效。"""
        return self.parse_session(token, now=now) is not None

    def revoke_session(self, token: Optional[str]) -> Optional[str]:
        """撤销给定签名会话令牌并返回其 nonce（用于断开活跃 WebSocket 连接）。"""
        parsed = self._parse_signed_parts(token)
        if parsed is None:
            return None
        nonce, expires_at = parsed
        self._revoked_nonces[nonce] = float(expires_at)
        return nonce


auth_service = AccessCodeAuth()
