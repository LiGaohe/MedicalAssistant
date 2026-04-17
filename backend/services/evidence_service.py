import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from ..models import TranscriptTurn, EvidenceSpan
from .llm.llm_service import LLMService
from ..utils.logger import logger


class EvidenceService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        self.triggers = self._load_triggers()
        logger.info(f"EvidenceService initialized with {len(self.triggers)} field types")
        
    def _load_triggers(self) -> Dict[str, Any]:
        try:
            with open("config/field_triggers.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
            
    def select_evidence_by_rules(
        self, 
        visit_id: str, 
        top_k: int = 5
    ) -> List[EvidenceSpan]:
        logger.info(f"开始规则证据选择，visit_id={visit_id}")
        
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        logger.info(f"查询到 {len(turns)} 条对话轮次")
        
        if not turns:
            logger.warning("没有找到对话轮次，返回空证据列表")
            return []
        
        candidates = []
        
        for field_type, field_config in self.triggers.items():
            trigger_words = field_config.get("triggers", [])
            speaker_pref = field_config.get("speaker_preference", None)
            weight = field_config.get("weight", 1.0)
            
            for turn in turns:
                score = self._calculate_turn_score(
                    turn, 
                    trigger_words, 
                    speaker_pref, 
                    weight
                )
                
                if score > 0:
                    candidates.append({
                        "turn": turn,
                        "field_type": field_type,
                        "score": score
                    })
        
        logger.info(f"找到 {len(candidates)} 个候选证据")
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        evidence_spans = []
        for candidate in candidates[:top_k * len(self.triggers)]:
            turn = candidate["turn"]
            evidence = EvidenceSpan(
                visit_id=visit_id,
                turn_id=turn.turn_id,
                field_type=candidate["field_type"],
                content=turn.text,
                confidence=0.7,
                score=candidate["score"]
            )
            evidence_spans.append(evidence)
            
        logger.info(f"返回 {len(evidence_spans)} 条证据")
        return evidence_spans
        
    def select_evidence_by_llm(
        self, 
        visit_id: str
    ) -> List[EvidenceSpan]:
        if not self.llm_service:
            raise RuntimeError("LLM service not available")
            
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()
        
        transcript = self._format_transcript(turns)
        
        try:
            response = self.llm_service.generate_with_template(
                "evidence_selection",
                transcript=transcript
            )
            
            result = json.loads(response.text)
            evidence_list = result.get("evidence", [])
            
            evidence_spans = []
            for item in evidence_list:
                turn_ids = item.get("turn_ids", [])
                for turn_id in turn_ids:
                    turn = self.db.query(TranscriptTurn).filter(
                        TranscriptTurn.turn_id == turn_id
                    ).first()
                    
                    if turn:
                        evidence = EvidenceSpan(
                            visit_id=visit_id,
                            turn_id=turn.turn_id,
                            field_type=item.get("field", "unknown"),
                            content=turn.text,
                            confidence=item.get("confidence", 0.5),
                            score=item.get("confidence", 0.5),
                            reasoning=item.get("reasoning", "")
                        )
                        evidence_spans.append(evidence)
                        
            return evidence_spans
            
        except Exception as e:
            print(f"LLM evidence selection failed: {e}")
            return []
            
    def _calculate_turn_score(
        self, 
        turn: TranscriptTurn, 
        trigger_words: List[str], 
        speaker_pref: Optional[str], 
        weight: float
    ) -> float:
        score = 0.0
        text_lower = turn.text.lower()
        
        for trigger in trigger_words:
            if trigger.lower() in text_lower:
                score += 1.0
                
        if speaker_pref and turn.speaker == speaker_pref:
            score *= 1.2
            
        if len(turn.text) < 5:
            score *= 0.5
            
        return score * weight
        
    def _format_transcript(self, turns: List[TranscriptTurn]) -> str:
        lines = []
        for turn in turns:
            speaker = turn.speaker or "unknown"
            lines.append(f"[{turn.turn_id}] {speaker}: {turn.text}")
        return "\n".join(lines)
        
    def save_evidence(self, evidence_spans: List[EvidenceSpan]):
        for evidence in evidence_spans:
            self.db.add(evidence)
        self.db.commit()
        
    def get_evidence_by_visit(self, visit_id: str) -> List[EvidenceSpan]:
        return self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).order_by(EvidenceSpan.score.desc()).all()
        
    def get_evidence_by_field(
        self, 
        visit_id: str, 
        field_type: str
    ) -> List[EvidenceSpan]:
        return self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id,
            EvidenceSpan.field_type == field_type
        ).order_by(EvidenceSpan.score.desc()).all()
