from typing import List, Tuple, Optional
from difflib import SequenceMatcher
from ..utils.logger import logger


class FuzzyMatcher:
    """模糊匹配器，用于中文术语的相似度计算和匹配"""

    def __init__(self, threshold: float = 0.7):
        """
        初始化模糊匹配器

        Args:
            threshold: 相似度阈值，默认0.7
        """
        self.threshold = threshold
        logger.info(f"FuzzyMatcher initialized with threshold: {threshold}")

    def calculate_similarity(self, term1: str, term2: str) -> float:
        """
        计算两个术语的相似度

        使用SequenceMatcher算法计算相似度，适用于中文字符串

        Args:
            term1: 第一个术语
            term2: 第二个术语

        Returns:
            相似度分数，范围[0, 1]
        """
        if not term1 or not term2:
            return 0.0

        if term1 == term2:
            return 1.0

        similarity = SequenceMatcher(None, term1, term2).ratio()

        if len(term1) != len(term2):
            shorter = min(len(term1), len(term2))
            longer = max(len(term1), len(term2))
            length_penalty = shorter / longer
            similarity = similarity * (0.7 + 0.3 * length_penalty)

        return similarity

    def calculate_jaccard_similarity(self, term1: str, term2: str) -> float:
        """
        计算Jaccard相似度

        适用于部分匹配场景

        Args:
            term1: 第一个术语
            term2: 第二个术语

        Returns:
            Jaccard相似度分数，范围[0, 1]
        """
        if not term1 or not term2:
            return 0.0

        set1 = set(term1)
        set2 = set(term2)

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 0.0

        return intersection / union

    def calculate_levenshtein_distance(self, term1: str, term2: str) -> int:
        """
        计算编辑距离（Levenshtein距离）

        Args:
            term1: 第一个术语
            term2: 第二个术语

        Returns:
            编辑距离
        """
        if len(term1) < len(term2):
            return self.calculate_levenshtein_distance(term2, term1)

        if len(term2) == 0:
            return len(term1)

        previous_row = range(len(term2) + 1)

        for i, c1 in enumerate(term1):
            current_row = [i + 1]
            for j, c2 in enumerate(term2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def calculate_levenshtein_similarity(self, term1: str, term2: str) -> float:
        """
        基于编辑距离计算相似度

        Args:
            term1: 第一个术语
            term2: 第二个术语

        Returns:
            相似度分数，范围[0, 1]
        """
        if not term1 or not term2:
            return 0.0

        if term1 == term2:
            return 1.0

        distance = self.calculate_levenshtein_distance(term1, term2)
        max_len = max(len(term1), len(term2))

        return 1.0 - (distance / max_len)

    def find_best_match(
        self,
        query: str,
        candidates: List[str],
        use_multiple_algorithms: bool = True
    ) -> Optional[Tuple[str, float]]:
        """
        从候选列表中找到最佳匹配

        Args:
            query: 查询术语
            candidates: 候选术语列表
            use_multiple_algorithms: 是否使用多种算法综合评分

        Returns:
            最佳匹配的术语和相似度分数，如果没有匹配则返回None
        """
        if not query or not candidates:
            return None

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            if use_multiple_algorithms:
                score1 = self.calculate_similarity(query, candidate)
                score2 = self.calculate_jaccard_similarity(query, candidate)
                score3 = self.calculate_levenshtein_similarity(query, candidate)

                score = (score1 * 0.5 + score2 * 0.3 + score3 * 0.2)
            else:
                score = self.calculate_similarity(query, candidate)

            if score > best_score:
                best_score = score
                best_match = candidate

        if best_score >= self.threshold:
            logger.debug(f"Best match for '{query}': '{best_match}' (score: {best_score:.3f})")
            return (best_match, best_score)

        logger.debug(f"No match found for '{query}' above threshold {self.threshold}")
        return None

    def find_top_matches(
        self,
        query: str,
        candidates: List[str],
        top_n: int = 5,
        use_multiple_algorithms: bool = True
    ) -> List[Tuple[str, float]]:
        """
        找到前N个最佳匹配

        Args:
            query: 查询术语
            candidates: 候选术语列表
            top_n: 返回的匹配数量
            use_multiple_algorithms: 是否使用多种算法综合评分

        Returns:
            匹配结果列表，每个元素为(术语, 相似度)元组
        """
        if not query or not candidates:
            return []

        matches = []

        for candidate in candidates:
            if use_multiple_algorithms:
                score1 = self.calculate_similarity(query, candidate)
                score2 = self.calculate_jaccard_similarity(query, candidate)
                score3 = self.calculate_levenshtein_similarity(query, candidate)

                score = (score1 * 0.5 + score2 * 0.3 + score3 * 0.2)
            else:
                score = self.calculate_similarity(query, candidate)

            if score >= self.threshold:
                matches.append((candidate, score))

        matches.sort(key=lambda x: x[1], reverse=True)

        top_matches = matches[:top_n]

        if top_matches:
            logger.debug(f"Found {len(top_matches)} matches for '{query}'")

        return top_matches

    def contains_match(self, query: str, candidate: str) -> Tuple[bool, float]:
        """
        检查查询术语是否包含在候选术语中，或候选术语是否包含查询术语

        Args:
            query: 查询术语
            candidate: 候选术语

        Returns:
            (是否匹配, 相似度分数)
        """
        if not query or not candidate:
            return (False, 0.0)

        if query == candidate:
            return (True, 1.0)

        if query in candidate:
            ratio = len(query) / len(candidate)
            return (True, 0.8 + 0.2 * ratio)

        if candidate in query:
            ratio = len(candidate) / len(query)
            return (True, 0.8 + 0.2 * ratio)

        return (False, 0.0)
