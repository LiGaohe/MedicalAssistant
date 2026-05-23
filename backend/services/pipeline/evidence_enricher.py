import time
from typing import Dict, Any, List
from ...models import TranscriptTurn, AtomicFact
from ...utils.logger import logger


class EvidenceEnricher:
    @staticmethod
    def build_traces_from_fact_ids(
        fact_ids: set,
        fact_by_id: Dict[str, AtomicFact],
        turn_by_index: Dict[int, TranscriptTurn]
    ) -> List[Dict[str, Any]]:
        traces = []
        seen_turn_ids = set()

        for fid in fact_ids:
            fact = fact_by_id.get(fid)
            if not fact:
                continue

            turn_ids = fact.evidence_turn_ids or []
            evidence_texts = fact.evidence_text or []

            for i, tid in enumerate(turn_ids):
                if tid in seen_turn_ids:
                    continue
                seen_turn_ids.add(tid)

                turn = turn_by_index.get(tid)
                if not turn:
                    continue

                trace = {
                    "turn_id": turn.turn_id,
                    "turn_index": turn.turn_index,
                    "turn_text": turn.text,
                    "speaker": turn.corrected_speaker or turn.speaker,
                    "original_speaker": turn.speaker,
                    "speaker_corrected": bool(
                        turn.corrected_speaker
                        and turn.corrected_speaker != turn.speaker
                    ),
                    "content": evidence_texts[i] if i < len(evidence_texts) else turn.text[:100],
                    "confidence": 0.8
                }
                traces.append(trace)

        logger.info(f"从 {len(fact_ids)} 个fact_id构建了 {len(traces)} 条证据溯源")
        return traces

    @staticmethod
    def enrich(
        emr_result: Dict[str, Any],
        fact_records: List[AtomicFact],
        turns: List[TranscriptTurn]
    ) -> Dict[str, Any]:
        logger.info("开始证据溯源富化")
        enrichment_start = time.time()

        fact_by_id = {f.fact_id: f for f in fact_records}
        turn_by_index = {t.turn_index: t for t in turns}

        so_used_fact_ids = emr_result.get("so_used_fact_ids", [])
        assessment_items = emr_result.get("assessment_items", [])
        plan_items = emr_result.get("plan_items", {})

        logger.info(
            f"证据溯源输入: so_fact_ids={len(so_used_fact_ids)}, "
            f"assessment_items={len(assessment_items)}, "
            f"plan_items_keys={list(plan_items.keys()) if plan_items else []}"
        )

        _b = EvidenceEnricher.build_traces_from_fact_ids

        s_fact_ids = set()
        o_fact_ids = set()
        for fid in so_used_fact_ids:
            fact = fact_by_id.get(fid)
            if fact:
                if fact.section_candidate == "S":
                    s_fact_ids.add(fid)
                elif fact.section_candidate == "O":
                    o_fact_ids.add(fid)

        s_has_subsection = any(
            fact_by_id.get(fid).subsection
            for fid in s_fact_ids
            if fact_by_id.get(fid)
        ) if s_fact_ids else False
        o_has_subsection = any(
            fact_by_id.get(fid).subsection
            for fid in o_fact_ids
            if fact_by_id.get(fid)
        ) if o_fact_ids else False

        llm_s_field_fact_ids = {}
        s_field_names = [
            "chief_complaint", "history_present_illness",
            "past_history", "denied_symptoms"
        ]
        subject_section = dict(emr_result.get("subjective", {}))
        for field in s_field_names:
            field_data = subject_section.get(field)
            if isinstance(field_data, dict):
                traces = field_data.get("evidence_traces", [])
                if isinstance(traces, list) and traces:
                    fids = set()
                    for t in traces:
                        if isinstance(t, str):
                            fids.add(t)
                        elif isinstance(t, dict):
                            fids.add(t.get("fact_id", ""))
                    if fids:
                        llm_s_field_fact_ids[field] = fids

        if llm_s_field_fact_ids:
            logger.info(
                f"使用LLM SO阶段的per-field证据分配: "
                f"{dict((k, len(v)) for k, v in llm_s_field_fact_ids.items())}"
            )
            for field in s_field_names:
                if field in subject_section and isinstance(subject_section[field], dict):
                    field_fids = llm_s_field_fact_ids.get(field, set())
                    subject_section[field]["evidence_traces"] = _b(
                        field_fids, fact_by_id, turn_by_index
                    )
        elif s_has_subsection:
            s_field_fact_ids = {}
            for fid in s_fact_ids:
                fact = fact_by_id.get(fid)
                if fact and fact.subsection:
                    s_field_fact_ids.setdefault(fact.subsection, set()).add(fid)

            for field in s_field_names:
                if field in subject_section and isinstance(subject_section[field], dict):
                    field_fids = s_field_fact_ids.get(field, set())
                    subject_section[field]["evidence_traces"] = _b(
                        field_fids, fact_by_id, turn_by_index
                    )
        else:
            s_evidence_traces = _b(
                s_fact_ids, fact_by_id, turn_by_index
            )
            for field in s_field_names:
                if field in subject_section and isinstance(subject_section[field], dict):
                    subject_section[field]["evidence_traces"] = s_evidence_traces

        llm_o_field_fact_ids = {}
        o_field_names = ["physical_examination", "auxiliary_examination"]
        objective_section = dict(emr_result.get("objective", {}))
        for field in o_field_names:
            field_data = objective_section.get(field)
            if isinstance(field_data, dict):
                traces = field_data.get("evidence_traces", [])
                if isinstance(traces, list) and traces:
                    fids = set()
                    for t in traces:
                        if isinstance(t, str):
                            fids.add(t)
                        elif isinstance(t, dict):
                            fids.add(t.get("fact_id", ""))
                    if fids:
                        llm_o_field_fact_ids[field] = fids

        if llm_o_field_fact_ids:
            logger.info(
                f"使用LLM SO阶段的per-field证据分配: "
                f"{dict((k, len(v)) for k, v in llm_o_field_fact_ids.items())}"
            )
            for field in o_field_names:
                if field in objective_section and isinstance(objective_section[field], dict):
                    field_fids = llm_o_field_fact_ids.get(field, set())
                    objective_section[field]["evidence_traces"] = _b(
                        field_fids, fact_by_id, turn_by_index
                    )
        elif o_has_subsection:
            o_field_fact_ids = {}
            for fid in o_fact_ids:
                fact = fact_by_id.get(fid)
                if fact and fact.subsection:
                    o_field_fact_ids.setdefault(fact.subsection, set()).add(fid)

            for field in o_field_names:
                if field in objective_section and isinstance(objective_section[field], dict):
                    field_fids = o_field_fact_ids.get(field, set())
                    objective_section[field]["evidence_traces"] = _b(
                        field_fids, fact_by_id, turn_by_index
                    )
        else:
            o_evidence_traces = _b(
                o_fact_ids, fact_by_id, turn_by_index
            )
            for field in o_field_names:
                if field in objective_section and isinstance(objective_section[field], dict):
                    objective_section[field]["evidence_traces"] = o_evidence_traces

        diagnosis_fact_ids = set()
        for item in assessment_items:
            if isinstance(item, dict):
                sids = item.get("supporting_fact_ids", [])
                diagnosis_fact_ids.update(sids)
        a_evidence_traces = _b(
            diagnosis_fact_ids, fact_by_id, turn_by_index
        )

        assessment_section = dict(emr_result.get("assessment", {}))
        if "diagnosis" in assessment_section and isinstance(assessment_section["diagnosis"], dict):
            assessment_section["diagnosis"]["evidence_traces"] = a_evidence_traces

        treatment_fact_ids = set()
        advice_fact_ids = set()

        if isinstance(plan_items, dict):
            for med in plan_items.get("medications", []):
                if isinstance(med, dict):
                    treatment_fact_ids.update(med.get("used_fact_ids", []))
            for test in plan_items.get("tests", []):
                if isinstance(test, dict):
                    treatment_fact_ids.update(test.get("used_fact_ids", []))
            follow_up = plan_items.get("follow_up", {})
            if isinstance(follow_up, dict):
                advice_fact_ids.update(follow_up.get("used_fact_ids", []))
            education = plan_items.get("education", {})
            if isinstance(education, dict):
                advice_fact_ids.update(education.get("used_fact_ids", []))

        t_evidence_traces = _b(
            treatment_fact_ids, fact_by_id, turn_by_index
        )
        adv_evidence_traces = _b(
            advice_fact_ids, fact_by_id, turn_by_index
        )

        plan_section = dict(emr_result.get("plan", {}))
        if "treatment" in plan_section and isinstance(plan_section["treatment"], dict):
            plan_section["treatment"]["evidence_traces"] = t_evidence_traces
        if "advice" in plan_section and isinstance(plan_section["advice"], dict):
            plan_section["advice"]["evidence_traces"] = adv_evidence_traces

        emr_result["subjective"] = subject_section
        emr_result["objective"] = objective_section
        emr_result["assessment"] = assessment_section
        emr_result["plan"] = plan_section

        s_total = sum(
            len(traces) for field_data in subject_section.values()
            if isinstance(field_data, dict)
            for traces in [field_data.get("evidence_traces", [])]
        )
        o_total = sum(
            len(traces) for field_data in objective_section.values()
            if isinstance(field_data, dict)
            for traces in [field_data.get("evidence_traces", [])]
        )
        total_traces = (
            s_total + o_total
            + len(a_evidence_traces)
            + len(t_evidence_traces)
            + len(adv_evidence_traces)
        )
        logger.info(
            f"证据溯源富化完成: S={s_total}, O={o_total}, "
            f"A={len(a_evidence_traces)}, P_T={len(t_evidence_traces)}, P_Adv={len(adv_evidence_traces)}, "
            f"总计={total_traces}, 耗时={time.time() - enrichment_start:.2f}秒"
        )

        return emr_result