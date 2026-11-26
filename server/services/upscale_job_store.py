"""程序说明：长视频分块超分任务断点存储与远端 ComfyUI SeedVR2 单块执行器（辅助 long_video_pipeline_service 保持模块精简）。"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional

from routers.comfyui_execution import ComfyUIUnavailableError, upload_image
from services.comfy_instance_service import comfy_instance_service
from services.config_service import FILES_DIR, USER_DATA_DIR
from services.db_service import db_service
from tools.comfy_dynamic import apply_workflow_inputs_and_seeds
from tools.utils.comfyui import ComfyUIWorkflowRunner
from utils.comfyui_history import require_generation_outputs

UPSCALE_JOBS_DIR = os.path.join(USER_DATA_DIR, "upscale_jobs")
_SAFE_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")

_OFFLINE_ERR_MARKERS = (
    "530",
    "502",
    "504",
    "unavailable",
    "connecterror",
    "connection refused",
    "timed out",
    "timeout",
    "name or service not known",
    "cannot connect",
    "disconnected",
    "offline",
)


def is_transient_offline_error(exc: BaseException) -> bool:
    """判断异常是否由 Colab 隧道断线或实例离线引起，以便保存为可续跑挂起状态。"""
    if isinstance(exc, ComfyUIUnavailableError):
        return True
    text = f"{type(exc).__name__} {exc}".lower()
    return any(m in text for m in _OFFLINE_ERR_MARKERS)


def build_upscale_job_id(
    source_name: str, scale_multiplier: float, slice_seconds: float
) -> str:
    """根据源视频名、放大倍数与切片秒数生成稳定的可续跑任务 ID。"""
    digest = hashlib.sha1(
        f"{source_name}|{scale_multiplier:.2f}|{slice_seconds:.2f}".encode("utf-8")
    ).hexdigest()[:12]
    return f"up_{digest}"


def _job_json_path(job_id: str, jobs_dir: Optional[str] = None) -> str:
    if not _SAFE_JOB_ID_RE.match(str(job_id or "")):
        raise ValueError(f"非法超分任务 ID: {job_id}")
    base = jobs_dir or UPSCALE_JOBS_DIR
    return os.path.join(base, job_id, "job.json")


def save_upscale_job_state(job: Dict[str, Any], jobs_dir: Optional[str] = None) -> None:
    """原子替换写入分块超分任务进度检查点文件 job.json。"""
    path = _job_json_path(str(job["job_id"]), jobs_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def get_upscale_job(job_id: str, jobs_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读取单个分块超分任务的断点状态快照。"""
    path = _job_json_path(job_id, jobs_dir)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_upscale_jobs(jobs_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """按更新时间倒序返回全部分块超分任务列表。"""
    base = jobs_dir or UPSCALE_JOBS_DIR
    if not os.path.isdir(base):
        return []
    out: List[Dict[str, Any]] = []
    for entry in os.listdir(base):
        jpath = os.path.join(base, entry, "job.json")
        if not os.path.isfile(jpath):
            continue
        try:
            with open(jpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    out.append(data)
        except Exception:
            continue
    out.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return out


def build_upscale_workflow_inputs(
    input_defs: List[Dict[str, Any]],
    uploaded_name: str,
    scale_multiplier: float,
) -> Dict[str, Any]:
    """根据超分工作流 schema 动态绑定上传切片视频参数名（如 source_video），防止回退到工作流示例视频。"""
    mapped: Dict[str, Any] = {
        "source_video": uploaded_name,
        "input_video": uploaded_name,
        "scale_multiplier": float(scale_multiplier),
    }
    for param in input_defs:
        if not isinstance(param, dict):
            continue
        pname = str(param.get("name") or "").strip()
        ptype = str(param.get("type") or "").strip().lower()
        if pname and (ptype == "video" or pname in ("source_video", "input_video", "video")):
            mapped[pname] = uploaded_name
    return mapped


async def default_seedvr2_chunk_upscaler(
    slice_path: str,
    dest_chunk_path: str,
    scale_multiplier: float,
    workflow_name: str = "video_upscale_seedvr2_3b",
) -> None:
    """将单个预切片视频上传至 ComfyUI 执行 SeedVR2 超分，并将结果移入任务专属检查点目录。"""
    workflows = await db_service.list_comfy_workflows(enabled_only=False)
    target_wf: Optional[Dict[str, Any]] = None
    for wf in workflows:
        if wf.get("name") == workflow_name:
            target_wf = wf
            break
    if target_wf is None:
        raise RuntimeError(f"数据库中未找到超分工作流 `{workflow_name}`")

    instance = await comfy_instance_service.resolve_instance(
        target_wf.get("instance_id"),
        capability=target_wf.get("capability"),
        workflow_name=workflow_name,
    )
    api_url = str(instance["base_url"]).rstrip("/")
    headers = dict(instance.get("headers") or {})
    instance_id = str(instance.get("id") or "default")
    max_concurrency = int(instance.get("max_concurrency") or 1)

    with open(slice_path, "rb") as sf:
        raw_bytes = sf.read()
    uploaded_name = await upload_image(
        BytesIO(raw_bytes),
        api_url,
        os.path.basename(slice_path),
        subfolder="",
        headers=headers,
    )

    input_defs = (
        target_wf["inputs"]
        if isinstance(target_wf["inputs"], list)
        else json.loads(target_wf["inputs"] or "[]")
    )
    base_wf_dict = await db_service.get_comfy_workflow(target_wf["id"])
    wf_payload = apply_workflow_inputs_and_seeds(
        base_wf_dict,
        input_defs,
        build_upscale_workflow_inputs(input_defs, uploaded_name, scale_multiplier),
        seed_strategy="fixed",
    )

    ctx: Dict[str, Any] = {"workflow_name": workflow_name}
    if target_wf.get("outputs"):
        ctx["explicit_outputs"] = target_wf.get("outputs")

    runner = ComfyUIWorkflowRunner(
        wf_payload,
        api_url,
        headers=headers,
        timeout=None,
        instance_id=instance_id,
    )
    async with comfy_instance_service.acquire_slot(instance_id, max_concurrency):
        await comfy_instance_service.maybe_free_memory_on_family_switch(
            instance_id, api_url, "seedvr2", headers=headers
        )
        outputs = await runner.generate(ctx=ctx)

    require_generation_outputs(outputs)
    first_out = outputs[0] if isinstance(outputs, list) else outputs
    _, _, _, downloaded_fname = first_out
    downloaded_path = os.path.join(FILES_DIR, downloaded_fname)
    os.makedirs(os.path.dirname(dest_chunk_path), exist_ok=True)
    shutil.move(downloaded_path, dest_chunk_path)
