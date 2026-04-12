# Medical Assistant - QWEN Context File

## 项目概述

这是一个**中文医疗 AI 问诊助手**项目，核心目标是将医患对话的语音输入转为结构化病历（SOAP 格式）。项目采用分层架构，当前重点开发的是 **ASR（语音识别）模块**。

### 核心功能

1. **语音转文字**：使用 FunASR（Paraformer 模型）将中文医疗对话转为文本
2. **医疗术语增强**：通过热词定制提升药名、病名、检查名的识别准确率
3. **结构化病历生成**：将转写文本生成 SOAP 格式病历（规划中）

### 技术选型结论

| 模块 | 选择方案 | 理由 |
|------|---------|------|
| ASR 主线 | **FunASR + Paraformer** | 流程完整（VAD + 标点 + 热词）、部署友好、上手门槛低 |
| 备选方案 | WeNet 2.0、Qwen3 ASR、FireRedASR | 用于并行 POC 验证 |
| 硬件适配 | CPU 模式优先 | AMD 780M 集成显卡，ROCm 支持有限 |

## 项目结构

```
MedicalAssisstant/
├── config/
│   └── hotwords_medical.txt    # 医疗热词表（80+ 术语）
├── docs/
│   ├── 技术选型文档.md          # ASR 模块技术选型（详细 benchmark 对比）
│   ├── architecture.md         # 系统架构设计文档
│   ├── completion_status.md    # 开发完成状态记录
│   ├── 中文_ASR_路线盘点.md     # 中文 ASR 方案调研
│   ├── 中文医疗_ASR_上手路线.md # 医疗 ASR 上手指南
│   └── AI问诊助手开题报告.md    # 开题报告
├── scripts/
│   ├── compare_asr.py          # ASR 对比测试脚本
│   ├── download_dataset.py     # 通用数据集下载
│   └── download_medical_dataset.py  # 医疗数据集/合成音频生成
├── src/
│   ├── __init__.py
│   └── asr/
│       ├── __init__.py         # 模块入口
│       ├── base.py             # ASR 抽象基类 + ASRResult 数据类
│       ├── factory.py          # 工厂模式（统一创建入口）
│       ├── funasr_engine.py    # FunASR 引擎实现
│       └── medasr_engine.py    # MedASR 引擎实现（仅支持英文）
└── requirements-asr.txt        # ASR 模块依赖
```

## 构建与运行

### 环境准备

```bash
# 创建虚拟环境（如尚未激活）
# Windows:
med_env\Scripts\activate

# 安装 ASR 依赖
pip install -r requirements-asr.txt

# 如需 CPU 版 PyTorch（推荐）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### 生成测试数据

```bash
# 使用 Edge-TTS 合成医疗对话音频（快速测试）
python scripts/download_medical_dataset.py --method synthetic --output_dir ./data/medical

# 或使用离线 pyttsx3 合成
python scripts/download_medical_dataset.py --method pyttsx3 --output_dir ./data/medical
```

### 运行 ASR 测试

```bash
# 对比测试所有引擎
python scripts/compare_asr.py --audio test.wav --device cpu

# 只测试 FunASR
python scripts/compare_asr.py --audio test.wav --engine funasr

# 使用医疗热词
python scripts/compare_asr.py --audio test.wav --hotword config/hotwords_medical.txt

# 医疗术语召回测试（需先生成合成数据）
python data/medical/test_medical_asr.py --audio_dir ./data/medical/synthetic_audio --engine funasr
```

### 代码中使用

```python
from src.asr import ASRFactory

# 创建 FunASR 引擎
engine = ASRFactory.create("funasr", device="cpu", hotword_path="config/hotwords_medical.txt")
engine.load_model()
result = engine.transcribe("audio.wav")
print(result.text)
print(f"RTF: {result.real_time_factor:.3f}")
```

## 架构设计

### ASR 模块架构

采用**工厂模式 + 策略模式**：

- **`ASRBase`**：抽象基类，定义 `load_model()` 和 `transcribe()` 接口
- **`FunASREngine`**：FunASR 实现，支持 VAD、标点恢复、热词定制
- **`MedASREngine`**：MedASR 实现（⚠️ 仅支持英文医疗场景）
- **`ASRFactory`**：统一创建入口，支持动态注册新引擎
- **`ASRResult`**：统一返回数据结构（文本、RTF、时间戳等）

### 系统分层架构（规划中）

```
输入层 → 处理层 → 输出层
 ASR      证据选择    结构化病历
 文本      术语规范化   SOAP 格式
          LLM 生成
          验证检查
```

### 数据流

```
音频输入 → 预处理（16kHz/单声道） → VAD 切分 → ASR 转写 → 标点恢复 → 热词增强 → 文本输出
```

## 开发约定

### 代码风格

- 使用 Python 类型提示（type hints）
- 抽象基类定义接口，具体实现通过继承扩展
- 数据类使用 `@dataclass`
- 工厂模式管理引擎注册和创建

### 扩展新引擎

```python
from src.asr import ASRBase, ASRResult, ASRFactory

class WhisperEngine(ASRBase):
    def __init__(self, device="cpu"):
        super().__init__("Whisper", device)
    
    def load_model(self):
        # 加载模型
        pass
    
    def transcribe(self, audio_path, **kwargs) -> ASRResult:
        # 转写逻辑
        pass

# 注册
ASRFactory.register("whisper", WhisperEngine)
```

### 测试数据

- 项目包含 12 段中文医疗对话样本（医生/患者角色）
- 可通过 Edge-TTS 或 pyttsx3 自动生成合成音频
- 也可申请 MMedFD 真实医疗数据集（需邮件申请）

## 重要注意事项

1. **MedASR 仅支持英文**：官方暂无中文版本，对中文音频会输出警告
2. **AMD 780M 建议使用 CPU 模式**：ROCm 对集成显卡支持有限
3. **热词文件**：`config/hotwords_medical.txt` 包含 80+ 常见医疗术语，可根据科室扩展
4. **长音频处理**：VAD 自动切分，单段不超过 30 秒
5. **依赖安装**：首次运行需安装 `funasr`、`modelscope`、`librosa` 等

## 相关文档

- **技术选型**：`docs/技术选型文档.md`（FunASR vs WeNet vs Qwen3 ASR 等详细对比）
- **系统架构**：`docs/architecture.md`（完整架构设计、数据流图、模块接口）
- **完成状态**：`docs/completion_status.md`（已完成任务和待验证项）
- **上手指南**：`docs/中文医疗_ASR_上手路线.md`
