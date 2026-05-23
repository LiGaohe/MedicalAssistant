from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from sqlalchemy.orm import Session


@dataclass
class PipelineContext:
    db: Optional[Session] = None
    llm_service: Optional[Any] = None
    prompt_manager: Optional[Any] = None
    language: str = "zh"
    debug_mode: bool = False
    visit_id: str = ""
    turns: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    all_role_mappings: dict = field(default_factory=dict)
    all_cleaned_turns: list = field(default_factory=list)
    combined_text: str = ""
    fact_records: list = field(default_factory=list)
    emr_draft: dict = field(default_factory=dict)
    emr_final: dict = field(default_factory=dict)
    save_evidence: bool = True
    fact_result: dict = field(default_factory=dict)
    consolidation_result: dict = field(default_factory=dict)
    normalized_result: dict = field(default_factory=dict)
    extraction_result: dict = field(default_factory=dict)
    verification_result: dict = field(default_factory=dict)


class PipelineStage(ABC):
    @abstractmethod
    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        ...

    @abstractmethod
    def stage_name(self) -> str:
        ...