import json
import re
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from ..models import NormalizedTerm, TranscriptTurn
from .llm.llm_service import LLMService
from .umls.umls_client import UMLSClient
from .umls.term_cache import TermCache
from .umls import UMLSCandidate
from ..config import settings
from ..utils.logger import logger


class TerminologyService:
    def __init__(
        self, 
        db: Session, 
        llm_service: Optional[LLMService] = None,
        umls_client: Optional[UMLSClient] = None,
        language: str = "zh"
    ):
        self.db = db
        self.llm_service = llm_service
        self.language = language
        self.term_dict = self._load_term_dict()
        
        self.umls_client = umls_client
        self.cache_service: Optional[TermCache] = None
        
        if settings.UMLS_ENABLED and settings.UMLS_API_KEY:
            self._init_umls()
        
        logger.info(f"TerminologyService initialized with {len(self.term_dict)} term types, UMLS: {'enabled' if self.umls_client else 'disabled'}, language: {language}")
    
    def _init_umls(self):
        try:
            self.cache_service = TermCache(
                cache_dir=settings.UMLS_CACHE_DIR,
                default_ttl_hours=settings.UMLS_CACHE_TTL_HOURS
            )
            
            if not self.umls_client:
                self.umls_client = UMLSClient(
                    api_key=settings.UMLS_API_KEY,
                    cache_service=self.cache_service,
                    request_timeout=settings.UMLS_REQUEST_TIMEOUT,
                    max_retries=settings.UMLS_MAX_RETRIES,
                    rate_limit_delay=settings.UMLS_RATE_LIMIT_DELAY
                )
            
            if self.umls_client.health_check():
                logger.info("UMLS client initialized and health check passed")
            else:
                logger.warning("UMLS client health check failed, will use fallback")
                self.umls_client = None
                
        except Exception as e:
            logger.error(f"Failed to initialize UMLS client: {e}")
            self.umls_client = None
            self.cache_service = None
        
    def _load_term_dict(self) -> Dict[str, Any]:
        try:
            with open("config/medical_terms.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning("medical_terms.json not found, using empty dict")
            return {}
            
    def normalize_term(
        self, 
        term: str, 
        context: str = "",
        term_type: Optional[str] = None
    ) -> NormalizedTerm:
        logger.debug(f"Normalizing term: '{term}' (type: {term_type})")
        
        normalized, confidence, reasoning, code, code_system, source, candidates, cui = \
            self._normalize_by_dict(term, term_type)
        
        if self.umls_client and confidence < 0.95:
            umls_result = self._normalize_by_umls(term, context)
            if umls_result and umls_result[1] > confidence:
                normalized, confidence, reasoning, code, code_system, source, candidates, cui = umls_result
        
        if confidence < 0.7 and self.llm_service:
            llm_result = self._normalize_by_llm(term, context)
            if llm_result and llm_result[1] > confidence:
                normalized, confidence, reasoning = llm_result
                source = "LLM"
                if not code:
                    code, code_system = self._extract_code_from_llm_reasoning(reasoning)
        
        is_risky = confidence < 0.5
        
        return NormalizedTerm(
            original_term=term,
            normalized_term=normalized,
            term_type=term_type or self._infer_term_type(term),
            confidence=confidence,
            is_risky=is_risky,
            reasoning=reasoning,
            code=code,
            code_system=code_system,
            source=source,
            candidates=candidates,
            cui=cui
        )
    
    def _infer_term_type(self, term: str) -> str:
        for type_name in self.term_dict:
            type_dict = self.term_dict[type_name]
            for standard, aliases in type_dict.items():
                if term == standard or term in aliases:
                    return type_name
        return "unknown"
        
    def _normalize_by_dict(
        self, 
        term: str, 
        term_type: Optional[str] = None
    ) -> Tuple[str, float, str, Optional[str], Optional[str], str, Optional[List], Optional[str]]:
        if term_type and term_type in self.term_dict:
            type_dict = self.term_dict[term_type]
            for standard, aliases in type_dict.items():
                if term == standard or term in aliases:
                    return standard, 1.0, f"字典精确匹配: {term} -> {standard}", None, None, "dict", None, None
                    
        for type_name, type_dict in self.term_dict.items():
            for standard, aliases in type_dict.items():
                if term == standard or term in aliases:
                    return standard, 0.95, f"字典匹配: {term} -> {standard}", None, None, "dict", None, None
                    
        similar_terms = self._find_similar_terms(term)
        if similar_terms:
            best_match, similarity = similar_terms[0]
            if similarity > 0.8:
                return best_match, similarity, f"相似度匹配: {term} -> {best_match}", None, None, "dict_similar", None, None
                
        return term, 0.3, "未找到匹配，保留原词", None, None, "none", None, None
    
    def _normalize_by_umls(
        self,
        term: str,
        context: str
    ) -> Optional[Tuple[str, float, str, Optional[str], Optional[str], str, Optional[List], Optional[str]]]:
        if not self.umls_client:
            return None
        
        try:
            logger.debug(f"Querying UMLS for term: '{term}'")
            
            umls_language = "CHI" if self.language == "zh" else "ENG"
            search_result = self.umls_client.search_term(term, language=umls_language)
            
            if search_result.error:
                logger.warning(f"UMLS search error for '{term}': {search_result.error}")
                fallback_language = "ENG" if self.language == "zh" else "CHI"
                search_result = self.umls_client.search_term(term, language=fallback_language)
            
            if not search_result.candidates:
                logger.debug(f"No UMLS candidates found for term: '{term}'")
                return None
            
            candidates = search_result.candidates[:5]
            
            if self.llm_service and len(candidates) > 1:
                selected = self._llm_select_candidate(term, context, candidates)
                if selected:
                    best_candidate = selected
                else:
                    best_candidate = candidates[0]
            else:
                best_candidate = candidates[0]
            
            code, code_system = self._get_code_from_candidate(best_candidate)
            
            candidates_data = [
                {
                    "term": c.term,
                    "cui": c.cui,
                    "score": c.score,
                    "preferred": c.preferred
                }
                for c in candidates
            ]
            
            confidence = min(0.95, 0.7 + best_candidate.score * 0.25)
            
            reasoning = f"UMLS匹配: {term} -> {best_candidate.term} (CUI: {best_candidate.cui})"
            
            logger.info(f"UMLS match for '{term}': {best_candidate.term} (confidence: {confidence:.2f})")
            
            return (
                best_candidate.term,
                confidence,
                reasoning,
                code,
                code_system,
                "UMLS",
                candidates_data,
                best_candidate.cui
            )
            
        except Exception as e:
            logger.error(f"UMLS normalization failed for '{term}': {e}")
            return None
    
    def _llm_select_candidate(
        self,
        original_term: str,
        context: str,
        candidates: List[UMLSCandidate]
    ) -> Optional[UMLSCandidate]:
        if not self.llm_service or not candidates:
            return None
        
        try:
            candidates_text = "\n".join([
                f"{i+1}. {c.term} (CUI: {c.cui}, Score: {c.score:.2f})"
                for i, c in enumerate(candidates[:5])
            ])
            
            prompt = f"""你是一个医学术语专家。请从以下候选术语中选择最匹配原始术语的一个。

原始术语: {original_term}
上下文: {context}

候选术语:
{candidates_text}

请只输出最佳匹配的编号(1-{len(candidates)})，不要输出其他内容。"""

            response = self.llm_service.generate(prompt, max_tokens=10)
            
            match = re.search(r'(\d+)', response.text)
            if match:
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(candidates):
                    logger.debug(f"LLM selected candidate {idx + 1} for '{original_term}'")
                    return candidates[idx]
                    
        except Exception as e:
            logger.warning(f"LLM candidate selection failed: {e}")
        
        return None
    
    def _get_code_from_candidate(
        self,
        candidate: UMLSCandidate
    ) -> Tuple[Optional[str], Optional[str]]:
        if not self.umls_client or not candidate.cui:
            return None, None
        
        try:
            atoms = self.umls_client.get_atoms(candidate.cui)
            
            code_sources = ["ICD10CM", "ICD10", "SNOMEDCT_US", "RXNORM"]
            
            for atom in atoms:
                source = atom.get("rootSource", "")
                if source in code_sources:
                    code = atom.get("code", "")
                    if code:
                        return code, source
                        
        except Exception as e:
            logger.debug(f"Failed to get code for CUI {candidate.cui}: {e}")
        
        return None, None
    
    def _extract_code_from_llm_reasoning(
        self,
        reasoning: str
    ) -> Tuple[Optional[str], Optional[str]]:
        icd_pattern = r'(?:ICD[-_]?10[-_]?CM?[:\s]*)([A-Z]\d{2}(?:\.\w+)?)'
        match = re.search(icd_pattern, reasoning, re.IGNORECASE)
        if match:
            return match.group(1), "ICD-10-CM"
        
        snomed_pattern = r'(?:SNOMED[-_]?CT?[:\s]*)(\d+)'
        match = re.search(snomed_pattern, reasoning, re.IGNORECASE)
        if match:
            return match.group(1), "SNOMED-CT"
        
        return None, None
        
    def _normalize_by_llm(
        self, 
        term: str, 
        context: str
    ) -> Optional[Tuple[str, float, str]]:
        if not self.llm_service:
            return None
            
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
            logger.error(f"LLM规范化失败: {e}")
            return None
            
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
    
    def clear_cache(self) -> int:
        if self.cache_service:
            return self.cache_service.clear_expired()
        return 0
    
    def get_cache_stats(self) -> Optional[Dict[str, Any]]:
        if self.cache_service:
            return self.cache_service.get_stats()
        return None
