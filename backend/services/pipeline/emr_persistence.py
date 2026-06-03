import time
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from ...models import TranscriptTurn, EMRRecord, EvidenceSpan, Visit
from ...utils.logger import logger


class EMRPersistence:
    def __init__(self, db: Session, validation_service):
        self.db = db
        self.validation_service = validation_service

    def save_evidence_spans(
        self,
        extraction_result: Dict[str, Any],
        visit_id: str,
        emr_result: Dict[str, Any] = None
    ) -> int:
        saved_count = 0

        self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).delete()

        for section in ["subjective", "objective", "assessment", "plan"]:
            if section not in extraction_result:
                continue
            
            section_data = extraction_result[section]
            
            # 处理section级别的evidence_traces
            if isinstance(section_data, dict):
                section_evidence_traces = section_data.get("evidence_traces", [])
                section_text = section_data.get("text", "")
                
                if section_evidence_traces:
                    logger.info(f"save_evidence_spans: 处理section级别evidence_traces, section={section}, traces数={len(section_evidence_traces)}")
                    for trace in section_evidence_traces:
                        turn_id = trace.get("turn_id")
                        turn_index = trace.get("turn_index")

                        if turn_id is None and turn_index is not None:
                            turn = self.db.query(TranscriptTurn).filter(
                                TranscriptTurn.visit_id == visit_id,
                                TranscriptTurn.turn_index == turn_index
                            ).first()
                            if turn:
                                turn_id = turn.turn_id
                                logger.debug(f"通过turn_index找到turn_id: turn_index={turn_index}, turn_id={turn_id}")

                        if turn_id is None:
                            logger.warning(f"证据溯源跳过: 无法找到对应的turn_id, section={section}, content={trace.get('content', '')[:30]}...")
                            continue

                        evidence = EvidenceSpan(
                            visit_id=visit_id,
                            turn_id=turn_id,
                            field_type=section,  # 使用section名称作为field_type
                            field_value=section_text,
                            content=trace.get("content", ""),
                            turn_text=trace.get("turn_text", ""),
                            start_char=trace.get("start_char"),
                            end_char=trace.get("end_char"),
                            confidence=trace.get("confidence", 0.8),
                            score=trace.get("confidence", 0.8),
                            reasoning=f"来源: {trace.get('speaker', 'unknown')}"
                        )
                        self.db.add(evidence)
                        saved_count += 1

            for field_name, field_data in extraction_result[section].items():
                if field_name in ("text", "evidence_traces"):
                    continue
                if not isinstance(field_data, dict):
                    continue

                evidence_traces = field_data.get("evidence_traces", [])

                field_value = None
                if emr_result and section in emr_result:
                    field_info = emr_result[section].get(field_name, {})
                    if isinstance(field_info, dict):
                        field_value = field_info.get("value", "")
                    elif isinstance(field_info, str):
                        field_value = field_info

                for trace in evidence_traces:
                    turn_id = trace.get("turn_id")
                    turn_index = trace.get("turn_index")

                    if turn_id is None and turn_index is not None:
                        turn = self.db.query(TranscriptTurn).filter(
                            TranscriptTurn.visit_id == visit_id,
                            TranscriptTurn.turn_index == turn_index
                        ).first()
                        if turn:
                            turn_id = turn.turn_id
                            logger.debug(f"通过turn_index找到turn_id: turn_index={turn_index}, turn_id={turn_id}")

                    if turn_id is None:
                        logger.warning(f"证据溯源跳过: 无法找到对应的turn_id, field={field_name}, content={trace.get('content', '')[:30]}...")
                        continue

                    evidence = EvidenceSpan(
                        visit_id=visit_id,
                        turn_id=turn_id,
                        field_type=field_name,
                        field_value=field_value,
                        content=trace.get("content", ""),
                        turn_text=trace.get("turn_text", ""),
                        start_char=trace.get("start_char"),
                        end_char=trace.get("end_char"),
                        confidence=trace.get("confidence", 0.8),
                        score=trace.get("confidence", 0.8),
                        reasoning=f"来源: {trace.get('speaker', 'unknown')}"
                    )

                    self.db.add(evidence)
                    saved_count += 1

        try:
            self.db.commit()
            logger.info(f"保存了 {saved_count} 条证据溯源记录到数据库")
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存证据溯源记录失败: {e}")

        return saved_count

    def save_emr_record(
        self,
        emr_result: Dict[str, Any],
        visit_id: str,
        record_type: str = "llm_generated",
        draft_text: str = None
    ) -> Optional[EMRRecord]:
        """
        保存病历记录到数据库
        
        Args:
            emr_result: EMR JSON数据
            visit_id: 访问ID
            record_type: 记录类型，默认为"llm_generated"，草稿可使用"llm_draft"
            draft_text: 草稿文本（可选）
            
        Returns:
            EMRRecord对象或None（保存失败时）
        """
        try:
            visit = self.db.query(Visit).filter(Visit.visit_id == visit_id).first()
            language = visit.language if visit and visit.language else "zh"

            validation_result = self.validation_service.validate(emr_result, language=language)
            validation_errors = self.validation_service.to_dict(validation_result)

            max_version = self.db.query(EMRRecord).filter(
                EMRRecord.visit_id == visit_id
            ).count()

            new_version = max_version + 1

            emr_record = EMRRecord(
                visit_id=visit_id,
                version=new_version,
                record_type=record_type,
                emr_json=emr_result,
                evidence_mapping=None,
                validation_errors=validation_errors,
                draft_text=draft_text
            )

            self.db.add(emr_record)
            self.db.commit()

            logger.info(f"保存病历记录成功: visit_id={visit_id}, version={new_version}, record_type={record_type}, 验证评分: {validation_result.score:.2%}")
            return emr_record

        except Exception as e:
            self.db.rollback()
            logger.error(f"保存病历记录失败: {e}")
            return None

    def normalize_format(self, emr_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        将分节生成的新格式归一化为前端兼容的旧格式。
        
        前端 displaySection() 期望每个子字段为 {value, evidence_traces} 格式。
        新prompt输出的是直接字符串，需要包装。
        Assessment 从 assessment_items 构建 diagnosis 字段。
        Plan 从 plan_items 构建 treatment 和 advice 字段。
        """
        result = dict(emr_result)

        subject_section = dict(result.get("subjective", {}))
        objective_section = dict(result.get("objective", {}))
        assessment_section = dict(result.get("assessment", {}))
        plan_section = dict(result.get("plan", {}))
        
        # 保留section级别的evidence_traces
        logger.info(f"normalize_format: 原始section evidence_traces数: "
                    f"subjective={len(subject_section.get('evidence_traces', []))}, "
                    f"objective={len(objective_section.get('evidence_traces', []))}, "
                    f"assessment={len(assessment_section.get('evidence_traces', []))}, "
                    f"plan={len(plan_section.get('evidence_traces', []))}")

        # 如果section只有text字段，将text内容填充到必填字段（用于验证）
        section_text_to_fields = {
            "subjective": ["chief_complaint", "history_present_illness"],
            "objective": ["physical_examination", "auxiliary_examination"],
            "assessment": ["diagnosis"],
            "plan": ["treatment"]
        }
        
        for section_data, section_name in [
            (subject_section, "subjective"),
            (objective_section, "objective"),
            (assessment_section, "assessment"),
            (plan_section, "plan")
        ]:
            # 检查是否只有text字段
            has_only_text = (
                "text" in section_data and 
                section_data.get("text") and
                len([k for k in section_data.keys() if k not in ("text", "evidence_traces")]) == 0
            )
            
            if has_only_text:
                text_content = section_data.get("text", "")
                # 将text内容填充到必填字段
                for field_name in section_text_to_fields.get(section_name, []):
                    if field_name not in section_data:
                        section_data[field_name] = {"value": text_content, "evidence_traces": []}
                logger.info(f"normalize_format: section={section_name} 只有text，已填充到必填字段")

        for section_data, section_name in [
            (subject_section, "subjective"),
            (objective_section, "objective")
        ]:
            for field, val in list(section_data.items()):
                if field in ("text", "evidence_traces"):
                    continue
                if isinstance(val, str):
                    section_data[field] = {"value": val or "", "evidence_traces": []}

        assessment_items = result.get("assessment_items", [])
        if assessment_items:
            explicit_diags = [item for item in assessment_items if item.get("diagnosis_type") == "explicit_diagnosis"]
            suspected_diags = [item for item in assessment_items if item.get("diagnosis_type") == "suspected_diagnosis"]
            symptom_assessments = [item for item in assessment_items if item.get("diagnosis_type") == "symptom_based_assessment"]

            diagnosis_parts = []
            for diag in explicit_diags:
                diagnosis_parts.append(diag.get("text", ""))
            for diag in suspected_diags:
                diagnosis_parts.append(diag.get("text", ""))
            for diag in symptom_assessments:
                diagnosis_parts.append(diag.get("text", ""))

            diagnosis_value = "；".join(filter(None, diagnosis_parts))
            if diagnosis_value:
                assessment_section["diagnosis"] = {"value": diagnosis_value, "evidence_traces": []}

        plan_items = result.get("plan_items", {})
        if plan_items:
            medications = plan_items.get("medications", [])
            tests = plan_items.get("tests", [])
            follow_up = plan_items.get("follow_up", {})
            education = plan_items.get("education", {})

            treatment_parts = []
            for med in medications:
                if isinstance(med, dict):
                    parts = [med.get("name", "")]
                    dosage = med.get("dosage", "")
                    freq = med.get("frequency", "")
                    duration = med.get("duration", "")
                    detail = " ".join(filter(None, [dosage, freq, duration]))
                    if detail:
                        parts.append(detail)
                    treatment_parts.append(" ".join(filter(None, parts)))
            for test in tests:
                if isinstance(test, dict):
                    name = test.get("name", "")
                    reason = test.get("reason", "")
                    if name:
                        treatment_parts.append(f"{name}（{reason}）" if reason else name)

            treatment_value = "；".join(filter(None, treatment_parts))
            if treatment_value:
                plan_section["treatment"] = {"value": treatment_value, "evidence_traces": []}

            advice_parts = []
            if isinstance(follow_up, dict) and follow_up.get("text"):
                advice_parts.append(follow_up["text"])
            if isinstance(education, dict) and education.get("text"):
                advice_parts.append(education["text"])

            advice_value = "；".join(filter(None, advice_parts))
            if advice_value:
                plan_section["advice"] = {"value": advice_value, "evidence_traces": []}

        result["subjective"] = subject_section
        result["objective"] = objective_section
        result["assessment"] = assessment_section
        result["plan"] = plan_section

        logger.info(f"EMR格式归一化完成"
                    f", assessment_items={len(assessment_items)}"
                    f", plan_medications={len(plan_items.get('medications', [])) if plan_items else 0}"
                    f", plan_tests={len(plan_items.get('tests', [])) if plan_items else 0}")
        return result

    def save_evidence_spans_from_emr(
        self,
        emr_result: Dict[str, Any],
        visit_id: str
    ) -> int:
        logger.info(f"保存证据溯源记录到EvidenceSpan表: visit_id={visit_id}")

        self.db.query(EvidenceSpan).filter(
            EvidenceSpan.visit_id == visit_id
        ).delete()

        saved_count = 0
        field_to_section_name = {}
        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = emr_result.get(section_name, {})
            for field_name in section.keys():
                if field_name not in ("text", "evidence_traces"):
                    field_to_section_name[field_name] = section_name

        for section_name in ["subjective", "objective", "assessment", "plan"]:
            section = emr_result.get(section_name, {})
            
            # 处理section级别的evidence_traces
            section_evidence_traces = section.get("evidence_traces", [])
            section_text = section.get("text", "")
            
            if section_evidence_traces:
                logger.info(f"处理section级别evidence_traces: section={section_name}, traces数={len(section_evidence_traces)}")
                for trace in section_evidence_traces:
                    if not isinstance(trace, dict):
                        logger.warning(f"Skipping non-dict trace: {type(trace)} - {trace}")
                        continue

                    evidence = EvidenceSpan(
                        visit_id=visit_id,
                        turn_id=trace.get("turn_id"),
                        field_type=section_name,  # 使用section名称作为field_type
                        field_value=section_text,
                        content=trace.get("content", ""),
                        turn_text=trace.get("turn_text", ""),
                        confidence=trace.get("confidence", 0.8),
                        score=trace.get("confidence", 0.8),
                        reasoning=f"来源: {trace.get('speaker', 'unknown')}"
                    )
                    self.db.add(evidence)
                    saved_count += 1
            
            # 处理字段级别的evidence_traces
            for field_name, field_data in section.items():
                if field_name in ("text", "evidence_traces"):
                    continue
                if not isinstance(field_data, dict):
                    continue

                traces = field_data.get("evidence_traces", [])
                field_value = field_data.get("value", "")

                for trace in traces:
                    if not isinstance(trace, dict):
                        logger.warning(f"Skipping non-dict trace: {type(trace)} - {trace}")
                        continue

                    evidence = EvidenceSpan(
                        visit_id=visit_id,
                        turn_id=trace.get("turn_id"),
                        field_type=field_name,
                        field_value=field_value,
                        content=trace.get("content", ""),
                        turn_text=trace.get("turn_text", ""),
                        confidence=trace.get("confidence", 0.8),
                        score=trace.get("confidence", 0.8),
                        reasoning=f"来源: {trace.get('speaker', 'unknown')}"
                    )
                    self.db.add(evidence)
                    saved_count += 1

        try:
            self.db.commit()
            logger.info(f"保存了 {saved_count} 条证据溯源记录到EvidenceSpan表")
        except Exception as e:
            self.db.rollback()
            logger.error(f"保存证据溯源记录失败: {e}")
            return 0

        return saved_count

    def template_generation(
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
            subjective_text.append(f"主诉：{chief_complaint}")
        if history:
            subjective_text.append(f"现病史：{history}")
        if past_history:
            subjective_text.append(f"既往史：{past_history}")

        objective_text = []
        if physical:
            objective_text.append(f"体格检查：{physical}")
        if auxiliary:
            objective_text.append(f"辅助检查：{auxiliary}")

        assessment_text = f"诊断：{diagnosis}" if diagnosis else "诊断：待定"

        plan_text = []
        if treatment:
            plan_text.append(f"治疗方案：{treatment}")
        if advice:
            plan_text.append(f"医嘱：{advice}")

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
            self.save_evidence_spans(extraction_result, visit_id, result)
            self.save_emr_record(result, visit_id)

        return result