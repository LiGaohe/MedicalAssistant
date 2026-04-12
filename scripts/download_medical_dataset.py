"""
医疗语音测试数据获取脚本

支持的方式:
1. 申请 MMedFD 数据集 (需审批)
2. 使用 TTS 合成医疗对话音频 (快速测试)
3. 手动录制测试音频

用法:
    python scripts/download_medical_dataset.py --method synthetic --output_dir ./data/medical
    python scripts/download_medical_dataset.py --method mmedfd --output_dir ./data/medical
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


MEDICAL_DIALOGUE_SAMPLES = [
    {
        "id": "med_001",
        "speaker": "doctor",
        "text": "您好，请问您今天哪里不舒服？",
        "category": "问诊开场"
    },
    {
        "id": "med_002",
        "speaker": "patient",
        "text": "医生，我这几天一直头疼，而且有点发烧。",
        "category": "症状描述"
    },
    {
        "id": "med_003",
        "speaker": "doctor",
        "text": "头疼是从什么时候开始的？体温量过吗？",
        "category": "病史询问"
    },
    {
        "id": "med_004",
        "speaker": "patient",
        "text": "从前天开始的，体温三十七度八，我吃了布洛芬但是效果不明显。",
        "category": "症状描述"
    },
    {
        "id": "med_005",
        "speaker": "doctor",
        "text": "除了头疼发烧，还有其他症状吗？比如咳嗽、流鼻涕？",
        "category": "症状询问"
    },
    {
        "id": "med_006",
        "speaker": "patient",
        "text": "有点咳嗽，但是不严重，嗓子也有点疼。",
        "category": "症状描述"
    },
    {
        "id": "med_007",
        "speaker": "doctor",
        "text": "我听一下您的肺部。深呼吸。好的，肺部听起来比较清晰。",
        "category": "体格检查"
    },
    {
        "id": "med_008",
        "speaker": "doctor",
        "text": "根据您的症状，考虑是上呼吸道感染。我给您开点药。",
        "category": "诊断"
    },
    {
        "id": "med_009",
        "speaker": "doctor",
        "text": "阿莫西林胶囊，一天三次，一次一粒。奥美拉唑肠溶片，一天一次。",
        "category": "用药建议"
    },
    {
        "id": "med_010",
        "speaker": "doctor",
        "text": "多喝水，注意休息。如果三天后症状没有好转，再来复诊。",
        "category": "医嘱"
    },
    {
        "id": "med_011",
        "speaker": "patient",
        "text": "好的，谢谢医生。这个药饭前吃还是饭后吃？",
        "category": "用药咨询"
    },
    {
        "id": "med_012",
        "speaker": "doctor",
        "text": "阿莫西林饭后吃，奥美拉唑饭前半小时服用。有什么问题随时来。",
        "category": "用药指导"
    },
]


def create_medical_dialogue_json(output_dir: Path) -> Path:
    """创建医疗对话文本数据"""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "medical_dialogue_samples.json"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(MEDICAL_DIALOGUE_SAMPLES, f, ensure_ascii=False, indent=2)
    
    print(f"已创建医疗对话文本: {json_path}")
    return json_path


def generate_synthetic_audio_with_edge_tts(output_dir: Path) -> None:
    """使用 Edge-TTS 生成合成音频 (免费)"""
    try:
        import edge_tts
    except ImportError:
        print("\n请先安装 edge-tts:")
        print("  pip install edge-tts")
        return
    
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "synthetic_audio"
    audio_dir.mkdir(exist_ok=True)
    
    voices = {
        "doctor": "zh-CN-YunxiNeural",
        "patient": "zh-CN-XiaoxiaoNeural",
    }
    
    print("\n正在生成合成医疗语音...")
    
    for sample in MEDICAL_DIALOGUE_SAMPLES:
        speaker = sample["speaker"]
        text = sample["text"]
        sample_id = sample["id"]
        
        voice = voices.get(speaker, "zh-CN-YunxiNeural")
        output_file = audio_dir / f"{sample_id}_{speaker}.wav"
        
        print(f"  生成: {sample_id} ({speaker})")
        
        communicate = edge_tts.Communicate(text, voice)
        communicate.save(str(output_file))
    
    print(f"\n合成音频已保存到: {audio_dir}")
    print(f"共生成 {len(MEDICAL_DIALOGUE_SAMPLES)} 个音频文件")


def generate_synthetic_audio_with_pyttsx3(output_dir: Path) -> None:
    """使用 pyttsx3 生成合成音频 (离线)"""
    try:
        import pyttsx3
    except ImportError:
        print("\n请先安装 pyttsx3:")
        print("  pip install pyttsx3")
        return
    
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "synthetic_audio"
    audio_dir.mkdir(exist_ok=True)
    
    engine = pyttsx3.init()
    engine.setProperty('rate', 150)
    
    print("\n正在生成合成医疗语音 (离线模式)...")
    
    for sample in MEDICAL_DIALOGUE_SAMPLES:
        speaker = sample["speaker"]
        text = sample["text"]
        sample_id = sample["id"]
        
        output_file = audio_dir / f"{sample_id}_{speaker}.wav"
        
        print(f"  生成: {sample_id} ({speaker})")
        
        engine.save_to_file(text, str(output_file))
    
    engine.runAndWait()
    print(f"\n合成音频已保存到: {audio_dir}")


def print_mmedfd_instructions() -> None:
    """打印 MMedFD 申请说明"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                    MMedFD 数据集申请指南                          ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  数据集名称: MMedFD (中文医疗语音对话)                            ║
║  数据规模:   136.9小时, 5,805个会话, 10,814轮对话                ║
║  数据内容:   真实医患对话语音，含说话人标签和时间戳               ║
║                                                                  ║
║  申请方式:                                                       ║
║  1. 发送邮件至: yangxiao.wxy@antgroup.com                        ║
║  2. 邮件内容需包含:                                              ║
║     - 所属机构/学校                                              ║
║     - 项目名称和目标                                             ║
║     - 数据使用计划                                               ║
║     - 数据保护措施                                               ║
║                                                                  ║
║  GitHub: https://github.com/Kinetics-JOJO/MMedFD                 ║
║  论文:   https://arxiv.org/abs/2509.19817                        ║
║                                                                  ║
║  注意: 数据仅限研究用途，不可重新分发                             ║
╚══════════════════════════════════════════════════════════════════╝
""")


def print_manual_recording_guide(output_dir: Path) -> None:
    """打印手动录制指南"""
    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║                    手动录制医疗测试音频指南                       ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  录制建议:                                                       ║
║  1. 使用手机或电脑麦克风录制                                     ║
║  2. 格式: WAV, 采样率: 16kHz, 单声道                             ║
║  3. 时长: 每段 10-30 秒                                          ║
║                                                                  ║
║  录制内容示例:                                                   ║
║  - 医生问诊: "您好，请问哪里不舒服？"                            ║
║  - 患者描述: "我头疼三天了，吃了布洛芬不管用"                    ║
║  - 医生诊断: "根据症状，考虑是上呼吸道感染"                      ║
║  - 用药建议: "阿莫西林一天三次，一次一粒"                        ║
║                                                                  ║
║  保存位置: {output_dir / 'recorded_audio':<40} ║
║                                                                  ║
║  录制完成后运行:                                                 ║
║  python scripts/compare_asr.py --audio <音频文件> --device cpu   ║
╚══════════════════════════════════════════════════════════════════╝
""")


def create_test_script(output_dir: Path) -> None:
    """创建医疗 ASR 测试脚本"""
    script_path = output_dir / "test_medical_asr.py"
    
    content = '''"""
医疗 ASR 测试脚本

用法:
    python test_medical_asr.py --audio_dir ./synthetic_audio --engine funasr
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from asr import ASRFactory


MEDICAL_TERMS = [
    "阿莫西林", "布洛芬", "奥美拉唑", "上呼吸道感染",
    "头疼", "发烧", "咳嗽", "嗓子疼", "肺部",
]


def evaluate_medical_terms(text: str, expected_terms: list) -> dict:
    """评估医疗术语识别情况"""
    found = []
    missed = []
    
    for term in expected_terms:
        if term in text:
            found.append(term)
        else:
            missed.append(term)
    
    return {
        "found_terms": found,
        "missed_terms": missed,
        "recall": len(found) / len(expected_terms) if expected_terms else 0,
    }


def test_medical_asr(audio_dir: str, engine_type: str = "funasr", device: str = "cpu"):
    """测试医疗 ASR"""
    audio_path = Path(audio_dir)
    
    if not audio_path.exists():
        print(f"错误: 音频目录不存在: {audio_dir}")
        return
    
    audio_files = list(audio_path.glob("*.wav"))
    if not audio_files:
        print(f"错误: 未找到音频文件: {audio_dir}")
        return
    
    print(f"找到 {len(audio_files)} 个音频文件")
    
    dialogue_file = audio_path.parent / "medical_dialogue_samples.json"
    references = {}
    if dialogue_file.exists():
        with open(dialogue_file, "r", encoding="utf-8") as f:
            samples = json.load(f)
            for s in samples:
                references[s["id"]] = s["text"]
    
    engine = ASRFactory.create(engine_type, device=device)
    print(f"\n加载 {engine_type} 模型...")
    engine.load_model()
    
    total_terms_found = 0
    total_terms = 0
    
    for audio_file in sorted(audio_files):
        sample_id = audio_file.stem.split("_")[0]
        
        result = engine.transcribe(audio_file)
        
        expected = references.get(sample_id, "")
        term_eval = evaluate_medical_terms(result.text, MEDICAL_TERMS)
        
        total_terms_found += len(term_eval["found_terms"])
        total_terms += len(MEDICAL_TERMS)
        
        print(f"\\n{'='*60}")
        print(f"文件: {audio_file.name}")
        print(f"参考: {expected}")
        print(f"识别: {result.text}")
        print(f"医疗术语召回: {term_eval['recall']:.2%}")
        if term_eval["found_terms"]:
            print(f"识别到的术语: {', '.join(term_eval['found_terms'])}")
        print(f"RTF: {result.real_time_factor:.3f}")
    
    print(f"\\n{'='*60}")
    print(f"总体医疗术语召回率: {total_terms_found/total_terms:.2%}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="医疗 ASR 测试")
    parser.add_argument("--audio_dir", type=str, required=True,
                        help="音频文件目录")
    parser.add_argument("--engine", type=str, default="funasr",
                        choices=["funasr", "medasr"])
    parser.add_argument("--device", type=str, default="cpu",
                        choices=["cpu", "cuda"])
    
    args = parser.parse_args()
    test_medical_asr(args.audio_dir, args.engine, args.device)


if __name__ == "__main__":
    main()
'''
    
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"\n已创建测试脚本: {script_path}")


def main():
    parser = argparse.ArgumentParser(description="医疗语音测试数据获取工具")
    parser.add_argument(
        "--method", "-m",
        type=str,
        choices=["mmedfd", "synthetic", "edge_tts", "pyttsx3", "manual"],
        default="synthetic",
        help="获取方式"
    )
    parser.add_argument(
        "--output_dir", "-o",
        type=str,
        default="./data/medical",
        help="输出目录"
    )
    
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    
    print(f"\n{'='*60}")
    print("医疗语音测试数据获取工具")
    print(f"{'='*60}")
    
    if args.method == "mmedfd":
        print_mmedfd_instructions()
    
    elif args.method == "synthetic" or args.method == "edge_tts":
        create_medical_dialogue_json(output_dir)
        generate_synthetic_audio_with_edge_tts(output_dir)
        create_test_script(output_dir)
    
    elif args.method == "pyttsx3":
        create_medical_dialogue_json(output_dir)
        generate_synthetic_audio_with_pyttsx3(output_dir)
        create_test_script(output_dir)
    
    elif args.method == "manual":
        create_medical_dialogue_json(output_dir)
        print_manual_recording_guide(output_dir)
        create_test_script(output_dir)
    
    print(f"\n{'='*60}")
    print("后续步骤:")
    print("1. 安装依赖: pip install -r requirements-asr.txt")
    if args.method in ["synthetic", "edge_tts", "pyttsx3"]:
        print("2. 运行测试: python data/medical/test_medical_asr.py --audio_dir ./data/medical/synthetic_audio")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
