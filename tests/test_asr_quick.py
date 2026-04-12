"""
ASR快速测试脚本
用于验证语音识别系统是否正常工作
"""
import os
from pathlib import Path

_DEFAULT_CACHE_DIR = Path("D:/models/modelscope_cache")
_DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["MODELSCOPE_CACHE"] = str(_DEFAULT_CACHE_DIR)

import json
import sys
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.asr.factory import ASRFactory


MINI_TEST_DATA = [
    {
        "id": "test_001",
        "text": "患者主诉头痛三天伴有发热",
        "category": "症状描述"
    },
    {
        "id": "test_002", 
        "text": "医生询问病史和用药情况",
        "category": "问诊"
    },
    {
        "id": "test_003",
        "text": "建议服用布洛芬退烧",
        "category": "处方"
    },
    {
        "id": "test_004",
        "text": "高血压患者需要定期测量血压",
        "category": "医嘱"
    },
    {
        "id": "test_005",
        "text": "糖尿病的典型症状是多饮多食多尿",
        "category": "医学知识"
    },
    {
        "id": "test_006",
        "text": "阿莫西林是一种常用的抗生素",
        "category": "药物说明"
    },
    {
        "id": "test_007",
        "text": "心电图检查显示心率正常",
        "category": "检查结果"
    },
    {
        "id": "test_008",
        "text": "建议住院观察治疗",
        "category": "治疗方案"
    },
    {
        "id": "test_009",
        "text": "患者对青霉素过敏",
        "category": "过敏史"
    },
    {
        "id": "test_010",
        "text": "术后需要注意伤口护理",
        "category": "术后医嘱"
    }
]


def calculate_cer(reference: str, hypothesis: str) -> float:
    """计算字符错误率 (CER)"""
    import difflib
    
    ref_chars = list(reference)
    hyp_chars = list(hypothesis)
    
    matcher = difflib.SequenceMatcher(None, ref_chars, hyp_chars)
    
    s = 0  # substitutions
    d = 0  # deletions
    i = 0  # insertions
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            s += max(i2 - i1, j2 - j1)
        elif tag == 'delete':
            d += (i2 - i1)
        elif tag == 'insert':
            i += (j2 - j1)
    
    n = len(ref_chars)
    if n == 0:
        return 0.0
    
    return (s + d + i) / n


def test_asr_basic():
    """基础功能测试"""
    print("="*60)
    print("ASR 基础功能测试")
    print("="*60)
    
    try:
        print("\n[1/3] 创建 ASR 引擎...")
        asr = ASRFactory.create("funasr", device="cpu")
        print("✓ 引擎创建成功")
        
        print("\n[2/3] 加载模型...")
        asr.load_model()
        print("✓ 模型加载成功")
        
        print("\n[3/3] 测试识别功能...")
        audio_dir = project_root / "data" / "audio"
        audio_files = list(audio_dir.glob("*.wav")) + list(audio_dir.glob("*.mp3"))
        
        if audio_files:
            test_audio = audio_files[0]
            print(f"  测试音频: {test_audio.name}")
            result = asr.transcribe(test_audio)
            print(f"  识别结果: {result.text[:50]}...")
            print(f"  耗时: {result.inference_time:.2f}s")
            print(f"  RTF: {result.real_time_factor:.3f}")
            print("✓ 识别功能正常")
        else:
            print("  ⚠ 未找到测试音频文件")
            print(f"  请将音频文件放入: {audio_dir}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_asr_with_tts():
    """使用TTS合成音频进行测试"""
    print("\n" + "="*60)
    print("ASR TTS合成测试")
    print("="*60)
    
    try:
        import edge_tts
        import asyncio
    except ImportError:
        print("⚠ edge-tts 未安装，跳过TTS测试")
        print("  安装命令: pip install edge-tts")
        return False
    
    print("\n[1/3] 创建 ASR 引擎...")
    asr = ASRFactory.create("funasr", device="cpu")
    asr.load_model()
    print("✓ 模型加载完成")
    
    temp_dir = project_root / "data" / "temp_test"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    print("\n[2/3] 合成测试音频...")
    test_items = MINI_TEST_DATA[:3]
    
    async def synthesize():
        for item in test_items:
            audio_path = temp_dir / f"{item['id']}.wav"
            communicate = edge_tts.Communicate(
                item['text'],
                "zh-CN-XiaoxiaoNeural"
            )
            await communicate.save(str(audio_path))
            print(f"  ✓ 合成: {item['id']}")
    
    asyncio.run(synthesize())
    
    print("\n[3/3] 运行识别测试...")
    results = []
    total_cer = 0
    
    for item in test_items:
        audio_path = temp_dir / f"{item['id']}.wav"
        if not audio_path.exists():
            continue
        
        result = asr.transcribe(audio_path)
        cer = calculate_cer(item['text'], result.text)
        total_cer += cer
        
        results.append({
            "id": item['id'],
            "reference": item['text'],
            "hypothesis": result.text,
            "cer": cer,
            "category": item['category']
        })
        
        print(f"\n  [{item['id']}] {item['category']}")
        print(f"    参考: {item['text']}")
        print(f"    识别: {result.text}")
        print(f"    CER: {cer:.2%}")
    
    avg_cer = total_cer / len(results) if results else 0
    
    print("\n" + "-"*60)
    print(f"平均 CER: {avg_cer:.2%}")
    print(f"测试样本: {len(results)} 条")
    
    for f in temp_dir.glob("*.wav"):
        f.unlink()
    temp_dir.rmdir()
    
    return True


def test_asr_with_dataset(dataset_path: str = None):
    """使用数据集进行测试"""
    print("\n" + "="*60)
    print("ASR 数据集测试")
    print("="*60)
    
    if dataset_path:
        dataset_file = Path(dataset_path)
        if not dataset_file.exists():
            print(f"✗ 数据集文件不存在: {dataset_path}")
            return False
        
        with open(dataset_file, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
    else:
        print("使用内置迷你测试数据...")
        test_data = MINI_TEST_DATA
    
    print("\n[1/2] 创建 ASR 引擎...")
    asr = ASRFactory.create("funasr", device="cpu")
    asr.load_model()
    print("✓ 模型加载完成")
    
    print("\n[2/2] 运行测试...")
    print("  注意: 此测试需要实际的音频文件")
    print("  请将音频文件放入 data/audio/ 目录")
    
    audio_dir = project_root / "data" / "audio"
    audio_files = {f.stem: f for f in audio_dir.glob("*.wav")}
    
    if not audio_files:
        print("\n⚠ 未找到音频文件，无法完成测试")
        print(f"  音频目录: {audio_dir}")
        return False
    
    results = []
    for item in test_data:
        audio_id = item.get('id', '')
        if audio_id in audio_files:
            result = asr.transcribe(audio_files[audio_id])
            cer = calculate_cer(item['text'], result.text)
            results.append({
                "id": audio_id,
                "reference": item['text'],
                "hypothesis": result.text,
                "cer": cer
            })
            print(f"  ✓ {audio_id}: CER={cer:.2%}")
    
    if results:
        avg_cer = sum(r['cer'] for r in results) / len(results)
        print(f"\n平均 CER: {avg_cer:.2%}")
        print(f"测试样本: {len(results)} 条")
    
    return True


def generate_test_report(results: list, output_path: str = None):
    """生成测试报告"""
    if output_path is None:
        output_path = project_root / "data" / "logs" / "asr_test_report.json"
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_samples": len(results),
        "average_cer": sum(r['cer'] for r in results) / len(results) if results else 0,
        "results": results
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n测试报告已保存: {output_path}")


def main():
    """主测试流程"""
    print("\n" + "="*60)
    print("  Medical Assistant ASR 测试工具")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*60)
    
    print("\n选择测试模式:")
    print("  1. 基础功能测试（快速验证）")
    print("  2. TTS合成测试（需要edge-tts）")
    print("  3. 数据集测试（需要音频文件）")
    print("  4. 全部测试")
    print("  0. 退出")
    
    choice = input("\n请输入选项 [0-4]: ").strip()
    
    if choice == "1":
        test_asr_basic()
    elif choice == "2":
        test_asr_with_tts()
    elif choice == "3":
        dataset = input("数据集路径（留空使用内置数据）: ").strip()
        test_asr_with_dataset(dataset if dataset else None)
    elif choice == "4":
        test_asr_basic()
        test_asr_with_tts()
    elif choice == "0":
        print("退出测试")
    else:
        print("无效选项")


if __name__ == "__main__":
    main()
