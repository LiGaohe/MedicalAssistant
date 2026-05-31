import json
import re
import time
import asyncio
from typing import Dict, Any, List

from sqlalchemy.orm import Session
from ..models import TranscriptTurn, EMRRecord, EvidenceSpan, NormalizedTerm
from .llm.llm_service import LLMService
from .llm_pipeline_service import LLMPipelineService, run_async
from ..utils.logger import logger
from ..config import settings


class LLMPipelineServiceEnglish(LLMPipelineService):
    FIELD_TYPE_MAPPING = {
        "chief_complaint": "chief_complaint",
        "history_present_illness": "history_present_illness",
        "past_history": "past_history",
        "physical_examination": "physical_examination",
        "auxiliary_examination": "auxiliary_examination",
        "diagnosis": "diagnosis",
        "treatment": "treatment",
        "advice": "advice",
        "other": "other"
    }
    
    def __init__(self, db: Session, llm_service: LLMService = None):
        super().__init__(db, llm_service, language="en")
        logger.info(f"LLMPipelineServiceEnglish initialized (English mode), UMLS={'enabled' if self.terminology_service.umls_client else 'disabled'}")

    def _format_segment(self, segment: List[TranscriptTurn]) -> str:
        """
        Format transcript turns with turn_index for precise evidence tracing.
        
        Output format includes turn_index for evidence tracing:
        - Labeled: [#0] [spk0]: dialogue content
        - Unlabeled: [#0] dialogue content
        """
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

    def _build_role_annotation_prompt(self, transcript: str) -> str:
        return f"""You are a medical conversation analysis expert. Please analyze the following doctor-patient conversation and complete three tasks:

## Task 1: Speaker Identification and Correction

First, determine the dialogue format:
- **Labeled**: format like [#0] [spk0]: dialogue content, where [#0] is the turn index
- **Unlabeled**: format like [#0] dialogue content, no speaker labels

**IMPORTANT: The turn index [#N] is a globally unique identifier. It MUST be preserved completely in the output. DO NOT modify or delete it.**

### Case A: Labeled
ASR speaker diarization may contain errors. Please check the content of each utterance and determine if the speaker label is correct.
- Doctor characteristics: asking questions, examining, diagnosing, prescribing, giving advice, using medical terminology
- Patient characteristics: describing symptoms, answering questions, expressing feelings, asking about conditions

If you find a speaker label that doesn't match the content, use the correct speaker label in the corrected dialogue.

### Case B: Unlabeled
Please assign speaker labels to each utterance based on content:
- Use [Doctor] and [Patient] as labels
- Determine the speaker of each utterance based on content characteristics

## Task 2: Role Mapping
List all speaker labels appearing in the conversation and determine whether each is a doctor or patient.
- If speaker corrections were made, the mapping should be based on the corrected labels
- If the original dialogue is unlabeled, map [Doctor] -> doctor, [Patient] -> patient

## Task 3: Evidence Annotation
Use XML tags to annotate evidence fields that may be relevant to medical record generation. Available tags:
- <chief_complaint>...</chief_complaint>: the patient's primary symptoms or problems
- <history_present_illness>...</history_present_illness>: detailed development of symptoms
- <past_history>...</past_history>: past disease history, surgical history, allergy history, etc.
- <physical_examination>...</physical_examination>: the doctor's examination process and findings
- <auxiliary_examination>...</auxiliary_examination>: lab tests, imaging exams, etc.
- <diagnosis>...</diagnosis>: the doctor's diagnostic conclusions
- <treatment>...</treatment>: treatment plan, medications, etc.
- <advice>...</advice>: the doctor's recommendations and instructions
- <other>...</other>: other relevant information

## Critical Constraints
1. **NO HALLUCINATION**: Only annotate content that explicitly exists in the original text. Absolutely DO NOT add, fabricate, or infer any information not present in the original.
2. **Completeness**: Must preserve ALL original conversation content. Cannot delete or omit any dialogue.
3. **Accuracy**: Evidence annotation must accurately correspond to the original content. Cannot distort the original meaning.
4. **Faithful to Original**: Annotated content must be exactly the same as the original. Cannot modify, add, or delete any words.
5. **Preserve Turn Index**: The turn index [#N] MUST be preserved completely. This is the key identifier for evidence tracing.

## Original Conversation
{transcript}

## Output Format
Please output in the following JSON format:
{{
  "dialog_format": "labeled or unlabeled",
  "speakers_found": ["list of speaker labels"],
  "corrections": [
    {{"turn_index": 0, "original_speaker": "original label", "corrected_speaker": "corrected label", "reason": "reason for correction"}}
  ],
  "role_mapping": {{
    "speaker_label_1": "doctor or patient",
    "speaker_label_2": "doctor or patient"
  }},
  "annotated_text": "processed conversation text, preserving turn index [#N], with XML tags around evidence"
}}

Notes:
1. dialog_format: "labeled" means the original conversation has speaker labels, "unlabeled" means it doesn't
2. corrections: only fill when labeled conversations have errors, otherwise empty list
3. role_mapping: list ALL speaker labels and their roles, don't omit any
4. annotated_text:
   - MUST preserve turn index [#N] format
   - Labeled: [#N] [speaker]: dialogue content
   - Unlabeled: [#N] [Doctor/Patient]: dialogue content
5. Evidence annotation should be accurate, don't miss important information
6. One passage may contain multiple evidence fields
7. **Must preserve ALL original conversation content, cannot delete any dialogue**
8. **The turn index [#N] is the key for evidence tracing, MUST be preserved completely**"""

    def _build_normalization_prompt(self, annotated_text: str) -> str:
        return f"""You are a medical terminology normalization expert. Please normalize colloquial medical terms in the following annotated text to standard medical terminology.

## Annotated Text
{annotated_text}

## Task Requirements
1. Identify colloquial medical terms in the text (e.g., "head pain" -> "headache", "high BP" -> "hypertension")
2. Replace colloquial terms with standard medical terminology
3. Keep all XML tags unchanged
4. Keep the conversation format unchanged

## Output Format
Please output in the following JSON format:
{{
  "normalized_text": "the complete normalized text",
  "terms": [
    {{
      "original": "original term",
      "normalized": "standard term",
      "category": "symptom|drug|diagnosis|exam|other"
    }}
  ]
}}

Notes:
1. Only normalize medical terms, do not modify other content
2. Preserve the original meaning and tone
3. If a term is already in standard form, no modification needed"""

    def _build_extraction_prompt(
        self,
        normalized_text: str,
        role_mapping: Dict[str, str]
    ) -> str:
        role_desc = "\n".join([f"- {spk}: {role}" for spk, role in role_mapping.items()])

        return f"""You are a medical record generation expert. Please extract medical record fields from the following normalized text.

## Role Mapping
{role_desc}

## Normalized Text
{normalized_text}

## Task Requirements
1. Extract field content from XML tags
2. Merge content from the same field (deduplicate)
3. Handle possible conflicts (retain more detailed and accurate content)
4. Annotate the source speaker for each field

## Output Format
Please output in the following JSON format:
{{
  "subjective": {{
    "chief_complaint": {{
      "value": "chief complaint content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }},
    "history_present_illness": {{
      "value": "history of present illness content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }},
    "past_history": {{
      "value": "past history content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }}
  }},
  "objective": {{
    "physical_examination": {{
      "value": "physical examination content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }},
    "auxiliary_examination": {{
      "value": "auxiliary examination content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }}
  }},
  "assessment": {{
    "diagnosis": {{
      "value": "diagnosis content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }}
  }},
  "plan": {{
    "treatment": {{
      "value": "treatment plan",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }},
    "advice": {{
      "value": "medical advice content",
      "speaker": "speaker ID",
      "confidence": 0.0-1.0
    }}
  }}
}}

Notes:
1. If a field has no content, set value to empty string
2. confidence indicates confidence in the extraction result
3. Ensure extracted content matches the role (chief complaint from patient, diagnosis from doctor, etc.)"""

    def _build_emr_generation_prompt(
        self,
        extraction_result: Dict[str, Any],
        role_mapping: Dict[str, str]
    ) -> str:
        extraction_json = json.dumps(extraction_result, ensure_ascii=False, indent=2)

        return f"""You are a medical record writing expert. Please generate medical record text that complies with medical record writing standards based on the following structured data.

## Structured Data
{extraction_json}

## Task Requirements
1. Generate natural and fluent medical record text
2. Comply with SOAP format (Subjective, Objective, Assessment, Plan)
3. Use standard medical terminology
4. Maintain accuracy and completeness of content

## Critical Constraints
1. **NO HALLUCINATION**: Only use content that explicitly exists in the structured data above. Absolutely DO NOT add, fabricate, or infer any information not present in the original text.
2. **Content Consistency**: Generated medical record content must come entirely from the structured data. Do not add any extra descriptions, inferences, or assumptions.
3. **Empty Field Handling**: If a field is empty or does not exist in the structured data, keep it empty. Do not fabricate content.
4. **Faithful to Original**: Medical record content must be faithful to the original conversation. Do not add symptoms not mentioned by the patient, diagnoses not made by the doctor, etc.

## Output Format
Please output in the following JSON format:
{{
  "subjective": {{
    "text": "Subjective section medical record text",
    "chief_complaint": "Chief Complaint",
    "history_present_illness": "History of Present Illness",
    "past_history": "Past History"
  }},
  "objective": {{
    "text": "Objective section medical record text",
    "physical_examination": "Physical Examination",
    "auxiliary_examination": "Auxiliary Examination"
  }},
  "assessment": {{
    "text": "Assessment section medical record text",
    "diagnosis": "Diagnosis"
  }},
  "plan": {{
    "text": "Plan section medical record text",
    "treatment": "Treatment Plan",
    "advice": "Medical Advice"
  }}
}}

Notes:
1. The text field should be complete paragraphs suitable for direct display
2. Each sub-field contains structured data
3. If a field is empty, leave it empty. Do not write "Not remarkable" or fabricate any content"""

    def _template_emr_generation(
        self,
        extraction_result: Dict[str, Any],
        visit_id: str = None,
        save_evidence: bool = True
    ) -> Dict[str, Any]:
        def get_value(section: str, field: str) -> str:
            try:
                return extraction_result.get(section, {}).get(field, {}).get("value", "")
            except:
                return ""

        def get_evidence_traces(section: str, field: str) -> List[Dict[str, Any]]:
            try:
                return extraction_result.get(section, {}).get(field, {}).get("evidence_traces", [])
            except:
                return []

        chief_complaint = get_value("subjective", "chief_complaint")
        history = get_value("subjective", "history_present_illness")
        past_history = get_value("subjective", "past_history")
        physical = get_value("objective", "physical_examination")
        auxiliary = get_value("objective", "auxiliary_examination")
        diagnosis = get_value("assessment", "diagnosis")
        treatment = get_value("plan", "treatment")
        advice = get_value("plan", "advice")

        subjective_text = []
        if chief_complaint:
            subjective_text.append(f"Chief Complaint: {chief_complaint}")
        if history:
            subjective_text.append(f"History of Present Illness: {history}")
        if past_history:
            subjective_text.append(f"Past History: {past_history}")

        objective_text = []
        if physical:
            objective_text.append(f"Physical Examination: {physical}")
        if auxiliary:
            objective_text.append(f"Auxiliary Examination: {auxiliary}")

        assessment_text = f"Diagnosis: {diagnosis}" if diagnosis else "Diagnosis: Pending"

        plan_text = []
        if treatment:
            plan_text.append(f"Treatment Plan: {treatment}")
        if advice:
            plan_text.append(f"Medical Advice: {advice}")

        result = {
            "subjective": {
                "text": "\n".join(subjective_text),
                "chief_complaint": {
                    "value": chief_complaint,
                    "evidence_traces": get_evidence_traces("subjective", "chief_complaint")
                },
                "history_present_illness": {
                    "value": history,
                    "evidence_traces": get_evidence_traces("subjective", "history_present_illness")
                },
                "past_history": {
                    "value": past_history,
                    "evidence_traces": get_evidence_traces("subjective", "past_history")
                }
            },
            "objective": {
                "text": "\n".join(objective_text),
                "physical_examination": {
                    "value": physical,
                    "evidence_traces": get_evidence_traces("objective", "physical_examination")
                },
                "auxiliary_examination": {
                    "value": auxiliary,
                    "evidence_traces": get_evidence_traces("objective", "auxiliary_examination")
                }
            },
            "assessment": {
                "text": assessment_text,
                "diagnosis": {
                    "value": diagnosis,
                    "evidence_traces": get_evidence_traces("assessment", "diagnosis")
                }
            },
            "plan": {
                "text": "\n".join(plan_text),
                "treatment": {
                    "value": treatment,
                    "evidence_traces": get_evidence_traces("plan", "treatment")
                },
                "advice": {
                    "value": advice,
                    "evidence_traces": get_evidence_traces("plan", "advice")
                }
            }
        }

        if save_evidence and visit_id:
            self._save_evidence_spans(extraction_result, visit_id, result)
            self._save_emr_record(result, visit_id)

        return result

    def _assign_speakers_from_unlabeled(
        self,
        annotated_text: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str]
    ) -> Dict[int, str]:
        assignment_map = {}

        speaker_pattern = r'\[(Doctor|Patient)\]:\s*([^\n\[]+)'
        matches = re.findall(speaker_pattern, annotated_text)

        if not matches:
            logger.warning("Unlabeled dialogue parsing failed: no [Doctor]/[Patient] tags found")
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
                    f"Unlabeled dialogue assigned speaker: turn_index={turn_index}, "
                    f"speaker={speaker_label}, text={text_content[:30]}..."
                )
                turn_index += 1

        if self.db and assignment_map:
            try:
                self.db.commit()
                logger.info(f"Saved {len(assignment_map)} speaker assignment records")
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to save speaker assignment records: {e}")

        return assignment_map

    def _extract_evidence_traces(
        self,
        annotated_text: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str] = None,
        correction_map: Dict[int, str] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract evidence traces from annotated text.
        
        Priority: Parse turn_index from annotated text (format: [#N]) for precise matching.
        """
        evidence_traces = []
        correction_map = correction_map or {}
        role_mapping = role_mapping or {}

        tag_pattern = r'<(chief_complaint|history_present_illness|past_history|physical_examination|auxiliary_examination|diagnosis|treatment|advice|other)>(.*?)</\1>'
        turn_index_pattern = r'\[#(\d+)\]'

        turn_by_index = {}
        for turn in segment:
            turn_by_index[turn.turn_index] = turn

        for match in re.finditer(tag_pattern, annotated_text, re.DOTALL):
            field_type_en = match.group(1)
            content = match.group(2).strip()

            field_type = self.FIELD_TYPE_MAPPING.get(field_type_en, "other")

            start_char = match.start()
            end_char = match.end()

            speaker = None
            original_speaker = None
            turn_id = None
            turn_index = None
            turn_text = None
            matched_turns = []

            turn_index_matches = re.findall(turn_index_pattern, content)

            if not turn_index_matches:
                line_start = annotated_text.rfind('\n', 0, start_char) + 1
                line_end = annotated_text.find('\n', start_char)
                if line_end == -1:
                    line_end = len(annotated_text)
                line = annotated_text[line_start:line_end]
                turn_index_matches = re.findall(turn_index_pattern, line)

            if turn_index_matches:
                for idx_str in turn_index_matches:
                    idx = int(idx_str)
                    if idx in turn_by_index:
                        turn = turn_by_index[idx]
                        if turn not in matched_turns:
                            matched_turns.append(turn)

                matched_turns.sort(key=lambda t: t.turn_index)

                if matched_turns:
                    first_turn = matched_turns[0]
                    turn_id = first_turn.turn_id
                    turn_index = first_turn.turn_index
                    original_speaker = first_turn.speaker
                    speaker = correction_map.get(first_turn.turn_index, first_turn.speaker)

                    if len(matched_turns) == 1:
                        turn_text = first_turn.text
                    else:
                        turn_text = "\n".join([
                            f"[{correction_map.get(t.turn_index, t.speaker)}]: {t.text}" 
                            for t in matched_turns
                        ])

                    logger.debug(f"Matched by turn_index: turn_index={turn_index}, content={content[:30]}...")

            if turn_id is None:
                logger.warning(f"Cannot parse turn_index from annotated text, using fallback: {content[:50]}...")
                matched_turns = self._fallback_match_turns(
                    content, segment, role_mapping, correction_map, field_type
                )

                if matched_turns:
                    first_turn = matched_turns[0]
                    turn_id = first_turn.turn_id
                    turn_index = first_turn.turn_index
                    original_speaker = first_turn.speaker
                    speaker = correction_map.get(first_turn.turn_index, first_turn.speaker)

                    if len(matched_turns) == 1:
                        turn_text = first_turn.text
                    else:
                        turn_text = "\n".join([
                            f"[{correction_map.get(t.turn_index, t.speaker)}]: {t.text}" 
                            for t in matched_turns
                        ])

                    logger.debug(f"Fallback match succeeded: turn_index={turn_index}, content={content[:30]}...")

            evidence_trace = {
                "field_type": field_type,
                "field_type_en": field_type_en,
                "content": content,
                "speaker": speaker,
                "original_speaker": original_speaker,
                "speaker_corrected": original_speaker is not None and original_speaker != speaker,
                "turn_id": turn_id,
                "turn_index": turn_index,
                "turn_text": turn_text,
                "start_char": start_char,
                "end_char": end_char
            }

            evidence_traces.append(evidence_trace)
            logger.debug(f"Extracted evidence: {field_type_en} - {content[:30]}... (turn_id={turn_id}, turn_index={turn_index})")

        return evidence_traces

    def _fallback_match_turns(
        self,
        content: str,
        segment: List[TranscriptTurn],
        role_mapping: Dict[str, str],
        correction_map: Dict[int, str],
        field_type: str
    ) -> List[TranscriptTurn]:
        """Fallback matching when turn_index cannot be parsed from annotated text."""
        turn_by_speaker = {}
        for turn in segment:
            effective_speaker = correction_map.get(turn.turn_index, turn.speaker)
            if effective_speaker not in turn_by_speaker:
                turn_by_speaker[effective_speaker] = []
            turn_by_speaker[effective_speaker].append(turn)

        role_to_speaker = {}
        for spk, role in role_mapping.items():
            if role not in role_to_speaker:
                role_to_speaker[role] = []
            role_to_speaker[role].append(spk)

        def find_turns_by_role_label(label: str) -> List[TranscriptTurn]:
            if label in turn_by_speaker:
                return turn_by_speaker[label]
            if label in ["Doctor", "doctor"]:
                for spk in role_to_speaker.get("doctor", []):
                    if spk in turn_by_speaker:
                        return turn_by_speaker[spk]
            elif label in ["Patient", "patient"]:
                for spk in role_to_speaker.get("patient", []):
                    if spk in turn_by_speaker:
                        return turn_by_speaker[spk]
            return []

        matched_turns = []

        speaker_markers = re.findall(r'\[(spk\d+|Doctor|Patient)\]:\s*([^[]+)', content)

        if speaker_markers:
            for spk_label, text_part in speaker_markers:
                text_part = text_part.strip().rstrip(',，.。')
                if not text_part:
                    continue

                candidate_turns = find_turns_by_role_label(spk_label)
                for turn in candidate_turns:
                    if text_part in turn.text or turn.text in text_part:
                        if turn not in matched_turns:
                            matched_turns.append(turn)
                        break

        if not matched_turns:
            clean_content = re.sub(r'<[^>]+>', '', content)
            clean_content = re.sub(r'\[#\d+\]\s*', '', clean_content)
            clean_content = re.sub(r'\[(spk\d+|Doctor|Patient)\]:\s*', '', clean_content)
            clean_content = clean_content.strip()

            expected_role = self.FIELD_EXPECTED_ROLE.get(field_type)
            candidate_turns_for_fallback = []

            if expected_role:
                for spk, role in role_mapping.items():
                    if role == expected_role:
                        if spk in turn_by_speaker:
                            candidate_turns_for_fallback.extend(turn_by_speaker[spk])

            if not candidate_turns_for_fallback:
                candidate_turns_for_fallback = segment

            best_match_turn = None
            best_match_score = 0

            for turn in candidate_turns_for_fallback:
                if clean_content:
                    turn_text_clean = turn.text.strip()
                    if clean_content.lower() in turn_text_clean.lower():
                        match_score = len(clean_content) / len(turn_text_clean) if turn_text_clean else 0
                        if match_score > best_match_score:
                            best_match_score = match_score
                            best_match_turn = turn

            if best_match_turn:
                matched_turns.append(best_match_turn)

        return matched_turns

    def _infer_roles_by_rules(self, segment: List[TranscriptTurn]) -> Dict[str, str]:
        doctor_indicators = [
            "what brings you", "how can I", "let me", "I'll", "you should",
            "check", "examine", "diagnose", "prescribe", "recommend",
            "follow up", "take this", "try this", "how long", "have you",
            "any other", "on a scale", "I see", "I understand",
            "请问", "哪里不舒服", "持续多长时间"
        ]

        patient_indicators = [
            "I have", "I feel", "it hurts", "I've been", "my",
            "doctor", "yes", "no", "okay", "thank you", "sometimes",
            "not really", "I think", "a few days", "for a while",
            "医生", "我", "头疼", "不舒服"
        ]

        speaker_scores = {}

        for turn in segment:
            speaker = turn.speaker
            if speaker not in speaker_scores:
                speaker_scores[speaker] = {"doctor": 0, "patient": 0}

            text = turn.text

            for indicator in doctor_indicators:
                if indicator.lower() in text.lower():
                    speaker_scores[speaker]["doctor"] += 1

            for indicator in patient_indicators:
                if indicator.lower() in text.lower():
                    speaker_scores[speaker]["patient"] += 1

            if text.endswith("?"):
                speaker_scores[speaker]["doctor"] += 2

            if text.lower().startswith("doctor"):
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

    def _debug_interact(
        self,
        stage: str,
        prompt: str,
        **context
    ) -> str:
        import sys

        if not sys.stdin.isatty():
            logger.warning(f"DEBUG mode unavailable in HTTP requests, skipping stage: {stage}")
            raise RuntimeError(f"DEBUG mode requires terminal interaction. Stage: {stage}")

        print("\n" + "=" * 80)
        print(f"[DEBUG Mode] Stage: {stage}")
        print("=" * 80)
        print("\n>>> Full content to send to LLM:\n")
        print(prompt)
        print("\n" + "-" * 80)

        while True:
            try:
                user_input = input("\nChoose action:\n  y - Confirm and send to LLM\n  n - Skip, manually enter result\n  q - Cancel\n\nEnter choice: ").strip().lower()
            except EOFError:
                logger.warning("Cannot read user input, skipping DEBUG interaction")
                raise RuntimeError("DEBUG mode requires terminal interaction")

            if user_input == 'y':
                if not self.llm_service:
                    print("\n[Warning] LLM service unavailable! Please configure LLM or choose 'n' to manually enter result.")
                    continue

                try:
                    print("\n>>> Calling LLM...")
                    response = self.llm_service.generate(prompt)
                    print("\n>>> LLM response:\n")
                    print(response.text)
                    return response.text
                except Exception as e:
                    print(f"\n[Error] LLM call failed: {e}")
                    print("Please choose 'n' to manually enter result, or 'q' to cancel.")
                    continue

            elif user_input == 'n':
                print("\n" + "=" * 80)
                print(">>> Manual Input Mode")
                print("=" * 80)
                print(f"\nStage: {stage}")
                print("\nInstructions:")

                if stage == "role_annotation":
                    print("""
1. Analyze the conversation content to determine whether each speaker (spk0, spk1, etc.) is a doctor or patient
2. Annotate evidence fields with XML tags:
   - <chief_complaint>...</chief_complaint>
   - <history_present_illness>...</history_present_illness>
   - <past_history>...</past_history>
   - <physical_examination>...</physical_examination>
   - <auxiliary_examination>...</auxiliary_examination>
   - <diagnosis>...</diagnosis>
   - <treatment>...</treatment>
   - <advice>...</advice>
3. Output result in JSON format
""")
                elif stage == "field_extraction":
                    print("""
1. Extract field content from XML tags
2. Merge content from the same field (deduplicate)
3. Handle possible conflicts
4. Output result in JSON format
""")
                elif stage == "emr_generation":
                    print("""
1. Generate medical record text from structured data
2. Comply with SOAP format
3. Use standard medical terminology
4. Output result in JSON format
""")

                print("\nEnter the LLM response (JSON format):")
                print("(Press Enter after input, then type 'END' and press Enter to finish)\n")

                lines = []
                while True:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)

                result = "\n".join(lines)
                print("\n>>> Received manual input result")
                return result

            elif user_input == 'q':
                print("\n>>> Operation cancelled")
                raise RuntimeError("User cancelled the operation")

            else:
                print("\nInvalid input, please try again.")

    def get_all_prompts(self, turns: List[TranscriptTurn]) -> List[Dict[str, Any]]:
        stages = []

        segments = self._segment_turns(turns)
        total_segments = len(segments)

        for i, segment in enumerate(segments):
            transcript_text = self._format_segment(segment)
            prompt = self._build_role_annotation_prompt(transcript_text)

            stages.append({
                "stage": "role_annotation",
                "segment_index": i,
                "total_segments": total_segments,
                "prompt": prompt,
                "description": f"Stage 1.{i+1}/{total_segments}: Role Identification & Evidence Annotation",
                "instructions": """
1. Analyze the conversation content, determine whether each speaker (spk0, spk1, etc.) is a doctor or patient
2. Annotate evidence fields with XML tags:
   - <chief_complaint>...</chief_complaint>
   - <history_present_illness>...</history_present_illness>
   - <past_history>...</past_history>
   - <physical_examination>...</physical_examination>
   - <auxiliary_examination>...</auxiliary_examination>
   - <diagnosis>...</diagnosis>
   - <treatment>...</treatment>
   - <advice>...</advice>
3. Output result in JSON format:
{
  "role_mapping": {"spk0": "doctor", "spk1": "patient"},
  "annotated_text": "annotated conversation text..."
}
"""
            })

        stages.append({
            "stage": "field_extraction",
            "prompt": "[Pending: waiting for Stage 2 to complete]",
            "description": "Stage 3: Field Extraction",
            "instructions": """
1. Extract field content from XML tags
2. Merge content from the same field (deduplicate)
3. Handle possible conflicts
4. Output result in JSON format:
{
  "subjective": {"chief_complaint": {"value": "...", "speaker": "...", "confidence": 0.9}, ...},
  "objective": {...},
  "assessment": {...},
  "plan": {...}
}
""",
            "pending": True
        })

        stages.append({
            "stage": "emr_generation",
            "prompt": "[Pending: waiting for Stage 3 to complete]",
            "description": "Stage 4: EMR Generation",
            "instructions": """
1. Generate medical record text from structured data
2. Comply with SOAP format
3. Output result in JSON format:
{
  "subjective": {"text": "Subjective section", "chief_complaint": "...", ...},
  "objective": {"text": "Objective section", ...},
  "assessment": {"text": "Assessment section", ...},
  "plan": {"text": "Plan section", ...}
}
""",
            "pending": True
        })

        return stages

    def process_stage_with_user_input(
        self,
        visit_id: str,
        stage: str,
        user_response: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        turns = self.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()

        if not turns:
            return {"error": "No transcript turns found"}

        segments = self._segment_turns(turns)
        total_segments = len(segments)

        if stage == "role_annotation":
            segment_index = context.get("segment_index", 0)
            segment = segments[segment_index] if segment_index < len(segments) else segments[0]

            result = self._parse_role_annotation_response(user_response, segment)

            all_annotated_texts = context.get("all_annotated_texts", [])
            all_evidence_traces = context.get("all_evidence_traces", [])

            if result.get("annotated_text"):
                all_annotated_texts.append(result["annotated_text"])
            if result.get("evidence_traces"):
                all_evidence_traces.extend(result["evidence_traces"])

            next_stage = None
            next_prompt = None
            next_segment_index = None
            next_description = None

            if segment_index + 1 < total_segments:
                next_stage = "role_annotation"
                next_segment_index = segment_index + 1
                next_prompt = self._build_role_annotation_prompt(
                    self._format_segment(segments[next_segment_index])
                )
                next_description = f"Stage 1.{next_segment_index + 1}/{total_segments}: Role Identification & Evidence Annotation"
            else:
                next_stage = "field_extraction"
                combined_annotated_text = "\n\n".join(all_annotated_texts)
                next_prompt = self._build_extraction_prompt(combined_annotated_text, context.get("role_mapping", {}))
                next_description = "Stage 2: Field Extraction"

            return {
                "result": result,
                "next_stage": next_stage,
                "next_prompt": next_prompt,
                "next_segment_index": next_segment_index,
                "next_description": next_description,
                "context_update": {
                    "all_annotated_texts": all_annotated_texts,
                    "all_evidence_traces": all_evidence_traces,
                    "role_mapping": {**context.get("role_mapping", {}), **result.get("role_mapping", {})}
                }
            }

        elif stage == "field_extraction":
            normalized_text = context.get("normalized_text", "")
            if not normalized_text:
                all_annotated_texts = context.get("all_annotated_texts", [])
                normalized_text = "\n\n".join(all_annotated_texts) if all_annotated_texts else "\n\n".join([self._format_segment(s) for s in segments])

            all_evidence_traces = context.get("all_evidence_traces", [])
            result = self._parse_extraction_response(user_response, all_evidence_traces)

            return {
                "result": result,
                "next_stage": "emr_generation",
                "next_prompt": self._build_emr_generation_prompt(result, context.get("role_mapping", {})),
                "next_description": "Stage 4: EMR Generation",
                "context_update": {
                    "extraction_result": result
                }
            }

        elif stage == "emr_generation":
            extraction_result = context.get("extraction_result", {})
            result = self._parse_emr_response(user_response, extraction_result, visit_id, True)

            return {
                "result": result,
                "next_stage": None,
                "next_prompt": None,
                "next_description": None,
                "completed": True
            }

        return {"error": f"Unknown stage: {stage}"}

    def _normalize_terms_stage(
        self,
        annotated_text: str,
        role_mapping: Dict[str, str],
        visit_id: str = None,
        save_to_db: bool = True
    ) -> Dict[str, Any]:
        """
        英文术语规范化阶段（不需要翻译步骤）
        
        优化点：
        1. 跳过翻译步骤（英文已经是目标语言）
        2. 并行UMLS检索
        3. 批量LLM选择
        4. 并行获取Code
        """
        logger.info(">>> 阶段2: 术语规范化 (英文模式)")
        stage_start = time.time()
        
        identified_terms = self.terminology_service.identify_colloquial_terms(annotated_text)
        
        if not identified_terms:
            logger.info("未识别到任何医学术语")
            return {"normalized_text": annotated_text, "terms": []}
        
        logger.info(f"识别到 {len(identified_terms)} 个医学术语")
        
        seen_terms = set()
        unique_terms = []
        for term_info in identified_terms:
            term = term_info.get("term", "")
            if term not in seen_terms:
                seen_terms.add(term)
                unique_terms.append(term_info)
        
        logger.info(f"去重后剩余 {len(unique_terms)} 个术语")
        
        normalized_terms = []
        terms_for_result = []
        
        parallel_enabled = getattr(settings, 'TERMINOLOGY_PARALLEL_ENABLED', True)
        
        if parallel_enabled and self.terminology_service.async_umls_client and len(unique_terms) > 1:
            logger.info("使用并行模式规范化术语（英文，跳过翻译）")
            
            try:
                normalized_terms = run_async(
                    self._normalize_terms_parallel_en(unique_terms, annotated_text)
                )
            except Exception as e:
                logger.warning(f"并行规范化失败，回退到串行模式: {e}")
                normalized_terms = self._normalize_terms_serial(unique_terms)
        else:
            logger.info("使用串行模式规范化术语")
            normalized_terms = self._normalize_terms_serial(unique_terms)
        
        for i, normalized in enumerate(normalized_terms):
            term_info = unique_terms[i] if i < len(unique_terms) else {}
            term = term_info.get("term", "")
            term_type = term_info.get("term_type", "unknown")
            is_colloquial = term_info.get("is_colloquial", True)
            
            terms_for_result.append({
                "original": term,
                "normalized": normalized.normalized_term,
                "category": term_type,
                "source": normalized.source,
                "confidence": normalized.confidence,
                "cui": normalized.cui,
                "code": normalized.code,
                "code_system": normalized.code_system,
                "is_colloquial": is_colloquial
            })
            
            logger.info(f"  术语规范化: '{term}' -> '{normalized.normalized_term}' (source: {normalized.source}, confidence: {normalized.confidence:.2f})")
        
        normalized_text = annotated_text
        for term_result in terms_for_result:
            original = term_result["original"]
            normalized = term_result["normalized"]
            if isinstance(normalized, dict):
                logger.warning(f"术语规范化结果为dict类型: original='{original}', normalized={normalized}, 跳过替换")
                continue
            if not isinstance(normalized, str):
                normalized = str(normalized)
                term_result["normalized"] = normalized
            if original and normalized != original:
                normalized_text = normalized_text.replace(original, normalized)
        
        if save_to_db and visit_id and normalized_terms:
            try:
                self.terminology_service.save_normalized_terms(normalized_terms, visit_id)
                logger.info(f"保存了 {len(normalized_terms)} 个规范化术语到数据库")
            except Exception as e:
                logger.error(f"保存规范化术语失败: {e}")
        
        stage_time = time.time() - stage_start
        logger.info(f"术语规范化完成，共规范化 {len(normalized_terms)} 个术语，耗时: {stage_time:.2f}秒")
        
        return {
            "normalized_text": normalized_text,
            "terms": terms_for_result
        }
    
    def _normalize_terms_serial(self, unique_terms: List[Dict[str, Any]]) -> List[Any]:
        """串行规范化术语"""
        normalized_terms = []
        for term_info in unique_terms:
            term = term_info.get("term", "")
            term_type = term_info.get("term_type", "unknown")
            context = term_info.get("context", "")
            
            normalized = self.terminology_service.normalize_term(term, context, term_type)
            normalized_terms.append(normalized)
        
        return normalized_terms
    
    async def _normalize_terms_parallel_en(self, unique_terms: List[Dict[str, Any]], context: str) -> List[Any]:
        """
        并行规范化术语（英文版本，跳过翻译步骤）
        
        流程：
        1. 并行UMLS检索（无需翻译）
        2. 批量LLM选择
        3. 并行获取Code
        """
        terms = [t.get("term", "") for t in unique_terms]
        contexts = {t.get("term", ""): t.get("context", context) for t in unique_terms}
        term_types = {t.get("term", ""): t.get("term_type", "unknown") for t in unique_terms}
        
        umls_results = {}
        if self.terminology_service.async_umls_client:
            search_start = time.time()
            umls_results = await self.terminology_service.async_umls_client.batch_search(
                terms,
                language="ENG"
            )
            logger.info(f"并行UMLS检索完成，耗时: {time.time() - search_start:.2f}秒")
        
        term_candidates = {}
        for term in terms:
            result = umls_results.get(term)
            if result and hasattr(result, 'candidates') and result.candidates:
                term_candidates[term] = result.candidates[:5]
        
        selections = {}
        if term_candidates and self.llm_service:
            select_start = time.time()
            selections = self.terminology_service._batch_select_candidates(term_candidates, contexts, {})
            logger.info(f"批量LLM选择完成，耗时: {time.time() - select_start:.2f}秒")
        
        code_tasks = {}
        for term in terms:
            if term in selections:
                code_tasks[term] = self.terminology_service._async_get_code_from_candidate(selections[term])
        
        code_results = {}
        if code_tasks:
            code_start = time.time()
            code_results_list = await asyncio.gather(*code_tasks.values(), return_exceptions=True)
            for term, result in zip(code_tasks.keys(), code_results_list):
                if isinstance(result, Exception):
                    logger.warning(f"获取code失败 for {term}: {result}")
                    code_results[term] = (None, None)
                else:
                    code_results[term] = result
            logger.info(f"并行获取code完成，耗时: {time.time() - code_start:.2f}秒")
        
        normalized_terms = []
        for term_info in unique_terms:
            term = term_info.get("term", "")
            term_type = term_types.get(term, "unknown")
            
            normalized = term
            confidence = 0.3
            reasoning = "无法规范化，保留原术语"
            code = None
            code_system = None
            source = "none"
            candidates_data = None
            cui = None
            
            if term in selections:
                best_candidate = selections[term]
                code, code_system = code_results.get(term, (None, None))
                
                candidates = term_candidates.get(term, [])
                candidates_data = [
                    {
                        "term": c.term,
                        "cui": c.cui,
                        "score": c.score,
                        "preferred": c.preferred
                    }
                    for c in candidates
                ]
                
                confidence = min(0.95, 0.6 + best_candidate.score * 0.35)
                reasoning = f"UMLS匹配: {term} -> {best_candidate.term} (CUI: {best_candidate.cui})"
                source = "UMLS"
                cui = best_candidate.cui
                normalized = best_candidate.term
            
            elif confidence < 0.5 and self.llm_service:
                llm_result = self.terminology_service._normalize_by_llm(term, contexts.get(term, ""))
                if llm_result and llm_result[1] > confidence:
                    normalized, confidence, reasoning = llm_result
                    source = "LLM"
            
            is_risky = confidence < 0.5
            
            normalized_term = NormalizedTerm(
                original_term=term,
                normalized_term=normalized,
                term_type=term_type,
                confidence=confidence,
                is_risky=is_risky,
                reasoning=reasoning,
                code=code,
                code_system=code_system,
                source=source,
                candidates=candidates_data,
                cui=cui
            )
            normalized_terms.append(normalized_term)
        
        return normalized_terms
