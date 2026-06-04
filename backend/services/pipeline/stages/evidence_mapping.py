import time
import json
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..debug_interactor import DebugInteractor
from ....utils.logger import logger


class EvidenceMappingStage(PipelineStage):

    STAGE_DELAY = 0.3

    def stage_name(self) -> str:
        return "证据溯源构建"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段: {self.stage_name()}")
        stage_start = time.time()

        emr_draft = ctx.emr_draft
        combined_text = ctx.combined_text
        turns = ctx.turns

        if not emr_draft:
            logger.warning("emr_draft为空，跳过证据溯源构建")
            return {"status": "skipped"}

        if not combined_text or not turns:
            logger.warning("对话内容为空，无法构建证据溯源")
            self._add_empty_evidence_traces(emr_draft)
            return {"status": "skipped"}

        prompt = ctx.prompt_manager.render(
            "evidence_mapping",
            transcript=combined_text,
            emr_draft=self._format_emr_for_prompt(emr_draft)
        )
        logger.debug(f"证据溯源构建提示词长度: {len(prompt)} 字符")

        debug_interactor = DebugInteractor(ctx.llm_service)

        if ctx.debug_mode:
            try:
                response_text = debug_interactor.interact(
                    stage="evidence_mapping",
                    prompt=prompt
                )
            except RuntimeError as e:
                logger.error(f"DEBUG模式交互失败: {e}")
                self._add_empty_evidence_traces(emr_draft)
                return {"status": "debug_cancelled"}
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，证据溯源构建跳过")
                self._add_empty_evidence_traces(emr_draft)
                return {"status": "llm_unavailable"}

            try:
                response = ctx.llm_service.generate_stream_to_response(prompt, thinking_enabled=False)
                logger.debug("证据溯源构建阶段: thinking模式已禁用，使用流式处理")
                ctx.llm_stats.record_from_response("evidence_mapping", prompt, response)
                response_text = response.text
            except Exception as e:
                logger.error(f"证据溯源构建LLM调用失败: {e}")
                ctx.llm_stats.record_call("evidence_mapping", len(prompt), 0, success=False, error_message=str(e))
                self._add_empty_evidence_traces(emr_draft)
                return {"status": "llm_error"}

        mapping_result = self._parse_mapping_response(response_text)
        if mapping_result:
            self._apply_evidence_mapping(emr_draft, mapping_result, turns)
            logger.info(f"证据溯源构建完成")
        else:
            logger.warning("证据映射解析失败，使用空证据")
            self._add_empty_evidence_traces(emr_draft)

        stage_time = time.time() - stage_start
        logger.info(f"证据溯源构建完成, 耗时: {stage_time:.2f}秒")

        return {"status": "success"}

    def _format_emr_for_prompt(self, emr_draft: Dict[str, Any]) -> str:
        lines = []
        section_names = {
            "subjective": "主观症状（S）",
            "objective": "客观体征（O）",
            "assessment": "评估诊断（A）",
            "plan": "治疗计划（P）"
        }
        for section_key, section_label in section_names.items():
            section = emr_draft.get(section_key, {})
            text = section.get("text", "")
            if text:
                lines.append(f"**{section_label}**：{text}")
        return "\n".join(lines)

    def _parse_mapping_response(self, response_text: str) -> Dict[str, Any]:
        try:
            mapping = parse_json_response(response_text, "证据映射", raise_on_error=False)
            if not mapping or not isinstance(mapping, dict):
                return None
            
            required_sections = ["subjective", "objective", "assessment", "plan"]
            for section in required_sections:
                if section not in mapping:
                    return None
                section_data = mapping[section]
                if not isinstance(section_data, dict) or "source_turn_indices" not in section_data:
                    return None
            
            return mapping
        except Exception as e:
            logger.debug(f"证据映射JSON解析失败: {e}")
            return None

    def _apply_evidence_mapping(self, emr_draft: Dict[str, Any], mapping: Dict[str, Any], turns: List) -> None:
        logger.info(f"_apply_evidence_mapping: turns列表长度={len(turns)}, turn_index列表={[t.turn_index for t in turns[:10]]}...")
        turn_map = {turn.turn_index: turn for turn in turns}
        logger.info(f"_apply_evidence_mapping: turn_map keys={list(turn_map.keys())[:20]}...")
        
        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = emr_draft.get(section_name, {})
            if not isinstance(section, dict):
                continue
            
            source_indices = mapping.get(section_name, {}).get("source_turn_indices", [])
            logger.info(f"_apply_evidence_mapping: section={section_name}, source_indices={source_indices[:10]}...")
            evidence_traces = []
            
            if source_indices and isinstance(source_indices, list):
                for idx in source_indices:
                    turn = turn_map.get(idx)
                    logger.debug(f"_apply_evidence_mapping: 查找idx={idx}, 结果={turn is not None}")
                    if turn:
                        turn_text = turn.corrected_text or turn.text
                        evidence_traces.append({
                            "turn_id": turn.turn_id,
                            "turn_index": turn.turn_index,
                            "speaker": turn.speaker,
                            "turn_text": turn_text,
                            "content": turn_text[:100] if turn_text else ""
                        })
            
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                    continue
                if isinstance(field_data, dict) and "value" in field_data:
                    field_data["evidence_traces"] = evidence_traces
                    logger.debug(f"为字段 {section_name}.{field_name} 添加 {len(evidence_traces)} 条证据溯源")
            
            if "text" in section and section["text"]:
                section["evidence_traces"] = evidence_traces
                logger.info(f"为section {section_name} 添加 {len(evidence_traces)} 条证据溯源到section级别")
        
        # 计算总trace数，包括字段级别和section级别
        total_traces = 0
        for section_name, section in emr_draft.items():
            if not isinstance(section, dict):
                continue
            # 字段级别的trace
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                    continue
                if isinstance(field_data, dict):
                    total_traces += len(field_data.get("evidence_traces", []))
            # section级别的trace
            total_traces += len(section.get("evidence_traces", []))
        
        logger.info(f"证据溯源已应用: 共 {total_traces} 条trace分配到各字段和section")

    def _add_empty_evidence_traces(self, emr_draft: Dict[str, Any]) -> None:
        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = emr_draft.get(section_name, {})
            if isinstance(section, dict):
                for field_name, field_data in section.items():
                    if field_name in ("text", "evidence_traces", "assessment_items", "plan_items"):
                        continue
                    if isinstance(field_data, dict) and "value" in field_data:
                        field_data["evidence_traces"] = []
                if "text" in section and section["text"]:
                    section["evidence_traces"] = []