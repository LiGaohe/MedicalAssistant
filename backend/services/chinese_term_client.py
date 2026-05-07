from typing import List, Dict, Optional
from ..models.chinese_term import ChineseTerm, ChineseSearchResult
from .chinese_term_indexer import ChineseTermIndexer
from .fuzzy_matcher import FuzzyMatcher
from ..utils.logger import logger


class ChineseTermClient:
    """中文术语搜索客户端"""

    def __init__(
        self,
        indexer: ChineseTermIndexer,
        fuzzy_threshold: float = 0.7,
        exact_match_bonus: float = 0.2
    ):
        """
        初始化中文术语搜索客户端

        Args:
            indexer: 术语索引器
            fuzzy_threshold: 模糊匹配阈值
            exact_match_bonus: 精确匹配的额外加分
        """
        self.indexer = indexer
        self.fuzzy_matcher = FuzzyMatcher(threshold=fuzzy_threshold)
        self.exact_match_bonus = exact_match_bonus

        logger.info(f"ChineseTermClient initialized (threshold: {fuzzy_threshold}, bonus: {exact_match_bonus})")

    def search_term(
        self,
        term: str,
        term_type: Optional[str] = None,
        use_fuzzy: bool = True
    ) -> Optional[ChineseSearchResult]:
        """
        搜索中文术语

        Args:
            term: 待搜索的术语
            term_type: 术语类型过滤（symptom/diagnosis等）
            use_fuzzy: 是否使用模糊匹配

        Returns:
            搜索结果，如果没有匹配则返回None
        """
        if not term:
            return None

        logger.debug(f"Searching term: '{term}' (type: {term_type}, fuzzy: {use_fuzzy})")

        exact_term = self.indexer.get_term(term)
        if exact_term:
            if term_type is None or exact_term.term_type == term_type:
                confidence = 1.0 + self.exact_match_bonus
                confidence = min(confidence, 1.0)

                logger.info(f"Exact match found: '{term}' -> '{exact_term.term}' (confidence: {confidence:.2f})")

                return ChineseSearchResult(
                    original_term=term,
                    matched_term=exact_term.term,
                    confidence=confidence,
                    code=exact_term.code,
                    code_system=exact_term.code_system,
                    term_type=exact_term.term_type,
                    source=exact_term.source,
                    match_type="exact",
                    candidates=[exact_term]
                )

        if term in self.indexer.colloquial_synonyms:
            synonyms = self.indexer.colloquial_synonyms[term]
            logger.debug(f"Found colloquial synonym mapping: '{term}' -> {synonyms}")

            for synonym in synonyms:
                synonym_term = self.indexer.get_term(synonym)
                if synonym_term:
                    if term_type is None or synonym_term.term_type == term_type:
                        confidence = 0.95

                        logger.info(f"Colloquial synonym match: '{term}' -> '{synonym_term.term}' (confidence: {confidence:.2f})")

                        return ChineseSearchResult(
                            original_term=term,
                            matched_term=synonym_term.term,
                            confidence=confidence,
                            code=synonym_term.code,
                            code_system=synonym_term.code_system,
                            term_type=synonym_term.term_type,
                            source=synonym_term.source,
                            match_type="synonym",
                            candidates=[synonym_term]
                        )

        if not use_fuzzy:
            logger.debug(f"No exact match found and fuzzy search disabled for '{term}'")
            return None

        candidates = self.indexer.search(term, term_type=term_type)

        if not candidates:
            logger.debug(f"No candidates found for '{term}'")
            return None

        candidate_terms = [c.term for c in candidates]

        best_match = self.fuzzy_matcher.find_best_match(term, candidate_terms)

        if not best_match:
            logger.debug(f"No fuzzy match above threshold for '{term}'")
            return None

        matched_term_text, similarity = best_match
        matched_term_obj = self.indexer.get_term(matched_term_text)

        if not matched_term_obj:
            logger.warning(f"Matched term '{matched_term_text}' not found in index")
            return None

        top_matches = self.fuzzy_matcher.find_top_matches(term, candidate_terms, top_n=5)
        candidate_list = []
        for matched_text, score in top_matches:
            candidate_obj = self.indexer.get_term(matched_text)
            if candidate_obj:
                candidate_list.append(candidate_obj)

        logger.info(f"Fuzzy match found: '{term}' -> '{matched_term_text}' (similarity: {similarity:.2f})")

        return ChineseSearchResult(
            original_term=term,
            matched_term=matched_term_text,
            confidence=similarity,
            code=matched_term_obj.code,
            code_system=matched_term_obj.code_system,
            term_type=matched_term_obj.term_type,
            source=matched_term_obj.source,
            match_type="fuzzy",
            candidates=candidate_list
        )

    def batch_search(
        self,
        terms: List[str],
        term_type: Optional[str] = None,
        use_fuzzy: bool = True
    ) -> Dict[str, Optional[ChineseSearchResult]]:
        """
        批量搜索术语

        Args:
            terms: 术语列表
            term_type: 术语类型过滤
            use_fuzzy: 是否使用模糊匹配

        Returns:
            术语到搜索结果的映射
        """
        if not terms:
            return {}

        logger.info(f"Batch searching {len(terms)} terms")

        results = {}
        for term in terms:
            results[term] = self.search_term(term, term_type=term_type, use_fuzzy=use_fuzzy)

        matched_count = sum(1 for r in results.values() if r is not None)
        logger.info(f"Batch search completed: {matched_count}/{len(terms)} terms matched")

        return results

    def get_stats(self) -> Dict[str, int]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        return self.indexer.get_stats()

    def is_available(self) -> bool:
        """
        检查客户端是否可用

        Returns:
            是否可用
        """
        stats = self.indexer.get_stats()
        return stats["total_terms"] > 0
