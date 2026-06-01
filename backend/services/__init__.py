"""业务逻辑服务"""
import warnings
import sys
from typing import TYPE_CHECKING

__all__ = [
    "ASRService",
    "ASRPostprocessor",
    "TranscriptNormalizer",
    "SpeakerRoleClassifier",
    "SpeakerRole",
    "SpeakerSegment",
    "LLMPipelineService",
    "LLMPipelineServiceEnglish",
]

_DEPRECATED_MODULES = {
    "SpeakerRoleClassifier": "speaker_role_classifier",
    "SpeakerRole": "speaker_role_classifier",
    "SpeakerSegment": "speaker_role_classifier",
}

def __getattr__(name: str):
    if name == "ASRService":
        from .asr_service import ASRService
        return ASRService
    elif name == "ASRPostprocessor":
        from .postprocessor import ASRPostprocessor
        return ASRPostprocessor
    elif name == "TranscriptNormalizer":
        from .normalizer import TranscriptNormalizer
        return TranscriptNormalizer
    elif name == "LLMPipelineService":
        from .llm_pipeline_service import LLMPipelineService
        return LLMPipelineService
    elif name == "LLMPipelineServiceEnglish":
        from .llm_pipeline_service_en import LLMPipelineServiceEnglish
        return LLMPipelineServiceEnglish
    elif name in _DEPRECATED_MODULES:
        warnings.warn(
            "SpeakerRoleClassifier 已废弃，不再推荐使用。"
            "说话人角色识别已改由LLM在处理流程中完成。"
            "该模块将在未来版本中移除。",
            DeprecationWarning,
            stacklevel=2
        )
        module_name = _DEPRECATED_MODULES[name]
        module = __import__(f".{module_name}", fromlist=[name], level=1)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")