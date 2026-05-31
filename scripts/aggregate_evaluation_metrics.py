"""
聚合评估指标脚本

从评估结果文件中提取并计算：
- 结构完整率
- 字段缺失率
- 诊断一致性
- 关键召回率
- 遗漏率
- 文档质量评分
- 安全风险

用法:
  python scripts/aggregate_evaluation_metrics.py --input data/experiments/results/results_simplified_20260531_113741_eval_20260531_122842.jsonl
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict

def load_jsonl(path):
    entries = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries

def aggregate_metrics(entries):
    stats = {
        'structure_completeness': [],
        'field_missing_rate': [],
        'diagnosis_match': [],
        'recall_rate': [],
        'omission_rate': [],
        'quality_score': [],
        'has_high_risk': [],
    }
    
    for entry in entries:
        qm = entry.get('quality_metrics', {})
        if qm:
            stats['structure_completeness'].append(qm.get('structure_completeness', 0))
            stats['field_missing_rate'].append(qm.get('field_missing_rate', 0))
            dm = qm.get('diagnosis_match')
            if dm is not None:
                stats['diagnosis_match'].append(1 if dm else 0)
        
        llm_eval = entry.get('llm_evaluation', {})
        if llm_eval:
            completeness = llm_eval.get('completeness') or {}
            summary = completeness.get('summary') or {}
            if summary:
                stats['recall_rate'].append(summary.get('recall_rate', 0))
                omission = 1 - summary.get('recall_rate', 0)
                stats['omission_rate'].append(omission)
            
            quality = llm_eval.get('quality') or {}
            if quality:
                stats['quality_score'].append(quality.get('total_score', 0))
            
            safety = llm_eval.get('safety') or {}
            if safety:
                stats['has_high_risk'].append(1 if safety.get('has_high_risk', False) else 0)
    
    result = {}
    for key, values in stats.items():
        if values:
            result[key] = {
                'count': len(values),
                'mean': sum(values) / len(values),
                'values': values
            }
        else:
            result[key] = {'count': 0, 'mean': 0, 'values': []}
    
    return result

def format_percentage(value):
    return f"{value * 100:.1f}"

def main():
    parser = argparse.ArgumentParser(description="聚合评估指标")
    parser.add_argument("--input", required=True, help="输入JSONL文件路径")
    parser.add_argument("--output", default="", help="输出文件路径（可选）")
    args = parser.parse_args()
    
    entries = load_jsonl(args.input)
    if not entries:
        print("未找到任何条目")
        return
    
    config_name = entries[0].get('config', '未知配置')
    stats = aggregate_metrics(entries)
    
    print(f"\n{'='*60}")
    print(f"  配置: {config_name}")
    print(f"  样本数: {len(entries)}")
    print(f"{'='*60}")
    
    print("\n【文档质量层】")
    sc = stats['structure_completeness']
    if sc['count'] > 0:
        print(f"  结构完整率: {format_percentage(sc['mean'])}% ({sc['count']} 样本)")
    
    fm = stats['field_missing_rate']
    if fm['count'] > 0:
        print(f"  字段缺失率: {format_percentage(fm['mean'])}% ({fm['count']} 样本)")
    
    dm = stats['diagnosis_match']
    if dm['count'] > 0:
        print(f"  诊断一致性: {format_percentage(dm['mean'])}% ({dm['count']} 样本)")
    
    print("\n【完整性层】")
    rr = stats['recall_rate']
    if rr['count'] > 0:
        print(f"  关键召回率: {format_percentage(rr['mean'])}% ({rr['count']} 样本)")
    
    om = stats['omission_rate']
    if om['count'] > 0:
        print(f"  遗漏率: {format_percentage(om['mean'])}% ({om['count']} 样本)")
    
    print("\n【文档质量评分】")
    qs = stats['quality_score']
    if qs['count'] > 0:
        print(f"  平均质量评分: {qs['mean']:.1f}/10 ({qs['count']} 样本)")
    
    print("\n【安全风险】")
    hr = stats['has_high_risk']
    if hr['count'] > 0:
        high_risk_count = sum(hr['values'])
        print(f"  高风险样本数: {high_risk_count}/{hr['count']} ({format_percentage(high_risk_count/hr['count'])}%)")
    
    if args.output:
        output_data = {
            'config': config_name,
            'sample_count': len(entries),
            'metrics': {
                'structure_completeness_pct': format_percentage(stats['structure_completeness']['mean']),
                'field_missing_rate_pct': format_percentage(stats['field_missing_rate']['mean']),
                'diagnosis_match_pct': format_percentage(stats['diagnosis_match']['mean']),
                'recall_rate_pct': format_percentage(stats['recall_rate']['mean']),
                'omission_rate_pct': format_percentage(stats['omission_rate']['mean']),
                'quality_score_avg': stats['quality_score']['mean'],
                'high_risk_count': sum(stats['has_high_risk']['values']),
            }
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")

if __name__ == "__main__":
    main()