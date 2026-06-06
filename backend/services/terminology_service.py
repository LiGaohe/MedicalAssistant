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
from .term_rewriter import TermRewriter, ConstrainedTermSelector
from ..config import settings
from ..utils.logger import logger


class TerminologyService:
    _normalization_cache: Dict[str, NormalizedTerm] = {}
    _cache_max_size: int = 1000
    
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
        self.rewriter: Optional[TermRewriter] = None
        self.selector: Optional[ConstrainedTermSelector] = None
        
        if settings.UMLS_ENABLED and settings.UMLS_API_KEY and language != "zh":
            self._init_umls()
        elif language == "zh":
            logger.info("Chinese mode: UMLS disabled, using local ICD-11 and Chinese term libraries")
        
        if not self.translation_service and settings.TRANSLATION_ENABLED and language != "zh":
            self._init_translation()
        
        if settings.CHINESE_TERM_ENABLED:
            self._init_chinese_term_client()
        
        if settings.ENABLE_REWRITE and self.llm_service:
            self.rewriter = TermRewriter(llm_service=self.llm_service, language=language)
            self.selector = ConstrainedTermSelector(llm_service=self.llm_service, language=language)
            logger.info("TermRewriter and ConstrainedTermSelector initialized")
        elif settings.ENABLE_REWRITE:
            logger.warning("ENABLE_REWRITE is True but LLM service not available, rewrite disabled")
        
        logger.info(f"TerminologyService initialized, UMLS: {'enabled' if self.umls_client else 'disabled'}, Translation: {'enabled' if self.translation_service else 'disabled'}, ChineseTerm: {'enabled' if self.chinese_term_client else 'disabled'}, Rewrite: {'enabled' if self.rewriter else 'disabled'}, language: {language}")
    
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

            # 关闭thinking模式：术语识别是模式匹配任务，不需要深度推理
            response = self.llm_service.generate(prompt, max_tokens=8000, thinking_enabled=False)
            
            logger.info(f"LLM识别口语化术语响应长度: {len(response.text)} 字符")
            logger.debug(f"LLM识别口语化术语响应内容:\n{response.text}")
            
            if response.thinking_content:
                logger.info(f"LLM返回thinking内容, 长度: {len(response.thinking_content)} 字符")
            
            text = response.text.strip()
            text = self._strip_whitespace_padding(text)
            
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                json_str = json_match.group()
                try:
                    result = json.loads(json_str)
                    terms = result.get("terms", [])
                    logger.info(f"Identified {len(terms)} colloquial terms from text")
                    return terms
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析失败，尝试修复: {e}")
                    fixed = self._try_fix_json(json_str)
                    if fixed is not None:
                        terms = fixed.get("terms", [])
                        logger.info(f"JSON修复成功，识别到 {len(terms)} 个术语")
                        return terms
                    logger.error(f"JSON修复也失败，原始响应内容:\n{response.text[:500]}")
                    return []
            else:
                logger.warning("No valid JSON found in LLM response")
                logger.debug(f"完整响应内容:\n{response.text[:500]}")
                return []
                
        except Exception as e:
            logger.error(f"Failed to identify colloquial terms: {e}")
            return []
    
    def _strip_whitespace_padding(self, text: str) -> str:
        if not text:
            return text
        
        original_len = len(text)
        text = re.sub(r'[\t ]+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n', text)
        text = text.strip()
        
        if len(text) < original_len:
            logger.debug(f"去除空白填充: {original_len} -> {len(text)} 字符")
        
        return text
    
    def _try_fix_json(self, json_str: str) -> Optional[Dict[str, Any]]:
        if not json_str:
            return None
        
        fixed = json_str
        
        fixed = re.sub(r',\s*}', '}', fixed)
        fixed = re.sub(r',\s*]', ']', fixed)
        fixed = re.sub(r':\s*,', ': null,', fixed)
        fixed = re.sub(r':\s*}', ': null}', fixed)
        fixed = re.sub(r',\s*,', ',', fixed)
        
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        
        brace_count = fixed.count('{') - fixed.count('}')
        bracket_count = fixed.count('[') - fixed.count(']')
        
        if brace_count > 0:
            fixed += '}' * brace_count
        if bracket_count > 0:
            fixed += ']' * bracket_count
        
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        
        try:
            last_valid_brace = fixed.rfind('}')
            if last_valid_brace > 0:
                for end_pos in range(last_valid_brace, 0, -1):
                    if fixed[end_pos] == '}':
                        candidate = fixed[:end_pos + 1]
                        brace_c = candidate.count('{') - candidate.count('}')
                        bracket_c = candidate.count('[') - candidate.count(']')
                        if brace_c > 0:
                            candidate += '}' * brace_c
                        if bracket_c > 0:
                            candidate += ']' * bracket_c
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            continue
        except Exception:
            pass
        
        try:
            last_complete_item = json_str.rfind('},')
            if last_complete_item > 0:
                candidate = json_str[:last_complete_item + 1] + ']}'
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                
                candidate = json_str[:last_complete_item + 1] + ']'
                brace_c = candidate.count('{') - candidate.count('}')
                if brace_c > 0:
                    candidate += '}' * brace_c
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        
        logger.debug("所有JSON修复尝试均失败")
        return None
    
    def _get_cache_key(self, term: str, term_type: str) -> str:
        """生成缓存键"""
        return f"{term}|{term_type}"
    
    def _get_from_cache(self, term: str, term_type: str) -> Optional[NormalizedTerm]:
        """从缓存获取规范化结果"""
        cache_key = self._get_cache_key(term, term_type)
        if cache_key in self._normalization_cache:
            logger.info(f"[CACHE_HIT] Found cached result for '{term}' (type: {term_type})")
            return self._normalization_cache[cache_key]
        return None
    
    def _save_to_cache(self, term: str, term_type: str, result: NormalizedTerm):
        """保存规范化结果到缓存"""
        if len(self._normalization_cache) >= self._cache_max_size:
            keys_to_remove = list(self._normalization_cache.keys())[:self._cache_max_size // 2]
            for key in keys_to_remove:
                del self._normalization_cache[key]
            logger.info(f"[CACHE] Evicted {len(keys_to_remove)} entries from cache")
        
        cache_key = self._get_cache_key(term, term_type)
        self._normalization_cache[cache_key] = result
        logger.debug(f"[CACHE] Saved result for '{term}' (type: {term_type})")
    
    def normalize_single_term(
        self,
        term: str,
        context: str = "",
        term_type: str = "unknown"
    ) -> NormalizedTerm:
        """
        Normalize a single term (mention) without scanning full text.

        This is a convenience wrapper around normalize_term() for the
        selective normalization pipeline (Stage 3). It does not call
        identify_colloquial_terms() and directly normalizes the given term.

        Args:
            term: The term (mention) to normalize
            context: Optional context string
            term_type: Type of the term (symptom, drug, diagnosis, etc.)

        Returns:
            NormalizedTerm with normalization results
        """
        cached_result = self._get_from_cache(term, term_type)
        if cached_result:
            return cached_result
        
        logger.info(f"Normalizing single term: '{term}' (type: {term_type})")
        result = self.normalize_term(term, context=context, term_type=term_type)
        
        self._save_to_cache(term, term_type, result)
        
        return result

    def batch_normalize_terms(
        self,
        terms: List[Dict[str, str]],
        context: str = ""
    ) -> Dict[str, NormalizedTerm]:
        """
        批量规范化术语，使用批量LLM调用优化性能
        
        Args:
            terms: [{"term": "脖子处淋巴结肿大", "type": "symptom"}, ...]
            context: 可选的上下文字符串
        
        Returns:
            {"脖子处淋巴结肿大": NormalizedTerm, ...}
        """
        if not terms:
            return {}
        
        logger.info(f"[BATCH_NORM] Starting batch normalization for {len(terms)} terms")
        start_time = time.time()
        
        results = {}
        is_zh = self.language == "zh"
        
        terms_needing_rewrite = []
        rewrite_map = {}
        
        for term_info in terms:
            term = term_info.get("term", "")
            term_type = term_info.get("type", "unknown")
            
            best_result = self._try_exact_or_alias_match(term, term_type)
            if best_result:
                normalized, confidence, reasoning, code, code_system, source, candidates = best_result
                logger.info(f"[BATCH_NORM] Exact/alias match: '{term}' -> '{normalized}'")
                results[term] = NormalizedTerm(
                    original_term=term,
                    normalized_term=normalized,
                    term_type=term_type,
                    confidence=confidence,
                    is_risky=confidence < 0.5,
                    reasoning=reasoning,
                    code=code,
                    code_system=code_system,
                    source=source,
                    candidates=candidates
                )
                continue
            
            if is_zh and self.chinese_term_client:
                zh_result = self._normalize_by_chinese_term(term, term_type)
                if zh_result and zh_result[1] >= settings.REWRITE_TRIGGER_THRESHOLD:
                    n, c, r, cd, cs, s, cands = zh_result
                    logger.info(f"[BATCH_NORM] ChineseTerm match: '{term}' -> '{n}' (score: {c:.2f})")
                    results[term] = NormalizedTerm(
                        original_term=term,
                        normalized_term=n,
                        term_type=term_type,
                        confidence=c,
                        is_risky=c < 0.5,
                        reasoning=r,
                        code=cd,
                        code_system=cs,
                        source=s,
                        candidates=cands
                    )
                    continue
            
            terms_needing_rewrite.append(term_info)
            rewrite_map[term] = term_type
        
        if terms_needing_rewrite and self.rewriter:
            logger.info(f"[BATCH_NORM] {len(terms_needing_rewrite)} terms need rewrite, using batch LLM")
            
            batch_rewrite_start = time.time()
            batch_rewrites = self.rewriter.batch_rewrite_colloquial(
                terms_needing_rewrite,
                max_phrasings_per_term=2
            )
            logger.info(f"[BATCH_NORM] Batch rewrite completed in {time.time() - batch_rewrite_start:.2f}s")
            
            for term_info in terms_needing_rewrite:
                term = term_info.get("term", "")
                term_type = term_info.get("type", "unknown")
                
                if term in results:
                    continue
                
                rewrites = batch_rewrites.get(term, [term])
                best_score = 0.0
                best_normalized = term
                best_code = None
                best_code_system = None
                best_source = "unresolved"
                best_candidates = None
                
                for rewrite in rewrites:
                    if rewrite == term:
                        continue
                    
                    if is_zh and self.chinese_term_client:
                        zh_result = self._normalize_by_chinese_term(rewrite, term_type)
                        if zh_result:
                            n, c, r, cd, cs, s, cands = zh_result
                            if c > best_score:
                                best_score = c
                                best_normalized = n
                                best_code = cd
                                best_code_system = cs
                                best_source = s
                                best_candidates = cands
                                logger.info(f"[BATCH_NORM] Rewrite match: '{term}' -> '{rewrite}' -> '{n}' (score: {c:.2f})")
                
                if best_score >= 0.3:
                    results[term] = NormalizedTerm(
                        original_term=term,
                        normalized_term=best_normalized,
                        term_type=term_type,
                        confidence=best_score,
                        is_risky=best_score < 0.5,
                        reasoning=f"批量重写匹配: {term} -> {best_normalized}",
                        code=best_code,
                        code_system=best_code_system,
                        source=best_source,
                        candidates=best_candidates
                    )
                else:
                    results[term] = NormalizedTerm(
                        original_term=term,
                        normalized_term=term,
                        term_type=term_type,
                        confidence=0.3,
                        is_risky=True,
                        reasoning="批量规范化未找到匹配，保留原术语",
                        source="unresolved"
                    )
        
        for term_info in terms:
            term = term_info.get("term", "")
            if term not in results:
                term_type = term_info.get("type", "unknown")
                results[term] = NormalizedTerm(
                    original_term=term,
                    normalized_term=term,
                    term_type=term_type,
                    confidence=0.3,
                    is_risky=True,
                    reasoning="未处理，保留原术语",
                    source="unresolved"
                )
        
        total_time = time.time() - start_time
        logger.info(f"[BATCH_NORM] Completed {len(results)} terms in {total_time:.2f}s")
        
        return results

    def normalize_term(
        self, 
        term: str, 
        context: str = "",
        term_type: Optional[str] = None
    ) -> NormalizedTerm:
        logger.info(f"[TERM_NORM] Normalizing term: '{term}' (type: {term_type})")
        
        normalized = term
        confidence = 0.0
        reasoning = ""
        code = None
        code_system = None
        source = "none"
        candidates = None
        cui = None
        is_zh = self.language == "zh"

        best_result = self._try_exact_or_alias_match(term, term_type)
        if best_result:
            normalized, confidence, reasoning, code, code_system, source, candidates = best_result
            logger.info(f"[TERM_NORM] Exact/alias match: '{term}' -> '{normalized}' (confidence: {confidence:.2f}, source: {source})")
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

        if self.rewriter and self.rewriter.detect_multi_concept(term):
            logger.info(f"[TERM_NORM] Multi-concept detected for '{term}', decomposing")
            atomic_mentions = self.rewriter.decompose_multi_concept(term, term_type or "unknown", context)
            if len(atomic_mentions) > 1:
                logger.info(f"[TERM_NORM] Decomposed '{term}' into {len(atomic_mentions)} atomic mentions: {atomic_mentions}")
                normalized_terms = []
                for atomic in atomic_mentions:
                    sub_result = self.normalize_term(atomic, context, term_type)
                    normalized_terms.append(sub_result.normalized_term)
                combined = "；".join(normalized_terms)
                return NormalizedTerm(
                    original_term=term,
                    normalized_term=combined,
                    term_type=term_type or "unknown",
                    confidence=0.5,
                    is_risky=False,
                    reasoning=f"多概念拆解规范化: {term} -> {atomic_mentions} -> {normalized_terms}",
                    source="decompose",
                )

        best_score = 0.0
        all_candidates = []

        if is_zh and self.chinese_term_client:
            zh_result_data = self._normalize_by_chinese_term(term, term_type)
            if zh_result_data:
                n, c, r, cd, cs, s, cands = zh_result_data
                all_candidates.append({
                    "term": n, "confidence": c, "reasoning": r,
                    "code": cd, "code_system": cs, "source": s, "candidates": cands
                })
                if c > best_score:
                    best_score = c
                    normalized, confidence, reasoning, code, code_system, source, candidates = n, c, r, cd, cs, s, cands
                    logger.info(f"[TERM_NORM] ChineseTerm result: '{term}' -> '{normalized}' (score: {c:.2f})")

        if not is_zh and self.umls_client:
            umls_result_data = self._normalize_by_umls(term, context)
            if umls_result_data:
                n, c, r, cd, cs, s, cands, cu = umls_result_data
                all_candidates.append({
                    "term": n, "confidence": c, "reasoning": r,
                    "code": cd, "code_system": cs, "source": s, "candidates": cands, "cui": cu
                })
                if c > best_score:
                    best_score = c
                    normalized, confidence, reasoning, code, code_system, source, candidates, cui = n, c, r, cd, cs, s, cands, cu
                    logger.info(f"[TERM_NORM] UMLS result: '{term}' -> '{normalized}' (score: {c:.2f})")

        threshold = settings.REWRITE_TRIGGER_THRESHOLD
        if best_score >= threshold:
            logger.info(f"[TERM_NORM] High confidence ({best_score:.2f} >= {threshold}), returning directly")
            is_risky = confidence < 0.5
            return NormalizedTerm(
                original_term=term, normalized_term=normalized,
                term_type=term_type or "unknown", confidence=confidence,
                is_risky=is_risky, reasoning=reasoning,
                code=code, code_system=code_system, source=source,
                candidates=candidates, cui=cui
            )

        rewrite_produced_new_terms = False
        if self.rewriter and best_score < threshold:
            logger.info(f"[TERM_NORM] Low confidence ({best_score:.2f} < {threshold}), triggering rewrite")
            rewrites = self.rewriter.rewrite_colloquial(term, term_type or "unknown", context)
            search_terms = [term] + [r for r in rewrites if r != term]
            logger.info(f"[TERM_NORM] Search terms after rewrite: {search_terms}")
            
            rewrite_produced_new_terms = len(search_terms) > 1

            for search_term in search_terms:
                if search_term == term:
                    continue

                if is_zh and self.chinese_term_client:
                    zh_result = self._normalize_by_chinese_term(search_term, term_type)
                    if zh_result:
                        n, c, r, cd, cs, s, cands = zh_result
                        all_candidates.append({
                            "term": n, "confidence": c, "reasoning": r,
                            "code": cd, "code_system": cs, "source": s, "candidates": cands,
                            "via_rewrite": search_term
                        })
                        if c > best_score:
                            best_score = c
                            normalized, confidence, reasoning, code, code_system, source, candidates = n, c, r, cd, cs, s, cands
                            logger.info(f"[TERM_NORM] Rewrite retrieval match: '{search_term}' -> '{normalized}' (score: {c:.2f})")

                if not is_zh and self.umls_client:
                    umls_result = self._normalize_by_umls(search_term, context)
                    if umls_result:
                        n, c, r, cd, cs, s, cands, cu = umls_result
                        all_candidates.append({
                            "term": n, "confidence": c, "reasoning": r,
                            "code": cd, "code_system": cs, "source": s, "candidates": cands,
                            "cui": cu, "via_rewrite": search_term
                        })
                        if c > best_score:
                            best_score = c
                            normalized, confidence, reasoning, code, code_system, source, candidates, cui = n, c, r, cd, cs, s, cands, cu
                            logger.info(f"[TERM_NORM] Rewrite retrieval UMLS match: '{search_term}' -> '{normalized}' (score: {c:.2f})")

        if best_score < threshold and self.rewriter and rewrite_produced_new_terms:
            logger.info(f"[TERM_NORM] Still low confidence ({best_score:.2f}), generating alternative phrasings")
            alternatives = self.rewriter.generate_alternative_phrasings(term, term_type or "unknown", context)
            if alternatives:
                for alt in alternatives:
                    if is_zh and self.chinese_term_client:
                        zh_result = self._normalize_by_chinese_term(alt, term_type)
                        if zh_result:
                            n, c, r, cd, cs, s, cands = zh_result
                            all_candidates.append({
                                "term": n, "confidence": c, "reasoning": r,
                                "code": cd, "code_system": cs, "source": s, "candidates": cands,
                                "via_alt": alt
                            })
                            if c > best_score:
                                best_score = c
                                normalized, confidence, reasoning, code, code_system, source, candidates = n, c, r, cd, cs, s, cands
                                logger.info(f"[TERM_NORM] Alt phrasing match: '{alt}' -> '{normalized}' (score: {c:.2f})")

                    if not is_zh and self.umls_client:
                        umls_result = self._normalize_by_umls(alt, context)
                        if umls_result:
                            n, c, r, cd, cs, s, cands, cu = umls_result
                            all_candidates.append({
                                "term": n, "confidence": c, "reasoning": r,
                                "code": cd, "code_system": cs, "source": s, "candidates": cands,
                                "cui": cu, "via_alt": alt
                            })
                            if c > best_score:
                                best_score = c
                                normalized, confidence, reasoning, code, code_system, source, candidates, cui = n, c, r, cd, cs, s, cands, cu
                                logger.info(f"[TERM_NORM] Alt phrasing UMLS match: '{alt}' -> '{normalized}' (score: {c:.2f})")

        if all_candidates and self.selector:
            logger.info(f"[TERM_NORM] Running constrained selection from {len(all_candidates)} candidates")
            selected = self.selector.select_from_candidates(
                mention=term,
                concept_type=term_type or "unknown",
                candidates=all_candidates,
                context=context
            )
            if selected:
                normalized = selected.get("term", normalized)
                confidence = selected.get("confidence", confidence)
                reasoning = selected.get("reasoning", reasoning) or f"Constrained selection from {len(all_candidates)} candidates"
                code = selected.get("code", code)
                code_system = selected.get("code_system", code_system)
                source = selected.get("source", "constrained_select")
                candidates = selected.get("candidates", candidates)
                cui = selected.get("cui", cui)
                logger.info(f"[TERM_NORM] Constrained selection: '{term}' -> '{normalized}' (confidence: {confidence:.2f})")

        if confidence < 0.3:
            normalized = term
            confidence = 0.3
            reasoning = "无法规范化，保留原术语(unresolved)"
            source = "unresolved"
            logger.info(f"[TERM_NORM] Unresolved: '{term}' kept as original")

        is_risky = confidence < 0.5

        logger.info(f"[TERM_NORM] Final: '{term}' -> '{normalized}' (confidence: {confidence:.2f}, source: {source})")
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

    def _try_exact_or_alias_match(
        self,
        term: str,
        term_type: Optional[str] = None
    ) -> Optional[Tuple[str, float, str, Optional[str], Optional[str], str, Optional[List]]]:
        if not self.chinese_term_client:
            return None

        try:
            result = self.chinese_term_client.search_term(
                term=term,
                term_type=term_type,
                use_fuzzy=False
            )

            if not result:
                return None

            if result.match_type == "exact" and result.confidence >= 0.9:
                candidates_data = None
                if result.candidates:
                    candidates_data = [
                        {"term": c.term, "code": c.code, "code_system": c.code_system,
                         "term_type": c.term_type, "source": c.source}
                        for c in result.candidates[:5]
                    ]
                return (
                    result.matched_term, result.confidence,
                    f"精确匹配: {term} -> {result.matched_term}",
                    result.code, result.code_system, "ChineseTerm_exact", candidates_data
                )

            if result.match_type == "synonym" and result.confidence >= 0.85:
                candidates_data = None
                if result.candidates:
                    candidates_data = [
                        {"term": c.term, "code": c.code, "code_system": c.code_system,
                         "term_type": c.term_type, "source": c.source}
                        for c in result.candidates[:5]
                    ]
                return (
                    result.matched_term, result.confidence,
                    f"同义词匹配: {term} -> {result.matched_term}",
                    result.code, result.code_system, "ChineseTerm_synonym", candidates_data
                )

        except Exception as e:
            logger.error(f"Exact/alias match check failed for '{term}': {e}")

        return None
    
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
            
            if self.language == "zh":
                normalized_term = term
                if translated_term:
                    reasoning = f"UMLS匹配(保留中文): {term}(翻译:{translated_term}) -> CUI: {best_candidate.cui}, 英文: {best_candidate.term}"
                else:
                    reasoning = f"UMLS匹配(保留中文): {term} -> CUI: {best_candidate.cui}, 英文: {best_candidate.term}"
            else:
                normalized_term = best_candidate.term
                if translated_term:
                    reasoning = f"UMLS匹配: {term}(翻译:{translated_term}) -> {best_candidate.term} (CUI: {best_candidate.cui})"
                else:
                    reasoning = f"UMLS匹配: {term} -> {best_candidate.term} (CUI: {best_candidate.cui})"
            
            return (
                normalized_term,
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

                # 关闭thinking模式：翻译是简单映射任务
                response = self.llm_service.generate(prompt, max_tokens=2000, thinking_enabled=False)
                
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

            # 关闭thinking模式：候选选择是简单匹配任务
            response = self.llm_service.generate(prompt, max_tokens=2000, thinking_enabled=False)
            
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

口腔化术语: {term}
上下文: {context}

请按以下格式输出JSON：
{{
  "normalized_term": "标准术语",
  "reasoning": "映射理由"
}}

注意：只能根据你的医学知识输出最合理的标准术语。如果无法确定，将normalized_term设为与输入相同的值，confidence设为0.3。"""
            else:
                prompt = f"""You are a medical terminology normalization expert. Please map the following colloquial medical term to a standard medical term.

Colloquial term: {term}
Context: {context}

Please output in the following JSON format:
{{
  "normalized_term": "standard term",
  "reasoning": "mapping rationale"
}}

Note: Output the most reasonable standard term based on your medical knowledge. If uncertain, set normalized_term to the same value as input with confidence 0.3."""

            # 关闭thinking模式：术语标准化是简单映射任务
            response = self.llm_service.generate(prompt, max_tokens=1000, thinking_enabled=False)
            
            text = response.text.strip()
            text = self._strip_whitespace_padding(text)
            
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                json_str = json_match.group()
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError:
                    result = self._try_fix_json(json_str)
                
                if result is not None:
                    normalized_term = result.get("normalized_term", term)
                    if isinstance(normalized_term, dict):
                        logger.warning(f"LLM返回normalized_term为dict类型: {normalized_term}, 尝试提取字符串值")
                        normalized_term = normalized_term.get("value") or normalized_term.get("term") or str(normalized_term)
                    if not isinstance(normalized_term, str):
                        normalized_term = str(normalized_term)
                    reasoning = result.get("reasoning", "")
                    if isinstance(reasoning, dict):
                        reasoning = str(reasoning)
                    
                    confidence = 0.4
                    if normalized_term != term and normalized_term:
                        confidence = 0.45
                    
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

    def _extract_medical_terms_with_llm(self, text: str) -> Tuple[List[str], int, int, int]:
        """
        从文本中提取医学术语

        Returns:
            Tuple[terms, llm_call_count, char_count, token_count]
        """
        logger.info(f"[EXTRACT_TERMS] Extracting medical terms from draft via LLM, text length: {len(text)}")
        if not self.llm_service:
            logger.warning("[EXTRACT_TERMS] LLM service not available, skipping term extraction")
            return [], 0, 0, 0

        try:
            prompt = self.llm_service.prompt_manager.render(
                "extract_medical_terms",
                draft_text=text
            )
            # 术语提取是模式匹配任务，关闭thinking模式；使用流式调用减少等待
            response = self.llm_service.generate_stream_to_response(
                prompt,
                thinking_enabled=False,
                max_tokens=4096
            )
            logger.info(f"[EXTRACT_TERMS] LLM response length: {len(response.text)} characters")
            raw_text = response.text.strip()
            raw_text = self._strip_whitespace_padding(raw_text)

            # 统计LLM调用信息
            prompt_chars = getattr(response, 'prompt_chars', 0) or 0
            completion_tokens = getattr(response, 'completion_tokens', 0) or 0
            if prompt_chars == 0 and completion_tokens == 0:
                prompt_chars = len(prompt)
                completion_tokens = len(raw_text) // 4

            # 优先尝试解析JSON数组
            json_match = re.search(r'\[[\s\S]*\]', raw_text)
            if json_match:
                json_str = json_match.group()
                try:
                    term_objects = json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.warning(f"[EXTRACT_TERMS] JSON array parse failed: {e}")
                    term_objects = None
            else:
                term_objects = None

            # 如果数组解析失败，尝试解析JSON对象并包装为数组
            if term_objects is None:
                json_match = re.search(r'\{[\s\S]*\}', raw_text)
                if json_match:
                    json_str = json_match.group()
                    try:
                        obj = json.loads(json_str)
                    except json.JSONDecodeError as e:
                        logger.warning(f"[EXTRACT_TERMS] JSON object parse failed: {e}, skipping term extraction")
                        return [], 1, prompt_chars, completion_tokens

                    if isinstance(obj, dict):
                        # 单个对象包装为数组
                        term_objects = [obj]
                        logger.info(f"[EXTRACT_TERMS] Parsed single JSON object as array: {obj}")
                    elif isinstance(obj, list):
                        term_objects = obj
                    else:
                        logger.warning(f"[EXTRACT_TERMS] Unexpected JSON type: {type(obj)}, skipping term extraction")
                        return [], 1, prompt_chars, completion_tokens
                else:
                    logger.warning("[EXTRACT_TERMS] No valid JSON found in LLM response, skipping term extraction")
                    logger.warning(f"[EXTRACT_TERMS] Raw response: {raw_text[:500]}")
                    return [], 1, prompt_chars, completion_tokens

            if not isinstance(term_objects, list):
                logger.warning(f"[EXTRACT_TERMS] Response is not a list: {type(term_objects)}, skipping term extraction")
                return [], 1, prompt_chars, completion_tokens

            terms = []
            for item in term_objects:
                if isinstance(item, dict) and "term" in item:
                    terms.append(item["term"])
                elif isinstance(item, str):
                    terms.append(item)

            unique_terms = list(dict.fromkeys(terms))
            logger.info(f"[EXTRACT_TERMS] LLM extracted {len(unique_terms)} unique medical terms: {unique_terms}")
            return unique_terms, 1, prompt_chars, completion_tokens

        except Exception as e:
            logger.error(f"[EXTRACT_TERMS] LLM extraction failed: {e}, skipping term extraction")
            return [], 0, 0, 0

    def _llm_standardize_terms(self, terms: List[str]) -> Tuple[Dict[str, str], int, int, int]:
        """
        LLM术语标准化

        Returns:
            Tuple[term_mapping, llm_call_count, char_count, token_count]
        """
        logger.info(f"[LLM_STD] Starting LLM standardization for {len(terms)} terms")
        if not self.llm_service:
            logger.warning("[LLM_STD] LLM service not available, returning empty mapping")
            return {}, 0, 0, 0
        try:
            terms_json = json.dumps(terms, ensure_ascii=False)
            prompt = self.llm_service.prompt_manager.render(
                "term_standardization",
                terms=terms_json
            )
            # 术语标准化是简单映射任务，关闭thinking模式；使用流式调用减少等待
            response = self.llm_service.generate_stream_to_response(
                prompt,
                thinking_enabled=False,
                max_tokens=4096
            )
            logger.info(f"[LLM_STD] LLM response length: {len(response.text)} characters")
            text = response.text.strip()
            text = self._strip_whitespace_padding(text)

            # 统计LLM调用信息
            prompt_chars = getattr(response, 'prompt_chars', 0) or 0
            completion_tokens = getattr(response, 'completion_tokens', 0) or 0
            if prompt_chars == 0 and completion_tokens == 0:
                prompt_chars = len(prompt)
                completion_tokens = len(text) // 4

            json_match = re.search(r'\{[\s\S]*\}', text)
            if not json_match:
                logger.warning("[LLM_STD] No valid JSON found in LLM response")
                return {}, 1, prompt_chars, completion_tokens
            json_str = json_match.group()
            try:
                result = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(f"[LLM_STD] JSON parse failed, attempting fix: {e}")
                result = self._try_fix_json(json_str)
            if result is None or not isinstance(result, dict):
                logger.error("[LLM_STD] JSON fix also failed or result is not a dict")
                return {}, 1, prompt_chars, completion_tokens
            for original, standardized in result.items():
                logger.info(f"[LLM_STD] '{original}' -> '{standardized}'")
            logger.info(f"[LLM_STD] Standardized {len(result)} terms")
            return result, 1, prompt_chars, completion_tokens
        except Exception as e:
            logger.error(f"[LLM_STD] LLM standardization failed: {e}")
            return {}, 0, 0, 0

    def _lookup_standardized_terms_zh(self, term_mapping: Dict[str, str]) -> Dict[str, Tuple[str, Optional[str], Optional[str]]]:
        logger.info(f"[LOOKUP_ZH] Looking up {len(term_mapping)} terms in ICD-11")
        if not self.chinese_term_client:
            logger.warning("[LOOKUP_ZH] Chinese term client not available, returning empty dict")
            return {}
        result = {}
        for original_term, llm_term in term_mapping.items():
            try:
                exact_result = self.chinese_term_client.search_term(
                    term=llm_term,
                    use_fuzzy=False
                )
                if exact_result and exact_result.confidence >= 0.9:
                    result[original_term] = (
                        exact_result.matched_term,
                        exact_result.code,
                        exact_result.code_system
                    )
                    logger.info(f"[LOOKUP_ZH] Exact match: '{original_term}' -> LLM:'{llm_term}' -> '{exact_result.matched_term}' (code: {exact_result.code})")
                    continue
                fuzzy_result = self.chinese_term_client.search_term(
                    term=llm_term,
                    use_fuzzy=True
                )
                if fuzzy_result and fuzzy_result.confidence >= 0.7:
                    result[original_term] = (
                        fuzzy_result.matched_term,
                        fuzzy_result.code,
                        fuzzy_result.code_system
                    )
                    logger.info(f"[LOOKUP_ZH] Fuzzy match: '{original_term}' -> LLM:'{llm_term}' -> '{fuzzy_result.matched_term}' (code: {fuzzy_result.code}, confidence: {fuzzy_result.confidence:.2f})")
                    continue
                result[original_term] = (llm_term, None, None)
                logger.info(f"[LOOKUP_ZH] No match, keeping LLM result: '{original_term}' -> '{llm_term}'")
            except Exception as e:
                logger.error(f"[LOOKUP_ZH] Lookup failed for '{llm_term}': {e}")
                result[original_term] = (llm_term, None, None)
        logger.info(f"[LOOKUP_ZH] Lookup completed: {len(result)} results")
        return result

    def _lookup_standardized_terms_en(self, term_mapping: Dict[str, str]) -> Dict[str, Tuple[str, Optional[str], Optional[str]]]:
        logger.info(f"[LOOKUP_EN] Looking up {len(term_mapping)} terms in UMLS")
        if not self.umls_client:
            logger.warning("[LOOKUP_EN] UMLS client not available, returning empty dict")
            return {}
        result = {}
        for original_term, llm_term in term_mapping.items():
            try:
                search_result = self.umls_client.search_term(llm_term, language="ENG")
                if search_result.candidates:
                    preferred_candidates = [c for c in search_result.candidates if c.preferred]
                    if preferred_candidates:
                        best = max(preferred_candidates, key=lambda c: c.score)
                    else:
                        best = max(search_result.candidates, key=lambda c: c.score)
                    result[original_term] = (best.term, best.cui, None)
                    logger.info(f"[LOOKUP_EN] Match: '{original_term}' -> LLM:'{llm_term}' -> '{best.term}' (CUI: {best.cui}, score: {best.score:.2f})")
                    continue
                result[original_term] = (llm_term, None, None)
                logger.info(f"[LOOKUP_EN] No match, keeping LLM result: '{original_term}' -> '{llm_term}'")
            except Exception as e:
                logger.error(f"[LOOKUP_EN] Lookup failed for '{llm_term}': {e}")
                result[original_term] = (llm_term, None, None)
        logger.info(f"[LOOKUP_EN] Lookup completed: {len(result)} results")
        return result

    def normalize_draft_terms(self, text: str) -> Tuple[Dict[str, str], int, int, int]:
        """
        术语规范化

        Returns:
            Tuple[replacement_map, llm_call_count, char_count, token_count]
        """
        logger.info(f"[NORM_DRAFT] Starting draft term normalization, text length: {len(text)}")
        start_time = time.time()
        total_llm_calls = 0
        total_chars = 0
        total_tokens = 0

        terms, extract_calls, extract_chars, extract_tokens = self._extract_medical_terms_with_llm(text)
        total_llm_calls += extract_calls
        total_chars += extract_chars
        total_tokens += extract_tokens
        if not terms:
            logger.info("[NORM_DRAFT] No terms extracted, returning empty dict")
            return {}, total_llm_calls, total_chars, total_tokens
        logger.info(f"[NORM_DRAFT] Extracted {len(terms)} medical terms: {terms}")

        pre_matched = {}
        terms_needing_llm = []
        if self.language == "zh" and self.chinese_term_client:
            for term in terms:
                try:
                    exact_result = self.chinese_term_client.search_term(term=term, use_fuzzy=False)
                    if exact_result and exact_result.confidence >= 0.9:
                        if term != exact_result.matched_term:
                            pre_matched[term] = exact_result.matched_term
                            logger.info(f"[NORM_DRAFT] Pre-check exact match: '{term}' -> '{exact_result.matched_term}' (skip LLM)")
                        continue
                except Exception as e:
                    logger.debug(f"[NORM_DRAFT] Pre-check failed for '{term}': {e}")
                terms_needing_llm.append(term)
        elif self.language != "zh" and self.umls_client:
            for term in terms:
                try:
                    search_result = self.umls_client.search_term(term, language="ENG")
                    if search_result.candidates:
                        best = search_result.candidates[0]
                        if best.score >= 0.9:
                            if term != best.term:
                                pre_matched[term] = best.term
                                logger.info(f"[NORM_DRAFT] Pre-check UMLS match: '{term}' -> '{best.term}' (skip LLM)")
                            continue
                except Exception as e:
                    logger.debug(f"[NORM_DRAFT] Pre-check UMLS failed for '{term}': {e}")
                terms_needing_llm.append(term)
        else:
            terms_needing_llm = list(terms)

        if pre_matched:
            logger.info(f"[NORM_DRAFT] Pre-check matched {len(pre_matched)} terms, {len(terms_needing_llm)} terms need LLM")

        llm_result = {}
        if terms_needing_llm:
            term_mapping, std_calls, std_chars, std_tokens = self._llm_standardize_terms(terms_needing_llm)
            total_llm_calls += std_calls
            total_chars += std_chars
            total_tokens += std_tokens
            if term_mapping:
                if self.language == "zh":
                    lookup_result = self._lookup_standardized_terms_zh(term_mapping)
                else:
                    lookup_result = self._lookup_standardized_terms_en(term_mapping)
                for original_term, (final_term, _, _) in lookup_result.items():
                    if original_term != final_term:
                        llm_result[original_term] = final_term
            else:
                logger.warning("[NORM_DRAFT] LLM standardization failed for remaining terms")

        replacement_map = {**pre_matched, **llm_result}
        elapsed = time.time() - start_time
        logger.info(f"[NORM_DRAFT] Completed: extracted={len(terms)}, pre_matched={len(pre_matched)}, llm_processed={len(terms_needing_llm)}, replacements={len(replacement_map)}, llm_calls={total_llm_calls}, chars={total_chars}, tokens={total_tokens}, elapsed={elapsed:.2f}s")
        return replacement_map, total_llm_calls, total_chars, total_tokens

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

            # 关闭thinking模式：批量选择是简单匹配任务
            response = self.llm_service.generate(prompt, max_tokens=4000, thinking_enabled=False)

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
        并行版本的术语提取和规范化（已修复语言分流）
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
        is_zh = self.language == "zh"

        translations = {}
        if is_zh and self.translation_service:
            trans_start = time.time()
            translations = self.translation_service.batch_translate_zh_to_en(terms)
            logger.info(f"批量翻译完成，耗时: {time.time() - trans_start:.2f}秒")

        umls_results = {}
        if not is_zh and self.async_umls_client:
            search_start = time.time()
            search_terms = [translations.get(term, term) for term in terms]
            umls_results = await self.async_umls_client.batch_search(
                search_terms,
                language="ENG"
            )
            logger.info(f"并行UMLS检索完成，耗时: {time.time() - search_start:.2f}秒")

        chinese_results = {}
        if is_zh and self.chinese_term_client:
            chinese_start = time.time()
            chinese_results = self.chinese_term_client.batch_search(terms)
            matched_count = sum(1 for r in chinese_results.values() if r is not None)
            logger.info(f"中文术语批量搜索完成: {matched_count}/{len(terms)} 匹配, 耗时: {time.time() - chinese_start:.2f}秒")

        term_candidates = {}
        if not is_zh:
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

            if is_zh and term in chinese_results and chinese_results[term]:
                zh_result = chinese_results[term]
                normalized = zh_result.matched_term
                confidence = zh_result.confidence
                code = zh_result.code
                code_system = zh_result.code_system
                source = "ChineseTerm"
                reasoning = f"中文术语库匹配: {term} -> {zh_result.matched_term} (confidence: {zh_result.confidence:.2f})"
                if zh_result.candidates:
                    candidates_data = [
                        {"term": c.term, "code": c.code, "code_system": c.code_system,
                         "term_type": c.term_type, "source": c.source}
                        for c in zh_result.candidates[:5]
                    ]
                logger.info(f"ChineseTerm批量匹配: '{term}' -> '{normalized}' (confidence: {confidence:.2f})")

            elif not is_zh and term in selections:
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
                    logger.info(f"LLM兜底规范化: '{term}' -> '{normalized}' (confidence: {confidence:.2f})")

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
