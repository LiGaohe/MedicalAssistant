"""
从日志提取端到端基线草稿并重新计算质量评估指标

端到端基线的草稿输出格式为自由文本SOAP:
{
  "S（主观症状）": "...",
  "O（客观体征）": "...",
  "A（评估诊断）": "...",
  "P（治疗计划）": "..."
}

需要转换为结构化格式以计算质量指标。

用法:
  python scripts/evaluate_end_to_end_from_logs.py --log data/logs/app_20260531.log --output data/experiments/results/end_to_end_quality_metrics.json
"""

import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

SOAP_SECTION_MAP = {
    "S（主观症状）": "subjective",
    "O（客观体征）": "objective",
    "A（评估诊断）": "assessment",
    "P（治疗计划）": "plan",
    "S": "subjective",
    "O": "objective",
    "A": "assessment",
    "P": "plan",
}

REQUIRED_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness"],
    "objective": [],
    "assessment": ["diagnosis"],
    "plan": ["treatment"],
}

ALL_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness", "past_history"],
    "objective": ["physical_examination", "auxiliary_examination"],
    "assessment": ["diagnosis", "differential_diagnosis"],
    "plan": ["treatment", "advice"],
}


def extract_drafts_from_log(log_path, start_time=None, end_time=None):
    """从日志提取端到端基线的草稿内容"""
    drafts = []
    
    with open(log_path, 'r', encoding='utf-8') as f:
        current_sample_id = None
        current_time = None
        
        for line in f:
            time_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if time_match:
                current_time = time_match.group(1)
            
            sample_match = re.search(r'exp_(\d+)_', line)
            if sample_match:
                current_sample_id = sample_match.group(1)
                print(f"发现sample_id: {current_sample_id}")
            
            sample_match2 = re.search(r'test_e2e_(\d+)_', line)
            if sample_match2:
                current_sample_id = sample_match2.group(1)
                print(f"发现sample_id: {current_sample_id}")
            
            if 'LLM API原始响应' in line and 'S（主观症状）' in line:
                time_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                if time_match:
                    current_time = time_match.group(1)
                
                content_start = line.find('"content": "') + len('"content": "')
                content_end = line.rfind('", "reasoning_content"')
                if content_end == -1:
                    content_end = line.rfind('", "finish_reason"')
                if content_end == -1:
                    content_end = line.find('"}], "usage"')
                
                if content_start > 0 and content_end > content_start:
                    json_str = line[content_start:content_end]
                    json_str = json_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                    
                    try:
                        draft_json = json.loads(json_str)
                        if 'S（主观症状）' in draft_json or 'S' in draft_json:
                            draft = {
                                "sample_id": current_sample_id,
                                "time": current_time,
                                "raw_draft": draft_json,
                            }
                            drafts.append(draft)
                            print(f"提取成功: sample_id={current_sample_id}")
                    except json.JSONDecodeError as e:
                        print(f"JSON解析失败: {e}")
    
    return drafts


def convert_draft_to_structured(draft):
    """将自由文本草稿转换为结构化格式"""
    raw = draft.get("raw_draft", {})
    
    s_data = raw.get("S（主观症状）", raw.get("S", ""))
    o_data = raw.get("O（客观体征）", raw.get("O", ""))
    a_data = raw.get("A（评估诊断）", raw.get("A", ""))
    p_data = raw.get("P（治疗计划）", raw.get("P", ""))
    
    if isinstance(s_data, str):
        s_text = s_data
        s_chief_complaint = ""
        s_history = s_data
    else:
        s_text = s_data.get("主诉", "") + " " + s_data.get("现病史", "") + " " + s_data.get("否认症状", "")
        s_chief_complaint = s_data.get("主诉", "")
        s_history = s_data.get("现病史", "")
    
    if isinstance(o_data, str):
        o_text = o_data
        o_physical = ""
        o_auxiliary = o_data
    else:
        o_text = o_data.get("体格检查", "") + " " + o_data.get("辅助检查", "")
        o_physical = o_data.get("体格检查", "")
        o_auxiliary = o_data.get("辅助检查", "")
    
    if isinstance(a_data, str):
        a_text = a_data
        a_diagnosis = a_data
    else:
        a_text = a_data.get("诊断", "")
        a_diagnosis = a_data.get("诊断", "")
    
    if isinstance(p_data, str):
        p_text = p_data
        p_treatment = p_data
        p_advice = ""
    else:
        p_text = p_data.get("治疗方案", "") + " " + p_data.get("医嘱", "")
        p_treatment = p_data.get("治疗方案", "")
        p_advice = p_data.get("医嘱", "")
    
    structured = {
        "subjective": {
            "text": s_text.strip(),
            "chief_complaint": {"value": s_chief_complaint.strip(), "source_turn_indices": []},
            "history_present_illness": {"value": s_history.strip(), "source_turn_indices": []},
            "past_history": {"value": "", "source_turn_indices": []},
        },
        "objective": {
            "text": o_text.strip(),
            "physical_examination": {"value": o_physical.strip(), "source_turn_indices": []},
            "auxiliary_examination": {"value": o_auxiliary.strip(), "source_turn_indices": []},
        },
        "assessment": {
            "text": a_text.strip(),
            "diagnosis": {"value": a_diagnosis.strip(), "source_turn_indices": []},
            "differential_diagnosis": {"value": "", "source_turn_indices": []},
        },
        "plan": {
            "text": p_text.strip(),
            "treatment": {"value": p_treatment.strip(), "source_turn_indices": []},
            "advice": {"value": p_advice.strip(), "source_turn_indices": []},
        },
    }
    
    return structured


def compute_quality_metrics(emr, sample_diagnosis=None):
    """计算质量指标"""
    if not emr or not isinstance(emr, dict):
        return None
    
    SOAP_SECTIONS = ["subjective", "objective", "assessment", "plan"]
    
    present_sections = 0
    for section in SOAP_SECTIONS:
        sec = emr.get(section, {})
        text = sec.get("text", "") if isinstance(sec, dict) else ""
        if text and len(text.strip()) > 0:
            present_sections += 1
    
    structure_completeness = present_sections / len(SOAP_SECTIONS)
    
    total_required = 0
    missing_required = 0
    
    for section, fields in REQUIRED_FIELDS.items():
        sec = emr.get(section, {})
        if not isinstance(sec, dict):
            continue
        for field in fields:
            total_required += 1
            fd = sec.get(field, {})
            val = fd.get("value", "") if isinstance(fd, dict) else ""
            if not val or not str(val).strip():
                missing_required += 1
    
    field_missing_rate = missing_required / total_required if total_required > 0 else 0
    
    diagnosis_match = None
    if sample_diagnosis:
        assessment = emr.get("assessment", {})
        if isinstance(assessment, dict):
            diag_field = assessment.get("diagnosis", {})
            if isinstance(diag_field, dict):
                diag_val = str(diag_field.get("value", "")).strip()
                if diag_val:
                    diagnosis_match = sample_diagnosis in diag_val or diag_val in sample_diagnosis
    
    return {
        "structure_completeness": round(structure_completeness, 4),
        "present_sections": present_sections,
        "total_sections": len(SOAP_SECTIONS),
        "field_missing_rate": round(field_missing_rate, 4),
        "missing_required_fields": missing_required,
        "total_required_fields": total_required,
        "diagnosis_match": diagnosis_match,
    }


def load_sample_diagnoses(samples_file):
    """加载样本诊断标签"""
    diagnoses = {}
    if Path(samples_file).exists():
        with open(samples_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for sample in data.get("samples", []):
                sid = sample.get("sample_id")
                diag = sample.get("diagnosis", "")
                if sid:
                    diagnoses[sid] = diag
    return diagnoses


def main():
    parser = argparse.ArgumentParser(description="从日志提取端到端基线草稿并计算质量指标")
    parser.add_argument("--log", required=True, help="日志文件路径")
    parser.add_argument("--samples", default="data/experiments/test_samples.json", help="样本文件路径（用于诊断标签）")
    parser.add_argument("--output", default="", help="输出文件路径")
    parser.add_argument("--start_time", default="2026-05-31 11:06:44", help="开始时间")
    parser.add_argument("--end_time", default="2026-05-31 11:20:00", help="结束时间")
    args = parser.parse_args()
    
    print(f"从日志提取端到端基线草稿: {args.log}")
    
    drafts = extract_drafts_from_log(args.log)
    print(f"提取到 {len(drafts)} 个草稿")
    
    diagnoses = load_sample_diagnoses(args.samples)
    
    results = []
    for draft in drafts:
        sid = draft.get("sample_id")
        structured = convert_draft_to_structured(draft)
        diag = diagnoses.get(sid, "")
        
        metrics = compute_quality_metrics(structured, diag)
        
        result = {
            "sample_id": sid,
            "config": "端到端基线",
            "time": draft.get("time"),
            "emr_result": structured,
            "quality_metrics": metrics,
            "diagnosis": diag,
        }
        results.append(result)
        
        if metrics:
            print(f"  {sid}: 结构完整率={metrics['structure_completeness']*100:.0f}%, "
                  f"字段缺失率={metrics['field_missing_rate']*100:.0f}%, "
                  f"诊断一致性={metrics.get('diagnosis_match')}")
    
    if results:
        structure_rates = [r["quality_metrics"]["structure_completeness"] for r in results if r.get("quality_metrics")]
        field_missing_rates = [r["quality_metrics"]["field_missing_rate"] for r in results if r.get("quality_metrics")]
        diagnosis_matches = [1 if r["quality_metrics"].get("diagnosis_match") else 0 for r in results if r.get("quality_metrics") and r["quality_metrics"].get("diagnosis_match") is not None]
        
        avg_structure = sum(structure_rates) / len(structure_rates) if structure_rates else 0
        avg_field_missing = sum(field_missing_rates) / len(field_missing_rates) if field_missing_rates else 0
        avg_diagnosis_match = sum(diagnosis_matches) / len(diagnosis_matches) if diagnosis_matches else 0
        
        print(f"\n{'='*60}")
        print(f"  端到端基线质量指标汇总 ({len(results)} 样本)")
        print(f"{'='*60}")
        print(f"  结构完整率: {avg_structure*100:.1f}%")
        print(f"  字段缺失率: {avg_field_missing*100:.1f}%")
        print(f"  诊断一致性: {avg_diagnosis_match*100:.1f}% ({len(diagnosis_matches)} 样本有诊断标签)")
    else:
        avg_structure = 0
        avg_field_missing = 0
        avg_diagnosis_match = 0
        diagnosis_matches = []
        print("未提取到任何草稿")
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump({
                "config": "端到端基线",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "total": len(results),
                "summary": {
                    "avg_structure_completeness": round(avg_structure, 4) if results else 0,
                    "avg_field_missing_rate": round(avg_field_missing, 4) if results else 0,
                    "avg_diagnosis_match": round(avg_diagnosis_match, 4) if diagnosis_matches else 0,
                },
                "results": results,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")


if __name__ == "__main__":
    main()