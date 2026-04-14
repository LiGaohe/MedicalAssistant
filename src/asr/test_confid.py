from funasr import AutoModel
import os
from pathlib import Path

# 1. 固定缓存路径（与你原代码一致）
_DEFAULT_CACHE_DIR = Path("D:/models/modelscope_cache")
_DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MODELSCOPE_CACHE", str(_DEFAULT_CACHE_DIR))

# 2. 模型初始化（关键：强制开启置信度相关参数）
model = AutoModel(
    model="paraformer-zh",           # 基础模型
    vad_model="fsmn-vad",            # VAD分割
    punc_model="ct-punc",            # 标点恢复
    timestamp_extractor=True,        # 时间戳（词级对齐的基础）
    beam_search=True,                # ★ 核心：启用束搜索才能输出细粒度置信度
    device="cpu",                    # CPU运行
    disable_update=True,             # 锁定配置
)

# 3. 音频路径（保持你的测试文件）
wav_path = "d:/practice/MedicalAssisstant/data/audio/speech_asr_aishell1_testsets/wav/test/S0764/BAC009S0764W0121.wav"

# 4. 生成结果（关键参数组合）
result = model.generate(
    input=wav_path,
    batch_size_s=300,                # 批次时长
    batch_type="seg",                # ★ 核心：分段处理配合beam_search
    return_raw=False                 # 确保结构化输出
)

# ==================== 结果解析 ====================
print("="*60)
print("【完整结果层级预览】")
print(f"顶层字段: {list(result[0].keys())}\n")

# 场景A：理想情况 - 存在sentence_info词级置信度
if "sentence_info" in result[0]:
    print("✅ 成功获取词级明细（sentence_info）")
    sentences = result[0]["sentence_info"]
    
    for idx, sent in enumerate(sentences):
        print(f"\n📝 句子{idx+1}: {sent['text']}")
        
        # 优先提取词级置信度
        if "word_conf" in sent:
            words = sent.get("words", ["未知"] * len(sent["word_conf"]))
            for i, (word, conf) in enumerate(zip(words, sent["word_conf"])):
                print(f"   🔹 词{i+1}: {word} → {conf:.4f}")
        # 次选：整句置信度
        elif "confidence" in sent:
            print(f"   🔸 整句置信度: {sent['confidence']:.4f}")
        else:
            print("   ⚠ 本句无置信度字段，详见:", list(sent.keys()))
            
# 场景B：只有顶层置信度列表
elif "confidence" in result[0]:
    print("✅ 获取到顶层置信度列表")
    conf_list = result[0]["confidence"]
    text = result[0]["text"]
    words = text.split() if isinstance(text, str) else []
    
    print(f"识别文本: {text}")
    for i, conf_val in enumerate(conf_list):
        word_display = words[i] if i < len(words) else f"词位_{i}"
        print(f"  {word_display}: {conf_val:.4f}")

# 场景C：原始logits（部分历史版本）
elif "pred_logits" in result[0]:
    print("⚠ 获取到原始logits，需手动转换置信度")
    logits = result[0]["pred_logits"]
    print(f"原始logits形状/样例: {type(logits)} -> {str(logits)[:100]}...")
    # 可在此添加softmax转换逻辑
    
# 场景D：完全缺失（最终兜底）
else:
    print("❌ 无任何置信度相关字段，当前输出：")
    print(result[0])
    print("\n🔴 排查建议：")
    print("1. 检查funASR版本: pip show funasr | grep Version")
    print("2. 更新到最新版: pip install -U funasr")
    print("3. 删除缓存目录 D:/models/modelscope_cache 后重试")
    print("4. 尝试改用模型: model='paraformer-zh-streaming'")

print("="*60)