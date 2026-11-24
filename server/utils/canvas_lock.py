"""程序说明：提供按 canvas_id 互斥的全局异步画布锁，避免并发工具与保存接口相互覆盖。"""
import asyncio
from contextlib import asynccontextmanager
from typing import Dict


class CanvasLockManager:
    """按画布 ID 维护异步互斥锁的管理器。"""

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lock_canvas(self, canvas_id: str):
        """获取指定画布的异步锁，确保读-改-写原子执行。"""
        lock = self._locks.get(canvas_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[canvas_id] = lock

        async with lock:
            yield


# 全局唯一画布锁实例：供图片、视频、ComfyUI 工具及画布保存路由共用。
canvas_lock_manager = CanvasLockManager()
