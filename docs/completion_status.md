# 完成状态记录

## 2026-05-27 JSON解析失败时停止后续执行并输出LLM响应

### 问题背景

当LLM返回的JSON解析失败时（如 `finish_reason=length` 导致输出被截断），系统继续执行下一阶段，只返回空结果，无法定位错误原因。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 创建 JSONParseError 异常类 | ✅ | 在 `utils.py` 中创建自定义异常类，包含阶段名、原始响应内容、错误信息 |
| 修改 parse_json_response | ✅ | 新增 `raise_on_error` 参数，失败时抛出异常而非返回 None |
| 修改 FactExtractionStage | ✅ | JSON解析失败时输出完整LLM响应并抛出异常 |
| 修改 SOAPGenerationStage | ✅ | SO生成和AP合并生成阶段添加异常处理 |
| 修改 orchestrator.py | ✅ | `process_transcript` 和 `process_with_callback` 方法捕获异常并停止后续执行 |

### 修改文件

- `backend/services/pipeline/utils.py` — 新增 `JSONParseError` 异常类，`parse_json_response` 新增 `raise_on_error` 参数
- `backend/services/pipeline/stages/fact_extraction.py` — JSON解析失败时输出完整响应并抛出异常
- `backend/services/pipeline/stages/soap_generation.py` — SO/AP生成阶段添加异常处理
- `backend/services/pipeline/orchestrator.py` — 阶段2和阶段4添加异常捕获，返回包含 `llm_response` 的错误结果

### 行为变更

**之前**：JSON解析失败 → 返回空结果 → 继续执行下一阶段

**现在**：JSON解析失败 → 输出完整LLM响应到日志 → 抛出异常 → 停止后续执行 → 返回包含 `llm_response` 的错误结果

---

## 2026-05-23 修复 A/P 证据溯源丢失 —— JSON 嵌套解析 + per-field 兜底

### 根因

DEBUG 日志中 LLM AP 阶段原始输出（[app_20260523.log:L2405](file:///d:/practice/MedicalAssisstant/data/logs/app_20260523.log#L2405)）显示，LLM 将 `assessment_items` / `plan_items` **嵌套在了 `assessment` / `plan` 对象内部**，而非 prompt 要求的顶级字段：

```json
// 错误嵌套：
{ "assessment": { "diagnosis": {...}, "assessment_items": [...] }, "plan": { "plan_items": {...} } }
// 正确格式：
{ "assessment": { "diagnosis": {...} }, "assessment_items": [...], "plan": {...}, "plan_items": {...} }
```

导致 `result.get("assessment_items", [])` 返回 `[]`，A/P 证据溯源永久为空。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 定位根因 | ✅ | 通过 DEBUG 日志捕获大模型原始 AP 输出，确认嵌套问题 |
| 修复 soap_generation.py 解析 | ✅ | 合并/分离两种模式下，`assessment_items`/`plan_items` 在顶层为空时回退到从 `assessment`/`plan` 对象内读取 |
| 修复 evidence_enricher.py | ✅ | A/P 证据优先读取 LLM 输出的 per-field `diagnosis.evidence_traces` / `treatment.evidence_traces` / `advice.evidence_traces`，空时回退到 `assessment_items` / `plan_items` |
| 验证 | ✅ | 测试对话：diagnosis traces=2，treatment traces=3，advice traces=2 |

### 修改文件

- `backend/services/pipeline/stages/soap_generation.py` — 合并/分离模式均新增嵌套回退解析
- `backend/services/pipeline/evidence_enricher.py` — A/P 新增 LLM per-field evidence_traces 优先读取，assessment_items/plan_items 为回退

---

## 2026-05-23 LLMPipelineService 完整重构 —— SOLID 原则拆分

### 变更说明

将 4471 行的 God Class `LLMPipelineService` 按 SOLID 原则（单一职责、开闭原则）拆分为 15 个独立模块。

- `LLMPipelineService` 变为 38 行**向后兼容包装类**，全部逻辑委托给 `PipelineOrchestrator`
- 外部 API（`api/emr.py`、`llm_pipeline_service_en.py`、`services/__init__.py`）**零修改**

### 重构前后对比

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| 文件数 | 1 | 15 (1 包装 + 1 编排 + 7 基础设施 + 6 Stage) |
| 核心类行数 | 4471 | 38 (包装) + 531 (编排) |
| 净删除行数 | — | ~3900 |
| 类中方法数 | 80+ | 12 (编排) + 4 (包装) |
| SOLID 合规 | SRP 违反（God Class） | SRP/OCP 合规 |

### 新增模块清单

`backend/services/pipeline/` 目录新增 14 个文件：

| 目录 | 文件 | 职责 |
|------|------|------|
| `pipeline/` | `__init__.py` | 模块入口 |
| `pipeline/` | `base.py` | `PipelineContext` 数据传递对象 + `PipelineStage` 抽象接口 |
| `pipeline/` | `utils.py` | JSON 解析工具函数 |
| `pipeline/` | `speaker_handler.py` | 说话人角色处理 |
| `pipeline/` | `debug_interactor.py` | Debug 交互器 |
| `pipeline/` | `evidence_enricher.py` | 证据溯源富化器 |
| `pipeline/` | `emr_persistence.py` | EMR 持久化服务 |
| `pipeline/` | `interactive.py` | 交互式分步处理服务 |
| `pipeline/` | `orchestrator.py` | Pipeline 编排器（核心） |
| `pipeline/stages/` | `__init__.py` | Stages 子模块入口 |
| `pipeline/stages/` | `turn_cleaning.py` | 阶段1: 转写清洗与角色纠错 |
| `pipeline/stages/` | `fact_extraction.py` | 阶段2: 事实抽取与证据绑定 |
| `pipeline/stages/` | `fact_consolidation.py` | 阶段2.5: 事实收束 |
| `pipeline/stages/` | `term_normalization.py` | 阶段3: 选择性术语规范化 |
| `pipeline/stages/` | `soap_generation.py` | 阶段4: 分节生成 SOAP 病历 |
| `pipeline/stages/` | `verification.py` | 阶段5: 核查与修订 |

### 设计模式

| 模式 | 实现 | 说明 |
|------|------|------|
| Pipeline 模式 | `PipelineStage` 抽象接口 | `execute(ctx: PipelineContext) -> Dict` 统一入口，6 个阶段可独立测试和替换 |
| Context 对象 | `PipelineContext` dataclass | 各阶段间数据传递，避免阶段间直接耦合 |
| 向后兼容包装 | `LLMPipelineService` 包装类 | 所有公共方法委托给 `PipelineOrchestrator`，外部调用方零修改 |
| 依赖注入 | `InteractivePipelineService` | 依赖从 `LLMPipelineService` 改为 `PipelineOrchestrator` |

### 删除内容

- 23 个 DEPRECATED 方法（~1090 行）：`_run_evaluation`, `_build_role_annotation_prompt`, `_parse_role_annotation_response`, `_extract_evidence_traces`, `_fallback_match_turns`, `_normalize_terms_stage_legacy`, `_normalize_terms_serial`, `_normalize_terms_parallel`, `_build_normalization_prompt`, `_parse_normalization_response`, `_extract_fields_stage`, `_build_extraction_prompt`, `_parse_extraction_response`, `_attach_evidence_traces`, `_fallback_extraction`, `_generate_emr_stage`, `_build_emr_generation_prompt`, `_parse_emr_response`, `_attach_evidence_to_emr`, `_legacy_role_annotation_stage`, `_legacy_term_normalization_stage`, `_legacy_field_extraction_stage`, `_legacy_emr_generation_stage`
- 6 个死代码方法（已复制到 Stage 类）

### 修改文件

1. `backend/services/llm_pipeline_service.py` — 重写为 38 行包装类
2. `backend/services/pipeline/orchestrator.py` — 新建，531 行核心编排逻辑
3. `backend/services/pipeline/interactive.py` — 依赖注入从 `LLMPipelineService` 改为 `PipelineOrchestrator`（22 处 `self.lsp.` → `self.orchestrator.`），删除 4 个 `_legacy_*` 路由

### 未修改文件（外部兼容）

- `backend/api/emr.py` — 导入 `LLMPipelineService` 路径不变
- `backend/services/__init__.py` — 导出路径不变
- `backend/services/llm_pipeline_service_en.py` — 导入路径不变

### 架构图

详见 `docs/architecture.md` 中新增的 "Pipeline 模块架构" 章节。

---

## 2026-05-22 LLMPipelineService 重构 Step 6 —— 提取交互式阶段处理到 InteractivePipelineService

### 变更说明

将 `LLMPipelineService` 中的交互式/手动分步处理方法 (`process_stage_with_user_input` 和 `_build_compact_turns`) 提取到独立的 `InteractivePipelineService` 类中，放置于 `pipeline/interactive.py`。LLM Pilepine Service 保留 `process_stage_with_user_input` 作为向后兼容的委托方法。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 创建 `pipeline/interactive.py` | ✅ 完成 | 新建 `InteractivePipelineService` 类，接收 `LLMPipelineService` 实例作为依赖 |
| 提取 `process_stage` 方法 | ✅ 完成 | 将原 LSP 中的分步处理逻辑（turn_cleaning/fact_extraction/emr_generation_so/assessment/plan/verification + 4个legacy阶段路由）完整迁移 |
| 提取 `_build_compact_turns` | ✅ 完成 | 作为静态方法移至 `InteractivePipelineService` |
| LSP 委托 | ✅ 完成 | LSP 的 `process_stage_with_user_input` 委托给 `self.interactive_service.process_stage()` |
| `_build_compact_turns` 从 LSP 移除 | ✅ 完成 | 删除 LSP 中的旧方法，无残留引用 |
| `_legacy_*` 方法保留 | ✅ 完成 | 4个 `_legacy_*` 方法保留在 LSP 中，通过 `self.lsp._legacy_*` 调用 |

### 修改文件

1. `backend/services/pipeline/interactive.py` — 新建，包含 `InteractivePipelineService` 类
2. `backend/services/llm_pipeline_service.py` — 新增 `InteractivePipelineService` 导入；`__init__` 中实例化 `self.interactive_service`；`process_stage_with_user_input` 方法体替换为委托调用；删除 `_build_compact_turns` 方法

---

## 2026-05-22 修复证据溯源字段级分配 —— 以LLM SO阶段输出为准

### 变更说明

日志分析发现：LLM SO 阶段已按字段输出独立的 `evidence_traces`（如 `chief_complaint` → `["fact_...41973dcae321"]`），但 `_enrich_evidence_traces()` 的 subsection 分组逻辑将这些 per-field 分配**覆盖**了。由于 fact_extraction 阶段 LLM 尚未正确输出 `subsection`，导致部分字段（如主诉）证据溯源为空（traces=0）。

修复方案：在 `_enrich_evidence_traces()` 中，**优先使用 LLM SO 阶段的 per-field evidence_traces**，提取每个字段的 fact_ids 后独立调用 `_build_evidence_traces_from_fact_ids()` 进行富化。仅当 LLM 未提供 per-field 数据时，才依次回退到 subsection 分组 → section 级分配。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 根因定位 | ✅ 完成 | 通过 DEBUG 日志捕获 LLM SO 阶段原始输出，确认 LLM 已正确输出 per-field evidence_traces |
| 修复 `_enrich_evidence_traces()` | ✅ 完成 | 新增 `llm_s_field_fact_ids` / `llm_o_field_fact_ids` 提取逻辑，LLM per-field > subsection > section 三级回退 |
| 验证 | ✅ 完成 | 测试 visit `text_20260522_190012_ed7177eb`：主诉 traces=3（原来=0），现病史 traces=8，否认症状 traces=2，体格检查 traces=1，辅助检查 traces=1 |

### 修改文件

- `backend/services/llm_pipeline_service.py` — `_enrich_evidence_traces()` 新增 LLM per-field 证据提取逻辑（优先级高于 subsection 分组）

---

## 2026-05-22 病历生成实时进度显示

### 变更说明

此前病历生成过程只显示"正在生成病历..."，用户等待过程枯燥，无法获知当前处理阶段。本次使用 Server-Sent Events (SSE) 技术实现实时进度推送，让用户在等待过程中能看到各阶段的处理进度。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 后端 SSE 端点 | ✅ 完成 | 新增 `/api/emr/process-stream` 端点，使用 StreamingResponse 返回 SSE 格式数据 |
| 后端进度回调方法 | ✅ 完成 | `LLMPipelineService` 新增 `process_with_callback()` 方法，每个阶段开始/结束时 yield 进度事件 |
| 前端 SSE 接收 | ✅ 完成 | `agent.js` 使用 fetch + ReadableStream 接收 SSE 流，实时更新阶段显示 |
| CSS 进度条动画 | ✅ 完成 | 新增 `.stage-progress-animated` 样式，带渐变动画效果 |
| 网络中断处理 | ✅ 完成 | 当页面刷新导致连接中断时，显示友好提示和"检查病历状态"按钮 |

### 修改文件

1. `backend/api/emr.py` — 新增 `/process-stream` SSE 端点
2. `backend/services/llm_pipeline_service.py` — 新增 `process_with_callback()` 方法
3. `frontend/js/agent.js` — 修改 `processEMR()` 使用 SSE，新增 `handleSSEEvent()`、`updateStageMessage()`、`checkEMRStatus()` 函数
4. `frontend/css/ide.css` — 新增阶段进度条动画样式、warning 消息样式、检查状态按钮样式

### 显示的阶段

| 阶段 | 名称 | 说明 |
|------|------|------|
| 阶段1 | 转写清洗与角色纠错 | 清洗ASR文本，识别医生/患者角色 |
| 阶段2 | 事实抽取与证据绑定 | 从对话中抽取原子临床事实 |
| 阶段2.5 | 事实收束 | 合并重复事实，标记冲突 |
| 阶段3 | 选择性术语规范化 | 规范化医学术语 |
| 阶段4 | 分节生成SOAP病历 | 生成主观/客观/评估/计划部分 |
| 阶段5 | 核查与修订 | 验证病历完整性，修订错误 |

### 网络中断处理

当用户在病历生成过程中刷新页面导致 SSE 连接中断时：

1. 前端检测到网络错误，显示警告消息（黄色边框）
2. 提示用户"后端可能仍在处理中"
3. 提供"检查病历状态"按钮，用户可点击检查病历是否已生成完成

---

## 2026-05-22 原子事实按详细SOAP字段分类 —— 证据溯源字段级独立

### 变更说明

此前所有主观数据字段（主诉/现病史/既往史/否认症状）共享同一份证据溯源列表，前端展开各字段的"证据来源"时内容完全相同。根因是 `AtomicFact` 仅按 `section_candidate`（S/O/A/P）四级分类，`_enrich_evidence_traces()` 将 S 节段所有事实的证据无差别赋给每个主观字段。

本次在 `AtomicFact` 新增 `subsection` 字段，在 `fact_extraction` prompt 中要求 LLM 输出细粒度分类，在 `_enrich_evidence_traces()` 中按 `subsection` 分组构建独立证据列表，实现字段级证据溯源区分。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| prompt 新增 subsection 字段 | ✅ 完成 | `fact_extraction` prompt 新增 `subsection` 字段及取值约束说明，更新输出格式示例 |
| AtomicFact 模型新增字段 | ✅ 完成 | 新增 `subsection = Column(String, nullable=True)`，`init_db()` 通过 `_add_missing_columns()` 自动兼容 |
| 解析并存储 subsection | ✅ 完成 | `_save_atomic_facts()` 读取 `subsection` 并写入 DB，`existing_facts_summary` 包含 `subsection` |
| 证据溯源按字段独立分配 | ✅ 完成 | `_enrich_evidence_traces()` 按 `subsection` 分组 S/O 事实，各字段独立构建 `evidence_traces` |
| 向后兼容 | ✅ 完成 | 通过 `s_has_subsection` / `o_has_subsection` 检测自动回退旧逻辑 |

### 修改文件

1. `backend/models/atomic_fact.py` — 新增 `subsection` 列
2. `backend/services/llm/prompts.py` — `fact_extraction` prompt 模板新增 `subsection` 字段说明
3. `backend/services/llm_pipeline_service.py` — `_save_atomic_facts()` 存储 subsection；`_fact_extraction_stage()` summary 包含 subsection；`_enrich_evidence_traces()` 按 subsection 分组分配证据；日志统计适配新结构

---

## 2026-05-22 事实收束阶段关闭 thinking 模式

### 变更说明

事实收束阶段的任务（合并重复、标记冲突）不需要复杂推理，关闭 thinking 模式以减少 LLM reasoning tokens 开销，降低该阶段耗时约 30-50%。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 关闭 thinking 模式 | ✅ 完成 | `_fact_consolidation_stage` 中 LLM 调用设置 `thinking_enabled=False` |

### 修改文件

1. `backend/services/llm_pipeline_service.py` — `_fact_consolidation_stage` 方法中 LLM 调用添加 `thinking_enabled=False` 参数，日志从"thinking模式已启用"改为"thinking模式已禁用"

---

## 2026-05-22 病历显示清晰度优化与证据来源折叠

### 变更说明

病历生成页面的字段名和字段值字体偏小、视觉区分度不足；证据溯源信息嵌入在每个字段下方，多条证据叠加后占据大量页面空间。本次优化增大字段字体、增加左侧色条区分字段，并将证据溯源默认折叠为紧凑按钮。

同时修复：历史病历加载时证据溯源未折叠（`editor.js` 有独立实现未同步修改）、病历 `text` 字段与子字段内容重复显示。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 字段样式增强 | ✅ 完成 | .field-name 字体 11→12px，颜色改为 #9cdcfe，增加 letter-spacing；.field-value 字体 13→14px，增加 line-height |
| 字段区域区分 | ✅ 完成 | .field-item 增加 border-left: 3px solid #569cd6 左侧色条，padding 增大至 10px 14px |
| 证据溯源折叠 | ✅ 完成 | .evidence-traces 默认 collapsed，仅显示"证据来源 (N条)"按钮，点击展开/收起 |
| 折叠按钮样式 | ✅ 完成 | 新增 .evidence-toggle-btn 样式，hover 高亮，展开/收起时前缀 ± 切换 |
| JS 交互（emr.js） | ✅ 完成 | buildEvidenceHtml 添加 collapsed 类和折叠按钮，addExpandListeners 新增证据折叠事件 |
| JS 交互（editor.js） | ✅ 完成 | 同步修改 editor.js 的 buildEvidenceHtml 和 addExpandListeners，修复历史病历加载时证据未折叠 |
| 病历内容去重 | ✅ 完成 | displaySection 当存在结构化子字段时不再显示 text（叙述性文本），避免重复显示 |

### 修改文件

1. `frontend/css/ide.css` — 增强 .field-item/.field-name/.field-value 样式；新增 .evidence-toggle-btn 样式；调整 .evidence-traces 折叠相关样式；覆盖 style.css 级联样式
2. `frontend/js/emr.js` — buildEvidenceHtml 添加 collapsed 类和折叠按钮；addExpandListeners 新增证据折叠事件；displaySection 去除重复 text
3. `frontend/js/editor.js` — 同步修改：buildEvidenceHtml 折叠、addExpandListeners 折叠事件；displaySection 去除重复 text

---

## 2026-05-21 病历缓存、删除与历史病历功能

### 变更说明

解决页面刷新后病历数据丢失问题，新增 localStorage 缓存机制；新增病历删除功能；新增历史病历查看面板。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 后端 DELETE API | ✅ 完成 | 新增 DELETE /api/emr/record/{visit_id} 和 GET /api/emr/visits 接口 |
| 后端删除服务 | ✅ 完成 | EMRGenerationService 新增 delete_emr_by_version、delete_all_emr、get_all_visits_with_emr |
| 前端缓存模块 | ✅ 完成 | cache.js：localStorage 封装，支持保存/读取/删除/列出缓存 |
| 前端历史面板 | ✅ 完成 | history.js：侧边栏历史病历列表，支持查看和删除操作 |
| HTML 模板更新 | ✅ 完成 | 新增 history 活动栏按钮（Ctrl+5）、历史面板、删除版本按钮 |
| CSS 样式更新 | ✅ 完成 | 新增 .history-* 系列样式、.editor-btn-danger、.sidebar-header-refresh |
| app.js 集成 | ✅ 完成 | 新增 Ctrl+5 快捷键、页面初始化时从缓存恢复病历数据 |
| agent.js 集成 | ✅ 完成 | 病历生成成功后自动写入 localStorage 缓存 |
| editor.js 集成 | ✅ 完成 | 版本加载/保存后更新缓存、新增 deleteCurrentVersion 删除功能 |

### 新增文件

1. `frontend/js/cache.js` — localStorage 缓存管理模块（读写删除索引管理）
2. `frontend/js/history.js` — 历史病历面板模块（列表渲染、查看、删除）

### 修改文件

1. `backend/api/emr.py` — 新增 DELETE /record/{visit_id}、GET /visits 两个接口
2. `backend/services/emr_generation_service.py` — 新增删除和列表查询方法
3. `frontend/emr.html` — 新增历史面板 HTML、活动栏按钮、删除版本按钮、JS 引入
4. `frontend/css/ide.css` — 新增历史列表、删除按钮、刷新按钮样式
5. `frontend/js/app.js` — 集成 history 面板、Ctrl+5 快捷键、缓存恢复
6. `frontend/js/agent.js` — 病历生成后调用 CacheModule 写缓存
7. `frontend/js/editor.js` — 加载/保存后更新缓存、新增 deleteCurrentVersion

### 缓存设计

```
缓存键: emr_cache_{visit_id}
缓存索引: emr_cache_index（维护访问顺序，最多100个条目）
缓存内容: { emrRecord, versions, visitInfo, cachedAt }

数据流向:
  后端 API → 前端内存 (运行时) ──→ 写入 localStorage (持久化)
  页面刷新 → localStorage 读取 → 前端内存恢复
  删除操作 → 后端 API + localStorage 同步清除
```

### API 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| DELETE | /api/emr/record/{visit_id} | 删除所有病历（无 version 参数）|
| DELETE | /api/emr/record/{visit_id}?version=N | 删除指定版本 |
| GET | /api/emr/visits | 列出所有有 EMR 的就诊 |

---

## 2026-05-21 IDE界面图标统一：去除Emoji，统一为SVG

### 变更说明

将IDE界面及评估页面中所有emoji图标替换为统一的lucide SVG图标，确保界面风格一致。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| app.js添加icon()函数 | ✅ 完成 | 添加App.icon(name, size)统一图标辅助函数，支持18种图标 |
| emr.html emoji替换 | ✅ 完成 | 标题栏、按钮、消息图标、关闭按钮等12处emoji替换为inline SVG |
| agent.js emoji替换 | ✅ 完成 | 消息图标、阶段状态、按钮文字等21处emoji替换为App.icon()调用 |
| editor.js emoji替换 | ✅ 完成 | 证据溯源按钮2处emoji替换为App.icon()调用 |
| evaluation.js emoji替换 | ✅ 完成 | 添加本地evalIcon()辅助函数，替换事实状态、覆盖率、安全图标等7处 |
| ide.css样式更新 | ✅ 完成 | 按钮SVG对齐样式、icon-spin旋转动画 |

### 修改文件

1. `frontend/js/app.js` — 添加 `App.icon()` 图标辅助函数
2. `frontend/emr.html` — 所有emoji替换为inline SVG
3. `frontend/js/agent.js` — 所有emoji替换为App.icon()调用
4. `frontend/js/editor.js` — 按钮文字emoji替换
5. `frontend/js/evaluation.js` — 添加本地图标函数，替换emoji
6. `frontend/css/ide.css` — 新增按钮SVG图标对齐样式、旋转动画
7. `docs/completion_status.md` — 本文件

### 图标映射

| 旧emoji | 新SVG | 用途 |
|---------|-------|------|
| ⚕ | stethoscope | 医疗/系统图标 |
| 🖨 | printer | 打印按钮 |
| 📊 | barChart | 评估按钮 |
| ⚡✨ | sparkles | 生成/魔法 |
| 🤖 | bot | Agent/机器人 |
| 👤 | user | 用户 |
| 📝✏ | pencil | 编辑/文本调试 |
| 💾 | save | 保存 |
| 📎 | paperclip | 证据溯源 |
| ⬆ | upload | 上传 |
| 🎤 | mic | 语音转写 |
| ✅✓ | checkCircle | 成功/完成 |
| ❌✗ | xCircle/x | 失败/错误 |
| ⏳ | loader | 加载中(带旋转动画) |
| ⏸ | circlePause | 暂停 |
| 🔄 | refreshCw | 重试/刷新 |
| ⚠ | alertTriangle | 警告 |

---

## 2026-05-21 前端重构：VS Code IDE风格界面

### 变更说明

将前端多页面架构重构为 VS Code 风格的 IDE 单页应用界面。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| IDE布局HTML | ✅ 完成 | 重写 emr.html，使用CSS Grid实现三栏IDE布局 |
| IDE布局CSS | ✅ 完成 | 新增 ide.css，VS Code暗色主题，Grid布局样式 |
| 主控制器 | ✅ 完成 | app.js：全局状态管理、活动栏切换、事件总线、状态栏 |
| Agent侧边栏 | ✅ 完成 | agent.js：对话式消息展示、音频上传、ASR转写流程、病历生成流程 |
| 病历编辑器 | ✅ 完成 | editor.js：SOAP四部分折叠面板、编辑/保存、版本切换、证据溯源、打印 |
| 调试侧边栏 | ✅ 完成 | debug.js：LLM多阶段调试面板（从模态框迁移到侧边栏） |
| 配置侧边栏 | ✅ 完成 | config-sidebar.js：LLM配置表单和配置列表管理 |
| 文本调试模式 | ✅ 完成 | 保留在IDE界面的模态框中 |

### 新增/修改文件

**新增文件**：

1. `frontend/css/ide.css` — IDE布局专用样式（VS Code暗色主题）
2. `frontend/js/app.js` — IDE主控制器
3. `frontend/js/agent.js` — Agent侧边栏模块
4. `frontend/js/editor.js` — 病历编辑器模块
5. `frontend/js/debug.js` — 调试侧边栏模块
6. `frontend/js/config-sidebar.js` — 配置侧边栏模块

**修改文件**：

1. `frontend/emr.html` — 重写为IDE布局页面
2. `docs/architecture.md` — 更新前端界面章节
3. `docs/completion_status.md` — 本文件

**保留不变**：

- `frontend/index.html` / `frontend/result.html` / `frontend/evaluation.html` / `frontend/config.html`
- `frontend/css/style.css` — 保留原有样式
- `frontend/js/upload.js` / `frontend/js/result.js` / `frontend/js/evaluation.js` / `frontend/js/config.js`
- 所有后端 API

### IDE 布局结构

```
Activity Bar (48px) | Sidebar (340px) | Editor Area (flex)
     4 icons        | Agent/Debug/    | SOAP病历 + 工具栏
                    | Config panels   |
```

### 键盘快捷键

- Ctrl+1: 切换到病历编辑器
- Ctrl+2: 切换到 Agent 助手
- Ctrl+3: 切换到调试模式
- Ctrl+4: 切换到大模型配置

---

## 2026-05-21 BugFix: 并行处理时LLM配置线程安全与fallback结果丢失

### 问题描述

1. **LLM调用失败**：`float() argument must be a string or a real number, not 'NoneType'`
2. **turn丢失**：实际有32个turn，但只处理了22个

### 问题分析

**问题1：线程安全问题**
- 并行处理时，多个线程共享同一个`llm_service`实例
- 数据库session不是线程安全的，导致某些线程的config查询返回None
- `float(config.temperature)`失败，因为config为None

**问题2：fallback结果格式不一致**
- 正常处理返回：`{"turns": [...], "role_mapping": {...}}`
- fallback返回：`{"role_mapping": {...}, "annotated_text": "..."}`
- fallback没有返回`turns`字段，导致这些turn被丢失

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| LLMService添加配置缓存 | ✅ 完成 | 使用`adapter_configs`缓存配置，避免每次查询数据库 |
| LLMService添加线程锁 | ✅ 完成 | 使用`threading.Lock`保护数据库查询 |
| 修复fallback返回格式 | ✅ 完成 | 返回与正常处理一致的`{"turns": [...], "role_mapping": {...}}`格式 |

### 修改文件

1. **backend/services/llm/llm_service.py**
   - 添加`adapter_configs`缓存配置信息
   - 添加`threading.Lock`保护数据库查询
   - `generate()`方法使用缓存配置而非每次查询数据库

2. **backend/services/llm_pipeline_service.py**
   - `_fallback_role_annotation()`返回与正常处理一致的格式
   - 包含`turns`字段，确保所有turn都被正确处理

---

## 2026-05-20 性能优化：大模型Thinking模式选择性启用

### 问题描述

病历处理总耗时仍较长（约225秒），日志分析发现大模型thinking模式是主要瓶颈：
- 每次LLM调用都启用thinking模式
- 事实收束阶段reasoning_tokens达3729，thinking内容7787字符
- 核查修订阶段重写整份SOAP，工作量过大

### 问题分析

| 阶段 | thinking模式 | 问题 |
|------|-------------|------|
| 转写清洗 | 启用 | 简单模式匹配任务，不需要复杂推理 |
| 事实抽取 | 启用 | 结构化抽取任务，不需要复杂推理 |
| 事实收束 | 启用 | 需要冲突判断，保留thinking |
| SO生成 | 启用 | 结构化生成任务，不需要复杂推理 |
| AP生成 | 启用 | 需要诊断推断，保留thinking |
| 核查修订 | 启用 | 重写整份SOAP，工作量过大 |

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 转写清洗阶段禁用thinking | ✅ 完成 | 添加`thinking_enabled=False` |
| 事实抽取阶段禁用thinking | ✅ 完成 | 添加`thinking_enabled=False` |
| 字段抽取阶段禁用thinking | ✅ 完成 | 添加`thinking_enabled=False` |
| SO生成阶段禁用thinking | ✅ 完成 | 添加`thinking_enabled=False` |
| 简化核查修订提示词 | ✅ 完成 | 改为定向核查，先输出问题清单 |
| 简化事实收束提示词 | ✅ 完成 | 移除补判逻辑，仅合并重复和标记冲突 |
| 新增Thinking配置项 | ✅ 完成 | `LLM_THINKING_ENABLED`和`LLM_THINKING_STAGES` |

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 转写清洗、事实抽取、字段抽取、SO生成阶段添加`thinking_enabled=False`
   - 各阶段添加thinking模式日志记录

2. **backend/services/llm/prompts.py**
   - `soap_verification`：简化为定向核查，最多5个问题，仅修订有问题的字段
   - `fact_consolidation`：移除补判逻辑，仅合并重复和标记冲突

3. **backend/config.py**
   - 新增`LLM_THINKING_ENABLED`：全局thinking开关
   - 新增`LLM_THINKING_STAGES`：指定启用thinking的阶段列表

### 预期效果

| 指标 | 优化前 | 优化后目标 | 提升 |
|------|--------|------------|------|
| 简单任务推理时间 | 20-60秒 | 5-15秒 | 70-75% |
| 核查修订工作量 | 重写整份SOAP | 仅修订问题字段 | 50-70% |
| 总耗时 | 225秒 | 120-150秒 | 33-47% |

---

## 2026-05-20 BugFix: turn_id索引匹配与max_tokens不足

### 问题描述

1. **turn_id不在segment索引中**：LLM返回的turn_id与数据库中的turn_index匹配失败
2. **无法从响应中提取有效JSON**：思考模式下reasoning_tokens消耗大量token（如13383），导致输出被截断，JSON不完整
3. **'NoneType' object has no attribute 'max_tokens'**：LLM配置查询返回None

### 问题分析

**问题1：turn_id匹配失败（根本原因）**
- 输入格式：`[#30] [spk0]: 对话内容` - 使用数据库中的`turn_index`（如30, 31）
- Prompt示例：`"turn_id": 0` - 示例中使用0，LLM理解为位置索引
- LLM输出：`turn_id: 0, 1` - LLM按示例返回位置索引
- 匹配失败：`turn_by_index`的keys是`[30, 31]`，找不到0, 1
- **解决方案**：修改prompt模板，明确告诉LLM使用`[#N]`中的N作为turn_id

**问题2：max_tokens不足**
- 默认max_tokens=2048，思考模式下乘以3=6144
- 实际reasoning_tokens消耗13383，远超可用空间
- 导致`finish_reason=length`，JSON输出被截断

**问题3：LLM配置查询返回None**
- 数据库中可能没有对应的配置记录
- 或配置的is_active=False

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 修复prompt模板turn_id说明 | ✅ 完成 | 明确告诉LLM使用`[#N]`中的N作为turn_id |
| 添加LLM配置查询详细日志 | ✅ 完成 | 显示数据库中所有配置，帮助定位问题 |
| 添加turn_id匹配详细日志 | ✅ 完成 | 显示segment详情、turn_index列表、匹配过程 |
| 增大max_tokens默认值 | ✅ 完成 | 从2048改为8192 |
| 增大思考模式倍数 | ✅ 完成 | 从3倍改为5倍 |

### 修改文件

1. **backend/services/llm/prompts.py**
   - `turn_cleaning`模板：添加说明"turn_id必须使用对话中的[#N]编号"
   - 示例改为`"turn_id": 30`而非`"turn_id": 0`

2. **backend/services/llm/llm_service.py**
   - `generate()`: 添加详细日志，显示数据库中所有配置
   - 当config为None时，列出所有可用配置帮助定位问题

3. **backend/services/llm_pipeline_service.py**
   - `_parse_cleaning_response()`: 使用`turn_by_index.get(turn_id)`匹配
   - `_apply_asr_corrections()`: 同样使用turn_by_index匹配
   - 添加详细日志：segment详情、turn_index列表、匹配过程

4. **backend/models/llm_config.py**
   - `max_tokens`默认值从2048改为8192

5. **backend/services/llm/openai_compatible_adapter.py**
   - 思考模式下max_tokens倍数从3改为5

### 注意事项

数据库中已有的LLM配置记录不会自动更新max_tokens值。需要手动更新：

```sql
UPDATE llm_configs SET max_tokens = 8192 WHERE max_tokens = 2048;
```

或在配置页面重新设置max_tokens。

---

## 2026-05-20 性能优化：段落处理并行化与阶段延迟减少

### 变更内容

针对病历处理时间过长的问题（总耗时约272-281秒），实施两项核心优化：**段落处理并行化**和**减少阶段间延迟**。

### 问题分析

从日志分析，病历处理主要耗时分布：

| 阶段 | 耗时范围 | 占比 | 瓶颈原因 |
|------|----------|------|----------|
| 段落处理(turn_cleaning) | 81-144秒 | 30-52% | 串行LLM调用，每段约20-36秒 |
| 阶段间延迟 | 15秒 | 5% | STAGE_DELAY=3秒×5次 |

**根因**：
1. 段落处理串行执行，32个turn分成4个段落，每个段落需要一次LLM调用
2. 阶段间延迟原本是为了避免API限流，但现代LLM API通常不需要

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增_process_segments_parallel()方法 | ✅ 完成 | 使用ThreadPoolExecutor并行处理段落 |
| 修改process_transcript()使用并行处理 | ✅ 完成 | 替代原有串行处理逻辑 |
| 添加MAX_PARALLEL_SEGMENTS配置 | ✅ 完成 | 限制最大并行数，默认4 |
| 减少STAGE_DELAY | ✅ 完成 | 从3秒降至0.5秒 |
| 添加性能监控日志 | ✅ 完成 | 记录并行处理耗时 |

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 新增`MAX_PARALLEL_SEGMENTS = 4`类变量
   - 修改`STAGE_DELAY`从3.0降至0.5
   - 新增`_process_segments_parallel()`方法：使用线程池并行处理段落
   - 修改`process_transcript()`：使用并行处理替代串行处理

### 预期效果

| 指标 | 优化前 | 优化后目标 | 提升 |
|------|--------|------------|------|
| 段落处理耗时 | 81-144秒 | 30-50秒 | 60-70% |
| 阶段延迟 | 15秒 | 2.5秒 | 83% |
| 总耗时 | 272-281秒 | 150-180秒 | 35-45% |

### 技术实现

**并行处理架构**：

```
段落1 ──┐
段落2 ──┼── ThreadPoolExecutor(max_workers=4) ── 合并结果
段落3 ──┤
段落4 ──┘
```

**关键设计**：
1. 使用`ThreadPoolExecutor`实现LLM调用的并行化
2. 限制最大并行数（`MAX_PARALLEL_SEGMENTS=4`），避免API限流
3. 保留串行模式作为fallback（调试模式自动切换）
4. 错误处理：单个段落失败时使用`_fallback_role_annotation()`

---

## 2026-05-20 BugFix: LLM API请求超时修复

### 变更内容

修复事实收束阶段LLM API调用超时问题（`The read operation timed out`）。

### 问题分析

从终端日志分析，事实收束阶段LLM请求耗时约121秒，刚好超过默认的120秒超时：

- 请求开始时间: 15:02:14
- 错误发生时间: 15:04:15
- 总耗时: 约121秒

**根因**：事实收束阶段处理大量事实时，LLM响应时间可能超过默认的120秒超时限制。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| LLMRequest添加timeout参数 | ✅ 完成 | 支持请求级别超时配置 |
| OpenAICompatibleAdapter支持请求级超时 | ✅ 完成 | 优先使用请求级超时，否则使用默认值 |
| LLMService支持传递timeout参数 | ✅ 完成 | generate()方法新增timeout参数 |
| 事实收束阶段使用更长超时 | ✅ 完成 | 设置300秒超时 |

### 修改文件

1. **backend/services/llm/base.py**
   - `LLMRequest`数据类新增`timeout: Optional[float] = None`字段

2. **backend/services/llm/openai_compatible_adapter.py**
   - 修改`generate()`方法，优先使用请求级超时
   - 添加超时设置日志输出

3. **backend/services/llm/llm_service.py**
   - `generate()`方法新增`timeout`参数
   - 将timeout传递给LLMRequest

4. **backend/services/llm_pipeline_service.py**
   - `_fact_consolidation_stage()`调用generate时传入`timeout=300.0`

### 超时策略

| 场景 | 默认超时 | 说明 |
|------|----------|------|
| 普通请求 | 120秒 | 默认值 |
| thinking模式 | 300秒 | 需要更长推理时间 |
| 事实收束阶段 | 300秒 | 处理大量事实需要更长时间 |

## 2026-05-20 术语规范化性能优化

### 变更内容

针对术语规范化阶段处理时间过长的问题（单个术语约14秒，25个术语约350秒），实施三项优化措施：**智能跳过策略**、**批量LLM调用**、**结果缓存机制**。

### 问题分析

从终端日志分析，处理单个术语"脖子处淋巴结肿大"耗时约14秒：

- 第一次LLM调用（rewrite）：约9秒
- 第二次LLM调用（alternative phrasing）：约5秒
- 最终结果：unresolved（未解决）

**根因**：串行处理架构 + 多次LLM调用 + 无效调用未被跳过

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| P0: 智能跳过策略 | ✅ 完成 | 当rewrite无变化时跳过alternative phrasing，减少50%无效调用 |
| P1: 批量LLM调用 | ✅ 完成 | 新增`batch_rewrite_colloquial()`方法，25个术语从25次调用减少到1次 |
| P1: 批量规范化 | ✅ 完成 | 新增`batch_normalize_terms()`方法，`_normalize_terms_stage`支持批量模式 |
| P2: 结果缓存机制 | ✅ 完成 | 添加术语规范化结果缓存，避免重复计算 |

### 修改文件

1. **backend/services/terminology_service.py**
   - 新增类变量 `_normalization_cache` 和 `_cache_max_size`
   - 新增 `_get_cache_key()`、`_get_from_cache()`、`_save_to_cache()` 缓存方法
   - 修改 `normalize_single_term()` 添加缓存检查和写入
   - 新增 `batch_normalize_terms()` 批量规范化方法
   - 修改 `normalize_term()` 添加 `rewrite_produced_new_terms` 标志，智能跳过alternative phrasing

2. **backend/services/term_rewriter.py**
   - 新增 `batch_rewrite_colloquial()` 批量重写方法
   - 新增 `_build_batch_rewrite_prompt()` 批量提示词构建
   - 新增 `_parse_batch_rewrite_response()` 批量响应解析

3. **backend/services/llm_pipeline_service.py**
   - 修改 `_normalize_terms_stage()` 支持 `use_batch` 参数
   - 批量模式下使用 `batch_normalize_terms()` 替代串行调用

### 预期效果

| 指标 | 优化前 | 优化后目标 |
|------|--------|------------|
| 单术语平均耗时 | 14秒 | <2秒 |
| 25术语总耗时 | 350秒 | <50秒 |
| LLM调用次数 | 50次 | <5次 |

### 配置项

无需新增配置项，批量模式默认启用（`use_batch=True`）。

## 2026-05-19 术语规范化优化：引入Rewrite阶段与约束选择

### 变更内容

依据《口语术语规范化模块设计》文档，重构术语规范化核心流程，引入 **Rewrite 阶段**、**多概念拆解**、**约束选择** 和 **置信度驱动的选择性触发**，同时修正中英文路径分流问题。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增 TermRewriter 模块 | ✅ 完成 | `backend/services/term_rewriter.py`，封装口语改写、多概念拆解、alternative phrasing |
| 新增 ConstrainedTermSelector | ✅ 完成 | 约束LLM只能从候选列表中选择，禁止自由生成术语 |
| 重构 normalize_term() | ✅ 完成 | 引入分级触发链路：exact/alias预检 → 多概念拆解 → 语言分流检索 → rewrite → alt phrasing → 约束选择 → unresolved |
| 修复并行模式语言分流 | ✅ 完成 | `extract_and_normalize_terms_parallel()` 中文走本地术语库，英文走UMLS |
| 修改 _normalize_by_llm() | ✅ 完成 | 降低LLM兜底置信度（0.3→0.45），减少自由生成风险 |
| 新增配置项 | ✅ 完成 | `ENABLE_REWRITE`、`REWRITE_TRIGGER_THRESHOLD`、`REWRITE_MAX_PHRASINGS`、`ALT_PHRASING_MAX_COUNT`、`ENABLE_MULTI_CONCEPT_DECOMPOSE` |

### 修改文件

1. **backend/services/term_rewriter.py（新增）**
   - `TermRewriter` 类：`rewrite_colloquial()`、`decompose_multi_concept()`、`generate_alternative_phrasings()`、`detect_multi_concept()`
   - `ConstrainedTermSelector` 类：`select_from_candidates()`
   - 中英文 prompt 内置，支持 concept_type 差异化引导

2. **backend/services/terminology_service.py**
   - 初始化 `TermRewriter` 和 `ConstrainedTermSelector`
   - `normalize_term()` 重写为分级触发链路
   - 新增 `_try_exact_or_alias_match()` 预检方法
   - `extract_and_normalize_terms_parallel()` 修复中英文分流

3. **backend/config.py**
   - 新增5个配置项

### 数据流变更

```
旧流程：
mention → ChineseTerm → UMLS → LLM兜底(自由生成)

新流程（中文路径）：
mention
  → [预检] exact/alias → 命中直接返回
  → [预检] 多概念检测 → 拆解 → 递归规范化
  → [检索] 本地术语库(ChineseTerm/ICD-11)
  → [判断] 最高分 ≥ 0.5 → 直接返回
  → [改写] 低置信度 → rewrite → re-retrieve
  → [扩写] still low → alternative phrasing → re-retrieve
  → [约束] LLM 约束选择(unresolved可接受)
  → [兜底] unresolved(保留原mention, confidence=0.3)

新流程（英文路径）：
同中文路径，检索源替换为UMLS，不检索本地术语库
```

---

## 2026-05-19 性能优化：提示词精简与事实过滤

### 问题分析

实际运行日志显示，从阶段2开始提示词显著增长，总处理时间超过8分钟（496s）：

| 阶段 | 优化前提示词长度 | 优化前耗时 |
|------|-----------------|-----------|
| 阶段2（事实抽取） | 8,391 chars | 149.55s |
| 阶段4a（SO生成） | 12,152 chars | 47.50s |
| 阶段4b-1（评估） | 13,640 chars | ~21s |
| 阶段4b-2（计划） | 14,344 chars | ~14s |
| 阶段5（核查） | 20,128 chars | 64.17s |

**根因**：
1. 提示词模板过度冗长，包含大量冗余指令和详细示例
2. 所有阶段（SO/评估/计划/核查）都传入**全部事实的完整JSON**，而每个阶段实际只需特定 section 的事实

### 优化方案

**优化1：精简提示词模板**

将6个核心模板大幅缩减（每个减少50-60%），保留关键指令和输出格式，去除冗余描述和示例。

| 模板 | 优化前 | 优化后 | 缩减 |
|------|--------|--------|------|
| turn_cleaning | ~1300 chars | 496 chars | -62% |
| fact_extraction | ~2100 chars | 950 chars | -55% |
| emr_generation_so | ~2100 chars | 1039 chars | -50% |
| emr_generation_assessment | ~1800 chars | 848 chars | -53% |
| emr_generation_plan | ~2400 chars | 877 chars | -63% |
| soap_verification | ~2200 chars | 1128 chars | -49% |

**优化2：按 section_candidate 过滤事实**

新增 `_filter_facts_by_section()` 方法，各阶段仅传入相关 section 的事实：
- 阶段4a（SO生成）：仅传入 S+O 事实（减少约40%事实数据）
- 阶段4b-1（评估）：仅传入 A 事实（减少约88%事实数据）
- 阶段4b-2（计划）：仅传入 P 事实（减少约52%事实数据）
- 阶段5（核查）：保持全部事实（需全面核查）
- 新增 `_build_compact_context()` 方法用于紧凑上下文摘要

### 修改文件

1. **backend/services/llm/prompts.py**
   - 精简 `turn_cleaning` 模板（52行 → 23行）
   - 精简 `fact_extraction` 模板（80行 → 40行）
   - 精简 `emr_generation_so` 模板（53行 → 37行）
   - 精简 `emr_generation_assessment` 模板（73行 → 31行）
   - 精简 `emr_generation_plan` 模板（90行 → 33行）
   - 精简 `soap_verification` 模板（103行 → 38行）

2. **backend/services/llm_pipeline_service.py**
   - 新增 `_filter_facts_by_section(fact_records, sections)` 方法
   - 新增 `_build_compact_context(fact_records, max_items)` 方法
   - 新增 `_build_compact_turns(all_cleaned_turns)` 方法（用于调试模式构建紧凑轮次JSON）
   - 修改 `_generate_so_stage()`：使用 `_filter_facts_by_section(fact_records, ["S", "O"])`
   - 修改 `_generate_ap_stage()`：评估使用 A 事实，计划使用 P 事实
   - 重写 `process_stage_with_user_input()`：全部改为新版阶段名称（turn_cleaning → fact_extraction → emr_generation_so → emr_generation_assessment → emr_generation_plan → verification），使用 prompt_manager 构建提示词；跳过自动执行的 normalize_terms 阶段
   - 新增 `_legacy_role_annotation_stage/term_normalization/field_extraction/emr_generation` 兼容旧阶段名称
   - 新增 `_lightweight_normalize()` 方法：在 fact_extraction 后自动使用 ChineseTerm 本地库进行轻量术语规范化
   - 更新 `_debug_interact()` 手动输入提示为新版简洁模板
   - 更新 `get_all_prompts()` 移除 normalize_terms 阶段（自动执行），调整阶段编号（1→6）

### 预期效果

- 提示词模板总长度缩减约 **50-60%**
- 各阶段事实数据量缩减 **40-88%**（根据 section 分布）
- 预计总提示词长度从 ~68K chars 降至 ~35K chars（约 **48% 缩减**）
- 预计处理时间缩短约 **30-50%**

---

## 2026-05-19 BugFix 3: 证据溯源数据填充

### 变更内容

修复 `evidence_traces` 始终为空数组的问题，实现从 `AtomicFact` → `TranscriptTurn` 的证据溯源链路，前端可清晰展示每条病历内容对应的原始转写文本来源。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| `_build_evidence_traces_from_fact_ids()` | ✅ 完成 | 从 fact_id 集合反查 AtomicFact → TranscriptTurn，构建 evidence_trace 条目 |
| `_enrich_evidence_traces()` | ✅ 完成 | 按 SO/A/P 分节填充各字段 evidence_traces，S/O 按 section_candidate 分组，A 来自 assessment_items，P 来自 plan_items 子项 |
| `_save_evidence_spans_from_emr()` | ✅ 完成 | 遍历富化后的 EMR，写入 EvidenceSpan 表，供 `/api/emr/evidence/{visit_id}` 查询 |
| `process_transcript()` 流程调整 | ✅ 完成 | 移除冗余的 `_normalize_emr_format()`；核查后保留 fact_id 引用；依次调用 normalize → enrich → save_spans → save_emr |

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 新增 `_build_evidence_traces_from_fact_ids(fact_ids, fact_by_id, turn_by_index)` 方法
   - 新增 `_enrich_evidence_traces(emr_result, fact_records, turns)` 方法
   - 新增 `_save_evidence_spans_from_emr(emr_result, visit_id)` 方法
   - 修改 `process_transcript()`：将 `emr_result` 变量重命名为 `emr_draft`；移除第一处 `_normalize_emr_format()`；核查后注入 `so_used_fact_ids`/`assessment_items`/`plan_items`；调用富化和保存方法

2. **backend/services/llm/prompts.py**
   - 无需修改（已有 `used_fact_ids` 和 `supporting_fact_ids` 输出要求）

### 证据溯源链路

```
LLM 生成 SOAP → 返回 used_fact_ids / supporting_fact_ids
                              ↓
_enrich_evidence_traces() → 反查 AtomicFact.evidence_turn_ids
                              ↓
_build_evidence_traces_from_fact_ids() → 反查 TranscriptTurn
                              ↓
填充 emr_json.{section}.{field}.evidence_traces = [{speaker, turn_text, turn_index, content}, ...]
                              ↓
_save_evidence_spans_from_emr() → 写入 EvidenceSpan 表
                              ↓
前端 buildEvidenceHtml() → 展示"证据来源"内联面板
showEvidence() → 展示"证据溯源"表格面板
```

---

## 2026-05-18 阶段5实现：核查与修订

### 变更内容

在 LLM Pipeline 中新增阶段5核查与修订，在 SOAP 病历生成后自动执行结构化核查，产出的问题清单包括四个核查维度，并基于问题清单输出修订后的 `soap_final`。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增 soap_verification 提示模板 | ✅ 完成 | `prompts.py` 新增模板，定义四个核查维度的详细指令和输出格式 |
| 新增 _verification_stage() | ✅ 完成 | `llm_pipeline_service.py` 新增方法，实现完整的核查与修订流程 |
| 核查规则实现 | ✅ 完成 | 四个维度：unsupported_claims、missing_critical_facts、internal_conflicts、certainty_errors |
| 修订逻辑实现 | ✅ 完成 | 优先级：删除无证据声明 → 补充遗漏事实 → 修正措辞 |
| 集成到 process_transcript() | ✅ 完成 | 在阶段4之后调用阶段5，输出使用修订后的 soap_final |
| API 层适配 | ✅ 完成 | `PipelineProcessResponse` 新增 `fact_result` 和 `verification_result` 字段 |

### 修改文件

1. **backend/services/llm/prompts.py**
   - 在 `_load_chinese_templates()` 中新增 `PromptTemplate`：
     - `soap_verification`：输入 `draft_emr`（草稿 SOAP）、`fact_table`（事实表 JSON）、`role_mapping`（角色映射）。四个核查维度：`unsupported_claims`（无证据声明）、`missing_critical_facts`（遗漏关键事实）、`internal_conflicts`（内部冲突）、`certainty_errors`（确定性错误）。输出 JSON 包含 `issues`（四个数组）和 `soap_final`（修订后的完整 SOAP）

2. **backend/services/llm/prompts.py**（重构）
   - 复用已有 `_format_facts_for_prompt()` 辅助方法，避免内联序列化逻辑重复

3. **backend/services/llm_pipeline_service.py**
   - 新增 `_verification_stage(draft_emr, fact_records, role_mapping)` 方法：
     - 将 `draft_emr` 序列化为 JSON
     - 使用 `_format_facts_for_prompt()` 将 AtomicFact 列表转换为 JSON
     - 渲染 `soap_verification` 模板
     - 调用 LLM（支持 debug_mode）
     - 解析 JSON 响应获取 `issues` 和 `soap_final`
     - 记录各维度问题数量到日志
     - 失败时回退到使用原始草稿
   - `process_transcript()` 阶段5调用：
     - 在阶段4之后调用 `_verification_stage(emr_result, fact_records, all_role_mappings)`
     - 返回字典中 `emr_result` 使用修订后的 `soap_final`

4. **backend/api/emr.py**
   - `PipelineProcessResponse` 新增 `fact_result` 和 `verification_result` 字段
   - `process_with_pipeline()` 返回结果填充新增字段

### 核查维度详解

| 维度 | 字段名 | 检测内容 | 修订策略 |
|------|--------|----------|----------|
| 无证据声明 | `unsupported_claims` | 病历中无法在事实表找到对应证据的陈述 | **优先删除**（最高优先级） |
| 遗漏关键事实 | `missing_critical_facts` | 事实表中高重要度、但在病历中被遗漏的事实 | 补充到对应 SOAP 节 |
| 内部冲突 | `internal_conflicts` | SOAP 各节之间信息不一致 | 修正冲突内容 |
| 确定性错误 | `certainty_errors` | suspected 诊断被写成明确诊断等措辞问题 | 调整措辞 |

### 修订优先级

```
1. 删除无证据声明（unsupported_claims）    — 最高优先级，防止幻觉
2. 补充遗漏关键事实（missing_critical_facts）— 确保完整性
3. 修正措辞（certainty_errors + internal_conflicts）— 确保准确性
```

### 数据流变更

```
旧流程（阶段4→完成）：
阶段4 → emr_result → 返回

新流程（阶段4→阶段5→完成）：
阶段4 → emr_result（草稿）→ 阶段5 _verification_stage()
  ↓                              ↓
  输入：draft_emr + fact_table   issues（问题清单）+ soap_final（修订版）
                                    ↓
                               返回 soap_final 替代 emr_result
```

### 返回数据结构变更

| 字段 | 位置 | 说明 |
|------|------|------|
| `emr_result` | `PipelineProcessResponse.emr_result` | 修订后的最终 SOAP（来自 `soap_final`） |
| `emr_draft` | 内部返回字典 | 阶段4原始草稿，保留供调试参考 |
| `verification_result` | `PipelineProcessResponse.verification_result` | 完整的核查结果，含 `issues` 和 `soap_final` |
| `fact_result` | `PipelineProcessResponse.fact_result` | 阶段2事实抽取结果 |

### 保持未变更的方法

- `_generate_so_stage()` — 不变，上游消费者保持兼容
- `_generate_ap_stage()` — 不变
- `_run_evaluation()` — 不变
- 旧 prompt 模板 — 保留，向后兼容

---

## 2026-05-18 阶段4重构：分节生成SOAP + 三层诊断

### 变更内容

将 LLM Pipeline 的阶段4从"单次SOAP生成"重构为"分节生成 + 三层诊断策略"，将原来的一个 LLM 调用拆分为三个独立的子阶段调用：SO生成、Assessment生成、Plan生成。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增 emr_generation_so 提示模板 | ✅ 完成 | `prompts.py` 新增模板，输入事实表+对话摘要，输出 S+O+used_fact_ids |
| 新增 emr_generation_assessment 提示模板 | ✅ 完成 | `prompts.py` 新增模板，要求三层诊断策略输出 |
| 新增 emr_generation_plan 提示模板 | ✅ 完成 | `prompts.py` 新增模板，要求四子字段结构化 |
| 新增 _format_facts_for_prompt() | ✅ 完成 | 将 AtomicFact ORM 列表格式化为 prompt 用的 JSON 字符串 |
| 新增 _generate_so_stage() | ✅ 完成 | 阶段4a，调用 emr_generation_so 模板，只生成 Subjective + Objective |
| 新增 _generate_ap_stage() | ✅ 完成 | 阶段4b，分两步：先生成 Assessment（三层诊断），再生成 Plan（四子字段） |
| 标记旧方法为 DEPRECATED | ✅ 完成 | `_generate_emr_stage()`、`_build_emr_generation_prompt()` 标记弃用但保留 |
| 修改 process_transcript() | ✅ 完成 | 阶段4调用改为 `_generate_so_stage()` + `_generate_ap_stage()`，合并结果为 emr_result |

### 修改文件

1. **backend/services/llm/prompts.py**
   - 在 `_load_chinese_templates()` 中新增 3 个 `PromptTemplate`：
     - `emr_generation_so`：输入 `facts_json` 和 `dialogue_summary`，输出 `subjective`、`objective`、`used_fact_ids`。核心规则：禁止生成诊断和计划，每条描述必须有事实依据，每条描述引用对应 `fact_id`
     - `emr_generation_assessment`：输入 `subjective_text`、`objective_text`、`facts_json`，输出 `assessment` 和 `assessment_items`。每条 assessment_item 包含 `certainty_level`、`supporting_fact_ids`、`diagnosis_type`。硬规则：只有 `certainty=explicit` 且 `concept_type=disease` 的事实才能输出 `explicit_diagnosis`
     - `emr_generation_plan`：输入 `subjective_text`、`objective_text`、`assessment_text`、`facts_json`，输出 `plan` 和 `plan_items`。plan_items 包含 `medications`、`tests`、`follow_up`、`education` 四个子字段

2. **backend/services/llm_pipeline_service.py**
   - 新增 `_format_facts_for_prompt(fact_records)`：将 AtomicFact ORM 对象列表转换为 JSON 字符串，包含 `fact_id`、`section_candidate`、`concept_type`、`mention`、`normalized_term`、`polarity`、`temporality`、`certainty`、`speaker`、`evidence_turn_ids`、`evidence_text` 字段
   - 新增 `_generate_so_stage(fact_records, role_mapping)`：
     - 构建对话摘要（从 fact_records 的 mention 提取）
     - 渲染 `emr_generation_so` 模板
     - 调用 LLM → JSON 解析
     - 返回 `{"subjective": {...}, "objective": {...}, "used_fact_ids": [...]}`
   - 新增 `_generate_ap_stage(so_result, fact_records, role_mapping)`：
     - 步骤1：渲染 `emr_generation_assessment` 模板 → 调用 LLM → JSON 解析 → 获取 `assessment` 和 `assessment_items`
     - 步骤2（延迟 `STAGE_DELAY` 秒后）：渲染 `emr_generation_plan` 模板 → 调用 LLM → JSON 解析 → 获取 `plan` 和 `plan_items`
     - 返回 `{"assessment": {...}, "plan": {...}, "assessment_items": [...], "plan_items": {...}}`
   - `_generate_emr_stage()`：添加 DEPRECATED 注释块和 `logger.warning`
   - `_build_emr_generation_prompt()`：添加 DEPRECATED 注释块和 `logger.warning`
   - `process_transcript()` 阶段4调用：
     - 旧：`emr_result = self._generate_emr_stage(extraction_result, ...)`
     - 新：`so_result = self._generate_so_stage(...)` → `ap_result = self._generate_ap_stage(so_result, ...)` → 合并为 `emr_result` 字典

### 三层诊断策略

| 诊断层次 | diagnosis_type | 触发条件 | 输出约束 |
|----------|---------------|----------|----------|
| 明确诊断 | `explicit_diagnosis` | `certainty=explicit` + `concept_type=disease` | 仅可输出1个 |
| 倾向性诊断 | `suspected_diagnosis` | `certainty=supported` + `concept_type=disease` | 可输出多个 |
| 症状性评估 | `symptom_based_assessment` | 无明确诊断指向 | 描述症状模式 |

### Plan四子字段结构

| 子字段 | 字段名 | 内容 |
|--------|--------|------|
| 药物治疗 | `medications` | 药品名称、用法用量、疗程 |
| 检查建议 | `tests` | 建议的辅助检查项目 |
| 随访建议 | `follow_up` | 复诊时间、随访计划 |
| 健康教育 | `education` | 生活方式指导、注意事项 |

### 数据流变更

```
旧流程（阶段4→阶段5）：
阶段4 → _generate_emr_stage(extraction_result, ...)
         → 单次LLM调用，生成完整SOAP（含S+O+A+P）
    ↓
阶段5 → _verification_stage(emr_result, ...)

新流程（阶段4→阶段5）：
阶段4a → _generate_so_stage(fact_records, role_mapping)
          → LLM调用1：生成 S（主观数据）+ O（客观数据）
    ↓
阶段4b → _generate_ap_stage(so_result, fact_records, role_mapping)
          → LLM调用2：基于 S+O 生成 Assessment（三层诊断）
          → LLM调用3：基于 S+O+A 生成 Plan（四子字段结构化）
    ↓
阶段5 → _verification_stage(emr_result, ...)
```

### emr_result 结构变更

| 字段 | 旧版 | 新版 |
|------|------|------|
| `subjective` | ✅ 保留 | ✅ 保留 |
| `objective` | ✅ 保留 | ✅ 保留 |
| `assessment` | ✅ 保留 | ✅ 保留 |
| `plan` | ✅ 保留 | ✅ 保留 |
| `so_used_fact_ids` | — | ✅ 新增，SO生成使用的事实ID列表 |
| `assessment_items` | — | ✅ 新增，评估项列表（含 diagnosis_type） |
| `plan_items` | — | ✅ 新增，计划项（含 medications/tests/follow_up/education） |

### 保持未变更的方法

- `_verification_stage()` — 不变，下游消费者保持兼容
- `_run_evaluation()` — 不变
- 旧 prompt 模板（`emr_generation`、`emr_generation_with_role`）— 保留，向后兼容
- `_generate_emr_stage()` — 保留但标记 DEPRECATED
- `_build_emr_generation_prompt()` — 保留但标记 DEPRECATED

---

## 2026-05-18 阶段3重构：选择性术语规范化

### 变更内容

将 LLM Pipeline 的阶段3从"全文术语规范化"重构为"选择性术语规范化"，不再对全文文本做术语规范化，改为只对阶段2事实表中 `normalization_needed=True` 的 `mention` 字段做规范化。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增 normalize_single_term() | ✅ 完成 | `terminology_service.py` 新增薄包装方法，直接调用 `normalize_term()` |
| 重构 _normalize_terms_stage() | ✅ 完成 | 新签名接受 `fact_records: List[AtomicFact]`，不再接受 `annotated_text` |
| 更新 process_transcript() | ✅ 完成 | 阶段3调用改为通过 FactService 查询事实表后传入 |
| 标记旧方法为 DEPRECATED | ✅ 完成 | `_build_normalization_prompt()`、`_normalize_terms_serial()`、`_normalize_terms_parallel()` 标记弃用 |
| 保留旧 _normalize_terms_stage() | ✅ 完成 | 重命名为 `_normalize_terms_stage_legacy()`，保留兼容 |

### 修改文件

1. **backend/services/terminology_service.py**
   - 新增 `normalize_single_term(term, context, term_type)` 方法
   - 作为 `normalize_term()` 的薄包装，语义化命名
   - 不调用 `identify_colloquial_terms()`，直接规范化单个术语

2. **backend/services/llm_pipeline_service.py**
   - 导入 `FactService`
   - 新增 `_normalize_terms_stage(fact_records, role_mapping, visit_id, save_to_db)` 新方法：
     - 遍历 `fact_records`，筛选 `normalization_needed=True` 且 `mention` 非空的记录
     - 对每条符合条件的 fact 调用 `terminology_service.normalize_single_term(fact.mention, context="", term_type=fact.concept_type)`
     - 更新 `fact.normalized_term`、`fact.normalized_code`、`fact.normalization_needed=False`
     - 提交到数据库
     - 返回包含 `terms`、`processed_count`、`skipped_count`、`total_count` 的字典
   - 旧 `_normalize_terms_stage()` 重命名为 `_normalize_terms_stage_legacy()` 并标记 DEPRECATED
   - `_build_normalization_prompt()` 标记 DEPRECATED
   - `_normalize_terms_serial()` 标记 DEPRECATED
   - `_normalize_terms_parallel()` 标记 DEPRECATED
   - `process_transcript()` 阶段3调用：
     - 创建 `FactService(self.db)`，查询 `get_facts_by_visit(visit_id)`
     - 传入 `fact_records` 调用新的 `_normalize_terms_stage()`

### 数据流变更

```
旧流程（阶段2→阶段3）：
阶段2 → _fact_extraction_stage()
    ↓
阶段3 → _normalize_terms_stage(combined_text, role_mapping, visit_id)
         → identify_colloquial_terms(annotated_text)  ← 全文扫描
         → normalize_term(term, context, term_type)   ← 每个术语
         → normalized_text.replace(original, normalized) ← 全文替换
         → save_normalized_terms()                    ← 保存 NormalizedTerm 记录

新流程（阶段2→阶段3）：
阶段2 → _fact_extraction_stage()
         → _save_atomic_facts() 将事实写入 DB
    ↓
阶段3 → FactService.get_facts_by_visit(visit_id)  ← 从 DB 读取事实
         → _normalize_terms_stage(fact_records, role_mapping, visit_id)
         → 仅处理 normalization_needed=True 的 fact
         → normalize_single_term(fact.mention)  ← 不扫描全文
         → 直接更新 fact.normalized_term、fact.normalized_code  ← 更新 AtomicFact 记录
         → 不再替换全文文本
```

### 保持未变更的方法

- `normalize_term()` — 不变（`normalize_single_term()` 的底层实现）
- `identify_colloquial_terms()` — 保留，旧版 legacy 方法仍需使用
- `save_normalized_terms()` — 保留，旧版 legacy 方法仍需使用
- `_normalize_terms_stage_legacy()` — 保留，向后兼容
- `_normalize_terms_serial()` — 保留但标记 DEPRECATED
- `_normalize_terms_parallel()` — 保留但标记 DEPRECATED
- `_build_normalization_prompt()` — 保留但标记 DEPRECATED
- `_parse_normalization_response()` — 不变

### normalized_result 返回结构变更

| 字段 | 旧版 | 新版 |
|------|------|------|
| `normalized_text` | 替换后的全文 | **已移除** |
| `terms` | `[{original, normalized, category, source, confidence, cui, code, code_system, is_colloquial}]` | `[{fact_id, original, normalized, category, source, confidence, cui, code, code_system, section_candidate}]` |
| `processed_count` | 无 | 成功处理的 fact 数 |
| `skipped_count` | 无 | 处理失败的 fact 数 |
| `total_count` | 无 | 总 fact 数 |

---

## 2026-05-18 阶段2实现：事实抽取与证据绑定

### 变更内容

在 LLM Pipeline 中新增阶段2，从阶段1输出的 turn JSON 中抽取原子临床事实，绑定证据来源，输出结构化事实表。原有的 `_extract_fields_stage()` 标记为 DEPRECATED。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增 fact_extraction 提示模板 | ✅ 完成 | `backend/services/llm/prompts.py` 新增 template key |
| 新增 _fact_extraction_stage() | ✅ 完成 | 从 cleaned_turns 中通过 LLM 抽取原子事实 |
| 新增 _deduplicate_facts() | ✅ 完成 | 按 mention+section+speaker 去重，合并 evidence_turn_ids |
| 新增 _save_atomic_facts() | ✅ 完成 | 将事实保存为 AtomicFact 记录到数据库 |
| 创建 FactService | ✅ 完成 | `backend/services/fact_service.py` 封装 AtomicFact CRUD |
| 修改 process_transcript() | ✅ 完成 | 在阶段1之后插入阶段2调用 |
| 标记 _extract_fields_stage() 为 DEPRECATED | ✅ 完成 | 添加 DEPRECATED 注释，调用代码注释掉 |
| 标记 _extract_evidence_traces() 为 DEPRECATED | ✅ 完成 | 添加 DEPRECATED 注释 |
| 返回字典新增 fact_result | ✅ 完成 | process_transcript() 响应中包含 fact_result |

### 修改文件

1. **backend/services/llm/prompts.py**
   - 在 `_load_chinese_templates()` 中新增 `fact_extraction` 模板
   - 模板要求 LLM 从 cleaned_turns JSON 中抽取原子临床事实
   - 每条事实包含：section_candidate, concept_type, mention, polarity, temporality, certainty, speaker, evidence_turn_ids, evidence_text
   - 包含去重规则：同一事实多 turn 提及则合并

2. **backend/services/llm_pipeline_service.py**
   - 导入 `uuid` 和 `AtomicFact`
   - 新增 `_fact_extraction_stage()`：构建提示词→调用LLM→解析JSON→去重→保存数据库
   - 新增 `_deduplicate_facts()`：按 mention+section_candidate+speaker 组合键去重，合并 evidence_turn_ids 和 evidence_text
   - 新增 `_save_atomic_facts()`：将事实列表保存为 AtomicFact 记录
   - 修改 `process_transcript()`：
     - 在阶段1完成后插入 `_fact_extraction_stage()` 调用
     - `_extract_fields_stage()` 调用注释掉，`extraction_result` 直接来自 `fact_result`
     - 返回字典新增 `fact_result` 字段
   - `_extract_fields_stage()` 添加 DEPRECATED 注释
   - `_extract_evidence_traces()` 添加 DEPRECATED 注释

3. **backend/services/fact_service.py**（新增）
   - `FactService` 类：封装 AtomicFact 的 CRUD 操作
   - `save_facts(facts, visit_id)`：批量保存事实
   - `get_facts_by_visit(visit_id)`：按 visit_id 查询事实
   - `get_facts_needing_normalization(visit_id)`：查询需要规范化的记录
   - `update_normalized_term(fact_id, normalized_term, normalized_code)`：更新单条事实的规范化术语

### 保持未变更的方法

- `_extract_fields_stage()` — 保留但标记为 DEPRECATED
- `_extract_evidence_traces()` — 保留但标记为 DEPRECATED
- `_build_extraction_prompt()` — 不变
- `_parse_extraction_response()` — 不变
- `_fallback_extraction()` — 不变

### 数据流变更

```
旧流程（阶段1→阶段3→阶段4）：
阶段1 → cleaned_turns + combined_text
    ↓
阶段3 → _normalize_terms_stage(combined_text)
阶段4 → _extract_fields_stage(normalized_text, [])
阶段5 → _generate_emr_stage(extraction_result, ...)

新流程（阶段1→阶段2→阶段3→阶段5）：
阶段1 → cleaned_turns + combined_text
    ↓
阶段2 → _fact_extraction_stage(cleaned_turns, role_mapping, visit_id)
         → AtomicFact 列表（结构化事实表）
    ↓
阶段3 → _normalize_terms_stage(combined_text)  [后续重构为选择性规范化]
阶段5 → _generate_emr_stage(fact_result, ...)
```

### FactService API

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `save_facts()` | `facts: List[Dict]`, `visit_id: str` | `List[AtomicFact]` | 批量保存原子事实 |
| `get_facts_by_visit()` | `visit_id: str` | `List[AtomicFact]` | 按就诊ID查询所有事实 |
| `get_facts_needing_normalization()` | `visit_id: str` | `List[AtomicFact]` | 查询需要规范化的记录 |
| `update_normalized_term()` | `fact_id, normalized_term, normalized_code` | None | 更新单条事实的规范化术语 |

---

## 2026-05-18 阶段1重构：转写清洗与角色纠错

### 变更内容

将 LLM Pipeline 的阶段1从"角色标注+XML证据标注"重构为独立的"转写清洗与角色纠错"，输出 turn JSON 而非 XML 标注文本。证据标注职责移交给未来的阶段2（事实抽取）。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 新增 turn_cleaning 提示模板 | ✅ 完成 | `backend/services/llm/prompts.py` 新增 template key |
| 新增 _build_cleaning_prompt() | ✅ 完成 | 使用 PromptManager 渲染 turn_cleaning 模板 |
| 新增 _parse_cleaning_response() | ✅ 完成 | 解析 turn JSON 列表，JSON解析失败时回退到 _fallback_role_annotation() |
| 新增 _apply_asr_corrections() | ✅ 完成 | 将 corrected_text 和 changed_spans 写入数据库 |
| 新增 _build_text_from_cleaned_turns() | ✅ 完成 | 从清洗后的 turn JSON 构建合并文本供后续阶段使用 |
| 修改 _process_segment() | ✅ 完成 | 调用 _build_cleaning_prompt() + _parse_cleaning_response() + _apply_asr_corrections() |
| 修改 process_transcript() | ✅ 完成 | 收集 cleaned_turns 替代 annotated_texts 和 evidence_traces |
| 标记旧方法为 DEPRECATED | ✅ 完成 | _build_role_annotation_prompt()、_parse_role_annotation_response() 标记为 DEPRECATED |
| 更新 _debug_interact() | ✅ 完成 | 新增 turn_cleaning 阶段的手动输入指引 |

### 修改文件

1. **backend/services/llm/prompts.py**
   - 在 `_load_chinese_templates()` 中新增 `turn_cleaning` 模板
   - 模板要求 LLM 执行：(a) 角色纠错 (b) ASR 转写错误修正
   - 输出格式：turn JSON（含 turn_id、speaker_role、corrected_text、changed_spans、correction_confidence、reason）
   - 不含任何 XML 标签指令或证据标注要求

2. **backend/services/llm_pipeline_service.py**
   - 新增 `_build_cleaning_prompt()`：使用 PromptManager 加载 turn_cleaning 模板
   - 新增 `_parse_cleaning_response()`：解析 LLM 返回的 turn JSON 列表，提取角色映射和说话人纠正记录
   - 新增 `_apply_asr_corrections()`：将 changed_spans 非空的 turn 的 corrected_text 写入数据库
   - 新增 `_build_text_from_cleaned_turns()`：从清洗后的 turn JSON 构建合并文本（优先使用 corrected_text）
   - 修改 `_process_segment()`：调用新的 cleaning 方法替代旧的 role_annotation 方法
   - 修改 `process_transcript()`：收集 `all_cleaned_turns` 替代 `all_annotated_texts` 和 `all_evidence_traces`
   - 返回字典中 `annotated_text` → `cleaned_turns` + `combined_text`，移除 `evidence_traces`
   - `_extract_fields_stage()` 传入空列表作为 evidence_traces（证据溯源现在来自阶段2）
   - `_build_role_annotation_prompt()` 和 `_parse_role_annotation_response()` 标记为 DEPRECATED
   - `_debug_interact()` 新增 `turn_cleaning` 阶段的手动输入指引

### 保持未变更的方法

- `_format_segment()` — 不变
- `_fallback_role_annotation()` — 不变
- `_infer_roles_by_rules()` — 不变
- `_apply_speaker_corrections()` — 不变
- `_assign_speakers_from_unlabeled()` — 不变
- `_segment_turns()` — 不变
- `_extract_evidence_traces()` — 保留标记为 DEPRECATED

### 数据流变更

```
旧流程：
阶段1 → annotated_text (XML标注文本) + evidence_traces
    ↓
阶段2 → _normalize_terms_stage(annotated_text)
阶段3 → _extract_fields_stage(normalized_text, evidence_traces)

新流程：
阶段1 → cleaned_turns (turn JSON列表) + combined_text
    ↓
阶段2 → _normalize_terms_stage(combined_text)  [暂未重构]
阶段3 → _extract_fields_stage(normalized_text, [])  [证据溯源移入阶段2]
```

---

## 2026-05-18 诊断推断优化 - 结合上下文综合判断

### 问题

诊断字段直接复述对话中提到的诊断（如"上呼吸道感染"），未结合上下文进行综合推断。

**示例**：
- 对话中患者说"医生诊断为上呼吸道感染，但至今未痊愈，时好时坏"
- 医生后续建议检查支原体，提到"支原体感染会导致反复呼吸道感染"
- 患者提到"孩子一直特别容易咳嗽"
- 综合判断：症状持续时间长、反复发作、医生建议检查支原体，更倾向于支气管炎

### 根因

病历生成阶段的prompt只要求"忠实原文"，没有要求LLM结合上下文进行诊断推断。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 传递原始对话到病历生成阶段 | ✅ 完成 | `_generate_emr_stage` 新增 `dialogue_text` 参数 |
| 修改病历生成prompt | ✅ 完成 | 新增"诊断推断要求"章节，明确要求结合上下文推断 |
| 添加诊断推断示例 | ✅ 完成 | 在prompt中提供具体的推断示例 |

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - `process_transcript()`：在调用 `_generate_emr_stage` 前构建 `dialogue_text`
   - `_generate_emr_stage()`：新增 `dialogue_text` 参数
   - `_build_emr_generation_prompt()`：
     - 新增 `dialogue_text` 参数
     - prompt中新增"原始对话"章节
     - prompt中新增"诊断推断要求"章节，包含5条推断原则和示例
     - 新增"诊断推断例外"约束

### 测试结果

| 对比项 | 修改前 | 修改后 |
|--------|--------|--------|
| 诊断 | 上呼吸道感染 | 反复呼吸道感染；支原体感染待除外；咳嗽变异性哮喘待除外 |
| 依据 | 直接复述对话 | 结合症状持续时间、反复发作特点、医生建议等上下文 |

**诊断推断依据**：
1. 症状持续时间长（7月至今，近5个月）
2. 反复发作特点（时好时坏）
3. 医生建议检查支原体
4. 医生提到可能的诊断方向（支气管哮喘、过敏性咳嗽）

---

## 2026-05-18 修复术语规范化replace()类型错误

### 问题

`TypeError: replace() argument 2 must be str, not dict`，发生在术语规范化阶段替换文本时。

### 根因

DeepSeek思考模式下，LLM返回的JSON中`normalized_term`字段值可能为dict而非string（如`{"value": "头痛"}`而非`"头痛"`），传播到`normalized_text.replace(original, normalized)`时触发类型错误。

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| _normalize_by_llm类型防护 | ✅ 完成 | 检测normalized_term为dict时尝试提取value/term字段，否则转str |
| _normalize_terms_stage类型防护 | ✅ 完成 | 替换前检查normalized类型，dict跳过替换，非str转str |
| 英文pipeline同步修复 | ✅ 完成 | llm_pipeline_service_en.py同样添加类型防护 |

### 修改文件

1. **backend/services/terminology_service.py**
   - `_normalize_by_llm()`：检测`normalized_term`为dict时尝试提取`value`/`term`字段，否则`str()`转换
   - `reasoning`字段同样添加dict→str防护

2. **backend/services/llm_pipeline_service.py**
   - `_normalize_terms_stage()`：替换前检查`normalized`类型，dict跳过替换并记录警告，非str转str

3. **backend/services/llm_pipeline_service_en.py**
   - 同步添加相同的类型防护逻辑

---

## 2026-05-18 修复DeepSeek思考模式导致术语规范化失败

### 问题

DeepSeek启用high深度思考模式后，术语规范化阶段输出"未识别到任何医学术语"。

### 根因

| 原因 | 说明 |
|------|------|
| reasoning_tokens计入completion_tokens | DeepSeek思考模式下，`reasoning_tokens`（2649）计入`completion_tokens`（10651），实际可用于content的token仅约8000，达到`max_tokens=8000`上限即被截断 |
| finish_reason: length | 输出被截断，JSON结构不完整 |
| 空白填充异常 | 截断后content被填充大量`\t`和空白字符（54367字符），导致JSON解析失败 |
| JSON解析不够健壮 | `terminology_service.py`仅使用简单`re.search`解析JSON，无修复能力 |

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 思考模式自动增加max_tokens | ✅ 完成 | 启用思考模式时max_tokens×3，补偿reasoning_tokens消耗 |
| 思考模式增加HTTP超时 | ✅ 完成 | 思考模式超时从120s增加到300s |
| 截断检测与日志 | ✅ 完成 | 检测finish_reason=length和空白填充异常，输出警告日志 |
| 空白填充清理 | ✅ 完成 | 新增`_strip_whitespace_padding`方法，清理响应中的空白填充 |
| JSON修复能力 | ✅ 完成 | 新增`_try_fix_json`方法，处理截断JSON、末尾多余逗号、缺失括号等 |
| identify_colloquial_terms健壮化 | ✅ 完成 | 解析失败时尝试修复，而非直接返回空列表 |
| _normalize_by_llm健壮化 | ✅ 完成 | 同样增加空白清理和JSON修复 |

### 修改文件

1. **backend/services/llm/openai_compatible_adapter.py**
   - 启用思考模式时自动将`max_tokens`乘以3，补偿reasoning_tokens消耗
   - 思考模式HTTP超时从120s增加到300s
   - 新增`finish_reason=length`截断检测和日志警告
   - 新增空白填充异常检测和日志警告

2. **backend/services/terminology_service.py**
   - 新增`_strip_whitespace_padding()`方法：清理响应中的大量空白填充字符
   - 新增`_try_fix_json()`方法：修复截断JSON、末尾多余逗号、缺失闭合括号等
   - `identify_colloquial_terms()`：解析前先清理空白填充，解析失败时尝试JSON修复
   - `_normalize_by_llm()`：同样增加空白清理和JSON修复逻辑
   - 记录thinking_content长度日志

### 修复策略

**预防层（解决根因）**：

| 问题 | 修复 |
|------|------|
| max_tokens不足 | 思考模式自动×3，8000→24000 |
| 超时不够 | 思考模式120s→300s |

**容错层（处理截断后的恢复）**：

| 问题 | 修复 |
|------|------|
| 空白填充 | `_strip_whitespace_padding`清理 |
| JSON截断 | `_try_fix_json`丢弃未完成项，保留已完成项 |
| 缺失括号 | 自动补全`}`和`]` |

---

## 2026-05-18 前端大模型配置编辑功能

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 后端ConfigUpdate模型扩展 | ✅ 完成 | 支持全字段更新（config_name/provider/model_name等） |
| 后端update_config端点扩展 | ✅ 完成 | 支持全字段更新，含配置名称唯一性校验、API Key空值保护 |
| 前端编辑按钮 | ✅ 完成 | 配置列表中每个配置项新增绿色"编辑"按钮 |
| 前端编辑模式 | ✅ 完成 | 点击编辑后表单填充已有数据，提交按钮变为"更新配置" |
| 前端取消编辑 | ✅ 完成 | 编辑模式下显示"取消编辑"按钮，退出编辑模式恢复表单 |
| 编辑按钮样式 | ✅ 完成 | 绿色主题编辑按钮（btn-edit），与蓝色启用/红色删除区分 |
| API Key安全处理 | ✅ 完成 | 编辑时不回显密钥，未修改时不覆盖原有密钥 |

### 修改文件

1. **backend/api/llm.py**
   - `ConfigUpdate` 模型新增 `config_name`、`provider`、`model_name`、`api_key`、`api_endpoint`、`max_tokens`、`temperature` 字段
   - `update_config` 端点支持全字段更新
   - 更新时校验 `config_name` 唯一性（排除自身）
   - `api_key` 为空字符串时不覆盖原有密钥

2. **frontend/config.html**
   - 表单新增隐藏字段 `editingConfigId` 存储正在编辑的配置ID
   - 提交按钮添加 `id="submitBtn"`，文本在新建/编辑模式间切换
   - 新增"取消编辑"按钮，仅在编辑模式下显示

3. **frontend/js/config.js**
   - 新增 `enterEditMode(config)` 函数：填充表单数据、切换UI状态、滚动到表单
   - 新增 `exitEditMode()` 函数：重置表单、恢复新建模式
   - 新增 `editConfig(configId)` 全局函数：加载配置数据并进入编辑模式
   - 表单提交逻辑根据 `editingConfigId` 判断走 POST（新建）或 PUT（更新）
   - 编辑模式下 API Key 为空时不发送该字段，避免覆盖原有密钥
   - 删除配置时若正在编辑该配置则自动退出编辑模式

4. **frontend/css/style.css**
   - 新增 `.btn-small.btn-edit` 绿色编辑按钮样式
   - 新增 `.btn-small.btn-edit:hover` 悬浮样式

### 交互流程

| 操作 | 触发 | 行为 |
|------|------|------|
| 点击"编辑" | 配置列表中的编辑按钮 | 填充表单、切换为更新模式、滚动到表单 |
| 点击"更新配置" | 编辑模式下的提交按钮 | PUT请求更新配置、退出编辑模式、刷新列表 |
| 点击"取消编辑" | 编辑模式下的取消按钮 | 清空表单、恢复新建模式 |
| 点击"保存配置" | 新建模式下的提交按钮 | POST请求创建配置、刷新列表 |
| 删除正在编辑的配置 | 删除按钮 | 退出编辑模式、删除配置、刷新列表 |

---

## 2026-05-18 DeepSeek思考模式与JSON输出支持

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| LLMConfig模型扩展 | ✅ 完成 | 新增json_mode、thinking_enabled、thinking_effort字段 |
| LLMRequest/LLMResponse扩展 | ✅ 完成 | 请求支持json_mode/thinking参数，响应支持thinking_content |
| OpenAICompatibleAdapter扩展 | ✅ 完成 | payload中添加response_format和thinking参数构建 |
| LLMService扩展 | ✅ 完成 | generate方法支持json_mode/thinking参数传递 |
| API层扩展 | ✅ 完成 | ConfigCreate/ConfigUpdate/GenerateRequest支持新字段 |
| 前端配置页面扩展 | ✅ 完成 | 新增JSON模式、思考模式、思考强度配置选项 |
| 数据库自动迁移 | ✅ 完成 | 新增列自动添加到现有数据库 |
| generate_json自动启用JSON模式 | ✅ 完成 | 调用generate_json时自动设置json_mode=True |

### 修改文件

1. **backend/models/llm_config.py**
   - 新增 `json_mode` 列（Boolean，默认False）
   - 新增 `thinking_enabled` 列（Boolean，默认False）
   - 新增 `thinking_effort` 列（String，默认"high"）
   - `to_dict()` 方法添加新字段输出

2. **backend/services/llm/base.py**
   - `LLMRequest` 新增 `json_mode`、`thinking_enabled`、`thinking_effort` 字段
   - `LLMResponse` 新增 `thinking_content` 字段
   - `LLMAdapter.__init__` 读取 `json_mode`、`thinking_enabled`、`thinking_effort` 配置

3. **backend/services/llm/openai_compatible_adapter.py**
   - `generate()` 方法构建payload时添加 `response_format` 参数（JSON模式）
   - `generate()` 方法构建payload时添加 `thinking` 参数（思考模式）
   - 响应解析提取 `reasoning_content` 或 `reasoning` 字段作为 `thinking_content`
   - 新增日志输出json_mode和thinking_enabled状态

4. **backend/services/llm/llm_service.py**
   - `_create_adapter()` 传递 `json_mode`、`thinking_enabled`、`thinking_effort` 到适配器
   - `generate()` 方法新增 `json_mode`、`thinking_enabled`、`thinking_effort` 参数
   - `generate_json()` 调用时自动设置 `json_mode=True`

5. **backend/api/llm.py**
   - `GenerateRequest` 新增 `json_mode`、`thinking_enabled`、`thinking_effort` 字段
   - `ConfigCreate` 新增 `json_mode`、`thinking_enabled`、`thinking_effort` 字段
   - `ConfigUpdate` 新增 `json_mode`、`thinking_enabled`、`thinking_effort` 字段
   - `generate_text` 端点传递新参数，响应中包含 `thinking_content`
   - `create_config` 端点保存和更新新字段
   - `update_config` 端点支持更新新字段

6. **frontend/config.html**
   - 服务商下拉框新增 `Sense-DeepSeek` 选项
   - 新增JSON输出模式复选框
   - 新增思考模式复选框
   - 新增思考强度下拉框（高/低，仅在思考模式启用时显示）

7. **frontend/js/config.js**
   - 表单提交时包含 `json_mode`、`thinking_enabled`、`thinking_effort`
   - 思考模式复选框联动控制思考强度下拉框显示
   - 配置列表显示JSON模式和思考模式状态

### 设计决策

**参数传递优先级**：

| 参数 | 请求级别 | 配置级别 | 优先级 |
|------|---------|---------|--------|
| json_mode | `request.json_mode` | `config.json_mode` | 请求级 > 配置级（OR逻辑） |
| thinking_enabled | `request.thinking_enabled` | `config.thinking_enabled` | 请求级 > 配置级（OR逻辑） |
| thinking_effort | `request.thinking_effort` | `config.thinking_effort` | 请求级优先，配置级兜底 |

**DeepSeek API参数映射**：

| 功能 | API参数 | 值 |
|------|---------|-----|
| JSON输出 | `response_format` | `{"type": "json_object"}` |
| 思考模式 | `thinking` | `{"type": "enabled", "reasoning_effort": "high"/"low"}` |
| 思考内容 | 响应中 `reasoning_content` 或 `reasoning` 字段 | 字符串 |

**向后兼容**：

- 所有新字段均有默认值，不影响现有配置
- `json_mode` 默认 `False`，不启用JSON输出
- `thinking_enabled` 默认 `False`，不启用思考模式
- `thinking_effort` 默认 `"high"`
- 数据库自动迁移机制自动添加新列

---

## 2026-05-14 中期汇报大纲更新（基于实测结果）

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 修正术语规范化描述 | ✅ 完成 | 从"UMLS为主"修正为"本地ICD-11/症状库(ChineseTerm)为主"，UMLS降级 |
| 修正纠错描述 | ✅ 完成 | 从"ASR纠错"修正为"LLM后处理纠错" |
| 填入实测数据 | ✅ 完成 | 7项测试结果全部填入大纲 |
| 更新方案演进过程 | ✅ 完成 | 增加UMLS中文覆盖差的实测证据，补充方案修正过程 |

### 修改文件

1. **docs/汇报/中期/修改后大纲.md**
   - 创新点2从"UMLS术语规范化集成"改为"基于本地术语库的中文术语规范化"
   - 3.1节"ASR纠错"改为"LLM后处理纠错"，注明纠错由LLM完成
   - 3.2节方案演进增加UMLS中文覆盖差的实测证据
   - 3.4节填入四层评估体系实测数据（2个样本）
   - 4.2节增加"ASR纠错→LLM后处理纠错"的偏差说明
   - 删除"需要紧急执行的测试清单"（测试已完成）

### 关键修正

1. **术语规范化核心来源**：ChineseTerm（本地ICD-11/症状库）命中率100%，UMLS对中文口语命中率0%
2. **纠错归属**：纠错由LLM后处理完成，与ASR模型无关
3. **质量评估**：QualityEvaluator使用LLM打分

---

## 2026-05-07 病历生成流程性能优化

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 性能分析计划 | ✅ 完成 | 创建详细的性能优化计划文档 |
| 步骤级并行化 | ✅ 完成 | 实现证据选择与术语规范化的并行执行 |
| 术语规范化深度优化 | ✅ 完成 | 实现Code获取并行化，批量处理优化 |
| 条件性执行优化 | ✅ 完成 | 智能跳过无数据步骤 |
| LLMPipelineService优化 | ✅ 完成 | 为实际使用的服务应用并行优化 |
| 英文服务优化 | ✅ 完成 | 英文病历生成跳过翻译步骤 |
| 异步执行问题修复 | ✅ 完成 | 解决FastAPI事件循环中的asyncio.run()问题 |

### 新增文件

1. **.trae/documents/病历生成流程性能优化计划.md**
   - 详细的性能分析和优化计划
   - 各阶段实施记录
   - 性能对比数据

2. **scripts/test_performance_optimization.py**
   - 性能优化测试脚本
   - 对比串行和并行模式性能

### 修改文件

1. **backend/services/medical_record_pipeline.py**
   - 添加`run_async`辅助函数
   - 添加`_process_visit_parallel`异步方法
   - 添加`_process_visit_serial`同步方法
   - 添加`_step_evidence_selection_async`异步方法
   - 添加`_step_terminology_normalization_async`异步方法
   - 添加性能监控日志
   - 添加条件性执行逻辑

2. **backend/services/llm_pipeline_service.py**
   - 添加`run_async`辅助函数
   - 添加`_normalize_terms_serial`方法
   - 添加`_normalize_terms_parallel`方法
   - 优化`_normalize_terms_stage`方法
   - 添加术语去重逻辑
   - 添加性能监控日志

3. **backend/services/llm_pipeline_service_en.py**
   - 重写`_normalize_terms_stage`方法
   - 添加`_normalize_terms_serial`方法
   - 添加`_normalize_terms_parallel_en`方法
   - 跳过翻译步骤优化

4. **backend/services/emr_generation_service.py**
   - 添加性能监控日志

5. **backend/services/terminology_service.py**
   - 优化`extract_and_normalize_terms_parallel`方法
   - 实现Code获取并行化

### 设计决策

**并行处理架构**：

```
┌─────────────────────────────────────────────────────┐
│              病历生成并行处理流程                      │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐                  │
│  │ 证据选择    │  │ 术语规范化  │  ← 并行执行       │
│  └─────────────┘  └─────────────┘                  │
│           ↘            ↙                            │
│            ┌─────────────┐                          │
│            │ 要素抽取    │                          │
│            └─────────────┘                          │
│                  ↓                                  │
│            ┌─────────────┐                          │
│            │ 病历生成    │                          │
│            └─────────────┘                          │
└─────────────────────────────────────────────────────┘
```

**术语规范化并行流程**：

```
术语识别 → 批量翻译 → 并行UMLS检索 → 批量LLM选择 → 并行获取Code
```

**异步执行解决方案**：

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

### 性能对比

| 服务 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 中文服务 | 串行处理 | 并行处理 | 减少30-50% |
| 英文服务 | 串行处理 | 并行处理（跳过翻译） | 减少40-60% |

**关键优化点**：

1. **步骤级并行**：证据选择和术语规范化并行执行
2. **批量处理**：批量翻译、批量UMLS检索、批量LLM选择
3. **并行Code获取**：使用asyncio.gather并行获取所有术语的code
4. **术语去重**：避免重复处理相同术语
5. **条件性跳过**：无数据时跳过相关步骤
6. **英文优化**：跳过翻译步骤，直接使用英文术语

### 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `TERMINOLOGY_PARALLEL_ENABLED` | True | 是否启用术语规范化并行模式 |
| `UMLS_MAX_CONCURRENT` | 5 | UMLS API最大并发请求数 |

### 日志输出示例

```
INFO: === 开始多阶段LLM处理: visit_id ===
INFO: 使用并行模式规范化术语
INFO: 批量翻译完成，耗时: 1.23秒
INFO: 并行UMLS检索完成，耗时: 5.67秒
INFO: 批量LLM选择完成，耗时: 3.45秒
INFO: 并行获取code完成，耗时: 2.34秒
INFO: 术语规范化完成，共规范化 8 个术语，耗时: 12.69秒
INFO: === 多阶段LLM处理完成: visit_id, 总耗时: 36.69秒 ===
```

### 后续优化

1. **LLM调用合并**：减少LLM调用次数
2. **预加载机制**：预加载常用术语和模板
3. **增量处理**：只处理变化的部分
4. **智能缓存**：基于语义相似度的缓存

---

## 2026-05-06 术语规范化并行优化

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 创建异步UMLS客户端 | ✅ 完成 | 新增 `AsyncUMLSClient` 类，支持并发HTTP请求 |
| 扩展翻译服务批量翻译 | ✅ 完成 | 添加 `batch_translate_zh_to_en()` 方法 |
| 实现批量LLM候选选择 | ✅ 完成 | 单次LLM调用为所有术语选择最佳候选 |
| 重构主流程为并行版本 | ✅ 完成 | 添加 `extract_and_normalize_terms_parallel()` 方法 |
| 添加配置项 | ✅ 完成 | 新增 `UMLS_MAX_CONCURRENT`、`TERMINOLOGY_PARALLEL_ENABLED` |
| 添加性能监控日志 | ✅ 完成 | 各阶段耗时日志输出 |
| 测试验证 | ✅ 完成 | 性能提升约 2x |

### 新增文件

1. **backend/services/umls/async_umls_client.py**
   - `AsyncUMLSClient` 异步UMLS客户端类
   - 使用 aiohttp 实现异步HTTP请求
   - 支持 `batch_search()` 并发检索多个术语
   - 信号量控制最大并发数，避免API限流

2. **scripts/test_parallel_terminology.py**
   - 并行优化测试脚本
   - 对比串行和并行模式性能
   - 测试批量翻译和异步UMLS检索

### 修改文件

1. **backend/services/translation_service.py**
   - 新增 `batch_translate_zh_to_en()` 方法
   - 利用 transformers pipeline 原生批量处理能力

2. **backend/services/terminology_service.py**
   - 导入 `AsyncUMLSClient` 和 `asyncio`
   - 新增 `async_umls_client` 属性
   - 新增 `_batch_select_candidates()` 方法：批量LLM候选选择
   - 新增 `extract_and_normalize_terms_parallel()` 方法：并行处理流程
   - 新增 `_extract_and_normalize_terms_parallel_with_cleanup()` 方法：带清理的包装方法
   - 新增 `_extract_and_normalize_terms_serial()` 方法：串行处理流程（原有逻辑）
   - 修改 `extract_and_normalize_terms()` 方法：支持 `use_parallel` 参数

3. **backend/config.py**
   - 新增 `UMLS_MAX_CONCURRENT: int = 5` 配置项
   - 新增 `TERMINOLOGY_PARALLEL_ENABLED: bool = True` 配置项

### 设计决策

**并行流水线架构**：

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

### 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `UMLS_MAX_CONCURRENT` | 5 | UMLS API最大并发请求数 |
| `TERMINOLOGY_PARALLEL_ENABLED` | True | 是否启用并行模式 |

### 使用方法

**自动使用**：

并行模式默认启用，无需手动调用。系统会自动检测并选择最优处理方式。

**手动切换**：

```python
# 使用并行模式（默认）
terms = term_service.extract_and_normalize_terms(text, use_parallel=True)

# 使用串行模式
terms = term_service.extract_and_normalize_terms(text, use_parallel=False)
```

**测试验证**：

```bash
# 激活环境
source med_env/Scripts/activate

# 运行测试
python scripts/test_parallel_terminology.py
```

---

## 2026-05-07 ASR转写文本纠错增强

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 扩展LLM提示词纠错范围 | ✅ 完成 | 修改 `emr_generation_with_role` 模板，支持所有拼音相似错误 |
| 添加纠错示例 | ✅ 完成 | 增加日常用语、同音字混淆、声调错误等示例 |
| 更新中英文提示词 | ✅ 完成 | 同时更新中文和英文版本的提示词模板 |

### 修改文件

1. **backend/services/llm/prompts.py**
   - 修改中文版 `emr_generation_with_role` 模板
   - 修改英文版 `emr_generation_with_role` 模板
   - 扩展ASR纠错指令，从医学术语扩展到所有拼音相似错误

### 设计决策

**纠错范围扩展**：

原有提示词主要针对医学术语纠错，现在扩展到所有拼音相似错误：

| 错误类型 | 示例 | 说明 |
|---------|------|------|
| 医学术语错误 | "阿莫希林"→"阿莫西林" | 药物名称、疾病名称等 |
| 日常用语错误 | "少吃闲的食物"→"少吃咸的食物" | 日常用语中的同音字错误 |
| 同音字混淆 | "堂尿病"→"糖尿病" | 拼音相同但汉字错误 |
| 声调错误 | "夫泻"→"腹泻" | 拼音相同但声调不同 |

**纠错原则**：

1. **识别所有拼音相似或同音字错误**：不限于医学术语
2. **结合上下文语境判断**：根据对话内容确定正确词汇
3. **静默纠错**：只在病历文本中使用纠正后的正确术语，不标注纠正过程

**实现方式**：

- 在病历生成阶段（`emr_generation_with_role` 阶段）由LLM自动识别和修正
- 不依赖静态词表，符合项目架构原则
- 利用LLM的上下文理解能力，提高纠错准确率

### 预期效果

**修改前**：
- ASR输出："少吃闲的食物"
- 病历生成："少吃闲的食物"（未纠正）

**修改后**：
- ASR输出："少吃闲的食物"
- 病历生成："少吃咸的食物"（自动纠正）

### 后续优化

1. **纠错效果评估**：收集实际纠错案例，评估准确率
2. **提示词优化**：根据实际效果调整纠错示例和指令
3. **多阶段纠错**：考虑在术语规范化阶段也加入纠错逻辑

---

## 2026-05-06 添加专门翻译小模型

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 创建翻译服务类 | ✅ 完成 | 新增 `TranslationService` 类，使用 Helsinki-NLP/opus-mt-zh-en 模型 |
| 添加配置项 | ✅ 完成 | 在 `backend/config.py` 添加翻译相关配置 |
| 更新依赖 | ✅ 完成 | 在 `requirements.txt` 添加 transformers、torch、sentencepiece |
| 集成到TerminologyService | ✅ 完成 | 修改 `_translate_term_to_english()` 优先使用翻译服务 |
| 创建测试脚本 | ✅ 完成 | 新增 `scripts/test_translation_service.py` 测试翻译功能 |
| 更新架构文档 | ✅ 完成 | 在 `docs/architecture.md` 添加翻译服务说明 |

### 新增文件

1. **backend/services/translation_service.py**
   - `TranslationService` 翻译服务类
   - 支持中英文翻译，使用专门翻译小模型
   - 自动降级机制，模型加载失败时返回 None

2. **scripts/test_translation_service.py**
   - 翻译服务测试脚本
   - 测试翻译功能和性能
   - 支持与LLM翻译对比测试

### 修改文件

1. **backend/config.py**
   - 新增 `TRANSLATION_ENABLED` 配置项（默认 True）
   - 新增 `TRANSLATION_MODEL` 配置项（默认 Helsinki-NLP/opus-mt-zh-en）
   - 新增 `TRANSLATION_DEVICE` 配置项（默认 cpu）

2. **backend/services/terminology_service.py**
   - 导入 `TranslationService`
   - 修改 `__init__()` 添加 `translation_service` 参数
   - 新增 `_init_translation()` 方法初始化翻译服务
   - 修改 `_translate_term_to_english()` 优先使用翻译服务

3. **requirements.txt**
   - 新增 `transformers>=4.30.0`
   - 新增 `torch>=2.0.0`
   - 新增 `sentencepiece>=0.1.99`

4. **docs/architecture.md**
   - 在目录结构中添加 `translation_service.py`
   - 在服务层表格中添加 TranslationService 说明
   - 在配置项表格中添加翻译相关配置

### 设计决策

**翻译模型选择**：

- 选择 Helsinki-NLP/opus-mt-zh-en 模型
- 模型大小约300MB，轻量级
- 专门针对中英文翻译优化
- CPU上也能快速推理

**降级策略**：

```
翻译服务可用 → 使用翻译小模型 → 快速翻译
翻译服务不可用 → 降级到LLM推理模型 → 兜底方案
```

**性能预期**：

| 方案 | 响应时间 | 备注 |
|------|---------|------|
| LLM推理模型 | 2-5秒 | 需要完整推理过程 |
| 翻译小模型 | 0.1-0.5秒 | 专门优化的翻译模型 |

**预期提升**：翻译速度提升 **5-50倍**

### 使用方法

**自动使用**：

翻译服务会自动初始化并集成到术语规范化流程中，无需手动调用。

**测试翻译服务**：

```bash
# 激活环境
source med_env/Scripts/activate

# 安装依赖
pip install transformers torch sentencepiece

# 测试翻译服务
python scripts/test_translation_service.py
```

**配置选项**：

```python
# backend/config.py 或 .env 文件
TRANSLATION_ENABLED = True  # 启用/禁用翻译服务
TRANSLATION_MODEL = "Helsinki-NLP/opus-mt-zh-en"  # 翻译模型
TRANSLATION_DEVICE = "cpu"  # 运行设备（cpu/cuda）
```

### 后续优化

1. **模型优化**：尝试量化模型减少内存占用
2. **缓存机制**：添加翻译结果缓存，避免重复翻译
3. **批量翻译**：支持批量翻译提升效率
4. **模型切换**：支持运行时切换翻译模型

---

## 2026-05-04 术语规范化流程重构

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 移除字典匹配依赖 | ✅ 完成 | 不再依赖静态词表进行术语匹配 |
| LLM识别口语术语 | ✅ 完成 | 新增 `identify_colloquial_terms` 方法 |
| UMLS优先规范化 | ✅ 完成 | UMLS成为主要术语规范化手段 |
| LLM选择UMLS候选 | ✅ 完成 | 从多个UMLS候选中选择最匹配的术语 |
| 移除LLM自评confidence | ✅ 完成 | LLM不再输出confidence，改用规则计算 |
| 中英文双语支持 | ✅ 完成 | 所有提示词支持中英文 |
| 文档更新 | ✅ 完成 | 更新 processing_flow.md 术语规范化流程 |

### 修改文件

1. **backend/services/terminology_service.py**
   - 移除 `_normalize_by_dict` 方法
   - 移除 `_find_similar_terms` 和 `_calculate_similarity` 方法
   - 移除 `_infer_term_type` 方法
   - 新增 `identify_colloquial_terms` 方法：LLM识别文本中的口语化医学术语
   - 重写 `normalize_term` 方法：UMLS优先，LLM兜底
   - 重写 `extract_and_normalize_terms` 方法：使用LLM识别术语而非遍历字典
   - 重写 `_llm_select_candidate` 方法：支持中英文提示词
   - 重写 `_normalize_by_llm` 方法：移除LLM输出的confidence，改用规则计算

2. **backend/services/llm/prompts.py**
   - 删除中文版 `term_normalization` 模板（已废弃）
   - 删除英文版 `term_normalization` 模板（已废弃）

3. **docs/processing_flow.md**
   - 更新术语规范化流程图
   - 更新详细步骤表格
   - 更新术语规范化优先级
   - 新增术语识别提示词模板说明
   - 新增UMLS候选选择提示词模板说明

### 设计决策

**UMLS优先原则**：

- UMLS作为主要术语规范化手段，提供标准医学术语概念编码
- LLM仅在UMLS无结果时作为兜底方案
- 移除静态字典匹配，提高泛用性

**置信度计算规则**：

| 来源 | 置信度计算方式 |
|------|----------------|
| UMLS | `min(0.95, 0.6 + score * 0.35)`，基于UMLS匹配分数 |
| LLM规范化成功 | 固定 0.5（兜底方案，置信度较低） |
| LLM规范化失败 | 固定 0.3（保留原词） |

**流程对比**：

| 项目 | 旧流程 | 新流程 |
|------|--------|--------|
| 术语识别 | 遍历字典术语检查文本 | LLM识别文本中的口语术语 |
| 优先级 | 字典 > UMLS > LLM | UMLS > LLM > 保留原词 |
| 泛用性 | 仅能识别字典中已有的术语 | 可识别任意医学术语 |
| confidence | LLM自评（不可靠） | 规则计算（可靠） |

**新流程**：

```
文本 → LLM识别口语术语 → UMLS检索标准术语 → LLM选择最佳候选 → 返回规范化结果
```

---

## 2026-05-04 英文LLM提示词支持

### 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| 英文LLM Pipeline服务 | ✅ 完成 | 新增 `LLMPipelineServiceEnglish` 类，继承自中文版本 |
| 英文提示词 | ✅ 完成 | 全部4个阶段的提示词改为英文（角色标注、术语规范化、字段抽取、病历生成） |
| 英文字段映射 | ✅ 完成 | XML标签及字段映射改为英文 |
| 英文说话人标签 | ✅ 完成 | 使用 `[Doctor]`/`[Patient]` 替代 `[医生]`/`[患者]` |
| 英文模板生成 | ✅ 完成 | 模板兜底方案改为英文标签 |
| 英文调试模式 | ✅ 完成 | 调试交互提示和阶段描述改为英文 |
| 英文规则推断 | ✅ 完成 | 规则推断使用英文关键词 |
| API语言路由 | ✅ 完成 | API端点根据 `visit.language` 自动选择中/英文服务 |

### 新增文件

1. **backend/services/llm_pipeline_service_en.py**
   - `LLMPipelineServiceEnglish` 类，继承自 `LLMPipelineService`
   - 重写所有提示词构建方法：`_build_role_annotation_prompt`、`_build_normalization_prompt`、`_build_extraction_prompt`、`_build_emr_generation_prompt`
   - 重写 `_template_emr_generation`：使用英文字段标签
   - 重写 `_assign_speakers_from_unlabeled`：支持 `[Doctor]`/`[Patient]` 标签
   - 重写 `_extract_evidence_traces`：使用英文XML标签和说话人标签匹配
   - 重写 `_infer_roles_by_rules`：使用英文关键词进行规则推断
   - 重写 `_debug_interact`：英文调试交互界面
   - 重写 `get_all_prompts`：英文阶段描述和指引
   - 重写 `process_stage_with_user_input`：英文阶段描述

### 修改文件

1. **backend/api/emr.py**
   - 导入 `LLMPipelineServiceEnglish`
   - 导入 `Visit` 模型用于语言检测
   - `/process` 端点：根据 `visit.language` 选择服务
   - `/pipeline/process` 端点：根据 `visit.language` 选择服务
   - `/debug/prompts/{visit_id}` 端点：根据 `visit.language` 选择服务
   - `/debug/process-stage` 端点：根据 `visit.language` 选择服务

2. **backend/services/__init__.py**
   - 导出 `LLMPipelineServiceEnglish`

### 设计决策

**继承而非修改**：

- `LLMPipelineServiceEnglish` 继承自 `LLMPipelineService`，遵循开闭原则
- 仅重写包含中文特定逻辑的方法，共享所有公共业务逻辑
- 遵循单一职责原则：中文和英文版本的提示词逻辑分离

**语言切换机制**：

- 通过 `Visit.language` 字段判断语言（`"en"` / `"zh"`）
- API端点在每次请求时检查语言并实例化对应的服务类
- 与前端 `debugLanguageSelect` 下拉框和 `CreateFromTextRequest.language` 对接

**英文提示词设计**：

- XML标签使用英文：`<chief_complaint>`、`<diagnosis>` 等
- 说话人标签使用英文：`[Doctor]`、`[Patient]`
- 生成的病历字段使用英文标签：`Chief Complaint`、`Diagnosis` 等
- 符合国际医疗病历书写规范（SOAP格式）

### 架构影响

```
LLMPipelineService (中文)
    ├── 继承
    └── LLMPipelineServiceEnglish (英文)
            ├── 重写: _build_role_annotation_prompt
            ├── 重写: _build_normalization_prompt
            ├── 重写: _build_extraction_prompt
            ├── 重写: _build_emr_generation_prompt
            ├── 重写: _template_emr_generation
            ├── 重写: _assign_speakers_from_unlabeled
            ├── 重写: _extract_evidence_traces
            ├── 重写: _infer_roles_by_rules
            ├── 重写: _debug_interact
            ├── 重写: get_all_prompts
            └── 重写: process_stage_with_user_input
```

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

当前实现中，证据置信度使用固定默认值0.8。未来可扩展为LLM输出或基于规则计算。

**ASR置信度的作用**：

ASR输出的置信度存储在`TranscriptTurn.confidence`字段中，用于过滤低置信度的对话轮次（阈值< 0.5），以及在规则匹配评分中作为权重因子。

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

---

## 2026-05-20 BugFix: 调试模式病历未保存到数据库

### 问题描述

调试模式完成所有阶段后，前端显示"所有阶段处理完成"，但没有生成病历（前端没有显示病历）。

### 问题分析

通过代码审查发现，调试模式的 `process_stage_with_user_input()` 方法在 `verification` 阶段完成后，只返回了 `completed: True`，但**没有调用 `_save_emr_record()` 方法保存病历到数据库**。

正常模式（`process_visit()` 方法）在处理完所有阶段后会调用：
```python
self._save_evidence_spans_from_emr(emr_final, visit_id)
self._save_emr_record(emr_final, visit_id)
```

但调试模式缺少这一步。

### 修复内容

在 `process_stage_with_user_input()` 方法的 `verification` 阶段处理逻辑中，添加病历保存逻辑：

1. 从 context 中获取 `subjective`、`objective`、`assessment`、`plan`、`assessment_items`、`plan_items`
2. 构建 `emr_final`（优先使用 `soap_final`，否则使用各部分数据）
3. 调用 `_normalize_emr_format()` 格式化病历
4. 调用 `_save_emr_record()` 保存到数据库
5. 返回结果中新增 `emr_saved: True` 标记

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 修改 `process_stage_with_user_input()` 方法的 `verification` 分支
   - 新增病历保存逻辑

### 预期效果

调试模式完成所有阶段后，病历会正确保存到数据库，前端可以正常显示病历内容。

### 后续修复：证据溯源缺失

**问题**：调试模式生成的病历没有证据溯源。

**原因**：
1. `fact_extraction` 阶段没有保存原子事实到数据库
2. `verification` 阶段没有填充证据溯源（`_enrich_evidence_traces`）和保存证据溯源（`_save_evidence_spans_from_emr`）

**修复内容**：

1. 在 `fact_extraction` 阶段添加 `_save_atomic_facts(facts_data, visit_id)` 保存原子事实到数据库
2. 在 `verification` 阶段添加：
   - 从数据库加载原子事实：`fact_service.get_facts_by_visit(visit_id)`
   - 填充证据溯源：`_enrich_evidence_traces(emr_final, fact_records, turns)`
   - 保存证据溯源：`_save_evidence_spans_from_emr(emr_final, visit_id)`

## 2026-05-20 BugFix: 商汤API调用400错误

### 问题描述

调用商汤API时出现400 Bad Request错误，导致LLM调用失败。

### 问题分析（已修正）

**初步分析（错误）**：
误以为商汤API使用不同的参数格式（`max_new_tokens`、`{"enabled": true}`）

**实际原因**：
根据官方文档，DeepSeek V4 Flash模型的API格式是正确的：
- 模型ID：`deepseek-v4-flash`
- API endpoint：`https://token.sensenova.cn/v1/chat/completions`
- thinking参数格式：`{"type": "enabled", "reasoning_effort": "high"}`（正确）
- 使用`max_tokens`参数（正确）
- 支持JSON模式`response_format`（正确）

### 修复内容

1. **撤销错误的参数格式修改**，恢复原有正确的格式
2. **添加详细的错误日志**：
   - 在HTTP错误时获取API返回的具体错误内容
   - 记录完整的请求payload便于调试

### 修改文件

1. **backend/services/llm/openai_compatible_adapter.py**
   - 撤销商汤API适配逻辑
   - 恢复原有参数格式
   - 添加`HTTPStatusError`详细错误日志
   - 添加请求payload日志

### 后续排查

需要查看详细错误日志来确定400错误的具体原因：
- API Key问题
- 模型未开通
- 其他参数问题

### 真正原因（已定位）

通过详细错误日志发现：
```
'messages' must contain the word 'json' in some form, to use 'response_format' of type 'json_object'.
```

**问题**：当使用 `response_format: {"type": "json_object"}` 时，messages 中必须包含 "json" 这个词，这是 OpenAI API 的要求。

### 最终修复

在启用 json_mode 时，在 messages 中添加 system message：
```python
if use_json_mode:
    messages.append({"role": "system", "content": "请以JSON格式输出结果。"})
```

### 修改文件

1. **backend/services/llm/openai_compatible_adapter.py**
   - 在 json_mode 启用时添加包含 "json" 关键词的 system message

## 2026-05-20 BugFix: 事实合并导致所有事实被删除

### 问题描述

病历生成后内容为空，证据溯源缺失。

### 问题分析

通过日志发现：
```
事实收束完成: 合并=20, 冲突=0, 补判=0, 最终=0
从数据库查询到 0 条原子事实用于阶段3规范化
```

**根本原因**：LLM返回的事实收束结果中，`merged_from` 列表包含了 `fact_id` 本身：
```json
{
  "fact_id": "fact_xxx",
  "merged_from": ["fact_xxx"],
  ...
}
```

在合并逻辑中，代码会删除 `merged_from` 中的所有事实，包括要保留的事实本身！

```python
for from_id in merged_from_ids:
    from_fact = self.db.query(AtomicFact).filter(AtomicFact.fact_id == from_id).first()
    if from_fact:
        ...
        self.db.delete(from_fact)  # 这里删除了保留的事实！
```

### 修复内容

在 `_apply_fact_merges()` 方法中添加检查，跳过 `from_id` 等于 `keep_fact_id` 的情况：

```python
for from_id in merged_from_ids:
    if from_id == keep_fact_id:
        continue  # 跳过要保留的事实
    from_fact = self.db.query(AtomicFact).filter(AtomicFact.fact_id == from_id).first()
    ...
```

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 修改 `_apply_fact_merges()` 方法，添加跳过保留事实的逻辑

### 预期效果

事实合并后，保留的事实不会被错误删除，病历生成和证据溯源正常工作。

## 2026-05-20 BugFix: ASR修正索引映射失败

### 问题描述

日志显示：
```
解析到 2 个清洗后的turn
ASR修正跳过: 找不到turn_index=0对应的turn
ASR修正跳过: 找不到turn_index=1对应的turn
```

### 问题分析

**根本原因**：LLM返回的 `turn_id` 是相对于当前 segment 的位置索引（0, 1, 2...），而代码使用 `turn_by_index = {turn.turn_index: turn for turn in segment}` 进行查找，期望的是全局的 `turn_index`。

当 segment 不是从 `turn_index=0` 开始时（例如 segment 包含 turn_index 为 100 和 101 的两个 turn），就会出现找不到对应 turn 的情况。

**示例**：
- segment 包含 turn_index 为 100 和 101 的两个 turn
- `_format_segment` 输出 `[#100]` 和 `[#101]`
- LLM 返回 `turn_id: 0` 和 `turn_id: 1`（相对于 segment 的位置）
- 代码用 `turn_by_index.get(0)` 查找，找不到 turn_index=100 的 turn

### 修复内容

在 `_parse_cleaning_response()` 和 `_apply_asr_corrections()` 方法中添加回退逻辑：

1. 添加调试日志显示 segment 中可用的 turn_index 列表
2. 当 `turn_by_index.get(turn_id)` 找不到时，尝试按位置匹配：`segment[i]` 对应 `turn_id=i`
3. 记录回退匹配的详细日志

```python
turn = turn_by_index.get(turn_id)
if not turn:
    if i < len(segment):
        turn = segment[i]
        logger.warning(
            f"turn_id={turn_id}不在segment索引中, "
            f"回退到位置匹配: 位置{i} -> turn_index={turn.turn_index}"
        )
    else:
        logger.warning(
            f"turn_id={turn_id}匹配失败: 位置{i}超出segment范围(len={len(segment)})"
        )
        continue
```

### 修改文件

1. **backend/services/llm_pipeline_service.py**
   - 修改 `_parse_cleaning_response()` 方法，添加索引映射回退逻辑
   - 修改 `_apply_asr_corrections()` 方法，添加索引映射回退逻辑

### 预期效果

ASR修正和角色识别能够正确匹配到对应的 turn，不再出现"找不到turn"的警告。
