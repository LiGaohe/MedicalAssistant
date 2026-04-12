"""
ASR识别效果测试脚本

使用方法:
1. 准备测试音频文件（放到 data/audio/ 目录）
2. 准备参考文本文件（用于对比识别准确率）
3. 运行测试脚本

示例:
    python scripts/test_asr_performance.py --audio data/audio/test.wav --reference data/audio/test.txt
    python scripts/test_asr_performance.py --audio-dir data/audio/ --reference-dir data/audio/references/
"""

import argparse
import sys
from pathlib import Path
import json
import time
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.asr import FunASREngine
from backend.services.postprocessor import ASRPostprocessor
from backend.services.normalizer import TranscriptNormalizer


class ASRPerformanceTester:
    def __init__(self, device: str = "cpu", hotword_path: str = None):
        self.device = device
        self.hotword_path = hotword_path
        self.engine = None
        self.postprocessor = ASRPostprocessor()
        self.normalizer = TranscriptNormalizer()
        
    def initialize(self):
        print("正在初始化ASR引擎...")
        self.engine = FunASREngine(
            device=self.device,
            hotword_path=self.hotword_path
        )
        self.engine.load_model()
        print("ASR引擎初始化完成")
    
    def test_single_audio(
        self, 
        audio_path: str, 
        reference_text: str = None,
        enable_correction: bool = True
    ) -> Dict:
        """
        测试单个音频文件
        
        Args:
            audio_path: 音频文件路径
            reference_text: 参考文本（可选）
            enable_correction: 是否启用纠错
            
        Returns:
            测试结果字典
        """
        print(f"\n测试音频: {audio_path}")
        
        # 1. 转写
        start_time = time.time()
        result = self.engine.transcribe(audio_path)
        inference_time = time.time() - start_time
        
        # 2. 获取识别文本
        recognized_text = result.text
        
        # 3. 后处理纠错
        corrected_text = recognized_text
        corrections = []
        if enable_correction:
            corrected_text, corrections = self.postprocessor.correct(recognized_text)
        
        # 4. 计算指标
        test_result = {
            "audio_path": str(audio_path),
            "audio_duration": result.duration_seconds,
            "inference_time": inference_time,
            "real_time_factor": inference_time / result.duration_seconds if result.duration_seconds > 0 else 0,
            "recognized_text": recognized_text,
            "corrected_text": corrected_text,
            "corrections": corrections,
            "segments": result.segments
        }
        
        # 5. 如果有参考文本，计算准确率
        if reference_text:
            # 标准化文本（去除空格、标点等）
            ref_normalized = self._normalize_text(reference_text)
            rec_normalized = self._normalize_text(corrected_text)
            
            # 计算字符错误率 (CER)
            cer = self._calculate_cer(ref_normalized, rec_normalized)
            
            # 计算准确率
            accuracy = max(0, 1 - cer)
            
            test_result["reference_text"] = reference_text
            test_result["cer"] = cer
            test_result["accuracy"] = accuracy
        
        return test_result
    
    def test_audio_directory(
        self, 
        audio_dir: str, 
        reference_dir: str = None,
        enable_correction: bool = True
    ) -> Dict:
        """
        测试音频目录中的所有音频文件
        
        Args:
            audio_dir: 音频文件目录
            reference_dir: 参考文本目录（可选）
            enable_correction: 是否启用纠错
            
        Returns:
            汇总测试结果
        """
        audio_dir = Path(audio_dir)
        audio_files = list(audio_dir.glob("*.wav")) + list(audio_dir.glob("*.mp3"))
        
        if not audio_files:
            print(f"在 {audio_dir} 中未找到音频文件")
            return {}
        
        print(f"找到 {len(audio_files)} 个音频文件")
        
        results = []
        total_duration = 0
        total_inference_time = 0
        total_cer = 0
        cer_count = 0
        
        for audio_file in audio_files:
            # 查找对应的参考文本
            reference_text = None
            if reference_dir:
                ref_file = Path(reference_dir) / f"{audio_file.stem}.txt"
                if ref_file.exists():
                    reference_text = ref_file.read_text(encoding='utf-8').strip()
            
            # 测试单个音频
            result = self.test_single_audio(
                str(audio_file), 
                reference_text,
                enable_correction
            )
            results.append(result)
            
            # 累计统计
            total_duration += result["audio_duration"]
            total_inference_time += result["inference_time"]
            if "cer" in result:
                total_cer += result["cer"]
                cer_count += 1
        
        # 汇总结果
        summary = {
            "total_files": len(audio_files),
            "total_duration": total_duration,
            "total_inference_time": total_inference_time,
            "average_rtf": total_inference_time / total_duration if total_duration > 0 else 0,
            "average_cer": total_cer / cer_count if cer_count > 0 else None,
            "average_accuracy": max(0, 1 - (total_cer / cer_count)) if cer_count > 0 else None,
            "detailed_results": results
        }
        
        return summary
    
    def _normalize_text(self, text: str) -> str:
        """标准化文本（去除空格、标点等）"""
        import re
        # 去除所有空白字符
        text = re.sub(r'\s+', '', text)
        # 去除标点符号
        text = re.sub(r'[^\w]', '', text)
        return text
    
    def _calculate_cer(self, reference: str, hypothesis: str) -> float:
        """
        计算字符错误率 (Character Error Rate)
        
        CER = (S + D + I) / N
        其中:
        - S: 替换错误数
        - D: 删除错误数
        - I: 插入错误数
        - N: 参考文本长度
        """
        try:
            import Levenshtein
            distance = Levenshtein.distance(reference, hypothesis)
            cer = distance / len(reference) if len(reference) > 0 else 0
            return cer
        except ImportError:
            print("警告: 未安装python-Levenshtein，使用简化计算")
            # 简化计算：只计算字符匹配率
            if len(reference) == 0:
                return 0 if len(hypothesis) == 0 else 1
            
            matches = sum(1 for a, b in zip(reference, hypothesis) if a == b)
            max_len = max(len(reference), len(hypothesis))
            return 1 - (matches / max_len)


def print_test_result(result: Dict):
    """打印单个测试结果"""
    print("\n" + "="*60)
    print(f"音频文件: {result['audio_path']}")
    print(f"音频时长: {result['audio_duration']:.2f}秒")
    print(f"推理时间: {result['inference_time']:.2f}秒")
    print(f"实时率(RTF): {result['real_time_factor']:.3f}x")
    
    if result.get('corrections'):
        print(f"\n纠错数量: {len(result['corrections'])}")
        for correction in result['corrections']:
            print(f"  {correction['original']} -> {correction['corrected']} ({correction['type']})")
    
    if 'cer' in result:
        print(f"\n字符错误率(CER): {result['cer']:.2%}")
        print(f"识别准确率: {result['accuracy']:.2%}")
    
    print(f"\n识别文本: {result['recognized_text']}")
    if result.get('corrected_text') != result['recognized_text']:
        print(f"纠错文本: {result['corrected_text']}")
    
    if result.get('reference_text'):
        print(f"参考文本: {result['reference_text']}")


def print_summary(summary: Dict):
    """打印汇总结果"""
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)
    print(f"测试文件数: {summary['total_files']}")
    print(f"总音频时长: {summary['total_duration']:.2f}秒")
    print(f"总推理时间: {summary['total_inference_time']:.2f}秒")
    print(f"平均实时率(RTF): {summary['average_rtf']:.3f}x")
    
    if summary['average_cer'] is not None:
        print(f"平均字符错误率(CER): {summary['average_cer']:.2%}")
        print(f"平均识别准确率: {summary['average_accuracy']:.2%}")


def main():
    parser = argparse.ArgumentParser(description="ASR识别效果测试工具")
    parser.add_argument("--audio", type=str, help="单个音频文件路径")
    parser.add_argument("--reference", type=str, help="参考文本文件路径")
    parser.add_argument("--audio-dir", type=str, help="音频文件目录")
    parser.add_argument("--reference-dir", type=str, help="参考文本目录")
    parser.add_argument("--device", type=str, default="cpu", help="设备类型 (cpu/cuda)")
    parser.add_argument("--hotword-path", type=str, help="热词文件路径")
    parser.add_argument("--no-correction", action="store_true", help="禁用纠错功能")
    parser.add_argument("--output", type=str, help="结果输出文件路径(JSON)")
    
    args = parser.parse_args()
    
    # 初始化测试器
    tester = ASRPerformanceTester(
        device=args.device,
        hotword_path=args.hotword_path
    )
    tester.initialize()
    
    # 执行测试
    if args.audio:
        # 单文件测试
        reference_text = None
        if args.reference:
            reference_text = Path(args.reference).read_text(encoding='utf-8').strip()
        
        result = tester.test_single_audio(
            args.audio,
            reference_text,
            enable_correction=not args.no_correction
        )
        print_test_result(result)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存到: {args.output}")
    
    elif args.audio_dir:
        # 目录测试
        summary = tester.test_audio_directory(
            args.audio_dir,
            args.reference_dir,
            enable_correction=not args.no_correction
        )
        print_summary(summary)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"\n结果已保存到: {args.output}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
