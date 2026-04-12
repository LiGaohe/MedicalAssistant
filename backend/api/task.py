from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.task import Task

router = APIRouter(prefix="/api/task", tags=["task"])


@router.get("/{task_id}")
async def get_task_status(
    task_id: str,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(Task.task_id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return JSONResponse(
        status_code=200,
        content={
            "task_id": task.task_id,
            "visit_id": task.visit_id,
            "task_type": task.task_type,
            "status": task.status,
            "progress": task.progress,
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None
        }
    )
