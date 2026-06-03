# 项目架构文档

## 系统架构图

![系统架构图](./assets/system-architecture.png)

### 系统架构说明

系统采用分层架构设计，分为三层：

**输入层 (Input Layer)**：

- **ASR模块**：负责将语音信号转换为文本，支持实时转写和批量处理
- **原始文本**：作为事实来源，保存完整的对话内容

**处理层 (Processing Layer)**：

- **证据选择模块**：从对话文本中检索与病历生成相关的片段
- **术语规范化模块**：将口语化表达映射到标准医学术语，使用本地 ICD-11 中文术语库进行规范化（中文模式），支持 UMLS/SNOMED 概念检索（英文模式）
- **结构化生成模块**：基于LLM生成符合SOAP格式的结构化病历
- **验证模块**：检查生成病历的内容一致性，确保与原始对话相符。包含四步核查：Claim核查、Checklist核查、硬规则核查（部位矛盾/否定冲突）、确定性核查（诊断确定性层级是否被拔高）
- **医学本体库**：存储标准医学术语和概念，为术语规范化提供支持

**输出层 (Output Layer)**：

- **结构化病历**：最终输出的SOAP格式病历文档

## 数据流程图

![数据流程图](data-flow.svg)

### 数据流程说明

数据流程展示了从音频输入到结构化病历输出的完整处理过程：

**主要处理流程**：

1. **音频输入**：接收医疗问诊的音频数据
2. **ASR转写**：将音频转换为原始文本，保留时间戳和说话人信息
3. **原始文本**：存储完整的对话文本作为后续处理的事实依据
4. **证据选择**：从对话中提取与病历相关的关键片段
5. **术语规范化**：将口语化术语映射为标准医学术语，中文模式使用本地 ICD-11 中文术语库和口语同义词映射表进行规范化，英文模式查询 UMLS 医学本体库获取概念编码
6. **结构化生成**：基于规范化后的证据生成SOAP格式病历
7. **验证检查**：验证病历内容的完整性和一致性
8. **结构化病历**：输出最终的结构化病历文档

**数据交互**：

- 术语规范化模块与医学本体库交互，获取标准术语映射
- 各模块间通过标准化的数据格式传递信息

## 当前目录结构

```
MedicalAssisstant/
├── backend/                    # 后端服务
│   ├── api/                   # API 路由
│   │   ├── __init__.py
│   │   ├── asr.py             # ASR 相关 API
│   │   ├── task.py            # 任务管理 API
│   │   ├── upload.py          # 上传 API
│   │   ├── llm.py             # LLM 配置管理 API
│   │   ├── emr.py             # 病历生成 API
│   │   └── evaluation.py      # 病历质量评估 API
│   ├── models/                # 数据模型
│   │   ├── __init__.py
│   │   ├── task.py            # 任务模型
│   │   ├── transcript.py      # 转写记录模型（含ASRCorrection）
│   │   ├── visit.py           # 就诊记录模型
│   │   ├── llm_config.py      # LLM配置模型（含JSON模式、思考模式）
│   │   ├── evidence.py        # 证据片段模型
│   │   ├── term.py            # 规范化术语模型（含UMLS编码）
│   │   ├── extracted_item.py  # 抽取要素模型
│   │   ├── emr_record.py      # 病历记录模型
│   │   ├── atomic_fact.py     # 原子事实模型（阶段2核心中间表示，含subsection细粒度字段分类）
│   │   └── evaluation_record.py # 评估记录模型
│   ├── services/              # 业务服务
│   │   ├── __init__.py
│   │   ├── asr_service.py     # ASR 服务（封装FunASR）
│   │   ├── normalizer.py      # 术语规范化服务
│   │   ├── postprocessor.py   # 后处理服务（医疗术语纠错）
│   │   ├── llm/               # LLM服务模块
│   │   │   ├── __init__.py
│   │   │   ├── base.py        # LLM基类
│   │   │   ├── openai_compatible_adapter.py # OpenAI兼容接口（支持JSON模式、思考模式）
│   │   │   ├── prompts.py     # Prompt模板管理（中英文）
│   │   │   └── llm_service.py # LLM服务封装
│   │   ├── umls/              # UMLS医学术语库模块
│   │   │   ├── __init__.py    # 数据类定义
│   │   │   ├── umls_client.py # UMLS API客户端（同步）
│   │   │   ├── async_umls_client.py # UMLS API客户端（异步，支持并发）
│   │   │   └── term_cache.py  # 术语缓存管理
│   │   ├── llm_pipeline_service.py    # LLM多阶段处理（中文提示词）
│   │   ├── llm_pipeline_service_en.py # LLM多阶段处理（英文提示词，跳过翻译优化）
│   │   ├── evidence_service.py # 证据选择服务
│   │   ├── terminology_service.py # 术语规范化服务（集成UMLS + 本地ICD-11中文术语库，支持并行处理）
│   │   ├── translation_service.py # 中英文翻译服务（专门翻译小模型）
│   │   ├── extraction_service.py # 病历要素抽取服务
│   │   ├── emr_generation_service.py # 病历生成服务
│   │   ├── medical_record_pipeline.py # 病历生成流水线（支持并行处理）
│   │   ├── fact_service.py    # 原子事实CRUD服务（阶段2输出）
│   │   ├── evaluation/         # 病历质量评估模块
│   │   │   ├── __init__.py     # 模块入口
│   │   │   ├── base.py         # 评估器基类
│   │   │   ├── consistency.py  # 一致性评估服务
│   │   │   ├── completeness.py # 完整性评估服务
│   │   │   ├── quality.py      # 文档质量评估服务
│   │   │   ├── safety.py       # 安全风险评估服务
│   │   │   └── evaluation_pipeline.py # 评估流水线
│   │   └── validation_service.py # 病历验证服务（规则验证）
│   │   ├── pipeline/            # LLM流水线子模块（SOLID重构后 16 个文件）
│   │   │   ├── __init__.py
│   │   │   ├── base.py            # PipelineContext 数据传递对象 + PipelineStage 抽象接口
│   │   │   ├── orchestrator.py    # PipelineOrchestrator 核心编排器（含skip_cleaning/skip_hallucination_check/stop_after_draft流程控制、幻觉检查、_format_turns直接格式化、_compute_changes变更计算）
│   │   │   ├── utils.py           # JSON解析工具函数
│   │   │   ├── speaker_handler.py # 说话人角色处理
│   │   │   ├── debug_interactor.py # Debug交互器
│   │   │   ├── evidence_enricher.py # 证据溯源富化器
│   │   │   ├── emr_persistence.py # EMR持久化服务
│   │   │   ├── interactive.py     # 交互式分步处理服务
│   │   │   ├── stages/            # Pipeline阶段实现（PipelineStage子类）
│   │   │   │   ├── __init__.py
│   │   │   │   ├── turn_cleaning.py    # 阶段1: 转写清洗与角色纠错
│   │   │   │   ├── direct_soap_generation.py  # 阶段2: 直接草稿生成
│   │   │   │   ├── hallucination_check.py    # 阶段2.5: 幻觉检查（草稿生成后立即核查全SOAP各字段与对话的一致性）
│   │   │   │   ├── claim_verification.py    # 阶段3: 后置核查（Claim/Checklist/硬规则/确定性四步核查）
│   │   │   ├── soap_structuring.py      # 阶段3: 草稿结构化（自由文本草稿→SOAP JSON）
│   │   │   └── field_revision.py        # 阶段4: 字段级修订与落盘
│   ├── utils/                 # 工具函数
│   │   ├── __init__.py
│   │   └── audio_utils.py     # 音频处理工具
│   ├── __init__.py
│   ├── config.py              # 配置管理（pydantic-settings）
│   ├── database.py            # 数据库连接（SQLAlchemy）
│   └── main.py                # FastAPI应用入口
├── config/                     # 配置文件
│   ├── asr_correction_rules.json # ASR 纠正规则（医疗术语映射）
│   └── hotwords_medical.txt    # 医疗热词表（80+术语）
├── data/                       # 数据存储（运行时创建）
│   ├── audio/                  # 上传的音频文件
│   ├── cache/                  # 缓存数据
│   │   └── umls/               # UMLS术语缓存
│   └── database/               # SQLite数据库文件
├── docs/                       # 文档
│   ├── architecture.md         # 架构文档 (本文件)
│   ├── completion_status.md    # 完成状态记录
│   ├── 技术选型文档.md          # ASR技术选型分析
│   ├── 说话人分离使用说明.md    # 说话人分离功能说明
│   └── specs/                  # 规格文档
│       └── 2026-04-12-m1-milestone-design.md
├── .trae/                      # Trae工具目录
│   └── documents/              # Trae文档
│       └── 病历生成流程性能优化计划.md # 性能优化计划文档
├── scripts/                    # 实验与工具脚本
│   ├── __init__.py
│   ├── prepare_test_data.py   # 测试数据准备脚本（从IMCS-MRG抽取样本）
│   ├── run_batch_experiments.py # 批量实验运行脚本（四种方案 × 五种消融配置）
│   └── aggregate_results.py   # 评估结果汇总脚本（ROUGE/BLEU/字段级聚合）
├── frontend/                   # 前端界面
│   ├── css/
│   │   ├── style.css          # 样式文件
│   │   └── ide.css            # IDE布局样式（VS Code暗色主题）
│   ├── js/
│   │   ├── app.js             # IDE主控制器（全局状态、活动栏、事件总线）
│   │   ├── cache.js           # localStorage 缓存管理（EMR数据持久化）
│   │   ├── agent.js           # Agent助手面板（音频上传、转写、病历生成、后处理阶段选择、定稿保存）
│   │   ├── editor.js          # 病历编辑器面板（SOAP显示、编辑、版本管理、打印）
│   │   ├── debug.js           # 调试面板（LLM多阶段调试）
│   │   ├── config-sidebar.js  # LLM配置面板
│   │   ├── history.js         # 历史病历面板（列表查看、删除）
│   │   ├── config.js          # LLM配置页面脚本
│   │   ├── evaluation.js      # 评估页面脚本
│   │   ├── emr.js             # 旧病历页面脚本
│   │   ├── result.js          # 转写结果页面脚本
│   │   └── upload.js          # 旧上传页面脚本
│   ├── emr.html               # IDE主界面（单页应用入口）
│   ├── index.html             # 上传页面
│   ├── result.html            # 转写结果页面
│   ├── evaluation.html        # 病历质量评估页面
│   └── config.html            # LLM配置页面
├── output/                     # 输出目录
│   └── raw_asr_result.json    # ASR原始输出
├── scripts/                    # 脚本
│   ├── demo_diarization.py    # 说话人分离演示
│   ├── test_diarization.py    # 说话人分离测试
│   ├── test_diarization_debug.py # 调试脚本
│   ├── test_diarization_with_tts.py # TTS测试脚本
│   ├── test_qwen3_asr.py      # Qwen3-ASR测试脚本
│   ├── test_translation_service.py # 翻译服务测试脚本
│   ├── test_parallel_terminology.py # 术语规范化并行测试脚本
│   ├── test_performance_optimization.py # 性能优化测试脚本
│   └── set_cache_path.bat     # 设置缓存路径脚本
├── src/                        # 核心源代码
│   ├── asr/                   # ASR 模块
│   │   ├── __init__.py        # 模块入口
│   │   ├── base.py            # 抽象基类（ASRResult数据类）
│   │   ├── factory.py         # 工厂模式
│   │   ├── funasr_engine.py   # FunASR 实现（支持说话人分离）
│   │   ├── medasr_engine.py   # MedASR 实现（仅英文）
│   │   ├── qwen3_asr_engine.py # Qwen3-ASR 实现（高性能中文ASR）
│   │   └── test_confid.py     # 置信度测试
│   └── __init__.py
├── .gitignore
├── README.md                   # 项目说明
├── requirements.txt           # 项目依赖
└── requirements-asr.txt       # ASR专用依赖
```

## 系统架构设计

### 设计原则

本系统采用分层架构：

- **事实来源单一**：对话文本作为唯一事实来源
- **分层处理**：证据选择 → 术语规范化 → 结构化生成 → 验证
- **受控术语增强**：术语规范化作为受控的第二步，而非开放式检索

## 详细系统设计

### 1. ASR模块详细设计

#### 1.1 ASR模块整体流程

```mermaid
graph TB
    A[音频输入] --> B[音频预处理]
    B --> C{音频时长判断}
    C -->|短音频 < 30s| D[直接转写]
    C -->|长音频 ≥ 30s| E[VAD切分]
    E --> F[分段转写]
    D --> G[标点恢复]
    F --> G
    G --> H[热词增强]
    H --> I[时间戳生成]
    I --> J[文本输出]
    
    style A fill:#e1f5ff
    style J fill:#e8f5e9
    style E fill:#fff3e0
    style H fill:#fce4ec
```

#### 1.2 音频预处理流程

```mermaid
graph LR
    A[原始音频] --> B[格式检查]
    B --> C{采样率}
    C -->|≠ 16kHz| D[重采样至16kHz]
    C -->|= 16kHz| E[声道检查]
    D --> E
    E --> F{声道数}
    F -->|多声道| G[转为单声道]
    F -->|单声道| H[音量归一化]
    G --> H
    H --> I[预处理完成]
    
    style A fill:#e1f5ff
    style I fill:#e8f5e9
```

**实现步骤：**

1. **格式检查**
   - 支持格式：WAV、MP3、FLAC、OGG
   - 不支持格式：返回错误提示
2. **采样率标准化**
   - 目标采样率：16000 Hz
   - 重采样算法：librosa.resample()
   - 原因：ASR模型训练时使用16kHz
3. **声道处理**
   - 多声道音频：取平均值转为单声道
   - 单声道音频：直接使用
   - 原因：医疗问诊场景通常为单声道录音
4. **音量归一化**
   - 目标：峰值音量归一化到-3dB
   - 方法：计算音频RMS值，应用增益
   - 原因：提高识别稳定性

#### 1.3 长音频切分策略

```mermaid
graph TB
    A[长音频输入] --> B[VAD静音检测]
    B --> C{静音段识别}
    C -->|静音 > 500ms| D[切分点标记]
    C -->|静音 < 500ms| E[继续检测]
    D --> F[分段边界确定]
    F --> G{分段时长检查}
    G -->|时长 > 30s| H[强制切分]
    G -->|时长 ≤ 30s| I[保留分段]
    H --> I
    I --> J[分段音频输出]
    
    style A fill:#e1f5ff
    style J fill:#e8f5e9
    style B fill:#fff3e0
```

**切分规则：**

| 规则类型   | 参数值    | 说明              |
| ------ | ------ | --------------- |
| 静音阈值   | -40 dB | 低于此值视为静音        |
| 最小静音时长 | 500 ms | 静音持续超过此时长才切分    |
| 最大分段时长 | 30 秒   | 单段不超过30秒，避免内存溢出 |
| 最小分段时长 | 1 秒    | 单段至少1秒，避免碎片化    |
| 边界缓冲   | 100 ms | 切分点前后各保留100ms静音 |

**VAD模型选择：**

- **FunASR-VAD**：基于FSMN的语音活动检测模型（听到当前声音时，它会快速翻看记忆中记录的之前几秒和之后几秒的关键信息，结合完整的上下文再做判断）
- **优势**：准确率高，支持实时检测
- **输出**：每个语音段的起止时间戳

#### 1.4 静音处理策略

```mermaid
graph TB
    A[音频流] --> B[静音检测]
    B --> C{静音类型}
    C -->|句首静音| D[保留200ms]
    C -->|句中静音| E[保留原样]
    C -->|句尾静音| F[保留200ms]
    C -->|长静音 > 2s| G[标记为分段点]
    D --> H[输出处理后的音频]
    E --> H
    F --> H
    G --> I[触发分段]
    
    style A fill:#e1f5ff
    style H fill:#e8f5e9
    style I fill:#fff3e0
```

**处理策略：**

1. **句首静音**
   - 保留前200ms静音
   - 原因：避免语音起始部分被截断
2. **句中静音**
   - 保留原样
   - 原因：自然停顿，有助于理解语义
3. **句尾静音**
   - 保留后200ms静音
   - 原因：避免语音结尾部分被截断
4. **超长静音**
   - 静音超过2秒，标记为分段点
   - 原因：可能表示话题切换

#### 1.5 文本标点恢复

```mermaid
graph LR
    A[无标点文本] --> B[标点预测模型]
    B --> C{标点类型}
    C -->|逗号| D[插入,]
    C -->|句号| E[插入。]
    C -->|问号| F[插入?]
    C -->|感叹号| G[插入!]
    D --> H[标点文本输出]
    E --> H
    F --> H
    G --> H
    
    style A fill:#e1f5ff
    style H fill:#e8f5e9
    style B fill:#fff3e0
```

**实现方案：**

| 方案             | 模型        | 准确率  | 速度 | 适用场景       |
| -------------- | --------- | ---- | -- | ---------- |
| FunASR-CT-Punc | ct-punc   | 95%+ | 快  | 中文医疗场景（推荐） |
| 基于规则           | 正则表达式     | 70%  | 极快 | 简单场景       |
| 基于BERT         | BERT-punc | 98%  | 慢  | 高精度要求      |

**标点恢复流程：**

1. **输入**：ASR输出的无标点文本
2. **分词**：按字符切分（中文）
3. **预测**：模型预测每个位置后的标点类型
4. **插入**：根据预测结果插入标点符号
5. **后处理**：修正明显的标点错误（如连续标点）

#### 1.6 时间戳生成

```mermaid
graph TB
    A[音频分段] --> B[分段转写]
    B --> C[字级别对齐]
    C --> D[时间戳计算]
    D --> E[全局时间戳映射]
    E --> F[时间戳输出]
    
    subgraph 时间戳信息
        G[字级别时间戳]
        H[词级别时间戳]
        I[句子级别时间戳]
    end
    
    F --> G
    F --> H
    F --> I
    
    style A fill:#e1f5ff
    style F fill:#e8f5e9
    style C fill:#fff3e0
```

**时间戳层级：**

| 层级   | 粒度   | 用途         |
| ---- | ---- | ---------- |
| 字级别  | 每个汉字 | 精确定位、字幕生成  |
| 词级别  | 每个词语 | 关键词检索、术语提取 |
| 句子级别 | 每个句子 | 章节划分、摘要生成  |

**时间戳计算方法：**

1. **分段偏移量**：记录每个分段在整个音频中的起始时间
2. **字级别对齐**：使用CTC解码路径计算每个字的起止时间
3. **全局映射**：分段偏移量 + 字级别时间 = 全局时间戳

**输出格式：**

```json
{
  "text": "患者主诉头痛三天",
  "segments": [
    {
      "start": 0.0,
      "end": 2.5,
      "text": "患者主诉头痛三天",
      "words": [
        {"word": "患者", "start": 0.0, "end": 0.5},
        {"word": "主诉", "start": 0.6, "end": 1.1},
        {"word": "头痛", "start": 1.2, "end": 1.7},
        {"word": "三天", "start": 1.8, "end": 2.5}
      ]
    }
  ]
}
```

#### 1.7 热词增强机制

```mermaid
graph TB
    A[医疗热词表] --> B[热词加载]
    B --> C[热词编码]
    C --> D[ASR解码]
    D --> E{热词匹配}
    E -->|匹配成功| F[提升解码概率]
    E -->|未匹配| G[正常解码]
    F --> H[输出文本]
    G --> H
    
    style A fill:#e1f5ff
    style H fill:#e8f5e9
    style F fill:#fff3e0
```

**热词表结构：**

| 字段 | 说明          | 示例        |
| -- | ----------- | --------- |
| 术语 | 医学专业术语      | 阿莫西林、头孢克肟 |
| 权重 | 提升权重（1-100） | 50        |
| 类别 | 术语类别        | 药品、症状、诊断  |

**热词增强原理：**

1. **解码阶段介入**：在ASR解码时，遇到热词表中的词，提升其解码概率
2. **权重计算**：`新概率 = 原概率 × (1 + 权重/100)`
3. **动态调整**：根据上下文动态调整热词权重

**热词表管理：**

- **初始热词表**：包含80+常见医疗术语
- **动态扩展**：根据科室需求添加专业术语
- **权重优化**：根据识别准确率调整权重

#### 1.8 后续服务对接

```mermaid
graph TB
    A[ASR输出] --> B[文本后处理]
    B --> C[格式标准化]
    C --> D{输出目标}
    D -->|实时显示| E[WebSocket推送]
    D -->|文件存储| F[JSON文件保存]
    D -->|数据库存储| G[数据库写入]
    D -->|LLM处理| H[病历生成模块]
    
    style A fill:#e1f5ff
    style E fill:#e8f5e9
    style F fill:#e8f5e9
    style G fill:#e8f5e9
    style H fill:#fff3e0
```

**对接方案：**

| 目标系统  | 接口类型      | 数据格式     | 实时性 |
| ----- | --------- | -------- | --- |
| 前端显示  | WebSocket | JSON     | 实时  |
| 文件存储  | 文件系统      | JSON/TXT | 批量  |
| 数据库   | SQL/NoSQL | 结构化数据    | 批量  |
| LLM模块 | HTTP API  | JSON     | 实时  |

**数据标准化：**

1. **文本清洗**：去除多余空格、标点规范化
2. **说话人分离**：区分医生和患者（需说话人识别模块）
3. **时间戳同步**：确保时间戳与文本对应
4. **格式转换**：转换为下游模块所需格式

#### 1.9 Qwen3-ASR引擎

Qwen3-ASR是阿里巴巴开源的高性能语音识别模型，支持52种语言（包括22种中文方言）。

**模型规格：**

| 模型 | 参数量 | 显存需求 | RTF | 适用场景 |
|------|--------|----------|-----|----------|
| Qwen3-ASR-1.7B | ~2B | 4GB+ | ~0.064 | 高精度转写 |
| Qwen3-ASR-0.6B | ~0.9B | 2GB+ | ~0.064 | 快速转写 |

**架构特点：**

```
Audio (16kHz) → 128-mel Spectrogram → Conv2d×3 (8× downsample)
             → Transformer Encoder → Linear Projector → Qwen3 Decoder → Text
```

**与FunASR对比：**

| 特性 | Qwen3-ASR | FunASR |
|------|-----------|--------|
| 中文准确率 | SOTA (AISHELL-2: 2.71% CER) | 高 (AISHELL-2: 2.85% CER) |
| 说话人分离 | 不支持 | 支持 (cam++模型) |
| 热词增强 | 不支持 | 支持 |
| 长音频处理 | 自动分块 | VAD切分 |
| 流式推理 | 支持 | 支持 |

**使用建议：**

- **需要说话人分离**：使用FunASR
- **仅需高精度转写**：使用Qwen3-ASR
- **医疗术语识别**：FunASR + 热词增强

### 2. 语音采集模块设计

#### 2.1 音频采集流程

```mermaid
graph TB
    A[麦克风初始化] --> B[音频流采集]
    B --> C[缓冲区管理]
    C --> D{缓冲区状态}
    D -->|已满| E[数据输出]
    D -->|未满| F[继续采集]
    E --> G[音频数据块]
    F --> B
    G --> H[实时传输]
    
    style A fill:#e1f5ff
    style G fill:#e8f5e9
    style C fill:#fff3e0
```

**采集参数：**

| 参数    | 值            | 说明      |
| ----- | ------------ | ------- |
| 采样率   | 16000 Hz     | ASR模型要求 |
| 位深度   | 16 bit       | 标准音频质量  |
| 声道数   | 1            | 单声道     |
| 缓冲区大小 | 1024 samples | 约64ms延迟 |

#### 2.2 多麦克风支持

```mermaid
graph LR
    A[音频输入] --> B{麦克风选择}
    B -->|单麦克风| C[直接采集]
    B -->|多麦克风| D[麦克风阵列]
    D --> E[波束成形]
    E --> F[降噪处理]
    F --> G[增强音频]
    C --> H[音频输出]
    G --> H
    
    style A fill:#e1f5ff
    style H fill:#e8f5e9
    style E fill:#fff3e0
```

**多麦克风处理：**

1. **波束成形**：聚焦目标声源方向
2. **噪声抑制**：利用多麦克风信息降低环境噪声
3. **回声消除**：去除扬声器回声

### 3. 结构化病历生成模块设计

#### 3.1 病历生成流程

```mermaid
graph TB
    A[对话文本] --> B[证据选择]
    B --> C[术语规范化]
    C --> D[结构化生成]
    D --> E[验证检查]
    E --> F{验证通过?}
    F -->|是| G[输出病历]
    F -->|否| H[人工审核]
    H --> I[修正病历]
    I --> G
    
    style A fill:#e1f5ff
    style G fill:#e8f5e9
    style B fill:#fff3e0
    style C fill:#fff3e0
```

#### 3.2 证据选择模块

```mermaid
graph LR
    A[对话文本] --> B[文本分段]
    B --> C[向量化]
    C --> D[相似度计算]
    D --> E[证据片段]
    
    style A fill:#e1f5ff
    style E fill:#e8f5e9
```

**实现方法：**

| 方法   | 技术                 | 优势      | 劣势      |
| ---- | ------------------ | ------- | ------- |
| 向量检索 | Embedding + Cosine | 语义理解强   | 需要预训练模型 |
| BM25 | TF-IDF变体           | 速度快、可解释 | 语义理解弱   |
| 混合检索 | 向量 + BM25          | 综合优势    | 实现复杂    |

#### 3.3 术语规范化模块

##### 3.3.1 串行处理流程（原有）

```mermaid
graph TB
    A[文本输入] --> B[LLM识别口语术语]
    B --> C[获取术语列表]
    C --> D{UMLS可用?}
    D -->|是| E[UMLS检索标准术语]
    D -->|否| F[LLM规范化兜底]
    E --> G{有候选?}
    G -->|是| H{候选数 > 1?}
    G -->|否| F
    H -->|是| I[LLM选择最佳候选]
    H -->|否| J[使用首个候选]
    I --> K[获取CUI/ICD-10编码]
    J --> K
    K --> L[返回UMLS结果]
    F --> M[返回LLM结果]
    L --> N[输出规范化结果]
    M --> N
    
    style A fill:#e1f5ff
    style N fill:#e8f5e9
    style B fill:#fff3e0
    style E fill:#fff3e0
    style I fill:#fff3e0
```

##### 3.3.2 并行处理流程（优化后）

```mermaid
graph TB
    A[文本输入] --> B[LLM识别口语术语]
    B --> C[获取术语列表]
    C --> D[去重处理]
    D --> E[批量翻译]
    E --> F[并行UMLS检索]
    F --> G[批量LLM候选选择]
    G --> H[结果合并]
    H --> I[输出规范化结果]
    
    style A fill:#e1f5ff
    style I fill:#e8f5e9
    style E fill:#fff3e0
    style F fill:#fff3e0
    style G fill:#fff3e0
```

**并行处理流水线架构**：

```
identify_colloquial_terms (批量识别)
    ↓
┌─────────────────────────────────────────────────────┐
│              并行处理流水线                           │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐│
│  │ 批量翻译     │→ │ 并行UMLS检索 │→ │ 批量LLM选择  ││
│  │ (翻译模型)   │  │ (asyncio)    │  │ (单次LLM调用)││
│  └──────────────┘  └──────────────┘  └──────────────┘│
└─────────────────────────────────────────────────────┘
    ↓
结果合并与返回
```

**并行优化核心组件**：

| 组件 | 文件 | 功能 |
|------|------|------|
| AsyncUMLSClient | `backend/services/umls/async_umls_client.py` | 异步UMLS客户端，支持并发HTTP请求 |
| TranslationService | `backend/services/translation_service.py` | 翻译服务，支持批量翻译 |
| TerminologyService | `backend/services/terminology_service.py` | 术语规范化服务，集成并行处理 |

**性能对比**：

| 测试项 | 串行耗时 | 并行耗时 | 提升 |
|--------|---------|---------|------|
| 批量翻译 (5个术语) | 0.88秒 | 0.43秒 | 2.06x |
| 异步UMLS检索 (5个术语) | - | 4.17秒 | 并发执行 |
| 整体对比 (12个术语) | 436秒 | 229秒 | 1.90x |

**降级策略**：

```
并行模式启用 + AsyncUMLSClient可用 → 并行处理
并行模式禁用 或 AsyncUMLSClient不可用 → 串行处理（原有逻辑）
并行处理失败 → 自动回退到串行处理
```

**并行配置项**：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `UMLS_MAX_CONCURRENT` | 5 | UMLS API最大并发请求数 |
| `TERMINOLOGY_PARALLEL_ENABLED` | True | 是否启用并行模式 |

##### 3.3.3 术语规范化流程说明

| 步骤 | 处理方式 | 置信度范围 | 说明 |
| --- | --- | --- | --- |
| 1. 预检匹配 | exact/alias 匹配 | 0.85-1.0 | 中文模式 exact 或 synonym 命中时直接返回 |
| 2. 多概念拆解 | LLM拆解 + 递归规范化 | - | 含并列词时拆解为atomic mention分别处理 |
| 3. 语言分流检索 | 中文：本地术语库(ChineseTerm/ICD-11+口语同义词)；英文：UMLS | 0.60-0.95 | 按语言选择检索源，中英文路径互斥 |
| 4. Rewrite改写 | LLM口语→临床改写 | - | 初轮检索置信度 < 阈值时触发 |
| 5. Alternative Phrasing | LLM等价别名生成 | - | Rewrite后仍低置信度时触发 |
| 6. 约束选择 | LLM从候选中选择 | 0.30-0.95 | 只能从候选列表选择，无匹配返回unresolved |
| 7. 兜底保留 | 保留原词 | 0.30 | 所有方法都失败时保留原词，标记unresolved |

**中英文路径互斥**：

- 中文模式（language=="zh"）：只使用本地术语库（ChineseTerm/ICD-11+口语同义词映射），不走UMLS
- 英文模式（language!="zh"）：只使用UMLS，不走本地术语库
- 并行模式 `extract_and_normalize_terms_parallel()` 同样遵循语言分流

##### 3.3.4 草稿后处理两步规范化流程（`normalize_draft_terms()`）

在四阶段流水线中，阶段2.5 使用 `normalize_draft_terms()` 对 SOAP 草稿进行术语规范化，采用两步流程：

| 步骤 | 处理方式 | 说明 |
| --- | --- | --- |
| 1. 术语提取 | 正则提取 | 中文提取2-6字词组，英文提取2-4词短语 |
| 2. LLM规范化 | `term_standardization` prompt | 批量将口语术语规范为医学标准用语，输出术语而非句子 |
| 3a. ICD-11检索（中文） | 先精确后模糊（≥0.7） | 用LLM规范化结果在本地ICD-11术语库检索标准术语和编码 |
| 3b. UMLS检索（英文） | 选最高分preferred term | 用LLM规范化结果在UMLS检索标准术语和CUI |
| 4. 替换回草稿 | 字符串替换 | 仅替换原术语≠规范化术语的条目 |

**关键设计**：

- ICD-11不具备口语到规范术语的映射能力，因此先由LLM将口语规范为医学标准用语，再用术语库检索
- 术语库无匹配时保留LLM规范化结果，不回退到原口语术语
- 中文路径在LLM规范化前先用 colloquial_synonyms.json 做快速替换

**UMLS集成特性：**

| 特性 | 说明 |
| --- | --- |
| LLM识别术语 | 使用LLM从文本中识别口语化医学术语，无需依赖静态词表 |
| 混合查询 | 优先中文查询，无结果时翻译后英文查询 |
| 候选选择 | 多候选时由LLM选择最佳匹配 |
| 编码获取 | 自动获取ICD-10/SNOMED-CT编码 |
| 缓存机制 | 本地缓存查询结果，减少API调用 |
| 降级策略 | UMLS不可用时自动降级到LLM方案 |

**本体库选择：**

| 本体库 | 覆盖范围 | 语言 | 访问方式 | 当前状态 |
| --- | --- | --- | --- | --- |
| UMLS | 全面 | 多语言 | 需申请许可 | ✅ 已集成 |
| SNOMED CT | 临床术语 | 多语言 | 需申请许可 | 🔜 预留接口 |
| ICD-10 | 诊断编码 | 多语言 | 公开可用 | ✅ 通过UMLS获取 |
| MeSH | 医学主题词 | 英文 | 公开可用 | 🔜 预留接口 |

**规范化输出格式：**

```json
{
  "original_term": "头疼",
  "normalized_term": "头痛",
  "term_type": "symptom",
  "code": "R51",
  "code_system": "ICD-10-CM",
  "source": "UMLS",
  "confidence": 0.95,
  "cui": "C0018681",
  "candidates": [
    {"term": "头痛", "cui": "C0018681", "score": 0.95},
    {"term": "偏头痛", "cui": "C0149931", "score": 0.72}
  ]
}
```

#### 3.4 结构化生成模块

```mermaid
graph LR
    A[证据片段] --> B[Prompt构建]
    B --> C[LLM推理]
    C --> D[结构化输出]
    D --> E[格式验证]
    E --> F[病历JSON]
    
    style A fill:#e1f5ff
    style F fill:#e8f5e9
    style C fill:#fff3e0
```

**SOAP格式定义：**

| 章节             | 内容   | 示例               |
| -------------- | ---- | ---------------- |
| S (Subjective) | 主观症状 | 患者主诉头痛三天         |
| O (Objective)  | 客观体征 | 体温37.5℃，血压120/80 |
| A (Assessment) | 评估诊断 | 上呼吸道感染           |
| P (Plan)       | 治疗计划 | 口服阿莫西林，多饮水       |

#### 3.5 验证模块

```mermaid
graph TB
    A[生成病历] --> B[规则检查]
    B --> C{规则通过?}
    C -->|否| D[标记错误]
    C -->|是| E[LLM验证]
    E --> F{一致性检查}
    F -->|不一致| G[标记疑问]
    F -->|一致| H[验证通过]
    D --> I[人工审核队列]
    G --> I
    H --> J[输出最终病历]
    
    style A fill:#e1f5ff
    style J fill:#e8f5e9
    style B fill:#fff3e0
    style E fill:#fff3e0
```

**验证规则：**

| 规则类型  | 检查内容      | 示例          |
| ----- | --------- | ----------- |
| 完整性检查 | 必填字段是否存在  | SOAP各章节是否完整 |
| 一致性检查 | 病历与对话是否一致 | 诊断是否在对话中提及  |
| 逻辑性检查 | 医学逻辑是否合理  | 症状与诊断是否匹配   |
| 格式检查  | 输出格式是否正确  | JSON格式是否合法  |

### 4. 数据存储模块设计

#### 4.1 数据存储架构

```mermaid
graph TB
    A[原始音频] --> B[对象存储]
    C[转写文本] --> D[文档数据库]
    E[结构化病历] --> F[关系数据库]
    G[术语映射] --> H[图数据库]
    
    style A fill:#e1f5ff
    style C fill:#e1f5ff
    style E fill:#e1f5ff
    style G fill:#e1f5ff
    style B fill:#e8f5e9
    style D fill:#e8f5e9
    style F fill:#e8f5e9
    style H fill:#e8f5e9
```

**存储方案：**

| 数据类型  | 存储系统       | 原因        |
| ----- | ---------- | --------- |
| 原始音频  | MinIO/OSS  | 大文件、对象存储  |
| 转写文本  | MongoDB    | 半结构化、灵活查询 |
| 结构化病历 | PostgreSQL | 结构化、事务支持  |
| 术语映射  | Neo4j      | 图结构、关系查询  |

### 5. 性能优化设计

#### 5.1 ASR性能优化

```mermaid
graph LR
    A[音频输入] --> B{缓存检查}
    B -->|命中| C[返回缓存结果]
    B -->|未命中| D[执行ASR]
    D --> E[结果缓存]
    E --> F[返回结果]
    C --> G[输出]
    F --> G
    
    style A fill:#e1f5ff
    style G fill:#e8f5e9
    style B fill:#fff3e0
```

**优化策略：**

| 策略   | 方法        | 效果       |
| ---- | --------- | -------- |
| 模型缓存 | 预加载模型到内存  | 减少启动时间   |
| 结果缓存 | 缓存已识别音频结果 | 避免重复计算   |
| 批处理  | 批量处理多个音频段 | 提高GPU利用率 |
| 流式处理 | 实时处理音频流   | 降低延迟     |

#### 5.2 并发处理设计

```mermaid
graph TB
    A[请求队列] --> B[负载均衡]
    B --> C[Worker 1]
    B --> D[Worker 2]
    B --> E[Worker 3]
    C --> F[结果聚合]
    D --> F
    E --> F
    F --> G[响应输出]
    
    style A fill:#e1f5ff
    style G fill:#e8f5e9
    style B fill:#fff3e0
```

**并发配置：**

| 参数    | 值      | 说明      |
| ----- | ------ | ------- |
| 最大并发数 | CPU核心数 | 避免资源竞争  |
| 队列长度  | 100    | 限制排队请求  |
| 超时时间  | 30秒    | 避免长时间等待 |

### 6. 安全设计

#### 6.1 数据安全

```mermaid
graph LR
    A[原始数据] --> B[加密传输]
    B --> C[加密存储]
    C --> D[访问控制]
    D --> E[审计日志]
    
    style A fill:#e1f5ff
    style E fill:#e8f5e9
    style B fill:#fff3e0
    style C fill:#fff3e0
```

**安全措施：**

| 层面   | 措施        | 实现        |
| ---- | --------- | --------- |
| 传输安全 | HTTPS/TLS | 加密传输通道    |
| 存储安全 | AES-256   | 加密存储数据    |
| 访问安全 | RBAC      | 基于角色的访问控制 |
| 审计安全 | 日志记录      | 记录所有操作    |

### 7. 监控与日志设计

#### 7.1 监控指标

```mermaid
graph TB
    A[系统监控] --> B[性能指标]
    A --> C[业务指标]
    A --> D[错误指标]
    
    B --> B1[ASR延迟]
    B --> B2[系统吞吐量]
    B --> B3[资源使用率]
    
    C --> C1[识别准确率]
    C --> C2[病历生成成功率]
    C --> C3[用户满意度]
    
    D --> D1[错误率]
    D --> D2[异常类型]
    D --> D3[告警触发]
    
    style A fill:#e1f5ff
    style B fill:#fff3e0
    style C fill:#fff3e0
    style D fill:#fff3e0
```

**关键指标：**

| 指标类别 | 指标名称  | 阈值    | 告警级别     |
| ---- | ----- | ----- | -------- |
| 性能   | ASR延迟 | < 2s  | Warning  |
| 性能   | 系统可用性 | > 99% | Critical |
| 业务   | 识别准确率 | > 95% | Warning  |
| 错误   | 错误率   | < 1%  | Critical |

## 模块说明

### 输入层

| 模块 | 职责 | 技术方案 | 实现状态 |
|------|------|----------|----------|
| 音频上传模块 | 接收音频文件上传 | FastAPI + multipart | ✅ 已实现 |
| ASR模块 | 语音转文字 | FunASR (Paraformer) | ✅ 已实现 |
| 说话人分离 | 区分医生/患者 | FunASR CAM++ | ✅ 已实现 |

### 处理层

| 模块 | 职责 | 技术方案 | 实现状态 |
|------|------|----------|----------|
| ASR后处理 | 医疗术语纠错 | 规则匹配 | ✅ 已实现 |
| 文本规范化 | 标点、说话人映射 | 正则表达式 | ✅ 已实现 |
| 证据选择模块 | 从对话中检索相关片段 | 触发词匹配 + LLM | ✅ 已实现 |
| 术语规范化模块 | 口语化表述映射到专业术语 | LLM识别 + UMLS检索 + LLM候选选择 | ✅ 已实现 |
| 病历要素抽取模块 | 从证据中抽取SOAP要素 | 规则抽取 + LLM | ✅ 已实现 |
| 病历生成模块 | 基于抽取结果生成结构化病历 | 模板生成 + LLM | ✅ 已实现 |
| 验证模块 | 检查病历完整性和术语正确性 | 字典匹配 + UMLS | ✅ 已实现 |

### 输出层

| 模块 | 职责 | 格式 | 实现状态 |
|------|------|------|----------|
| 转写结果展示 | 显示转写文本和说话人 | HTML/JSON | ✅ 已实现 |
| 结构化病历 | 最终输出的结构化医疗文档 | SOAP格式 | ✅ 已实现 |

### 外部依赖

| 资源 | 用途 | 状态 |
|------|------|------|
| FunASR模型 | ASR转写和说话人分离 | ✅ 已集成 |
| 医疗热词表 | 提升医疗术语识别率 | ✅ 已配置 |
| ASR纠正规则 | 医疗术语纠错 | ✅ 已配置 |
| 字段触发词表 | 证据选择触发词 | ✅ 已配置 |
| 医学术语词表 | 术语类型提示（仅用于LLM参考） | ✅ 已配置 |
| 医学本体库 (UMLS/SNOMED/ICD) | 术语规范化检索 | ✅ 已集成 |
| LLM API / 本地模型 | 结构化生成 | ✅ 已集成 |

## 后端服务架构

### API路由

| 路由 | 方法 | 功能 | 文件 |
|------|------|------|------|
| /api/upload | POST | 上传音频文件 | backend/api/upload.py |
| /api/asr/transcribe/{visit_id} | POST | 启动ASR转写任务 | backend/api/asr.py |
| /api/task/{task_id} | GET | 查询任务状态 | backend/api/task.py |
| /api/emr/process | POST | 处理就诊记录生成病历 | backend/api/emr.py |
| /api/emr/process-stream | POST | SSE实时推送病历生成进度（支持stop_after_draft/skip_cleaning/skip_hallucination_check参数） | backend/api/emr.py |
| /api/emr/status/{visit_id} | GET | 查询病历处理状态 | backend/api/emr.py |
| /api/emr/record/{visit_id} | GET | 获取病历记录 | backend/api/emr.py |
| /api/emr/record/{visit_id} | PUT | 更新病历记录 | backend/api/emr.py |
| /api/emr/record/{visit_id} | DELETE | 删除病历记录（全部或指定版本） | backend/api/emr.py |
| /api/emr/versions/{visit_id} | GET | 获取病历所有版本 | backend/api/emr.py |
| /api/emr/visits | GET | 列出所有有EMR记录的就诊 | backend/api/emr.py |
| /api/emr/postprocess | POST | 病历草稿后处理（术语规范化/核查修订） | backend/api/emr.py |
| /api/emr/finalize | POST | 病历草稿定稿保存（规范化+证据溯源+落盘） | backend/api/emr.py |
| /api/emr/structure | POST | 自由文本草稿结构化为SOAP JSON | backend/api/emr.py |
| / | GET | 首页（上传界面） | backend/main.py |
| /health | GET | 健康检查 | backend/main.py |

### 数据模型

| 模型 | 表名 | 说明 | 文件 |
|------|------|------|------|
| Visit | visits | 就诊记录 | backend/models/visit.py |
| Task | tasks | 任务记录 | backend/models/task.py |
| TranscriptTurn | transcript_turns | 转写轮次 | backend/models/transcript.py |
| ASRCorrection | asr_corrections | ASR纠正记录 | backend/models/transcript.py |
| EvidenceSpan | evidence_spans | 证据片段 | backend/models/evidence.py |
| NormalizedTerm | normalized_terms | 规范化术语 | backend/models/term.py |
| ExtractedItem | extracted_items | 抽取的病历要素 | backend/models/extracted_item.py |
| EMRRecord | emr_records | 病历记录 | backend/models/emr_record.py |
| AtomicFact | atomic_facts | 原子临床事实（阶段2输出，核心中间表示，含section_candidate粗分类和subsection细粒度字段分类） | backend/models/atomic_fact.py |
| LLMConfig | llm_configs | LLM配置（含JSON模式、思考模式） | backend/models/llm_config.py |

#### LLMConfig 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键，自增 |
| config_name | String(100) | 配置名称，唯一 |
| provider | String(50) | 服务商（openai_compatible/openai/anthropic/sense-deepseek/custom） |
| model_name | String(100) | 模型名称 |
| api_key | String(200) | API密钥 |
| api_endpoint | String(200) | API端点 |
| is_active | Boolean | 是否启用 |
| max_tokens | Integer | 最大Token数，默认2048 |
| temperature | String(10) | 温度参数，默认"0.7" |
| json_mode | Boolean | JSON输出模式，默认False |
| thinking_enabled | Boolean | 思考模式开关，默认False |
| thinking_effort | String(10) | 思考强度（high/low），默认"high" |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

#### EMRRecord 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| record_id | Integer | 主键，自增 |
| visit_id | String | 外键，关联就诊记录 |
| version | Integer | 版本号，默认1 |
| record_type | String | 记录类型，默认"system_draft" |
| emr_json | JSON | 病历结构化JSON内容 |
| evidence_mapping | JSON | 证据映射，可为空 |
| validation_errors | JSON | 验证错误，可为空 |
| created_at | DateTime | 创建时间 |
| draft_text | Text | 病历草稿纯文本，可为空 |

#### TranscriptTurn 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| turn_id | Integer | 主键，自增 |
| visit_id | String | 外键，关联就诊记录 |
| turn_index | Integer | 轮次索引 |
| speaker | String | 说话人ID（spk0, spk1等） |
| text | String | 转写文本 |
| original_text | String | 原始文本（纠错前） |
| corrected_text | String | 纠正后文本 |
| start_ms | Integer | 开始时间戳（毫秒） |
| end_ms | Integer | 结束时间戳（毫秒） |
| confidence | Float | ASR置信度（0.0-1.0），默认1.0 |
| created_at | DateTime | 创建时间 |

### 服务层

| 服务 | 功能 | 文件 |
|------|------|------|
| ASRService | 封装FunASR引擎，支持说话人分离和角色识别 | backend/services/asr_service.py |
| ASRPostprocessor | ASR后处理，医疗术语纠错 | backend/services/postprocessor.py |
| TranscriptNormalizer | 文本标准化，说话人映射 | backend/services/normalizer.py |
| SpeakerRoleClassifier | 说话人角色识别，基于语义分析识别医生/患者 | backend/services/speaker_role_classifier.py |
| EvidenceService | 证据选择，基于触发词、置信度和LLM筛选相关片段 | backend/services/evidence_service.py |
| TerminologyService | 术语规范化，分级触发链路(预检→拆解→分流检索→Rewrite→约束选择→unresolved)，中英文路径互斥(中文走本地术语库含ICD-11+口语同义词映射/英文走UMLS)，支持并行处理；新增两步规范化方法(normalize_draft_terms: 正则提取→LLM批量规范化→术语库检索) | backend/services/terminology_service.py |
| TermRewriter | 术语改写服务，口语→临床改写、多概念拆解、alternative phrasing生成 | backend/services/term_rewriter.py |
| TranslationService | 中英文翻译，使用专门翻译小模型提升翻译速度 | backend/services/translation_service.py |
| FactService | 原子事实CRUD服务，封装AtomicFact的增删改查操作 | backend/services/fact_service.py |
| ExtractionService | 病历要素抽取，从证据中抽取SOAP要素 | backend/services/extraction_service.py |
| EMRGenerationService | 病历生成，基于模板和LLM生成结构化病历 | backend/services/emr_generation_service.py |
| MedicalRecordPipeline | 整合服务，串联所有处理步骤，支持并行处理 | backend/services/medical_record_pipeline.py |
| LLMPipelineService | **向后兼容包装类**（38行），全部逻辑委托给 PipelineOrchestrator。阶段1:转写清洗与角色纠错，阶段2:直接草稿生成，阶段3:草稿结构化(free_text模式)，阶段4:幻觉检查，阶段5:后置核查，阶段6:字段级修订与落盘 | backend/services/llm_pipeline_service.py |
| PipelineOrchestrator | 核心编排器，串联 6 个 PipelineStage + 术语规范化后处理（TurnCleaningStage → DirectSOAPGenerationStage → SoapStructuringStage[free_text模式] → _normalize_terms_in_draft → HallucinationCheckStage → ClaimVerificationStage → FieldRevisionStage）；HallucinationCheckStage 在草稿结构化后使用 consistency_check 模板核查全SOAP各字段与对话的一致性，标记无依据的虚假内容；process_transcript/process_with_callback 支持 skip_cleaning/skip_hallucination_check/stop_after_draft/skip_verification 参数控制各阶段执行与跳过；free_text模式下推送 draft_text_ready 事件（含draft_text字段），结构化完成后推送 draft_ready 事件（含emr_draft字段）；_format_turns 方法用于 skip_cleaning=True 时直接构建 combined_text；_compute_changes 方法对比 before/after EMR 字段值差异生成变更记录（term_replacement/unsupported_claim_removed/missing_item_added/downgrade/revision） | backend/services/pipeline/orchestrator.py |
| LLMPipelineServiceEnglish | 英文多阶段LLM处理，跳过翻译步骤优化 | backend/services/llm_pipeline_service_en.py |
| LLMService | LLM服务，支持多适配器、模板渲染、JSON模式和思考模式 | backend/services/llm/llm_service.py |
| PromptManager | Prompt模板管理器，支持中英文模板，按需渲染（Template.safe_substitute） | backend/services/llm/prompts.py |

### prompts.py 模板清单

`_load_chinese_templates()` 注册的中文模板：

| 模板名 | required_vars | 用途 |
|--------|--------------|------|
| `evidence_selection` | `["transcript"]` | 从对话中识别病历相关证据片段 |
| `item_extraction` | `["normalized_text"]` | 从规范化文本抽取SOAP病历要素 |
| `emr_generation` | `["extracted_data", "template_requirements"]` | 基于结构化数据生成病历文本 |
| `emr_generation_with_role` | `["extracted_data", "transcript", "template_requirements"]` | 含角色识别的病历生成 |
| `turn_cleaning` | `["transcript"]` | 对话轮次角色纠错和ASR修正 |
| `direct_soap_generation` | `["transcript"]` | 四阶段：单次LLM调用直接生成完整SOAP（含source_turn_indices） |
| `free_soap_generation` | `["transcript"]` | 自由文本SOAP草稿生成（按SOAP四段自由叙述，不分字段） |
| `soap_structuring` | `["draft_text", "transcript"]` | 将自由文本SOAP草稿结构化为标准JSON格式（含source_turn_indices） |
| `claim_verification` | `["transcript", "draft_emr"]` | 四阶段：A/P逐claim原子核查（supported/unsupported/not_addressed） |
| `checklist_verification` | `["transcript", "draft_emr"]` | 四阶段：检查SOAP关键信息遗漏 |
| `certainty_verification` | `["transcript", "assessment_json"]` | 四阶段：检查诊断确定性层级是否被拔高 |
| `field_revision` | `["draft_emr", "issues_json", "transcript"]` | 四阶段：定点修订SOAP草稿（仅改失败字段） |
| `term_standardization` | `["terms"]` | 两步术语规范化第一步：LLM将口语术语批量规范为医学标准用语（中英文） |
| `fact_extraction` | `["new_turns_json", "existing_facts_summary"]` | **DEPRECATED**：增量抽取原子临床事实 |
| `fact_consolidation` | `["facts_json"]` | **DEPRECATED**：重复事实合并+冲突标记 |
| `soap_verification` | `["draft_emr", "fact_table", "role_mapping"]` | **DEPRECATED**：SOAP草稿核查（4类问题×最多1个） |
| `emr_generation_so` | `["facts_json", "dialogue_summary"]` | **DEPRECATED**：分节生成主观+客观数据 |
| `emr_generation_assessment` | `["subjective_text", "objective_text", "facts_json"]` | **DEPRECATED**：分节生成评估（三层诊断策略） |
| `emr_generation_plan` | `["subjective_text", "objective_text", "assessment_text", "facts_json"]` | **DEPRECATED**：分节生成计划（四子字段） |
| `emr_generation_ap` | `["subjective_text", "objective_text", "facts_json"]` | **DEPRECATED**：分节合并生成评估+计划 |

`_load_chinese_evaluation_templates()` 注册的质量评估模板：

| 模板名 | required_vars | 用途 |
|--------|--------------|------|
| `consistency_check` | `["transcript", "emr_content"]` | 病历-对话一致性检查 |
| `internal_consistency_check` | `["emr_content"]` | 病历内部自相矛盾检查 |
| `key_fact_extraction` | `["transcript"]` | 从对话提取关键事实清单 |
| `completeness_check` | `["key_facts", "emr_content"]` | 关键事实覆盖度评估 |
| `document_quality_check` | `["emr_content"]` | 文档质量五维评分 |
| `safety_risk_check` | `["transcript", "emr_content"]` | 安全风险检查（6类错误） |

### Pipeline 模块架构（SOLID 重构后）

#### 分层架构图

```mermaid
graph TB
    subgraph "外部 API 层"
        EMR_API[api/emr.py]
    end

    subgraph "兼容层"
        LSP[LLMPipelineService<br/>38行包装类]
    end

    subgraph "编排层"
        ORC[PipelineOrchestrator<br/>含术语规范化]
    end

    subgraph "阶段层 (PipelineStage)"
        TCS[TurnCleaningStage<br/>转写清洗与角色纠错]
        DSG[DirectSOAPGenerationStage<br/>端到端草稿生成<br/>free_text/json双模式]
        SSS[SoapStructuringStage<br/>草稿结构化<br/>free_text模式]
        HCS[HallucinationCheckStage<br/>幻觉检查]
        CVS[ClaimVerificationStage<br/>后置核查]
        FRS[FieldRevisionStage<br/>字段级修订与落盘]
    end

    subgraph "基础设施层"
        CTX[PipelineContext<br/>数据传递对象]
        UTIL[utils.py<br/>JSON解析]
        SPK[speaker_handler.py<br/>说话人角色处理]
        DBG[debug_interactor.py<br/>Debug交互]
        EVI[evidence_enricher.py<br/>证据溯源富化]
        EMR_P[emr_persistence.py<br/>EMR持久化]
        INT[interactive.py<br/>交互式分步处理]
    end

    EMR_API --> LSP
    LSP --> ORC
    ORC --> TCS
    TCS --> DSG
    DSG --> SSS
    SSS --> HCS
    HCS --> CVS
    CVS --> FRS
    ORC --> CTX
    ORC --> EMR_P
    ORC --> EVI
    ORC --> INT
    INT --> ORC
```

#### 阶段依赖关系

| 阶段 | Stage 类 | 输入 | 输出 | 核心文件 |
|------|----------|------|------|----------|
| 1 | TurnCleaningStage | turns (原始转写 TranscriptTurn[]) | cleaned_turns, role_mappings | [stages/turn_cleaning.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/stages/turn_cleaning.py) |
| 2 | DirectSOAPGenerationStage | combined_text (清洗后全文) | free_text模式: draft_text (自由文本草稿); json模式: emr_draft (完整SOAP草稿，含evidence_traces) | [stages/direct_soap_generation.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/stages/direct_soap_generation.py) |
| 3 | SoapStructuringStage (free_text模式) | draft_text + combined_text | emr_draft (SOAP JSON，含evidence_traces) | [stages/soap_structuring.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/stages/soap_structuring.py) |
| 3.5 | _normalize_terms_in_draft (后处理) | emr_draft | emr_draft (术语规范化后，中文路径: colloquial_synonyms预处理+normalize_draft_terms; 英文路径: normalize_draft_terms) | [orchestrator.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/orchestrator.py) |
| 4 | HallucinationCheckStage | emr_draft + combined_text | hallucination_result (一致性核查结果) | [stages/hallucination_check.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/stages/hallucination_check.py) |
| 5 | ClaimVerificationStage | emr_draft + combined_text | verification_issues (Claim/Checklist/硬规则/确定性) | [stages/claim_verification.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/stages/claim_verification.py) |
| 6 | FieldRevisionStage | emr_draft + verification_issues | emr_draft (修订后，覆盖原草稿) | [stages/field_revision.py](file:///d:/practice/MedicalAssisstant/backend/services/pipeline/stages/field_revision.py) |

#### PipelineStage 接口

所有阶段实现统一的 `PipelineStage` 抽象接口：

```python
class PipelineStage(ABC):
    @abstractmethod
    def stage_name(self) -> str: ...

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> Dict[str, Any]: ...
```

**PipelineContext** 作为各阶段间的数据传递对象，避免阶段间直接耦合：

| 字段 | 类型 | 说明 |
|------|------|------|
| db | Session | 数据库会话 |
| llm_service | LLMService | LLM 服务实例 |
| prompt_manager | PromptManager | Prompt 模板管理器 |
| language | str | 语言设置 (zh/en) |
| debug_mode | bool | 调试模式开关 |
| visit_id | str | 就诊 ID |
| turns | List[TranscriptTurn] | 原始转写轮次 |
| save_evidence | bool | 是否保存证据溯源 |
| all_role_mappings | Dict | 角色映射结果（阶段1输出） |
| all_cleaned_turns | List[Dict] | 清洗后轮次（阶段1输出） |
| combined_text | str | 合并清洗文本（阶段1输出） |
| terminology_service | TerminologyService | 术语规范化服务（阶段2.5后处理使用，内部根据language自动分流中文/英文路径） |
| emr_draft | Dict | SOAP 草稿（阶段2输出，阶段2.5术语规范化，阶段4修订后覆盖） |
| draft_text | str | 自由文本SOAP草稿（free_text模式下阶段2输出） |
| emr_final | Dict | 最终SOAP病历（阶段4输出，经normalize_format后落盘） |
| verification_issues | Dict | 后置核查问题清单（阶段3输出，含unsupported_claims/not_addressed_claims/missing_items/hard_rule_violations） |
| skip_cleaning | bool | 跳过阶段1: 转写清洗与角色纠错（默认False） |
| skip_hallucination_check | bool | 跳过阶段2.5: 幻觉检查（默认False） |
| stop_after_draft | bool | 草稿生成后停止（默认True） |
| skip_verification | bool | 术语规范化后停止，跳过阶段5+6（默认False） |

#### 关键设计决策

- **PipelineStage 模式**：`execute(ctx) -> Dict` 统一入口，4 个阶段可独立测试和替换，符合开闭原则（新增阶段无需修改编排器）
- **PipelineContext**：作为各阶段间的数据传递对象，阶段间通过 Context 读写数据而非直接引用，避免阶段间直接耦合
- **可选流程控制**：通过 `skip_cleaning`、`skip_hallucination_check`、`stop_after_draft`、`skip_verification` 参数控制各阶段执行与跳过，跳过的阶段返回值为 `None`
- **术语规范化**：阶段2完成后、阶段3开始前，对 SOAP 草稿进行术语规范化（`_normalize_terms_in_draft()`）。中文路径：先使用 colloquial_synonyms.json 做快速替换，再调用 `normalize_draft_terms()`（LLM批量规范化+术语库检索）；英文路径：直接调用 `normalize_draft_terms()`。中英文均生效
- **Orchestrator 单一职责**：`PipelineOrchestrator` 只负责流程编排和资源初始化，不包含领域逻辑（领域逻辑在 Stage 类中）
- **向后兼容包装**：`LLMPipelineService` 保留为包装类，所有公共方法委托给 `PipelineOrchestrator`，确保 `api/emr.py` 和外部调用方零修改
- **依赖注入**：`InteractivePipelineService` 依赖从 `LLMPipelineService` 改为 `PipelineOrchestrator`，支持独立测试

### 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| APP_NAME | 中文门诊病历生成系统 | 应用名称 |
| DATABASE_URL | sqlite:///data/database/medical.db | 数据库连接 |
| ASR_ENGINE | funasr | ASR引擎类型 |
| ASR_DEVICE | cpu | 计算设备 |
| ENABLE_DIARIZATION | true | 启用说话人分离 |
| ENABLE_ROLE_CORRECTION | true | 启用说话人角色识别修正 |
| ENABLE_ASR_CORRECTION | true | 启用ASR纠错 |
| HOTWORD_PATH | config/hotwords_medical.txt | 热词表路径 |
| LLM_DEBUG_MODE | false | LLM调试模式开关 |
| LLM_SEGMENT_TURNS | 10 | LLM分段轮次数 |
| TRANSLATION_ENABLED | true | 启用翻译服务 |
| TRANSLATION_MODEL | Helsinki-NLP/opus-mt-zh-en | 翻译模型名称 |
| TRANSLATION_DEVICE | cpu | 翻译模型运行设备 |
| UMLS_MAX_CONCURRENT | 5 | UMLS API最大并发请求数 |
| TERMINOLOGY_PARALLEL_ENABLED | true | 启用术语规范化并行模式 |
| DRAFT_GENERATION_MODE | free_text | 草稿生成模式（free_text: 自由文本草稿+结构化两步模式） |

## 依赖关系

### 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | ^0.104.0 | Web框架 |
| uvicorn | ^0.24.0 | ASGI服务器 |
| sqlalchemy | ^2.0.0 | ORM框架 |
| funasr | ^1.0.0 | ASR引擎 |
| torch | ^2.0.0 | 深度学习框架 |
| transformers | ^4.35.0 | 翻译模型 |
| openai | ^1.3.0 | LLM API |
| requests | ^2.31.0 | HTTP客户端 |
| pydantic | ^2.5.0 | 数据验证 |
| asyncio | 内置 | 异步编程 |
| concurrent.futures | 内置 | 线程池执行 |

### 性能优化依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| asyncio | 内置 | 异步编程，并行处理 |
| ThreadPoolExecutor | 内置 | 线程池，解决事件循环嵌套问题 |

## 性能优化

### 并行处理架构

病历生成流程支持并行处理，主要优化点：

1. **步骤级并行**：证据选择和术语规范化并行执行
2. **批量处理**：批量翻译、批量UMLS检索、批量LLM选择
3. **并行Code获取**：使用asyncio.gather并行获取所有术语的code
4. **术语去重**：避免重复处理相同术语
5. **条件性跳过**：无数据时跳过相关步骤
6. **英文优化**：跳过翻译步骤，直接使用英文术语

### 性能对比

| 服务 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 中文服务 | 串行处理 | 并行处理 | 减少30-50% |
| 英文服务 | 串行处理 | 并行处理（跳过翻译） | 减少40-60% |

### 并行处理流程图

```mermaid
graph TB
    A[对话文本] --> B[证据选择]
    A --> C[术语规范化]
    B --> D[要素抽取]
    C --> D
    D --> E[病历生成]
    
    style B fill:#fff3e0
    style C fill:#fff3e0
    style D fill:#e8f5e9
    style E fill:#e8f5e9
```

### 异步执行解决方案

在FastAPI环境中，使用`run_async`辅助函数处理异步代码：

```python
def run_async(coro):
    """
    在同步上下文中运行异步协程
    
    解决问题：在FastAPI的事件循环中不能使用asyncio.run()
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)
```

## 前端界面

### 页面结构

| 页面 | 文件 | 功能 |
|------|------|------|
| 上传页面 | frontend/index.html | 音频上传、表单填写、进度显示 |
| 结果页面 | frontend/result.html | 转写结果展示、状态刷新、说话人区分 |
| **IDE主页面** | **frontend/emr.html** | **VS Code风格IDE界面，集成Agent助手、病历编辑器、调试模式、配置管理** |
| 评估页面 | frontend/evaluation.html | 病历质量评估、评估调试模式 |
| 配置页面 | frontend/config.html | LLM配置管理（保留独立入口） |

### IDE 布局架构（VS Code 风格）

```
┌──────────────────────────────────────────────────────────────┐
│  标题栏：应用名称 | 就诊ID | 病历状态 | 打印/评估按钮        │
├──────┬───────────────────────┬───────────────────────────────┤
│ 活   │                       │  Agent 侧边栏 / 调试面板      │
│ 动   │   SOAP 病历主区域      │  / 配置面板                  │
│ 栏   │   (S/O/A/P 折叠面板)   │  (根据活动栏选择切换)        │
│      │                       │                               │
├──────┴───────────────────────┴───────────────────────────────┤
│  状态栏：版本 | 语言 | 说话人轮次 | 操作状态                 │
└──────────────────────────────────────────────────────────────┘
```

**活动栏图标**：

- 📋 病历编辑器（默认）- 聚焦主编辑区
- 💬 Agent 助手 - 侧边栏显示Agent对话式交互
- 🔧 调试模式 - 侧边栏显示LLM多阶段调试面板
- ⚙️ 大模型配置 - 侧边栏显示LLM配置管理

### 样式与脚本

| 文件 | 功能 |
|------|------|
| frontend/css/style.css | 全局样式、响应式布局（保留原有页面样式） |
| frontend/css/ide.css | IDE布局专用样式（VS Code暗色主题） |
| frontend/js/app.js | IDE主控制器（状态管理、活动栏切换、事件总线） |
| frontend/js/agent.js | Agent侧边栏（消息展示、音频上传、ASR流程、流程模式选择组件、病历生成流程、后处理阶段选择面板、定稿保存、draft_text_ready事件处理、草稿结构化按钮处理） |
| frontend/js/editor.js | 病历编辑器（SOAP展示/编辑、版本管理、证据溯源、打印、变更视图渲染、草稿预览面板displayDraftText/switchEditorTab/getDraftTextFromPanel） |
| frontend/js/debug.js | 调试侧边栏（阶段选择、提示词展示、手动输入、提交/跳过） |
| frontend/js/config-sidebar.js | 配置侧边栏（LLM配置表单、配置列表管理） |
| frontend/js/upload.js | 上传页面逻辑、拖拽处理、进度更新 |
| frontend/js/result.js | 结果页面逻辑、状态轮询、说话人渲染 |

### 用户流程

**传统流程（保留）**：

1. 访问首页 → 拖拽或选择音频文件
2. 填写患者信息（可选）→ 点击上传
3. 自动跳转结果页 → 点击开始转写
4. 转写完成 → 点击生成病历 → 跳转IDE界面

**IDE界面流程**：

1. 在IDE界面Agent面板中直接拖拽上传音频（或从结果页跳转）
2. Agent面板显示上传成功，自动开始语音转写
3. 转写完成后Agent面板显示轮次统计
4. 选择流程模式（快速草稿/标准流程/完整流程）→ 点击「生成病历」
5. Agent面板逐步显示LLM处理阶段
6. 所有阶段完成后，SOAP病历自动在主编辑区展示
7. 可在编辑区进行查看、折叠、编辑、版本切换、证据溯源、打印
8. 可切换到调试面板进行逐阶段手动调试
9. 可切换到配置面板管理LLM配置

### PipelineModeSelector 组件

流程模式选择组件位于 Agent 侧边栏上传区域下方，支持用户在生成病历前选择处理流程。

**组件结构**：

```
┌─────────────────────────────────────┐
│ 生成模式选择                          │
├─────────────────────────────────────┤
│ ○ 快速草稿（推荐）                    │
│   仅生成草稿，最快速度                 │
│                                     │
│ ○ 标准流程                           │
│   转写清洗 + 草稿生成                 │
│                                     │
│ ○ 完整流程                           │
│   全流程：清洗→草稿→核查→修订          │
│                                     │
│ □ 启用幻觉检查                        │
│ □ 启用后置核查                        │
└─────────────────────────────────────┘
```

**参数映射**：

| 模式 | skip_cleaning | skip_hallucination_check | stop_after_draft | skip_verification |
|------|---------------|--------------------------|------------------|-------------------|
| 快速草稿 | true | true | true | false |
| 简化流程 | true | true | false | true |
| 标准流程 | false | true | false | false |
| 完整流程 | false | false | false | false |

**复选框覆盖规则**：

- 启用幻觉检查：`skip_hallucination_check = false`
- 启用后置核查：`stop_after_draft = false`

**核心函数**：

| 函数 | 功能 |
|------|------|
| `renderPipelineModeSelector()` | 渲染组件HTML |
| `initPipelineModeSelectorEvents()` | 绑定事件 |
| `setPipelineMode(mode)` | 设置模式 |
| `getPipelineParams()` | 计算API参数 |

## 数据流程

### 标准流程

```mermaid
graph LR
    A[音频输入] --> B[ASR转写]
    B --> C[说话人分离]
    C --> D[阶段1: 转写清洗与角色纠错]
    D --> E[阶段2: 直接草稿生成<br/>free_text/json双模式]
    E --> F[阶段3: 草稿结构化<br/>free_text模式: 自由文本→SOAP JSON]
    F --> G[阶段4: 幻觉检查<br/>一致性核查]
    G --> H[阶段5: 后置核查<br/>Claim核查+Checklist核查+硬规则核查]
    H --> I[阶段6: 字段级修订与落盘<br/>定点修订+schema约束校验]
    I --> J[病历输出]
    style D fill:#e1f5ff
    style E fill:#fff3e0
    style F fill:#e8f5e9
    style G fill:#fce4ec
    style H fill:#fff3e0
    style I fill:#e8f5e9
    style J fill:#e8f5e9
```

### 并行处理流程

```mermaid
graph TB
    A[对话文本] --> B[证据选择]
    A --> C[术语规范化]
    B --> D[要素抽取]
    C --> D
    D --> E[病历生成]
    
    style B fill:#fff3e0
    style C fill:#fff3e0
    style D fill:#e8f5e9
    style E fill:#e8f5e9
```

**并行处理说明**：

1. **证据选择和术语规范化并行执行**：两个步骤无数据依赖，可同时进行
2. **术语规范化内部并行**：
   - 批量翻译（中文服务）
   - 并行UMLS检索
   - 批量LLM选择
   - 并行获取Code
3. **条件性跳过**：
   - 无对话轮次时跳过证据选择和术语规范化
   - 无证据时跳过要素抽取
   - 无术语时跳过术语规范化

### 英文服务流程

英文病历生成服务跳过翻译步骤：

```mermaid
graph LR
    A[英文对话] --> B[证据选择]
    A --> C[术语规范化<br/>跳过翻译]
    B --> D[要素抽取]
    C --> D
    D --> E[病历生成]
```

## ASR 模块架构

### 设计原则

- **单一职责**：每个引擎类只负责一种 ASR 模型
- **开闭原则**：通过继承 `ASRBase` 扩展新引擎，无需修改现有代码
- **依赖倒置**：上层代码依赖抽象接口 `ASRBase`，而非具体实现

### 类图

```
┌─────────────────────────────────────────────────────────────┐
│                        ASRBase (抽象类)                      │
├─────────────────────────────────────────────────────────────┤
│ + model_name: str                                           │
│ + device: str                                               │
│ + load_model() -> None                                      │
│ + transcribe(audio_path) -> ASRResult                       │
│ + is_loaded() -> bool                                       │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ 继承
              ┌───────────────┴───────────────┐
              │                               │
┌─────────────────────────┐     ┌─────────────────────────┐
│     FunASREngine        │     │      MedASREngine       │
├─────────────────────────┤     ├─────────────────────────┤
│ - model_id: str         │     │ - model_id: str         │
│ - vad_model: str        │     │ - _processor            │
│ - punc_model: str       │     │ - _model                │
│ - hotword_path: str     │     │                         │
├─────────────────────────┤     ├─────────────────────────┤
│ + load_model()          │     │ + load_model()          │
│ + transcribe()          │     │ + transcribe()          │
│ + create_medical_version│     │ + transcribe_with_warning│
└─────────────────────────┘     └─────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      ASRFactory (工厂类)                    │
├─────────────────────────────────────────────────────────────┤
│ - _registry: dict[str, type[ASRBase]]                       │
├─────────────────────────────────────────────────────────────┤
│ + create(engine_type) -> ASRBase                            │
│ + create_all() -> dict[str, ASRBase]                        │
│ + register(name, engine_class) -> None                      │
│ + list_available() -> list[str]                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      ASRResult (数据类)                     │
├─────────────────────────────────────────────────────────────┤
│ + text: str                                                 │
│ + language: str                                             │
│ + duration_seconds: float                                   │
│ + inference_time: float                                     │
│ + model_name: str                                           │
│ + real_time_factor: float (计算属性)                         │
└─────────────────────────────────────────────────────────────┘
```

### 模块依赖关系

```
compare_asr.py (脚本层)
       │
       ▼
   factory.py (工厂层)
       │
       ├──────────┬──────────┐
       ▼          ▼          │
funasr_engine  medasr_engine │
       │          │          │
       └──────────┴──────────┘
                  │
                  ▼
             base.py (抽象层)
```

## 量化评估模块架构

### 模块概述

量化评估模块用于对EMR生成管线进行多配置对比评估，支持中间结果持久化与跨运行复用。

### 数据模型

**BenchmarkRun（实验运行记录）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `sample_id` | String | 样本ID |
| `config_key` | String | 配置键（end_to_end/full/standard等） |
| `visit_id` | String | 就诊ID |
| `status` | String | 运行状态（running/completed/failed） |
| `emr_raw_draft` | JSON | 阶段2后的原始草稿（中间结果） |
| `emr_pre_revision` | JSON | 阶段5前的修订前EMR（中间结果） |
| `emr_result` | JSON | 最终EMR结果 |
| `hallucination_result` | JSON | 幻觉检查结果 |
| `verification_issues` | JSON | 后置核查问题 |
| `key_facts` | JSON | 关键事实提取结果（中间结果） |
| `elapsed_seconds` | Float | 运行耗时 |
| `llm_call_count` | Integer | LLM调用次数 |
| `error_message` | Text | 错误信息 |

**中间结果持久化机制**：

```
中间结果保存时机：
├── emr_raw_draft → process_with_fork完成后立即保存
├── emr_pre_revision → process_with_fork完成后立即保存
├── emr_result → process_with_fork完成后立即保存
├── hallucination_result → process_with_fork完成后立即保存
├── verification_issues → process_with_fork完成后立即保存
└── key_facts → key_facts提取完成后立即保存
```

### 中间结果复用流程

```mermaid
graph TB
    A[样本处理开始] --> B{检查数据库}
    B -->|已有中间结果| C[读取中间结果]
    B -->|无中间结果| D[运行process_with_fork]
    D --> E[保存中间结果到数据库]
    E --> F{检查状态}
    F -->|失败| G[保存已有结果并停止]
    F -->|成功| H[继续评估]
    C --> H
    H --> I{检查key_facts}
    I -->|已有| J[复用key_facts]
    I -->|无| K[提取key_facts]
    K --> L[保存key_facts到数据库]
    J --> M[运行8个配置评估]
    L --> M
    
    style A fill:#e1f5ff
    style G fill:#ffebee
    style M fill:#e8f5e9
```

### 空内容检查逻辑

空内容EMR不保存到数据库，避免无效数据污染：

```python
def _is_emr_empty(emr: Optional[Dict]) -> bool:
    # 检查所有SOAP section是否有非空内容
    for section in ["subjective", "objective", "assessment", "plan"]:
        sec = emr.get(section, {})
        if isinstance(sec, dict) and len(sec) > 0:
            # 检查text字段或value字段是否有内容
            if "text" in sec and str(sec.get("text", "")).strip():
                return False
            for field, val in sec.items():
                if isinstance(val, dict) and str(val.get("value", "")).strip():
                    return False
    return True  # 所有section都为空，不保存
```

**保留 `_is_emr_empty()` 的原因**：

虽然管线现在正确处理空内容（失败时返回 `failed` 状态），但 `_is_emr_empty()` 方法仍需保留：

1. **复用旧数据时检查**：数据库中可能存在旧数据（修复前保存的空内容）
2. **防止无效数据污染**：确保只复用有效的中间结果

### 失败状态传播机制

管线失败时正确传播状态，停止后续阶段：

```mermaid
graph TB
    A[阶段2: 草稿生成] --> B{检查状态}
    B -->|failed| C[返回 failed, 停止管线]
    B -->|completed| D[阶段3: 草稿结构化]
    D --> E{检查状态}
    E -->|failed| C
    E -->|completed| F[阶段4-6: 幻觉检查/核查/修订]
    F --> G{检查状态}
    G -->|failed| C
    G -->|completed| H[返回 completed]
    
    style C fill:#ffebee
    style H fill:#e8f5e9
```

**量化评估脚本处理**：

```python
if fork_status != "completed":
    logger.error(f"process_with_fork失败: {fork_result.get('error')}")
    print(f"FAIL (fork failed, 不保存到数据库)", flush=True)
    benchmark_db.close()
    db.close()
    raise RuntimeError(f"process_with_fork failed for sample {sample_id}")
```

**失败处理规则**：

- 管线失败 → 返回 `{"status": "failed"}` → 停止管线
- 量化评估脚本 → 抛出 `RuntimeError` → 停止该样本评估
- 失败样本不保存到数据库

### 文件依赖关系

```
backend/models/benchmark.py
├── BenchmarkRun（实验运行记录，含中间结果字段）
├── BenchmarkStage（阶段记录）
├── BenchmarkEvaluation（评估记录）
├── BenchmarkLLMCall（LLM调用记录）
└── BenchmarkSummary（汇总记录）

scripts/run_full_benchmark.py
├── _is_emr_empty() → 空内容检查
├── _check_intermediate_results() → 从数据库读取中间结果
├── _save_benchmark_run() → 保存中间结果到数据库
├── _build_jsonl_entry() → 构建JSONL输出
└── run_multi_variant() → 多配置评估主流程
    ├── 检查数据库中是否有中间结果
    ├── 复用已有中间结果，跳过process_with_fork
    ├── 运行process_with_fork后立即保存中间结果
    ├── 失败时也保存已有的中间结果
    └── key_facts提取后保存到数据库
```

### 复用效果

- **减少LLM调用**：已有中间结果的样本直接复用，不重新调用LLM
- **提高容错性**：阶段失败时，已生成的中间结果仍可被其他配置使用
- **支持恢复**：重新运行实验时，可从数据库读取已有结果，跳过已完成的阶段

## 使用方式

### 基础用法

```python
from src.asr import ASRFactory

# 创建单个引擎
engine = ASRFactory.create("funasr", device="cpu")
engine.load_model()
result = engine.transcribe("audio.wav")
print(result.text)
```

### 对比测试

```bash
# 测试所有引擎
python scripts/compare_asr.py --audio test.wav --device cpu

# 只测试 FunASR
python scripts/compare_asr.py --audio test.wav --engine funasr

# 使用医疗热词
python scripts/compare_asr.py --audio test.wav --hotword config/hotwords_medical.txt
```

### 扩展新引擎

```python
from src.asr import ASRBase, ASRResult, ASRFactory

class WhisperEngine(ASRBase):
    def __init__(self, device="cpu"):
        super().__init__("Whisper", device)
    
    def load_model(self):
        # 加载模型逻辑
        pass
    
    def transcribe(self, audio_path, **kwargs) -> ASRResult:
        # 转写逻辑
        pass

# 注册到工厂
ASRFactory.register("whisper", WhisperEngine)
```

