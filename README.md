# 中文门诊病历生成系统

基于FunASR的中文门诊音频转写系统，支持说话人分离和医疗术语纠错。

## 功能特性

### M1里程碑：音频到文本
- ✅ 音频文件上传（支持WAV/MP3格式）
- ✅ 自动语音识别（ASR）转写
- ✅ 说话人分离（区分不同说话人）
- ✅ 医疗术语智能纠错
- ✅ 转写结果标准化
- ✅ Web界面展示
- ✅ 任务状态跟踪

### M2里程碑：文本到病历
- ✅ 证据选择（从对话中筛选相关片段）
- ✅ 术语规范化（口语化表述映射到标准术语）
- ✅ 病历要素抽取（SOAP格式）
- ✅ 结构化病历生成
- ✅ 证据回链（每个字段可追溯到原始对话）
- ✅ 版本化管理（支持多版本病历）

## 技术栈

- **后端**: FastAPI + SQLAlchemy + SQLite
- **前端**: HTML + CSS + JavaScript
- **ASR引擎**: FunASR (Paraformer-large)
- **音频处理**: librosa + soundfile

## 快速开始

### 1. 环境要求

- Python 3.9+
- 操作系统: Windows/Linux/macOS

### 2. 安装依赖

```bash
# 克隆项目
git clone <repository-url>
cd MedicalAssistant

# 创建虚拟环境（推荐）
python -m venv med_venv

# 激活虚拟环境
# Windows:
source med_env/Scripts/activate
# Linux/Mac:
source med_env/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 初始化数据库

```bash
# 初始化SQLite数据库
python -c "from backend.database import init_db; init_db()"
```

### 4. 启动服务

```bash
# 首先进入虚拟环境
# Windows:
source med_env/Scripts/activate
# Linux/Mac:
source med_env/bin/activate
# 关闭端口8000的进程
# Windows:
netstat -ano | findstr 8000 # 查找端口8000的进程id
powershell -Command "Stop-Process -Id <process_id> -Force"
# 如果还清理不掉
taskkill /F /PID 22384
# 或
powershell -Command "taskkill /F /PID 22384"
# Linux/Mac:
lsof -iTCP:8000
kill -9 $(lsof -iTCP:8000 -t)
# 启动FastAPI服务
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动时，FunASR会自动下载模型（约1GB），请耐心等待。

### 5. 访问系统

打开浏览器访问: http://localhost:8000/

## 使用流程

### 阶段一：音频转写（M1里程碑）

#### 1. 上传音频

- 访问首页
- 拖拽或点击上传音频文件（支持WAV/MP3）
- 填写患者姓名和就诊日期（可选）
- 点击"开始上传"

#### 2. 开始转写

- 上传成功后自动跳转到结果页面
- 点击"开始转写"按钮
- 系统会在后台处理音频

#### 3. 查看转写结果

- 转写完成后自动显示结果
- 不同说话人用不同颜色区分
- 每段对话显示时间戳和置信度

### 阶段二：病历生成（M2里程碑）

#### 4. 配置LLM服务（可选但推荐）

**方式1：通过前端界面配置（推荐）**

- 点击首页或转写结果页面的"配置大模型"按钮
- 填写配置信息（以魔搭ModelScope为例）：
  - 配置名称：例如 `modelscope`
  - 服务商：选择 `OpenAI兼容接口`
  - 模型名称：例如 `ZhipuAI/GLM-5.1`
  - API Key：输入您的API Key（如 `ms-xxxxx`）
  - API Endpoint：例如 `https://api-inference.modelscope.cn/v1`
  - 其他参数保持默认即可
- 点击"保存配置"

**支持的LLM服务商**：

- **魔搭ModelScope**（推荐）：免费使用，支持多种开源模型
  - Endpoint: `https://api-inference.modelscope.cn/v1`
  - 模型: `ZhipuAI/GLM-5.1`, `Qwen/Qwen2.5-72B-Instruct` 等
  
- **通义千问**：阿里云大模型服务
  - Endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1`
  - 模型: `qwen-plus`, `qwen-turbo` 等
  
- **OpenAI**：GPT系列模型
  - Endpoint: `https://api.openai.com/v1`
  - 模型: `gpt-4`, `gpt-3.5-turbo` 等
  
- **本地模型**：如Ollama
  - Endpoint: `http://localhost:11434/v1`
  - 模型: `qwen2.5:7b`, `llama3.1:8b` 等

**方式2：通过API配置**

```bash
# 魔搭ModelScope示例
POST /api/llm/config
{
  "config_name": "modelscope",
  "provider": "openai_compatible",
  "model_name": "ZhipuAI/GLM-5.1",
  "api_key": "ms-xxxxx",
  "api_endpoint": "https://api-inference.modelscope.cn/v1",
  "is_active": true
}

# 通义千问示例
POST /api/llm/config
{
  "config_name": "qwen",
  "provider": "openai_compatible",
  "model_name": "qwen-plus",
  "api_key": "your-api-key",
  "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "is_active": true
}
```

#### 5. 生成病历

**方式1：通过前端界面生成（推荐）**

- 转写完成后，点击"生成病历"按钮
- 系统自动跳转到病历生成页面
- 点击"生成病历"按钮开始生成
- 生成完成后点击"查看病历"查看结果

**方式2：通过API生成**

```bash
POST /api/emr/process
{
  "visit_id": "your-visit-id",
  "use_llm": true,
  "save_intermediate": true
}
```

**方式3：使用测试脚本**

```bash
python scripts/test_m2_milestone.py
```

#### 6. 查看病历

**方式1：通过前端界面查看（推荐）**

- 在病历生成页面点击"查看病历"
- 选择不同版本查看历史病历
- 病历内容按SOAP格式展示：
  - 主观数据（Subjective）
  - 客观数据（Objective）
  - 评估（Assessment）
  - 计划（Plan）

**方式2：通过API查看**

```bash
# 获取最新病历
GET /api/emr/record/{visit_id}

# 获取指定版本病历
GET /api/emr/record/{visit_id}?version=1

# 获取所有版本
GET /api/emr/versions/{visit_id}
```

#### 7. 病历内容说明

生成的病历包含以下部分：

- **主观数据（Subjective）**：主诉、现病史、既往史
- **客观数据（Objective）**：体格检查、辅助检查
- **评估（Assessment）**：诊断
- **计划（Plan）**：治疗方案、医嘱

每个字段都包含：
- `value`：字段内容
- `evidence_ids`：证据ID列表（可追溯到原始对话）
- `confidence`：置信度

## 项目结构

```
MedicalAssisstant/
├── backend/                 # 后端代码
│   ├── api/                # API接口
│   │   ├── upload.py      # 上传接口
│   │   ├── asr.py         # ASR转写接口
│   │   ├── task.py        # 任务状态接口
│   │   ├── llm.py         # LLM配置接口
│   │   └── emr.py         # 病历生成接口
│   ├── models/            # 数据模型
│   │   ├── visit.py       # 就诊记录模型
│   │   ├── transcript.py  # 转写记录模型
│   │   ├── task.py        # 任务状态模型
│   │   ├── llm_config.py  # LLM配置模型
│   │   ├── evidence.py    # 证据片段模型
│   │   ├── term.py        # 规范化术语模型
│   │   ├── extracted_item.py # 病历要素模型
│   │   └── emr_record.py  # 病历记录模型
│   ├── services/          # 业务逻辑
│   │   ├── asr_service.py # ASR服务
│   │   ├── postprocessor.py # 后处理纠错
│   │   ├── normalizer.py  # 结果标准化
│   │   ├── evidence_service.py # 证据选择服务
│   │   ├── terminology_service.py # 术语规范化服务
│   │   ├── extraction_service.py # 病历要素抽取服务
│   │   ├── emr_generation_service.py # 病历生成服务
│   │   ├── medical_record_pipeline.py # 整合服务
│   │   └── llm/           # LLM服务模块
│   │       ├── llm_service.py # LLM服务
│   │       ├── base.py    # 基础接口
│   │       ├── openai_compatible_adapter.py # OpenAI兼容适配器
│   │       └── prompts.py # Prompt模板
│   ├── utils/             # 工具函数
│   │   └── audio_utils.py # 音频处理工具
│   ├── config.py          # 配置管理
│   ├── database.py        # 数据库连接
│   └── main.py            # FastAPI应用入口
├── frontend/              # 前端代码
│   ├── css/              # 样式文件
│   │   └── style.css
│   ├── js/               # JavaScript逻辑
│   │   ├── upload.js     # 上传逻辑
│   │   └── result.js     # 结果展示逻辑
│   ├── index.html        # 上传页面
│   └── result.html       # 结果页面
├── config/               # 配置文件
│   ├── asr_correction_rules.json  # ASR纠错规则
│   ├── hotwords_medical.txt       # 医疗热词
│   ├── field_triggers.json        # 字段触发词表
│   └── medical_terms.json         # 医学术语词表
├── scripts/              # 测试脚本
│   ├── test_m2_milestone.py # M2里程碑测试
│   ├── test_qwen3_asr.py # Qwen3-ASR测试
│   └── demo_diarization.py # 说话人分离演示
├── data/                 # 数据存储
│   ├── audio/           # 音频文件存储
│   ├── database/        # SQLite数据库
│   └── logs/            # 日志文件
├── src/                  # FunASR模块
│   └── asr/             # ASR引擎
│       ├── funasr_engine.py # FunASR引擎
│       ├── qwen3_asr_engine.py # Qwen3-ASR引擎
│       └── factory.py   # ASR工厂
├── docs/                 # 文档
│   ├── architecture.md  # 架构文档
│   ├── completion_status.md # 完成状态记录
│   └── 开发任务清单.md  # 开发任务清单
├── requirements.txt      # Python依赖
└── README.md            # 项目文档
```

## API文档

启动服务后，访问以下地址查看API文档：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 主要接口

#### M1里程碑：音频转写接口

##### 1. 上传音频

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

##### 2. 开始转写

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

##### 3. 查询任务状态

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

##### 4. 获取转写结果

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
      "speaker": "spk0",
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

#### M2里程碑：病历生成接口

##### 5. 配置LLM服务

```http
POST /api/llm/config
Content-Type: application/json

Request:
{
  "config_name": "qwen",
  "provider": "openai_compatible",
  "model_name": "qwen-plus",
  "api_key": "your-api-key",
  "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "max_tokens": 2048,
  "temperature": "0.7",
  "is_active": true
}

Response:
{
  "success": true,
  "config_id": 1,
  "message": "LLM配置创建成功"
}
```

##### 6. 处理就诊记录生成病历

```http
POST /api/emr/process
Content-Type: application/json

Request:
{
  "visit_id": "uuid",
  "use_llm": true,
  "save_intermediate": true
}

Response:
{
  "visit_id": "uuid",
  "status": "completed",
  "evidence_count": 10,
  "normalized_terms_count": 11,
  "extracted_items_count": 20,
  "emr_record": {
    "record_id": 1,
    "version": 1,
    "record_type": "system_draft",
    "emr_json": {
      "subjective": {
        "text": "主诉：头疼三天...",
        "chief_complaint": {...},
        "history_present_illness": {...}
      },
      "objective": {...},
      "assessment": {...},
      "plan": {...}
    }
  },
  "errors": []
}
```

##### 7. 查询处理状态

```http
GET /api/emr/status/{visit_id}

Response:
{
  "visit_id": "uuid",
  "evidence_count": 10,
  "normalized_terms_count": 11,
  "extracted_items_count": 20,
  "has_emr": true,
  "emr_version": 1
}
```

##### 8. 获取病历记录

```http
GET /api/emr/record/{visit_id}?version=1

Response:
{
  "record_id": 1,
  "visit_id": "uuid",
  "version": 1,
  "record_type": "system_draft",
  "emr_json": {
    "subjective": {...},
    "objective": {...},
    "assessment": {...},
    "plan": {...}
  },
  "evidence_mapping": {
    "subjective.chief_complaint": [1, 2, 3],
    "assessment.diagnosis": [5, 6]
  },
  "validation_errors": null,
  "created_at": "2026-04-17T00:00:00"
}
```

##### 9. 获取所有版本

```http
GET /api/emr/versions/{visit_id}

Response:
{
  "visit_id": "uuid",
  "versions": [
    {
      "version": 1,
      "record_type": "system_draft",
      "created_at": "2026-04-17T00:00:00"
    },
    {
      "version": 2,
      "record_type": "reviewed",
      "created_at": "2026-04-17T01:00:00"
    }
  ]
}
```

## 配置说明

### 环境变量

创建 `.env` 文件（可选）：

```env
# 应用配置
APP_NAME=中文门诊病历生成系统
APP_VERSION=1.0.0
DEBUG=True

# 数据库配置
DATABASE_URL=sqlite:///data/database/medical.db

# 音频配置
AUDIO_STORAGE_PATH=data/audio
MAX_AUDIO_SIZE=104857600  # 100MB

# ASR配置
ASR_ENGINE=funasr
ASR_DEVICE=cpu  # 或 cuda
HOTWORD_PATH=config/hotwords_medical.txt

# 功能开关
ENABLE_DIARIZATION=True
ENABLE_ASR_CORRECTION=True
CORRECTION_CONFIDENCE_THRESHOLD=0.7
```

### ASR纠错规则

编辑 `config/asr_correction_rules.json` 添加自定义纠错规则：

```json
{
    "medical_terms": {
        "标准术语": ["错误识别1", "错误识别2"]
    },
    "pinyin_similar": {
        "标准术语": ["拼音相似词1", "拼音相似词2"]
    }
}
```

### 字段触发词表

编辑 `config/field_triggers.json` 配置证据选择触发词：

```json
{
  "chief_complaint": {
    "description": "主诉",
    "speaker_preference": "patient",
    "triggers": ["主诉", "哪里不舒服", "怎么了"],
    "weight": 1.0
  }
}
```

### 医学术语词表

编辑 `config/medical_terms.json` 配置术语规范化映射：

```json
{
  "symptoms": {
    "头痛": ["头疼", "脑袋疼", "头昏"],
    "发热": ["发烧", "体温高"]
  },
  "drugs": {
    "阿莫西林": ["阿莫西林", "阿莫仙"]
  }
}
```

## 注意事项

### 1. 模型下载

首次运行时，FunASR会自动下载以下模型：
- Paraformer-large（语音识别）
- FSMN-VAD（语音活动检测）
- CT-Transformer（标点恢复）

模型大小约1GB，下载时间取决于网络速度。

### 2. 音频格式

推荐使用：
- 采样率：16kHz
- 格式：WAV（PCM编码）
- 声道：单声道

系统会自动转换其他格式，但可能影响识别效果。

### 3. 说话人分离

当前版本使用FunASR的CAM++模型进行说话人分离：
- 支持自动识别不同说话人
- 输出格式：spk0, spk1, spk2...
- 角色识别（医生/患者）由后续大模型模块处理

### 4. 性能优化

- CPU模式：适合开发测试，速度较慢
- GPU模式：推荐使用CUDA，速度提升10-20倍

启用GPU：
```bash
# 安装CUDA版本的PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 修改配置
ASR_DEVICE=cuda
```

## 故障排除

### 1. 模型下载失败

```bash
# 手动下载模型到本地
export MODELSCOPE_CACHE=/path/to/model/cache
```

### 2. 音频处理错误

```bash
# 安装音频处理依赖
pip install librosa soundfile
```

### 3. 数据库错误

```bash
# 重新初始化数据库
rm data/database/medical.db
python -c "from backend.database import init_db; init_db()"
```

## 开发指南

### 里程碑进度

| 里程碑 | 目标 | 状态 |
|--------|------|------|
| M1 | 跑通音频到转写 | ✅ 已完成 |
| M2 | 跑通文本到病历 | ✅ 已完成 |
| M3 | 跑通审核闭环 | ✅ 已完成 |
| M4 | 跑通评测闭环 | ✅ 已完成 |

### 运行测试

```bash
# 测试M1里程碑（音频转写）
pytest tests/

# 测试M2里程碑（病历生成）
python scripts/test_m2_milestone.py

# 测试ASR引擎
python scripts/test_qwen3_asr.py audio.wav --device cpu
```

### 代码风格

```bash
# 格式化代码
black backend/

# 检查代码风格
flake8 backend/
```

## 贡献指南

欢迎提交Issue和Pull Request！

## 许可证

MIT License

## 联系方式

如有问题，请提交Issue或联系开发团队。
