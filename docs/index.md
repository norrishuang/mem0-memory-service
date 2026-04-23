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
    details: "Conversations flow into mem0 continuously — captured in real-time by the openclaw-plugin, digested every 15 min. No context is lost between sessions."
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
  - icon: 📊
    title: Token Tracking & Cost Visibility
    details: Every LLM call is tracked — input/output tokens logged per request, per agent, per user. Identify expensive operations, estimate Bedrock costs, and optimize pipeline frequency with real data.
  - icon: 🎯
    title: Targeted Memory Extraction
    details: "Pass a custom extraction prompt per /memory/add call to guide mem0 toward a specific dimension — tasks, decisions, config, or any custom category. auto_digest automatically runs a dedicated task-extraction pass on every session block, building a clean `category=task` index for precise work recall."
  - icon: 🔍
    title: Built-in Audit Logging
    details: All API calls written to daily JSONL files in audit_logs/. Plug in Fluent Bit, Vector, CloudWatch, or any file-tailing shipper — no code changes needed. Audit logs rotate daily and auto-expire after 30 days.
---
