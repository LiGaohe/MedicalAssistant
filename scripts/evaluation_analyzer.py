"""
病历生成评估结果分析工具

用于记录手动测试结果并计算评估指标
"""

import json
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass, field, asdict
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / "data" / "text"


@dataclass
class SampleResult:
    sample_id: str
    ground_truth_diagnosis: str
    predicted_diagnosis: str
    ground_truth_symptoms: List[str]
    predicted_symptoms: List[str]
    diagnosis_match: str  # "完全匹配", "部分匹配", "不匹配"
    symptom_precision: float = 0.0
    symptom_recall: float = 0.0
    symptom_f1: float = 0.0
    soap_completeness: Dict[str, bool] = field(default_factory=dict)
    notes: str = ""


def normalize_text(text: str) -> str:
    """标准化文本用于比较"""
    import re
    text = text.strip()
    text = re.sub(r'[，。、；：！？\s]', '', text)
    return text.lower()


def calculate_symptom_metrics(
    predicted: List[str],
    ground_truth: List[str]
) -> tuple:
    """计算症状抽取指标"""
    pred_set = set(normalize_text(s) for s in predicted if s)
    truth_set = set(normalize_text(s) for s in ground_truth if s)
    
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


def check_diagnosis_match(predicted: str, ground_truth: str) -> str:
    """检查诊断匹配程度"""
    pred_norm = normalize_text(predicted)
    truth_norm = normalize_text(ground_truth)
    
    if not pred_norm or not truth_norm:
        return "不匹配"
    
    if pred_norm == truth_norm:
        return "完全匹配"
    
    if pred_norm in truth_norm or truth_norm in pred_norm:
        return "部分匹配"
    
    common_chars = set(pred_norm) & set(truth_norm)
    if len(common_chars) >= min(len(pred_norm), len(truth_norm)) * 0.5:
        return "部分匹配"
    
    return "不匹配"


@dataclass
class EvaluationReport:
    total_samples: int = 0
    diagnosis_full_match: int = 0
    diagnosis_partial_match: int = 0
    diagnosis_no_match: int = 0
    avg_symptom_precision: float = 0.0
    avg_symptom_recall: float = 0.0
    avg_symptom_f1: float = 0.0
    soap_completeness_rate: Dict[str, float] = field(default_factory=dict)
    results: List[Dict] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "summary": {
                "total_samples": self.total_samples,
                "diagnosis_match_rate": {
                    "完全匹配": f"{self.diagnosis_full_match / self.total_samples * 100:.1f}%" if self.total_samples > 0 else "0%",
                    "部分匹配": f"{self.diagnosis_partial_match / self.total_samples * 100:.1f}%" if self.total_samples > 0 else "0%",
                    "不匹配": f"{self.diagnosis_no_match / self.total_samples * 100:.1f}%" if self.total_samples > 0 else "0%"
                },
                "avg_symptom_precision": f"{self.avg_symptom_precision:.2%}",
                "avg_symptom_recall": f"{self.avg_symptom_recall:.2%}",
                "avg_symptom_f1": f"{self.avg_symptom_f1:.2%}",
                "soap_completeness": {k: f"{v:.1%}" for k, v in self.soap_completeness_rate.items()}
            },
            "details": self.results
        }


def analyze_results(results: List[SampleResult]) -> EvaluationReport:
    """分析评估结果"""
    report = EvaluationReport()
    report.total_samples = len(results)
    
    total_precision = 0.0
    total_recall = 0.0
    total_f1 = 0.0
    soap_counts = {
        "主诉": 0,
        "现病史": 0,
        "体格检查": 0,
        "诊断": 0,
        "治疗": 0
    }
    
    for r in results:
        if r.diagnosis_match == "完全匹配":
            report.diagnosis_full_match += 1
        elif r.diagnosis_match == "部分匹配":
            report.diagnosis_partial_match += 1
        else:
            report.diagnosis_no_match += 1
        
        total_precision += r.symptom_precision
        total_recall += r.symptom_recall
        total_f1 += r.symptom_f1
        
        for field_name, is_complete in r.soap_completeness.items():
            if is_complete and field_name in soap_counts:
                soap_counts[field_name] += 1
        
        report.results.append(asdict(r))
    
    if report.total_samples > 0:
        report.avg_symptom_precision = total_precision / report.total_samples
        report.avg_symptom_recall = total_recall / report.total_samples
        report.avg_symptom_f1 = total_f1 / report.total_samples
        
        for field_name in soap_counts:
            report.soap_completeness_rate[field_name] = soap_counts[field_name] / report.total_samples
    
    return report


def print_report(report: EvaluationReport):
    """打印评估报告"""
    print("\n" + "=" * 60)
    print("病历生成评估报告")
    print("=" * 60)
    print(f"评估时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"样本数量: {report.total_samples}")
    print("-" * 60)
    
    print("\n【诊断匹配率】")
    print(f"  完全匹配: {report.diagnosis_full_match} ({report.diagnosis_full_match / report.total_samples * 100:.1f}%)")
    print(f"  部分匹配: {report.diagnosis_partial_match} ({report.diagnosis_partial_match / report.total_samples * 100:.1f}%)")
    print(f"  不匹配: {report.diagnosis_no_match} ({report.diagnosis_no_match / report.total_samples * 100:.1f}%)")
    
    print("\n【症状抽取指标】")
    print(f"  平均准确率: {report.avg_symptom_precision:.2%}")
    print(f"  平均召回率: {report.avg_symptom_recall:.2%}")
    print(f"  平均F1: {report.avg_symptom_f1:.2%}")
    
    print("\n【SOAP完整性】")
    for field_name, rate in report.soap_completeness_rate.items():
        status = "✓" if rate >= 0.8 else "△" if rate >= 0.5 else "✗"
        print(f"  {status} {field_name}: {rate:.1%}")
    
    print("\n" + "=" * 60)
    
    print("\n【评分标准】")
    print("  诊断匹配率 ≥ 80%: 优秀")
    print("  诊断匹配率 ≥ 60%: 良好")
    print("  诊断匹配率 < 60%: 需改进")
    print()
    print("  症状F1 ≥ 0.7: 优秀")
    print("  症状F1 ≥ 0.5: 良好")
    print("  症状F1 < 0.5: 需改进")
    print("=" * 60)


def save_report(report: EvaluationReport, output_file: str = "evaluation_report.json"):
    """保存评估报告"""
    output_path = DATA_DIR / output_file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存到: {output_path}")


def create_sample_result(
    sample_id: str,
    ground_truth_diagnosis: str,
    predicted_diagnosis: str,
    ground_truth_symptoms: List[str],
    predicted_symptoms: List[str],
    has_chief_complaint: bool = True,
    has_history: bool = True,
    has_physical: bool = False,
    has_diagnosis: bool = True,
    has_treatment: bool = True,
    notes: str = ""
) -> SampleResult:
    """创建样本评估结果（辅助函数）"""
    diagnosis_match = check_diagnosis_match(predicted_diagnosis, ground_truth_diagnosis)
    precision, recall, f1 = calculate_symptom_metrics(predicted_symptoms, ground_truth_symptoms)
    
    return SampleResult(
        sample_id=sample_id,
        ground_truth_diagnosis=ground_truth_diagnosis,
        predicted_diagnosis=predicted_diagnosis,
        ground_truth_symptoms=ground_truth_symptoms,
        predicted_symptoms=predicted_symptoms,
        diagnosis_match=diagnosis_match,
        symptom_precision=precision,
        symptom_recall=recall,
        symptom_f1=f1,
        soap_completeness={
            "主诉": has_chief_complaint,
            "现病史": has_history,
            "体格检查": has_physical,
            "诊断": has_diagnosis,
            "治疗": has_treatment
        },
        notes=notes
    )


if __name__ == "__main__":
    example_results = [
        create_sample_result(
            sample_id="10035922",
            ground_truth_diagnosis="小儿支气管炎",
            predicted_diagnosis="支气管炎",
            ground_truth_symptoms=["咳嗽", "发热", "淋巴结肿大"],
            predicted_symptoms=["咳嗽", "发热", "咳痰"],
            has_physical=True,
            notes="诊断基本准确，症状遗漏淋巴结肿大"
        ),
        create_sample_result(
            sample_id="10708561",
            ground_truth_diagnosis="小儿消化不良",
            predicted_diagnosis="消化不良",
            ground_truth_symptoms=["腹泻", "黄疸", "稀便"],
            predicted_symptoms=["腹泻", "消化不良"],
            has_physical=False,
            notes="遗漏黄疸症状"
        ),
    ]
    
    report = analyze_results(example_results)
    print_report(report)
    save_report(report)
