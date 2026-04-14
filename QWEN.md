# 中文门诊病历生成系统 - QWEN Context

## 项目概述

这是一个**中文医疗 AI 问诊助手**项目，核心目标是将医患对话的语音输入转为结构化病历（SOAP 格式）。系统采用分层架构，当前已实现完整的 **ASR（语音识别）模块** 和 **Web 应用界面**。

### 核心功能

1. **语音转文字**：使用 FunASR（Paraformer-large 模型）将中文医疗对话转为文本
2. **说话人分离**：自动区分医生和患者发言（偶数段→医生，奇数段→患者）
3. **医疗术语增强**：通过热词定制（80+ 术语）提升药名、病名、检查名的识别准确率
4. **ASR 纠错**：基于规则和拼音相似性的医疗术语智能纠错
5. **Web 界面**：支持音频上传、转写任务管理、结果展示（医生/患者对话区分显示）
6. **结构化病历生成**：将转写文本生成 SOAP 格式病历（规划中）

### 技术栈

| 层级 | 技术选型 |
|------|---------|
| **后端框架** | FastAPI + SQLAlchemy + SQLite |
| **前端** | HTML + CSS + JavaScript（原生） |
| **ASR 引擎** | FunASR (Paraformer-large) |
| **音频处理** | librosa + soundfile |
| **术语纠错** | pypinyin + python-Levenshtein |

### 系统架构

```
输入层 → 处理层 → 输出层
 ASR      证据选择    结构化病历
 文本      术语规范化   SOAP 格式
          LLM 生成
          验证检查
```

**当前已实现**：输入层（ASR）+ 部分处理层（后处理纠错、术语规范化）

## 项目结构

```
MedicalAssisstant/
├── backend/                    # 后端服务（FastAPI）
│   ├── api/                   # API 路由
│   │   ├── upload.py          # 音频上传接口
│   │   ├── asr.py             # ASR 转写接口
│   │   └── task.py            # 任务状态接口
│   ├── models/                # SQLAlchemy 数据模型
│   │   ├── visit.py           # 就诊记录模型
│   │   ├── transcript.py      # 转写记录模型
│   │   └── task.py            # 任务状态模型
│   ├── services/              # 业务逻辑
│   │   ├── asr_service.py     # ASR 服务（封装 FunASR）
│   │   ├── postprocessor.py   # 后处理服务（纠错）
│   │   └── normalizer.py      # 术语规范化服务
│   ├── utils/                 # 工具函数
│   │   └── audio_utils.py     # 音频处理工具
│   ├── config.py              # 配置管理（pydantic-settings）
│   ├── database.py            # 数据库连接（SQLite）
│   └── main.py                # FastAPI 应用入口
├── frontend/                   # 前端界面（原生 HTML/CSS/JS）
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── upload.js          # 上传页面逻辑
│   │   └── result.js          # 结果展示逻辑
│   ├── index.html             # 音频上传页面
│   └── result.html            # 转写结果页面
├── src/asr/                    # ASR 模块（工厂模式 + 策略模式）
│   ├── base.py                # ASRBase 抽象基类 + ASRResult 数据类
│   ├── factory.py             # ASRFactory 工厂类
│   ├── funasr_engine.py       # FunASR 引擎实现
│   └── medasr_engine.py       # MedASR 引擎实现（⚠️ 仅支持英文）
├── config/                     # 配置文件
│   ├── hotwords_medical.txt    # 医疗热词表（80+ 术语）
│   └── asr_correction_rules.json # ASR 纠错规则
├── data/                       # 数据存储
│   ├── audio/                 # 音频文件存储
│   ├── database/              # SQLite 数据库文件
│   └── logs/                  # 日志文件
├── docs/                       # 项目文档
│   ├── architecture.md         # 系统架构设计（详细）
│   ├── 技术选型文档.md          # ASR 方案对比
│   ├── completion_status.md    # 开发完成状态
│   └── ...
├── tests/                      # 测试脚本
│   ├── test_asr_oneclick.py   # 一键测试
│   └── test_asr_quick.py      # 快速测试
├── scripts/                    # 工具脚本
│   ├── compare_asr.py         # ASR 对比测试
│   └── download_medical_dataset.py  # 医疗数据集/合成音频
├── requirements.txt            # 项目完整依赖
├── requirements-asr.txt        # ASR 模块依赖
└── README.md                   # 项目文档
```

## 构建与运行

### 环境准备

```bash
# 创建虚拟环境（如尚未激活）
# Windows:
med_env\Scripts\activate

# 安装所有依赖
pip install -r requirements.txt

# 如需 CPU 版 PyTorch（推荐，适合 AMD 780M 集成显卡）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### 初始化数据库

```bash
# 初始化 SQLite 数据库
python -c "from backend.database import init_db; init_db()"
```

### 启动服务

```bash
# 启动 FastAPI 服务（开发模式）
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动时，FunASR 会自动下载模型（约 1GB），请耐心等待。

### 访问系统

- **主页**：http://localhost:8000/
- **API 文档（Swagger）**：http://localhost:8000/docs
- **API 文档（ReDoc）**：http://localhost:8000/redoc

### 运行 ASR 测试

```bash
# 对比测试所有引擎
python scripts/compare_asr.py --audio test.wav --device cpu

# 只测试 FunASR
python scripts/compare_asr.py --audio test.wav --engine funasr

# 使用医疗热词
python scripts/compare_asr.py --audio test.wav --hotword config/hotwords_medical.txt
```

### 生成测试数据

```bash
# 使用 Edge-TTS 合成医疗对话音频
python scripts/download_medical_dataset.py --method synthetic --output_dir ./data/medical

# 或使用离线 pyttsx3 合成
python scripts/download_medical_dataset.py --method pyttsx3 --output_dir ./data/medical
```

## 配置说明

### 环境变量（.env 文件，可选）

```env
APP_NAME=中文门诊病历生成系统
APP_VERSION=1.0.0
DEBUG=True

DATABASE_URL=sqlite:///data/database/medical.db

AUDIO_STORAGE_PATH=data/audio
MAX_AUDIO_SIZE=104857600  # 100MB

ASR_ENGINE=funasr
ASR_DEVICE=cpu  # 或 cuda

HOTWORD_PATH=config/hotwords_medical.txt

ENABLE_DIARIZATION=True
ENABLE_ASR_CORRECTION=True
CORRECTION_CONFIDENCE_THRESHOLD=0.7
```

### 配置管理

配置通过 `backend/config.py` 的 `Settings` 类管理，使用 `pydantic-settings`，支持从环境变量或 `.env` 文件读取。

## API 接口

### 1. 上传音频

```http
POST /api/upload
Content-Type: multipart/form-data

Parameters:
- audio_file: 音频文件（WAV/MP3）
- patient_name: 患者姓名（可选）
- visit_date: 就诊日期（可选）

Response:
{
  "success": true,
  "visit_id": "uuid",
  "audio_path": "data/audio/uuid.wav",
  "audio_duration": 120.5,
  "message": "音频上传成功"
}
```

### 2. 开始转写

```http
POST /api/asr/transcribe/{visit_id}

Response:
{
  "success": true,
  "visit_id": "uuid",
  "task_id": "uuid",
  "status": "processing",
  "message": "ASR转写任务已启动"
}
```

### 3. 查询任务状态

```http
GET /api/task/{task_id}

Response:
{
  "task_id": "uuid",
  "visit_id": "uuid",
  "task_type": "asr",
  "status": "completed",
  "progress": 100,
  "error_message": null,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:01:00"
}
```

### 4. 获取转写结果

```http
GET /api/asr/transcript/{visit_id}

Response:
{
  "visit_id": "uuid",
  "status": "completed",
  "audio_duration": 120.5,
  "turns": [
    {
      "turn_id": 1,
      "turn_index": 0,
      "speaker": "doctor",
      "text": "您好，请问哪里不舒服？",
      "original_text": "您好，请问哪里不舒服？",
      "corrected_text": "您好，请问哪里不舒服？",
      "start_ms": 0,
      "end_ms": 3000,
      "confidence": 0.95
    }
  ]
}
```

## 架构设计

### ASR 模块架构

采用**工厂模式 + 策略模式**：

- **`ASRBase`**：抽象基类，定义 `load_model()` 和 `transcribe()` 接口
- **`FunASREngine`**：FunASR 实现，支持 VAD、标点恢复、热词定制
- **`MedASREngine`**：MedASR 实现（⚠️ 仅支持英文医疗场景）
- **`ASRFactory`**：统一创建入口，支持动态注册新引擎
- **`ASRResult`**：统一返回数据结构（文本、RTF、时间戳等）

### ASR 数据流

```
音频输入 → 预处理（16kHz/单声道） → VAD 切分 → ASR 转写 → 标点恢复 → 热词增强 → 文本输出
```

### 说话人分离策略

当前版本使用简单的**交替映射策略**：
- 偶数段（0, 2, 4...） → 医生（doctor）
- 奇数段（1, 3, 5...） → 患者（patient）

后续版本将集成专业的说话人分离模型。

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

## 开发约定

### 代码风格

- 使用 Python 类型提示（type hints）
- 抽象基类定义接口，具体实现通过继承扩展
- 数据类使用 `@dataclass`
- 工厂模式管理引擎注册和创建
- FastAPI 路由按功能模块组织（api/ 目录）

### 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_asr.py -v
```

### 代码质量

```bash
# 格式化代码
black backend/

# 检查代码风格
flake8 backend/
```

## 重要注意事项

1. **MedASR 仅支持英文**：官方暂无中文版本，对中文音频会输出警告
2. **AMD 780M 建议使用 CPU 模式**：ROCm 对集成显卡支持有限
3. **热词文件**：`config/hotwords_medical.txt` 包含 80+ 常见医疗术语，可根据科室扩展
4. **长音频处理**：VAD 自动切分，单段不超过 30 秒
5. **依赖安装**：首次运行需安装 `funasr`、`modelscope`、`librosa` 等
6. **模型下载**：首次运行 FunASR 会自动下载约 1GB 模型文件
7. **音频格式推荐**：16kHz、WAV（PCM 编码）、单声道

## 技术选型结论

| 模块 | 选择方案 | 理由 |
|------|---------|------|
| ASR 主线 | **FunASR + Paraformer** | 流程完整（VAD + 标点 + 热词）、部署友好、上手门槛低 |
| 备选方案 | WeNet 2.0、Qwen3 ASR、FireRedASR | 用于并行 POC 验证 |
| 硬件适配 | CPU 模式优先 | AMD 780M 集成显卡，ROCm 支持有限 |

## 相关文档

- **技术选型**：`docs/技术选型文档.md`（FunASR vs WeNet vs Qwen3 ASR 等详细对比）
- **系统架构**：`docs/architecture.md`（完整架构设计、数据流图、模块接口）
- **完成状态**：`docs/completion_status.md`（已完成任务和待验证项）
- **上手指南**：`docs/中文医疗_ASR_上手路线.md`
- **ASR 测试指南**：`docs/asr_test_guide.md`
