from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pathlib import Path
import uuid

from ..database import get_db
from ..models.visit import Visit
from ..models.task import Task
from ..models.transcript import TranscriptTurn
from ..services.asr_service import ASRService
from ..services.postprocessor import ASRPostprocessor
from ..services.normalizer import TranscriptNormalizer
from ..config import settings

router = APIRouter(prefix="/api/asr", tags=["asr"])

asr_service = ASRService({
    "device": settings.ASR_DEVICE,
    "hotword_path": settings.HOTWORD_PATH
})

postprocessor = ASRPostprocessor()
normalizer = TranscriptNormalizer()


def process_asr_task(visit_id: str, db_url: str):
    from ..database import SessionLocal
    
    db = SessionLocal()
    try:
        visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
        if not visit:
            return
        
        task = db.query(Task).filter(
            Task.visit_id == visit_id,
            Task.task_type == "asr"
        ).first()
        
        if not task:
            return
        
        task.status = "running"
        task.progress = 10
        db.commit()
        
        result = asr_service.transcribe_with_diarization(visit.audio_path)
        task.progress = 50
        db.commit()
        
        turns = normalizer.normalize(result["turns"])
        task.progress = 70
        db.commit()
        
        for turn in turns:
            corrected_text, corrections = postprocessor.correct(turn["text"])
            turn["corrected_text"] = corrected_text
            
            transcript_turn = TranscriptTurn(
                visit_id=visit_id,
                turn_index=turn["turn_index"],
                speaker=turn["speaker"],
                text=turn["text"],
                original_text=turn["original_text"],
                corrected_text=turn["corrected_text"],
                start_ms=turn["start_ms"],
                end_ms=turn["end_ms"],
                confidence=turn["confidence"]
            )
            db.add(transcript_turn)
        
        task.status = "completed"
        task.progress = 100
        visit.status = "completed"
        db.commit()
        
    except Exception as e:
        task.status = "failed"
        task.error_message = str(e)
        visit.status = "failed"
        db.commit()
    finally:
        db.close()


@router.post("/transcribe/{visit_id}")
async def transcribe_audio(
    visit_id: str,
    background_tasks: BackgroundTasks,
    enable_diarization: bool = True,
    enable_correction: bool = True,
    db: Session = Depends(get_db)
):
    visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="就诊记录不存在")
    
    if visit.status == "processing":
        raise HTTPException(status_code=400, detail="该音频正在处理中")
    
    task_id = str(uuid.uuid4())
    task = Task(
        task_id=task_id,
        visit_id=visit_id,
        task_type="asr",
        status="pending",
        progress=0
    )
    db.add(task)
    
    visit.status = "processing"
    db.commit()
    
    background_tasks.add_task(process_asr_task, visit_id, settings.DATABASE_URL)
    
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "visit_id": visit_id,
            "task_id": task_id,
            "status": "processing",
            "message": "ASR转写任务已启动"
        }
    )


@router.get("/transcript/{visit_id}")
async def get_transcript(
    visit_id: str,
    db: Session = Depends(get_db)
):
    from ..models.visit import Visit
    
    visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="就诊记录不存在")
    
    turns = db.query(TranscriptTurn).filter(
        TranscriptTurn.visit_id == visit_id
    ).order_by(TranscriptTurn.turn_index).all()
    
    turns_data = []
    for turn in turns:
        turns_data.append({
            "turn_id": turn.turn_id,
            "turn_index": turn.turn_index,
            "speaker": turn.speaker,
            "text": turn.text,
            "original_text": turn.original_text,
            "corrected_text": turn.corrected_text,
            "start_ms": turn.start_ms,
            "end_ms": turn.end_ms,
            "confidence": turn.confidence
        })
    
    return JSONResponse(
        status_code=200,
        content={
            "visit_id": visit.visit_id,
            "status": visit.status,
            "audio_duration": visit.audio_duration,
            "turns": turns_data
        }
    )
