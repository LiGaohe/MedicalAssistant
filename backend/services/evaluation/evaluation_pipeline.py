"""
病历质量评估流水线

协调四层评估流程，计算综合得分
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from .consistency import ConsistencyEvaluator
from .completeness import CompletenessEvaluator
from .quality import QualityEvaluator
from .safety import SafetyEvaluator
from ...models.evaluation_record import EvaluationRecord
from ...models.emr_record import EMRRecord
from ...models.transcript import TranscriptTurn
import logging
import json

logger = logging.getLogger(__name__)


class EvaluationPipeline:
    def __init__(self, db: Session, llm_service):
        self.db = db
        self.llm_service = llm_service
        self.consistency = ConsistencyEvaluator(llm_service)
        self.completeness = CompletenessEvaluator(llm_service)
        self.quality = QualityEvaluator(llm_service)
        self.safety = SafetyEvaluator(llm_service)
        
    def evaluate(
        self, 
        record_id: int,
        skip_consistency: bool = False,
        skip_completeness: bool = False,
        skip_quality: bool = False,
        skip_safety: bool = False
    ) -> Dict[str, Any]:
        logger.info(f"Starting evaluation for record_id={record_id}")
        
        emr_record = self.db.query(EMRRecord).filter(
            EMRRecord.record_id == record_id
        ).first()
        
        if not emr_record:
            raise ValueError(f"EMR record {record_id} not found")
        
        visit = emr_record.visit
        transcript = self._get_transcript(visit.visit_id)
        emr_content = emr_record.emr_json
        
        results = {
            "record_id": record_id,
            "visit_id": visit.visit_id
        }
        
        key_facts = None
        
        if not skip_consistency:
            logger.info("Running consistency evaluation...")
            try:
                results["consistency"] = self.consistency.evaluate(transcript, emr_content)
            except Exception as e:
                logger.error(f"Consistency evaluation failed: {e}")
                results["consistency"] = None
        else:
            results["consistency"] = None
            
        if not skip_completeness:
            logger.info("Running completeness evaluation...")
            try:
                key_facts = self.completeness.extract_key_facts(transcript)
                results["completeness"] = self.completeness.evaluate(key_facts, emr_content)
            except Exception as e:
                logger.error(f"Completeness evaluation failed: {e}")
                results["completeness"] = None
        else:
            results["completeness"] = None
            
        if not skip_quality:
            logger.info("Running quality evaluation...")
            try:
                results["quality"] = self.quality.evaluate(emr_content)
            except Exception as e:
                logger.error(f"Quality evaluation failed: {e}")
                results["quality"] = None
        else:
            results["quality"] = None
            
        if not skip_safety:
            logger.info("Running safety evaluation...")
            try:
                results["safety"] = self.safety.evaluate(transcript, emr_content)
            except Exception as e:
                logger.error(f"Safety evaluation failed: {e}")
                results["safety"] = None
        else:
            results["safety"] = None
        
        overall_score = self._calculate_overall_score(results)
        results["overall_score"] = overall_score
        
        evaluation_record = self._save_evaluation(record_id, results)
        results["evaluation_id"] = evaluation_record.evaluation_id
        
        logger.info(f"Evaluation completed for record_id={record_id}, overall_score={overall_score}")
        return results
        
    def batch_evaluate(
        self, 
        record_ids: List[int],
        skip_consistency: bool = False,
        skip_completeness: bool = False,
        skip_quality: bool = False,
        skip_safety: bool = False
    ) -> List[Dict[str, Any]]:
        results = []
        for record_id in record_ids:
            try:
                result = self.evaluate(
                    record_id,
                    skip_consistency,
                    skip_completeness,
                    skip_quality,
                    skip_safety
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to evaluate record {record_id}: {e}")
                results.append({
                    "record_id": record_id,
                    "error": str(e)
                })
        return results
        
    def _get_transcript(self, visit_id: str) -> str:
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_id).all()
        return "\n".join([f"[{t.speaker}]: {t.text}" for t in turns])
        
    def _calculate_overall_score(self, results: Dict) -> float:
        score = 0.0
        weight_sum = 0.0
        
        if results.get("consistency"):
            support_rate = results["consistency"]["summary"].get("support_rate", 0)
            consistency_score = results["consistency"].get("consistency_score", 1.0)
            score += 0.35 * support_rate * consistency_score
            weight_sum += 0.35
            
        if results.get("completeness"):
            recall_rate = results["completeness"]["summary"].get("recall_rate", 0)
            score += 0.30 * recall_rate
            weight_sum += 0.30
            
        if results.get("quality"):
            quality_score = results["quality"].get("total_score", 0) / 10.0
            score += 0.20 * quality_score
            weight_sum += 0.20
            
        if results.get("safety"):
            if results["safety"].get("has_high_risk"):
                high_risk_count = results["safety"].get("high_risk_count", 0)
                safety_penalty = min(high_risk_count * 0.15, 0.30)
                score -= safety_penalty
                
        if weight_sum > 0:
            score = score / weight_sum * 0.85
            
        return max(0.0, min(1.0, score))
        
    def _save_evaluation(self, record_id: int, results: Dict) -> EvaluationRecord:
        consistency_result = results.get("consistency")
        completeness_result = results.get("completeness")
        quality_result = results.get("quality")
        safety_result = results.get("safety")
        
        evaluation = EvaluationRecord(
            record_id=record_id,
            consistency_result=consistency_result,
            support_rate=consistency_result["summary"].get("support_rate") if consistency_result else None,
            hallucination_rate=1 - consistency_result["summary"].get("support_rate", 1) if consistency_result else None,
            internal_consistency_score=consistency_result.get("consistency_score") if consistency_result else None,
            completeness_result=completeness_result,
            recall_rate=completeness_result["summary"].get("recall_rate") if completeness_result else None,
            weighted_recall=completeness_result["summary"].get("weighted_recall") if completeness_result else None,
            quality_result=quality_result,
            quality_total_score=quality_result.get("total_score") if quality_result else None,
            safety_result=safety_result,
            has_high_risk=1 if safety_result and safety_result.get("has_high_risk") else 0,
            high_risk_count=safety_result.get("high_risk_count") if safety_result else None,
            overall_score=results.get("overall_score"),
            evaluation_metadata={
                "llm_config": self.llm_service.get_available_models()[0] if self.llm_service.get_available_models() else None
            }
        )
        
        self.db.add(evaluation)
        self.db.commit()
        self.db.refresh(evaluation)
        
        return evaluation
