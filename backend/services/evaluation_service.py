"""
病历生成评估服务

在病历生成后自动评估结果质量
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from ..utils.logger import logger


@dataclass
class EvaluationResult:
    diagnosis_match: str
    symptom_precision: float
    symptom_recall: float
    symptom_f1: float
    soap_completeness: Dict[str, bool]


class EMREvaluationService:
    DATA_DIR = Path(__file__).parent.parent.parent / "data" / "text"
    
    def __init__(self):
        self.test_data = None
        self.test_input_data = None
        self._load_test_data()
    
    def _load_test_data(self):
        """加载测试数据集"""
        test_file = self.DATA_DIR / "test.json"
        test_input_file = self.DATA_DIR / "test_input.json"
        
        try:
            if test_file.exists():
                with open(test_file, encoding='utf-8') as f:
                    self.test_data = json.load(f)
                logger.info(f"加载测试数据集: {len(self.test_data)} 条")
            
            if test_input_file.exists():
                with open(test_input_file, encoding='utf-8') as f:
                    self.test_input_data = json.load(f)
        except Exception as e:
            logger.warning(f"加载测试数据集失败: {e}")
    
    def _normalize_text(self, text: str) -> str:
        """标准化文本"""
        if not text:
            return ""
        text = text.strip()
        text = re.sub(r'[，。、；：！？\s]', '', text)
        return text.lower()
    
    def _check_diagnosis_match(self, predicted: str, ground_truth: str) -> str:
        """检查诊断匹配程度"""
        pred_norm = self._normalize_text(predicted)
        truth_norm = self._normalize_text(ground_truth)
        
        if not pred_norm or not truth_norm:
            return "无法评估"
        
        if pred_norm == truth_norm:
            return "完全匹配"
        
        if pred_norm in truth_norm or truth_norm in pred_norm:
            return "部分匹配"
        
        common_chars = set(pred_norm) & set(truth_norm)
        if len(common_chars) >= min(len(pred_norm), len(truth_norm)) * 0.5:
            return "部分匹配"
        
        return "不匹配"
    
    def _calculate_symptom_metrics(
        self,
        predicted: List[str],
        ground_truth: List[str]
    ) -> tuple:
        """计算症状抽取指标"""
        pred_set = set(self._normalize_text(s) for s in predicted if s)
        truth_set = set(self._normalize_text(s) for s in ground_truth if s)
        
        if not pred_set and not truth_set:
            return 1.0, 1.0, 1.0
        
        if not pred_set:
            return 0.0, 0.0, 0.0
        
        if not truth_set:
            return 0.0, 0.0, 0.0
        
        intersection = pred_set & truth_set
        
        precision = len(intersection) / len(pred_set)
        recall = len(intersection) / len(truth_set)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return round(precision, 4), round(recall, 4), round(f1, 4)
    
    def _extract_symptoms_from_test(self, test_sample: Dict) -> List[str]:
        """从测试数据中提取症状"""
        symptoms = set()
        
        explicit_info = test_sample.get("explicit_info", {})
        for symptom in explicit_info.get("Symptom", []):
            symptoms.add(symptom)
        
        for turn in test_sample.get("dialogue", []):
            for symptom in turn.get("symptom_norm", []):
                symptoms.add(symptom)
        
        return list(symptoms)
    
    def _extract_symptoms_from_emr(self, emr_result: Dict) -> List[str]:
        """从生成的病历中提取症状"""
        symptoms = set()
        
        chief_complaint = emr_result.get("subjective", {}).get("chief_complaint", {}).get("value", "")
        if chief_complaint:
            symptoms.update(self._extract_symptom_keywords(chief_complaint))
        
        history = emr_result.get("subjective", {}).get("history_present_illness", {}).get("value", "")
        if history:
            symptoms.update(self._extract_symptom_keywords(history))
        
        return list(symptoms)
    
    def _extract_symptom_keywords(self, text: str) -> set:
        """从文本中提取症状关键词"""
        symptoms = set()
        
        patterns = [
            r'([^，。、；：！？\s]{2,10}?)(?=、|，|。|伴|伴发|伴有)',
            r'出现([^，。、；：！？\s]{2,8})',
            r'感到([^，。、；：！？\s]{2,8})',
            r'有([^，。、；：！？\s]{2,8}?)(?=症状|表现|感觉)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    match = match[0]
                match = match.strip()
                if match and len(match) >= 2:
                    symptoms.add(match)
        
        return symptoms
    
    def _extract_diagnosis_from_emr(self, emr_result: Dict) -> str:
        """从生成的病历中提取诊断"""
        diagnosis = emr_result.get("assessment", {}).get("diagnosis", {}).get("value", "")
        return diagnosis
    
    def _check_soap_completeness(self, emr_result: Dict) -> Dict[str, bool]:
        """检查SOAP完整性"""
        return {
            "主诉": bool(emr_result.get("subjective", {}).get("chief_complaint", {}).get("value")),
            "现病史": bool(emr_result.get("subjective", {}).get("history_present_illness", {}).get("value")),
            "体格检查": bool(emr_result.get("objective", {}).get("physical_examination", {}).get("value")),
            "诊断": bool(emr_result.get("assessment", {}).get("diagnosis", {}).get("value")),
            "治疗": bool(emr_result.get("plan", {}).get("treatment", {}).get("value"))
        }
    
    def find_matching_test_sample(self, dialogue_text: str) -> Optional[Dict]:
        """根据对话内容匹配测试样本"""
        if not self.test_input_data:
            return None
        
        dialogue_content = re.sub(r'\[[^\]]+\]:\s*', '', dialogue_text)
        dialogue_content = self._normalize_text(dialogue_content)
        
        for sample_id, sample in self.test_input_data.items():
            sample_dialogue = sample.get("dialogue", [])
            sample_text = " ".join(
                turn.get("sentence", "") for turn in sample_dialogue
            )
            sample_normalized = self._normalize_text(sample_text)
            
            if len(dialogue_content) > 30 and len(sample_normalized) > 30:
                if dialogue_content[:50] == sample_normalized[:50]:
                    return {
                        "sample_id": sample_id,
                        "test_sample": self.test_data.get(sample_id, {}),
                        "test_input_sample": sample
                    }
        
        return None
    
    def evaluate(
        self,
        emr_result: Dict,
        test_sample: Optional[Dict] = None,
        sample_id: Optional[str] = None
    ) -> Optional[EvaluationResult]:
        """评估病历生成结果"""
        if not test_sample and sample_id and self.test_data:
            test_sample = self.test_data.get(sample_id)
        
        if not test_sample:
            logger.warning("未找到测试样本，跳过评估")
            return None
        
        ground_truth_diagnosis = test_sample.get("diagnosis", "")
        ground_truth_symptoms = self._extract_symptoms_from_test(test_sample)
        
        predicted_diagnosis = self._extract_diagnosis_from_emr(emr_result)
        predicted_symptoms = self._extract_symptoms_from_emr(emr_result)
        
        diagnosis_match = self._check_diagnosis_match(predicted_diagnosis, ground_truth_diagnosis)
        precision, recall, f1 = self._calculate_symptom_metrics(predicted_symptoms, ground_truth_symptoms)
        soap_completeness = self._check_soap_completeness(emr_result)
        
        return EvaluationResult(
            diagnosis_match=diagnosis_match,
            symptom_precision=precision,
            symptom_recall=recall,
            symptom_f1=f1,
            soap_completeness=soap_completeness
        )
    
    def log_evaluation_result(
        self,
        sample_id: str,
        result: EvaluationResult,
        ground_truth_diagnosis: str = "",
        predicted_diagnosis: str = "",
        ground_truth_symptoms: List[str] = None,
        predicted_symptoms: List[str] = None
    ):
        """输出评估结果到日志"""
        logger.info("=" * 60)
        logger.info(f"病历生成评估结果 [样本ID: {sample_id}]")
        logger.info("=" * 60)
        
        logger.info(f"【诊断评估】")
        logger.info(f"  标注诊断: {ground_truth_diagnosis}")
        logger.info(f"  生成诊断: {predicted_diagnosis}")
        logger.info(f"  匹配结果: {result.diagnosis_match}")
        
        logger.info(f"【症状抽取评估】")
        if ground_truth_symptoms:
            logger.info(f"  标注症状: {', '.join(ground_truth_symptoms)}")
        if predicted_symptoms:
            logger.info(f"  生成症状: {', '.join(predicted_symptoms)}")
        logger.info(f"  准确率: {result.symptom_precision:.2%}")
        logger.info(f"  召回率: {result.symptom_recall:.2%}")
        logger.info(f"  F1分数: {result.symptom_f1:.2%}")
        
        logger.info(f"【SOAP完整性】")
        for field, is_complete in result.soap_completeness.items():
            status = "✓" if is_complete else "✗"
            logger.info(f"  {status} {field}: {'完整' if is_complete else '缺失'}")
        
        logger.info("=" * 60)
        
        if result.diagnosis_match in ["完全匹配", "部分匹配"] and result.symptom_f1 >= 0.5:
            logger.info("评估结论: 良好 ✓")
        elif result.symptom_f1 >= 0.3:
            logger.info("评估结论: 一般 △")
        else:
            logger.info("评估结论: 需改进 ✗")
        
        logger.info("=" * 60)
