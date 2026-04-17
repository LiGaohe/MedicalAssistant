import json
import re
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from ..models import NormalizedTerm, TranscriptTurn
from .llm.llm_service import LLMService
from ..utils.logger import logger


class TerminologyService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.llm_service = llm_service
        self.term_dict = self._load_term_dict()
        logger.info(f"TerminologyService initialized with {len(self.term_dict)} term types")
        
    def _load_term_dict(self) -> Dict[str, Any]:
        try:
            with open("config/medical_terms.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
            
    def normalize_term(
        self, 
        term: str, 
        context: str = "",
        term_type: Optional[str] = None
    ) -> NormalizedTerm:
        normalized, confidence, reasoning = self._normalize_by_dict(term, term_type)
        
        if confidence < 0.7 and self.llm_service:
            llm_normalized, llm_confidence, llm_reasoning = self._normalize_by_llm(
                term, context
            )
            if llm_confidence > confidence:
                normalized = llm_normalized
                confidence = llm_confidence
                reasoning = llm_reasoning
                
        is_risky = confidence < 0.5
        
        return NormalizedTerm(
            original_term=term,
            normalized_term=normalized,
            term_type=term_type or "unknown",
            confidence=confidence,
            is_risky=is_risky,
            reasoning=reasoning
        )
        
    def _normalize_by_dict(
        self, 
        term: str, 
        term_type: Optional[str] = None
    ) -> Tuple[str, float, str]:
        if term_type and term_type in self.term_dict:
            type_dict = self.term_dict[term_type]
            for standard, aliases in type_dict.items():
                if term == standard or term in aliases:
                    return standard, 1.0, f"字典精确匹配: {term} -> {standard}"
                    
        for type_name, type_dict in self.term_dict.items():
            for standard, aliases in type_dict.items():
                if term == standard or term in aliases:
                    return standard, 0.95, f"字典匹配: {term} -> {standard}"
                    
        similar_terms = self._find_similar_terms(term)
        if similar_terms:
            best_match, similarity = similar_terms[0]
            if similarity > 0.8:
                return best_match, similarity, f"相似度匹配: {term} -> {best_match}"
                
        return term, 0.3, "未找到匹配，保留原词"
        
    def _normalize_by_llm(
        self, 
        term: str, 
        context: str
    ) -> Tuple[str, float, str]:
        if not self.llm_service:
            return term, 0.0, "LLM服务不可用"
            
        try:
            response = self.llm_service.generate_with_template(
                "term_normalization",
                term=term,
                context=context
            )
            
            result = json.loads(response.text)
            return (
                result.get("normalized_term", term),
                result.get("confidence", 0.5),
                result.get("reasoning", "")
            )
        except Exception as e:
            return term, 0.0, f"LLM规范化失败: {str(e)}"
            
    def _find_similar_terms(self, term: str) -> List[Tuple[str, float]]:
        similar = []
        
        for type_name, type_dict in self.term_dict.items():
            for standard, aliases in type_dict.items():
                all_terms = [standard] + aliases
                
                for t in all_terms:
                    similarity = self._calculate_similarity(term, t)
                    if similarity > 0.6:
                        similar.append((standard, similarity))
                        
        similar.sort(key=lambda x: x[1], reverse=True)
        return similar[:5]
        
    def _calculate_similarity(self, term1: str, term2: str) -> float:
        if term1 == term2:
            return 1.0
            
        len1, len2 = len(term1), len(term2)
        if len1 == 0 or len2 == 0:
            return 0.0
            
        max_len = max(len1, len2)
        min_len = min(len1, len2)
        
        common_chars = 0
        for i in range(min_len):
            if term1[i] == term2[i]:
                common_chars += 1
                
        return common_chars / max_len
        
    def extract_and_normalize_terms(
        self, 
        text: str, 
        context: str = ""
    ) -> List[NormalizedTerm]:
        logger.debug(f"开始提取和规范化术语，文本长度: {len(text)}")
        terms = []
        
        for type_name, type_dict in self.term_dict.items():
            for standard, aliases in type_dict.items():
                all_terms = [standard] + aliases
                
                for term in all_terms:
                    if term in text:
                        normalized = self.normalize_term(term, context, type_name)
                        terms.append(normalized)
                        logger.debug(f"  发现术语: {term} -> {normalized.normalized_term}")
                        
        logger.info(f"从文本中提取了 {len(terms)} 个术语")
        return terms
        
    def save_normalized_terms(
        self, 
        terms: List[NormalizedTerm], 
        visit_id: str,
        turn_id: Optional[int] = None
    ):
        for term in terms:
            term.visit_id = visit_id
            if turn_id:
                term.turn_id = turn_id
            self.db.add(term)
        self.db.commit()
        
    def get_normalized_terms_by_visit(
        self, 
        visit_id: str
    ) -> List[NormalizedTerm]:
        return self.db.query(NormalizedTerm).filter(
            NormalizedTerm.visit_id == visit_id
        ).all()
