"""程序说明：提供脱敏配置读取与配置更新接口，更新后刷新工具注册表。"""
from fastapi import APIRouter, HTTPException, Request
from services.config_service import config_service
from services.tool_service import tool_service

router = APIRouter(prefix="/api/config")


@router.get("/exists")
async def config_exists():
    return {"exists": config_service.exists_config()}


@router.get("")
async def get_config():
    return config_service.get_masked_config()


@router.post("")
async def update_config(request: Request):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Config payload must be an object")
        res = await config_service.update_config(data)
        # 每次更新配置后，重新初始化工具
        await tool_service.initialize()
        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
