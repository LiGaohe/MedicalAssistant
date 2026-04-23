"""
病历质量评估API路由
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

from ..database import get_db
from ..services.evaluation.evaluation_pipeline import EvaluationPipeline
from ..services.evaluation.consistency import ConsistencyEvaluator
from ..services.evaluation.completeness import CompletenessEvaluator
from ..services.evaluation.quality import QualityEvaluator
from ..services.evaluation.safety import SafetyEvaluator
from ..services.llm.llm_service import LLMService
from ..models.evaluation_record import EvaluationRecord
from ..models.emr_record import EMRRecord
from ..models.transcript import TranscriptTurn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


class EvaluationRequest(BaseModel):
    record_id: int
    skip_consistency: bool = False
    skip_completeness: bool = False
    skip_quality: bool = False
    skip_safety: bool = False


class BatchEvaluationRequest(BaseModel):
    record_ids: List[int]
    skip_consistency: bool = False
    skip_completeness: bool = False
    skip_quality: bool = False
    skip_safety: bool = False


@router.post("/evaluate")
async def evaluate_emr(
    request: EvaluationRequest,
    db: Session = Depends(get_db)
):
    llm_service = LLMService(db)
    pipeline = EvaluationPipeline(db, llm_service)
    
    try:
        results = pipeline.evaluate(
            record_id=request.record_id,
            skip_consistency=request.skip_consistency,
            skip_completeness=request.skip_completeness,
            skip_quality=request.skip_quality,
            skip_safety=request.skip_safety
        )
        return {"status": "success", "results": results}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch")
async def batch_evaluate(
    request: BatchEvaluationRequest,
    db: Session = Depends(get_db)
):
    llm_service = LLMService(db)
    pipeline = EvaluationPipeline(db, llm_service)
    
    try:
        results = pipeline.batch_evaluate(
            record_ids=request.record_ids,
            skip_consistency=request.skip_consistency,
            skip_completeness=request.skip_completeness,
            skip_quality=request.skip_quality,
            skip_safety=request.skip_safety
        )
        return {"status": "success", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/result/{evaluation_id}")
async def get_evaluation_result(
    evaluation_id: int,
    db: Session = Depends(get_db)
):
    evaluation = db.query(EvaluationRecord).filter(
        EvaluationRecord.evaluation_id == evaluation_id
    ).first()
    
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
        
    return evaluation.to_dict()


@router.get("/list/{record_id}")
async def list_evaluations(
    record_id: int,
    db: Session = Depends(get_db)
):
    evaluations = db.query(EvaluationRecord).filter(
        EvaluationRecord.record_id == record_id
    ).order_by(EvaluationRecord.created_at.desc()).all()
    
    return {
        "record_id": record_id,
        "evaluations": [e.to_dict() for e in evaluations]
    }


@router.get("/statistics")
async def get_statistics(
    db: Session = Depends(get_db)
):
    from sqlalchemy import func
    
    total_evaluations = db.query(func.count(EvaluationRecord.evaluation_id)).scalar()
    
    avg_support_rate = db.query(
        func.avg(EvaluationRecord.support_rate)
    ).scalar() or 0
    
    avg_recall_rate = db.query(
        func.avg(EvaluationRecord.recall_rate)
    ).scalar() or 0
    
    avg_quality_score = db.query(
        func.avg(EvaluationRecord.quality_total_score)
    ).scalar() or 0
    
    high_risk_count = db.query(
        func.count(EvaluationRecord.evaluation_id)
    ).filter(EvaluationRecord.has_high_risk == 1).scalar()
    
    return {
        "total_evaluations": total_evaluations,
        "average_support_rate": round(avg_support_rate, 3) if avg_support_rate else 0,
        "average_recall_rate": round(avg_recall_rate, 3) if avg_recall_rate else 0,
        "average_quality_score": round(avg_quality_score, 2) if avg_quality_score else 0,
        "high_risk_case_count": high_risk_count
    }


class DebugStageRequest(BaseModel):
    stage: str
    user_response: str
    context: Optional[Dict[str, Any]] = None


@router.get("/debug/prompts/{record_id}")
async def get_debug_prompts(
    record_id: int,
    db: Session = Depends(get_db)
):
    emr_record = db.query(EMRRecord).filter(EMRRecord.record_id == record_id).first()
    if not emr_record:
        raise HTTPException(status_code=404, detail="EMR record not found")
    
    llm_service = LLMService(db)
    
    turns = db.query(TranscriptTurn).filter(
        TranscriptTurn.visit_id == emr_record.visit_id
    ).order_by(TranscriptTurn.turn_id).all()
    transcript = "\n".join([f"[{t.speaker}]: {t.text}" for t in turns])
    
    emr_content = emr_record.emr_json
    formatted_emr = QualityEvaluator(llm_service)._format_emr_content(emr_content)
    
    stages = [
        {
            "stage": "consistency",
            "description": "1. 一致性评估 - 事实支持检查",
            "prompt": llm_service.prompt_manager.render(
                "consistency_check",
                transcript=transcript,
                emr_content=formatted_emr
            )
        },
        {
            "stage": "internal_consistency",
            "description": "2. 一致性评估 - 内部一致性检查",
            "prompt": llm_service.prompt_manager.render(
                "internal_consistency_check",
                emr_content=formatted_emr
            )
        },
        {
            "stage": "key_fact_extraction",
            "description": "3. 完整性评估 - 关键事实提取",
            "prompt": llm_service.prompt_manager.render(
                "key_fact_extraction",
                transcript=transcript
            )
        },
        {
            "stage": "completeness",
            "description": "4. 完整性评估 - 覆盖情况检查",
            "prompt": llm_service.prompt_manager.render(
                "completeness_check",
                key_facts="【关键事实将通过上一步结果动态填充】",
                emr_content=formatted_emr
            )
        },
        {
            "stage": "quality",
            "description": "5. 文档质量评估",
            "prompt": llm_service.prompt_manager.render(
                "document_quality_check",
                emr_content=formatted_emr
            )
        },
        {
            "stage": "safety",
            "description": "6. 安全风险评估",
            "prompt": llm_service.prompt_manager.render(
                "safety_risk_check",
                transcript=transcript,
                emr_content=formatted_emr
            )
        }
    ]
    
    return {
        "record_id": record_id,
        "visit_id": emr_record.visit_id,
        "stages": stages
    }


@router.post("/debug/process-stage")
async def process_debug_stage(
    request: DebugStageRequest,
    db: Session = Depends(get_db)
):
    import json
    
    llm_service = LLMService(db)
    
    try:
        json_start = request.user_response.find("{")
        json_end = request.user_response.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            result = json.loads(request.user_response[json_start:json_end])
        else:
            result = json.loads(request.user_response)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    
    context_update = {}
    next_stage = None
    next_prompt = None
    
    if request.stage == "consistency":
        context_update["consistency_result"] = result
        next_stage = "internal_consistency"
        
    elif request.stage == "internal_consistency":
        context_update["internal_consistency_result"] = result
        next_stage = "key_fact_extraction"
        
    elif request.stage == "key_fact_extraction":
        context_update["key_facts"] = result
        next_stage = "completeness"
        
        emr_record_id = request.context.get("record_id") if request.context else None
        if emr_record_id:
            emr_record = db.query(EMRRecord).filter(EMRRecord.record_id == emr_record_id).first()
            if emr_record:
                formatted_emr = QualityEvaluator(llm_service)._format_emr_content(emr_record.emr_json)
                key_facts_str = json.dumps(result.get("key_facts", []), ensure_ascii=False, indent=2)
                next_prompt = llm_service.prompt_manager.render(
                    "completeness_check",
                    key_facts=key_facts_str,
                    emr_content=formatted_emr
                )
        
    elif request.stage == "completeness":
        context_update["completeness_result"] = result
        next_stage = "quality"
        
    elif request.stage == "quality":
        context_update["quality_result"] = result
        next_stage = "safety"
        
    elif request.stage == "safety":
        context_update["safety_result"] = result
        
        if request.context and request.context.get("record_id"):
            emr_record_id = request.context["record_id"]
            emr_record = db.query(EMRRecord).filter(EMRRecord.record_id == emr_record_id).first()
            
            if emr_record:
                consistency_result = request.context.get("consistency_result", {})
                completeness_result = request.context.get("completeness_result", {})
                quality_result = request.context.get("quality_result", {})
                safety_result = result
                
                support_rate = consistency_result.get("summary", {}).get("support_rate", 0)
                recall_rate = completeness_result.get("summary", {}).get("recall_rate", 0)
                quality_score = quality_result.get("total_score", 0)
                
                overall_score = (
                    0.35 * support_rate * consistency_result.get("consistency_score", 1.0) +
                    0.30 * recall_rate +
                    0.20 * (quality_score / 10)
                )
                
                if safety_result.get("has_high_risk"):
                    high_risk_count = safety_result.get("high_risk_count", 0)
                    safety_penalty = min(high_risk_count * 0.15, 0.30)
                    overall_score -= safety_penalty
                
                overall_score = max(0.0, min(1.0, overall_score))
                
                evaluation = EvaluationRecord(
                    record_id=emr_record_id,
                    consistency_result=consistency_result,
                    support_rate=support_rate,
                    hallucination_rate=1 - support_rate,
                    internal_consistency_score=consistency_result.get("consistency_score"),
                    completeness_result=completeness_result,
                    recall_rate=recall_rate,
                    weighted_recall=completeness_result.get("summary", {}).get("weighted_recall"),
                    quality_result=quality_result,
                    quality_total_score=quality_score,
                    safety_result=safety_result,
                    has_high_risk=1 if safety_result.get("has_high_risk") else 0,
                    high_risk_count=safety_result.get("high_risk_count"),
                    overall_score=overall_score,
                    evaluation_metadata={"debug_mode": True}
                )
                
                db.add(evaluation)
                db.commit()
                db.refresh(evaluation)
                
                return {
                    "status": "success",
                    "result": result,
                    "context_update": context_update,
                    "completed": True,
                    "evaluation_id": evaluation.evaluation_id
                }
    
    return {
        "status": "success",
        "result": result,
        "context_update": context_update,
        "next_stage": next_stage,
        "next_prompt": next_prompt
    }
