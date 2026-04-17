from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from ..database import get_db
from ..models import EMRRecord
from ..services.medical_record_pipeline import MedicalRecordPipeline
from ..services.emr_generation_service import EMRGenerationService
from ..services.llm_pipeline_service import LLMPipelineService
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
    emr_record: Optional[Dict[str, Any]]
    errors: list


@router.post("/process", response_model=ProcessResponse)
async def process_visit(
    request: ProcessRequest,
    db: Session = Depends(get_db)
):
    logger.info(f"收到病历处理请求: visit_id={request.visit_id}")
    try:
        llm_service = LLMService(db)
        pipeline = MedicalRecordPipeline(db, llm_service)
        
        result = pipeline.process_visit(
            request.visit_id,
            use_llm=request.use_llm,
            save_intermediate=request.save_intermediate
        )
        
        logger.info(f"病历处理完成: {result['status']}")
        return ProcessResponse(**result)
        
    except Exception as e:
        logger.error(f"病历处理失败: {str(e)}", exc_info=True)
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
    normalized_result: Optional[Dict[str, Any]] = None
    extraction_result: Optional[Dict[str, Any]] = None
    emr_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/pipeline/process", response_model=PipelineProcessResponse)
async def process_with_pipeline(
    request: PipelineProcessRequest,
    db: Session = Depends(get_db)
):
    logger.info(f"收到多阶段LLM处理请求: visit_id={request.visit_id}")
    logger.info(f"DEBUG模式: {settings.LLM_DEBUG_MODE}")
    
    try:
        llm_service = LLMService(db)
        
        if not llm_service.adapters:
            logger.warning("LLM服务不可用")
            if not settings.LLM_DEBUG_MODE:
                return PipelineProcessResponse(
                    status="failed",
                    error="LLM服务不可用，请先配置LLM或开启DEBUG模式"
                )
        
        pipeline = LLMPipelineService(db, llm_service)
        
        result = pipeline.process_transcript(request.visit_id)
        
        logger.info(f"多阶段LLM处理完成: {result['status']}")
        return PipelineProcessResponse(
            status=result.get("status", "completed"),
            role_mapping=result.get("role_mapping"),
            annotated_text=result.get("annotated_text"),
            normalized_result=result.get("normalized_result"),
            extraction_result=result.get("extraction_result"),
            emr_result=result.get("emr_result")
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
