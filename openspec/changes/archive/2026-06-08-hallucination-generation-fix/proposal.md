## Why

管线在草稿生成和结构化阶段产生幻觉内容（编造对话中未提及的事实），导致下游幻觉检查和字段修订阶段需要额外修正。当前幻觉残留清理已修复，但幻觉产生问题仍存在：样本10333432中，full配置幻觉率0.125，高频幻觉包括"曾去医院检查"（推断）、"暂无咽喉炎"（编造否定）、"抗病毒药物50mg规格"（编造药物细节）。

## What Changes

- 强化 `direct_soap_generation` 提示词：增加反幻觉约束（当前缺少"不得推断或添加"的约束）
- 强化 `free_soap_generation` 提示词：增加否定性陈述约束和药物/检查细节约束
- 强化 `soap_structuring` 提示词：增加"不得从对话中推断新内容"的约束，强调否定翻转检测

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无已有spec需要修改，本次仅修改提示词模板文本）

## Impact

- `backend/services/llm/prompts/soap_generation.py`：3个提示词模板文本修改
- 下游影响：草稿生成和结构化阶段的LLM输出将更忠实于对话原文，幻觉检查阶段应检测到更少的幻觉
