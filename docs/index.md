---
layout: home

hero:
  name: "mem0 Memory Service for OpenClaw"
  text: "Your AI Agents Never Forget"
  tagline: "Real-time memory capture, intelligent recall, and nightly AutoDream consolidation — powered by mem0, AWS Bedrock, OpenSearch & S3 Vectors"
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: View on GitHub
      link: https://github.com/norrishuang/mem0-memory-service

features:
  - icon: 🧠
    title: Semantic Memory
    details: Store and retrieve memories using natural language queries powered by vector embeddings
  - icon: 🌙
    title: AutoDream Consolidation
    details: "Every night, AutoDream does what human brains do during sleep — consolidates the day's short-term memories into long-term knowledge, and quietly discards what's no longer relevant."
  - icon: 🗄️
    title: Flexible Vector Store
    details: "Supports AWS OpenSearch (default) and AWS S3 Vectors as the vector backend — switch with a single environment variable. LLM inference and embeddings run on AWS Bedrock, keeping everything within your AWS account."
  - icon: 🌊
    title: MemoryStream
    details: "Conversations flow into mem0 continuously — snapshotted every 5 min, digested every 15 min. No context is lost between sessions."
  - icon: 🤖
    title: Multi-Agent Support
    details: Isolated memory spaces per agent, with cross-agent search capability. Memories tagged as `experience` are automatically shared across all agents — building a collective knowledge base.
  - icon: 🔌
    title: Zero-Config Agent Onboarding
    details: Enable the mem0-memory Skill once — every agent automatically inherits memory behavior (diary writing, MEMORY.md maintenance, retrieval). No AGENTS.md edits needed.
  - icon: 🛠️
    title: Simple CLI & REST API
    details: Easy-to-use CLI for all operations, plus a FastAPI REST server for programmatic access
  - icon: 🔒
    title: Privacy-First, Self-Hosted
    details: Fully self-hosted on your own AWS infrastructure. No data leaves your account — telemetry is disabled by default, and all LLM calls go through AWS Bedrock with your own IAM credentials.
---
