import asyncio
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session
from .llm.llm_service import LLMService
from .pipeline.orchestrator import PipelineOrchestrator


def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)


class LLMPipelineService:
    """向后兼容包装类，委托给 PipelineOrchestrator"""

    def __init__(self, db: Session, llm_service: Optional[LLMService] = None, language: str = "zh"):
        self._orchestrator = PipelineOrchestrator(db, llm_service, language)

    def process_transcript(
        self,
        visit_id: str,
        save_evidence: bool = True,
        skip_cleaning: bool = False,
        skip_hallucination_check: bool = False
    ) -> Dict[str, Any]:
        return self._orchestrator.process_transcript(
            visit_id, save_evidence, skip_cleaning, skip_hallucination_check
        )

    def process_with_callback(
        self,
        visit_id: str,
        progress_callback=None,
        save_evidence: bool = True,
        stop_after_draft: bool = True,
        skip_cleaning: bool = False,
        skip_hallucination_check: bool = False
    ):
        return self._orchestrator.process_with_callback(
            visit_id, progress_callback, save_evidence, stop_after_draft,
            skip_cleaning, skip_hallucination_check
        )

    def get_all_prompts(self, turns: List) -> List[Dict[str, Any]]:
        return self._orchestrator.get_all_prompts(turns)

    def process_stage_with_user_input(self, visit_id: str, stage: str, user_response: str, context: Dict[str, Any]) -> Dict[str, Any]:
        return self._orchestrator.process_stage_with_user_input(visit_id, stage, user_response, context)