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
    details: OpenClaw 每次对话都是独立 session，本服务打通 session 之间的隔阂——每 5 分钟自动快照对话，LLM 定期提炼关键事实存入向量库，上下文永不丢失。
  - icon: 🤖
    title: 多 Agent 隔离记忆
    details: 支持多个 Agent 并行运行（dev / blog / pjm 等），各 Agent 记忆空间完全隔离、互不干扰，自动扫描发现所有 Agent。
  - icon: 🔄
    title: 短期 + 长期分层存储
    details: 对话先保存为日记文件（短期），再由 LLM 自动提炼关键事实写入向量库（长期）。7 天后基于活跃度智能归档。
  - icon: 💰
    title: 低成本向量存储（S3 Vectors）
    details: 支持 Amazon S3 Vectors 作为向量后端，按实际用量付费，成本极低。同时也支持 OpenSearch。
  - icon: ⚡
    title: 全自动运维
    details: systemd timer 全程自动化：每 5 分钟会话快照、每 15 分钟日记摘要、每天短期记忆归档。零人工干预。
---
