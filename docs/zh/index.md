---
layout: home

hero:
  name: "mem0 记忆服务"
  text: "AI Agent 的永久记忆层"
  tagline: "实时记忆捕获、语义召回，每晚 AutoDream 自动沉淀 — 基于 mem0、AWS Bedrock、OpenSearch 与 S3 Vectors"
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
    title: 灵活的向量存储后端
    details: 支持 AWS OpenSearch（默认）和 AWS S3 Vectors 作为向量后端，一个环境变量即可切换。LLM 推理和向量嵌入均运行在 AWS Bedrock 上，数据全程留在你的 AWS 账户内。
  - icon: 🌊
    title: MemoryStream 记忆流
    details: "对话持续流入 mem0——每 5 分钟快照，每 15 分钟提炼。Session 之间，上下文永不丢失。"
  - icon: 🔌
    title: 一次启用，全 Agent 生效
    details: 启用 mem0-memory Skill，所有 Agent 自动继承完整记忆行为（写日记、维护 MEMORY.md、检索上下文）。无需修改任何 AGENTS.md。
  - icon: 🛠️
    title: 简单易用的 CLI 与 REST API
    details: 提供完整的 CLI 命令行工具和 FastAPI REST 接口，支持所有记忆操作，方便集成到任意工作流。
  - icon: 🔒
    title: 隐私优先，完全自托管
    details: 完全部署在你自己的 AWS 基础设施上，数据永不离开你的账户。遥测默认关闭，所有 LLM 调用通过 AWS Bedrock 走你自己的 IAM 凭证。
  - icon: 📊
    title: Token 追踪与成本可视化
    details: 每次 LLM 调用都被追踪——按请求、按 Agent、按用户记录输入/输出 token 数。识别高成本操作，估算 Bedrock 费用，用真实数据优化 pipeline 频率。
  - icon: 🎯
    title: 定向记忆抽取
    details: "每次 /memory/add 调用可传入自定义 extraction prompt，引导 mem0 按特定维度提炼记忆——任务、决策、配置，或任意自定义分类。auto_digest 对每个 session block 自动执行专项任务抽取 pass，构建干净的 `category=task` 索引，让"最近做了哪些工作"的查询精准命中。"
  - icon: 🔍
    title: 内置审计日志
    details: 所有 API 调用写入 audit_logs/ 目录下的每日 JSONL 文件。接入 Fluent Bit、Vector、CloudWatch 或任何支持文件 tail 的采集工具，无需修改代码。日志按天滚动，30 天后自动过期。
---
