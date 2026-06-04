"""
验证流式处理修改的脚本

检查所有Pipeline阶段是否正确使用 generate_stream_to_response()
"""

import re
from pathlib import Path

def check_stream_usage():
    """检查所有Pipeline阶段文件的LLM调用方式"""
    stages_dir = Path("backend/services/pipeline/stages")
    
    # 活跃文件列表
    active_files = [
        "direct_soap_generation.py",
        "turn_cleaning.py",
        "evidence_mapping.py",
        "hallucination_check.py",
        "claim_verification.py",
        "field_revision.py",
        "verification.py",
        "soap_structuring.py"
    ]
    
    # deprecated文件列表
    deprecated_files = [
        "fact_extraction.py",
        "fact_consolidation.py",
        "soap_generation.py"
    ]
    
    print("=" * 80)
    print("流式处理使用情况检查")
    print("=" * 80)
    
    # 检查活跃文件
    print("\n活跃文件检查:")
    print("-" * 80)
    
    stream_count = 0
    old_count = 0
    
    for filename in active_files:
        filepath = stages_dir / filename
        if not filepath.exists():
            print(f"⚠️  文件不存在: {filename}")
            continue
        
        content = filepath.read_text(encoding='utf-8')
        
        # 检查是否使用 generate_stream_to_response
        stream_matches = re.findall(r'generate_stream_to_response', content)
        old_matches = re.findall(r'ctx\.llm_service\.generate\(', content)
        
        stream_count += len(stream_matches)
        old_count += len(old_matches)
        
        if stream_matches:
            print(f"✅ {filename}: {len(stream_matches)} 处使用流式处理")
        else:
            print(f"⚠️  {filename}: 未使用流式处理")
        
        if old_matches:
            print(f"❌ {filename}: {len(old_matches)} 处仍使用旧方法")
    
    # 检查deprecated文件
    print("\n废弃文件检查:")
    print("-" * 80)
    
    for filename in deprecated_files:
        filepath = stages_dir / filename
        if not filepath.exists():
            print(f"⚠️  文件不存在: {filename}")
            continue
        
        content = filepath.read_text(encoding='utf-8')
        
        # 检查是否标注为deprecated
        if content.startswith("# DEPRECATED"):
            print(f"✅ {filename}: 已标注为废弃")
        else:
            print(f"⚠️  {filename}: 未标注为废弃")
    
    # 总结
    print("\n" + "=" * 80)
    print("总结:")
    print("-" * 80)
    print(f"流式处理使用次数: {stream_count}")
    print(f"旧方法使用次数: {old_count}")
    
    if old_count == 0 and stream_count > 0:
        print("\n✅ 所有活跃文件已成功改为流式处理！")
        return True
    else:
        print("\n❌ 仍有文件使用旧方法或未使用流式处理")
        return False

if __name__ == "__main__":
    success = check_stream_usage()
    exit(0 if success else 1)