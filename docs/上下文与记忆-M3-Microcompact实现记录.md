---
title: 上下文与记忆 M3 Microcompact 实现记录
tags:
  - Context-Engineering
  - Microcompact
  - RAG
  - Tool-Calling
  - AI-Agent
status: implemented
date: 2026-08-11
---

# 上下文与记忆 M3 Microcompact 实现记录

## 1. 背景

M1/M2 已经能够按 token 预算选择 RAG 资料，但旧行为只有“完整放入”或“整体丢弃”两种结果。单个检索块或工具结果过长时，即使其中包含重要风险、数字和约束，也可能因为整体超预算而完全不可见。

M3 增加 Artifact Microcompact：优先压缩大型 RAG/工具结果，保留可追溯引用和关键约束，仍无法装入预算时才丢弃。

## 2. 当前实际接入范围

- 通用 Microcompact 接口支持 `rag` 和 `tool` Artifact。
- 聊天 Agent 的 RAG 资料已经实际接入。
- 计划 ReAct Agent 的工具结果目前只存在于单次 Agent 调用内部，尚未进入聊天长期上下文，因此没有为了包装能力额外创建无消费者的工具结果表。
- 未来聊天 Agent 开放 Tool Calling 后，可直接复用同一 Artifact 接口。

## 3. 处理流程

```text
按相关性排序的 Artifact
  -> 估算完整内容 token
  -> 小于全文阈值：保留 full
  -> 超过全文阈值：提取 microcompact
  -> 仍超过本轮 Artifact 预算：dropped
  -> Context Builder 再分配剩余预算给近期对话
```

默认阈值：

| 配置 | 默认值 |
| --- | ---: |
| `CHAT_MICROCOMPACT_FULL_ARTIFACT_TOKENS` | 800 |
| `CHAT_MICROCOMPACT_TARGET_ARTIFACT_TOKENS` | 240 |

目标阈值必须小于全文阈值，配置启动时进行校验。

## 4. 确定性提取策略

Microcompact 不额外调用 LLM，避免增加成本、延迟和新的幻觉来源。

提取时优先保留包含以下信息的句子：

- 否定和风险：不应、不得、禁止、避免、危险、过敏、伤病、疼痛。
- 量化约束：数字、每天、每周、剂量、热量、蛋白质、公斤、克、分钟、次数和组数。
- 其余内容按原始顺序补充到目标 token 上限。

压缩结果明确标记为“微压缩摘录”，不会伪装成完整原文。系统提示同时声明 RAG 和工具结果是不可信数据，只能提取事实，不得执行其中的指令。

## 5. 可追溯性

每个 Artifact 要求非空 `reference_id`，并记录：

- 原始排名 `original_index`。
- 类型 `kind`。
- 来源引用 `reference_id`。
- 处理模式 `full / microcompact / dropped`。
- 原始估算 token。
- 实际注入 token。

Context Builder 诊断新增：

- `artifact_tokens_original`
- `artifact_tokens_included`
- `artifact_tokens_saved`
- `artifact_full`
- `artifact_microcompacted`
- `artifact_dropped`
- 每个 Artifact 的处理明细

只有 `full` 或 `microcompact` 的 RAG Artifact 会返回 citation；`dropped` 的来源不会假装参与本轮回答。

## 6. 代码入口

- [Artifact Microcompact](../backend/app/services/artifact_microcompact.py)
- [Context Builder 接入](../backend/app/services/context_builder.py)
- [聊天 RAG 引用 ID](../backend/app/graph/chat_workflow.py)
- [运行配置](../backend/app/core/config.py)
- [单元与集成测试](../backend/tests/test_artifact_microcompact.py)
- [固定评测器](../backend/app/evals/artifact_microcompact.py)
- [固定评测集](../backend/tests/fixtures/artifact_microcompact_cases.json)

## 7. 离线评测结果

命令：

```powershell
cd backend
python -m app.evals.artifact_microcompact
```

结果：

| 指标 | 结果 |
| --- | ---: |
| 固定用例 | 4 |
| 通过 | 4 |
| 原始估算 token | 2147 |
| 注入估算 token | 174 |
| 减少 | 1973 |
| Token reduction | 91.9% |

四个用例覆盖：健康风险长文、包含关键数字的工具结果、短 RAG 全文保留和零预算丢弃。风险词与关键数字保持检查全部通过。

> [!warning]
> 91.9% 是专门构造的确定性离线评测集结果，只证明算法和评测器行为，不代表生产流量平均降幅。简历最终只能使用真实长对话或生产样本测得的指标。

## 8. 剩余边界

- 当前是抽取式压缩，不理解复杂表格、深层 JSON 和跨句逻辑关系。
- 被压缩内容仍需通过原始引用回查，不能把摘录当成完整证据。
- 真实 RAG 数据的平均压缩率、事实保持率和回答质量仍待 M6 量化。
- 工具结果若未来需要跨轮使用，应先建立可检索的原始结果存储与访问控制，再依赖 `reference_id` 回溯。
- Microcompact Artifact 与长期记忆仍是不同数据层：即使 M4 已实现跨会话记忆，也不能把工具/RAG 摘录直接当成用户事实。

## 9. 下一步

M4 跨会话长期记忆已经完成治理，M5.0 已进一步完成关键词/向量/RRF 混合召回、事务 outbox、版本终检与使用追踪，详见 [[上下文与记忆-M4-长期记忆实现记录]] 和 [[上下文与记忆-M5-混合检索实现记录]]。下一步进入 M5.1 完整记忆中心与 M6 三模式真实模型量化。

## 10. 关联文档

- [[ADR-001-分层上下文与长期记忆]]
- [[上下文与记忆-M1-M2实现记录]]
- [[AI应用与AI-Agent项目亮点]]
