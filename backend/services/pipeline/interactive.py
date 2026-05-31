import json
from typing import Dict, Any, TYPE_CHECKING

from ...models import TranscriptTurn
from ...utils.logger import logger
from .utils import parse_json_response
from ..fact_service import FactService
from .evidence_enricher import EvidenceEnricher

if TYPE_CHECKING:
    from .orchestrator import PipelineOrchestrator


class InteractivePipelineService:
    def __init__(self, orchestrator: "PipelineOrchestrator"):
        self.orchestrator = orchestrator
        logger.info("InteractivePipelineService initialized")

    def process_stage(
        self,
        visit_id: str,
        stage: str,
        user_response: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        turns = self.orchestrator.db.query(TranscriptTurn).filter(
            TranscriptTurn.visit_id == visit_id
        ).order_by(TranscriptTurn.turn_index).all()

        if not turns:
            return {"error": "没有找到对话轮次"}

        segments = self.orchestrator._segment_turns(turns)
        total_segments = len(segments)

        if stage == "turn_cleaning":
            segment_index = context.get("segment_index", 0)
            segment = segments[segment_index] if segment_index < len(segments) else segments[0]

            cleaning_result = self.orchestrator._parse_cleaning_response(user_response, segment)

            if "turns" in cleaning_result:
                self.orchestrator._apply_asr_corrections(cleaning_result, segment)

            all_cleaned_turns = context.get("all_cleaned_turns", [])
            all_cleaned_turns.extend(cleaning_result.get("turns", []))

            next_stage = None
            next_prompt = None
            next_segment_index = None
            next_description = None

            if segment_index + 1 < total_segments:
                next_stage = "turn_cleaning"
                next_segment_index = segment_index + 1
                next_segment = segments[next_segment_index]
                next_prompt = self.orchestrator.prompt_manager.render(
                    "turn_cleaning",
                    transcript=self.orchestrator._format_segment(next_segment)
                )
                next_description = f"阶段1.{next_segment_index + 1}/{total_segments}: 转写清洗与角色纠错"
            else:
                next_stage = "fact_extraction"
                compact_turns = self._build_compact_turns(all_cleaned_turns)
                turns_json = json.dumps(compact_turns, ensure_ascii=False, indent=2)
                next_prompt = self.orchestrator.prompt_manager.render(
                    "fact_extraction",
                    turns_json=turns_json
                )
                logger.info(f"阶段1完成，共{len(all_cleaned_turns)}个清洗后轮次")
                next_description = f"阶段2: 事实抽取与证据绑定 (共{len(all_cleaned_turns)}个轮次，{total_segments}段)"

            return {
                "result": cleaning_result,
                "next_stage": next_stage,
                "next_prompt": next_prompt,
                "next_segment_index": next_segment_index,
                "next_description": next_description,
                "context_update": {
                    "all_cleaned_turns": all_cleaned_turns,
                    "role_mapping": {**context.get("role_mapping", {}), **cleaning_result.get("role_mapping", {})}
                }
            }

        elif stage == "fact_extraction":
            all_cleaned_turns = context.get("all_cleaned_turns", [])
            logger.info(f"收到用户输入的事实抽取结果，处理 {len(all_cleaned_turns)} 个轮次")

            parsed = parse_json_response(user_response, "事实抽取")
            facts_data = parsed.get("facts", []) if parsed else []
            logger.info(f"手动提取到 {len(facts_data)} 条事实")

            if not facts_data:
                return {
                    "result": {"error": "未能从输入中提取事实JSON"},
                    "next_stage": "fact_extraction",
                    "next_prompt": self.orchestrator.prompt_manager.render(
                        "fact_extraction",
                        turns_json=json.dumps(all_cleaned_turns, ensure_ascii=False, indent=2)
                    ),
                    "next_description": "请重新输入: 阶段2: 事实抽取与证据绑定"
                }

            so_facts = [f for f in facts_data if f.get("section_candidate") in ("S", "O")]
            a_facts = [f for f in facts_data if f.get("section_candidate") == "A"]
            p_facts = [f for f in facts_data if f.get("section_candidate") == "P"]
            logger.info(f"事实分类: S+O={len(so_facts)}, A={len(a_facts)}, P={len(p_facts)}")

            self.orchestrator._lightweight_normalize(facts_data)

            self.orchestrator._save_atomic_facts(facts_data, visit_id)
            logger.info(f"调试模式: 已保存 {len(facts_data)} 条原子事实到数据库")

            dialogue_parts = []
            for fact in so_facts:
                mention = fact.get("normalized_term") or fact.get("mention", "")
                speaker = fact.get("speaker", "unknown")
                dialogue_parts.append(f"[{speaker}]: {mention}")
            dialogue_summary = "\n".join(dialogue_parts)

            next_prompt_so = self.orchestrator.prompt_manager.render(
                "emr_generation_so",
                facts_json=json.dumps(so_facts, ensure_ascii=False, indent=2),
                dialogue_summary=dialogue_summary
            )

            return {
                "result": {"facts_count": len(facts_data), "facts": facts_data},
                "next_stage": "emr_generation_so",
                "next_prompt": next_prompt_so,
                "next_description": f"阶段3: 分节生成SO（共{len(so_facts)}条S/O事实）",
                "context_update": {
                    "facts": facts_data,
                    "so_facts": so_facts,
                    "a_facts": a_facts,
                    "p_facts": p_facts
                }
            }

        elif stage == "emr_generation_so":
            facts = context.get("facts", [])
            logger.info("收到用户输入的SO生成结果")

            parsed = parse_json_response(user_response, "SO生成")

            subjective = parsed.get("subjective", {}) if parsed else {}
            objective = parsed.get("objective", {}) if parsed else {}
            so_result = {"subjective": subjective, "objective": objective}

            a_facts = context.get("a_facts", [])
            subjective_text = json.dumps(subjective, ensure_ascii=False, indent=2)
            objective_text = json.dumps(objective, ensure_ascii=False, indent=2)

            next_prompt_assessment = self.orchestrator.prompt_manager.render(
                "emr_generation_assessment",
                subjective_text=subjective_text,
                objective_text=objective_text,
                facts_json=json.dumps(a_facts, ensure_ascii=False, indent=2)
            )

            return {
                "result": so_result,
                "next_stage": "emr_generation_assessment",
                "next_prompt": next_prompt_assessment,
                "next_description": f"阶段4-1: 生成评估（共{len(a_facts)}条A事实）",
                "context_update": {
                    "subjective": subjective,
                    "objective": objective,
                    "subjective_text": subjective_text,
                    "objective_text": objective_text,
                    "so_result": so_result
                }
            }

        elif stage == "emr_generation_assessment":
            logger.info("收到用户输入的评估生成结果")

            parsed = parse_json_response(user_response, "评估生成")
            assessment = parsed.get("assessment", {}) if parsed else {}
            assessment_items = parsed.get("assessment_items", []) if parsed else []
            assessment_text = json.dumps(assessment, ensure_ascii=False, indent=2)

            p_facts = context.get("p_facts", [])
            subjective_text = context.get("subjective_text", "{}")
            objective_text = context.get("objective_text", "{}")

            next_prompt_plan = self.orchestrator.prompt_manager.render(
                "emr_generation_plan",
                subjective_text=subjective_text,
                objective_text=objective_text,
                assessment_text=assessment_text,
                facts_json=json.dumps(p_facts, ensure_ascii=False, indent=2)
            )

            return {
                "result": {"assessment": assessment, "assessment_items": assessment_items},
                "next_stage": "emr_generation_plan",
                "next_prompt": next_prompt_plan,
                "next_description": f"阶段4-2: 生成计划（共{len(p_facts)}条P事实）",
                "context_update": {
                    "assessment": assessment,
                    "assessment_items": assessment_items,
                    "assessment_text": assessment_text
                }
            }

        elif stage == "emr_generation_plan":
            logger.info("收到用户输入的计划生成结果")

            parsed = parse_json_response(user_response, "计划生成")
            plan = parsed.get("plan", {}) if parsed else {}
            plan_items = parsed.get("plan_items", {}) if parsed else {}

            subjective = context.get("subjective", {})
            objective = context.get("objective", {})
            assessment = context.get("assessment", {})

            draft_emr = json.dumps({
                "subjective": subjective,
                "objective": objective,
                "assessment": assessment,
                "plan": plan
            }, ensure_ascii=False, indent=2)

            facts = context.get("facts", [])
            facts_table = json.dumps(facts, ensure_ascii=False, indent=2)
            role_mapping = json.dumps(context.get("role_mapping", {}), ensure_ascii=False, indent=2)

            next_prompt_verify = self.orchestrator.prompt_manager.render(
                "soap_verification",
                draft_emr=draft_emr,
                fact_table=facts_table,
                role_mapping=role_mapping
            )

            return {
                "result": {"plan": plan, "plan_items": plan_items},
                "next_stage": "verification",
                "next_prompt": next_prompt_verify,
                "next_description": f"阶段5: 核查与修订（共{len(facts)}条事实）",
                "context_update": {
                    "plan": plan,
                    "plan_items": plan_items,
                    "draft_emr": draft_emr
                }
            }

        elif stage == "verification":
            logger.info("收到用户输入的核查结果，处理完成")

            parsed = parse_json_response(user_response, "SOAP核查")
            soap_final = parsed.get("soap_final", {}) if parsed else {}
            issues = parsed.get("issues", {}) if parsed else {}

            logger.info(f"核查完成: unsupported={len(issues.get('unsupported_claims',[]))}, missing={len(issues.get('missing_critical_facts',[]))}, conflicts={len(issues.get('internal_conflicts',[]))}")

            subjective = context.get("subjective", {})
            objective = context.get("objective", {})
            assessment = context.get("assessment", {})
            plan = context.get("plan", {})
            assessment_items = context.get("assessment_items", [])
            plan_items = context.get("plan_items", {})

            emr_final = soap_final if soap_final else {
                "subjective": subjective,
                "objective": objective,
                "assessment": assessment,
                "plan": plan
            }
            emr_final["assessment_items"] = assessment_items
            emr_final["plan_items"] = plan_items

            emr_final = self.orchestrator.emr_persistence.normalize_format(emr_final)
            logger.info(f"调试模式: 病历格式归一化完成")

            fact_service = FactService(self.orchestrator.db)
            fact_records = fact_service.get_facts_by_visit(visit_id)
            logger.info(f"调试模式: 从数据库加载 {len(fact_records)} 条原子事实")

            emr_final = EvidenceEnricher.enrich(emr_final, fact_records, turns)
            logger.info(f"调试模式: 证据溯源富化完成")

            self.orchestrator.emr_persistence.save_evidence_spans_from_emr(emr_final, visit_id)
            logger.info(f"调试模式: 已保存证据溯源到数据库")

            self.orchestrator.emr_persistence.save_emr_record(emr_final, visit_id)
            logger.info(f"调试模式: 已保存病历记录到数据库: visit_id={visit_id}")

            return {
                "result": {"soap_final": soap_final, "issues": issues, "emr_saved": True},
                "next_stage": None,
                "next_prompt": None,
                "next_description": None,
                "completed": True,
                "context_update": {
                    "soap_final": soap_final,
                    "issues": issues
                }
            }

        elif stage in ("role_annotation", "field_extraction", "emr_generation"):
            return {
                "error": f"阶段 '{stage}' 已废弃，请使用新版分步流程",
                "deprecated": True
            }

        return {"error": f"未知阶段: {stage}"}

    @staticmethod
    def _build_compact_turns(all_cleaned_turns):
        compact = []
        for turn in all_cleaned_turns:
            compact.append({
                "turn_id": turn.get("turn_id"),
                "speaker_role": turn.get("speaker_role"),
                "corrected_text": turn.get("corrected_text", "")
            })
        return compact