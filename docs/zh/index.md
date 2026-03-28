---
layout: home

hero:
  name: "mem0 记忆服务"
  text: "为 OpenClaw Agent 提供跨 Session 持久记忆"
  tagline: 基于 mem0 + Amazon Bedrock，解决 AI Agent 最核心的记忆痛点
  actions:
    - theme: brand
      text: 快速开始
      link: /zh/guide/getting-started
    - theme: alt
      text: GitHub
      link: https://github.com/norrishuang/mem0-memory-service

features:
  - icon: 🧠
    title: 跨 Session 持久记忆
    details: 两层流水线——session_snapshot 每 5 分钟写日记文件；auto_digest --today 每 15 分钟将新内容分批直接写入 mem0（无本地 LLM），同时每天一次全量 LLM 提炼产出高质量回顾记忆。上下文永不丢失。
  - icon: 🤖
    title: 多 Agent 隔离记忆
    details: 支持多个 Agent 并行运行（agent1 / agent2 / agent3 等），各 Agent 记忆空间完全隔离、互不干扰，从 openclaw.json 自动发现所有 Agent。标记为 `experience` 的记忆自动在所有 Agent 间共享，沉淀团队集体经验。
  - icon: 🔄
    title: 短期 + 长期分层存储
    details: 三条路径写入长期记忆：memory_sync 当天同步 MEMORY.md（精选知识）、archive 7 天后升级活跃短期记忆、Agent 随时主动写入。7 天内基于活跃度智能归档。
  - icon: 💰
    title: 低成本向量存储（S3 Vectors）
    details: 支持 Amazon S3 Vectors 作为向量后端，按实际用量付费，成本极低。同时也支持 OpenSearch。
  - icon: ⚡
    title: 全自动运维，成本降低 96%
    details: 改为每天一次完整日记提炼（原每 15 分钟增量），LLM 调用次数降低 96%，记忆质量更高。MEMORY.md 同步基于 hash 去重，内容未变化时零额外调用。
  - icon: 🔌
    title: 一次启用，全 Agent 生效
    details: 启用 mem0-memory Skill，所有 Agent 自动继承完整记忆行为（写日记、维护 MEMORY.md、检索上下文）。无需修改任何 AGENTS.md。
  - icon: 🛠️
    title: 简单易用的 CLI 与 REST API
    details: 提供完整的 CLI 命令行工具和 FastAPI REST 接口，支持所有记忆操作，方便集成到任意工作流。
---
