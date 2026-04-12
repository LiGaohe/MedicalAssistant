# M1里程碑设计方案：音频到转写闭环

## 文档信息

| 项目 | 内容 |
|------|------|
| 创建日期 | 2026-04-12 |
| 里程碑 | M1 - 跑通音频到转写 |
| 状态 | 已批准 |
| 作者 | AI Assistant |

## 1. 概述

### 1.1 目标

完成里程碑M1：跑通音频到转写，实现从音频上传到标准化转写结果的完整闭环。

### 1.2 范围

本设计涵盖以下任务：

- T4 音频上传与任务创建
- T5 funASR 接口封装（集成现有模块）
- T5.5 ASR 后处理纠错
- T6 转写结果标准化

### 1.3 交付物

- 可运行的FastAPI后端服务
- 简单的HTML前端界面
- SQLite数据库初始化
- 完整的ASR转写功能（含说话人分离和纠错）

## 2. 技术选型

### 2.1 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 前端 | HTML + JavaScript + CSS | 简单、快速开发 |
| 后端 | FastAPI + Uvicorn | 现代、高性能、自动文档 |
| 数据库 | SQLite + SQLAlchemy | 轻量级、无需安装 |
| ASR | FunASR (现有模块) | 已实现、可直接集成 |
| 文件存储 | 本地文件系统 | 简单、直接 |

### 2.2 选型理由

**FastAPI：**
- 现代、高性能、自动生成API文档
- 学习曲线平缓，适合快速开发
- 原生支持异步，适合ASR等耗时操作

**SQLite：**
- 轻量级、无需安装数据库服务
- 适合原型开发和单用户场景
- 后续可平滑迁移到PostgreSQL

**纯HTML + JavaScript：**
- 无需构建工具，开发速度快
- 适合简单的前端需求
- 后续可升级为Vue/React

## 3. 系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (HTML + JS)                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  上传页面   │  │  结果页面   │  │  音频播放   │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
                          ↓ HTTP API
┌─────────────────────────────────────────────────────────┐
│                    后端 (FastAPI)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  上传接口   │  │  ASR接口    │  │  任务接口   │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  ASR服务    │  │  后处理服务 │  │  标准化服务 │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│              现有ASR模块 (src/asr)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  FunASR引擎 │  │  MedASR引擎 │  │  工厂模式   │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│              数据存储 (SQLite + 文件系统)                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  visits表   │  │  turns表    │  │  tasks表    │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
│  ┌─────────────┐                                        │
│  │  音频文件   │                                        │
│  └─────────────┘                                        │
└─────────────────────────────────────────────────────────┘
```

### 3.2 数据流程图

```
音频上传 → 保存文件 → 创建visit记录 → 创建task记录
    ↓
调用ASR服务 → 转写音频 → 说话人分离
    ↓
ASR后处理纠错 → 术语纠错 → 拼音相似纠错
    ↓
转写结果标准化 → 格式统一 → 写入数据库
    ↓
前端展示结果
```

## 4. 项目结构

### 4.1 目录结构

```
MedicalAssisstant/
├── backend/                    # 后端代码
│   ├── __init__.py
│   ├── main.py                # FastAPI入口
│   ├── config.py              # 配置文件
│   ├── database.py            # 数据库连接
│   ├── models/                # 数据模型
│   │   ├── __init__.py
│   │   ├── visit.py           # 就诊记录模型
│   │   ├── transcript.py      # 转写记录模型
│   │   └── task.py            # 任务状态模型
│   ├── api/                   # API路由
│   │   ├── __init__.py
│   │   ├── upload.py          # 上传接口
│   │   ├── asr.py             # ASR转写接口
│   │   └── task.py            # 任务状态接口
│   ├── services/              # 业务逻辑
│   │   ├── __init__.py
│   │   ├── asr_service.py     # ASR服务
│   │   ├── postprocessor.py   # ASR后处理
│   │   └── normalizer.py      # 结果标准化
│   └── utils/                 # 工具函数
│       ├── __init__.py
│       └── audio_utils.py     # 音频处理工具
├── frontend/                  # 前端代码
│   ├── index.html            # 上传页面
│   ├── result.html           # 结果展示页面
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── upload.js         # 上传逻辑
│       └── result.js         # 结果展示逻辑
├── data/                      # 数据目录
│   ├── audio/                # 音频文件存储
│   ├── database/             # SQLite数据库文件
│   └── logs/                 # 日志文件
├── src/                       # 现有ASR模块（保持不变）
├── config/                    # 配置文件（保持不变）
│   ├── hotwords_medical.txt  # 医疗热词表
│   └── asr_correction_rules.json  # ASR纠错规则
├── docs/                      # 文档（保持不变）
├── scripts/                   # 脚本（保持不变）
├── requirements.txt           # 后端依赖
└── README.md                  # 项目说明
```

### 4.2 文件说明

| 文件/目录 | 说明 |
|----------|------|
| backend/main.py | FastAPI应用入口，配置路由和中间件 |
| backend/config.py | 配置管理，使用pydantic-settings |
| backend/database.py | 数据库连接和会话管理 |
| backend/models/ | SQLAlchemy数据模型 |
| backend/api/ | FastAPI路由处理器 |
| backend/services/ | 业务逻辑层 |
| backend/utils/ | 工具函数 |
| frontend/ | 前端静态文件 |
| data/ | 数据存储目录 |

## 5. 数据库设计

### 5.1 表结构

#### 5.1.1 visits表（就诊记录）

```sql
CREATE TABLE visits (
    visit_id TEXT PRIMARY KEY,           -- 就诊记录ID（UUID）
    patient_name TEXT,                   -- 患者姓名
    visit_date TEXT,                     -- 就诊日期
    audio_path TEXT NOT NULL,            -- 原始音频路径
    audio_duration REAL,                 -- 音频时长（秒）
    status TEXT DEFAULT 'pending',       -- 状态：pending, processing, completed, failed
    created_at TEXT NOT NULL,            -- 创建时间
    updated_at TEXT NOT NULL             -- 更新时间
);
```

#### 5.1.2 transcript_turns表（转写轮次）

```sql
CREATE TABLE transcript_turns (
    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id TEXT NOT NULL,              -- 关联就诊记录
    turn_index INTEGER NOT NULL,         -- 轮次索引
    speaker TEXT NOT NULL,               -- 说话人：doctor, patient, unknown
    text TEXT NOT NULL,                  -- 转写文本
    original_text TEXT,                  -- 原始文本（纠错前）
    corrected_text TEXT,                 -- 纠错后文本
    start_ms INTEGER NOT NULL,           -- 开始时间（毫秒）
    end_ms INTEGER NOT NULL,             -- 结束时间（毫秒）
    confidence REAL,                     -- 置信度
    created_at TEXT NOT NULL,
    FOREIGN KEY (visit_id) REFERENCES visits(visit_id)
);
```

#### 5.1.3 tasks表（任务状态）

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,            -- 任务ID（UUID）
    visit_id TEXT NOT NULL,              -- 关联就诊记录
    task_type TEXT NOT NULL,             -- 任务类型：upload, asr, postprocess
    status TEXT DEFAULT 'pending',       -- 状态：pending, running, completed, failed
    progress INTEGER DEFAULT 0,          -- 进度（0-100）
    error_message TEXT,                  -- 错误信息
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (visit_id) REFERENCES visits(visit_id)
);
```

#### 5.1.4 asr_corrections表（ASR纠错记录）

```sql
CREATE TABLE asr_corrections (
    correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id TEXT NOT NULL,
    turn_id INTEGER NOT NULL,
    original_word TEXT NOT NULL,         -- 原始词
    corrected_word TEXT NOT NULL,        -- 纠正后的词
    correction_type TEXT NOT NULL,       -- 纠错类型：medical_term, pinyin_similar
    confidence REAL,                     -- 纠错置信度
    created_at TEXT NOT NULL,
    FOREIGN KEY (visit_id) REFERENCES visits(visit_id),
    FOREIGN KEY (turn_id) REFERENCES transcript_turns(turn_id)
);
```

### 5.2 数据关系图

```
visits (1) ──────< (N) transcript_turns
   │
   └──────< (N) tasks
   │
   └──────< (N) asr_corrections
```

## 6. API接口设计

### 6.1 音频上传接口

```
POST /api/upload
Content-Type: multipart/form-data

Request:
- audio_file: 音频文件
- patient_name: 患者姓名（可选）
- visit_date: 就诊日期（可选，默认当前时间）

Response:
{
    "success": true,
    "visit_id": "uuid-xxx",
    "audio_path": "data/audio/uuid-xxx.wav",
    "audio_duration": 120.5,
    "message": "音频上传成功"
}
```

### 6.2 ASR转写接口

```
POST /api/asr/transcribe/{visit_id}

Request:
- visit_id: 就诊记录ID（路径参数）
- enable_diarization: 是否启用说话人分离（默认true）
- enable_correction: 是否启用ASR纠错（默认true）

Response:
{
    "success": true,
    "visit_id": "uuid-xxx",
    "task_id": "task-xxx",
    "status": "processing",
    "message": "ASR转写任务已启动"
}
```

### 6.3 任务状态查询接口

```
GET /api/task/{task_id}

Response:
{
    "task_id": "task-xxx",
    "visit_id": "uuid-xxx",
    "task_type": "asr",
    "status": "completed",
    "progress": 100,
    "error_message": null,
    "created_at": "2026-04-12T10:00:00",
    "updated_at": "2026-04-12T10:02:30"
}
```

### 6.4 转写结果查询接口

```
GET /api/transcript/{visit_id}

Response:
{
    "visit_id": "uuid-xxx",
    "status": "completed",
    "turns": [
        {
            "turn_id": 1,
            "turn_index": 0,
            "speaker": "doctor",
            "text": "您好，请问您哪里不舒服？",
            "original_text": "您好，请问您哪里不舒服？",
            "corrected_text": "您好，请问您哪里不舒服？",
            "start_ms": 0,
            "end_ms": 3000,
            "confidence": 0.95
        }
    ]
}
```

## 7. 核心模块设计

### 7.1 ASR服务模块

**职责：** 封装FunASR调用，提供转写和说话人分离功能

**关键方法：**
- `initialize()`: 初始化ASR引擎
- `transcribe(audio_path)`: 基础转写
- `transcribe_with_diarization(audio_path)`: 转写 + 说话人分离

**依赖：**
- 现有ASR模块 (src/asr)
- FunASR库
- 医疗热词表

### 7.2 ASR后处理模块

**职责：** 纠正ASR识别错误，提升医疗术语准确率

**关键方法：**
- `correct(text)`: 纠正文本中的ASR错误
- `_correct_medical_terms(text)`: 医疗术语纠错
- `_correct_by_pinyin(text)`: 拼音相似度纠错

**依赖：**
- ASR纠错规则表 (config/asr_correction_rules.json)
- pypinyin库（拼音处理）

### 7.3 转写结果标准化模块

**职责：** 统一转写结果格式，确保数据一致性

**关键方法：**
- `normalize(turns)`: 标准化转写轮次列表
- `_normalize_speaker(speaker)`: 标准化说话人标签
- `_normalize_text(text)`: 标准化文本格式
- `_normalize_punctuation(text)`: 标点规范化

## 8. 前端设计

### 8.1 上传页面

**功能：**
- 音频文件上传（支持拖拽）
- 患者信息填写（可选）
- 上传进度显示
- 上传成功后跳转到结果页面

**页面布局：**
```
┌─────────────────────────────────────────┐
│         中文门诊病历生成系统              │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │  拖拽音频文件到此处               │   │
│  │  或点击选择文件                   │   │
│  │  支持: wav, mp3                  │   │
│  └─────────────────────────────────┘   │
│                                         │
│  患者姓名: [__________________]         │
│  就诊日期: [2026-04-12        ]         │
│                                         │
│  [开始上传]                             │
│                                         │
│  上传进度: ████████░░ 80%               │
│                                         │
└─────────────────────────────────────────┘
```

### 8.2 结果展示页面

**功能：**
- 显示转写状态
- 显示转写轮次列表
- 区分医生和患者发言（颜色标识）
- 显示时间戳和置信度
- 支持重新转写

**页面布局：**
```
┌─────────────────────────────────────────────────────────┐
│  就诊记录: uuid-xxx                                      │
│  状态: 已完成  音频时长: 2分30秒                          │
│  [播放音频] [导出结果] [重新转写]                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ [0:00-0:03] 医生 (蓝色背景)                       │   │
│  │ 您好，请问您哪里不舒服？                          │   │
│  │ 置信度: 0.95 ✓                                   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │ [0:03-0:06] 患者 (绿色背景)                       │   │
│  │ 我头痛三天了                                      │   │
│  │ 置信度: 0.92 ✓                                   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## 9. 实施计划

### 9.1 阶段1：基础框架（预计1-2天）

**任务清单：**
- [ ] 创建项目目录结构
- [ ] 初始化数据库和表结构
- [ ] 实现音频上传接口
- [ ] 创建简单的HTML上传页面
- [ ] 集成现有ASR模块
- [ ] 实现基础转写接口

**验收标准：**
- ✅ 可以上传音频文件
- ✅ 数据库中有visit记录
- ✅ 音频文件落盘成功
- ✅ 可以调用ASR转写

### 9.2 阶段2：ASR增强（预计2-3天）

**任务清单：**
- [ ] 实现说话人分离功能
- [ ] 建立ASR纠错规则表
- [ ] 实现ASR后处理纠错模块
- [ ] 实现转写结果标准化
- [ ] 添加任务状态管理

**验收标准：**
- ✅ 能区分医生和患者发言
- ✅ 常见医疗术语ASR错误能被纠正
- ✅ 转写结果格式统一

### 9.3 阶段3：前端优化（预计1-2天）

**任务清单：**
- [ ] 实现转写结果展示页面
- [ ] 添加说话人颜色标识
- [ ] 集成音频播放器
- [ ] 实现时间戳跳转功能
- [ ] 添加导出功能

**验收标准：**
- ✅ 转写结果清晰展示
- ✅ 医生患者发言有颜色区分
- ✅ 可以播放音频并跳转

## 10. 测试方案

### 10.1 单元测试

**测试范围：**
- ASR服务模块
- ASR后处理模块
- 转写结果标准化模块

**测试工具：**
- pytest
- pytest-asyncio

### 10.2 集成测试

**测试范围：**
- API接口测试
- 数据库操作测试
- 文件上传测试

**测试工具：**
- FastAPI TestClient
- SQLite内存数据库

### 10.3 端到端测试

**测试场景：**
- 上传音频 → 转写 → 查看结果
- 上传音频 → 转写失败 → 查看错误信息
- 重新转写已有音频

## 11. 部署方案

### 11.1 环境准备

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境（Windows）
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 11.2 数据库初始化

```bash
# 初始化数据库
python -m backend.database init
```

### 11.3 启动服务

```bash
# 启动后端服务
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# 访问前端页面
# 浏览器打开: http://localhost:8000/
```

## 12. 风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| FunASR说话人分离效果不佳 | 中 | 先用简单映射，后续优化 |
| ASR纠错规则覆盖不足 | 低 | 渐进式扩充规则表 |
| 前端功能简单 | 低 | M1阶段够用即可 |
| SQLite并发性能限制 | 低 | 原型阶段单用户使用 |

## 13. 后续优化方向

### 13.1 短期优化（M2-M3）

- 改进说话人识别准确率
- 扩充ASR纠错规则表
- 优化前端用户体验
- 添加批量处理功能

### 13.2 长期优化（M4及以后）

- 引入机器学习模型进行ASR纠错
- 实现实时转写功能
- 支持更多音频格式
- 迁移到PostgreSQL数据库

## 14. 参考资料

- [FunASR官方文档](https://github.com/alibaba-damo-academy/FunASR)
- [FastAPI官方文档](https://fastapi.tiangolo.com/)
- [SQLAlchemy官方文档](https://docs.sqlalchemy.org/)
- 项目技术选型文档: `docs/技术选型文档.md`
- 项目架构文档: `docs/architecture.md`
- 开发任务清单: `docs/开发任务清单.md`
