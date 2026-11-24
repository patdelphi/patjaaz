"""程序说明：使用单一访问码签发短期内存会话。"""
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Optional

SESSION_COOKIE_NAME = "jaaz_session"
SESSION_TTL_SECONDS = 12 * 60 * 60


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


class AccessCodeAuth:
    """校验访问码并管理过期的内存会话。"""

    def __init__(self, access_code: Optional[str] = None):
        self.access_code = access_code if access_code is not None else _load_access_code()
        self.sessions: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.access_code)

    def require_configured(self) -> None:
        if not self.enabled:
            raise RuntimeError("JAAZ_ACCESS_CODE is missing; configure it in .env before starting Jaaz.")

    def verify_access_code(self, provided_code: str) -> bool:
        return bool(
            self.access_code
            and provided_code
            and hmac.compare_digest(self.access_code, provided_code)
        )

    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions[token] = time.time() + SESSION_TTL_SECONDS
        return token

    def is_valid_session(self, token: Optional[str]) -> bool:
        if not token:
            return False
        expires_at = self.sessions.get(token)
        if expires_at is None:
            return False
        if expires_at <= time.time():
            self.sessions.pop(token, None)
            return False
        return True

    def revoke_session(self, token: Optional[str]) -> None:
        if token:
            self.sessions.pop(token, None)


auth_service = AccessCodeAuth()
