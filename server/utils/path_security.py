"""程序说明：集中处理工作区路径安全、允许浏览目录校验与 ComfyUI 代理目标校验。"""
import ntpath
import os
import re
from pathlib import Path
from typing import Iterable, Optional

# 仅允许安全的文件名字符（字母、数字、点、下划线、短横线），禁止路径分隔符。
SAFE_FILE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# 允许通过 ComfyUI 代理转发的路径前缀白名单。
ALLOWED_COMFYUI_PROXY_PREFIXES = (
    "/system_stats",
    "/object_info",
    "/api/object_info",
    "/queue",
    "/history",
    "/embeddings",
    "/extensions",
    "/prompt",
)


class PathSecurityError(ValueError):
    """路径或目标 URL 越界时抛出的安全异常。"""


def _has_drive_or_unc_prefix(path_text: str) -> bool:
    """判断路径是否包含 Windows 盘符或 UNC 网络共享前缀。"""
    if path_text.startswith(("/", "\\")):
        return True
    drive, _ = ntpath.splitdrive(path_text)
    if drive:
        return True
    return len(path_text) >= 2 and path_text[1] == ":" and path_text[0].isalpha()


def safe_join(base_dir: str | Path, user_path: str) -> str:
    """将用户传入的相对路径安全拼接到 base_dir 内，禁止绝对路径、盘符和目录穿越。"""
    if not isinstance(user_path, str):
        raise PathSecurityError("Path must be a string")
    if "\x00" in user_path:
        raise PathSecurityError("Path contains null byte")

    stripped = user_path.strip()
    if not stripped:
        raise PathSecurityError("Path must not be empty")
    if os.path.isabs(stripped) or _has_drive_or_unc_prefix(stripped):
        raise PathSecurityError("Absolute paths are not allowed")

    base_real = os.path.realpath(os.fspath(base_dir))
    candidate_real = os.path.realpath(os.path.join(base_real, stripped))
    try:
        common = os.path.commonpath([base_real, candidate_real])
    except ValueError as exc:
        raise PathSecurityError("Path crosses filesystem roots") from exc

    if common != base_real:
        raise PathSecurityError("Path escapes base directory")
    return candidate_real


def safe_file_id_path(files_dir: str | Path, file_id: str) -> str:
    """校验单段文件名 file_id 并安全解析到 files_dir 内。"""
    if not isinstance(file_id, str):
        raise PathSecurityError("Invalid file_id")
    if "\x00" in file_id or not file_id or len(file_id) > 255:
        raise PathSecurityError("Invalid file_id length or characters")
    if "/" in file_id or "\\" in file_id or ".." in file_id or file_id == ".":
        raise PathSecurityError("Invalid file_id traversal sequence")
    if not SAFE_FILE_ID_RE.fullmatch(file_id):
        raise PathSecurityError("Invalid file_id format")
    return safe_join(files_dir, file_id)


def _dedupe_real_paths(paths: Iterable[str]) -> list[str]:
    """按 realpath 规范化并去重目录列表。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not isinstance(raw, str):
            continue
        cleaned = raw.strip()
        if not cleaned or "\x00" in cleaned:
            continue
        resolved = os.path.realpath(os.path.expanduser(cleaned))
        norm_key = os.path.normcase(resolved)
        if norm_key not in seen:
            seen.add(norm_key)
            result.append(resolved)
    return result


def get_allowed_browse_roots(extra_roots: Optional[list[str]] = None) -> list[str]:
    """构建本机文件浏览允许的根目录白名单，默认包含 FILES_DIR 与用户主目录。"""
    from services.config_service import FILES_DIR
    from services.settings_service import settings_service

    raw_settings = settings_service.get_raw_settings()
    configured = raw_settings.get("allowed_browse_roots")

    roots: list[str] = [FILES_DIR]
    if isinstance(configured, list) and any(isinstance(item, str) and item.strip() for item in configured):
        roots.extend(item for item in configured if isinstance(item, str))
    else:
        roots.append(os.path.expanduser("~"))

    comfy_output = raw_settings.get("comfyui_output_dir")
    if isinstance(comfy_output, str) and comfy_output.strip():
        roots.append(comfy_output)

    env_roots = os.getenv("JAAZ_ALLOWED_BROWSE_ROOTS", "")
    if env_roots.strip():
        roots.extend(part for part in env_roots.split(os.pathsep) if part.strip())

    if extra_roots:
        roots.extend(extra_roots)

    return _dedupe_real_paths(roots)


def ensure_path_in_allowed_roots(target_path: str, allowed_roots: Iterable[str]) -> str:
    """校验任意浏览路径必须位于允许根目录列表中，防止越界访问。"""
    if not isinstance(target_path, str):
        raise PathSecurityError("Path must be a string")
    if "\x00" in target_path or not target_path.strip():
        raise PathSecurityError("Path must not be empty")

    target_real = os.path.realpath(target_path)
    for root in allowed_roots:
        root_real = os.path.realpath(root)
        try:
            if os.path.commonpath([root_real, target_real]) == root_real:
                return target_real
        except ValueError:
            continue

    raise PathSecurityError("Path is outside allowed directories")


def is_path_in_allowed_roots(target_path: str, allowed_roots: Iterable[str]) -> bool:
    """判断路径是否位于允许根目录列表内。"""
    try:
        ensure_path_in_allowed_roots(target_path, allowed_roots)
        return True
    except PathSecurityError:
        return False


def validate_comfyui_proxy_target(
    configured_url: str,
    requested_url: Optional[str],
    requested_path: str,
) -> str:
    """校验 ComfyUI 代理请求的服务器地址与路径，拒绝任意外部 URL（防 SSRF）。"""
    configured = (configured_url or "").strip().rstrip("/")
    if not configured:
        raise ValueError("ComfyUI URL is not configured")

    if requested_url is not None and str(requested_url).strip():
        normalized_req = str(requested_url).strip().rstrip("/")
        if normalized_req != configured:
            raise PathSecurityError("Only the configured ComfyUI server is allowed")

    if not isinstance(requested_path, str) or not requested_path.strip():
        raise PathSecurityError("ComfyUI proxy path is required")

    path_text = requested_path.strip()
    if (
        not path_text.startswith("/")
        or path_text.startswith("//")
        or "://" in path_text
        or "@" in path_text
        or "\\" in path_text
        or ".." in path_text
        or "#" in path_text
        or "\r" in path_text
        or "\n" in path_text
    ):
        raise PathSecurityError("Invalid ComfyUI proxy path")

    path_only = path_text.split("?", 1)[0]
    if not any(
        path_only == prefix or path_only.startswith(prefix + "/")
        for prefix in ALLOWED_COMFYUI_PROXY_PREFIXES
    ):
        raise PathSecurityError("ComfyUI proxy path is not in allowlist")

    return f"{configured}{path_text}"
