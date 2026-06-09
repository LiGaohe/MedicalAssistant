## 修复任务清单

- [x] 1. 修改 `direct_soap_generation` 提示词：增加反幻觉约束段落（5条约束）
- [x] 2. 修改 `free_soap_generation` 提示词：增加否定性陈述、药物细节、诊断确定性约束（3条约束）
- [x] 3. 修改 `soap_structuring` 提示词：增加否定翻转检测和数值一致性约束（2条约束）
- [x] 4. 运行benchmark验证幻觉率下降（在verify阶段执行）
