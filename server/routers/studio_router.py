"""程序说明：提供跨画布资产检索库（M1）、形状与流程模板库（E10/W1）、表格变量批量解析（W2）及 TTS/ffmpeg 合片路由（V3/V4）。"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel

from routers.studio_p5_routes import router as studio_p5_router
from services.config_service import FILES_DIR, USER_DATA_DIR, config_service
from services.db_service import db_service
from services.file_mapping_service import backfill_historical_mappings, list_file_mappings
from services.video_compose_service import compose_storyboard_clips
from tools.utils.image_canvas_utils import generate_file_id
from tools.video_generation.video_canvas_utils import generate_new_audio_element
from utils.canvas_lock import canvas_lock_manager
from utils.http_client import HttpClient
from utils.log_sanitizer import get_sanitized_logger
from utils.path_security import PathSecurityError

_logger = get_sanitized_logger(__name__)
router = APIRouter(prefix="/api/studio")

TEMPLATES_FILE = os.path.join(USER_DATA_DIR, "studio_templates.json")

BUILTIN_STUDIO_TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "tpl_builtin_3lane",
        "name": "三段式分镜创作泳道（出图 → 改图 → 出视频）",
        "category": "canvas_flow",
        "builtin": True,
        "description": "一键插入三个对齐的分镜 Frame 泳道与说明标题卡，适合标准短片生产。",
        "prompt_template": "",
    },
    {
        "id": "tpl_builtin_review_diamond",
        "name": "导演审片菱形分支节点",
        "category": "canvas_flow",
        "builtin": True,
        "description": "插入审片判断菱形与修改批注卡，用于标注改图或改视频决策分支。",
        "prompt_template": "",
    },
    {
        "id": "tpl_builtin_product_batch",
        "name": "多场景电商静物套图模板",
        "category": "prompt_skill",
        "builtin": True,
        "description": "参数化提示词模板，配合 CSV 表格变量批量生成风格统一的商业静物图。",
        "prompt_template": "商业摄影微距特写：{主体}置于{场景}之中，{光影}，电影级质感，16:9 宽画幅，无文字水印。",
    },
]


def _load_custom_templates() -> List[Dict[str, Any]]:
    if not os.path.isfile(TEMPLATES_FILE):
        return []
    try:
        with open(TEMPLATES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as exc:
        _logger.warning("读取自定义模板文件失败: %s", exc)
        return []


def _save_custom_templates(items: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(TEMPLATES_FILE), exist_ok=True)
    with open(TEMPLATES_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def parse_batch_variables_and_expand(
    raw_table: str,
    prompt_template: str,
    max_rows: int = 50,
) -> List[Dict[str, Any]]:
    """解析 CSV/TSV 或单列多行变量文本，并代入 {变量名} 提示词模板展开任务列表（W2）。"""
    cleaned = str(raw_table or "").lstrip("\ufeff").strip()
    tpl = str(prompt_template or "").strip()
    if not cleaned:
        return []

    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    if not lines:
        return []

    delimiter = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else "")
    placeholder_names = re.findall(r"\{([^{}]+)\}", tpl)

    rows_out: List[Dict[str, Any]] = []
    if delimiter and len(lines) >= 2:
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
        for idx, row in enumerate(reader):
            if idx >= max_rows:
                break
            clean_vars = {
                str(k or "").strip(): str(v or "").strip()
                for k, v in (row or {}).items()
                if k is not None
            }
            prompt = tpl
            for k, v in clean_vars.items():
                prompt = prompt.replace(f"{{{k}}}", v)
            rows_out.append({"index": idx + 1, "variables": clean_vars, "prompt": prompt})
        return rows_out

    # 单列多行模式：若模板含单个占位符则替换该占位符，否则拼在模板末尾
    single_key = placeholder_names[0] if placeholder_names else "item"
    for idx, line_val in enumerate(lines[:max_rows]):
        if tpl and f"{{{single_key}}}" in tpl:
            prompt = tpl.replace(f"{{{single_key}}}", line_val)
        elif tpl:
            prompt = f"{tpl} {line_val}"
        else:
            prompt = line_val
        rows_out.append(
            {"index": idx + 1, "variables": {single_key: line_val}, "prompt": prompt}
        )
    return rows_out


class SaveTemplateRequest(BaseModel):
    name: str
    category: str = "prompt_skill"
    description: str = ""
    prompt_template: str = ""


class BatchExpandRequest(BaseModel):
    raw_table: str
    prompt_template: str
    max_rows: int = 30


class ComposeVideoRequest(BaseModel):
    video_files: List[str] = []
    clip_edits: Optional[List[Dict[str, Any]]] = None
    target_clip_duration: Optional[float] = None
    transition_fade_sec: float = 0.2
    preserve_clip_audio: bool = True
    target_width: int = 0
    target_height: int = 0
    narration_audio: Optional[str] = None
    subtitles: Optional[List[Dict[str, Any]]] = None
    normalize_audio_loudness: bool = False
    burn_subtitles: bool = False
    intro_title: Optional[str] = None
    fade_out_outro_sec: float = 0.0
    canvas_id: str = ""
    session_id: str = ""


class TtsGenerateRequest(BaseModel):
    text: str
    voice: str = "alloy"
    provider: str = ""
    model: str = "tts-1"
    canvas_id: str = ""


@router.get("/assets")
async def search_studio_assets(
    q: str = "",
    kind: str = "all",
    limit: int = 80,
):
    """跨全量画布检索历史图像、视频与音频资产，支持按关键词与媒体类型过滤（M1）。"""
    try:
        canvases = await db_service.list_canvases()
        keyword = q.strip().lower()
        target_kind = kind.strip().lower()
        max_items = max(1, min(200, int(limit or 80)))
        seen_files: set[str] = set()
        results: List[Dict[str, Any]] = []

        for cv in canvases:
            cid = str(cv.get("id") or "")
            cname = str(cv.get("name") or cid)
            detail = await db_service.get_canvas_data(cid)
            data = (detail or {}).get("data") or {}
            elems = data.get("elements") if isinstance(data, dict) else []
            files_map = data.get("files") if isinstance(data, dict) else {}
            if not isinstance(elems, list) or not isinstance(files_map, dict):
                continue

            for el in reversed(elems):
                if not isinstance(el, dict) or el.get("isDeleted"):
                    continue
                etype = str(el.get("type") or "")
                if etype not in ("image", "video", "audio", "embeddable"):
                    continue
                fid = str(el.get("fileId") or el.get("id") or "")
                fentry = files_map.get(fid) or {}
                durl = str(fentry.get("dataURL") or el.get("link") or "")
                if "/api/file/" not in durl:
                    continue
                fname = durl.split("/api/file/", 1)[1].split("?", 1)[0]
                if not fname or fname in seen_files:
                    continue
                if not os.path.isfile(os.path.join(FILES_DIR, fname)):
                    continue

                lower_f = fname.lower()
                if etype == "image" or lower_f.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    media_kind = "image"
                elif etype == "audio" or lower_f.endswith((".mp3", ".wav", ".flac", ".m4a", ".aac")):
                    media_kind = "audio"
                else:
                    media_kind = "video"

                if target_kind not in ("", "all") and media_kind != target_kind:
                    continue

                cd = el.get("customData") if isinstance(el.get("customData"), dict) else {}
                lineage = cd.get("jaazLineage") if isinstance(cd.get("jaazLineage"), dict) else {}
                wf_name = str(lineage.get("workflowName") or cd.get("workflowName") or "")
                prompt = str(lineage.get("prompt") or "")

                if keyword:
                    haystack = f"{fname} {cname} {wf_name} {prompt}".lower()
                    if keyword not in haystack:
                        continue

                seen_files.add(fname)
                results.append(
                    {
                        "file_id": fname,
                        "url": f"/api/file/{fname}",
                        "kind": media_kind,
                        "mime_type": str(fentry.get("mimeType") or f"{media_kind}/mp4"),
                        "width": int(el.get("width") or 640),
                        "height": int(el.get("height") or 640),
                        "canvas_id": cid,
                        "canvas_name": cname,
                        "workflow_name": wf_name,
                        "prompt": prompt[:300],
                    }
                )
                if len(results) >= max_items:
                    return results
        return results
    except HTTPException:
        raise
    except Exception as exc:
        _logger.error("检索跨画布资产失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/templates")
async def list_studio_templates():
    """返回内置分镜图形模板与用户保存的参数化技能模板列表（E10 / W1）。"""
    try:
        return [*BUILTIN_STUDIO_TEMPLATES, *_load_custom_templates()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/templates")
async def save_studio_template(req: SaveTemplateRequest):
    """保存一条用户自定义提示词或分镜复用模板（W1）。"""
    try:
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Template name is required")
        custom = _load_custom_templates()
        item = {
            "id": f"tpl_{uuid.uuid4().hex[:10]}",
            "name": name[:80],
            "category": req.category or "prompt_skill",
            "builtin": False,
            "description": req.description.strip()[:240],
            "prompt_template": req.prompt_template.strip()[:2000],
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        custom.insert(0, item)
        _save_custom_templates(custom[:100])
        return item
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/batch_expand")
async def batch_expand_prompts(req: BatchExpandRequest):
    """解析表格或多行变量并展开批量生成提示词预览（W2）。"""
    try:
        rows = parse_batch_variables_and_expand(
            req.raw_table, req.prompt_template, max_rows=max(1, min(50, req.max_rows))
        )
        return {"count": len(rows), "rows": rows}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compose_video")
async def compose_video_endpoint(req: ComposeVideoRequest):
    """调用后端 ffmpeg 将多段画布分镜视频自动裁剪、保留原生音轨并拼接为单支 MP4 成片（V4）。"""
    try:
        return await compose_storyboard_clips(
            req.video_files,
            clip_edits=req.clip_edits,
            target_clip_duration=req.target_clip_duration,
            transition_fade_sec=req.transition_fade_sec,
            preserve_clip_audio=req.preserve_clip_audio,
            target_width=req.target_width,
            target_height=req.target_height,
            narration_audio=req.narration_audio,
            subtitles=req.subtitles,
            normalize_audio_loudness=req.normalize_audio_loudness,
            burn_subtitles=req.burn_subtitles,
            intro_title=req.intro_title,
            fade_out_outro_sec=req.fade_out_outro_sec,
            canvas_id=req.canvas_id,
            session_id=req.session_id,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        _logger.error("合成视频接口异常: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tts")
async def synthesize_speech_endpoint(req: TtsGenerateRequest):
    """调用已配置的 OpenAI 兼容语音端点将画布脚本合成为音频卡片写入画布（V3）。"""
    try:
        text = req.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="TTS text is required")

        cfg = config_service.get_config()
        chosen_cfg: Optional[Dict[str, Any]] = None
        if req.provider and isinstance(cfg.get(req.provider), dict) and cfg[req.provider].get("api_key"):
            chosen_cfg = cfg[req.provider]
        else:
            for pname in ("openai", "dashscope"):
                pc = cfg.get(pname)
                if isinstance(pc, dict) and pc.get("api_key") and pc.get("url"):
                    chosen_cfg = pc
                    break

        if not chosen_cfg:
            raise HTTPException(
                status_code=503,
                detail="未检测到已配置密钥的语音合成提供商，请在设置中配置支持 /audio/speech 的提供商或启用 ComfyUI TTS 工作流",
            )

        base_url = str(chosen_cfg.get("url") or "").rstrip("/")
        api_key = str(chosen_cfg.get("api_key") or "")
        async with HttpClient.create(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                f"{base_url}/audio/speech",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": req.model or "tts-1", "input": text[:2000], "voice": req.voice or "alloy"},
            )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"上游语音合成接口返回 HTTP {resp.status_code}",
                )
            audio_bytes = resp.content

        aid = f"tts_{generate_file_id()}"
        fname = f"{aid}.mp3"
        out_path = os.path.join(FILES_DIR, fname)
        with open(out_path, "wb") as af:
            af.write(audio_bytes)

        url = f"/api/file/{fname}"
        if req.canvas_id:
            fid = generate_file_id()
            file_data = {
                "mimeType": "audio/mpeg",
                "id": fid,
                "dataURL": url,
                "created": int(time.time() * 1000),
            }
            async with canvas_lock_manager.lock_canvas(req.canvas_id):
                canvas = await db_service.get_canvas_data(req.canvas_id)
                data = (canvas or {}).get("data") or {}
                data.setdefault("elements", [])
                data.setdefault("files", {})
                audio_el = await generate_new_audio_element(
                    req.canvas_id, fid, {"width": 360, "height": 108, "url": url}, canvas_data=data
                )
                data["elements"].append(audio_el)
                data["files"][fid] = file_data
                await db_service.save_canvas_data(req.canvas_id, json.dumps(data))

        return {"file_id": fname, "url": url}
    except HTTPException:
        raise
    except Exception as exc:
        _logger.error("TTS 合成异常: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/file_mappings")
async def get_file_mappings_endpoint(refresh: bool = False):
    """查询 Jaaz 本地文件与远端 ComfyUI / Google Drive (H:) 输出文件的映射表。"""
    try:
        if refresh:
            await asyncio.to_thread(backfill_historical_mappings)
        return {"mappings": await asyncio.to_thread(list_file_mappings)}
    except Exception as exc:
        _logger.error("读取文件映射表失败: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


router.include_router(studio_p5_router)
