"""
说话人角色识别模块

.. deprecated::
    该模块已废弃，不再推荐使用。
    
    废弃原因：
    1. 基于词表的语义推断覆盖不全，无法处理所有医疗对话场景
    2. 说话人分离(spk0/spk1)与医生/患者角色无固定对应关系
    3. 角色识别已改由LLM在处理流程中完成，语义理解更准确
    
    该模块将在未来版本中移除。
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional, Tuple
import re


class SpeakerRole(Enum):
    DOCTOR = "doctor"
    PATIENT = "patient"
    UNKNOWN = "unknown"


@dataclass
class SpeakerSegment:
    text: str
    start_ms: int
    end_ms: int
    speaker_id: str
    original_role: SpeakerRole
    corrected_role: SpeakerRole
    confidence: float
    correction_reason: str


class SpeakerRoleClassifier:
    DOCTOR_PATTERNS = [
        r"请问",
        r"哪里不舒服",
        r"持续多长时间",
        r"有没有.*症状",
        r"我给你(量|开|检查)",
        r"一周后.*复查",
        r"血压.*高",
        r"会引起",
        r"每天.*吃",
        r"先.*观察",
        r"注意休息",
        r"少吃",
        r"多(喝水|休息)",
        r"避免",
        r"建议",
        r"需要.*复查",
        r"按时.*服药",
    ]
    
    PATIENT_PATTERNS = [
        r"^(医生|大夫)",
        r"我这(几)?天",
        r"我(一直|经常|有时候)",
        r"特别是",
        r"大概.*了",
        r"但没有",
        r"有时候会",
        r"我需要吃",
        r"好的,?谢谢",
        r"谢谢医生",
        r"还需要注意什么",
        r"我需要.*吗",
    ]
    
    DOCTOR_QUESTION_PATTERNS = [
        r"哪里不舒服",
        r"持续多长时间",
        r"有没有.*症状",
        r"什么(时候|情况)",
        r"怎么(样|回事)",
    ]
    
    PATIENT_QUESTION_PATTERNS = [
        r"我需要.*吗",
        r"还需要注意",
        r"吃什么药",
        r"严重吗",
        r"能.*吗",
    ]
    
    QUESTION_ENDINGS = ["？", "?", "吗", "呢"]
    
    SYMPTOM_KEYWORDS = [
        "头疼", "头痛", "恶心", "呕吐", "发烧", "咳嗽", "肚子疼",
        "不舒服", "难受", "疼痛", "晕", "乏力", "失眠"
    ]
    
    DIAGNOSIS_KEYWORDS = [
        "血压", "偏高", "正常", "感染", "炎症", "感冒", "发烧"
    ]
    
    MEDICINE_KEYWORDS = [
        "药", "片", "胶囊", "口服", "注射", "点滴"
    ]
    
    DOCTOR_ADVICE_KEYWORDS = [
        "注意", "休息", "少吃", "多喝", "避免", "建议", "复查", "按时"
    ]

    def __init__(self, use_llm: bool = False, llm_config: Optional[Dict] = None):
        self.use_llm = use_llm
        self.llm_config = llm_config or {}
        self._compile_patterns()
    
    def _compile_patterns(self):
        self.doctor_patterns = [
            re.compile(p) for p in self.DOCTOR_PATTERNS
        ]
        self.patient_patterns = [
            re.compile(p) for p in self.PATIENT_PATTERNS
        ]
        self.doctor_question_patterns = [
            re.compile(p) for p in self.DOCTOR_QUESTION_PATTERNS
        ]
        self.patient_question_patterns = [
            re.compile(p) for p in self.PATIENT_QUESTION_PATTERNS
        ]
    
    def classify_segments(
        self,
        segments: List[Dict],
        speaker_id_mapping: Optional[Dict[str, str]] = None
    ) -> List[SpeakerSegment]:
        if speaker_id_mapping is None:
            speaker_id_mapping = {}
        
        results = []
        speaker_roles = {}
        
        for i, segment in enumerate(segments):
            text = segment.get("text", "")
            speaker_id = segment.get("speaker_id", segment.get("speaker", "unknown"))
            start_ms = segment.get("start_ms", segment.get("start", 0))
            end_ms = segment.get("end_ms", segment.get("end", 0))
            
            if speaker_id in speaker_id_mapping:
                original_role = SpeakerRole(speaker_id_mapping[speaker_id])
            else:
                original_role = self._map_speaker_id_to_role(speaker_id)
            
            corrected_role, confidence, reason = self._classify_single_segment(
                text, i, segments, speaker_roles
            )
            
            if confidence > 0.7:
                speaker_roles[speaker_id] = corrected_role
            
            results.append(SpeakerSegment(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                speaker_id=speaker_id,
                original_role=original_role,
                corrected_role=corrected_role,
                confidence=confidence,
                correction_reason=reason
            ))
        
        return results
    
    def _classify_single_segment(
        self,
        text: str,
        index: int,
        all_segments: List[Dict],
        speaker_roles: Dict[str, SpeakerRole]
    ) -> Tuple[SpeakerRole, float, str]:
        text = text.strip()
        
        doctor_score, doctor_reasons = self._calculate_doctor_score(text)
        patient_score, patient_reasons = self._calculate_patient_score(text)
        
        doctor_q_score, patient_q_score = self._calculate_question_scores(text)
        doctor_score += doctor_q_score
        patient_score += patient_q_score
        if doctor_q_score > 0:
            doctor_reasons.append("医生问诊模式")
        if patient_q_score > 0:
            patient_reasons.append("患者询问模式")
        
        is_mixed, mixed_reason = self._detect_mixed_speakers(text)
        if is_mixed:
            first_half_score, first_half_role = self._analyze_first_half(text)
            if first_half_role == SpeakerRole.DOCTOR:
                doctor_score += first_half_score + 1.0
                doctor_reasons.append(f"混合片段-前半部分医生: {mixed_reason}")
            elif first_half_role == SpeakerRole.PATIENT:
                patient_score += first_half_score + 1.0
                patient_reasons.append(f"混合片段-前半部分患者: {mixed_reason}")
        
        context_score, context_role = self._analyze_context(index, all_segments, speaker_roles)
        if context_role == SpeakerRole.DOCTOR:
            doctor_score += context_score
            doctor_reasons.append("上下文推断")
        elif context_role == SpeakerRole.PATIENT:
            patient_score += context_score
            patient_reasons.append("上下文推断")
        
        if doctor_score > patient_score:
            confidence = min(0.95, 0.5 + (doctor_score - patient_score) * 0.1)
            return SpeakerRole.DOCTOR, confidence, "; ".join(doctor_reasons) if doctor_reasons else "语义分析"
        elif patient_score > doctor_score:
            confidence = min(0.95, 0.5 + (patient_score - doctor_score) * 0.1)
            return SpeakerRole.PATIENT, confidence, "; ".join(patient_reasons) if patient_reasons else "语义分析"
        else:
            return SpeakerRole.UNKNOWN, 0.5, "无法确定"
    
    def _calculate_doctor_score(self, text: str) -> Tuple[float, List[str]]:
        score = 0.0
        reasons = []
        
        for pattern in self.doctor_patterns:
            if pattern.search(text):
                score += 1.0
                reasons.append(f"医生模式匹配: {pattern.pattern}")
        
        for keyword in self.DIAGNOSIS_KEYWORDS:
            if keyword in text:
                score += 0.5
                reasons.append(f"诊断关键词: {keyword}")
        
        for keyword in self.MEDICINE_KEYWORDS:
            if keyword in text:
                score += 0.5
                reasons.append(f"用药关键词: {keyword}")
        
        for keyword in self.DOCTOR_ADVICE_KEYWORDS:
            if keyword in text and "我需要" not in text and "还需要注意什么" not in text:
                score += 0.3
                reasons.append(f"医嘱关键词: {keyword}")
        
        if "我给你" in text or "给你开" in text or "给你量" in text:
            score += 2.0
            reasons.append("医生行为模式")
        
        return score, reasons
    
    def _calculate_patient_score(self, text: str) -> Tuple[float, List[str]]:
        score = 0.0
        reasons = []
        
        for pattern in self.patient_patterns:
            if pattern.search(text):
                score += 1.0
                reasons.append(f"患者模式匹配: {pattern.pattern}")
        
        for keyword in self.SYMPTOM_KEYWORDS:
            if keyword in text:
                score += 0.5
                reasons.append(f"症状关键词: {keyword}")
        
        if text.startswith("我") and ("天" in text or "直" in text or "时候" in text):
            score += 1.5
            reasons.append("患者自述模式")
        
        if "谢谢" in text:
            score += 1.0
            reasons.append("感谢表达")
        
        return score, reasons
    
    def _calculate_question_scores(self, text: str) -> Tuple[float, float]:
        doctor_score = 0.0
        patient_score = 0.0
        
        for pattern in self.doctor_question_patterns:
            if pattern.search(text):
                doctor_score += 1.5
                break
        
        for pattern in self.patient_question_patterns:
            if pattern.search(text):
                patient_score += 1.5
                break
        
        if text.endswith("？") or text.endswith("?"):
            if patient_score > 0:
                patient_score += 0.5
            else:
                doctor_score += 0.3
        
        return doctor_score, patient_score
    
    def _detect_mixed_speakers(self, text: str) -> Tuple[bool, str]:
        has_patient_pattern = False
        has_doctor_pattern = False
        reason = ""
        
        patient_indicators = ["特别是", "我这", "有时候", "大概", "没有"]
        doctor_indicators = ["持续多长时间", "有没有.*症状", "请问", "哪里不舒服"]
        
        for indicator in patient_indicators:
            if indicator in text:
                has_patient_pattern = True
                reason = f"患者特征: {indicator}"
                break
        
        for pattern in doctor_indicators:
            if re.search(pattern, text):
                has_doctor_pattern = True
                if reason:
                    reason += f" + 医生特征: {pattern}"
                else:
                    reason = f"医生特征: {pattern}"
                break
        
        return has_patient_pattern and has_doctor_pattern, reason
    
    def _analyze_first_half(self, text: str) -> Tuple[float, SpeakerRole]:
        mid_point = len(text) // 2
        first_half = text[:mid_point]
        
        patient_score = 0.0
        doctor_score = 0.0
        
        patient_indicators = ["特别是", "我这", "有时候", "大概", "早上", "晚上", "没有"]
        doctor_indicators = ["持续多长时间", "有没有", "请问", "哪里不舒服", "症状"]
        
        for indicator in patient_indicators:
            if indicator in first_half:
                patient_score += 1.0
        
        for indicator in doctor_indicators:
            if indicator in first_half:
                doctor_score += 1.0
        
        if "特别是" in first_half:
            patient_score += 2.0
        
        if doctor_score > patient_score:
            return doctor_score, SpeakerRole.DOCTOR
        elif patient_score > doctor_score:
            return patient_score, SpeakerRole.PATIENT
        else:
            return 0.0, SpeakerRole.UNKNOWN
    
    def _analyze_context(
        self,
        current_index: int,
        all_segments: List[Dict],
        speaker_roles: Dict[str, SpeakerRole]
    ) -> Tuple[float, SpeakerRole]:
        if current_index == 0:
            return 0.0, SpeakerRole.UNKNOWN
        
        prev_segment = all_segments[current_index - 1]
        prev_text = prev_segment.get("text", "")
        prev_speaker_id = prev_segment.get("speaker_id", prev_segment.get("speaker", "unknown"))
        
        if prev_speaker_id in speaker_roles:
            prev_role = speaker_roles[prev_speaker_id]
            if prev_role == SpeakerRole.DOCTOR:
                return 0.5, SpeakerRole.PATIENT
            elif prev_role == SpeakerRole.PATIENT:
                return 0.5, SpeakerRole.DOCTOR
        
        return 0.0, SpeakerRole.UNKNOWN
    
    def _map_speaker_id_to_role(self, speaker_id: str) -> SpeakerRole:
        if speaker_id == "unknown":
            return SpeakerRole.UNKNOWN
        
        try:
            spk_num = int(speaker_id.replace("spk", ""))
            if spk_num == 0:
                return SpeakerRole.DOCTOR
            elif spk_num == 1:
                return SpeakerRole.PATIENT
            else:
                return SpeakerRole.UNKNOWN
        except (ValueError, AttributeError):
            return SpeakerRole.UNKNOWN
    
    def correct_speaker_mapping(
        self,
        segments: List[Dict]
    ) -> Tuple[Dict[str, str], List[SpeakerSegment]]:
        speaker_doctor_scores: Dict[str, float] = {}
        speaker_patient_scores: Dict[str, float] = {}
        
        classified = self.classify_segments(segments)
        
        for seg in classified:
            speaker_id = seg.speaker_id
            if seg.corrected_role == SpeakerRole.DOCTOR:
                speaker_doctor_scores[speaker_id] = speaker_doctor_scores.get(speaker_id, 0) + seg.confidence
            elif seg.corrected_role == SpeakerRole.PATIENT:
                speaker_patient_scores[speaker_id] = speaker_patient_scores.get(speaker_id, 0) + seg.confidence
        
        speaker_mapping = {}
        for speaker_id in set(speaker_doctor_scores.keys()) | set(speaker_patient_scores.keys()):
            doctor_score = speaker_doctor_scores.get(speaker_id, 0)
            patient_score = speaker_patient_scores.get(speaker_id, 0)
            
            if doctor_score > patient_score:
                speaker_mapping[speaker_id] = SpeakerRole.DOCTOR.value
            elif patient_score > doctor_score:
                speaker_mapping[speaker_id] = SpeakerRole.PATIENT.value
            else:
                pass
        
        return speaker_mapping, classified
    
    def get_correction_summary(self, segments: List[SpeakerSegment]) -> Dict:
        total = len(segments)
        corrected = sum(1 for s in segments if s.original_role != s.corrected_role)
        doctor_count = sum(1 for s in segments if s.corrected_role == SpeakerRole.DOCTOR)
        patient_count = sum(1 for s in segments if s.corrected_role == SpeakerRole.PATIENT)
        unknown_count = sum(1 for s in segments if s.corrected_role == SpeakerRole.UNKNOWN)
        
        return {
            "total_segments": total,
            "corrected_count": corrected,
            "correction_rate": corrected / total if total > 0 else 0,
            "doctor_segments": doctor_count,
            "patient_segments": patient_count,
            "unknown_segments": unknown_count,
            "avg_confidence": sum(s.confidence for s in segments) / total if total > 0 else 0
        }
