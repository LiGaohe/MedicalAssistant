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
        self.term_type_hints = self._load_term_type_hints()
        
        self.umls_client = umls_client
        self.cache_service: Optional[TermCache] = None
        
        if settings.UMLS_ENABLED and settings.UMLS_API_KEY:
            self._init_umls()
        
        logger.info(f"TerminologyService initialized, UMLS: {'enabled' if self.umls_client else 'disabled'}, language: {language}")
    
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
    
    def _load_term_type_hints(self) -> Dict[str, List[str]]:
        try:
            with open("config/medical_terms.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                hints = {}
                for type_name, type_dict in data.items():
                    hints[type_name] = list(type_dict.keys())[:10]
                return hints
        except FileNotFoundError:
            logger.warning("medical_terms.json not found, using empty hints")
            return {}
    
    def identify_colloquial_terms(self, text: str) -> List[Dict[str, Any]]:
        if not self.llm_service:
            logger.warning("LLM service not available, cannot identify colloquial terms")
            return []
        
        try:
            logger.info("Identifying colloquial medical terms from text")
            
            type_examples = ""
            for type_name, examples in self.term_type_hints.items():
                type_examples += f"- {type_name}: {', '.join(examples[:5])}\n"
            
            if self.language == "zh":
                prompt = f"""你是一个医学术语识别专家。请从以下文本中识别所有口语化的医学术语。

## 文本内容
{text}

## 术语类型参考
{type_examples}

## 任务要求
1. 识别文本中的口语化医学术语（如"头疼"、"血压高"、"拉肚子"等）
2. 同时识别已经是标准形式的医学术语
3. 判断每个术语的类型（symptom/drug/diagnosis/examination/other）

## 输出格式
请按以下JSON格式输出：
{{
  "terms": [
    {{
      "term": "识别到的术语",
      "term_type": "symptom|drug|diagnosis|examination|other",
      "is_colloquial": true或false,
      "context": "术语在文本中的上下文片段"
    }}
  ]
}}

注意：只输出JSON，不要输出其他内容。"""
            else:
                prompt = f"""You are a medical terminology expert. Please identify all colloquial medical terms from the following text.

## Text
{text}

## Term Type Reference
{type_examples}

## Requirements
1. Identify colloquial medical terms (e.g., "headache", "high blood pressure")
2. Also identify standard medical terms
3. Determine the type of each term (symptom/drug/diagnosis/examination/other)

## Output Format
Please output in the following JSON format:
{{
  "terms": [
    {{
      "term": "identified term",
      "term_type": "symptom|drug|diagnosis|examination|other",
      "is_colloquial": true or false,
      "context": "context snippet of the term in text"
    }}
  ]
}}

Note: Only output JSON, no other content."""

            response = self.llm_service.generate(prompt, max_tokens=8000)
            
            json_match = re.search(r'\{[\s\S]*\}', response.text)
            if json_match:
                result = json.loads(json_match.group())
                terms = result.get("terms", [])
                logger.info(f"Identified {len(terms)} colloquial terms from text")
                return terms
            else:
                logger.warning("No valid JSON found in LLM response")
                return []
                
        except Exception as e:
            logger.error(f"Failed to identify colloquial terms: {e}")
            return []
    
    def normalize_term(
        self, 
        term: str, 
        context: str = "",
        term_type: Optional[str] = None
    ) -> NormalizedTerm:
        logger.debug(f"Normalizing term: '{term}' (type: {term_type})")
        
        normalized = term
        confidence = 0.0
        reasoning = ""
        code = None
        code_system = None
        source = "none"
        candidates = None
        cui = None
        
        if self.umls_client:
            umls_result = self._normalize_by_umls(term, context)
            if umls_result:
                normalized, confidence, reasoning, code, code_system, source, candidates, cui = umls_result
                logger.info(f"UMLS normalized '{term}' -> '{normalized}' (confidence: {confidence:.2f})")
        
        if confidence < 0.5 and self.llm_service:
            llm_result = self._normalize_by_llm(term, context)
            if llm_result and llm_result[1] > confidence:
                normalized, confidence, reasoning = llm_result
                source = "LLM"
                logger.info(f"LLM normalized '{term}' -> '{normalized}' (confidence: {confidence:.2f})")
        
        if confidence < 0.3:
            normalized = term
            confidence = 0.3
            reasoning = "无法规范化，保留原术语"
            source = "none"
        
        is_risky = confidence < 0.5
        
        return NormalizedTerm(
            original_term=term,
            normalized_term=normalized,
            term_type=term_type or "unknown",
            confidence=confidence,
            is_risky=is_risky,
            reasoning=reasoning,
            code=code,
            code_system=code_system,
            source=source,
            candidates=candidates,
            cui=cui
        )
    
    def _normalize_by_umls(
        self,
        term: str,
        context: str
    ) -> Optional[Tuple[str, float, str, Optional[str], Optional[str], str, Optional[List], Optional[str]]]:
        if not self.umls_client:
            return None
        
        try:
            logger.debug(f"Querying UMLS for term: '{term}'")
            
            search_term = term
            translated_term = None
            
            if self.language == "zh" and self.llm_service:
                translated_term = self._translate_term_to_english(term, context)
                if translated_term:
                    search_term = translated_term
                    logger.info(f"Translated '{term}' to English: '{translated_term}'")
            
            search_result = self.umls_client.search_term(search_term, language="ENG")
            
            if search_result.error:
                logger.warning(f"UMLS search error for '{search_term}': {search_result.error}")
            
            if not search_result.candidates and translated_term:
                logger.debug(f"No candidates for translated term '{translated_term}', trying original '{term}'")
                search_result = self.umls_client.search_term(term, language="ENG")
            
            if not search_result.candidates:
                logger.debug(f"No UMLS candidates found for term: '{term}'")
                return None
            
            candidates = search_result.candidates[:5]
            
            if self.llm_service and len(candidates) > 1:
                selected = self._llm_select_candidate(term, context, candidates, translated_term)
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
            
            confidence = min(0.95, 0.6 + best_candidate.score * 0.35)
            
            if translated_term:
                reasoning = f"UMLS匹配: {term}(翻译:{translated_term}) -> {best_candidate.term} (CUI: {best_candidate.cui})"
            else:
                reasoning = f"UMLS匹配: {term} -> {best_candidate.term} (CUI: {best_candidate.cui})"
            
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
    
    def _translate_term_to_english(self, term: str, context: str) -> Optional[str]:
        if not self.llm_service:
            return None
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                prompt = f"""请将以下中文医学术语翻译成英文。只输出英文翻译结果，不要输出其他内容。

中文术语: {term}
上下文: {context}

英文翻译:"""

                response = self.llm_service.generate(prompt, max_tokens=2000)
                
                if not response or not response.text:
                    logger.warning(f"Translation attempt {attempt + 1} returned empty response for '{term}'")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(1)
                    continue
                
                english_term = response.text.strip()
                english_term = re.sub(r'^(英文翻译:?\s*|English translation:?\s*)', '', english_term, flags=re.IGNORECASE)
                english_term = english_term.split('\n')[0].strip()
                english_term = re.sub(r'^["\']|["\']$', '', english_term)
                
                if english_term and len(english_term) < 100 and re.search(r'[a-zA-Z]', english_term):
                    logger.info(f"Translated '{term}' to '{english_term}'")
                    return english_term
                
                logger.warning(f"Translation attempt {attempt + 1} produced invalid result: '{english_term}'")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(1)
                    
            except Exception as e:
                logger.warning(f"Translation attempt {attempt + 1} failed for '{term}': {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(1)
        
        logger.warning(f"All translation attempts failed for '{term}'")
        return None
    
    def _llm_select_candidate(
        self,
        original_term: str,
        context: str,
        candidates: List[UMLSCandidate],
        translated_term: str = None
    ) -> Optional[UMLSCandidate]:
        if not self.llm_service or not candidates:
            return None
        
        try:
            candidates_text = "\n".join([
                f"{i+1}. {c.term} (CUI: {c.cui}, Score: {c.score:.2f})"
                for i, c in enumerate(candidates[:5])
            ])
            
            if self.language == "zh":
                translation_info = f"\n英文翻译: {translated_term}" if translated_term else ""
                prompt = f"""你是一个医学术语专家。请从以下UMLS候选术语中选择最匹配原始术语的一个。

原始术语: {original_term}{translation_info}
上下文: {context}

UMLS候选术语:
{candidates_text}

请只输出最佳匹配的编号(1-{len(candidates)})，不要输出其他内容。"""
            else:
                prompt = f"""You are a medical terminology expert. Please select the best matching term from the following UMLS candidates.

Original term: {original_term}
Context: {context}

UMLS Candidates:
{candidates_text}

Please output only the number (1-{len(candidates)}) of the best match, no other content."""

            response = self.llm_service.generate(prompt, max_tokens=100)
            
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
    
    def _normalize_by_llm(
        self, 
        term: str, 
        context: str
    ) -> Optional[Tuple[str, float, str]]:
        if not self.llm_service:
            return None
        
        try:
            if self.language == "zh":
                prompt = f"""你是一个医学术语规范化专家。请将以下口语化医疗术语映射到标准医学术语。

口语化术语: {term}
上下文: {context}

请按以下格式输出JSON：
{{
  "normalized_term": "标准术语",
  "reasoning": "映射理由"
}}"""
            else:
                prompt = f"""You are a medical terminology normalization expert. Please map the following colloquial medical term to a standard medical term.

Colloquial term: {term}
Context: {context}

Please output in the following JSON format:
{{
  "normalized_term": "standard term",
  "reasoning": "mapping rationale"
}}"""

            response = self.llm_service.generate(prompt, max_tokens=1000)
            
            json_match = re.search(r'\{[\s\S]*\}', response.text)
            if json_match:
                result = json.loads(json_match.group())
                normalized_term = result.get("normalized_term", term)
                reasoning = result.get("reasoning", "")
                
                if normalized_term != term:
                    confidence = 0.5
                else:
                    confidence = 0.3
                
                return (normalized_term, confidence, reasoning)
            return None
            
        except Exception as e:
            logger.error(f"LLM规范化失败: {e}")
            return None
    
    def extract_and_normalize_terms(
        self, 
        text: str, 
        context: str = ""
    ) -> List[NormalizedTerm]:
        logger.info(f"开始提取和规范化术语，文本长度: {len(text)}")
        
        identified_terms = self.identify_colloquial_terms(text)
        
        if not identified_terms:
            logger.info("未识别到任何术语")
            return []
        
        normalized_terms = []
        for term_info in identified_terms:
            term = term_info.get("term", "")
            term_type = term_info.get("term_type", "unknown")
            term_context = term_info.get("context", context)
            
            normalized = self.normalize_term(term, term_context, term_type)
            normalized_terms.append(normalized)
            logger.debug(f"  术语: {term} -> {normalized.normalized_term} (source: {normalized.source})")
        
        logger.info(f"共规范化 {len(normalized_terms)} 个术语")
        return normalized_terms
    
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
        logger.info(f"保存了 {len(terms)} 个规范化术语到数据库")
        
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
