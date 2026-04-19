from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class UMLSCandidate:
    term: str
    cui: str
    semantic_types: List[str] = field(default_factory=list)
    preferred: bool = False
    score: float = 0.0


@dataclass
class UMLSConcept:
    cui: str
    name: str
    semantic_types: List[str] = field(default_factory=list)
    definitions: List[str] = field(default_factory=list)
    atoms: List[dict] = field(default_factory=list)
    relations: List[dict] = field(default_factory=list)


@dataclass
class UMLSSearchResult:
    query: str
    candidates: List[UMLSCandidate] = field(default_factory=list)
    total_count: int = 0
    source: str = "UMLS"
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None
