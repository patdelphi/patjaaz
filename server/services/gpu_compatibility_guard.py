"""程序说明：远端 ComfyUI 显卡规格自适应防呆（拦截 SM<8.0 上的 NVFP4 工作流、长视频显存安全降档、按内存计算超分切片秒数）与 Colab 换址热续跑服务。"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from services.comfy_instance_service import (
    build_auth_headers,
    build_comfy_http_url,
    comfy_instance_service,
    infer_workflow_model_family,
    normalize_comfy_base_url,
)
from services.db_service import db_service
from utils.http_client import HttpClient
from utils.log_sanitizer import get_sanitized_logger

_logger = get_sanitized_logger(__name__)

GiB = 1024 ** 3

# SM < 8.0（Turing / Volta / Pascal / Maxwell）的常见显卡匹配模式，不支持 NVFP4 与原生 BF16 Tensor Core
_PRE_AMPERE_PATTERNS = (
    r"\btesla\s+t4\b",
    r"\bt4\b",
    r"\bquadro\s+t\d+",
    r"\bgtx\s*16\d+",
    r"\bgtx\s*10\d+",
    r"\brtx\s*20\d+",
    r"\bquadro\s+rtx\s*[34568]000\b",
    r"\bp100\b",
    r"\bp40\b",
    r"\btesla\s+p4\b",
    r"\bv100\b",
    r"\btitan\s+v\b",
    r"\btitan\s+xp\b",
    r"\bk80\b",
)


def parse_health_snapshot(raw_health: Any) -> Dict[str, Any]:
    """从实例的 last_health_json 或 /system_stats 响应提取标准化的 GPU 与系统内存指标。"""
    data: Dict[str, Any] = {}
    if isinstance(raw_health, str) and raw_health.strip():
        try:
            parsed = json.loads(raw_health)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    elif isinstance(raw_health, dict):
        if "gpu_name" in raw_health or "vram_total" in raw_health:
            return {
                "online": bool(raw_health.get("online", True)),
                "gpu_name": str(raw_health.get("gpu_name") or ""),
                "gpu_type": str(raw_health.get("gpu_type") or ""),
                "vram_total": int(raw_health.get("vram_total") or 0),
                "vram_free": int(raw_health.get("vram_free") or 0),
                "ram_total": int(raw_health.get("ram_total") or 0),
                "ram_free": int(raw_health.get("ram_free") or 0),
            }
        data = raw_health

    devices = data.get("devices") if isinstance(data.get("devices"), list) else []
    primary_dev = devices[0] if devices and isinstance(devices[0], dict) else {}
    sys_info = data.get("system") if isinstance(data.get("system"), dict) else {}

    return {
        "online": bool(data.get("online", bool(devices))),
        "gpu_name": str(primary_dev.get("name") or ""),
        "gpu_type": str(primary_dev.get("type") or ""),
        "vram_total": int(primary_dev.get("vram_total") or 0),
        "vram_free": int(primary_dev.get("vram_free") or 0),
        "ram_total": int(sys_info.get("ram_total") or 0),
        "ram_free": int(sys_info.get("ram_free") or 0),
    }


def is_pre_ampere_gpu(gpu_name: str) -> bool:
    """判断显卡型号是否属于 SM < 8.0（如 Tesla T4 / RTX 20 / V100 / P100）。"""
    lowered = str(gpu_name or "").strip().lower()
    if not lowered:
        return False
    return any(re.search(pat, lowered) for pat in _PRE_AMPERE_PATTERNS)


def workflow_requires_ampere_or_16gb(
    workflow_name: str,
    workflow_dict: Optional[Dict[str, Any]] = None,
) -> bool:
    """识别使用 NVFP4 量化或 >16GB 权重的重型模型工作流；SeedVR2 3B 超分返回 False。"""
    family = infer_workflow_model_family(workflow_name, workflow_dict)
    if family == "seedvr2":
        return False
    if family in ("minimax_h3_image", "minimax_h3_video", "sensenova"):
        return True

    if isinstance(workflow_dict, dict):
        for node in workflow_dict.values():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            for val in inputs.values():
                if isinstance(val, str) and "nvfp4" in val.lower():
                    return True
    return False


def compute_safe_upscale_slice_sec(
    width: int,
    height: int,
    scale_multiplier: float = 2.0,
    ram_bytes: int = 0,
) -> float:
    """按输出帧像素量与远端系统内存估算不会触发 float32 像素张量 OOM 的单段超分秒数。"""
    scale = max(1.0, float(scale_multiplier or 2.0))
    out_pixels = max(1, int(round(width * scale)) * int(round(height * scale)))

    if ram_bytes <= 0:
        base_sec = 10.0
    else:
        ram_gib = ram_bytes / GiB
        if ram_gib >= 40.0:
            base_sec = 15.0
        elif ram_gib >= 24.0:
            base_sec = 10.0
        elif ram_gib >= 14.0:
            base_sec = 6.0
        else:
            base_sec = 4.0

    # 超过约 4K 级别输出像素（> 4.2M px/帧）时进一步折半，防止 ResizeImageMaskNode 峰值翻倍溢出
    if out_pixels > 4_200_000:
        return max(3.0, round(base_sec * 0.5, 1))
    if out_pixels > 2_300_000:
        return min(base_sec, 10.0)
    return base_sec


def evaluate_workflow_hardware_guard(
    workflow_name: str,
    workflow_dict: Optional[Dict[str, Any]],
    params: Dict[str, Any],
    health_snapshot: Any,
) -> Dict[str, Any]:
    """在提交 ComfyUI 队列前评估远端硬件兼容性，返回拦截原因或安全参数修正。"""
    metrics = parse_health_snapshot(health_snapshot)
    gpu_name = metrics["gpu_name"]
    vram_total = metrics["vram_total"]
    adjusted_params: Dict[str, Any] = {}
    warnings: List[str] = []

    # 未知硬件快照时不误杀，交由后续实际连接处理
    if not gpu_name and vram_total <= 0:
        return {
            "blocked": False,
            "reason": "",
            "adjusted_params": adjusted_params,
            "warnings": warnings,
        }

    vram_gib = vram_total / GiB if vram_total > 0 else 0.0
    pre_ampere = is_pre_ampere_gpu(gpu_name)
    under_16gb = 0 < vram_total < int(15.8 * GiB)

    if workflow_requires_ampere_or_16gb(workflow_name, workflow_dict) and (
        pre_ampere or under_16gb
    ):
        reason = (
            f"远端显卡规格不兼容：当前检测到 `{gpu_name or 'GPU'}`"
            f"（显存 {vram_gib:.1f} GiB），无法运行需要 Ampere SM 8.0+ 架构及 >=16 GiB 显存的 "
            f"NVFP4 重型工作流 `{workflow_name}`（请在 Colab 切换至 L4 24GB 或 A100 40GB/80GB；"
            f"当前显卡仍可执行 SeedVR2 视频超分 `video_upscale_chunked`）。"
        )
        return {
            "blocked": True,
            "reason": reason,
            "adjusted_params": adjusted_params,
            "warnings": warnings,
        }

    # 针对 24GB 级显卡（如 L4 24GB）跑 >=12 秒长视频时，若 megapixels 过高会自动触发非分块 VAEDecode OOM
    raw_dur = params.get("duration_seconds")
    try:
        dur_sec = float(raw_dur) if raw_dur is not None else 0.0
    except (TypeError, ValueError):
        dur_sec = 0.0

    if dur_sec >= 12.0 and 0 < vram_total <= int(26.5 * GiB):
        raw_mp = params.get("megapixels")
        try:
            mp_val = float(raw_mp) if raw_mp is not None else 0.90
        except (TypeError, ValueError):
            mp_val = 0.90
        if mp_val > 0.55:
            adjusted_params["megapixels"] = 0.45
            warnings.append(
                f"检测到 {vram_gib:.1f} GiB 显存执行 {dur_sec:.1f}s 长视频，已自动将 megapixels 约束为 0.45 防止 VAEDecode 显存溢出"
            )

    return {
        "blocked": False,
        "reason": "",
        "adjusted_params": adjusted_params,
        "warnings": warnings,
    }


async def ensure_fresh_instance_health(instance: Dict[str, Any]) -> Dict[str, Any]:
    """优先复用实例已缓存的硬件信息；若首次尚无设备快照则轻量探测 /system_stats 一次。"""
    existing = parse_health_snapshot(instance.get("last_health_json"))
    if existing["gpu_name"] or existing["vram_total"] > 0:
        return existing

    # 仅对真实数据库实例记录做一次轻量探测，避免干扰无 /system_stats 的单元测试模拟桩
    if "last_health_json" not in instance:
        return existing

    base_url = str(instance.get("base_url") or "").strip()
    instance_id = str(instance.get("id") or "").strip()
    if not base_url:
        return existing

    try:
        headers = instance.get("headers") or build_auth_headers(instance)
        started = time.perf_counter()
        async with HttpClient.create(timeout=httpx.Timeout(3.5)) as client:
            resp = await client.get(
                build_comfy_http_url(base_url, "/system_stats"),
                headers=headers,
            )
            if resp.status_code == 200:
                payload = resp.json()
                snapshot = {
                    "online": True,
                    "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "devices": payload.get("devices", []) if isinstance(payload, dict) else [],
                    "system": payload.get("system", {}) if isinstance(payload, dict) else {},
                    "error": "",
                }
                if instance_id:
                    await db_service.update_comfy_instance_health(
                        instance_id, json.dumps(snapshot, ensure_ascii=False)
                    )
                return parse_health_snapshot(snapshot)
    except Exception as exc:
        _logger.debug("轻量探测 /system_stats 跳过: %s", exc)
    return existing


async def hot_resume_colab_instance(
    new_base_url: str,
    instance_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Colab 重启或更换隧道地址后，事务更新实例地址、清空失效上传缓存并立即探测硬件状态。"""
    normalized_url = normalize_comfy_base_url(new_base_url)
    if not normalized_url:
        raise ValueError("new_base_url 不能为空")

    instances = await comfy_instance_service.ensure_default_instance()
    target: Optional[Dict[str, Any]] = None
    if instance_id:
        target = await db_service.get_comfy_instance(instance_id)
        if target is None:
            raise ValueError(f"未找到指定的 ComfyUI 实例: {instance_id}")
    elif instances:
        enabled = [item for item in instances if item.get("enabled", 1)]
        target = enabled[0] if enabled else instances[0]

    if target is None:
        target = {
            "id": instance_id or "local_default",
            "name": "Colab ComfyUI",
            "base_url": normalized_url,
            "auth_type": "none",
            "max_concurrency": 1,
            "timeout_sec": 600,
            "enabled": 1,
            "priority": 100,
            "capabilities_json": ["t2i", "i2i", "t2v", "i2v", "tts"],
        }
    else:
        target = dict(target)
        target["base_url"] = normalized_url
        target["enabled"] = 1

    saved = await db_service.upsert_comfy_instance(target)
    cleared_cache = len(comfy_instance_service._upload_cache)
    comfy_instance_service._upload_cache.clear()
    health = await comfy_instance_service.probe_instance_health(saved)
    parsed = parse_health_snapshot(health)

    return {
        "instance_id": saved["id"],
        "name": saved.get("name") or saved["id"],
        "base_url": normalized_url,
        "cleared_upload_cache": cleared_cache,
        "online": bool(health.get("online")),
        "gpu_name": parsed["gpu_name"],
        "vram_gib": round(parsed["vram_total"] / GiB, 2) if parsed["vram_total"] else 0.0,
        "ram_gib": round(parsed["ram_total"] / GiB, 2) if parsed["ram_total"] else 0.0,
        "health": health,
    }
