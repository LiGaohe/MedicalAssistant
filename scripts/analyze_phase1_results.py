"""分析第一阶段实验结果"""
import json
import os
from pathlib import Path
from collections import defaultdict

def analyze_config(jsonl_file):
    """分析单个配置的结果"""
    samples = []
    empty_emr_count = 0
    partial_emr_count = 0
    full_emr_count = 0
    has_evaluation_count = 0
    diagnosis_match_count = 0
    
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            samples.append(data)
            
            # 检查EMR内容
            emr_result = data.get('emr_result', {})
            field_missing_rate = data.get('quality_metrics', {}).get('field_missing_rate', 0)
            
            if field_missing_rate == 1.0:
                empty_emr_count += 1
            elif field_missing_rate >= 0.5:
                partial_emr_count += 1
            else:
                full_emr_count += 1
            
            # 检查评估结果
            llm_evaluation = data.get('llm_evaluation')
            if llm_evaluation and llm_evaluation.get('consistency'):
                has_evaluation_count += 1
            
            # 检查诊断匹配
            diagnosis_match = data.get('quality_metrics', {}).get('diagnosis_match')
            if diagnosis_match is not None:
                diagnosis_match_count += 1
    
    return {
        'total': len(samples),
        'empty_emr': empty_emr_count,
        'partial_emr': partial_emr_count,
        'full_emr': full_emr_count,
        'has_evaluation': has_evaluation_count,
        'diagnosis_match_count': diagnosis_match_count,
        'samples': samples
    }

def main():
    phase1_dir = Path('data/experiments/results/phase1')
    
    configs = [
        ('end_to_end', '端到端基线'),
        ('full', '完整管线'),
        ('simplified', '简化管线'),
        ('standard', '标准管线'),
        ('no_term_norm', '无术语规范化'),
        ('no_hallucination', '无幻觉检测'),
        ('no_verification', '无后验证'),
        ('no_field_revision', '无字段修订'),
        ('full_ablation', '完整消融')
    ]
    
    print("=" * 80)
    print("第一阶段实验结果分析")
    print("=" * 80)
    print()
    
    results = {}
    
    for config_key, config_name in configs:
        jsonl_file = phase1_dir / f'results_{config_key}_20260602_000457.jsonl'
        if jsonl_file.exists():
            result = analyze_config(jsonl_file)
            results[config_key] = result
            
            print(f"{config_name} ({config_key}):")
            print(f"  总样本数: {result['total']}")
            print(f"  完整EMR: {result['full_emr']}")
            print(f"  部分空EMR (field_missing_rate >= 0.5): {result['partial_emr']}")
            print(f"  完全空EMR (field_missing_rate = 1.0): {result['empty_emr']}")
            print(f"  有LLM评估: {result['has_evaluation']}")
            print(f"  有诊断匹配评估: {result['diagnosis_match_count']}")
            print()
    
    # 分析异常样本
    print("=" * 80)
    print("异常样本分析")
    print("=" * 80)
    print()
    
    # 找出所有配置中的异常样本ID
    abnormal_samples = defaultdict(dict)
    
    for config_key, result in results.items():
        for sample in result['samples']:
            sample_id = sample['sample_id']
            field_missing_rate = sample.get('quality_metrics', {}).get('field_missing_rate', 0)
            
            if field_missing_rate >= 0.5:
                abnormal_samples[sample_id][config_key] = {
                    'field_missing_rate': field_missing_rate,
                    'diagnosis_match': sample.get('quality_metrics', {}).get('diagnosis_match'),
                    'has_evaluation': sample.get('llm_evaluation') is not None
                }
    
    print(f"异常样本总数: {len(abnormal_samples)}")
    print()
    
    # 按异常类型分类
    all_empty = []  # 所有配置都完全空
    some_empty = []  # 某些配置空
    partial_empty = []  # 部分字段空
    
    for sample_id, configs_data in abnormal_samples.items():
        if all(c['field_missing_rate'] == 1.0 for c in configs_data.values()):
            all_empty.append(sample_id)
        elif any(c['field_missing_rate'] == 1.0 for c in configs_data.values()):
            some_empty.append(sample_id)
        else:
            partial_empty.append(sample_id)
    
    print(f"所有配置都完全空的样本: {len(all_empty)}")
    print(f"  样本ID: {all_empty}")
    print()
    
    print(f"某些配置完全空的样本: {len(some_empty)}")
    print(f"  样本ID: {some_empty}")
    print()
    
    print(f"部分字段空的样本: {len(partial_empty)}")
    print(f"  样本ID: {partial_empty}")
    print()
    
    # 详细分析端到端配置的异常
    print("=" * 80)
    print("端到端配置详细分析")
    print("=" * 80)
    print()
    
    end_to_end_result = results.get('end_to_end', {})
    print(f"端到端配置总样本数: {end_to_end_result['total']}")
    print(f"为什么只有20个样本（而不是30个）？")
    print()
    
    # 检查端到端配置中哪些样本ID不在其他配置中
    all_sample_ids = set()
    for config_key, result in results.items():
        if config_key != 'end_to_end':
            for sample in result['samples']:
                all_sample_ids.add(sample['sample_id'])
    
    end_to_end_ids = set(s['sample_id'] for s in end_to_end_result['samples'])
    missing_in_end_to_end = all_sample_ids - end_to_end_ids
    
    print(f"其他配置中的样本ID总数: {len(all_sample_ids)}")
    print(f"端到端配置中的样本ID总数: {len(end_to_end_ids)}")
    print(f"端到端配置缺失的样本ID: {len(missing_in_end_to_end)}")
    print(f"  缺失样本ID: {sorted(missing_in_end_to_end)}")
    print()
    
    # 分析完整管线的异常
    print("=" * 80)
    print("完整管线详细分析")
    print("=" * 80)
    print()
    
    full_result = results.get('full', {})
    print(f"完整管线总样本数: {full_result['total']}")
    print(f"完整管线有诊断匹配评估的样本数: {full_result['diagnosis_match_count']}")
    print(f"为什么只有14个正常样本？")
    print()
    
    # 分析简化管线的异常
    print("=" * 80)
    print("简化管线详细分析")
    print("=" * 80)
    print()
    
    simplified_result = results.get('simplified', {})
    print(f"简化管线总样本数: {simplified_result['total']}")
    print(f"简化管线有诊断匹配评估的样本数: {simplified_result['diagnosis_match_count']}")
    print(f"为什么只有19个正常样本？")
    print()

if __name__ == '__main__':
    main()