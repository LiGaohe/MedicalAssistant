import re
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from ...models import TranscriptTurn
from ...utils.logger import logger


FIELD_TYPE_MAPPING = {
    "主诉": "chief_complaint",
    "现病史": "history_present_illness",
    "既往史": "past_history",
    "体格检查": "physical_examination",
    "辅助检查": "auxiliary_examination",
    "诊断": "diagnosis",
    "治疗": "treatment",
    "医嘱": "advice",
    "其他": "other"
}

FIELD_EXPECTED_ROLE = {
    "chief_complaint": "patient",
    "history_present_illness": "patient",
    "past_history": "patient",
    "physical_examination": "doctor",
    "auxiliary_examination": "doctor",
    "diagnosis": "doctor",
    "treatment": "doctor",
    "advice": "doctor",
    "other": None
}


class SpeakerHandler:
    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def assign_speakers_from_unlabeled(
        self,
        annotated_text: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str]
    ) -> Dict[int, str]:
        assignment_map = {}

        speaker_pattern = r'\[(医生|患者)\]:\s*([^\n\[]+)'
        matches = re.findall(speaker_pattern, annotated_text)

        if not matches:
            logger.warning("无标签对话解析失败：未找到[医生]/[患者]标签")
            return assignment_map

        turn_index = 0
        for speaker_label, text_content in matches:
            text_content = text_content.strip()
            if not text_content:
                continue

            if turn_index < len(segment):
                turn = segment[turn_index]
                turn.corrected_speaker = speaker_label
                assignment_map[turn_index] = speaker_label
                logger.info(
                    f"无标签对话分配说话人: turn_index={turn_index}, "
                    f"speaker={speaker_label}, text={text_content[:30]}..."
                )
                turn_index += 1

        if self.db and assignment_map:
            try:
                self.db.commit()
                logger.info(f"已保存 {len(assignment_map)} 条说话人分配记录")
            except Exception as e:
                self.db.rollback()
                logger.error(f"保存说话人分配记录失败: {e}")

        return assignment_map

    def apply_speaker_corrections(
        self,
        corrections: List[Dict[str, Any]],
        segment: List[TranscriptTurn]
    ) -> Dict[int, str]:
        correction_map = {}

        if not corrections:
            return correction_map

        turn_by_index = {turn.turn_index: turn for turn in segment}

        for correction in corrections:
            turn_index = correction.get("turn_index")
            original_speaker = correction.get("original_speaker")
            corrected_speaker = correction.get("corrected_speaker")
            reason = correction.get("reason", "")

            if turn_index is None or corrected_speaker is None:
                continue

            if original_speaker:
                original_speaker = re.sub(r'^\[|\]$', '', original_speaker)

            turn = turn_by_index.get(turn_index)
            if turn:
                if turn.speaker == original_speaker:
                    turn.corrected_speaker = corrected_speaker
                    correction_map[turn_index] = corrected_speaker
                    logger.info(
                        f"说话人纠正: turn_index={turn_index}, "
                        f"{original_speaker} -> {corrected_speaker}, "
                        f"原因: {reason}"
                    )
                else:
                    logger.warning(
                        f"说话人纠正跳过: turn_index={turn_index}, "
                        f"原始说话人不匹配 (期望={original_speaker}, 实际={turn.speaker})"
                    )

        if self.db and correction_map:
            try:
                self.db.commit()
                logger.info(f"已保存 {len(correction_map)} 条说话人纠正记录")
            except Exception as e:
                self.db.rollback()
                logger.error(f"保存说话人纠正记录失败: {e}")

        return correction_map

    def fallback_role_annotation(self, segment: List[TranscriptTurn]) -> Dict[str, Any]:
        role_mapping = self.infer_roles_by_rules(segment)

        turns = []
        for turn in segment:
            turns.append({
                "turn_id": turn.turn_index,
                "speaker_role": role_mapping.get(turn.speaker, turn.speaker),
                "corrected_text": turn.text,
                "section_hint": ["None"],
                "changed_spans": [],
                "correction_confidence": "low",
                "reason": "fallback处理：LLM调用失败，使用规则推断"
            })

        return {
            "role_mapping": role_mapping,
            "turns": turns
        }

    def infer_roles_by_rules(self, segment: List[TranscriptTurn]) -> Dict[str, str]:
        doctor_indicators = [
            "请问", "哪里不舒服", "持续多长时间", "有没有", "我给你",
            "量一下", "检查", "诊断", "考虑是", "开点", "注意", "复查",
            "需要", "建议", "治疗"
        ]

        patient_indicators = [
            "医生", "我", "头疼", "不舒服", "几天了", "有时候", "没有",
            "好的", "谢谢"
        ]

        speaker_scores = {}

        for turn in segment:
            speaker = turn.speaker
            if speaker not in speaker_scores:
                speaker_scores[speaker] = {"doctor": 0, "patient": 0}

            text = turn.text

            for indicator in doctor_indicators:
                if indicator in text:
                    speaker_scores[speaker]["doctor"] += 1

            for indicator in patient_indicators:
                if indicator in text:
                    speaker_scores[speaker]["patient"] += 1

            if text.endswith("？") or text.endswith("?"):
                speaker_scores[speaker]["doctor"] += 2

            if text.startswith("医生"):
                speaker_scores[speaker]["patient"] += 3

        role_mapping = {}
        for speaker, scores in speaker_scores.items():
            if scores["doctor"] > scores["patient"]:
                role_mapping[speaker] = "doctor"
            elif scores["patient"] > scores["doctor"]:
                role_mapping[speaker] = "patient"
            else:
                role_mapping[speaker] = "unknown"

        return role_mapping