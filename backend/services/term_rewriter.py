import json
import re
from typing import List, Dict, Optional
from .llm.llm_service import LLMService
from ..config import settings
from ..utils.logger import logger


MULTI_CONCEPT_PATTERNS = [
    re.compile(r'[和与及兼合伴併\+、]'),
    re.compile(r'(左右|双侧|双|两侧|双下肢|双上肢)([^\s和与及]+)'),
]


class TermRewriter:
    def __init__(self, llm_service: Optional[LLMService] = None, language: str = "zh"):
        self.llm_service = llm_service
        self.language = language
        logger.info(f"TermRewriter initialized, language={language}, llm={'available' if llm_service else 'unavailable'}")

    def detect_multi_concept(self, mention: str) -> bool:
        if not settings.ENABLE_MULTI_CONCEPT_DECOMPOSE:
            return False
        for pattern in MULTI_CONCEPT_PATTERNS:
            if pattern.search(mention):
                logger.debug(f"Multi-concept detected in mention: '{mention}'")
                return True
        return False

    def rewrite_colloquial(
        self,
        mention: str,
        concept_type: str = "unknown",
        context: str = ""
    ) -> List[str]:
        if not self.llm_service:
            logger.warning("LLM service not available for rewrite, returning original mention")
            return [mention]

        try:
            logger.info(f"Rewriting colloquial mention: '{mention}' (type: {concept_type})")

            max_phrasings = settings.REWRITE_MAX_PHRASINGS

            prompt = self._build_rewrite_prompt(mention, concept_type, context, max_phrasings)
            response = self.llm_service.generate(prompt, max_tokens=4000)

            rewrites = self._parse_rewrite_response(response.text.strip(), mention, max_phrasings)
            logger.info(f"Rewrite '{mention}' -> {rewrites}")
            return rewrites

        except Exception as e:
            logger.error(f"Rewrite failed for '{mention}': {e}")
            return [mention]

    def decompose_multi_concept(
        self,
        mention: str,
        concept_type: str = "unknown",
        context: str = ""
    ) -> List[str]:
        if not self.llm_service:
            logger.warning("LLM service not available for decomposition, returning original mention")
            return [mention]

        try:
            logger.info(f"Decomposing multi-concept mention: '{mention}' (type: {concept_type})")

            prompt = self._build_decompose_prompt(mention, concept_type, context)
            response = self.llm_service.generate(prompt, max_tokens=4000)

            atomic_mentions = self._parse_decompose_response(response.text.strip(), mention)
            logger.info(f"Decompose '{mention}' -> {atomic_mentions}")
            return atomic_mentions

        except Exception as e:
            logger.error(f"Decompose failed for '{mention}': {e}")
            return [mention]

    def generate_alternative_phrasings(
        self,
        mention: str,
        concept_type: str = "unknown",
        context: str = ""
    ) -> List[str]:
        if not self.llm_service:
            logger.warning("LLM service not available for alternative phrasing")
            return []

        try:
            logger.info(f"Generating alternative phrasings for: '{mention}' (type: {concept_type})")

            max_count = settings.ALT_PHRASING_MAX_COUNT

            prompt = self._build_alt_phrasing_prompt(mention, concept_type, context, max_count)
            response = self.llm_service.generate(prompt, max_tokens=2000)

            alternatives = self._parse_alt_phrasing_response(response.text.strip(), max_count)
            logger.info(f"Alternative phrasings for '{mention}': {alternatives}")
            return alternatives

        except Exception as e:
            logger.error(f"Alternative phrasing failed for '{mention}': {e}")
            return []

    def batch_rewrite_colloquial(
        self,
        mentions: List[Dict[str, str]],
        max_phrasings_per_term: int = 2
    ) -> Dict[str, List[str]]:
        """
        批量重写口语化术语，减少LLM调用次数
        
        Args:
            mentions: [{"term": "脖子处淋巴结肿大", "type": "symptom"}, ...]
            max_phrasings_per_term: 每个术语最多返回的变体数量
        
        Returns:
            {"脖子处淋巴结肿大": ["颈部淋巴结肿大"], ...}
        """
        if not self.llm_service:
            logger.warning("LLM service not available for batch rewrite")
            return {m["term"]: [m["term"]] for m in mentions}
        
        if not mentions:
            return {}
        
        try:
            logger.info(f"Batch rewriting {len(mentions)} colloquial mentions")
            
            prompt = self._build_batch_rewrite_prompt(mentions, max_phrasings_per_term)
            response = self.llm_service.generate(prompt, max_tokens=8000)
            
            results = self._parse_batch_rewrite_response(response.text.strip(), mentions, max_phrasings_per_term)
            logger.info(f"Batch rewrite completed: {len(results)} terms processed")
            return results
            
        except Exception as e:
            logger.error(f"Batch rewrite failed: {e}")
            return {m["term"]: [m["term"]] for m in mentions}

    def _build_batch_rewrite_prompt(
        self, 
        mentions: List[Dict[str, str]], 
        max_phrasings: int
    ) -> str:
        if self.language == "zh":
            terms_section = ""
            for i, m in enumerate(mentions, 1):
                term = m.get("term", "")
                term_type = m.get("type", "unknown")
                type_guidance = self._get_type_guidance(term_type)
                terms_section += f"\n【术语{i}】{term} (类型: {term_type})"
                if type_guidance:
                    terms_section += f"\n  {type_guidance}"
            
            return f"""你是医学术语规范化助手。

任务：
批量改写以下医学口语表达，使其更接近临床书写、更适合术语库检索。

要求：
1. 只改写给定的术语，保留原始语义
2. 不要把症状升级成明确诊断
3. 如果术语已经足够规范，原样返回
4. 每个术语最多给出{max_phrasings}个改写变体
5. 如果不需要改写，原样返回即可

术语列表：
{terms_section}

输出格式（JSON）：
{{
  "术语原文1": ["改写1", "改写2"],
  "术语原文2": ["改写1"],
  ...
}}

注意：只输出JSON，不要输出其他内容。如果术语无需改写，数组中只包含原术语。"""
        else:
            terms_section = ""
            for i, m in enumerate(mentions, 1):
                term = m.get("term", "")
                term_type = m.get("type", "unknown")
                type_guidance = self._get_type_guidance(term_type)
                terms_section += f"\n[Term {i}] {term} (type: {term_type})"
                if type_guidance:
                    terms_section += f"\n  {type_guidance}"
            
            return f"""You are a medical terminology normalization assistant.

Task:
Batch rewrite the following colloquial medical expressions into clinical-writing style expressions more suitable for terminology database retrieval.

Requirements:
1. Only rewrite the given terms, preserve original semantics
2. Do not upgrade symptoms to definitive diagnoses
3. If a term is already sufficiently standardized, return it as-is
4. Maximum {max_phrasings} rewrite variants per term
5. If no rewrite needed, return the original term

Term list:
{terms_section}

Output format (JSON):
{{
  "original_term_1": ["rewrite_1", "rewrite_2"],
  "original_term_2": ["rewrite_1"],
  ...
}}

Note: Only output JSON, no other content. If a term needs no rewrite, the array contains only the original term."""

    def _parse_batch_rewrite_response(
        self, 
        text: str, 
        mentions: List[Dict[str, str]], 
        max_count: int
    ) -> Dict[str, List[str]]:
        import json
        
        results = {}
        
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                
                for m in mentions:
                    term = m.get("term", "")
                    if term in parsed:
                        rewrites = parsed[term]
                        if isinstance(rewrites, list):
                            valid_rewrites = []
                            for r in rewrites:
                                if isinstance(r, str) and r.strip():
                                    valid_rewrites.append(r.strip())
                            if valid_rewrites:
                                results[term] = valid_rewrites[:max_count]
                            else:
                                results[term] = [term]
                        elif isinstance(rewrites, str):
                            results[term] = [rewrites.strip()] if rewrites.strip() else [term]
                        else:
                            results[term] = [term]
                    else:
                        results[term] = [term]
                
                logger.debug(f"Parsed batch rewrite results: {len(results)} terms")
                return results
                
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse batch rewrite JSON: {e}")
        
        for m in mentions:
            term = m.get("term", "")
            results[term] = [term]
        
        return results

    def _build_rewrite_prompt(
        self, mention: str, concept_type: str, context: str, max_phrasings: int
    ) -> str:
        type_guidance = self._get_type_guidance(concept_type)

        if self.language == "zh":
            return f"""你是医学术语规范化助手。

任务：
把给定的医学口语表达改写成更接近临床书写、且更适合术语库检索的表达。

要求：
1. 只改写给定mention，不要总结整段上下文。
2. 保留原始语义，不要把症状升级成明确诊断。
3. 如果原文只是患者主观描述，就输出症状或检查需求，不要补疾病名。
4. 如果mention已经足够规范，直接原样返回。
5. 最多给出{max_phrasings}个rewrite，按最保守到最适合检索排序。
6. 不要输出编码，不要输出解释性长句。

{type_guidance}

输入：
- mention: {mention}
- concept_type: {concept_type}
- context: {context}

输出格式（每行一个变体）：
rewrite_1: <改写结果>
rewrite_2: <改写结果>
rewrite_3: <改写结果>

如果不需要改写，只输出一行：
rewrite_1: {mention}"""
        else:
            return f"""You are a medical terminology normalization assistant.

Task:
Rewrite the given colloquial medical expression into a clinical-writing style expression more suitable for terminology database retrieval.

Requirements:
1. Only rewrite the given mention, do not summarize the entire context.
2. Preserve original semantics, do not upgrade symptoms to definitive diagnoses.
3. If the original is only a patient subjective description, output symptoms or examination needs, do not add disease names.
4. If the mention is already sufficiently standardized, return it as-is.
5. Maximum {max_phrasings} rewrites, sorted from most conservative to most search-friendly.
6. Do not output codes or explanatory long sentences.

{type_guidance}

Input:
- mention: {mention}
- concept_type: {concept_type}
- context: {context}

Output format (one variant per line):
rewrite_1: <rewrite result>
rewrite_2: <rewrite result>
rewrite_3: <rewrite result>

If no rewrite needed, output only one line:
rewrite_1: {mention}"""

    def _build_decompose_prompt(
        self, mention: str, concept_type: str, context: str
    ) -> str:
        type_guidance = self._get_type_guidance(concept_type)

        if self.language == "zh":
            return f"""你是医学术语拆解助手。

任务：
判断这个mention是否包含多个独立医学概念。如果包含，请拆成多个最小可检索的atomic mentions。

要求：
1. 若只有一个概念，返回原mention即可。
2. 若多个概念共享部位或修饰词，请把共享信息补到每个atomic mention中。
3. 不要凭常识添加新概念。
4. 每个atomic mention都必须能独立用于术语库检索。
5. 输出不要超过5个atomic mentions。

{type_guidance}

输入：
- mention: {mention}
- concept_type: {concept_type}
- context: {context}

输出格式（每行一个）：
atomic_1: <原子mention>
atomic_2: <原子mention>

如果只有一个概念，只输出一行：
atomic_1: {mention}"""
        else:
            return f"""You are a medical term decomposition assistant.

Task:
Determine if this mention contains multiple independent medical concepts. If so, decompose into minimal searchable atomic mentions.

Requirements:
1. If only one concept, return the original mention.
2. If multiple concepts share a body part or modifier, supplement the shared info into each atomic mention.
3. Do not add new concepts based on common sense.
4. Each atomic mention must be independently usable for terminology database retrieval.
5. Output no more than 5 atomic mentions.

{type_guidance}

Input:
- mention: {mention}
- concept_type: {concept_type}
- context: {context}

Output format (one per line):
atomic_1: <atomic mention>
atomic_2: <atomic mention>

If only one concept, output only one line:
atomic_1: {mention}"""

    def _build_alt_phrasing_prompt(
        self, mention: str, concept_type: str, context: str, max_count: int
    ) -> str:
        if self.language == "zh":
            return f"""你是术语检索扩写助手。

任务：
给定一个医学mention，生成少量与原意等价但更可能命中标准术语库的表达。

要求：
1. 只生成等价表达，不要扩大语义范围。
2. 最多生成{max_count}个alternate phrasings。
3. 若没有更好的表达，返回 NONE。
4. 不要输出编码。

输入：
- mention: {mention}
- concept_type: {concept_type}
- context: {context}

输出格式（每行一个，没有则输出NONE）：
alternative_1: <备选表达>
alternative_2: <备选表达>"""
        else:
            return f"""You are a terminology retrieval expansion assistant.

Task:
Given a medical mention, generate a few equivalent expressions that are more likely to match standard terminology databases.

Requirements:
1. Only generate equivalent expressions, do not broaden semantic scope.
2. Maximum {max_count} alternate phrasings.
3. If no better expression exists, return NONE.
4. Do not output codes.

Input:
- mention: {mention}
- concept_type: {concept_type}
- context: {context}

Output format (one per line, output NONE if none):
alternative_1: <alternative expression>
alternative_2: <alternative expression>"""

    def _get_type_guidance(self, concept_type: str) -> str:
        if self.language == "zh":
            guides = {
                "symptom": "【类型提示】这是症状类术语。改写时：保留症状属性，补全部位和性质；不要把症状升级为疾病诊断。",
                "diagnosis": "【类型提示】这是诊断类术语。改写时：优先拆解并列和省略表达；避免把症状表述升级为疾病。",
                "examination": "【类型提示】这是检查类术语。改写时：统一俗称与正式检查名称；明确检查方式和部位；区分影像、检验、内镜类型。",
                "treatment": "【类型提示】这是治疗类术语。改写时：统一俗称与规范术式名称；明确操作类型和部位。",
            }
        else:
            guides = {
                "symptom": "[Type Hint] This is a symptom term. When rewriting: preserve symptom attributes, supplement body part and quality; do not upgrade symptoms to disease diagnoses.",
                "diagnosis": "[Type Hint] This is a diagnosis term. When rewriting: prioritize decomposing parallel/abbreviated expressions; avoid upgrading symptom descriptions to diseases.",
                "examination": "[Type Hint] This is an examination term. When rewriting: unify colloquial names with formal examination names; clarify examination method and body part; distinguish imaging/lab/endoscopy types.",
                "treatment": "[Type Hint] This is a treatment term. When rewriting: unify colloquial names with standard procedure names; clarify procedure type and body part.",
            }
        return guides.get(concept_type, "")

    def _parse_rewrite_response(self, text: str, original: str, max_count: int) -> List[str]:
        lines = text.strip().split('\n')
        rewrites = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'(?:rewrite_\d+|rewrite)\s*[:：]\s*(.+)', line, re.IGNORECASE)
            if match:
                value = match.group(1).strip().strip('"').strip("'")
                if value and value not in rewrites:
                    rewrites.append(value)

        if not rewrites:
            logger.debug(f"No rewrite variants parsed from response, using original: '{original}'")
            return [original]

        return rewrites[:max_count]

    def _parse_decompose_response(self, text: str, original: str) -> List[str]:
        lines = text.strip().split('\n')
        atomic_mentions = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'(?:atomic_\d+|atomic)\s*[:：]\s*(.+)', line, re.IGNORECASE)
            if match:
                value = match.group(1).strip().strip('"').strip("'")
                if value and value not in atomic_mentions:
                    atomic_mentions.append(value)

        if not atomic_mentions:
            logger.debug(f"No atomic mentions parsed from response, using original: '{original}'")
            return [original]

        return atomic_mentions[:5]

    def _parse_alt_phrasing_response(self, text: str, max_count: int) -> List[str]:
        first_line = text.split('\n')[0].strip().upper()
        if first_line == "NONE" or "NONE" in first_line:
            logger.debug("Alternative phrasing returned NONE")
            return []

        lines = text.strip().split('\n')
        alternatives = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            match = re.match(r'(?:alternative_\d+|alternative)\s*[:：]\s*(.+)', line, re.IGNORECASE)
            if match:
                value = match.group(1).strip().strip('"').strip("'")
                if value and value not in alternatives:
                    alternatives.append(value)

        return alternatives[:max_count]


class ConstrainedTermSelector:
    def __init__(self, llm_service: Optional[LLMService] = None, language: str = "zh"):
        self.llm_service = llm_service
        self.language = language
        logger.info(f"ConstrainedTermSelector initialized, language={language}")

    def select_from_candidates(
        self,
        mention: str,
        concept_type: str,
        candidates: List[Dict],
        context: str = ""
    ) -> Optional[Dict]:
        if not self.llm_service:
            logger.warning("LLM service not available for constrained selection")
            if candidates:
                logger.info(f"No LLM, selecting first candidate for '{mention}'")
                return candidates[0]
            return None

        if not candidates:
            logger.debug(f"No candidates for constrained selection of '{mention}'")
            return None

        if len(candidates) == 1:
            logger.debug(f"Single candidate for '{mention}', auto-selecting")
            return candidates[0]

        try:
            logger.info(f"Constrained selection for '{mention}' from {len(candidates)} candidates")

            candidates_text = "\n".join([
                f"{i+1}. term={c.get('term', 'N/A')}, "
                f"type={c.get('term_type', c.get('source', 'N/A'))}, "
                f"code={c.get('code', c.get('cui', 'N/A'))}"
                for i, c in enumerate(candidates[:10])
            ])

            if self.language == "zh":
                prompt = f"""你是医学术语标准化助手。

任务：
在给定候选中选择与mention最匹配的标准术语。

要求：
1. 只能从候选列表中选择，不能输出列表外术语。
2. 优先保证概念类型正确，其次保证部位和核心语义匹配。
3. 如果原mention只是症状，不要选择明确疾病诊断。
4. 如果多个候选都接近，选择更保守、更贴近原文的术语。
5. 如果没有合适候选，输出unresolved。
6. 输出结果时只给出编号或unresolved，不要解释。

输入：
- mention: {mention}
- concept_type: {concept_type}
- context: {context}
- candidates:
{candidates_text}

输出格式（只输出编号或unresolved）：
selected: <编号或unresolved>"""
            else:
                prompt = f"""You are a medical terminology standardization assistant.

Task:
Select the standard term that best matches the mention from the given candidates.

Requirements:
1. Only select from the candidate list, do not output terms outside the list.
2. Prioritize correct concept type, then body part and core semantic match.
3. If the original mention is only a symptom, do not select a definitive disease diagnosis.
4. If multiple candidates are close, select the more conservative one closer to the original text.
5. If no suitable candidate, output unresolved.
6. Output only the number or unresolved, no explanation.

Input:
- mention: {mention}
- concept_type: {concept_type}
- context: {context}
- candidates:
{candidates_text}

Output format (only number or unresolved):
selected: <number or unresolved>"""

            response = self.llm_service.generate(prompt, max_tokens=100)
            text = response.text.strip()

            if text.upper() == "UNRESOLVED" or "unresolved" in text.lower():
                logger.info(f"Constrained selection: '{mention}' -> unresolved")
                return None

            match = re.search(r'(\d+)', text)
            if match:
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(candidates):
                    selected = candidates[idx]
                    logger.info(f"Constrained selection: '{mention}' -> {selected.get('term', 'N/A')} (idx={idx+1})")
                    return selected

            logger.warning(f"Could not parse selection response for '{mention}': {text[:100]}")
            return candidates[0]

        except Exception as e:
            logger.error(f"Constrained selection failed for '{mention}': {e}")
            return candidates[0] if candidates else None