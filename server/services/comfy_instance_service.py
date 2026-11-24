"""程序说明：提供 ComfyUI 多实例管理、反向代理 URL/WS 规范化、鉴权头注入、健康探测、上传去重缓存与任务远端取消联动。"""
from __future__ import annotations

import base64
from collections import OrderedDict
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
import urllib.parse

import httpx

from services.config_service import config_service, is_masked_secret, mask_secret
from services.db_service import db_service
from utils.http_client import HttpClient


def normalize_comfy_base_url(base_url: str) -> str:
    """规范化 ComfyUI 实例基础地址，保留反向代理路径前缀并去除末尾斜杠。"""
    raw = str(base_url or "").strip()
    if not raw:
        return ""
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"Invalid ComfyUI base_url: {raw}")
    clean_path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, clean_path, "", ""))


def build_comfy_http_url(base_url: str, endpoint_path: str) -> str:
    """在保留子路径前缀的前提下拼装 ComfyUI HTTP 请求地址。"""
    normalized = normalize_comfy_base_url(base_url)
    suffix = "/" + str(endpoint_path or "").lstrip("/")
    return f"{normalized}{suffix}" if suffix != "/" else normalized


def build_comfy_ws_url(base_url: str, client_id: str) -> str:
    """根据 HTTP/HTTPS 地址拼装保留子路径前缀的 WebSocket 地址。"""
    normalized = normalize_comfy_base_url(base_url)
    parts = urllib.parse.urlsplit(normalized)
    ws_scheme = "wss" if parts.scheme == "https" else "ws"
    ws_path = f"{parts.path.rstrip('/')}/ws"
    query = urllib.parse.urlencode({"clientId": client_id})
    return urllib.parse.urlunsplit((ws_scheme, parts.netloc, ws_path, query, ""))


def build_auth_headers(instance: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """根据实例鉴权配置构建 HTTP/WS 请求头（支持 none/bearer/basic/header）。"""
    if not isinstance(instance, dict):
        return {}
    auth_type = str(instance.get("auth_type") or "none").strip().lower()
    secret = str(instance.get("auth_secret") or "")
    header_name = str(instance.get("auth_header_name") or "").strip()

    if auth_type == "none" or not secret:
        return {}
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if auth_type == "basic":
        # 若输入形如 user:pass，自动编码为 Base64；若已是 Base64 则直接发送
        if ":" in secret:
            encoded = base64.b64encode(secret.encode("utf-8")).decode("ascii")
        else:
            encoded = secret
        return {"Authorization": f"Basic {encoded}"}
    if auth_type == "header" and header_name:
        return {header_name: secret}
    return {}


def mask_instance_record(instance: Dict[str, Any]) -> Dict[str, Any]:
    """返回脱敏后的实例记录供前端展示，不返回明文 auth_secret。"""
    masked = dict(instance)
    raw_secret = str(masked.get("auth_secret") or "")
    masked["has_secret"] = bool(raw_secret)
    masked["auth_secret"] = mask_secret(raw_secret)
    return masked


def merge_masked_instance_secret(
    incoming: Dict[str, Any], existing: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """保存实例时，若 auth_secret 仍为掩码占位符则保留原明文密钥。"""
    merged = dict(incoming)
    incoming_secret = merged.get("auth_secret")
    if isinstance(incoming_secret, str) and is_masked_secret(incoming_secret):
        merged["auth_secret"] = (
            str(existing.get("auth_secret") or "")
            if isinstance(existing, dict)
            else ""
        )
    return merged


class ComfyInstanceService:
    """集中管理 ComfyUI 多实例配置、健康检查、参考图上传缓存与远端取消。"""

    def __init__(self, max_upload_cache: int = 512) -> None:
        self._max_upload_cache = max_upload_cache
        self._upload_cache: OrderedDict[tuple[str, str], str] = OrderedDict()
        # session_id -> {(base_url, instance_id, prompt_id): headers_dict}
        self._active_prompts: Dict[
            str, Dict[tuple[str, str, str], Dict[str, str]]
        ] = {}

    @staticmethod
    def compute_bytes_sha256(content: bytes) -> str:
        """计算上传文件字节的 SHA-256 摘要，用于同实例去重。"""
        return hashlib.sha256(content).hexdigest()

    def get_cached_upload(self, instance_key: str, sha256_hex: str) -> Optional[str]:
        """命中已上传到同一实例的文件引用，避免重复网络传输。"""
        key = (instance_key or "default", sha256_hex)
        cached = self._upload_cache.get(key)
        if cached is not None:
            self._upload_cache.move_to_end(key)
        return cached

    def set_cached_upload(
        self, instance_key: str, sha256_hex: str, remote_ref: str
    ) -> None:
        """记录成功上传后的 ComfyUI 远端文件引用。"""
        key = (instance_key or "default", sha256_hex)
        self._upload_cache[key] = remote_ref
        self._upload_cache.move_to_end(key)
        while len(self._upload_cache) > self._max_upload_cache:
            self._upload_cache.popitem(last=False)

    def register_active_prompt(
        self,
        session_id: Optional[str],
        base_url: str,
        prompt_id: Optional[str],
        headers: Optional[Dict[str, str]] = None,
        instance_id: Optional[str] = None,
    ) -> None:
        """登记会话正在 ComfyUI 执行中的 prompt_id，供取消联动使用。"""
        if not session_id or not prompt_id or not base_url:
            return
        bucket = self._active_prompts.setdefault(session_id, {})
        key = (
            normalize_comfy_base_url(base_url),
            str(instance_id or "default"),
            str(prompt_id),
        )
        bucket[key] = dict(headers or {})

    def unregister_active_prompt(
        self,
        session_id: Optional[str],
        prompt_id: Optional[str] = None,
    ) -> None:
        """注销已结束或已取消的 ComfyUI prompt_id。"""
        if not session_id or session_id not in self._active_prompts:
            return
        if not prompt_id:
            self._active_prompts.pop(session_id, None)
            return
        bucket = self._active_prompts[session_id]
        to_delete = [key for key in bucket if key[2] == str(prompt_id)]
        for key in to_delete:
            bucket.pop(key, None)
        if not bucket:
            self._active_prompts.pop(session_id, None)

    async def cancel_session_prompts(self, session_id: str) -> List[Dict[str, Any]]:
        """取消指定会话关联的远端 ComfyUI 队列与运行任务（K5）。"""
        bucket = self._active_prompts.pop(session_id, {})
        if not bucket:
            return []

        results: List[Dict[str, Any]] = []
        async with HttpClient.create(timeout=10.0) as client:
            for (base_url, instance_id, prompt_id), headers in bucket.items():
                deleted = False
                interrupted = False
                errors: List[str] = []

                try:
                    queue_url = build_comfy_http_url(base_url, "/queue")
                    q_resp = await client.post(
                        queue_url,
                        json={"delete": [prompt_id]},
                        headers=headers,
                    )
                    deleted = 200 <= q_resp.status_code < 300
                except Exception as exc:
                    errors.append(f"queue:{exc}")

                # 仅靠 /queue 无法终止已在执行的节点，必须继续尝试 /interrupt
                try:
                    interrupt_url = build_comfy_http_url(base_url, "/interrupt")
                    i_resp = await client.post(
                        interrupt_url,
                        json={"prompt_id": prompt_id},
                        headers=headers,
                    )
                    if i_resp.status_code >= 400:
                        i_resp = await client.post(interrupt_url, headers=headers)
                    interrupted = 200 <= i_resp.status_code < 300
                except Exception as exc:
                    errors.append(f"interrupt:{exc}")

                results.append(
                    {
                        "instance_id": instance_id,
                        "prompt_id": prompt_id,
                        "queue_deleted": deleted,
                        "interrupted": interrupted,
                        "errors": errors,
                    }
                )
        return results

    async def ensure_default_instance(self) -> List[Dict[str, Any]]:
        """若实例表为空且旧 config.toml 配置了 comfyui.url，则自动引导一条默认实例。"""
        instances = await db_service.list_comfy_instances()
        if instances:
            return instances

        configured_url = str(
            config_service.get_config().get("comfyui", {}).get("url", "")
        ).strip()
        if configured_url:
            try:
                normalized = normalize_comfy_base_url(configured_url)
            except ValueError:
                normalized = configured_url.rstrip("/")
            if normalized:
                await db_service.upsert_comfy_instance(
                    {
                        "id": "local_default",
                        "name": "本地默认 ComfyUI",
                        "base_url": normalized,
                        "auth_type": "none",
                        "max_concurrency": 1,
                        "timeout_sec": 600,
                        "enabled": 1,
                        "priority": 100,
                        "capabilities_json": ["t2i", "i2i", "t2v", "i2v", "tts"],
                    }
                )
                return await db_service.list_comfy_instances()
        return []

    async def list_instances(self, masked: bool = True) -> List[Dict[str, Any]]:
        """列出全部 ComfyUI 实例（按需要脱敏）。"""
        instances = await self.ensure_default_instance()
        if masked:
            return [mask_instance_record(item) for item in instances]
        return instances

    async def resolve_instance(
        self, instance_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """按显式 instance_id 或最高优先级挑选可用的 ComfyUI 实例，兼容 config 回退。"""
        instances = await self.ensure_default_instance()
        chosen: Optional[Dict[str, Any]] = None

        if instance_id:
            for item in instances:
                if item.get("id") == instance_id:
                    chosen = item
                    break
            if chosen is not None and not chosen.get("enabled", 1):
                raise RuntimeError(f"ComfyUI instance '{instance_id}' is disabled")

        if chosen is None and not instance_id:
            enabled_list = [item for item in instances if item.get("enabled", 1)]
            if enabled_list:
                chosen = enabled_list[0]

        if chosen is not None:
            result = dict(chosen)
            result["base_url"] = normalize_comfy_base_url(result["base_url"])
            result["headers"] = build_auth_headers(result)
            return result

        # 若未配置任何多实例记录，回退兼容 config_service.app_config["comfyui"]["url"]
        fallback_url = str(
            config_service.app_config.get("comfyui", {}).get("url", "")
        ).strip()
        if not fallback_url:
            raise RuntimeError("No enabled ComfyUI instance is configured")

        return {
            "id": instance_id or "config_default",
            "name": "Default ComfyUI",
            "base_url": normalize_comfy_base_url(fallback_url),
            "auth_type": "none",
            "auth_header_name": "",
            "auth_secret": "",
            "headers": {},
            "max_concurrency": 1,
            "timeout_sec": 600,
            "enabled": 1,
            "priority": 100,
        }

    async def get_allowed_proxy_urls(self) -> List[str]:
        """收集所有已配置 ComfyUI 实例和 config.toml 中的基础 URL 供 SSRF 白名单校验。"""
        urls: List[str] = []
        configured_url = str(
            config_service.get_config().get("comfyui", {}).get("url", "")
        ).strip().rstrip("/")
        if configured_url:
            urls.append(configured_url)
        for item in await db_service.list_comfy_instances():
            base = str(item.get("base_url") or "").strip().rstrip("/")
            if base and base not in urls:
                urls.append(base)
        return urls

    async def find_headers_for_url(self, target_base_url: str) -> Dict[str, str]:
        """根据基础 URL 匹配对应实例的认证请求头。"""
        normalized = str(target_base_url or "").strip().rstrip("/")
        for item in await db_service.list_comfy_instances():
            if str(item.get("base_url") or "").strip().rstrip("/") == normalized:
                return build_auth_headers(item)
        return {}

    async def probe_instance_health(
        self, instance_or_id: str | Dict[str, Any]
    ) -> Dict[str, Any]:
        """探测指定 ComfyUI 实例健康状况与显存信息，并写回数据库快照。"""
        if isinstance(instance_or_id, str):
            instance = await db_service.get_comfy_instance(instance_or_id)
            if instance is None:
                raise ValueError(f"ComfyUI instance not found: {instance_or_id}")
        else:
            instance = dict(instance_or_id)

        instance_id = str(instance.get("id") or "")
        base_url = normalize_comfy_base_url(str(instance.get("base_url") or ""))
        headers = build_auth_headers(instance)
        started = time.perf_counter()

        snapshot: Dict[str, Any] = {
            "online": False,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "latency_ms": 0,
            "devices": [],
            "error": "",
        }
        try:
            async with HttpClient.create(timeout=httpx.Timeout(8.0)) as client:
                resp = await client.get(
                    build_comfy_http_url(base_url, "/system_stats"),
                    headers=headers,
                )
                resp.raise_for_status()
                payload = resp.json()
                snapshot["online"] = True
                snapshot["latency_ms"] = round((time.perf_counter() - started) * 1000)
                if isinstance(payload, dict):
                    snapshot["devices"] = payload.get("devices", [])
                    snapshot["system"] = payload.get("system", {})
        except Exception as exc:
            snapshot["latency_ms"] = round((time.perf_counter() - started) * 1000)
            snapshot["error"] = str(exc)

        if instance_id:
            await db_service.update_comfy_instance_health(
                instance_id, json.dumps(snapshot, ensure_ascii=False)
            )
        return snapshot


comfy_instance_service = ComfyInstanceService()
