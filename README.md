# 中文门诊病历生成系统

基于FunASR的中文门诊音频转写系统，支持说话人分离和医疗术语纠错。

## 功能特性

- ✅ 音频文件上传（支持WAV/MP3格式）
- ✅ 自动语音识别（ASR）转写
- ✅ 说话人分离（医生/患者）
- ✅ 医疗术语智能纠错
- ✅ 转写结果标准化
- ✅ Web界面展示
- ✅ 任务状态跟踪

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
cd MedicalAssisstant

# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

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
# 启动FastAPI服务
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动时，FunASR会自动下载模型（约1GB），请耐心等待。

### 5. 访问系统

打开浏览器访问: http://localhost:8000/

## 使用流程

### 1. 上传音频

- 访问首页
- 拖拽或点击上传音频文件（支持WAV/MP3）
- 填写患者姓名和就诊日期（可选）
- 点击"开始上传"

### 2. 开始转写

- 上传成功后自动跳转到结果页面
- 点击"开始转写"按钮
- 系统会在后台处理音频

### 3. 查看结果

- 转写完成后自动显示结果
- 医生发言显示为蓝色
- 患者发言显示为绿色
- 每段对话显示时间戳和置信度

## 项目结构

```
MedicalAssisstant/
├── backend/                 # 后端代码
│   ├── api/                # API接口
│   │   ├── upload.py      # 上传接口
│   │   ├── asr.py         # ASR转写接口
│   │   └── task.py        # 任务状态接口
│   ├── models/            # 数据模型
│   │   ├── visit.py       # 就诊记录模型
│   │   ├── transcript.py  # 转写记录模型
│   │   └── task.py        # 任务状态模型
│   ├── services/          # 业务逻辑
│   │   ├── asr_service.py # ASR服务
│   │   ├── postprocessor.py # 后处理纠错
│   │   └── normalizer.py  # 结果标准化
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
│   └── hotwords_medical.txt       # 医疗热词
├── data/                 # 数据存储
│   ├── audio/           # 音频文件存储
│   ├── database/        # SQLite数据库
│   └── logs/            # 日志文件
├── src/                  # FunASR模块
│   └── asr/             # ASR引擎
├── requirements.txt      # Python依赖
└── README.md            # 项目文档
```

## API文档

启动服务后，访问以下地址查看API文档：

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 主要接口

#### 1. 上传音频

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

#### 2. 开始转写

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

#### 3. 查询任务状态

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

#### 4. 获取转写结果

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

当前版本使用简单的交替映射策略：
- 偶数段 → 医生
- 奇数段 → 患者

后续版本将集成专业的说话人分离模型。

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

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_asr.py -v
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
