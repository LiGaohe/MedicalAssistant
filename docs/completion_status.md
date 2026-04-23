# 完成状态记录

## 2026-04-21 病历验证模块

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 验证服务实现 | ✅ 完成 | 实现必填字段验证和医学术语验证 |
| 集成到病历生成流程 | ✅ 完成 | 生成后自动验证，结果保存到validation_errors |
| 日志输出 | ✅ 完成 | 验证结果输出到日志 |

### 新增文件

1. **backend/services/validation_service.py**
   - `ValidationService` 验证服务类
   - 必填字段完整性验证
   - 医学术语正确性验证（字典+UMLS）
   - 验证评分和质量等级计算

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 导入 `ValidationService`
   - 在 `__init__` 中初始化验证服务
   - 修改 `_save_emr_record()`：保存前进行验证

2. **backend/services/emr_generation_service.py**
   - 导入 `ValidationService`
   - 在 `__init__` 中初始化验证服务
   - 修改 `save_emr()`：保存前进行验证

### 验证功能说明

**必填字段验证**：

| 字段 | 是否必填 | 最小长度 |
|------|----------|----------|
| 主诉 | 是 | 2 |
| 现病史 | 是 | 10 |
| 既往史 | 否 | - |
| 体格检查 | 否 | - |
| 辅助检查 | 否 | - |
| 诊断 | 是 | 2 |
| 鉴别诊断 | 否 | - |
| 治疗方案 | 是 | 2 |
| 医嘱 | 否 | - |

**医学术语验证**：

- 使用 `config/medical_terms.json` 进行本地字典匹配
- 支持症状、药物、诊断、检查等术语类型
- 验证结果包含置信度和规范化术语

**验证评分**：

- 字段完整性占 70%
- 术语正确性占 30%
- 质量等级：优秀(≥90%)、良好(≥80%)、合格(≥60%)、需改进(≥40%)、不合格(<40%)

### 验证结果示例

```
============================================================
病历验证结果
============================================================
【总体评分】100.00% (优秀)
【验证状态】✓ 通过
【字段完整性】
  ✓ 主诉: 完整
  ✓ 现病史: 完整
  ✓ 诊断: 完整
  ✓ 治疗方案: 完整
【术语验证】
  ✓ 头痛 -> 头痛 (置信度: 1.00)
  ✓ 高血压 -> 高血压 (置信度: 1.00)
【警告】
  △ [既往史] 可选字段为空
  △ [辅助检查] 可选字段为空
============================================================
```

### 数据库字段

验证结果保存到 `emr_records.validation_errors` 字段，JSON格式：

```json
{
  "is_valid": true,
  "score": 1.0,
  "errors": [],
  "warnings": ["[既往史] 可选字段为空"],
  "summary": {
    "total_score": 1.0,
    "quality_level": "优秀",
    "field_completeness": {...},
    "term_validation": {...}
  },
  "field_validations": {...},
  "term_validations": [...]
}
```

---

## 2026-04-19 病历生成评估测试工具

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 测试对话生成脚本 | ✅ 完成 | 从测试数据集生成调试模式可用格式 |
| 手动测试指南 | ✅ 完成 | 说明如何手动测试和评估 |
| 评估分析工具 | ✅ 完成 | 记录测试结果并计算评估指标 |
| 后端自动评估集成 | ✅ 完成 | 病历生成后自动评估并输出到日志 |

### 新增文件

1. **scripts/generate_test_dialogs.py**
   - 从 `test.json` 提取对话转换为调试模式格式
   - 支持指定样本数量或样本ID
   - 输出包含标注诊断和症状信息

2. **scripts/evaluation_analyzer.py**
   - 评估结果分析工具
   - 计算诊断匹配率、症状F1、SOAP完整性
   - 生成评估报告

3. **backend/services/evaluation_service.py**
   - 评估服务模块
   - 自动匹配测试数据集样本
   - 计算评估指标并输出到日志

4. **data/text/test_dialogs.txt**
   - 生成的测试对话文件（5个样本）
   - 可直接复制到调试模式使用

5. **data/text/manual_test_guide.md**
   - 手动测试指南
   - 包含测试方法、样本示例、评估指标、评估标准

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 导入 `EMREvaluationService`
   - 新增 `_run_evaluation()` 方法
   - 在 `process_transcript()` 完成后自动调用评估

### 评估流程

```
病历生成完成 → 匹配测试数据集 → 计算评估指标 → 输出到日志
```

### 日志输出示例

```
============================================================
病历生成评估结果 [样本ID: 10035922]
============================================================
【诊断评估】
  标注诊断: 小儿支气管炎
  生成诊断: 支气管炎
  匹配结果: 部分匹配
【症状抽取评估】
  标注症状: 咳嗽, 发热, 淋巴结肿大
  生成症状: 咳嗽, 发热
  准确率: 66.67%
  召回率: 66.67%
  F1分数: 66.67%
【SOAP完整性】
  ✓ 主诉: 完整
  ✓ 现病史: 完整
  ✗ 体格检查: 缺失
  ✓ 诊断: 完整
  ✓ 治疗: 完整
============================================================
评估结论: 良好 ✓
============================================================
```

### 使用方法

```bash
# 生成测试对话
python scripts/generate_test_dialogs.py -n 10

# 生成指定样本
python scripts/generate_test_dialogs.py -i 10035922

# 运行评估分析（示例）
python scripts/evaluation_analyzer.py
```

### 评估指标与标准

| 指标 | 优秀 | 良好 | 需改进 |
|------|------|------|--------|
| 诊断匹配率 | ≥ 80% | ≥ 60% | < 60% |
| 症状F1 | ≥ 0.7 | ≥ 0.5 | < 0.5 |
| SOAP完整性 | ≥ 90% | ≥ 70% | < 70% |

---

## 2026-04-18 证据溯源优化：最终病历内容关联

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 模型字段扩展 | ✅ 完成 | EvidenceSpan添加field_value字段 |
| 最终病历保存 | ✅ 完成 | 保存证据时同时保存对应的最终病历内容 |
| 证据溯源面板 | ✅ 完成 | 显示最终病历列 |
| 字段证据卡片 | ✅ 完成 | 显示最终病历内容 |

### 修改文件

1. **backend/models/evidence.py**
   - 新增 `field_value` 字段：存储最终病历内容

2. **backend/services/llm_pipeline_service.py**
   - 修改 `_save_evidence_spans()`：添加emr_result参数，保存field_value

3. **backend/api/emr.py**
   - 修改 `get_evidence_by_visit()`：返回field_value字段

4. **frontend/js/emr.js**
   - 修改 `buildEvidenceHtml()`：显示最终病历内容
   - 修改 `showEvidence()`：证据面板添加最终病历列

5. **frontend/css/style.css**
   - 新增 `.evidence-final-value` 样式
   - 新增 `.evidence-value-cell` 样式
   - 新增 `.evidence-turn-cell` 样式

### 证据溯源表格结构

| 列名 | 说明 |
|------|------|
| 字段类型 | 病历字段（主诉、现病史等） |
| 最终病历 | 生成的病历内容 |
| 标注片段 | LLM从原始转写中标注的相关片段 |
| 原始转写 | ASR转写的完整文本 |
| 说话人 | spk0/spk1等 |
| 轮次 | 对话轮次索引 |
| 置信度 | 计算后的置信度 |

### 数据关系说明

```
原始转写文本（完整）
    │
    ├── LLM标注 ──→ 标注片段（原始转写的子集）
    │                    │
    │                    └── 多个标注片段综合 ──→ 最终病历
    │
    └── 完整保存用于溯源
```

**示例**：

| 原始转写 | 标注片段 | 最终病历 |
|----------|----------|----------|
| 医生，我这几天一直头疼，特别是早上起来的时候 | 我这几天一直头疼 | 头痛3天，晨起明显 |

### 数据流程

```
ASR转写文本 → LLM标注证据 → 抽取字段 → 生成病历 → 保存证据(含field_value)
                                                    ↓
                                            前端显示证据溯源
```

### 数据库迁移

由于使用 `create_all` 方式，新字段不会自动添加到现有表。需要手动执行：

```sql
ALTER TABLE evidence_spans ADD COLUMN field_value TEXT;
```

**注意**：现有证据记录的 `field_value` 为空，需重新生成病历才能填充。

### 调试模式证据传递修复

调试模式下 `evidence_traces` 未正确传递到后续阶段，已修复：

| 阶段 | 修改内容 |
|------|----------|
| role_annotation | 将 `evidence_traces` 保存到 context |
| field_extraction | 从 context 获取 `evidence_traces` 并传递 |

**数据流**：
```
role_annotation → evidence_traces → context
                                        ↓
field_extraction ← 从context获取 ← evidence_traces
                                        ↓
emr_generation → 保存证据到数据库
```

### 标注片段跨多轮次匹配修复

当LLM将多个轮次内容合并到一个标签时（如 `<现病史>大概三天了， [spk1]: 有时候会恶心</现病史>`），需要匹配多个turn：

| 修改前 | 修改后 |
|--------|--------|
| 只匹配单个turn | 检测标注片段中的说话人标记，匹配所有相关turn |
| `turn_text` 为单个turn | `turn_text` 合并所有匹配的turn文本 |

**示例**：

| 标注片段 | 匹配的turn_text |
|----------|-----------------|
| `大概三天了， [spk1]: 有时候会恶心` | `[spk1]: 大概三天了，\n[spk1]: 有时候会恶心` |

### turn_text字段保存到数据库

`turn_text` 原来只在内存中传递，未保存到数据库，导致表格显示不完整。

**修改**：

1. **模型**：`EvidenceSpan` 添加 `turn_text` 字段
2. **保存**：`_save_evidence_spans()` 保存 `turn_text`
3. **API**：优先返回保存的 `turn_text`，回退到关联查询

**数据库迁移**：

```sql
ALTER TABLE evidence_spans ADD COLUMN turn_text TEXT;
```

---

## 2026-04-18 证据溯源优化：转写文本与置信度计算

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 转写文本显示 | ✅ 完成 | 证据溯源中显示原始转写文本 |
| 置信度计算 | ✅ 完成 | 基于内容匹配、角色匹配、ASR置信度计算 |
| 前端展示优化 | ✅ 完成 | 重新设计证据卡片样式，显示更多信息 |

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 新增 `FIELD_EXPECTED_ROLE`：定义各字段期望的说话人角色
   - 新增 `_calculate_evidence_confidence()`：置信度计算方法
   - 修改 `_extract_evidence_traces()`：添加turn_text和置信度计算
   - 修改 `_attach_evidence_traces()`：传递turn_text字段

2. **frontend/js/emr.js**
   - 修改 `buildEvidenceHtml()`：显示标注内容和原始转写
   - 修改 `showEvidence()`：证据面板添加原始转写列

3. **frontend/css/style.css**
   - 重构 `.evidence-traces` 样式
   - 新增 `.evidence-header`、`.evidence-detail`、`.evidence-turn-text` 样式

### 置信度计算逻辑

置信度由以下因素加权计算：

| 因素 | 权重范围 | 说明 |
|------|----------|------|
| 基础置信度 | 0.5 | 起始值 |
| 内容匹配度 | +0.0~+0.3 | 证据内容与原始转写的相似程度 |
| 角色匹配度 | +0.2/-0.1 | 说话人角色与字段期望角色是否匹配 |
| ASR置信度 | +0.0~+0.1 | 转写置信度（如有） |

**最终置信度范围**：0.1 ~ 1.0

### 证据显示格式

每个证据卡片包含：

- **说话人**：spk0/spk1等
- **轮次**：对话轮次索引
- **置信度**：计算后的置信度百分比
- **标注内容**：LLM标注的证据内容
- **原始转写**：对应的ASR转写文本

---

## 2026-04-18 病历证据溯源、编辑与打印功能

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 证据溯源显示 | ✅ 完成 | 显示每个字段的证据来源，包含说话人、轮次、置信度 |
| 证据溯源面板 | ✅ 完成 | 独立面板展示所有证据，支持展开/隐藏 |
| 病历编辑功能 | ✅ 完成 | 支持编辑病历内容，保存为新版本 |
| 病历打印功能 | ✅ 完成 | 生成适合打印的格式，隐藏非必要元素 |
| 后端API扩展 | ✅ 完成 | 新增证据查询API和病历更新API |

### 修改文件

1. **backend/api/emr.py**
   - 新增 `UpdateEMRRequest` 模型：病历更新请求
   - 新增 `UpdateEMRResponse` 模型：病历更新响应
   - 新增 `PUT /api/emr/record/{visit_id}`：更新病历记录，创建新版本
   - 新增 `GET /api/emr/evidence/{visit_id}`：获取证据溯源数据

2. **frontend/emr.html**
   - 新增工具栏：包含编辑、保存、取消、打印、证据溯源按钮
   - 新增证据溯源面板 `evidencePanel`
   - 为病历内容区域添加ID `emrContent`

3. **frontend/js/emr.js**
   - 新增 `loadEvidenceData()`：加载证据数据
   - 新增 `showEvidence()`/`hideEvidence()`：显示/隐藏证据面板
   - 新增 `buildEvidenceHtml()`：构建证据溯源HTML
   - 新增 `enterEditMode()`/`exitEditMode()`：进入/退出编辑模式
   - 新增 `makeSectionEditable()`：将内容转为可编辑状态
   - 新增 `saveEMREdits()`：保存编辑后的病历
   - 新增 `printEMR()`：打印病历功能

4. **frontend/css/style.css**
   - 新增 `.emr-toolbar`：工具栏样式
   - 新增 `.evidence-panel`：证据面板样式
   - 新增 `.evidence-table`：证据表格样式
   - 新增 `.evidence-traces`：字段内证据显示样式
   - 新增 `.edit-textarea`：编辑文本框样式
   - 新增 `@media print`：打印样式

### 功能说明

**证据溯源**：

- 每个病历字段下方显示证据来源
- 证据来源包含：说话人、证据内容、轮次索引、置信度
- 独立面板可查看所有证据的汇总表格
- 点击"显示证据溯源"按钮切换面板显示

**病历编辑**：

- 点击"编辑病历"进入编辑模式
- 所有文本区域转为可编辑的文本框
- 点击"保存修改"保存为新版本（record_type: user_edited）
- 点击"取消编辑"放弃修改

**病历打印**：

- 点击"打印病历"打开打印预览窗口
- 打印格式优化：隐藏工具栏、证据溯源、置信度等
- 使用宋体字体，符合医疗文档规范
- 包含就诊记录ID和打印时间

---

## 2026-04-18 前端调试模式优化

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 动态提示词生成 | ✅ 完成 | 后续阶段提示词根据前一阶段结果动态生成 |
| Context传递优化 | ✅ 完成 | 正确传递和更新各阶段处理结果 |
| 阶段描述更新 | ✅ 完成 | 实时更新阶段选择器中的描述 |
| 多segment支持 | ✅ 完成 | 正确处理阶段1的多个segment |
| 病历保存功能 | ✅ 完成 | 调试模式完成后自动保存病历到数据库 |

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - `get_all_prompts()`：只返回阶段1的提示词，后续阶段标记为"待生成"
   - `process_stage_with_user_input()`：根据前一阶段结果动态生成下一阶段提示词
   - 添加 `context_update` 返回值，用于更新前端context
   - 添加 `next_description` 返回值，用于更新阶段描述
   - 添加 `next_segment_index` 返回值，用于处理多个segment
   - 新增 `_save_emr_record()`：保存病历记录到数据库
   - 修改 `_parse_emr_response()`：解析后自动保存病历
   - 修改 `_template_emr_generation()`：模板生成后自动保存病历

2. **backend/api/emr.py**
   - `DebugProcessStageResponse`：添加新字段 `next_segment_index`, `next_description`, `context_update`, `completed`
   - `debug_process_stage()`：返回新增字段

3. **frontend/js/emr.js**
   - 使用 `context_update` 更新 `debugContext`
   - 使用 `next_description` 更新阶段选择器
   - 使用 `next_segment_index` 更新当前segment索引
   - 正确传递 `segment_index` 到后端

### 工作流程

1. 用户打开调试模式，显示所有阶段（阶段1可能有多个segment）
2. 阶段1各segment处理完成后，合并所有 `annotated_text`
3. 阶段2使用阶段1的合并结果生成提示词
4. 阶段3使用阶段2的 `normalized_text` 生成提示词
5. 阶段4使用阶段3的 `extraction_result` 生成提示词
6. 阶段4完成后，自动保存病历记录到数据库
7. 刷新页面后显示生成的病历

---

## 2026-04-17 多阶段LLM证据抽取流程

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 配置开关 | ✅ 完成 | 添加 `LLM_DEBUG_MODE` 和 `LLM_SEGMENT_TURNS` 配置 |
| LLMPipelineService | ✅ 完成 | 实现多阶段LLM处理服务 |
| 调试模式支持 | ✅ 完成 | 支持y/n交互和手动输入结果 |
| API端点 | ✅ 完成 | 新增 `/api/emr/pipeline/process` 等端点 |
| LLM调用修复 | ✅ 完成 | 修复API响应解析和超时问题 |

### 设计决策

**多阶段处理流程**：

1. **阶段1 - 角色识别与证据标注**：
   - 将对话按轮次分段（默认每10轮一段）
   - 大模型识别说话人角色（医生/患者）
   - 用XML标签标注证据字段（动态识别）

2. **阶段2 - 术语规范化**：
   - 对标注文本中的口语化医学术语规范化
   - 保持XML标签和对话格式不变

3. **阶段3 - 字段抽取**：
   - 从XML标签中提取对应字段内容
   - 合并、去重、处理冲突

4. **阶段4 - 病历生成**：
   - 根据抽取结果生成SOAP格式病历
   - 符合中国医疗病历书写规范

**调试模式设计**：

- 输入 `y`：正常发送给大模型
- 输入 `n`：不发送，显示提示词和指导步骤，允许手动输入结果
- 输入 `q`：取消操作

### 实现详情

1. **配置项** (`backend/config.py`)
   - `LLM_DEBUG_MODE`：调试模式开关，默认 `False`
   - `LLM_SEGMENT_TURNS`：分段轮次数，默认 `10`

2. **LLMPipelineService** (`backend/services/llm_pipeline_service.py`)
   - `process_transcript()`：完整处理流程
   - `_segment_turns()`：按轮次分段
   - `_process_segment()`：处理单个段落
   - `_normalize_terms_stage()`：术语规范化阶段
   - `_extract_fields_stage()`：字段抽取阶段
   - `_generate_emr_stage()`：病历生成阶段
   - `_debug_interact()`：调试模式交互

3. **API端点** (`backend/api/emr.py`)
   - `POST /api/emr/pipeline/process`：多阶段LLM处理
   - `GET /api/emr/config/debug-mode`：获取调试模式配置
   - `POST /api/emr/config/debug-mode`：设置调试模式

4. **降级方案**：
   - LLM不可用时，使用规则推断角色
   - 保留原有的 `MedicalRecordPipeline` 作为备选

5. **LLM调用修复** (`backend/services/llm/openai_compatible_adapter.py`)
   - 增加超时时间：60s → 120s
   - 安全解析API响应：使用 `.get()` 方法避免 KeyError
   - 检查空choices：提供详细错误信息
   - 检查None content：避免后续处理错误
   - 添加重试机制：最多5次重试，指数退避
   - 添加请求间隔：默认2秒间隔避免限流
   - 检测限流：识别 `total_tokens=0` 的限流响应

6. **证据溯源功能** (`backend/services/llm_pipeline_service.py`)
   - `_extract_evidence_traces()`：从标注文本提取证据位置
   - `_attach_evidence_traces()`：关联证据到抽取字段
   - `_save_evidence_spans()`：保存溯源记录到数据库
   - 溯源信息包含：turn_id, turn_index, speaker, start_char, end_char, confidence
   - 添加阶段间延迟：3秒间隔避免API限流

7. **API端点整合** (`backend/api/emr.py`)
   - `/api/emr/process` 现在使用 `LLMPipelineService`（当 `use_llm=True`）
   - DEBUG模式在HTTP请求中自动禁用（需要终端交互）
   - 返回格式兼容旧的 `ProcessResponse`

### 使用方法

**开启调试模式**：

```python
# 方式1：修改配置文件
# backend/config.py
LLM_DEBUG_MODE = True
LLM_SEGMENT_TURNS = 10

# 方式2：通过API设置
POST /api/emr/config/debug-mode?enabled=true&segment_turns=10
```

**调用多阶段处理**：

```python
# API调用
POST /api/emr/pipeline/process
{
  "visit_id": "test_visit_001"
}

# 返回结果
{
  "status": "completed",
  "role_mapping": {"spk0": "doctor", "spk1": "patient"},
  "annotated_text": "标注后的文本...",
  "normalized_result": {...},
  "extraction_result": {...},
  "emr_result": {...}
}
```

**调试模式交互示例**：

```
================================================================================
[DEBUG模式] 阶段: role_annotation
================================================================================

>>> 即将发送给大模型的完整内容：

你是一个医疗对话分析专家。请分析以下医患对话...
--------------------------------------------------------------------------------

请选择操作：
  y - 确认发送给大模型
  n - 不发送，手动输入结果
  q - 取消操作

请输入选择: n

>>> 手动输入模式
阶段: role_annotation

指导步骤：
1. 分析对话内容，判断每个说话人(spk0, spk1等)是医生还是患者
2. 用XML标签标注证据字段...
```

### 测试结果

```
测试数据已存在，跳过创建

当前配置:
  LLM_DEBUG_MODE: False
  LLM_SEGMENT_TURNS: 10

可用的LLM适配器: ['glm-5.1']

============================================================
开始多阶段LLM处理...
============================================================
>>> 处理段落 1/1
合并后的标注文本长度: 327 字符
收集到 6 条证据溯源记录
>>> 阶段2: 术语规范化
>>> 阶段3: 字段抽取
>>> 阶段4: 病历生成
保存了 6 条证据溯源记录到数据库

============================================================
处理结果:
============================================================
状态: completed

角色映射:
  spk0: doctor
  spk1: patient

生成的病历:
  主观数据: 主诉：头痛3天，晨起明显。现病史：患者3天前无明显诱因出现头痛，以晨起时为著...
  客观数据: 体格检查：血压 145/95mmHg。辅助检查：暂缺。
  评估: 初步诊断：1. 高血压病；2. 头痛（考虑高血压所致）。
  计划: 治疗方案：给予降压药物治疗，每日1次，晨起口服。医嘱及健康指导：低盐饮食...

证据溯源信息 (共6条):
  [1] 主诉: 我这几天一直头疼，特别是早上起来的时候。...
      来源: turn_id=340, speaker=spk1, turn_index=1
  [2] 现病史: 大概三天了，有时候会恶心，但没有呕吐。...
      来源: turn_id=342, speaker=spk1, turn_index=3
  [3] 体格检查: 我给您量一下血压。一百四十五九十五，血压偏高。...
      来源: turn_id=343, speaker=spk0, turn_index=4
  [4] 诊断: 是的，考虑是高血压引起的头疼。...
      来源: turn_id=345, speaker=spk0, turn_index=6
  [5] 治疗: 我给您开点降压药，每天一次，早上吃。...
      来源: turn_id=345, speaker=spk0, turn_index=6
  ... 还有 1 条证据

数据库中保存的证据记录: 6 条
```

### 溯源数据结构

每条证据溯源记录包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| field_type | str | 字段类型（英文） |
| field_type_cn | str | 字段类型（中文） |
| content | str | 证据内容 |
| turn_id | int | 关联的对话轮次ID |
| turn_index | int | 对话轮次索引 |
| speaker | str | 说话人ID |
| start_char | int | 在标注文本中的起始位置 |
| end_char | int | 在标注文本中的结束位置 |
| confidence | float | 置信度 |

## 2026-04-17 置信度字段支持

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| TranscriptTurn模型 | ✅ 完成 | 添加 `confidence` 字段 |
| ASRService传递置信度 | ✅ 完成 | FunASR和Qwen3-ASR均传递置信度 |
| EvidenceService使用置信度 | ✅ 完成 | 基于置信度过滤和打分 |
| 单元测试 | ✅ 完成 | 8个测试全部通过 |

### 设计决策

**置信度在证据选择中的作用**：

1. **过滤低置信度轮次**：置信度低于阈值的对话轮次直接过滤
2. **影响证据得分**：置信度越高，证据得分越高
3. **继承到证据记录**：EvidenceSpan 继承 TranscriptTurn 的置信度

### 实现详情

1. **TranscriptTurn 模型** (`backend/models/transcript.py`)
   - 新增 `confidence` 字段，类型 `Float`，默认值 `1.0`
   - 允许为空，兼容旧数据

2. **ASRService 传递置信度** (`backend/services/asr_service.py`)
   - `_transcribe_funasr_with_diarization()`：从 FunASR 输出提取置信度
   - `_transcribe_qwen3_asr()`：Qwen3-ASR 默认置信度为 1.0

3. **EvidenceService 使用置信度** (`backend/services/evidence_service.py`)
   - `select_evidence_by_rules()` 新增 `confidence_threshold` 参数
   - `_calculate_turn_score()` 新增置信度过滤和加权逻辑
   - 低置信度轮次被过滤并记录日志

### 置信度打分公式

```
最终得分 = 基础得分 × 说话人偏好系数 × 句长系数 × (0.5 + 0.5 × confidence)
```

- 基础得分：触发词命中数量
- 说话人偏好系数：匹配偏好说话人时 ×1.2
- 句长系数：短句（<5字）×0.5
- 置信度系数：`0.5 + 0.5 × confidence`（范围 0.5-1.0）

### 测试结果

```
tests/test_confidence_feature.py::TestTranscriptTurnConfidence::test_create_turn_with_confidence PASSED
tests/test_confidence_feature.py::TestTranscriptTurnConfidence::test_create_turn_without_confidence PASSED
tests/test_confidence_feature.py::TestEvidenceServiceConfidence::test_filter_low_confidence_turns PASSED
tests/test_confidence_feature.py::TestEvidenceServiceConfidence::test_confidence_affects_score PASSED
tests/test_confidence_feature.py::TestEvidenceServiceConfidence::test_zero_confidence_turn_filtered PASSED
tests/test_confidence_feature.py::TestEvidenceServiceConfidence::test_evidence_inherits_turn_confidence PASSED
tests/test_confidence_feature.py::TestASRServiceConfidence::test_funasr_turns_include_confidence PASSED
tests/test_confidence_feature.py::TestASRServiceConfidence::test_qwen3_asr_turns_include_default_confidence PASSED
======================= 8 passed in 2.56s ========================
```

## 2026-04-17 病历生成角色识别功能

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 角色推断逻辑 | ✅ 完成 | 基于对话内容推断说话人角色（医生/患者） |
| 证据内容修正 | ✅ 完成 | 根据角色修正证据内容归属 |
| LLM Prompt模板 | ✅ 完成 | 新增支持角色识别的病历生成模板 |
| 字段去重逻辑 | ✅ 完成 | 保留置信度最高的字段 |

### 设计决策

**保持ASR模块职责边界**：
- ASR模块只输出 `spk0`/`spk1` 等原始说话人ID
- 角色识别（医生/患者）由病历生成模块负责
- 符合设计文档中的职责分离原则

### 实现详情

1. **角色推断** (`backend/services/emr_generation_service.py`)
   - 新增 `_infer_roles()` 方法
   - 基于对话内容特征推断角色：
     - 医生特征：问问题、检查、诊断、开药、医嘱
     - 患者特征：称呼"医生"、描述症状、回答问题
   - 问号结尾的句子倾向于医生

2. **证据内容修正** (`backend/services/emr_generation_service.py`)
   - 新增 `_correct_content_by_role()` 方法
   - 根据字段类型期望的角色修正内容：
     - 主诉、现病史、既往史 → 患者
     - 体格检查、诊断、治疗、医嘱 → 医生
   - 使用关键词匹配选择正确内容

3. **字段去重优化** (`backend/services/emr_generation_service.py`)
   - 修改 `_aggregate_items()` 方法
   - 同名字段保留置信度最高的
   - 避免正确内容被错误内容覆盖

4. **LLM Prompt模板** (`backend/services/llm/prompts.py`)
   - 新增 `emr_generation_with_role` 模板
   - 支持LLM进行角色识别和内容修正
   - 包含原始对话和初步抽取数据

### 测试结果

修改前：
```
主诉：有没有恶心、呕吐的症状？（医生问的问题，错误）
体格检查：考虑是高血压引起的头疼...（诊断内容，错误）
```

修改后：
```
主诉：医生，我这几天一直头疼，特别是早上起来的时候（患者回答，正确）
体格检查：我给您量一下血压，一百四十五九十五，血压偏高（正确）
```

## 2026-04-17 魔搭API集成修复

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| API Endpoint自动补全 | ✅ 完成 | 自动处理base_url和完整endpoint格式 |
| 配置页面提示更新 | ✅ 完成 | 添加魔搭配置示例和提示信息 |
| 使用文档更新 | ✅ 完成 | 添加魔搭ModelScope配置示例 |
| 集成测试 | ✅ 完成 | 验证魔搭API调用成功 |

### 实现详情

1. **API Endpoint自动补全** (`backend/services/llm/openai_compatible_adapter.py`)
   - 自动检测endpoint格式
   - 支持base_url格式（如 `https://api-inference.modelscope.cn/v1`）
   - 支持完整endpoint格式（如 `https://api.openai.com/v1/chat/completions`）
   - 自动添加 `/chat/completions` 后缀

2. **配置页面更新** (`frontend/config.html`)
   - 更新placeholder为魔搭示例
   - 添加提示信息：支持base_url格式或完整endpoint格式

3. **使用文档更新** (`docs/前端使用说明.md`)
   - 新增魔搭ModelScope配置示例（推荐）
   - 配置名称: modelscope
   - 模型: ZhipuAI/GLM-5.1
   - Endpoint: https://api-inference.modelscope.cn/v1

4. **集成测试**
   - 测试魔搭API调用成功
   - 验证endpoint自动补全功能
   - 确认响应格式正确

### 问题原因

用户配置的endpoint是 `https://api-inference.modelscope.cn/v1`（base_url格式），但代码期望的是完整endpoint格式（包含 `/chat/completions`）。OpenAI SDK会自动添加后缀，但我们的代码直接调用HTTP API，需要完整URL。

### 解决方案

修改 `OpenAICompatibleAdapter.__init__()` 方法，自动检测endpoint格式并补全：
- 如果endpoint不以 `/chat/completions` 结尾
- 检查是否以 `/v1` 结尾，如果是则添加 `/chat/completions`
- 否则添加 `/v1/chat/completions`

## 2026-04-17 前端功能更新

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 病历生成页面 | ✅ 完成 | frontend/emr.html, frontend/js/emr.js |
| LLM配置页面 | ✅ 完成 | frontend/config.html, frontend/js/config.js |
| 转写结果页面更新 | ✅ 完成 | 添加生成病历和配置LLM按钮 |
| 首页更新 | ✅ 完成 | 添加配置大模型按钮 |
| API接口调整 | ✅ 完成 | backend/api/llm.py 调整接口路径 |
| 样式更新 | ✅ 完成 | frontend/css/style.css 新增样式 |
| 使用文档 | ✅ 完成 | docs/前端使用说明.md |

### 实现详情

1. **病历生成页面** (`frontend/emr.html`)
   - 生成病历按钮
   - 查看病历按钮
   - 病历版本选择
   - SOAP格式展示（主观数据、客观数据、评估、计划）
   - 证据回链显示

2. **LLM配置页面** (`frontend/config.html`)
   - 配置表单（配置名称、服务商、模型名称、API Key、API Endpoint等）
   - 已保存配置列表
   - 启用/禁用/删除配置功能

3. **转写结果页面更新** (`frontend/result.html`)
   - 添加"生成病历"按钮（转写完成后显示）
   - 添加"配置大模型"按钮
   - 按钮事件处理逻辑

4. **首页更新** (`frontend/index.html`)
   - 添加"配置大模型"按钮
   - 跳转到配置页面

5. **API接口调整** (`backend/api/llm.py`)
   - `/api/llm/config` POST：创建/更新配置
   - `/api/llm/config/{config_id}` PUT：更新配置状态
   - `/api/llm/config/{config_id}` DELETE：删除配置
   - 返回格式统一为 `{"success": True/False, ...}`

6. **样式更新** (`frontend/css/style.css`)
   - 新增 `.btn-success`、`.btn-small`、`.btn-danger` 样式
   - 新增配置页面样式：`.config-section`、`.config-item`、`.config-header`等
   - 新增病历页面样式：`.emr-section`、`.emr-part`、`.field-item`等

7. **使用文档** (`docs/前端使用说明.md`)
   - 功能概览
   - 页面导航说明
   - 使用流程（不配置LLM vs 配置LLM）
   - API配置示例（通义千问、OpenAI、本地模型）
   - 病历内容说明
   - 故障排除

## 2026-04-17 M2里程碑：文本到病历

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 数据模型设计 | ✅ 完成 | EvidenceSpan, NormalizedTerm, ExtractedItem, EMRRecord |
| 字段触发词表 | ✅ 完成 | config/field_triggers.json |
| 医学术语词表 | ✅ 完成 | config/medical_terms.json |
| 证据选择模块 | ✅ 完成 | EvidenceService（规则+LLM） |
| 术语规范化模块 | ✅ 完成 | TerminologyService（字典+LLM） |
| 病历要素抽取模块 | ✅ 完成 | ExtractionService（规则+LLM） |
| 病历生成模块 | ✅ 完成 | EMRGenerationService（模板+LLM） |
| 整合服务 | ✅ 完成 | MedicalRecordPipeline |
| API接口 | ✅ 完成 | /api/emr/* |
| 测试脚本 | ✅ 完成 | scripts/test_m2_milestone.py |

### 实现详情

1. **数据模型** (`backend/models/`)
   - `EvidenceSpan`：证据片段，存储字段类型、内容、置信度、分数
   - `NormalizedTerm`：规范化术语，存储原始术语、标准术语、术语类型、风险标记
   - `ExtractedItem`：抽取的病历要素，存储字段名、字段值、证据ID列表
   - `EMRRecord`：病历记录，存储版本、类型、JSON内容、证据映射

2. **字段触发词表** (`config/field_triggers.json`)
   - 8个核心字段：主诉、现病史、既往史、体格检查、辅助检查、诊断、治疗方案、医嘱
   - 每个字段包含触发词列表、说话人偏好、权重
   - 支持基于规则的证据筛选

3. **医学术语词表** (`config/medical_terms.json`)
   - 4类术语：症状、药物、诊断、检查
   - 每个标准术语包含同义词和口语表达
   - 支持术语规范化

4. **证据选择模块** (`backend/services/evidence_service.py`)
   - `select_evidence_by_rules()`：基于触发词和说话人偏好筛选证据
   - `select_evidence_by_llm()`：使用LLM选择证据
   - 支持证据打分和排序

5. **术语规范化模块** (`backend/services/terminology_service.py`)
   - `normalize_term()`：规范化单个术语（字典+LLM）
   - `extract_and_normalize_terms()`：从文本中提取并规范化术语
   - 支持相似度匹配和风险标记

6. **病历要素抽取模块** (`backend/services/extraction_service.py`)
   - `extract_items()`：从证据中抽取病历要素（规则+LLM）
   - `aggregate_items()`：聚合抽取结果，去重和冲突处理
   - 支持SOAP格式输出

7. **病历生成模块** (`backend/services/emr_generation_service.py`)
   - `generate_emr()`：生成病历（模板+LLM）
   - 支持版本化存储
   - 支持证据映射

8. **整合服务** (`backend/services/medical_record_pipeline.py`)
   - `process_visit()`：完整处理流程
   - 步骤：证据选择 → 术语规范化 → 要素抽取 → 病历生成
   - 支持中间结果保存

9. **API接口** (`backend/api/emr.py`)
   - `POST /api/emr/process`：处理就诊记录
   - `GET /api/emr/status/{visit_id}`：查询处理状态
   - `GET /api/emr/record/{visit_id}`：获取病历记录
   - `GET /api/emr/versions/{visit_id}`：获取所有版本

### 测试结果

```
测试数据：9轮对话
证据数量：10个
规范化术语数量：11个
抽取要素数量：20个
病历生成：成功
```

### 使用方法

```python
# 方式1：使用整合服务
from backend.services.medical_record_pipeline import MedicalRecordPipeline
from backend.services.llm.llm_service import LLMService

pipeline = MedicalRecordPipeline(db, llm_service)
result = pipeline.process_visit("visit_id", use_llm=True)

# 方式2：使用API接口
POST /api/emr/process
{
  "visit_id": "test_visit_001",
  "use_llm": true,
  "save_intermediate": true
}
```

### 后续优化

1. **LLM Prompt优化**：优化证据选择、术语规范化、要素抽取的prompt模板
2. **规则优化**：完善触发词表和术语词表
3. **验证模块**：实现T22-T25（规则校验器、风险标记器、审核页面）
4. **评测模块**：实现T26-T29（测试集、指标脚本、错误分析）

## 2026-04-17 Qwen3-ASR引擎集成

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 安装qwen-asr包 | ✅ 完成 | pip install -U qwen-asr |
| 创建Qwen3ASREngine引擎类 | ✅ 完成 | src/asr/qwen3_asr_engine.py |
| 更新ASRFactory注册 | ✅ 完成 | 支持"qwen3-asr"引擎类型 |
| 更新ASRService支持 | ✅ 完成 | 支持Qwen3-ASR引擎切换 |
| 更新配置文件 | ✅ 完成 | 添加QWEN3_ASR_MODEL_SIZE等配置项 |
| 创建测试脚本 | ✅ 完成 | scripts/test_qwen3_asr.py |

### 实现详情

1. **Qwen3ASREngine引擎类** (`src/asr/qwen3_asr_engine.py`)
   - 继承ASRBase抽象基类
   - 支持1.7B和0.6B两种模型规格
   - 支持CPU和GPU运行
   - 支持长音频分块转写（超过30秒自动分块）
   - 使用transformers库加载模型

2. **ASRFactory更新** (`src/asr/factory.py`)
   - 注册"qwen3-asr"引擎类型
   - 支持通过工厂模式创建Qwen3ASREngine实例

3. **ASRService更新** (`backend/services/asr_service.py`)
   - 支持engine_type配置项切换引擎
   - Qwen3-ASR模式：不支持说话人分离，所有文本归为spk0
   - FunASR模式：保持原有说话人分离功能

4. **配置项** (`backend/config.py`)
   - `QWEN3_ASR_MODEL_SIZE`: 模型规格，默认"1.7B"
   - `QWEN3_ASR_LANGUAGE`: 语言，默认"Chinese"

### 使用方法

```python
# 方式1：使用ASRService
from backend.services.asr_service import ASRService

config = {
    "engine_type": "qwen3-asr",
    "device": "cpu",
    "qwen3_asr_model_size": "1.7B",
    "qwen3_asr_language": "Chinese"
}
service = ASRService(config)
result = service.transcribe_with_diarization("audio.wav")

# 方式2：直接使用引擎
from src.asr import Qwen3ASREngine

engine = Qwen3ASREngine(device="cpu", model_size="1.7B")
engine.load_model()
result = engine.transcribe("audio.wav")  # 短音频
result = engine.transcribe_long_audio("long_audio.wav")  # 长音频
```

### 测试命令

```bash
# 激活环境
source med_env/Scripts/activate

# 测试Qwen3-ASR
python scripts/test_qwen3_asr.py audio.wav --device cpu
```

### 注意事项

1. **模型下载**：首次运行时会自动从HuggingFace下载模型（约2.5GB）
2. **说话人分离**：Qwen3-ASR不支持说话人分离，如需区分医生/患者请使用FunASR
3. **长音频处理**：超过30秒的音频会自动分块处理，每块30秒
4. **内存需求**：1.7B模型CPU运行需要约4GB内存

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

## 2026-04-17 日志系统与病历显示问题修复

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 日志系统搭建 | ✅ 完成 | backend/utils/logger.py |
| 流水线日志输出 | ✅ 完成 | medical_record_pipeline.py 各阶段详细日志 |
| 证据选择日志 | ✅ 完成 | evidence_service.py 证据选择过程日志 |
| 术语规范化日志 | ✅ 完成 | terminology_service.py 术语提取和规范化日志 |
| 病历要素抽取日志 | ✅ 完成 | extraction_service.py 抽取过程日志 |
| 病历生成日志 | ✅ 完成 | emr_generation_service.py 生成过程日志 |
| API接口日志 | ✅ 完成 | backend/api/emr.py 请求和响应日志 |
| 时间显示修复 | ✅ 完成 | 后端返回ISO格式，前端正确解析显示 |
| 主程序日志 | ✅ 完成 | backend/main.py 启动日志 |

### 实现详情

1. **日志系统** (`backend/utils/logger.py`)
   - 统一的日志配置
   - 同时输出到控制台和文件
   - 日志文件路径：`data/logs/app_YYYYMMDD.log`
   - 控制台显示INFO级别，文件记录DEBUG级别
   - 格式：`时间 - 模块名 - 级别 - 消息`

2. **流水线日志** (`backend/services/medical_record_pipeline.py`)
   - 记录每个步骤的开始和完成
   - 记录每个步骤的结果数量
   - 记录前5条详细数据（DEBUG级别）
   - 记录错误和异常堆栈

3. **证据选择日志** (`backend/services/evidence_service.py`)
   - 记录查询到的对话轮次数
   - 记录候选证据数量
   - 记录最终返回的证据数量
   - 记录证据字段类型和内容摘要

4. **术语规范化日志** (`backend/services/terminology_service.py`)
   - 记录术语提取过程
   - 记录发现的术语和规范化结果
   - 记录术语类型和数量

5. **病历要素抽取日志** (`backend/services/extraction_service.py`)
   - 记录查询到的证据数量
   - 记录使用的抽取方法（LLM/规则）
   - 记录抽取的字段数量和内容摘要

6. **病历生成日志** (`backend/services/emr_generation_service.py`)
   - 记录查询到的抽取字段数量
   - 记录使用的生成方法（LLM/模板）
   - 记录生成的病历JSON内容
   - 记录病历版本号

7. **API接口日志** (`backend/api/emr.py`)
   - 记录请求参数
   - 记录处理状态
   - 记录错误信息

8. **时间显示修复**
   - 后端：将datetime对象转换为ISO格式字符串（`created_at.isoformat()`）
   - 前端：正确解析ISO格式时间，使用中文本地化显示
   - 格式：`YYYY-MM-DD HH:MM:SS`

### 解决的问题

1. **病历显示"暂无数据"问题**
   - 原因：流水线各阶段没有详细日志，无法定位问题
   - 解决：添加详细日志输出，方便调试和问题定位

2. **时间显示不正确问题**
   - 原因：后端返回datetime对象，前端解析失败
   - 解决：后端统一返回ISO格式字符串，前端正确解析

3. **日志输出问题**
   - 原因：没有统一的日志系统，只有零散的print语句
   - 解决：建立统一的日志系统，所有模块使用logger输出

### 日志示例

```
2026-04-17 10:30:15 - medical_assistant - INFO - 启动 中文门诊病历生成系统 v1.0.0
2026-04-17 10:30:15 - medical_assistant - INFO - 数据库初始化完成
2026-04-17 10:30:20 - medical_assistant - INFO - 收到病历处理请求: visit_id=xxx
2026-04-17 10:30:20 - medical_assistant - INFO - === 开始处理就诊记录: xxx ===
2026-04-17 10:30:20 - medical_assistant - INFO - >>> 步骤1: 证据选择
2026-04-17 10:30:20 - medical_assistant - INFO - 开始规则证据选择，visit_id=xxx
2026-04-17 10:30:20 - medical_assistant - INFO - 查询到 9 条对话轮次
2026-04-17 10:30:20 - medical_assistant - INFO - 找到 10 个候选证据
2026-04-17 10:30:20 - medical_assistant - INFO - 返回 10 条证据
2026-04-17 10:30:20 - medical_assistant - INFO - 证据选择完成，共找到 10 条证据
2026-04-17 10:30:20 - medical_assistant - INFO - >>> 步骤2: 术语规范化
...
```

### 使用方法

```bash
# 启动服务后，日志会自动输出到控制台和文件
uvicorn backend.main:app --reload

# 查看日志文件
tail -f data/logs/app_20260417.log
```

### 后续优化

1. **日志级别配置**：支持通过环境变量配置日志级别
2. **日志轮转**：支持日志文件按大小或时间轮转
3. **结构化日志**：支持JSON格式日志，方便日志分析
4. **性能监控**：记录各阶段处理时间，方便性能优化

---

## 2026-04-21 基于LLM的病历质量评估系统

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 评估记录模型 | ✅ 完成 | 创建EvaluationRecord模型存储评估结果 |
| 评估提示词模板 | ✅ 完成 | 添加6个结构化评估提示词 |
| 评估器基类 | ✅ 完成 | 提供LLM调用和JSON解析通用功能 |
| 一致性评估服务 | ✅ 完成 | 评估事实支持率和内部一致性 |
| 完整性评估服务 | ✅ 完成 | 评估关键事实召回率 |
| 文档质量评估服务 | ✅ 完成 | 评估五维度文档质量 |
| 安全风险评估服务 | ✅ 完成 | 检测高风险错误 |
| 评估流水线 | ✅ 完成 | 协调四层评估流程 |
| 评估API路由 | ✅ 完成 | 提供5个REST API端点 |

### 新增文件

1. **backend/models/evaluation_record.py**
   - `EvaluationRecord` 评估记录模型
   - 存储四层评估结果和综合得分

2. **backend/services/evaluation/__init__.py**
   - 评估模块入口
   - 导出所有评估服务类

3. **backend/services/evaluation/base.py**
   - `BaseEvaluator` 评估器基类
   - 提供LLM调用、JSON解析、病历格式化等通用功能

4. **backend/services/evaluation/consistency.py**
   - `ConsistencyEvaluator` 一致性评估服务
   - 评估事实支持率、幻觉率、内部一致性

5. **backend/services/evaluation/completeness.py**
   - `CompletenessEvaluator` 完整性评估服务
   - 提取关键事实清单，计算召回率

6. **backend/services/evaluation/quality.py**
   - `QualityEvaluator` 文档质量评估服务
   - 评估结构完整性、组织清晰度、表达简洁性、可理解性、术语规范性

7. **backend/services/evaluation/safety.py**
   - `SafetyEvaluator` 安全风险评估服务
   - 检测重大幻觉、重大遗漏、否定反转等高风险错误

8. **backend/services/evaluation/evaluation_pipeline.py**
   - `EvaluationPipeline` 评估流水线
   - 协调四层评估，计算综合得分，保存评估结果

9. **backend/api/evaluation.py**
   - 评估API路由
   - 提供5个REST API端点

### 修改文件

1. **backend/models/emr_record.py**
   - 添加 `evaluations` 关系

2. **backend/models/__init__.py**
   - 导出 `EvaluationRecord`

3. **backend/services/llm/prompts.py**
   - 添加6个评估提示词模板：
     - `consistency_check`：一致性评估
     - `internal_consistency_check`：内部一致性检查
     - `key_fact_extraction`：关键事实提取
     - `completeness_check`：完整性评估
     - `document_quality_check`：文档质量评估
     - `safety_risk_check`：安全风险评估

4. **backend/api/__init__.py**
   - 导出 `evaluation_router`

5. **backend/main.py**
   - 注册 `evaluation_router`

### 评估层级结构

```
第一层：一致性评估 (Consistency)
├── 事实支持率
├── 幻觉率
└── 内部一致性

第二层：完整性评估 (Completeness)
├── 关键事实召回率
└── 加权遗漏率

第三层：文档质量评估 (Quality)
├── 结构完整性 (0-2分)
├── 组织清晰度 (0-2分)
├── 表达简洁性 (0-2分)
├── 可理解性 (0-2分)
└── 术语规范性 (0-2分)

第四层：安全风险评估 (Safety)
├── 重大幻觉检测
├── 重大遗漏检测
├── 否定反转检测
├── 部位侧别错误检测
├── 时间错误检测
└── 章节错放检测
```

### API端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/evaluation/evaluate` | POST | 评估单份病历 |
| `/api/evaluation/batch` | POST | 批量评估病历 |
| `/api/evaluation/result/{id}` | GET | 获取评估结果 |
| `/api/evaluation/list/{record_id}` | GET | 获取病历的评估历史 |
| `/api/evaluation/statistics` | GET | 获取评估统计数据 |

### 综合得分计算

```
综合得分 = 0.35 × 一致性 × 内部一致性
         + 0.30 × 完整性召回率
         + 0.20 × 文档质量得分
         - 安全扣分
```

### 设计原则

| 原则 | 说明 |
|------|------|
| 结构化二值判断 | 所有评估问题设计为"是/否"或有限选项 |
| 对话为证据源 | 所有判断基于原始对话，而非参考病历 |
| 分层独立评估 | 四层评估独立进行，每层输出结构化结果 |
| 可追溯性 | 每个判断结果附带LLM的推理过程和证据文本 |

### 数据库迁移

数据库使用自动迁移机制，启动服务时会自动创建 `evaluation_records` 表。

已更新 `backend/database.py` 的 `init_db()` 函数，包含 `EvaluationRecord` 模型。

---

## 2026-04-22 前端评估展示

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 评估页面HTML | ✅ 完成 | 创建evaluation.html评估结果展示页面 |
| 评估页面JS | ✅ 完成 | 创建evaluation.js处理评估逻辑 |
| 评估样式CSS | ✅ 完成 | 添加评估相关样式 |
| 病历页面集成 | ✅ 完成 | 在emr.html添加评估按钮 |
| API返回record_id | ✅ 完成 | 更新status API返回latest_record_id |

### 新增文件

1. **frontend/evaluation.html**
   - 评估结果展示页面
   - 包含综合得分、四层评估详情展示

2. **frontend/js/evaluation.js**
   - 评估页面交互逻辑
   - 处理评估结果展示、标签切换

### 修改文件

1. **frontend/css/style.css**
   - 添加评估相关样式（评分圆环、进度条、标签页等）
   - 添加btn-info按钮样式

2. **frontend/emr.html**
   - 添加"质量评估"按钮

3. **frontend/js/emr.js**
   - 添加evaluateBtn按钮引用和事件处理
   - 添加currentRecordId变量存储当前病历ID
   - 在病历生成成功后显示评估按钮

4. **backend/database.py**
   - 在init_db()中添加EvaluationRecord模型

5. **backend/services/medical_record_pipeline.py**
   - get_processing_status()返回latest_record_id

### 前端功能

**评估概览**：

- 综合得分圆环显示（颜色区分：绿色/橙色/红色）
- 一致性、完整性、文档质量进度条
- 安全风险状态指示

**四层评估详情**：

- 一致性评估：事实支持列表、内部矛盾检测
- 完整性评估：关键事实覆盖情况
- 文档质量：五维度评分
- 安全风险：高风险问题列表

### 页面导航流程

```
病历页面 (emr.html)
    ↓ 点击"质量评估"
评估页面 (evaluation.html)
    ↓ 显示评估结果
    ↓ 点击"返回病历"
病历页面 (emr.html)
```

---

## 2026-04-22 评估页面调试模式

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 调试按钮 | ✅ 完成 | 在评估页面添加调试模式按钮 |
| 调试模态框 | ✅ 完成 | 添加调试模态框HTML |
| 调试API | ✅ 完成 | 添加调试阶段获取和处理API |
| 调试JS逻辑 | ✅ 完成 | 添加调试交互逻辑 |

### 修改文件

1. **frontend/evaluation.html**
   - 添加"调试模式"按钮
   - 添加调试模态框

2. **frontend/js/evaluation.js**
   - 添加调试模式事件处理
   - 添加阶段选择和提交逻辑

3. **backend/api/evaluation.py**
   - 添加 `GET /api/evaluation/debug/prompts/{record_id}` 获取调试阶段
   - 添加 `POST /api/evaluation/debug/process-stage` 处理调试阶段

### 调试阶段

评估调试模式包含6个阶段：

| 阶段 | 说明 |
|------|------|
| consistency | 一致性评估 - 事实支持检查 |
| internal_consistency | 一致性评估 - 内部一致性检查 |
| key_fact_extraction | 完整性评估 - 关键事实提取 |
| completeness | 完整性评估 - 覆盖情况检查 |
| quality | 文档质量评估 |
| safety | 安全风险评估 |

### 使用方法

1. 在评估页面点击"调试模式"按钮
2. 选择要处理的阶段
3. 复制提示词到大模型获取响应
4. 将大模型返回的JSON粘贴到输入框
5. 点击"提交并继续"处理下一阶段
6. 完成所有阶段后自动保存评估结果

### 修复记录

**2026-04-22 修复前端字段名不匹配问题**

问题：前端期望的字段名与大模型返回的字段名不一致，导致显示 undefined 或 0。

修复内容：

| 模块 | 前端期望字段 | 大模型返回字段 | 修复方式 |
|------|-------------|---------------|---------|
| 一致性评估 | `fact.supported` | `fact.is_supported` | 兼容两种字段名 |
| 一致性评估 | `fact.fact_text` | `fact.fact` | 兼容两种字段名 |
| 一致性评估 | `fact.evidence` | `fact.evidence_text` | 兼容两种字段名 |
| 完整性评估 | `key_facts` | `coverage` | 兼容两种字段名 |
| 完整性评估 | `fact.coverage` | `fact.coverage_status` | 兼容两种字段名 |
| 完整性评估 | `fact.emr_content` | `fact.emr_text` | 兼容两种字段名 |
| 文档质量 | `scores.structure` | `scores.structure_completeness` | 兼容两种字段名 |
| 文档质量 | `score` (数字) | `score` (对象) | 处理对象格式 |
| 安全风险 | `risk.type` | `risk.risk_type` | 兼容两种字段名 |
| 安全风险 | `risk.original_text` | `risk.emr_content` | 兼容两种字段名 |
| 安全风险 | `risk.suggestion` | `risk.correct_content` | 兼容两种字段名 |

**2026-04-22 修复调试模式保存错误**

问题：调试模式保存评估结果时，`quality_result` 被错误地赋值为安全风险评估结果。

修复：在 `backend/api/evaluation.py` 的 `process_debug_stage` 函数中，将 `quality_result = result` 改为 `quality_result = request.context.get("quality_result", {})`。

影响：之前通过调试模式保存的评估结果中，文档质量数据被安全风险数据覆盖。需要重新运行调试模式以保存正确的评估结果。
