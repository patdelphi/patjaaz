"""程序说明：提供模型列举、可用工具过滤与聊天会话查询等根 API 路由。"""
import os
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
import httpx
import requests

from models.config_model import ModelInfo
from models.tool_model import ToolInfoJson
from services.config_service import config_service
from services.db_service import db_service
from services.tool_service import TOOL_MAPPING, tool_service
from utils.http_client import HttpClient

router = APIRouter(prefix="/api")


def get_ollama_model_list() -> List[str]:
    """查询本地 Ollama 可用模型列表。"""
    base_url = config_service.get_config().get("ollama", {}).get(
        "url", os.getenv("OLLAMA_HOST", "http://localhost:11434")
    )
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        data = response.json()
        return [model["name"] for model in data.get("models", [])]
    except requests.RequestException as e:
        print(f"Error querying Ollama: {e}")
        return []


async def get_comfyui_model_list(base_url: str) -> List[str]:
    """从 ComfyUI object_info 接口获取 Checkpoint 模型名称列表。"""
    try:
        timeout = httpx.Timeout(10.0)
        async with HttpClient.create(timeout=timeout) as client:
            response = await client.get(f"{base_url}/api/object_info")
            if response.status_code == 200:
                data = response.json()
                models = (
                    data.get("CheckpointLoaderSimple", {})
                    .get("input", {})
                    .get("required", {})
                    .get("ckpt_name", [[]])[0]
                )
                return models if isinstance(models, list) else []  # type: ignore
            print(f"ComfyUI server returned status {response.status_code}")
            return []
    except Exception as e:
        print(f"Error querying ComfyUI: {e}")
        return []


def filter_available_tools(
    tools: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> List[ToolInfoJson]:
    """根据当前提供商配置过滤可用工具；缺失 provider 配置时安全跳过而非抛出 KeyError。"""
    res: List[ToolInfoJson] = []
    if not isinstance(tools, dict) or not isinstance(config, dict):
        return res

    for tool_id, tool_info in tools.items():
        if not isinstance(tool_info, dict):
            continue
        provider = tool_info.get("provider", "")
        if not provider or provider == "system":
            continue

        provider_cfg = config.get(provider)
        provider_api_key = (
            str(provider_cfg.get("api_key", "")).strip()
            if isinstance(provider_cfg, dict)
            else ""
        )
        if provider != "comfyui" and not provider_api_key:
            continue

        item: ToolInfoJson = {
            "id": tool_id,
            "provider": provider,
            "type": tool_info.get("type", ""),
            "display_name": tool_info.get("display_name", ""),
        }
        if tool_info.get("capability"):
            item["capability"] = tool_info.get("capability")
        res.append(item)
    return res


@router.get("/list_models")
async def get_models() -> list[ModelInfo]:
    """列出当前已配置可用的文本大模型列表。"""
    try:
        config = config_service.get_config()
        res: List[ModelInfo] = []

        ollama_url = config.get("ollama", {}).get(
            "url", os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )
        if ollama_url and ollama_url.strip():
            ollama_models = get_ollama_model_list()
            for ollama_model in ollama_models:
                res.append(
                    {
                        "provider": "ollama",
                        "model": ollama_model,
                        "url": ollama_url,
                        "type": "text",
                    }
                )

        for provider in config.keys():
            if provider in ["ollama"]:
                continue

            provider_config = config.get(provider)
            if not isinstance(provider_config, dict):
                continue
            provider_url = provider_config.get("url", "").strip()
            provider_api_key = provider_config.get("api_key", "").strip()

            if not provider_url or not provider_api_key:
                continue

            protocol = provider_config.get("protocol")
            models = provider_config.get("models", {})
            for model_name, model in models.items():
                model_type = model.get("type", "text")
                if model_type == "text":
                    item: ModelInfo = {
                        "provider": provider,
                        "model": model_name,
                        "url": provider_url,
                        "type": model_type,
                    }
                    if protocol:
                        item["protocol"] = protocol
                    if isinstance(model.get("capabilities"), dict):
                        item["capabilities"] = model["capabilities"]
                    if provider_config.get("max_tokens"):
                        item["max_tokens"] = provider_config["max_tokens"]
                    res.append(item)
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/list_tools")
async def list_tools() -> list[ToolInfoJson]:
    """列出当前已配置的图像/视频/工作流生成工具。"""
    try:
        config = config_service.get_config()
        return filter_available_tools(tool_service.tools, config)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/list_chat_sessions")
async def list_chat_sessions():
    """列出全部历史聊天会话。"""
    try:
        return await db_service.list_sessions(None)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/chat_session/{session_id}")
async def get_chat_session(session_id: str):
    """获取指定聊天会话的消息历史。"""
    try:
        return await db_service.get_chat_history(session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
