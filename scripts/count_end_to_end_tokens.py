"""
端到端基线和质量评估 Token 统计脚本

专门统计端到端基线（草稿阶段就截止，没有"多阶段LLM处理完成"标记）的 token 消耗。
同时统计质量评估（llm_evaluation）的 token 消耗。

用法:
    python scripts/count_end_to_end_tokens.py --log_dir data/logs/llm_raw --date 20260531
"""

import argparse
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / "count_end_to_end_tokens.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_llm_raw_log(llm_raw_file: Path, target_date: str, time_range: tuple) -> list:
    """从llm_raw日志中提取指定日期和时间范围的每次调用字符数"""
    calls = []
    
    start_hour, start_minute, end_hour, end_minute = time_range
    
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
        
        date_part = timestamp_str.split('_')[0]
        if date_part != target_date:
            continue
        
        try:
            time_part = timestamp_str.split('_')[1]
            hour = int(time_part[:2])
            minute = int(time_part[2:4])
            second = int(time_part[4:6])
            call_time = datetime.strptime(date_part, "%Y%m%d").replace(hour=hour, minute=minute, second=second)
            
            if not (start_hour <= hour < end_hour or (hour == start_hour and minute >= start_minute) or (hour == end_hour and minute < end_minute)):
                if hour < start_hour or (hour == start_hour and minute < start_minute):
                    continue
                if hour > end_hour or (hour == end_hour and minute >= end_minute):
                    continue
        except Exception as e:
            logger.warning(f"时间解析失败: {timestamp_str}, {e}")
            continue
        
        prompt_chars = len(prompt_text.strip())
        response_chars = len(response_text.strip())
        total_chars = prompt_chars + response_chars
        
        call_type = "unknown"
        prompt_lower = prompt_text.lower()
        if "soap格式撰写病历草稿" in prompt_lower or "按soap格式撰写病历" in prompt_lower:
            call_type = "draft"
        elif "提取病历生成的关键事实清单" in prompt_lower or "从医患对话中提取" in prompt_lower and "关键事实" in prompt_lower:
            call_type = "completeness_extract"
        elif "检查以下关键事实在病历中的覆盖情况" in prompt_lower or "覆盖情况" in prompt_lower:
            call_type = "completeness_check"
        elif "病历质量评估专家" in prompt_lower and ("五维度" in prompt_lower or "评分" in prompt_lower):
            call_type = "quality"
        elif "医疗病历安全风险评估" in prompt_lower or "高风险错误" in prompt_lower or "安全风险评估" in prompt_lower:
            call_type = "safety"
        
        calls.append({
            "call_id": call_id,
            "adapter": adapter,
            "timestamp": call_time,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "total_chars": total_chars,
            "call_type": call_type
        })
    
    return calls


def main():
    parser = argparse.ArgumentParser(description="统计端到端基线和质量评估的token消耗")
    parser.add_argument("--log_dir", default="data/logs/llm_raw",
                        help="LLM原始日志目录")
    parser.add_argument("--date", default="20260531",
                        help="目标日期（格式：YYYYMMDD）")
    parser.add_argument("--start_time", default="11:06",
                        help="实验开始时间（格式：HH:MM）")
    parser.add_argument("--end_time", default="11:16",
                        help="实验结束时间（格式：HH:MM）")
    parser.add_argument("--sample_count", type=int, default=10,
                        help="样本数量")
    args = parser.parse_args()
    
    log_dir = Path(args.log_dir)
    if not log_dir.exists():
        logger.error(f"日志目录不存在: {log_dir}")
        return
    
    start_hour = int(args.start_time.split(':')[0])
    start_minute = int(args.start_time.split(':')[1])
    end_hour = int(args.end_time.split(':')[0])
    end_minute = int(args.end_time.split(':')[1])
    time_range = (start_hour, start_minute, end_hour, end_minute)
    
    all_calls = []
    for log_file in sorted(log_dir.glob("llm_raw_*.log")):
        calls = parse_llm_raw_log(log_file, args.date, time_range)
        if calls:
            logger.info(f"  {log_file.name}: {len(calls)} 次调用（时间范围={args.start_time}-{args.end_time}）")
            all_calls.extend(calls)
    
    logger.info(f"总计 {len(all_calls)} 次 LLM 调用（时间范围={args.start_time}-{args.end_time}）")
    
    draft_calls = [c for c in all_calls if c["call_type"] == "draft"]
    eval_calls = [c for c in all_calls if c["call_type"] in ["completeness_extract", "completeness_check", "quality", "safety"]]
    
    draft_total_chars = sum(c["total_chars"] for c in draft_calls)
    draft_prompt_chars = sum(c["prompt_chars"] for c in draft_calls)
    draft_response_chars = sum(c["response_chars"] for c in draft_calls)
    
    eval_total_chars = sum(c["total_chars"] for c in eval_calls)
    eval_prompt_chars = sum(c["prompt_chars"] for c in eval_calls)
    eval_response_chars = sum(c["response_chars"] for c in eval_calls)
    
    sample_count = args.sample_count
    
    print("\n" + "=" * 80)
    print(f"  Token消耗统计（时间范围: {args.start_time}-{args.end_time}）")
    print("=" * 80)
    
    print(f"\n  [端到端基线 - 草稿生成阶段]")
    print(f"    LLM调用次数:    {len(draft_calls)}")
    print(f"    总prompt字符:   {draft_prompt_chars:,}")
    print(f"    总response字符: {draft_response_chars:,}")
    print(f"    总字符数:       {draft_total_chars:,}")
    if len(draft_calls) > 0:
        print(f"    平均字符消耗:   {draft_total_chars / len(draft_calls):,.0f} 字符/调用")
        print(f"    平均每样本:     {draft_total_chars / sample_count:,.0f} 字符/样本 ≈ {draft_total_chars / sample_count / 1000:.1f}K")
    
    print(f"\n  [质量评估阶段]")
    print(f"    LLM调用次数:    {len(eval_calls)}")
    print(f"    总prompt字符:   {eval_prompt_chars:,}")
    print(f"    总response字符: {eval_response_chars:,}")
    print(f"    总字符数:       {eval_total_chars:,}")
    if len(eval_calls) > 0:
        print(f"    平均字符消耗:   {eval_total_chars / len(eval_calls):,.0f} 字符/调用")
        print(f"    平均每样本:     {eval_total_chars / sample_count:,.0f} 字符/样本 ≈ {eval_total_chars / sample_count / 1000:.1f}K")
    
    print(f"\n  [总计]")
    total_chars = draft_total_chars + eval_total_chars
    total_calls = len(draft_calls) + len(eval_calls)
    print(f"    LLM调用次数:    {total_calls}")
    print(f"    总字符数:       {total_chars:,}")
    print(f"    平均每样本:     {total_chars / sample_count:,.0f} 字符/样本 ≈ {total_chars / sample_count / 1000:.1f}K")
    
    print("\n" + "=" * 80)
    print("  说明: 中文场景下，1字符≈1-2token")
    print("  端到端基线：草稿生成阶段（stop_after_draft=True）")
    print("  质量评估：完整性+质量+安全评估（额外的LLM调用）")
    print("=" * 80)


if __name__ == "__main__":
    main()