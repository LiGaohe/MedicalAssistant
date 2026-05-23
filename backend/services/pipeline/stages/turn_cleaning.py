import time
from typing import Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from ..base import PipelineContext, PipelineStage
from ..utils import parse_json_response
from ..speaker_handler import SpeakerHandler
from ..debug_interactor import DebugInteractor
from ....models import TranscriptTurn
from ....config import settings
from ....utils.logger import logger


class TurnCleaningStage(PipelineStage):
    MAX_PARALLEL_SEGMENTS = 4

    def stage_name(self) -> str:
        return "转写清洗与角色纠错"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段1: {self.stage_name()}")
        stage_start = time.time()

        segments = self._segment_turns(ctx.turns)
        logger.info(f"对话分为 {len(segments)} 个段落")

        all_role_mappings, all_cleaned_turns = self._process_segments_parallel(ctx, segments)
        logger.info(f"段落处理完成，耗时: {time.time() - stage_start:.2f}秒")

        combined_text = self._build_text_from_cleaned_turns(all_cleaned_turns, ctx.turns)
        logger.info(f"合并后的清洗文本长度: {len(combined_text)} 字符")
        logger.info(f"收集到 {len(all_cleaned_turns)} 个清洗后的turn")

        ctx.all_role_mappings = all_role_mappings
        ctx.all_cleaned_turns = all_cleaned_turns
        ctx.combined_text = combined_text

        return {
            "role_mapping": all_role_mappings,
            "cleaned_turns": all_cleaned_turns,
            "combined_text": combined_text
        }

    def _segment_turns(self, turns: List[TranscriptTurn]) -> List[List[TranscriptTurn]]:
        segments = []
        current_segment = []
        segment_turns = settings.LLM_SEGMENT_TURNS

        for turn in turns:
            current_segment.append(turn)
            if len(current_segment) >= segment_turns:
                segments.append(current_segment)
                current_segment = []

        if current_segment:
            segments.append(current_segment)

        return segments

    def _process_segments_parallel(
        self,
        ctx: PipelineContext,
        segments: List[List[TranscriptTurn]]
    ) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
        logger.info(f">>> 并行处理 {len(segments)} 个段落")
        parallel_start = time.time()

        if not segments:
            return {}, []

        if ctx.debug_mode:
            logger.info("调试模式：使用串行处理")
            all_role_mappings = {}
            all_cleaned_turns = []
            for i, segment in enumerate(segments):
                logger.info(f">>> 处理段落 {i+1}/{len(segments)}")
                result = self._process_segment(ctx, segment, i)
                if result.get("role_mapping"):
                    all_role_mappings.update(result["role_mapping"])
                if result.get("turns"):
                    all_cleaned_turns.extend(result["turns"])
            return all_role_mappings, all_cleaned_turns

        max_workers = min(len(segments), self.MAX_PARALLEL_SEGMENTS)
        logger.info(f"使用 {max_workers} 个并行线程处理段落")

        results = [None] * len(segments)
        speaker_handler = SpeakerHandler(ctx.db)
        debug_interactor = DebugInteractor(ctx.llm_service)

        def process_single_segment(args):
            idx, segment = args
            try:
                result = self._process_segment(ctx, segment, idx, speaker_handler, debug_interactor)
                return idx, result, None
            except Exception as e:
                logger.error(f"段落 {idx} 处理失败: {e}")
                return idx, None, str(e)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = list(executor.map(
                process_single_segment,
                [(i, segment) for i, segment in enumerate(segments)]
            ))

            for idx, result_data, error in futures:
                if error:
                    logger.warning(f"段落 {idx} 处理出错: {error}，使用fallback")
                    fallback_result = speaker_handler.fallback_role_annotation(segments[idx])
                    results[idx] = fallback_result
                else:
                    results[idx] = result_data

        all_role_mappings = {}
        all_cleaned_turns = []

        for idx, result in enumerate(results):
            if result:
                if result.get("role_mapping"):
                    all_role_mappings.update(result["role_mapping"])
                if result.get("turns"):
                    all_cleaned_turns.extend(result["turns"])

        parallel_time = time.time() - parallel_start
        logger.info(f"并行段落处理完成，耗时: {parallel_time:.2f}秒，处理了 {len(segments)} 个段落")

        return all_role_mappings, all_cleaned_turns

    def _process_segment(
        self,
        ctx: PipelineContext,
        segment: List[TranscriptTurn],
        segment_index: int,
        speaker_handler: SpeakerHandler = None,
        debug_interactor: DebugInteractor = None
    ) -> Dict[str, Any]:
        if speaker_handler is None:
            speaker_handler = SpeakerHandler(ctx.db)
        if debug_interactor is None:
            debug_interactor = DebugInteractor(ctx.llm_service)

        transcript_text = self._format_segment(segment)
        prompt = self._build_cleaning_prompt(ctx, transcript_text)

        if ctx.debug_mode:
            response_text = debug_interactor.interact(
                stage="turn_cleaning",
                segment_index=segment_index,
                prompt=prompt,
                transcript_text=transcript_text
            )
        else:
            if not ctx.llm_service:
                logger.warning("LLM服务不可用，使用规则推断")
                return speaker_handler.fallback_role_annotation(segment)

            try:
                response = ctx.llm_service.generate(prompt, timeout=300.0, thinking_enabled=False)
                logger.debug("转写清洗阶段: thinking模式已禁用")
                response_text = response.text
            except Exception as e:
                logger.error(f"LLM调用失败: {e}")
                return speaker_handler.fallback_role_annotation(segment)

        cleaning_result = self._parse_cleaning_response(ctx, response_text, segment, speaker_handler)

        if "turns" in cleaning_result:
            self._apply_asr_corrections(ctx, cleaning_result, segment)

        return cleaning_result

    @staticmethod
    def _format_segment(segment: List[TranscriptTurn]) -> str:
        has_valid_speakers = False
        for turn in segment:
            if turn.speaker and turn.speaker not in ("unknown", "", "None"):
                has_valid_speakers = True
                break

        lines = []
        for turn in segment:
            if has_valid_speakers:
                lines.append(f"[#{turn.turn_index}] [{turn.speaker}]: {turn.text}")
            else:
                lines.append(f"[#{turn.turn_index}] {turn.text}")

        return "\n".join(lines)

    @staticmethod
    def _build_cleaning_prompt(ctx: PipelineContext, transcript: str) -> str:
        logger.info("构建转写清洗提示词")
        prompt = ctx.prompt_manager.render("turn_cleaning", transcript=transcript)
        logger.debug(f"转写清洗提示词长度: {len(prompt)} 字符")
        return prompt

    def _parse_cleaning_response(
        self,
        ctx: PipelineContext,
        response_text: str,
        segment: List[TranscriptTurn],
        speaker_handler: SpeakerHandler = None
    ) -> Dict[str, Any]:
        logger.info("解析转写清洗响应")

        if speaker_handler is None:
            speaker_handler = SpeakerHandler(ctx.db)

        result = parse_json_response(response_text, "转写清洗")

        if result:
            turns_data = result.get("turns", [])
            logger.info(f"解析到 {len(turns_data)} 个清洗后的turn")

            role_mapping = {}
            speaker_corrections = []

            turn_by_index = {turn.turn_index: turn for turn in segment}
            logger.info(f"segment详情: 长度={len(segment)}, turn_index列表={[t.turn_index for t in segment]}")
            logger.info(f"turn_by_index映射: {list(turn_by_index.keys())}")

            for i, turn_json in enumerate(turns_data):
                turn_id = turn_json.get("turn_id")
                speaker_role = turn_json.get("speaker_role")
                section_hint = turn_json.get("section_hint", [])

                if turn_id is None or speaker_role is None:
                    logger.warning(f"turn JSON缺少必要字段: turn_id={turn_id}, speaker_role={speaker_role}")
                    continue

                logger.debug(f"处理turn_json[{i}]: turn_id={turn_id}, speaker_role={speaker_role}")

                role_mapping[str(turn_id)] = speaker_role

                turn = turn_by_index.get(turn_id)
                if turn:
                    logger.debug(f"turn_id={turn_id}通过turn_by_index匹配成功: turn_index={turn.turn_index}")
                else:
                    logger.warning(f"turn_id={turn_id}在turn_by_index中未找到, 尝试位置匹配")
                    if 0 <= i < len(segment):
                        turn = segment[i]
                        logger.warning(
                            f"位置匹配: 位置{i} -> turn_index={turn.turn_index} (turn_id={turn_id}被忽略)"
                        )
                    else:
                        logger.warning(
                            f"位置{i}超出segment范围[0,{len(segment)-1}], 跳过此turn"
                        )
                        continue

                if turn:
                    original_speaker = turn.speaker
                    if original_speaker and original_speaker not in ("unknown", "", "None"):
                        if speaker_role == "doctor":
                            expected_label = "spk0" if original_speaker != "spk0" else original_speaker
                        else:
                            expected_label = "spk1" if original_speaker != "spk1" else original_speaker
                    else:
                        expected_label = f"spk_{turn_id}"

                    if original_speaker and original_speaker != speaker_role and original_speaker not in ("unknown", "", "None"):
                        speaker_corrections.append({
                            "turn_index": turn_id,
                            "original_speaker": original_speaker,
                            "corrected_speaker": speaker_role,
                            "reason": turn_json.get("reason", "")
                        })

                    turn.corrected_speaker = speaker_role
                    turn.section_hint = section_hint if section_hint else None
                    logger.debug(f"turn_index={turn_id}, section_hint={section_hint}")

            if speaker_corrections:
                speaker_handler.apply_speaker_corrections(speaker_corrections, segment)

            for turn in segment:
                if turn.corrected_speaker:
                    role_mapping[turn.speaker] = turn.corrected_speaker

            return {
                "turns": turns_data,
                "role_mapping": role_mapping,
                "speaker_corrections": speaker_corrections
            }

        logger.warning("转写清洗JSON解析失败，回退到规则推断")
        return speaker_handler.fallback_role_annotation(segment)

    def _apply_asr_corrections(
        self,
        ctx: PipelineContext,
        cleaning_result: Dict[str, Any],
        segment: List[TranscriptTurn]
    ) -> Dict[int, str]:
        logger.info("应用ASR修正结果")

        turns_data = cleaning_result.get("turns", [])
        if not turns_data:
            logger.info("没有需要应用的ASR修正")
            return {}

        turn_by_index = {turn.turn_index: turn for turn in segment}
        logger.info(f"ASR修正 - segment详情: 长度={len(segment)}, turn_index列表={[t.turn_index for t in segment]}")

        correction_map = {}
        applied_count = 0

        for i, turn_json in enumerate(turns_data):
            turn_id = turn_json.get("turn_id")
            corrected_text = turn_json.get("corrected_text", "")
            changed_spans = turn_json.get("changed_spans", [])

            if turn_id is None:
                continue

            turn = turn_by_index.get(turn_id)
            if turn:
                logger.debug(f"ASR修正: turn_id={turn_id}通过turn_by_index匹配成功, turn_index={turn.turn_index}")
            else:
                logger.warning(f"ASR修正: turn_id={turn_id}在turn_by_index中未找到, 尝试位置匹配")
                if 0 <= i < len(segment):
                    turn = segment[i]
                    logger.warning(
                        f"ASR修正位置匹配: 位置{i} -> turn_index={turn.turn_index} (turn_id={turn_id}被忽略)"
                    )
                else:
                    logger.warning(
                        f"ASR修正跳过: 位置{i}超出segment范围[0,{len(segment)-1}]"
                    )
                    continue

            if changed_spans and corrected_text:
                turn.corrected_text = corrected_text
                correction_map[turn_id] = corrected_text
                applied_count += 1
                logger.info(
                    f"ASR修正: turn_index={turn_id}, "
                    f"修改了 {len(changed_spans)} 处, "
                    f"置信度: {turn_json.get('correction_confidence', 'N/A')}"
                )

        if ctx.db and correction_map:
            try:
                ctx.db.commit()
                logger.info(f"已保存 {applied_count} 条ASR修正记录到数据库")
            except Exception as e:
                ctx.db.rollback()
                logger.error(f"保存ASR修正记录失败: {e}")

        logger.info(f"ASR修正完成: 共修正 {applied_count} 个turn")
        return correction_map

    @staticmethod
    def _build_text_from_cleaned_turns(
        cleaned_turns: List[Dict[str, Any]],
        original_turns: List[TranscriptTurn]
    ) -> str:
        logger.info(f"从 {len(cleaned_turns)} 个清洗turn构建文本")

        if cleaned_turns:
            turn_text_map = {}
            for ct in cleaned_turns:
                tid = ct.get("turn_id")
                ct_text = ct.get("corrected_text", "")
                if tid is not None and ct_text:
                    turn_text_map[tid] = ct_text

            lines = []
            for turn in original_turns:
                text = turn_text_map.get(turn.turn_index, turn.text)
                speaker = turn.corrected_speaker or turn.speaker
                if speaker and speaker not in ("unknown", "", "None"):
                    lines.append(f"[#{turn.turn_index}] [{speaker}]: {text}")
                else:
                    lines.append(f"[#{turn.turn_index}] {text}")

            combined = "\n".join(lines)
            logger.info(f"构建文本完成: {len(combined)} 字符, 使用了 {len(turn_text_map)} 个修正后的turn")
            return combined

        lines = []
        for turn in original_turns:
            speaker = turn.speaker
            if speaker and speaker not in ("unknown", "", "None"):
                lines.append(f"[#{turn.turn_index}] [{speaker}]: {turn.text}")
            else:
                lines.append(f"[#{turn.turn_index}] {turn.text}")

        return "\n".join(lines)