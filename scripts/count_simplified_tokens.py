"""
简化管线 Token 消耗统计脚本

专门统计简化管线（skip_verification=True）的 token 消耗。
从 app.log 中提取样本的开始和结束时间，从 llm_raw 日志中统计对应的 LLM 调用字符数。

用法:
    python scripts/count_simplified_tokens.py --app_log data/logs/app_20260531.log --llm_raw_dir data/logs/llm_raw
"""

import argparse
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "count_simplified_tokens.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_app_log_for_simplified_samples(app_log: Path) -> list:
    """从app.log中提取简化管线样本的开始和结束时间"""
    samples = []
    
    with open(app_log, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for i, line in enumerate(lines):
        start_match = re.search(r'=== 开始多阶段LLM处理.*?: (\S+) ===', line)
        if start_match:
            visit_id = start_match.group(1)
            time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if time_match:
                start_time = datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M:%S")
                samples.append({
                    "visit_id": visit_id,
                    "start_time": start_time,
                    "end_time": None,
                    "elapsed": None,
                    "config": None,
                    "line_index": i
                })
        
        config_match = re.search(r'流程控制参数: skip_cleaning=(\w+), skip_hallucination_check=(\w+), stop_after_draft=(\w+), skip_verification=(\w+)', line)
        if config_match:
            skip_cleaning = config_match.group(1) == 'True'
            skip_hallucination = config_match.group(2) == 'True'
            stop_after_draft = config_match.group(3) == 'True'
            skip_verification = config_match.group(4) == 'True'
            
            if skip_cleaning and skip_hallucination and not stop_after_draft and skip_verification:
                config_name = "简化管线"
            elif skip_cleaning and skip_hallucination and stop_after_draft:
                config_name = "端到端基线"
            else:
                config_name = "其他"
            
            for sample in reversed(samples):
                if sample["config"] is None:
                    sample["config"] = config_name
                    break
        
        end_match = re.search(r'(stop_after_draft=True, 草稿阶段完成后停止|skip_verification=True, 跳过阶段5\+6).*总耗时: (\d+\.\d+)秒', line)
        if end_match:
            elapsed = float(end_match.group(2))
            time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            if time_match:
                end_time = datetime.strptime(time_match.group(1), "%Y-%m-%d %H:%M:%S")
                for sample in reversed(samples):
                    if sample["end_time"] is None:
                        sample["end_time"] = end_time
                        sample["elapsed"] = elapsed
                        break
    
    return [s for s in samples if s["end_time"] is not None and s["config"] in ["简化管线", "端到端基线"]]


def parse_llm_raw_for_chars(llm_raw_file: Path) -> list:
    """从llm_raw日志中提取每次调用的字符数和时间"""
    calls = []
    
    with open(llm_raw_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pattern = r'\[LLM RAW RESPONSE\] call_id=(\S+), adapter=(\S+), timestamp=(\S+)\n={80}\n\[PROMPT\]\n(.*?)\n\[RESPONSE[^\]]*\]\n(.*?)\n={80}'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for match in matches:
        call_id = match[0]
        adapter = match[1]
        timestamp_str = match[2]
        prompt_text = match[3]
        response_text = match[4]
        
        try:
            date_part = timestamp_str.split('_')[0]
            time_part = timestamp_str.split('_')[1]
            base_date = datetime.strptime(date_part, "%Y%m%d")
            hour = int(time_part[:2])
            minute = int(time_part[2:4])
            second = int(time_part[4:6])
            call_time = base_date.replace(hour=hour, minute=minute, second=second)
        except Exception as e:
            logger.warning(f"时间解析失败: {timestamp_str}, {e}")
            continue
        
        prompt_chars = len(prompt_text.strip())
        response_chars = len(response_text.strip())
        total_chars = prompt_chars + response_chars
        
        calls.append({
            "call_id": call_id,
            "adapter": adapter,
            "timestamp": call_time,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "total_chars": total_chars
        })
    
    return calls


def main():
    parser = argparse.ArgumentParser(description="统计简化管线和端到端基线的token消耗")
    parser.add_argument("--app_log", default="data/logs/app_20260531.log",
                        help="应用日志文件（包含实验配置标记）")
    parser.add_argument("--llm_raw_dir", default="data/logs/llm_raw",
                        help="LLM原始日志目录")
    args = parser.parse_args()
    
    app_log = Path(args.app_log)
    llm_raw_dir = Path(args.llm_raw_dir)
    
    if not app_log.exists():
        logger.error(f"应用日志不存在: {app_log}")
        return
    
    if not llm_raw_dir.exists():
        logger.error(f"LLM日志目录不存在: {llm_raw_dir}")
        return
    
    logger.info(f"解析应用日志: {app_log}")
    samples = parse_app_log_for_simplified_samples(app_log)
    
    simplified_samples = [s for s in samples if s["config"] == "简化管线"]
    end_to_end_samples = [s for s in samples if s["config"] == "端到端基线"]
    
    logger.info(f"找到 {len(simplified_samples)} 个简化管线样本")
    logger.info(f"找到 {len(end_to_end_samples)} 个端到端基线样本")
    
    logger.info(f"解析LLM原始日志...")
    all_calls = []
    for log_file in sorted(llm_raw_dir.glob("llm_raw_*.log")):
        calls = parse_llm_raw_for_chars(log_file)
        logger.info(f"  {log_file.name}: {len(calls)} 次调用")
        all_calls.extend(calls)
    
    logger.info(f"总计 {len(all_calls)} 次 LLM 调用")
    
    def compute_stats(samples_list, all_calls_list, config_name):
        total_prompt = 0
        total_response = 0
        total_calls = 0
        total_elapsed = 0
        
        for sample in samples_list:
            start_time = sample["start_time"]
            end_time = sample["end_time"]
            sample_calls = [c for c in all_calls_list if start_time <= c["timestamp"] < end_time]
            total_calls += len(sample_calls)
            total_prompt += sum(c["prompt_chars"] for c in sample_calls)
            total_response += sum(c["response_chars"] for c in sample_calls)
            total_elapsed += sample.get("elapsed", 0)
        
        sample_count = len(samples_list)
        total_chars = total_prompt + total_response
        
        return {
            "name": config_name,
            "sample_count": sample_count,
            "call_count": total_calls,
            "prompt_chars": total_prompt,
            "response_chars": total_response,
            "total_chars": total_chars,
            "avg_chars": total_chars / sample_count if sample_count > 0 else 0,
            "avg_calls": total_calls / sample_count if sample_count > 0 else 0,
            "avg_elapsed": total_elapsed / sample_count if sample_count > 0 else 0
        }
    
    simplified_stats = compute_stats(simplified_samples, all_calls, "简化管线")
    end_to_end_stats = compute_stats(end_to_end_samples, all_calls, "端到端基线")
    
    print("\n" + "=" * 80)
    print("  Token消耗统计（简化管线 vs 端到端基线）")
    print("=" * 80)
    
    for stats in [end_to_end_stats, simplified_stats]:
        print(f"\n  [{stats['name']}]")
        print(f"    样本数:         {stats['sample_count']}")
        print(f"    平均耗时:       {stats['avg_elapsed']:.1f} 秒/样本")
        print(f"    LLM调用总数:    {stats['call_count']}")
        print(f"    平均调用次数:   {stats['avg_calls']:.1f} 次/样本")
        print(f"    总prompt字符:   {stats['prompt_chars']:,}")
        print(f"    总response字符: {stats['response_chars']:,}")
        print(f"    总字符数:       {stats['total_chars']:,}")
        print(f"    平均字符消耗:   {stats['avg_chars']:,.0f} 字符/样本 ≈ {stats['avg_chars']/1000:.1f}K")
    
    print("\n" + "=" * 80)
    print("  说明: 中文场景下，1字符≈1-2token")
    print("=" * 80)


if __name__ == "__main__":
    main()