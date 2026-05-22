from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import json

from ..database import get_db
from ..models import EMRRecord, Visit
from ..services.medical_record_pipeline import MedicalRecordPipeline
from ..services.emr_generation_service import EMRGenerationService
from ..services.llm_pipeline_service import LLMPipelineService
from ..services.llm_pipeline_service_en import LLMPipelineServiceEnglish
from ..services.llm.llm_service import LLMService
from ..utils.logger import logger
from ..config import settings

router = APIRouter(prefix="/api/emr", tags=["EMR"])


class ProcessRequest(BaseModel):
    visit_id: str
    use_llm: bool = True
    save_intermediate: bool = True


class ProcessResponse(BaseModel):
    visit_id: str
    status: str
    evidence_count: int
    normalized_terms_count: int
    extracted_items_count: int
    fact_count: int = 0
    verification_issues: Optional[Dict[str, Any]] = None
    emr_record: Optional[Dict[str, Any]]
    errors: list


@router.post("/process", response_model=ProcessResponse)
async def process_visit(
    request: ProcessRequest,
    db: Session = Depends(get_db)
):
    logger.info(f"收到病历处理请求: visit_id={request.visit_id}")
    logger.info(f"DEBUG模式: {settings.LLM_DEBUG_MODE}")
    
    if settings.LLM_DEBUG_MODE:
        logger.warning("DEBUG模式已开启，但HTTP请求不支持终端交互")
        return ProcessResponse(
            visit_id=request.visit_id,
            status="failed",
            evidence_count=0,
            normalized_terms_count=0,
            extracted_items_count=0,
            emr_record=None,
            errors=["DEBUG模式已开启，HTTP请求不支持终端交互。请关闭DEBUG模式或将后端配置文件中的LLM_DEBUG_MODE设为False"]
        )
    
    try:
        llm_service = LLMService(db)
        
        visit = db.query(Visit).filter(Visit.visit_id == request.visit_id).first()
        language = visit.language if visit and visit.language else "zh"
        
        if request.use_llm:
            if language == "en":
                pipeline = LLMPipelineServiceEnglish(db, llm_service)
            else:
                pipeline = LLMPipelineService(db, llm_service)
            result = pipeline.process_transcript(request.visit_id)
            
            fact_result = result.get("fact_result", {})
            fact_count = fact_result.get("fact_count", 0) if isinstance(fact_result, dict) else 0
            normalized_terms_count = len(result.get("normalized_result", {}).get("terms", []))
            verification_result = result.get("verification_result", {})
            verification_issues = verification_result.get("issues") if isinstance(verification_result, dict) else None
            
            emr_result = result.get("emr_result", {})
            
            latest_emr = db.query(EMRRecord).filter(
                EMRRecord.visit_id == request.visit_id
            ).order_by(EMRRecord.version.desc()).first()
            
            emr_record = {
                "record_id": latest_emr.record_id if latest_emr else None,
                "version": latest_emr.version if latest_emr else None,
                "emr_json": {
                    "subjective": emr_result.get("subjective", {}),
                    "objective": emr_result.get("objective", {}),
                    "assessment": emr_result.get("assessment", {}),
                    "plan": emr_result.get("plan", {})
                }
            }
            
            logger.info(f"病历处理完成: {result['status']}")
            return ProcessResponse(
                visit_id=request.visit_id,
                status=result.get("status", "completed"),
                evidence_count=fact_count,
                normalized_terms_count=normalized_terms_count,
                extracted_items_count=fact_count,
                fact_count=fact_count,
                verification_issues=verification_issues,
                emr_record=emr_record,
                errors=[]
            )
        else:
            pipeline = MedicalRecordPipeline(db, llm_service)
            
            result = pipeline.process_visit(
                request.visit_id,
                use_llm=False,
                save_intermediate=request.save_intermediate
            )
            
            logger.info(f"病历处理完成: {result['status']}")
            return ProcessResponse(**result)
        
    except RuntimeError as e:
        if "User cancelled" in str(e):
            logger.info("用户取消操作")
            return ProcessResponse(
                visit_id=request.visit_id,
                status="cancelled",
                evidence_count=0,
                normalized_terms_count=0,
                extracted_items_count=0,
                emr_record=None,
                errors=["用户取消操作"]
            )
        if "DEBUG模式" in str(e):
            logger.warning(f"DEBUG模式错误: {e}")
            return ProcessResponse(
                visit_id=request.visit_id,
                status="failed",
                evidence_count=0,
                normalized_terms_count=0,
                extracted_items_count=0,
                emr_record=None,
                errors=[str(e)]
            )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"病历处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.responses import StreamingResponse


@router.post("/process-stream")
async def process_visit_stream(
    request: ProcessRequest,
    db: Session = Depends(get_db)
):
    """
    SSE端点：实时推送病历生成进度
    
    返回 Server-Sent Events 流，包含各阶段的处理进度
    """
    logger.info(f"收到SSE病历处理请求: visit_id={request.visit_id}")
    logger.info(f"DEBUG模式: {settings.LLM_DEBUG_MODE}")
    
    if settings.LLM_DEBUG_MODE:
        logger.warning("DEBUG模式已开启，但SSE请求不支持终端交互")
        
        async def debug_error_generator():
            yield f"event: error\ndata: {json.dumps({'error': 'DEBUG模式已开启，SSE请求不支持终端交互'}, ensure_ascii=False)}\n\n"
        
        return StreamingResponse(
            debug_error_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    async def event_generator():
        try:
            llm_service = LLMService(db)
            
            visit = db.query(Visit).filter(Visit.visit_id == request.visit_id).first()
            language = visit.language if visit and visit.language else "zh"
            
            if language == "en":
                pipeline = LLMPipelineServiceEnglish(db, llm_service)
            else:
                pipeline = LLMPipelineService(db, llm_service)
            
            for event in pipeline.process_with_callback(
                request.visit_id,
                save_evidence=request.save_intermediate
            ):
                event_data = {
                    "stage": event.get("stage"),
                    "name": event.get("name"),
                    "status": event.get("status"),
                    "detail": event.get("detail", "")
                }
                
                if event.get("extra"):
                    event_data["extra"] = event["extra"]
                
                yield f"event: stage_update\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                
                if event.get("status") == "completed" and event.get("stage") == 0:
                    result = event.get("extra", {}).get("result", {})
                    
                    latest_emr = db.query(EMRRecord).filter(
                        EMRRecord.visit_id == request.visit_id
                    ).order_by(EMRRecord.version.desc()).first()
                    
                    emr_result = result.get("emr_result", {})
                    emr_record = {
                        "record_id": latest_emr.record_id if latest_emr else None,
                        "version": latest_emr.version if latest_emr else None,
                        "emr_json": {
                            "subjective": emr_result.get("subjective", {}),
                            "objective": emr_result.get("objective", {}),
                            "assessment": emr_result.get("assessment", {}),
                            "plan": emr_result.get("plan", {})
                        }
                    }
                    
                    complete_data = {
                        "status": "completed",
                        "emr_record": emr_record,
                        "role_mapping": result.get("role_mapping"),
                        "fact_count": result.get("fact_result", {}).get("fact_count", 0),
                        "processing_time": result.get("processing_time", 0)
                    }
                    yield f"event: complete\ndata: {json.dumps(complete_data, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            logger.error(f"SSE处理失败: {str(e)}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/visit/{visit_id}")
async def get_visit_info(
    visit_id: str,
    db: Session = Depends(get_db)
):
    logger.info(f"获取就诊信息: visit_id={visit_id}")
    try:
        visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
        
        if not visit:
            logger.warning(f"就诊记录不存在: visit_id={visit_id}")
            raise HTTPException(status_code=404, detail="Visit not found")
        
        logger.info(f"返回就诊信息: patient_name={visit.patient_name}")
        return {
            "visit_id": visit.visit_id,
            "patient_name": visit.patient_name,
            "visit_date": visit.visit_date,
            "language": visit.language,
            "status": visit.status,
            "created_at": visit.created_at.isoformat() if visit.created_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取就诊信息失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{visit_id}")
async def get_processing_status(
    visit_id: str,
    db: Session = Depends(get_db)
):
    try:
        llm_service = LLMService(db)
        pipeline = MedicalRecordPipeline(db, llm_service)
        
        status = pipeline.get_processing_status(visit_id)
        return status
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/record/{visit_id}")
async def get_emr_record(
    visit_id: str,
    version: Optional[int] = None,
    db: Session = Depends(get_db)
):
    logger.info(f"获取病历记录: visit_id={visit_id}, version={version}")
    try:
        llm_service = LLMService(db)
        emr_service = EMRGenerationService(db, llm_service)
        
        emr = emr_service.get_emr_by_visit(visit_id, version)
        
        if not emr:
            logger.warning(f"病历记录不存在: visit_id={visit_id}")
            raise HTTPException(status_code=404, detail="EMR record not found")
        
        logger.info(f"返回病历记录: version={emr.version}")
        return {
            "record_id": emr.record_id,
            "visit_id": emr.visit_id,
            "version": emr.version,
            "record_type": emr.record_type,
            "emr_json": emr.emr_json,
            "evidence_mapping": emr.evidence_mapping,
            "validation_errors": emr.validation_errors,
            "created_at": emr.created_at.isoformat() if emr.created_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取病历记录失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/{visit_id}")
async def get_emr_versions(
    visit_id: str,
    db: Session = Depends(get_db)
):
    logger.info(f"获取病历版本列表: visit_id={visit_id}")
    try:
        llm_service = LLMService(db)
        emr_service = EMRGenerationService(db, llm_service)
        
        versions = emr_service.get_all_versions(visit_id)
        
        logger.info(f"返回 {len(versions)} 个版本")
        return {
            "visit_id": visit_id,
            "versions": [
                {
                    "version": v.version,
                    "record_type": v.record_type,
                    "created_at": v.created_at.isoformat() if v.created_at else None
                }
                for v in versions
            ]
        }
        
    except Exception as e:
        logger.error(f"获取病历版本失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class PipelineProcessRequest(BaseModel):
    visit_id: str


class PipelineProcessResponse(BaseModel):
    status: str
    role_mapping: Optional[Dict[str, str]] = None
    annotated_text: Optional[str] = None
    cleaned_turns: Optional[list] = None
    combined_text: Optional[str] = None
    normalized_result: Optional[Dict[str, Any]] = None
    extraction_result: Optional[Dict[str, Any]] = None
    emr_result: Optional[Dict[str, Any]] = None
    emr_draft: Optional[Dict[str, Any]] = None
    fact_result: Optional[Dict[str, Any]] = None
    verification_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/pipeline/process", response_model=PipelineProcessResponse)
async def process_with_pipeline(
    request: PipelineProcessRequest,
    db: Session = Depends(get_db)
):
    logger.info(f"收到多阶段LLM处理请求: visit_id={request.visit_id}")
    logger.info(f"DEBUG模式: {settings.LLM_DEBUG_MODE}")

    visit = db.query(Visit).filter(Visit.visit_id == request.visit_id).first()
    language = visit.language if visit and visit.language else "zh"
    logger.info(f"检测到语言: {language}")
    
    try:
        llm_service = LLMService(db)
        
        if not llm_service.adapters:
            logger.warning("LLM服务不可用")
            if not settings.LLM_DEBUG_MODE:
                return PipelineProcessResponse(
                    status="failed",
                    error="LLM服务不可用，请先配置LLM或开启DEBUG模式"
                )
        
        if language == "en":
            pipeline = LLMPipelineServiceEnglish(db, llm_service)
        else:
            pipeline = LLMPipelineService(db, llm_service)
        
        result = pipeline.process_transcript(request.visit_id)
        
        logger.info(f"多阶段LLM处理完成: {result['status']}")
        return PipelineProcessResponse(
            status=result.get("status", "completed"),
            role_mapping=result.get("role_mapping"),
            annotated_text=result.get("annotated_text"),
            cleaned_turns=result.get("cleaned_turns"),
            combined_text=result.get("combined_text"),
            normalized_result=result.get("normalized_result"),
            extraction_result=result.get("extraction_result"),
            emr_result=result.get("emr_result"),
            emr_draft=result.get("emr_draft"),
            fact_result=result.get("fact_result"),
            verification_result=result.get("verification_result")
        )
        
    except RuntimeError as e:
        if "User cancelled" in str(e):
            logger.info("用户取消操作")
            return PipelineProcessResponse(
                status="cancelled",
                error="用户取消操作"
            )
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"多阶段LLM处理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/debug-mode")
async def get_debug_mode():
    return {
        "debug_mode": settings.LLM_DEBUG_MODE,
        "segment_turns": settings.LLM_SEGMENT_TURNS
    }


@router.post("/config/debug-mode")
async def set_debug_mode(
    enabled: bool,
    segment_turns: Optional[int] = None
):
    settings.LLM_DEBUG_MODE = enabled
    if segment_turns is not None:
        settings.LLM_SEGMENT_TURNS = segment_turns
    
    logger.info(f"DEBUG模式已{'开启' if enabled else '关闭'}")
    logger.info(f"分段轮次数: {settings.LLM_SEGMENT_TURNS}")
    
    return {
        "debug_mode": settings.LLM_DEBUG_MODE,
        "segment_turns": settings.LLM_SEGMENT_TURNS
    }


class CreateFromTextRequest(BaseModel):
    dialog_text: str
    language: str = "zh"


class CreateFromTextResponse(BaseModel):
    status: str
    visit_id: Optional[str] = None
    turn_count: Optional[int] = None
    error: Optional[str] = None


@router.post("/debug/create-from-text", response_model=CreateFromTextResponse)
async def create_from_text(
    request: CreateFromTextRequest,
    db: Session = Depends(get_db)
):
    logger.info("从文本创建临时对话记录")
    
    import re
    import uuid
    from datetime import datetime
    from ..models import Visit, TranscriptTurn
    
    try:
        visit_id = f"text_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        visit = Visit(
            visit_id=visit_id,
            patient_name="文本输入测试",
            visit_date=datetime.now().strftime("%Y-%m-%d"),
            audio_path=f"text_input://{visit_id}",
            language=request.language,
            status="pending"
        )
        db.add(visit)
        
        lines = request.dialog_text.strip().split('\n')
        turns = []
        turn_index = 0
        
        speaker_pattern = r'^\[([^\]]+)\]:\s*(.+)$'
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            match = re.match(speaker_pattern, line)
            if match:
                speaker = match.group(1)
                text = match.group(2)
            else:
                speaker = "unknown"
                text = line
            
            turn = TranscriptTurn(
                visit_id=visit_id,
                turn_index=turn_index,
                speaker=speaker,
                text=text,
                start_ms=turn_index * 5000,
                end_ms=(turn_index + 1) * 5000,
                confidence=1.0
            )
            turns.append(turn)
            turn_index += 1
        
        if not turns:
            return CreateFromTextResponse(
                status="failed",
                error="没有找到有效的对话内容"
            )
        
        db.add_all(turns)
        db.commit()
        
        logger.info(f"创建临时对话记录成功: visit_id={visit_id}, turns={len(turns)}")
        
        return CreateFromTextResponse(
            status="success",
            visit_id=visit_id,
            turn_count=len(turns)
        )
        
    except Exception as e:
        logger.error(f"创建临时对话记录失败: {str(e)}", exc_info=True)
        db.rollback()
        return CreateFromTextResponse(
            status="failed",
            error=str(e)
        )


class DebugPromptsResponse(BaseModel):
    visit_id: str
    stages: List[Dict[str, Any]]


class DebugProcessStageRequest(BaseModel):
    visit_id: str
    stage: str
    user_response: str
    context: Optional[Dict[str, Any]] = None


class DebugProcessStageResponse(BaseModel):
    status: str
    stage: str
    result: Optional[Dict[str, Any]] = None
    next_stage: Optional[str] = None
    next_prompt: Optional[str] = None
    next_segment_index: Optional[int] = None
    next_description: Optional[str] = None
    context_update: Optional[Dict[str, Any]] = None
    completed: Optional[bool] = None
    error: Optional[str] = None


@router.get("/debug/prompts/{visit_id}", response_model=DebugPromptsResponse)
async def get_debug_prompts(
    visit_id: str,
    db: Session = Depends(get_db)
):
    logger.info(f"获取调试提示词: visit_id={visit_id}")
    
    from ..models import TranscriptTurn
    
    visit = db.query(Visit).filter(Visit.visit_id == visit_id).first()
    language = visit.language if visit and visit.language else "zh"
    
    turns = db.query(TranscriptTurn).filter(
        TranscriptTurn.visit_id == visit_id
    ).order_by(TranscriptTurn.turn_index).all()
    
    if not turns:
        raise HTTPException(status_code=404, detail="没有找到对话轮次")
    
    if language == "en":
        pipeline = LLMPipelineServiceEnglish(db)
    else:
        pipeline = LLMPipelineService(db)
    stages = pipeline.get_all_prompts(turns)
    
    return DebugPromptsResponse(
        visit_id=visit_id,
        stages=stages
    )


@router.post("/debug/process-stage", response_model=DebugProcessStageResponse)
async def debug_process_stage(
    request: DebugProcessStageRequest,
    db: Session = Depends(get_db)
):
    logger.info(f"调试处理阶段: {request.stage}, visit_id={request.visit_id}")
    
    visit = db.query(Visit).filter(Visit.visit_id == request.visit_id).first()
    language = visit.language if visit and visit.language else "zh"
    
    try:
        if language == "en":
            pipeline = LLMPipelineServiceEnglish(db)
        else:
            pipeline = LLMPipelineService(db)
        result = pipeline.process_stage_with_user_input(
            visit_id=request.visit_id,
            stage=request.stage,
            user_response=request.user_response,
            context=request.context or {}
        )
        
        return DebugProcessStageResponse(
            status="success",
            stage=request.stage,
            result=result.get("result"),
            next_stage=result.get("next_stage"),
            next_prompt=result.get("next_prompt"),
            next_segment_index=result.get("next_segment_index"),
            next_description=result.get("next_description"),
            context_update=result.get("context_update"),
            completed=result.get("completed")
        )
        
    except Exception as e:
        logger.error(f"调试处理失败: {str(e)}", exc_info=True)
        return DebugProcessStageResponse(
            status="failed",
            stage=request.stage,
            error=str(e)
        )


class DeleteEMRResponse(BaseModel):
    status: str
    deleted_count: Optional[int] = None
    deleted_version: Optional[int] = None


@router.delete("/record/{visit_id}", response_model=DeleteEMRResponse)
async def delete_emr_record(
    visit_id: str,
    version: Optional[int] = None,
    db: Session = Depends(get_db)
):
    logger.info(f"删除病历记录: visit_id={visit_id}, version={version}")
    try:
        llm_service = LLMService(db)
        emr_service = EMRGenerationService(db, llm_service)

        if version is not None:
            deleted = emr_service.delete_emr_by_version(visit_id, version)
            if deleted:
                logger.info(f"已删除病历版本: visit_id={visit_id}, version={version}")
                return DeleteEMRResponse(
                    status="success",
                    deleted_version=version,
                    deleted_count=deleted
                )
            else:
                raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")
        else:
            count = emr_service.delete_all_emr(visit_id)
            logger.info(f"已删除 {count} 条病历记录: visit_id={visit_id}")
            return DeleteEMRResponse(
                status="success",
                deleted_count=count
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除病历失败: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


class VisitsListResponse(BaseModel):
    visits: List[Dict[str, Any]]


@router.get("/visits", response_model=VisitsListResponse)
async def list_visits_with_emr(
    db: Session = Depends(get_db)
):
    logger.info("获取所有有EMR记录的就诊列表")
    try:
        llm_service = LLMService(db)
        emr_service = EMRGenerationService(db, llm_service)

        visits = emr_service.get_all_visits_with_emr()
        return VisitsListResponse(visits=visits)

    except Exception as e:
        logger.error(f"获取就诊列表失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class UpdateEMRRequest(BaseModel):
    emr_json: Dict[str, Any]
    record_type: str = "user_edited"


class UpdateEMRResponse(BaseModel):
    status: str
    record_id: int
    version: int
    message: Optional[str] = None


@router.put("/record/{visit_id}", response_model=UpdateEMRResponse)
async def update_emr_record(
    visit_id: str,
    request: UpdateEMRRequest,
    db: Session = Depends(get_db)
):
    logger.info(f"更新病历记录: visit_id={visit_id}")
    try:
        llm_service = LLMService(db)
        emr_service = EMRGenerationService(db, llm_service)
        
        latest_version = emr_service._get_latest_version(visit_id)
        new_version = latest_version + 1
        
        emr = EMRRecord(
            visit_id=visit_id,
            version=new_version,
            record_type=request.record_type,
            emr_json=request.emr_json,
            evidence_mapping=None,
            validation_errors=None
        )
        
        db.add(emr)
        db.commit()
        db.refresh(emr)
        
        logger.info(f"病历更新成功: record_id={emr.record_id}, version={new_version}")
        
        return UpdateEMRResponse(
            status="success",
            record_id=emr.record_id,
            version=new_version,
            message="病历更新成功"
        )
        
    except Exception as e:
        logger.error(f"更新病历失败: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evidence/{visit_id}")
async def get_evidence_by_visit(
    visit_id: str,
    db: Session = Depends(get_db)
):
    logger.info(f"获取证据溯源: visit_id={visit_id}")
    try:
        from ..models import EvidenceSpan, TranscriptTurn
        
        evidence_list = db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).all()
        
        result = []
        for ev in evidence_list:
            turn = db.query(TranscriptTurn).filter(
                TranscriptTurn.turn_id == ev.turn_id
            ).first()
            
            turn_text = ev.turn_text
            if not turn_text and turn:
                turn_text = turn.text
            
            result.append({
                "evidence_id": ev.evidence_id,
                "field_type": ev.field_type,
                "field_value": ev.field_value,
                "content": ev.content,
                "turn_id": ev.turn_id,
                "turn_index": turn.turn_index if turn else None,
                "turn_text": turn_text,
                "speaker": turn.speaker if turn else None,
                "confidence": ev.confidence,
                "reasoning": ev.reasoning
            })
        
        logger.info(f"返回 {len(result)} 条证据")
        return {
            "visit_id": visit_id,
            "evidence": result
        }
        
    except Exception as e:
        logger.error(f"获取证据失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
