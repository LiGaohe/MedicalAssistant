from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class ChineseTerm:
    """中文术语数据模型"""
    term: str
    code: Optional[str] = None
    code_system: Optional[str] = None
    term_type: str = "unknown"
    synonyms: List[str] = field(default_factory=list)
    source: str = "unknown"

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "term": self.term,
            "code": self.code,
            "code_system": self.code_system,
            "term_type": self.term_type,
            "synonyms": self.synonyms,
            "source": self.source
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChineseTerm":
        """从字典创建实例"""
        return cls(
            term=data.get("term", ""),
            code=data.get("code"),
            code_system=data.get("code_system"),
            term_type=data.get("term_type", "unknown"),
            synonyms=data.get("synonyms", []),
            source=data.get("source", "unknown")
        )


@dataclass
class ChineseSearchResult:
    """中文术语搜索结果"""
    original_term: str
    matched_term: str
    confidence: float
    code: Optional[str] = None
    code_system: Optional[str] = None
    term_type: str = "unknown"
    source: str = "unknown"
    match_type: str = "exact"
    candidates: List[ChineseTerm] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "original_term": self.original_term,
            "matched_term": self.matched_term,
            "confidence": self.confidence,
            "code": self.code,
            "code_system": self.code_system,
            "term_type": self.term_type,
            "source": self.source,
            "match_type": self.match_type,
            "candidates": [c.to_dict() for c in self.candidates]
        }
