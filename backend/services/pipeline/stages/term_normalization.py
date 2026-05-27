# DEPRECATED: 六阶段流水线已重构为四阶段。选择性术语规范化不再使用，术语规范融入直接草稿生成prompt。
import time
from typing import Dict, Any, List

from ..base import PipelineContext, PipelineStage
from ....models import AtomicFact
from ....utils.logger import logger
from ...terminology_service import TerminologyService


class TermNormalizationStage(PipelineStage):
    def stage_name(self) -> str:
        return "选择性术语规范化"

    def execute(self, ctx: PipelineContext) -> Dict[str, Any]:
        logger.info(f">>> 阶段3: {self.stage_name()}（基于事实表）")
        stage_start = time.time()

        fact_records = ctx.fact_records
        role_mapping = ctx.all_role_mappings
        visit_id = ctx.visit_id
        save_to_db = ctx.save_evidence

        qualifying_facts = [
            f for f in fact_records
            if f.normalization_needed and f.mention and f.mention.strip()
        ]
        logger.info(f"共 {len(fact_records)} 条事实，其中 {len(qualifying_facts)} 条需要规范化")

        if not qualifying_facts:
            logger.info("没有需要规范化的事实，跳过术语规范化阶段")
            result = {
                "terms": [],
                "processed_count": 0,
                "skipped_count": len(fact_records),
                "total_count": len(fact_records)
            }
            ctx.normalized_result = result
            return result

        terminology_service = TerminologyService(ctx.db, ctx.llm_service, language=ctx.language)

        terms_for_result = []
        processed_count = 0
        skipped_count = 0
        use_batch = True

        if use_batch and len(qualifying_facts) > 1:
            logger.info(f"[BATCH_MODE] Using batch normalization for {len(qualifying_facts)} facts")

            terms_to_normalize = [
                {"term": fact.mention, "type": fact.concept_type or "unknown"}
                for fact in qualifying_facts
            ]

            batch_results = terminology_service.batch_normalize_terms(
                terms=terms_to_normalize,
                context=""
            )

            for fact in qualifying_facts:
                try:
                    result = batch_results.get(fact.mention)
                    if not result:
                        logger.warning(f"No batch result for '{fact.mention}', using fallback")
                        result = terminology_service.normalize_single_term(
                            term=fact.mention,
                            context="",
                            term_type=fact.concept_type or "unknown"
                        )

                    term_type = fact.concept_type or "unknown"

                    logger.info(
                        f"  事实规范化: fact_id={fact.fact_id}, "
                        f"'{fact.mention}' -> '{result.normalized_term}' "
                        f"(source: {result.source}, confidence: {result.confidence:.2f})"
                    )

                    terms_for_result.append({
                        "fact_id": fact.fact_id,
                        "original": fact.mention,
                        "normalized": result.normalized_term,
                        "category": term_type,
                        "source": result.source,
                        "confidence": result.confidence,
                        "cui": result.cui,
                        "code": result.code,
                        "code_system": result.code_system,
                        "section_candidate": fact.section_candidate
                    })

                    if save_to_db and ctx.db:
                        fact.normalized_term = result.normalized_term
                        fact.normalized_code = result.code
                        fact.normalization_needed = False

                    processed_count += 1

                except Exception as e:
                    logger.error(f"规范化事实 {fact.fact_id} (mention='{fact.mention}') 失败: {e}")
                    skipped_count += 1
        else:
            logger.info("[SERIAL_MODE] Using serial normalization")

            for fact in qualifying_facts:
                try:
                    term_type = fact.concept_type or "unknown"
                    result = terminology_service.normalize_single_term(
                        term=fact.mention,
                        context="",
                        term_type=term_type
                    )

                    logger.info(
                        f"  事实规范化: fact_id={fact.fact_id}, "
                        f"'{fact.mention}' -> '{result.normalized_term}' "
                        f"(source: {result.source}, confidence: {result.confidence:.2f})"
                    )

                    terms_for_result.append({
                        "fact_id": fact.fact_id,
                        "original": fact.mention,
                        "normalized": result.normalized_term,
                        "category": term_type,
                        "source": result.source,
                        "confidence": result.confidence,
                        "cui": result.cui,
                        "code": result.code,
                        "code_system": result.code_system,
                        "section_candidate": fact.section_candidate
                    })

                    if save_to_db and ctx.db:
                        fact.normalized_term = result.normalized_term
                        fact.normalized_code = result.code
                        fact.normalization_needed = False

                    processed_count += 1

                except Exception as e:
                    logger.error(f"规范化事实 {fact.fact_id} (mention='{fact.mention}') 失败: {e}")
                    skipped_count += 1

        if save_to_db and ctx.db:
            try:
                ctx.db.commit()
                logger.info(f"已更新 {processed_count} 条原子事实的规范化结果到数据库")
            except Exception as e:
                ctx.db.rollback()
                logger.error(f"保存原子事实规范化结果失败: {e}")

        stage_time = time.time() - stage_start
        logger.info(
            f"选择性术语规范化完成: 处理 {processed_count} 条, "
            f"跳过 {skipped_count} 条, 总事实 {len(fact_records)} 条, "
            f"耗时: {stage_time:.2f}秒"
        )

        result = {
            "terms": terms_for_result,
            "processed_count": processed_count,
            "skipped_count": skipped_count,
            "total_count": len(fact_records)
        }
        ctx.normalized_result = result
        return result