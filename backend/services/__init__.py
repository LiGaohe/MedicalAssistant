"""业务逻辑服务"""
import warnings

from .asr_service import ASRService
from .postprocessor import ASRPostprocessor
from .normalizer import TranscriptNormalizer
from .llm_pipeline_service import LLMPipelineService

warnings.warn(
    "SpeakerRoleClassifier 已废弃，不再推荐使用。"
    "说话人角色识别已改由LLM在处理流程中完成。"
    "该模块将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2
)

from .speaker_role_classifier import SpeakerRoleClassifier, SpeakerRole, SpeakerSegment

__all__ = [
    "ASRService",
    "ASRPostprocessor",
    "TranscriptNormalizer",
    "SpeakerRoleClassifier",
    "SpeakerRole",
    "SpeakerSegment",
    "LLMPipelineService",
]
