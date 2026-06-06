from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from .llm_stats_collector import LLMStatsCollector


@dataclass
class PipelineContext:
    db: Optional[Session] = None
    llm_service: Optional[Any] = None
    prompt_manager: Optional[Any] = None
    language: str = "zh"
    debug_mode: bool = False
    sequential: bool = False  # 串行处理标志，禁用并行以避免API速率限制
    visit_id: str = ""
    turns: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    all_role_mappings: dict = field(default_factory=dict)
    all_cleaned_turns: list = field(default_factory=list)
    combined_text: str = ""
    emr_draft: dict = field(default_factory=dict)
    draft_text: str = ""
    emr_final: dict = field(default_factory=dict)
    save_evidence: bool = True
    extraction_result: dict = field(default_factory=dict)
    verification_result: dict = field(default_factory=dict)
    verification_issues: dict = field(default_factory=dict)
    hallucination_result: dict = field(default_factory=dict)
    skip_cleaning: bool = False
    skip_hallucination_check: bool = False
    skip_structuring: bool = False
    stop_after_draft: bool = True
    llm_stats: LLMStatsCollector = field(default_factory=LLMStatsCollector)

    # 压缩相关
    _compressed_transcript: Optional[str] = field(default=None, init=False, repr=False)
    _transcript_dictionary: Optional[str] = field(default=None, init=False, repr=False)
    _compressor: Optional[Any] = field(default=None, init=False, repr=False)

    def get_compressed_transcript(self) -> Tuple[str, Optional[str]]:
        """获取压缩后的对话原文，按需压缩并缓存

        Returns:
            (compressed_text, dictionary_str): 压缩后的文本和字典说明
            dictionary_str为None表示未压缩（回退到原文）
        """
        if self._compressed_transcript is not None:
            return self._compressed_transcript, self._transcript_dictionary

        if not self.combined_text:
            return self.combined_text, None

        # 懒加载压缩器
        if self._compressor is None:
            from .transcript_compressor import TranscriptCompressor
            self._compressor = TranscriptCompressor()

        self._compressed_transcript, self._transcript_dictionary = self._compressor.compress(self.combined_text)
        return self._compressed_transcript, self._transcript_dictionary

    def compress_text(self, text: str) -> Tuple[str, Optional[str]]:
        """压缩任意文本片段（如裁剪后的转写）

        Args:
            text: 待压缩文本

        Returns:
            (compressed_text, dictionary_str)
        """
        if not text:
            return text, None

        if self._compressor is None:
            from .transcript_compressor import TranscriptCompressor
            self._compressor = TranscriptCompressor()

        return self._compressor.compress_section(text)


class PipelineStage(ABC):
    @abstractmethod
    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        ...

    @abstractmethod
    def stage_name(self) -> str:
        ...