# 项目架构文档

## 系统架构图

![系统架构图](system-architecture.svg)

### 系统架构说明

系统采用分层架构设计，分为三层：

**输入层 (Input Layer)**：

- **ASR模块**：负责将语音信号转换为文本，支持实时转写和批量处理
- **原始文本**：作为事实来源，保存完整的对话内容

**处理层 (Processing Layer)**：

- **证据选择模块**：从对话文本中检索与病历生成相关的片段
- **术语规范化模块**：将口语化表达映射到标准医学术语，支持UMLS/SNOMED概念检索
- **结构化生成模块**：基于LLM生成符合SOAP格式的结构化病历
- **验证模块**：检查生成病历的内容一致性，确保与原始对话相符
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
5. **术语规范化**：将口语化术语映射为标准医学术语，查询医学本体库获取概念编码
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
│   │   └── upload.py          # 上传 API
│   ├── models/                # 数据模型
│   │   ├── __init__.py
│   │   ├── task.py            # 任务模型
│   │   ├── transcript.py      # 转写记录模型（含ASRCorrection）
│   │   └── visit.py           # 就诊记录模型
│   ├── services/              # 业务服务
│   │   ├── __init__.py
│   │   ├── asr_service.py     # ASR 服务（封装FunASR）
│   │   ├── normalizer.py      # 术语规范化服务
│   │   └── postprocessor.py   # 后处理服务（医疗术语纠错）
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
│   └── database/               # SQLite数据库文件
├── docs/                       # 文档
│   ├── architecture.md         # 架构文档 (本文件)
│   ├── completion_status.md    # 完成状态记录
│   ├── 技术选型文档.md          # ASR技术选型分析
│   ├── 说话人分离使用说明.md    # 说话人分离功能说明
│   └── specs/                  # 规格文档
│       └── 2026-04-12-m1-milestone-design.md
├── frontend/                   # 前端界面
│   ├── css/
│   │   └── style.css          # 样式文件
│   ├── js/
│   │   ├── result.js          # 结果页面脚本
│   │   └── upload.js          # 上传页面脚本
│   ├── index.html             # 上传页面
│   └── result.html            # 结果展示页面
├── output/                     # 输出目录
│   └── raw_asr_result.json    # ASR原始输出
├── scripts/                    # 脚本
│   ├── demo_diarization.py    # 说话人分离演示
│   ├── test_diarization.py    # 说话人分离测试
│   ├── test_diarization_debug.py # 调试脚本
│   ├── test_diarization_with_tts.py # TTS测试脚本
│   └── set_cache_path.bat     # 设置缓存路径脚本
├── src/                        # 核心源代码
│   ├── asr/                   # ASR 模块
│   │   ├── __init__.py        # 模块入口
│   │   ├── base.py            # 抽象基类（ASRResult数据类）
│   │   ├── factory.py         # 工厂模式
│   │   ├── funasr_engine.py   # FunASR 实现（支持说话人分离）
│   │   ├── medasr_engine.py   # MedASR 实现（仅英文）
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

- **FunASR-VAD**：基于FSMN的语音活动检测模型
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

```mermaid
graph TB
    A[口语化术语] --> B[术语识别]
    B --> C[本体库检索]
    C --> D{匹配结果}
    D -->|精确匹配| E[直接映射]
    D -->|模糊匹配| F[相似度排序]
    D -->|无匹配| G[保留原词]
    E --> H[标准术语]
    F --> H
    G --> H
    
    style A fill:#e1f5ff
    style H fill:#e8f5e9
    style C fill:#fff3e0
```

**本体库选择：**

| 本体库       | 覆盖范围  | 语言  | 访问方式  |
| --------- | ----- | --- | ----- |
| UMLS      | 全面    | 多语言 | 需申请许可 |
| SNOMED CT | 临床术语  | 多语言 | 需申请许可 |
| ICD-10    | 诊断编码  | 多语言 | 公开可用  |
| MeSH      | 医学主题词 | 英文  | 公开可用  |

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
| 证据选择模块 | 从对话中检索相关片段 | 向量检索 / BM25 | 📋 待实现 |
| 术语规范化模块 | 口语化表述映射到专业术语 | UMLS/SNOMED 概念检索 | 📋 待实现 |
| 结构化生成模块 | 基于证据生成结构化病历 | LLM | 📋 待实现 |
| 验证模块 | 检查病历与对话一致性 | 规则检查 / LLM 验证 | 📋 待实现 |

### 输出层

| 模块 | 职责 | 格式 | 实现状态 |
|------|------|------|----------|
| 转写结果展示 | 显示转写文本和说话人 | HTML/JSON | ✅ 已实现 |
| 结构化病历 | 最终输出的结构化医疗文档 | SOAP格式 | 📋 待实现 |

### 外部依赖

| 资源 | 用途 | 状态 |
|------|------|------|
| FunASR模型 | ASR转写和说话人分离 | ✅ 已集成 |
| 医疗热词表 | 提升医疗术语识别率 | ✅ 已配置 |
| ASR纠正规则 | 医疗术语纠错 | ✅ 已配置 |
| 医学本体库 (UMLS/SNOMED/ICD) | 术语规范化检索 | 📋 待集成 |
| LLM API / 本地模型 | 结构化生成 | 📋 待集成 |

## 后端服务架构

### API路由

| 路由 | 方法 | 功能 | 文件 |
|------|------|------|------|
| /api/upload | POST | 上传音频文件 | backend/api/upload.py |
| /api/asr/transcribe/{visit_id} | POST | 启动ASR转写任务 | backend/api/asr.py |
| /api/task/{task_id} | GET | 查询任务状态 | backend/api/task.py |
| / | GET | 首页（上传界面） | backend/main.py |
| /health | GET | 健康检查 | backend/main.py |

### 数据模型

| 模型 | 表名 | 说明 | 文件 |
|------|------|------|------|
| Visit | visits | 就诊记录 | backend/models/visit.py |
| Task | tasks | 任务记录 | backend/models/task.py |
| TranscriptTurn | transcript_turns | 转写轮次 | backend/models/transcript.py |
| ASRCorrection | asr_corrections | ASR纠正记录 | backend/models/transcript.py |

### 服务层

| 服务 | 功能 | 文件 |
|------|------|------|
| ASRService | 封装FunASR引擎，支持说话人分离和角色识别 | backend/services/asr_service.py |
| ASRPostprocessor | ASR后处理，医疗术语纠错 | backend/services/postprocessor.py |
| TranscriptNormalizer | 文本标准化，说话人映射 | backend/services/normalizer.py |
| SpeakerRoleClassifier | 说话人角色识别，基于语义分析识别医生/患者 | backend/services/speaker_role_classifier.py |

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

## 前端界面

### 页面结构

| 页面 | 文件 | 功能 |
|------|------|------|
| 上传页面 | frontend/index.html | 音频上传、表单填写、进度显示 |
| 结果页面 | frontend/result.html | 转写结果展示、状态刷新、说话人区分 |

### 样式与脚本

| 文件 | 功能 |
|------|------|
| frontend/css/style.css | 全局样式、响应式布局 |
| frontend/js/upload.js | 上传逻辑、拖拽处理、进度更新 |
| frontend/js/result.js | 结果展示、状态轮询、说话人渲染 |

### 用户流程

1. 访问首页 → 拖拽或选择音频文件
2. 填写患者信息（可选）→ 点击上传
3. 自动跳转结果页 → 点击开始转写
4. 等待转写完成 → 查看说话人分离结果

## 数据流程

![数据流程图](data-flow.svg)

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

