import uuid
import json
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from ..models import AtomicFact

logger = logging.getLogger(__name__)


class FactService:
    def __init__(self, db: Session):
        self.db = db
        logger.info("FactService 初始化完成")

    def save_facts(self, facts: List[Dict], visit_id: str) -> List[AtomicFact]:
        saved = []
        try:
            for fact_data in facts:
                fact_id = f"fact_{visit_id}_{uuid.uuid4().hex[:12]}"

                atomic_fact = AtomicFact(
                    fact_id=fact_id,
                    visit_id=visit_id,
                    section_candidate=fact_data.get("section_candidate", ""),
                    concept_type=fact_data.get("concept_type", "other"),
                    mention=fact_data.get("mention", ""),
                    polarity=fact_data.get("polarity", "present"),
                    temporality=fact_data.get("temporality", "unknown"),
                    certainty=fact_data.get("certainty", "supported"),
                    speaker=fact_data.get("speaker", "patient"),
                    evidence_turn_ids=fact_data.get("evidence_turn_ids", []),
                    evidence_text=fact_data.get("evidence_text", []),
                    asr_risk=fact_data.get("asr_risk", "low"),
                    normalization_needed=fact_data.get("normalization_needed", True)
                )

                self.db.add(atomic_fact)
                saved.append(atomic_fact)

            self.db.commit()
            logger.info(f"批量保存 {len(saved)} 条原子事实, visit_id={visit_id}")
        except Exception as e:
            self.db.rollback()
            logger.error(f"批量保存原子事实失败: {e}")
            raise

        return saved

    def get_facts_by_visit(self, visit_id: str) -> List[AtomicFact]:
        facts = self.db.query(AtomicFact).filter(
            AtomicFact.visit_id == visit_id
        ).order_by(AtomicFact.created_at).all()
        logger.info(f"查询到 visit_id={visit_id} 的 {len(facts)} 条原子事实")
        return facts

    def get_facts_needing_normalization(self, visit_id: str) -> List[AtomicFact]:
        facts = self.db.query(AtomicFact).filter(
            AtomicFact.visit_id == visit_id,
            AtomicFact.normalization_needed == True
        ).order_by(AtomicFact.created_at).all()
        logger.info(f"查询到 visit_id={visit_id} 的 {len(facts)} 条需要规范化的原子事实")
        return facts

    def update_normalized_term(
        self,
        fact_id: str,
        normalized_term: str,
        normalized_code: str = None
    ):
        try:
            fact = self.db.query(AtomicFact).filter(
                AtomicFact.fact_id == fact_id
            ).first()

            if not fact:
                logger.warning(f"未找到 fact_id={fact_id} 的原子事实")
                return

            fact.normalized_term = normalized_term
            fact.normalized_code = normalized_code
            fact.normalization_needed = False

            self.db.commit()
            logger.info(f"更新原子事实规范化术语: fact_id={fact_id}, '{fact.mention}' -> '{normalized_term}'")
        except Exception as e:
            self.db.rollback()
            logger.error(f"更新原子事实规范化术语失败: {e}")
            raise