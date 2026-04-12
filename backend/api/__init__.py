"""API路由"""
from .upload import router as upload_router
from .asr import router as asr_router
from .task import router as task_router

__all__ = ["upload_router", "asr_router", "task_router"]
