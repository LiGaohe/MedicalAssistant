from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import uuid
import shutil
from datetime import datetime

from ..database import get_db
from ..models.visit import Visit
from ..models.task import Task
from ..config import settings
from ..utils.audio_utils import get_audio_duration, validate_audio_file

router = APIRouter(prefix="/api", tags=["upload"])


@router.post("/upload")
async def upload_audio(
    audio_file: UploadFile = File(...),
    patient_name: str = Form(None),
    visit_date: str = Form(None),
    db: Session = Depends(get_db)
):
    visit_id = str(uuid.uuid4())
    
    file_ext = Path(audio_file.filename).suffix.lower()
    if file_ext not in [".wav", ".mp3"]:
        raise HTTPException(status_code=400, detail="仅支持wav和mp3格式")
    
    audio_storage = Path(settings.AUDIO_STORAGE_PATH)
    audio_storage.mkdir(parents=True, exist_ok=True)
    
    audio_path = audio_storage / f"{visit_id}{file_ext}"
    
    with open(audio_path, "wb") as buffer:
        shutil.copyfileobj(audio_file.file, buffer)
    
    is_valid, message = validate_audio_file(audio_path, settings.MAX_AUDIO_SIZE)
    if not is_valid:
        audio_path.unlink()
        raise HTTPException(status_code=400, detail=message)
    
    audio_duration = get_audio_duration(audio_path)
    
    visit = Visit(
        visit_id=visit_id,
        patient_name=patient_name,
        visit_date=visit_date or datetime.now().strftime("%Y-%m-%d"),
        audio_path=str(audio_path),
        audio_duration=audio_duration,
        status="pending"
    )
    db.add(visit)
    
    task_id = str(uuid.uuid4())
    task = Task(
        task_id=task_id,
        visit_id=visit_id,
        task_type="upload",
        status="completed",
        progress=100
    )
    db.add(task)
    
    db.commit()
    
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "visit_id": visit_id,
            "audio_path": str(audio_path),
            "audio_duration": audio_duration,
            "message": "音频上传成功"
        }
    )
