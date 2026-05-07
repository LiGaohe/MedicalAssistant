import csv
import json
from typing import List, Dict, Optional, Set
from pathlib import Path
from ..models.chinese_term import ChineseTerm
from ..utils.logger import logger


class ChineseTermIndexer:
    """中文术语索引服务，负责加载和索引中文术语库"""

    def __init__(self):
        self.symptom_terms: Dict[str, ChineseTerm] = {}
        self.diagnosis_terms: Dict[str, ChineseTerm] = {}
        self.all_terms: Dict[str, ChineseTerm] = {}
        self.char_index: Dict[str, Set[str]] = {}
        self.colloquial_synonyms: Dict[str, List[str]] = {}
        self.term_count = 0

        logger.info("ChineseTermIndexer initialized")

    def load_symptom_norm(self, file_path: str) -> int:
        """
        加载IMCS标准症状库

        Args:
            file_path: symptom_norm.csv文件路径

        Returns:
            加载的术语数量
        """
        logger.info(f"Loading symptom norm from: {file_path}")

        if not Path(file_path).exists():
            logger.error(f"Symptom norm file not found: {file_path}")
            return 0

        count = 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row or not row[0].strip():
                        continue

                    term_text = row[0].strip()

                    if term_text == 'norm':
                        continue

                    term = ChineseTerm(
                        term=term_text,
                        term_type="symptom",
                        source="IMCS"
                    )

                    self.symptom_terms[term_text] = term
                    self.all_terms[term_text] = term
                    count += 1

            logger.info(f"Loaded {count} symptom terms from IMCS")
            return count

        except Exception as e:
            logger.error(f"Failed to load symptom norm: {e}")
            return 0

    def load_icd11_terms(self, file_path: str) -> int:
        """
        加载ICD-11中文术语库

        Args:
            file_path: ICD-11中文术语文件路径

        Returns:
            加载的术语数量
        """
        logger.info(f"Loading ICD-11 terms from: {file_path}")

        if not Path(file_path).exists():
            logger.error(f"ICD-11 file not found: {file_path}")
            return 0

        count = 0
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

                if not lines:
                    logger.warning("ICD-11 file is empty")
                    return 0

                header = lines[0].strip().split('\t')

                code_idx = None
                title_zh_idx = None
                class_kind_idx = None

                for i, col in enumerate(header):
                    col_clean = col.strip().lower()
                    if col_clean == 'code':
                        code_idx = i
                    elif col_clean == 'title':
                        title_zh_idx = i
                    elif col_clean == 'classkind':
                        class_kind_idx = i

                if title_zh_idx is None:
                    logger.warning("ICD-11 file missing Title column")
                    return 0

                logger.debug(f"ICD-11 column indices - Code: {code_idx}, Title: {title_zh_idx}, ClassKind: {class_kind_idx}")

                for line_num, line in enumerate(lines[1:], start=2):
                    line = line.strip()
                    if not line:
                        continue

                    parts = line.split('\t')

                    if len(parts) <= title_zh_idx:
                        continue

                    code = parts[code_idx].strip() if code_idx is not None and len(parts) > code_idx else None
                    title_zh = parts[title_zh_idx].strip()

                    if title_zh.startswith('"') and title_zh.endswith('"'):
                        title_zh = title_zh[1:-1]

                    if not title_zh:
                        continue

                    title_zh = title_zh.lstrip('- ').strip()

                    if not title_zh or len(title_zh) < 2:
                        continue

                    term_type = "diagnosis"
                    if class_kind_idx is not None and len(parts) > class_kind_idx:
                        class_kind = parts[class_kind_idx].strip().lower()
                        if class_kind == 'chapter':
                            term_type = "chapter"
                        elif class_kind == 'block':
                            term_type = "block"
                        elif class_kind == 'category':
                            term_type = "diagnosis"

                    if code:
                        code = code.strip()
                        if not code:
                            code = None

                    term = ChineseTerm(
                        term=title_zh,
                        code=code,
                        code_system="ICD-11" if code else None,
                        term_type=term_type,
                        source="ICD-11"
                    )

                    if title_zh not in self.all_terms:
                        self.diagnosis_terms[title_zh] = term
                        self.all_terms[title_zh] = term
                        count += 1

            logger.info(f"Loaded {count} ICD-11 terms")
            return count

        except Exception as e:
            logger.error(f"Failed to load ICD-11 terms: {e}")
            import traceback
            traceback.print_exc()
            return 0

    def load_colloquial_synonyms(self, file_path: str) -> int:
        """
        加载口语化术语同义词映射

        Args:
            file_path: 同义词映射文件路径

        Returns:
            加载的映射数量
        """
        logger.info(f"Loading colloquial synonyms from: {file_path}")

        if not Path(file_path).exists():
            logger.warning(f"Colloquial synonyms file not found: {file_path}")
            return 0

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.colloquial_synonyms = json.load(f)

            count = len(self.colloquial_synonyms)
            logger.info(f"Loaded {count} colloquial synonym mappings")
            return count

        except Exception as e:
            logger.error(f"Failed to load colloquial synonyms: {e}")
            return 0

    def build_index(self) -> int:
        """
        构建字符级倒排索引，用于快速检索

        Returns:
            索引的术语总数
        """
        logger.info("Building character-level inverted index...")

        self.char_index.clear()
        self.term_count = 0

        for term_text in self.all_terms.keys():
            for char in set(term_text):
                if char not in self.char_index:
                    self.char_index[char] = set()
                self.char_index[char].add(term_text)

            self.term_count += 1

        logger.info(f"Index built: {self.term_count} terms, {len(self.char_index)} unique characters")
        return self.term_count

    def search(
        self,
        query: str,
        term_type: Optional[str] = None,
        use_index: bool = True
    ) -> List[ChineseTerm]:
        """
        搜索术语

        Args:
            query: 查询术语
            term_type: 术语类型过滤（symptom/diagnosis等）
            use_index: 是否使用倒排索引加速

        Returns:
            匹配的术语列表
        """
        if not query:
            return []

        logger.debug(f"Searching for term: '{query}' (type: {term_type})")

        if query in self.all_terms:
            term = self.all_terms[query]
            if term_type is None or term.term_type == term_type:
                logger.debug(f"Exact match found: '{query}'")
                return [term]

        candidates = set()

        if use_index and self.char_index:
            for char in query:
                if char in self.char_index:
                    candidates.update(self.char_index[char])
        else:
            candidates = set(self.all_terms.keys())

        if term_type:
            if term_type == "symptom":
                candidates = candidates.intersection(set(self.symptom_terms.keys()))
            elif term_type == "diagnosis":
                candidates = candidates.intersection(set(self.diagnosis_terms.keys()))

        results = []
        for candidate_text in candidates:
            if query in candidate_text or candidate_text in query:
                results.append(self.all_terms[candidate_text])

        logger.debug(f"Found {len(results)} candidates for '{query}'")
        return results

    def get_term(self, term_text: str) -> Optional[ChineseTerm]:
        """
        获取指定术语

        Args:
            term_text: 术语文本

        Returns:
            术语对象，如果不存在则返回None
        """
        return self.all_terms.get(term_text)

    def get_stats(self) -> Dict[str, int]:
        """
        获取索引统计信息

        Returns:
            统计信息字典
        """
        return {
            "total_terms": len(self.all_terms),
            "symptom_terms": len(self.symptom_terms),
            "diagnosis_terms": len(self.diagnosis_terms),
            "indexed_characters": len(self.char_index),
            "colloquial_synonyms": len(self.colloquial_synonyms)
        }

    def clear(self):
        """清空索引"""
        self.symptom_terms.clear()
        self.diagnosis_terms.clear()
        self.all_terms.clear()
        self.char_index.clear()
        self.term_count = 0
        logger.info("Index cleared")
