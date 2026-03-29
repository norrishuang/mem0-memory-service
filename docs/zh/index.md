---
layout: home

hero:
  name: "mem0 记忆服务"
  text: "AI Agent 的永久记忆层"
  tagline: "实时记忆捕获、语义召回，每晚 AutoDream 自动沉淀 — 基于 mem0 + AWS"
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
    details: 对话内容持续被捕获并提炼为记忆——近期上下文数分钟内即可召回，每日全量提炼产出更高质量的长期记忆。上下文永不丢失。
  - icon: 🤖
    title: 多 Agent 隔离记忆
    details: 支持多个 Agent 并行运行（agent1 / agent2 / agent3 等），各 Agent 记忆空间完全隔离、互不干扰，从 openclaw.json 自动发现所有 Agent。标记为 `experience` 的记忆自动在所有 Agent 间共享，沉淀团队集体经验。
  - icon: 🌙
    title: AutoDream 记忆沉淀
    details: "每晚 AutoDream 像人类大脑在睡眠中做的那样——把当天的短期记忆巩固为长期知识，悄悄清理不再相关的内容。"
  - icon: 💰
    title: 低成本向量存储（S3 Vectors）
    details: 支持 Amazon S3 Vectors 作为向量后端，按实际用量付费，成本极低。同时也支持 OpenSearch。
  - icon: ⚡
    title: 实时捕获
    details: "每次对话都被持续快照并在数分钟内提炼。Session 之间不会丢失任何内容。"
  - icon: 🔌
    title: 一次启用，全 Agent 生效
    details: 启用 mem0-memory Skill，所有 Agent 自动继承完整记忆行为（写日记、维护 MEMORY.md、检索上下文）。无需修改任何 AGENTS.md。
  - icon: 🛠️
    title: 简单易用的 CLI 与 REST API
    details: 提供完整的 CLI 命令行工具和 FastAPI REST 接口，支持所有记忆操作，方便集成到任意工作流。
---
