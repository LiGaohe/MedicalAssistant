"""
从日志提取标准管线和完整管线的病历并计算质量评估指标

用法:
  python scripts/evaluate_pipeline_from_logs.py --log data/logs/app_20260531.log --config standard --output data/experiments/results/standard_quality.json
  python scripts/evaluate_pipeline_from_logs.py --log data/logs/app_20260530.log --config full --output data/experiments/results/full_quality.json
"""

import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

REQUIRED_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness"],
    "objective": [],
    "assessment": ["diagnosis"],
    "plan": ["treatment"],
}

ALL_FIELDS = {
    "subjective": ["chief_complaint", "history_present_illness", "denied_symptoms", "past_history"],
    "objective": ["physical_examination", "auxiliary_examination"],
    "assessment": ["diagnosis", "differential_diagnosis"],
    "plan": ["treatment", "advice"],
}

SOAP_SECTIONS = ["subjective", "objective", "assessment", "plan"]


def extract_emrs_from_log(log_path, config_type):
    """从日志提取病历结果
    
    Args:
        log_path: 日志文件路径
        config_type: 'standard' 或 'full'
    
    Returns:
        list of dicts with sample_id, emr_result, etc.
    """
    emrs = []
    
    config_markers = {
        "standard": "skip_hallucination_check=True, stop_after_draft=False, skip_verification=True",
        "full": "skip_hallucination_check=False",
    }
    
    marker = config_markers.get(config_type)
    if not marker:
        print(f"未知配置类型: {config_type}")
        return []
    
    print(f"查找配置标记: {marker}")
    
    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    current_sample_id = None
    current_visit_id = None
    in_target_config = False
    emr_json_buffer = []
    collecting_emr = False
    emr_start_line = None
    
    for i, line in enumerate(lines):
        time_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        current_time = time_match.group(1) if time_match else None
        
        visit_match = re.search(r'开始多阶段LLM处理.*?:\s*(exp_\d+_\w+)', line)
        if visit_match:
            current_visit_id = visit_match.group(1)
            sid_match = re.search(r'exp_(\d+)_', current_visit_id)
            if sid_match:
                current_sample_id = sid_match.group(1)
            print(f"[{i}] 发现visit_id: {current_visit_id}, sample_id: {current_sample_id}")
        
        if "流程控制参数:" in line:
            if marker in line:
                in_target_config = True
                print(f"[{i}] 匹配配置标记, in_target_config=True")
            else:
                in_target_config = False
                print(f"[{i}] 不匹配配置标记, in_target_config=False")
        
        if in_target_config and "LLM API原始响应" in line:
            print(f"[{i}] in_target_config=True, 检查是否有subjective...")
            has_subjective = '"subjective"' in line or '"subjective":' in line or 'subjective' in line
            print(f"[{i}] has_subjective={has_subjective}, sample_id={current_sample_id}, visit_id={current_visit_id}")
            if has_subjective:
                collecting_emr = True
                emr_start_line = i
                
                content_start = line.find('"content": "') + len('"content": "')
                if content_start > 0:
                    content_end = line.rfind('", "reasoning_content"')
                    if content_end == -1:
                        content_end = line.rfind('", "finish_reason"')
                    if content_end == -1:
                        content_end = line.find('"}], "usage"')
                    
                    if content_end > content_start:
                        json_str = line[content_start:content_end]
                        json_str = json_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
                        
                        try:
                            emr_json = json.loads(json_str)
                            if 'subjective' in emr_json:
                                emr = {
                                    "sample_id": current_sample_id,
                                    "visit_id": current_visit_id,
                                    "time": current_time,
                                    "config": config_type,
                                    "emr_result": emr_json,
                                    "line_number": i,
                                }
                                emrs.append(emr)
                                print(f"[{i}] 提取成功: sample_id={current_sample_id}")
                                collecting_emr = False
                        except json.JSONDecodeError as e:
                            print(f"[{i}] JSON解析失败: {e}, 尝试多行提取")
                            emr_json_buffer = [json_str]
        
        if collecting_emr and i > emr_start_line:
            emr_json_buffer.append(line.strip())
            combined = ''.join(emr_json_buffer)
            
            try:
                emr_json = json.loads(combined)
                if 'subjective' in emr_json:
                    emr = {
                        "sample_id": current_sample_id,
                        "visit_id": current_visit_id,
                        "time": current_time,
                        "config": config_type,
                        "emr_result": emr_json,
                        "line_number": emr_start_line,
                    }
                    emrs.append(emr)
                    print(f"[{i}] 多行提取成功: sample_id={current_sample_id}")
                    collecting_emr = False
                    emr_json_buffer = []
            except json.JSONDecodeError:
                pass
    
    unique_emrs = {}
    for emr in emrs:
        sid = emr.get("sample_id")
        if sid:
            existing = unique_emrs.get(sid)
            if existing is None or emr.get("line_number", 0) > existing.get("line_number", 0):
                unique_emrs[sid] = emr
    
    return list(unique_emrs.values())


def compute_quality_metrics(emr, sample_diagnosis=None):
    """计算质量指标"""
    if not emr or not isinstance(emr, dict):
        return None
    
    present_sections = 0
    for section in SOAP_SECTIONS:
        sec = emr.get(section, {})
        if isinstance(sec, dict):
            text = sec.get("text", "")
            has_fields = any(
                sec.get(field, {}).get("value", "") 
                for field in ALL_FIELDS.get(section, [])
            )
            if text or has_fields:
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
                    diag_val_lower = diag_val.lower()
                    sample_diag_lower = sample_diagnosis.lower()
                    diagnosis_match = sample_diag_lower in diag_val_lower or diag_val_lower in sample_diag_lower
                    
                    if not diagnosis_match:
                        key_terms = {
                            "小儿支气管炎": ["支气管炎", "气管炎"],
                            "小儿腹泻": ["腹泻"],
                            "小儿便秘": ["便秘"],
                            "新生儿黄疸": ["黄疸"],
                            "上呼吸道感染": ["上呼吸道感染", "呼吸道感染", "咽部感染"],
                        }
                        for key, terms in key_terms.items():
                            if key in sample_diagnosis or sample_diagnosis in key:
                                for term in terms:
                                    if term in diag_val_lower:
                                        diagnosis_match = True
                                        break
    
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
                    diagnoses[str(sid)] = diag
    return diagnoses


def main():
    parser = argparse.ArgumentParser(description="从日志提取病历并计算质量指标")
    parser.add_argument("--log", required=True, help="日志文件路径")
    parser.add_argument("--config", required=True, choices=["standard", "full"], help="配置类型")
    parser.add_argument("--samples", default="data/experiments/test_samples.json", help="样本文件路径")
    parser.add_argument("--output", default="", help="输出文件路径")
    args = parser.parse_args()
    
    print(f"从日志提取 {args.config} 管线病历: {args.log}")
    
    emrs = extract_emrs_from_log(args.log, args.config)
    print(f"提取到 {len(emrs)} 个病历")
    
    diagnoses = load_sample_diagnoses(args.samples)
    
    results = []
    for emr_data in emrs:
        sid = emr_data.get("sample_id")
        emr = emr_data.get("emr_result")
        diag = diagnoses.get(sid, "")
        
        metrics = compute_quality_metrics(emr, diag)
        
        result = {
            "sample_id": sid,
            "config": args.config,
            "visit_id": emr_data.get("visit_id"),
            "time": emr_data.get("time"),
            "emr_result": emr,
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
        diagnosis_matches = [1 if r["quality_metrics"].get("diagnosis_match") else 0 
                            for r in results if r.get("quality_metrics") and r["quality_metrics"].get("diagnosis_match") is not None]
        
        avg_structure = sum(structure_rates) / len(structure_rates) if structure_rates else 0
        avg_field_missing = sum(field_missing_rates) / len(field_missing_rates) if field_missing_rates else 0
        avg_diagnosis_match = sum(diagnosis_matches) / len(diagnosis_matches) if diagnosis_matches else 0
        
        print(f"\n{'='*60}")
        print(f"  {args.config} 管线质量指标汇总 ({len(results)} 样本)")
        print(f"{'='*60}")
        print(f"  结构完整率: {avg_structure*100:.1f}%")
        print(f"  字段缺失率: {avg_field_missing*100:.1f}%")
        print(f"  诊断一致性: {avg_diagnosis_match*100:.1f}% ({len(diagnosis_matches)} 样本有诊断标签)")
    else:
        avg_structure = 0
        avg_field_missing = 0
        avg_diagnosis_match = 0
        diagnosis_matches = []
        print("未提取到任何病历")
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump({
                "config": args.config,
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