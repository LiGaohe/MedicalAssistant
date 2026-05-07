import json
import re
import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from ..models import NormalizedTerm, TranscriptTurn
from .llm.llm_service import LLMService
from .umls.umls_client import UMLSClient
from .umls.async_umls_client import AsyncUMLSClient
from .umls.term_cache import TermCache
from .umls import UMLSCandidate, UMLSSearchResult
from .translation_service import TranslationService
from .chinese_term_indexer import ChineseTermIndexer
from .chinese_term_client import ChineseTermClient
from ..config import settings
from ..utils.logger import logger


class TerminologyService:
    def __init__(
        self, 
        db: Session, 
        llm_service: Optional[LLMService] = None,
        umls_client: Optional[UMLSClient] = None,
        translation_service: Optional[TranslationService] = None,
        language: str = "zh"
    ):
        self.db = db
        self.llm_service = llm_service
        self.translation_service = translation_service
        self.language = language
        self.term_type_hints = self._load_term_type_hints()
        
        self.umls_client = umls_client
        self.async_umls_client: Optional[AsyncUMLSClient] = None
        self.cache_service: Optional[TermCache] = None
        self.chinese_term_client: Optional[ChineseTermClient] = None
        
        if settings.UMLS_ENABLED and settings.UMLS_API_KEY:
            self._init_umls()
        
        if not self.translation_service and settings.TRANSLATION_ENABLED:
            self._init_translation()
        
        if settings.CHINESE_TERM_ENABLED:
            self._init_chinese_term_client()
        
        logger.info(f"TerminologyService initialized, UMLS: {'enabled' if self.umls_client else 'disabled'}, Translation: {'enabled' if self.translation_service else 'disabled'}, ChineseTerm: {'enabled' if self.chinese_term_client else 'disabled'}, language: {language}")
    
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
            
            max_concurrent = getattr(settings, 'UMLS_MAX_CONCURRENT', 5)
            self.async_umls_client = AsyncUMLSClient(
                api_key=settings.UMLS_API_KEY,
                cache_service=self.cache_service,
                request_timeout=settings.UMLS_REQUEST_TIMEOUT,
                max_retries=settings.UMLS_MAX_RETRIES,
                rate_limit_delay=settings.UMLS_RATE_LIMIT_DELAY,
                max_concurrent=max_concurrent
            )
            
            if self.umls_client.health_check():
                logger.info("UMLS client initialized and health check passed")
            else:
                logger.warning("UMLS client health check failed, will use fallback")
                self.umls_client = None
                self.async_umls_client = None
                
        except Exception as e:
            logger.error(f"Failed to initialize UMLS client: {e}")
            self.umls_client = None
            self.async_umls_client = None
            self.cache_service = None
    
    def _init_translation(self):
        try:
            logger.info("Initializing translation service")
            self.translation_service = TranslationService(
                model_name=settings.TRANSLATION_MODEL,
                device=settings.TRANSLATION_DEVICE
            )
            
            if self.translation_service.is_available():
                logger.info("Translation service initialized successfully")
            else:
                logger.warning("Translation service initialization failed, will use LLM fallback")
                self.translation_service = None
                
        except Exception as e:
            logger.error(f"Failed to initialize translation service: {e}")
            self.translation_service = None
    
    def _init_chinese_term_client(self):
        try:
            logger.info("Initializing Chinese term client")
            
            indexer = ChineseTermIndexer()
            
            symptom_count = indexer.load_symptom_norm(settings.SYMPTOM_NORM_PATH)
            logger.info(f"Loaded {symptom_count} symptom terms from IMCS")
            
            icd11_count = indexer.load_icd11_terms(settings.ICD11_ZH_PATH)
            logger.info(f"Loaded {icd11_count} terms from ICD-11")
            
            colloquial_file = "data/text/colloquial_synonyms.json"
            colloquial_count = indexer.load_colloquial_synonyms(colloquial_file)
            logger.info(f"Loaded {colloquial_count} colloquial synonym mappings")
            
            total_count = indexer.build_index()
            logger.info(f"Built index with {total_count} total terms")
            
            self.chinese_term_client = ChineseTermClient(
                indexer=indexer,
                fuzzy_threshold=settings.CHINESE_TERM_FUZZY_THRESHOLD,
                exact_match_bonus=settings.CHINESE_TERM_EXACT_MATCH_BONUS
            )
            
            if self.chinese_term_client.is_available():
                stats = self.chinese_term_client.get_stats()
                logger.info(f"Chinese term client initialized successfully: {stats}")
            else:
                logger.warning("Chinese term client initialization failed, no terms loaded")
                self.chinese_term_client = None
                
        except Exception as e:
            logger.error(f"Failed to initialize Chinese term client: {e}")
            self.chinese_term_client = None
    
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
        
        if self.chinese_term_client:
            chinese_result = self._normalize_by_chinese_term(term, term_type)
            if chinese_result:
                normalized, confidence, reasoning, code, code_system, source, candidates = chinese_result
                logger.info(f"ChineseTerm normalized '{term}' -> '{normalized}' (confidence: {confidence:.2f})")
        
        if confidence < 0.5 and self.umls_client:
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
    
    def _normalize_by_chinese_term(
        self,
        term: str,
        term_type: Optional[str] = None
    ) -> Optional[Tuple[str, float, str, Optional[str], Optional[str], str, Optional[List]]]:
        if not self.chinese_term_client:
            return None
        
        try:
            logger.debug(f"Searching Chinese term index for: '{term}'")
            
            result = self.chinese_term_client.search_term(
                term=term,
                term_type=term_type,
                use_fuzzy=True
            )
            
            if not result:
                logger.debug(f"No Chinese term match found for: '{term}'")
                return None
            
            confidence = result.confidence
            
            if confidence < 0.7:
                logger.debug(f"Chinese term match confidence too low: {confidence:.2f}")
                return None
            
            candidates_data = None
            if result.candidates:
                candidates_data = [
                    {
                        "term": c.term,
                        "code": c.code,
                        "code_system": c.code_system,
                        "term_type": c.term_type,
                        "source": c.source
                    }
                    for c in result.candidates[:5]
                ]
            
            match_type_desc = "精确匹配" if result.match_type == "exact" else "模糊匹配"
            reasoning = f"中文术语库{match_type_desc}: {term} -> {result.matched_term}"
            
            if result.code:
                reasoning += f" ({result.code_system}: {result.code})"
            
            logger.info(f"Chinese term match found: '{term}' -> '{result.matched_term}' (confidence: {confidence:.2f})")
            
            return (
                result.matched_term,
                confidence,
                reasoning,
                result.code,
                result.code_system,
                "ChineseTerm",
                candidates_data
            )
            
        except Exception as e:
            logger.error(f"Chinese term normalization failed for '{term}': {e}")
            return None
    
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
        if self.translation_service and self.translation_service.is_available():
            translated = self.translation_service.translate_zh_to_en(term)
            if translated:
                logger.info(f"Used translation service for '{term}' -> '{translated}'")
                return translated
        
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

            response = self.llm_service.generate(prompt, max_tokens=2000)
            
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

    def _batch_select_candidates(
        self,
        term_candidates: Dict[str, List[UMLSCandidate]],
        contexts: Dict[str, str],
        translations: Dict[str, str]
    ) -> Dict[str, UMLSCandidate]:
        """
        批量选择最佳候选术语

        Args:
            term_candidates: 术语到候选列表的映射
            contexts: 术语到上下文的映射
            translations: 术语到翻译的映射

        Returns:
            术语到选中候选的映射
        """
        if not self.llm_service or not term_candidates:
            return {}

        try:
            logger.info(f"Starting batch candidate selection for {len(term_candidates)} terms")

            candidates_text = ""
            term_list = list(term_candidates.keys())
            
            for i, term in enumerate(term_list):
                candidates = term_candidates[term]
                candidates_text += f"\n【术语{i+1}】{term}"
                if translations.get(term):
                    candidates_text += f" (翻译: {translations[term]})"
                candidates_text += "\n候选:\n"
                for j, c in enumerate(candidates[:5]):
                    candidates_text += f"  {j+1}. {c.term} (CUI: {c.cui}, Score: {c.score:.2f})\n"

            if self.language == "zh":
                prompt = f"""你是一个医学术语专家。请为每个术语选择最匹配的候选编号。

{candidates_text}

输出格式(JSON):
{{"术语原文1": 编号, "术语原文2": 编号, ...}}

注意：只输出JSON，不要输出其他内容。"""
            else:
                prompt = f"""You are a medical terminology expert. Please select the best matching candidate for each term.

{candidates_text}

Output format (JSON):
{{"term1": number, "term2": number, ...}}

Note: Only output JSON, no other content."""

            response = self.llm_service.generate(prompt, max_tokens=4000)

            json_match = re.search(r'\{[\s\S]*\}', response.text)
            if not json_match:
                logger.warning("No valid JSON found in batch selection response")
                return {}

            selections = json.loads(json_match.group())
            logger.debug(f"Batch selection result: {selections}")

            result = {}
            for term, idx in selections.items():
                if term in term_candidates:
                    try:
                        idx_int = int(idx)
                        if 1 <= idx_int <= len(term_candidates[term]):
                            result[term] = term_candidates[term][idx_int - 1]
                            logger.debug(f"Selected candidate {idx_int} for '{term}'")
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid selection index '{idx}' for term '{term}'")

            logger.info(f"Batch selection completed: {len(result)}/{len(term_candidates)} terms matched")
            return result

        except Exception as e:
            logger.error(f"Batch candidate selection failed: {e}")
            return {}

    async def _async_get_code_from_candidate(
        self,
        candidate: UMLSCandidate
    ) -> Tuple[Optional[str], Optional[str]]:
        if not self.async_umls_client or not candidate.cui:
            return None, None

        try:
            atoms = await self.async_umls_client.get_atoms(candidate.cui)

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

    async def extract_and_normalize_terms_parallel(
        self,
        text: str,
        context: str = ""
    ) -> List[NormalizedTerm]:
        """
        并行版本的术语提取和规范化
        """
        start_time = time.time()
        logger.info(f"开始并行提取和规范化术语，文本长度: {len(text)}")

        identified_terms = self.identify_colloquial_terms(text)

        if not identified_terms:
            logger.info("未识别到任何术语")
            return []

        seen_terms = set()
        unique_terms = []
        for term_info in identified_terms:
            term = term_info.get("term", "")
            if term not in seen_terms:
                seen_terms.add(term)
                unique_terms.append(term_info)

        logger.info(f"去重后剩余 {len(unique_terms)} 个术语")

        terms = [t["term"] for t in unique_terms]
        contexts = {t["term"]: t.get("context", context) for t in unique_terms}
        term_types = {t["term"]: t.get("term_type", "unknown") for t in unique_terms}

        translations = {}
        if self.language == "zh" and self.translation_service:
            trans_start = time.time()
            translations = self.translation_service.batch_translate_zh_to_en(terms)
            logger.info(f"批量翻译完成，耗时: {time.time() - trans_start:.2f}秒")

        umls_results = {}
        if self.async_umls_client:
            search_start = time.time()
            search_terms = [translations.get(term, term) for term in terms]
            umls_results = await self.async_umls_client.batch_search(
                search_terms,
                language="ENG"
            )
            logger.info(f"并行UMLS检索完成，耗时: {time.time() - search_start:.2f}秒")

        term_candidates = {}
        for term in terms:
            search_term = translations.get(term, term)
            result = umls_results.get(search_term)
            if result and hasattr(result, 'candidates') and result.candidates:
                term_candidates[term] = result.candidates[:5]

        selections = {}
        if term_candidates and self.llm_service:
            select_start = time.time()
            selections = self._batch_select_candidates(term_candidates, contexts, translations)
            logger.info(f"批量LLM选择完成，耗时: {time.time() - select_start:.2f}秒")

        code_tasks = {}
        for term in terms:
            if term in selections:
                code_tasks[term] = self._async_get_code_from_candidate(selections[term])
        
        code_results = {}
        if code_tasks:
            code_start = time.time()
            code_results_list = await asyncio.gather(*code_tasks.values(), return_exceptions=True)
            for term, result in zip(code_tasks.keys(), code_results_list):
                if isinstance(result, Exception):
                    logger.warning(f"获取code失败 for {term}: {result}")
                    code_results[term] = (None, None)
                else:
                    code_results[term] = result
            logger.info(f"并行获取code完成，耗时: {time.time() - code_start:.2f}秒")

        normalized_terms = []
        for term_info in unique_terms:
            term = term_info.get("term", "")
            term_type = term_types.get(term, "unknown")

            normalized = term
            confidence = 0.3
            reasoning = "无法规范化，保留原术语"
            code = None
            code_system = None
            source = "none"
            candidates_data = None
            cui = None

            if term in selections:
                best_candidate = selections[term]
                code, code_system = code_results.get(term, (None, None))

                candidates = term_candidates.get(term, [])
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
                trans_info = f"(翻译:{translations.get(term, term)})" if translations.get(term) else ""
                reasoning = f"UMLS匹配: {term}{trans_info} -> {best_candidate.term} (CUI: {best_candidate.cui})"
                source = "UMLS"
                cui = best_candidate.cui
                normalized = best_candidate.term

            elif confidence < 0.5 and self.llm_service:
                llm_result = self._normalize_by_llm(term, contexts.get(term, ""))
                if llm_result and llm_result[1] > confidence:
                    normalized, confidence, reasoning = llm_result
                    source = "LLM"

            is_risky = confidence < 0.5

            normalized_term = NormalizedTerm(
                original_term=term,
                normalized_term=normalized,
                term_type=term_type,
                confidence=confidence,
                is_risky=is_risky,
                reasoning=reasoning,
                code=code,
                code_system=code_system,
                source=source,
                candidates=candidates_data,
                cui=cui
            )
            normalized_terms.append(normalized_term)

        total_time = time.time() - start_time
        logger.info(f"并行规范化完成，共 {len(normalized_terms)} 个术语，总耗时: {total_time:.2f}秒")

        return normalized_terms

    def extract_and_normalize_terms(
        self,
        text: str,
        context: str = "",
        use_parallel: bool = True
    ) -> List[NormalizedTerm]:
        """
        术语提取和规范化入口

        Args:
            text: 输入文本
            context: 上下文
            use_parallel: 是否使用并行模式
        """
        parallel_enabled = getattr(settings, 'TERMINOLOGY_PARALLEL_ENABLED', True)
        
        if use_parallel and parallel_enabled and self.async_umls_client:
            try:
                result = asyncio.run(
                    self._extract_and_normalize_terms_parallel_with_cleanup(text, context)
                )
                return result
            except Exception as e:
                logger.error(f"并行处理失败，回退到串行模式: {e}")

        return self._extract_and_normalize_terms_serial(text, context)

    async def _extract_and_normalize_terms_parallel_with_cleanup(
        self,
        text: str,
        context: str = ""
    ) -> List[NormalizedTerm]:
        """
        带清理的并行处理包装方法
        """
        try:
            result = await self.extract_and_normalize_terms_parallel(text, context)
            return result
        finally:
            if self.async_umls_client:
                await self.async_umls_client.close()

    def _extract_and_normalize_terms_serial(
        self,
        text: str,
        context: str = ""
    ) -> List[NormalizedTerm]:
        """
        串行版本的术语提取和规范化（原有逻辑）
        """
        logger.info(f"开始串行提取和规范化术语，文本长度: {len(text)}")

        identified_terms = self.identify_colloquial_terms(text)

        if not identified_terms:
            logger.info("未识别到任何术语")
            return []

        seen_terms = set()
        unique_terms = []
        for term_info in identified_terms:
            term = term_info.get("term", "")
            if term not in seen_terms:
                seen_terms.add(term)
                unique_terms.append(term_info)
            else:
                logger.debug(f"跳过重复术语: '{term}'")

        logger.info(f"去重后剩余 {len(unique_terms)} 个术语（原始 {len(identified_terms)} 个）")

        normalized_terms = []
        for term_info in unique_terms:
            term = term_info.get("term", "")
            term_type = term_info.get("term_type", "unknown")
            term_context = term_info.get("context", context)

            normalized = self.normalize_term(term, term_context, term_type)
            normalized_terms.append(normalized)
            logger.debug(f"  术语: {term} -> {normalized.normalized_term} (source: {normalized.source})")

        logger.info(f"共规范化 {len(normalized_terms)} 个术语")
        return normalized_terms
