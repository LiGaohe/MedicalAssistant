import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


IMCS_FIELDS = ['主诉', '现病史', '辅助检查', '既往史', '诊断', '建议']

SOAP_TO_IMCS = {
    "subjective.chief_complaint": "主诉",
    "subjective.history_present_illness": "现病史",
    "subjective.past_history": "既往史",
    "objective.auxiliary_examination": "辅助检查",
    "assessment.diagnosis": "诊断",
    "plan.advice": "建议",
}


class IMCSAdapter:
    def __init__(self, dataset_path: Optional[str] = None):
        self.dataset: Dict[str, Any] = {}
        if dataset_path:
            self.load_dataset(dataset_path)

    def load_dataset(self, dataset_path: str) -> Dict[str, Any]:
        logger.info(f"Loading IMCS dataset from: {dataset_path}")

        path = Path(dataset_path)
        if not path.exists():
            logger.error(f"Dataset file not found: {dataset_path}")
            return {}

        try:
            with open(dataset_path, 'r', encoding='utf-8') as f:
                self.dataset = json.load(f)

            logger.info(f"Loaded {len(self.dataset)} samples from IMCS dataset")
            return self.dataset
        except Exception as e:
            logger.error(f"Failed to load dataset: {e}")
            return {}

    def get_sample_ids(self) -> List[str]:
        return list(self.dataset.keys())

    def get_dialogue_text(self, sample_id: str) -> str:
        sample = self.dataset.get(sample_id)
        if not sample:
            return ""

        lines = []
        if sample.get("self_report"):
            lines.append(f"【自述】{sample['self_report']}")

        for turn in sample.get("dialogue", []):
            speaker = turn.get("speaker", "")
            sentence = turn.get("sentence", "")
            lines.append(f"{speaker}：{sentence}")

        return "\n".join(lines)

    def get_reference_reports(self, sample_id: str) -> List[Dict[str, str]]:
        sample = self.dataset.get(sample_id)
        if not sample:
            return []

        reports = sample.get("report", [])
        result = []
        for report in reports:
            imcs_report = {}
            for field in IMCS_FIELDS:
                imcs_report[field] = report.get(field, "")
            result.append(imcs_report)

        return result

    def get_diagnosis(self, sample_id: str) -> str:
        sample = self.dataset.get(sample_id)
        if not sample:
            return ""
        return sample.get("diagnosis", "")

    def convert_soap_to_imcs(self, soap_emr: Dict[str, Any]) -> Dict[str, str]:
        result = {}

        subjective = soap_emr.get("subjective", {})
        if isinstance(subjective, dict):
            cc = subjective.get("chief_complaint", {})
            if isinstance(cc, dict):
                result["主诉"] = cc.get("value", "")
            elif isinstance(cc, str):
                result["主诉"] = cc

            hpi = subjective.get("history_present_illness", {})
            if isinstance(hpi, dict):
                result["现病史"] = hpi.get("value", "")
            elif isinstance(hpi, str):
                result["现病史"] = hpi.get("value", hpi) if isinstance(hpi, dict) else str(hpi)

            ph = subjective.get("past_history", {})
            if isinstance(ph, dict):
                result["既往史"] = ph.get("value", "")
            elif isinstance(ph, str):
                result["既往史"] = ph

        objective = soap_emr.get("objective", {})
        if isinstance(objective, dict):
            aux = objective.get("auxiliary_examination", {})
            if isinstance(aux, dict):
                result["辅助检查"] = aux.get("value", "")
            elif isinstance(aux, str):
                result["辅助检查"] = aux

        assessment = soap_emr.get("assessment", {})
        if isinstance(assessment, dict):
            diag = assessment.get("diagnosis", {})
            if isinstance(diag, dict):
                result["诊断"] = diag.get("value", "")
            elif isinstance(diag, str):
                result["诊断"] = diag

        plan = soap_emr.get("plan", {})
        if isinstance(plan, dict):
            advice = plan.get("advice", {})
            if isinstance(advice, dict):
                result["建议"] = advice.get("value", "")
            elif isinstance(advice, str):
                result["建议"] = advice

        for field in IMCS_FIELDS:
            if field not in result:
                result[field] = ""

        return result

    def format_imcs_report(self, report: Dict[str, str]) -> str:
        parts = []
        for field in IMCS_FIELDS:
            value = report.get(field, "")
            if value:
                parts.append(f"{field}：{value}")
        return "\n".join(parts)
