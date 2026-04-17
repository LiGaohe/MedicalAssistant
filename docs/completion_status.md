# 完成状态记录

## 2026-04-15 ASR模块职责简化与角色识别移除

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 移除角色识别模块 | ✅ 完成 | ASR模块只负责语音转文本和说话人分离 |
| 基于timestamp的句子拆分 | ✅ 完成 | 根据时间戳比例拆分文本，自动添加标点 |
| 测试脚本更新 | ✅ 完成 | test_timestamp_split.py |

### 设计决策

**ASR模块职责边界**：
- ✅ 语音转文本
- ✅ 说话人分离（输出 spk0, spk1, ...）
- ✅ 基于时间戳的句子拆分
- ✅ 自动添加标点符号
- ❌ 角色识别（医生/患者）→ 交给后续大模型模块

**原因**：
1. 基于词表的语义识别维护成本高、规则复杂、准确率有限
2. 项目后续模块会引入大模型将文本转为结构化病历
3. 大模型更适合进行角色识别和语义理解

### 实现详情

1. **移除角色识别** (`backend/services/asr_service.py`)
   - 删除 `SpeakerRoleClassifier` 导入和调用
   - 删除 `enable_role_correction` 配置项
   - 删除 `_map_speaker` 和 `_map_speaker_id` 方法
   - `transcribe_with_diarization` 只输出原始说话人ID（spk0, spk1）

2. **基于timestamp的句子拆分** (`backend/services/postprocessor.py`)
   - 根据时间戳比例估算文本分割位置
   - 自动添加标点符号（句号、问号、逗号）
   - 不再依赖语义分析

3. **Normalizer 简化** (`backend/services/normalizer.py`)
   - 删除 `_normalize_speaker` 方法
   - 直接输出 `speaker_id` 字段，不进行角色映射
   - 添加文档说明角色识别由后续模块处理

4. **前端显示优化** (`frontend/js/result.js`, `frontend/css/style.css`)
   - 前端显示 `speaker_id`（spk0, spk1）而不是角色（医生/患者）
   - 添加 `.speaker-0`, `.speaker-1`, `.speaker-other` 样式类
   - 不同说话人用不同颜色区分

5. **后端 API 适配** (`backend/api/asr.py`)
   - 使用 `turn["speaker_id"]` 而不是 `turn["speaker"]`
   - 数据库存储原始 speaker_id

6. **输出格式**
   ```json
   {
     "turns": [
       {
         "turn_index": 0,
         "speaker_id": "spk0",
         "text": "你好，请问哪里不舒服？",
         "start_ms": 170,
         "end_ms": 2095
       },
       {
         "turn_index": 1,
         "speaker_id": "spk1",
         "text": "医生，我这几天一直头疼，",
         "start_ms": 3570,
         "end_ms": 5610
       }
     ],
     "duration": 48.115,
     "inference_time": 12.34
   }
   ```

### 后续工作

角色识别将由后续模块（大模型）处理，输入为 ASR 输出的 turns 列表。

## 2026-04-15 VAD参数优化与说话人分离改进

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| VAD参数支持 | ✅ 完成 | 添加`vad_kwargs`参数，支持VAD配置 |
| 说话人分离优化 | ✅ 完成 | 针对短暂停顿场景优化参数 |
| 测试脚本 | ✅ 完成 | test_optimized_diarization.py |

### 实现详情

1. **VAD参数支持** (`src/asr/funasr_engine.py`)
   - 新增`vad_kwargs`参数，支持VAD模型配置
   - 支持的关键参数：
     - `max_single_segment_time`: VAD最大单段语音时长（毫秒）
     - `vad_speech_threshold`: VAD语音检测阈值

2. **说话人分离优化**
   - 针对短暂停顿（0.3-0.5秒）场景优化
   - 默认配置：
     - `max_single_segment_time`: 3000ms（减小以检测短暂停顿）
     - `vad_speech_threshold`: 0.5（提高以减少噪声误触发）
     - `speaker_threshold`: 0.7（严格区分不同说话人）

3. **测试脚本** (`scripts/test_optimized_diarization.py`)
   - 测试优化后的配置
   - 支持测试不同阈值配置
   - 输出详细的调试信息

### 解决的问题

**问题描述**：
- "一百四十五九十五血压高会引起头疼吗？"没有被正确拆分为：
  - 医生："一百四十五九十五"
  - 患者："血压高会引起头疼吗？"

**原因分析**：
1. VAD将两个说话人的语音合并为一个句子（停顿太短）
2. 说话人聚类阈值可能不够严格

**解决方案**：
1. 减小`max_single_segment_time`（6000ms → 3000ms），让VAD更敏感地检测短暂停顿
2. 提高`vad_speech_threshold`（默认 → 0.5），减少噪声误触发
3. 保持`speaker_threshold`（0.7），严格区分不同说话人

### 使用方法

```python
from src.asr import FunASREngine

# 创建优化后的引擎
engine = FunASREngine.create_medical_version(
    enable_diarization=True,
    device="cpu",
    speaker_threshold=0.7,
    max_single_segment_time=3000,  # 减小以检测短暂停顿
    vad_speech_threshold=0.5,      # 提高以减少噪声误触发
)

# 加载模型并转写
engine.load_model()
result = engine.transcribe("audio.wav")

# 查看说话人分离结果
for segment in result.speaker_segments:
    print(f"{segment['speaker']}: {segment['text']}")
```

### 参数调优建议

1. **如果仍然合并**：
   - 进一步减小`max_single_segment_time`（如2000ms）
   - 提高`speaker_threshold`（如0.8）

2. **如果过度分割**：
   - 增大`max_single_segment_time`（如4000ms）
   - 降低`vad_speech_threshold`（如0.4）

3. **如果噪声干扰**：
   - 提高`vad_speech_threshold`（如0.6）

## 2026-04-15 句子拆分后处理逻辑优化

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 删除按比例估算文本片段 | ✅ 完成 | 移除`_split_text_by_ratio`方法，无理论依据 |
| 语义分割优化 | ✅ 完成 | 仅依赖语义边界分割，找不到分割点则保留原文本 |
| FunASR说话人分离参数支持 | ✅ 完成 | 支持`speaker_diarization_conf`配置 |
| 修复重复输出问题 | ✅ 完成 | 找不到语义分割点时不拆分，避免重复输出 |

### 实现详情

1. **删除按比例估算文本片段** (`backend/services/postprocessor.py`)
   - 移除`_split_text_by_ratio`方法
   - 移除`_estimate_text_segment`方法
   - 原因：FunASR不提供字级别的时间戳，按时间比例估算文本片段没有理论依据

2. **语义分割优化**
   - 仅在找到语义分割点时才分割文本
   - 找不到分割点时保留原始文本（时间戳仍然拆分）
   - 语义分割点：`"的时候"`, `"了"`, `"，"`, `"。"`, `"？"`, `"！"`

3. **FunASR说话人分离参数支持** (`src/asr/funasr_engine.py`)
   - 新增`speaker_diarization_config`参数
   - 支持`threshold`（聚类阈值）和`max_speakers`（最大说话人数）
   - `create_medical_version`方法支持配置这些参数

### 已知限制

1. **文本分割依赖语义分析**
   - 对于没有明显语义分割点的句子（如"一百四十五九十五血压高会引起头疼吗？"），无法准确分割文本
   - 时间戳仍然会拆分，但文本保持原样

2. **FunASR不提供字级别时间戳**
   - 这是FunASR的限制，无法精确知道每个字对应的时间
   - 后处理只能基于语义分析进行文本分割

### 关于声纹识别

FunASR的说话人分离**正是基于声纹识别**的：
- `spk_model="cam++"` 是声纹嵌入模型
- 工作原理：提取声纹特征 → 聚类分组 → 分配说话人标签

**可调参数**：
- `threshold`: 聚类阈值，默认0.5
  - 提高阈值（0.6-0.7）更严格，更容易区分不同说话人
  - 降低阈值（0.3-0.4）更宽松，可能合并相似说话人
- `max_speakers`: 最大说话人数量

## 2026-04-15 句子拆分后处理逻辑

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 句子拆分后处理模块 | ✅ 完成 | ASRPostprocessor，基于时间间隔拆分错误合并的句子 |
| 语义分割优化 | ✅ 完成 | 基于语义边界（"的时候"、"了"等）进行文本分割 |
| ASRService集成 | ✅ 完成 | 集成句子拆分逻辑，支持配置拆分阈值 |
| 测试脚本 | ✅ 完成 | test_sentence_split.py、test_role_after_split.py |

### 实现详情

1. **句子拆分后处理模块** (`backend/services/postprocessor.py`)
   - 检测句子内部的时间间隔（默认阈值800ms）
   - 根据语义边界分割文本（优先在"的时候"、"了"、"，"等位置分割）
   - 返回拆分后的sentence_info和拆分记录

2. **ASRService集成**
   - 新增 `enable_sentence_split` 配置项（默认启用）
   - 新增 `split_gap_threshold_ms` 配置项（默认800ms）
   - `transcribe_with_diarization` 方法集成句子拆分逻辑

3. **优化效果**
   - 成功拆分"特别是早上起来的时候头疼持续多长时间了"
     - "特别是早上起来的时候" → 患者
     - "头疼持续多长时间了" → 医生
   - SpeakerRoleClassifier正确识别拆分后句子的角色

### 关键改进

1. **时间间隔检测**
   - 分析timestamp数组，检测相邻时间戳之间的间隔
   - 间隔超过阈值时触发句子拆分

2. **语义分割优化**
   - 优先在语义边界分割（"的时候"、"了"、"，"等）
   - 避免在词语中间分割

3. **与角色识别协同**
   - 拆分后的句子重新进行角色识别
   - 正确识别不同说话人的句子

## 2026-04-15 说话人角色识别优化

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 说话人角色识别模块 | ✅ 完成 | SpeakerRoleClassifier，基于语义分析识别医生/患者角色 |
| ASRService集成 | ✅ 完成 | 集成角色识别模块，支持混合方案 |
| 测试脚本 | ✅ 完成 | test_speaker_role.py，验证角色识别效果 |

### 实现详情

1. **说话人角色识别模块** (`backend/services/speaker_role_classifier.py`)
   - 基于语义分析识别说话人角色
   - 支持医生问诊模式识别（"持续多长时间"、"有没有症状"等）
   - 支持患者询问模式识别（"我需要...吗"、"还需要注意什么"等）
   - 支持上下文推断（根据前一个说话人推断当前说话人）
   - 支持说话人映射修正（根据语义分析结果修正声学分离结果）

2. **ASRService集成**
   - 新增 `enable_role_correction` 配置项
   - `transcribe_with_diarization` 方法集成角色识别
   - 输出包含原始角色、修正角色、置信度、修正原因

3. **优化效果**
   - 修正率：4.2%（原始声学分离结果大部分正确）
   - 平均置信度：0.68
   - 正确识别混合片段（如"特别是早上起来的时候头疼持续多长时间了"）
   - 正确识别问诊语句（如"持续多长时间了"）
   - 正确识别患者询问（如"还需要注意什么吗"）
   - 正确识别医嘱（如"注意休息"、"少吃咸的食物"）

### 关键改进

1. **区分医生问诊和患者询问**
   - 医生问诊模式：询问症状、持续时间、病史等
   - 患者询问模式：询问用药、注意事项、严重程度等

2. **改进上下文推断**
   - 根据前一个说话人的角色推断当前说话人
   - 医生说完后通常是患者回答，反之亦然

3. **添加医嘱关键词识别**
   - "注意休息"、"少吃"、"多喝"、"避免"、"建议"、"复查"等

4. **混合片段检测**
   - 检测一句话中是否包含多个说话人的特征
   - 优先根据句子前半部分判断说话人
   - 例如："特别是早上起来的时候"（患者）+ "头疼持续多长时间了"（医生）→ 识别为患者

## 2026-04-14 后端框架与前端界面实现

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 后端框架搭建 | ✅ 完成 | FastAPI应用框架，包含API路由、数据库连接、配置管理 |
| 数据库模型设计 | ✅ 完成 | Visit、Task、TranscriptTurn、ASRCorrection模型 |
| API接口实现 | ✅ 完成 | 上传接口、ASR转写接口、任务状态查询接口 |
| 服务层实现 | ✅ 完成 | ASRService、ASRPostprocessor、TranscriptNormalizer |
| 音频工具实现 | ✅ 完成 | 音频验证、时长获取、格式转换 |
| 前端上传页面 | ✅ 完成 | 拖拽上传、表单填写、进度显示 |
| 前端结果页面 | ✅ 完成 | 转写结果展示、状态刷新、说话人区分 |
| 说话人分离脚本 | ✅ 完成 | demo_diarization.py、test_diarization.py等测试脚本 |

### 实现详情

1. **后端框架**
   - FastAPI应用入口：`backend/main.py`
   - 配置管理：`backend/config.py`（支持环境变量配置）
   - 数据库连接：`backend/database.py`（SQLite + SQLAlchemy）

2. **数据模型**
   - Visit：就诊记录，存储音频路径、患者信息、状态
   - Task：任务记录，存储ASR任务状态和进度
   - TranscriptTurn：转写轮次，存储说话人、文本、时间戳
   - ASRCorrection：ASR纠正记录，存储纠正前后对比

3. **API接口**
   - POST /api/upload：上传音频文件
   - POST /api/asr/transcribe/{visit_id}：启动ASR转写
   - GET /api/task/{task_id}：查询任务状态

4. **服务层**
   - ASRService：封装FunASR引擎，支持说话人分离
   - ASRPostprocessor：ASR后处理，医疗术语纠错
   - TranscriptNormalizer：文本标准化，说话人映射

5. **前端界面**
   - 上传页面：拖拽上传、表单填写、进度显示
   - 结果页面：转写结果展示、说话人区分、状态刷新

## 2026-04-12 M1里程碑设计方案

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| M1里程碑设计方案 | ✅ 完成 | `docs/specs/2026-04-12-m1-milestone-design.md` |
| 技术栈选型 | ✅ 完成 | FastAPI + HTML/JS + SQLite |
| 数据库设计 | ✅ 完成 | visits, transcript_turns, tasks, asr_corrections |
| API接口设计 | ✅ 完成 | 上传、转写、任务状态、结果查询 |
| 前端页面设计 | ✅ 完成 | 上传页面、结果展示页面 |
| 实施计划制定 | ✅ 完成 | 3阶段渐进式开发 |

### 设计要点

1. **技术栈选择**
   - 后端：FastAPI（现代、高性能、自动文档）
   - 前端：纯HTML + JavaScript（简单、快速）
   - 数据库：SQLite（轻量级、无需安装）
   - ASR：FunASR（现有模块集成）

2. **核心功能**
   - 音频上传（支持wav/mp3）
   - ASR转写（FunASR）
   - 说话人分离（区分医生/患者）
   - ASR后处理纠错（医疗术语纠错）
   - 转写结果标准化

3. **实施策略**
   - 阶段1：基础框架（1-2天）
   - 阶段2：ASR增强（2-3天）
   - 阶段3：前端优化（1-2天）

## 2026-04-11 技术选型文档更新

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 技术选型文档创建 | ✅ 完成 | `docs/技术选型文档.md` - ASR模块技术选型 |
| Benchmark分数更新 | ✅ 完成 | 使用公开数据，移除未公开数据 |
| 候选方案扩展 | ✅ 完成 | 加入Qwen3 ASR和FireRedASR对比 |
| 医疗场景证据补充 | ✅ 完成 | 加入MMedFD基准和稀有词处理证据 |
| 选择理由优化 | ✅ 完成 | 重新评估选择FunASR的理由 |
| MedASR对比加入 | ✅ 完成 | 加入谷歌MedASR医疗专用方案对比 |

### 主要改进

1. **Benchmark数据更新**
   - Paraformer Large: AISHELL-1 1.95%, AISHELL-2 2.85%, WenetSpeech meeting 6.97%
   - Qwen3 ASR: AISHELL-2 2.71%, WenetSpeech meeting 5.88%
   - FireRedASR: 四个中文集平均CER 3.05%
   - WeNet U2++: AISHELL-1 4.63%, AISHELL-2 5.39%
   - MedASR: 放射科听写WER 4.6%, 医疗数据集WER 4.6%-6.9%

2. **候选方案扩展**
   - 加入Qwen3 ASR（高性能候选）
   - 加入FireRedASR（高性能参考）
   - 加入MedASR（医疗专用方案，仅支持英文）
   - 移除PaddleSpeech（证据不足）

3. **医疗场景证据补充**
   - MMedFD医疗对话基准数据
   - 稀有词处理证据
   - MedASR医疗专用证据（WER 4.6%-6.9%）
   - 医疗适配路径优化

4. **选择理由优化**
   - 强调流程完整性（最核心优势）
   - 对比各方案的优劣
   - 说明为什么不选择其他方案
   - 说明MedASR仅支持英文医疗场景的限制

## 2026-04-06 ASR 模块开发

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| ASR 基础接口设计 | ✅ 完成 | `src/asr/base.py` - 抽象基类和数据类 |
| FunASR 引擎实现 | ✅ 完成 | `src/asr/funasr_engine.py` - 支持热词定制 |
| MedASR 引擎实现 | ✅ 完成 | `src/asr/medasr_engine.py` - 仅支持英文 |
| 工厂模式实现 | ✅ 完成 | `src/asr/factory.py` - 统一创建入口 |
| 对比测试脚本 | ✅ 完成 | `scripts/compare_asr.py` - 命令行工具 |
| 医疗热词文件 | ✅ 完成 | `config/hotwords_medical.txt` - 80+医疗术语 |
| 依赖配置 | ✅ 完成 | `requirements-asr.txt` |
| 数据集下载脚本 | ✅ 完成 | `scripts/download_dataset.py` - 支持 AISHELL-1 |
| 医疗数据集脚本 | ✅ 完成 | `scripts/download_medical_dataset.py` - 支持合成医疗语音 |

### 待验证

| 任务 | 状态 | 说明 |
|------|------|------|
| FunASR 实际运行测试 | ⏳ 待验证 | 需要安装依赖后测试 |
| MedASR 实际运行测试 | ⏳ 待验证 | 需要安装依赖后测试 |
| AMD 780M 兼容性测试 | ⏳ 待验证 | CPU 模式应该可行 |

### 注意事项

1. **MedASR 仅支持英文**：官方暂无中文版本，对中文音频会输出警告
2. **AMD 780M 建议 CPU 模式**：ROCm 对集成显卡支持有限
3. **热词文件**：已创建 80+ 常见医疗术语，可根据科室扩展
