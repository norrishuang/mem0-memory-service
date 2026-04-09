# 快速开始

## 概述

mem0 Memory Service for OpenClaw 是基于 [mem0](https://github.com/mem0ai/mem0) 的统一记忆层，为 AI Agent 提供持久化语义记忆存储。

Agent 可以通过对话自动存储和检索记忆，无需手动管理文件。

### 设计理念

mem0 的核心优势是**记忆提取和去重**——从对话中自动抽取关键事实、智能合并相似记忆、提供语义检索。但 mem0 本身不区分"短期事件"和"长期知识"。

本服务在 mem0 之上增加了一层**记忆生命周期管理**：

```
mem0 负责：    语义提取、智能去重、向量检索
本服务负责：   分层存储、生命周期管理、活跃度归档
```

### 架构

```
OpenClaw Agents (agent1, agent2, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (Docker / systemd)  │
│                      │
│  分层记忆:           │  长期记忆 (无 run_id)
│  - 长期: 技术决策、  │  短期记忆 (run_id=日期)
│    经验教训、偏好    │  归档: 活跃度判断
│  - 短期: 当天讨论    │  升级/删除
└──────────┬───────────┘
           │
     ┌─────▼─────┐       ┌──────────────────┐
     │   mem0    │──────▶│  LLM (Bedrock)    │
     │           │──────▶│  Embedder (Titan) │
     └─────┬─────┘       └──────────────────┘
           ▼
   OpenSearch / S3 Vectors
```

## 前置条件

- **Docker 20.10+** 和 **docker compose** (v2)
- **OpenSearch** 集群（2.x 或 3.x，需启用 k-NN 插件）或 **AWS S3 Vectors**
- **AWS Bedrock** 访问权限（或修改 `config.py` 使用其他 LLM/Embedder）
- **AWS IAM 权限** — 部署环境需要：
  - `bedrock:InvokeModel` 和 `bedrock:InvokeModelWithResponseStream`（Embedding 和 LLM 模型）
  - 如果使用 S3Vectors：`s3vectors:*`（对应 bucket 资源）
  - EC2 用户：将 IAM Role 附加到实例即可，无需在 .env 中配置 Access Key

## 一键部署

想快速尝试？把下面这段话发给你的 OpenClaw AI 助手，即可部署一套基于**本地 pgvector** 的记忆系统——无需任何云端向量数据库，记忆数据持久化在本地。

当你准备好扩展时，可以随时使用内置迁移工具**平滑迁移**到 S3 Vectors 或 OpenSearch，数据不会丢失。

---

> 帮我部署 **mem0 Memory Service**，使用本地 pgvector 模式。
>
> 步骤：
> 1. `git clone https://github.com/norrishuang/mem0-memory-service.git && cd mem0-memory-service`
> 2. 运行 `./tools/install.sh` — 自动检测 AWS Region，使用本地 pgvector（无需云端向量数据库）
> 3. 验证：`curl http://localhost:8230/health`
> 4. 在 OpenClaw 设置 → Skills → 启用 mem0-memory

---

安装脚本自动处理：AWS Region 探测、默认配置、Docker 容器启动（含 PostgreSQL + pgvector）、Skill 安装，无需手动配置任何内容。

> **前提条件**：Docker 20.10+（Linux/macOS 未安装时自动安装），AWS Bedrock 访问权限（EC2 IAM Role 或已配置凭证）。
> 开始体验无需 OpenSearch 或 S3 Vectors。

> **之后想迁移？** 使用 `tools/migrate_between_stores.py` 将记忆数据迁移到 S3 Vectors 或 OpenSearch，数据零丢失。参见[迁移指南](../guide/migration)。

## 部署方式

根据你的环境选择合适的部署方式：

### 🚀 方式 A：本地 pgvector（最快，无需云端向量数据库）

只想快速体验？使用内置的 PostgreSQL + pgvector，无需配置 S3 Vectors 或 OpenSearch，只需要 AWS Bedrock（LLM + Embedding）。

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
cp .env.example .env  # 设置 VECTOR_STORE=pgvector + AWS Bedrock 凭证
docker compose --profile pgvector up -d
```

→ [详细指南：Docker + pgvector 快速启动](../deploy/docker#最快启动本地-pgvector无需云服务)

---

### 🐳 方式 B：Docker（推荐）

生产就绪。使用 Docker Compose，支持 S3 Vectors、OpenSearch 或 pgvector。所有 Pipeline 在容器内以 cron 任务运行。

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
cp .env.example .env  # 配置 VECTOR_STORE + 凭证
docker compose up -d
```

→ [详细指南：Docker 部署](../deploy/docker)

---

### ⚙️ 方式 C：systemd（高级）

直接在宿主机运行，不依赖 Docker。适合不便使用 Docker 的环境。

→ [详细指南：systemd 部署](../deploy/systemd)

---

> **不知道选哪个？** 从**方式 A**（pgvector）开始本地体验。准备好用于生产时，切换到**方式 B**（S3 Vectors 或 OpenSearch）。参见[何时切换存储后端](../deploy/docker#何时切换到-s3-vectors-或-opensearch)。

## 为 OpenClaw Agent 启用 Skill

安装完成后，在 OpenClaw 中启用 **mem0-memory** skill，所有 Agent 即可自动获得记忆能力：

```bash
# 将 skill 复制到 OpenClaw skills 目录
mkdir -p ~/.openclaw/skills/mem0-memory
cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
```

然后进入 **OpenClaw 设置 → Skills**，启用 `mem0-memory`。

**完成。** 所有 Agent（无论新建还是已有）在下次 session 启动时，自动继承完整的记忆行为规范：
- 回答问题前主动检索记忆
- 对话中主动写日记
- Heartbeat 时维护 MEMORY.md
- 自动使用正确的 `--agent <id>` 参数，无需修改任何 AGENTS.md

> 无需修改各 Agent 的 `AGENTS.md` 文件。Skill 对所有 Agent 统一生效。

**想了解背后的原理？** 参见[工作原理](./how-it-works)，详细解释了 Skill 系统、记忆流转过程和 Agent 行为规范。

## 快速使用

```bash
# 添加长期记忆
python3 cli.py add --user me --agent <your-agent-id> --text "重要经验教训..."

# 添加短期记忆（当天日期）
python3 cli.py add --user me --agent <your-agent-id> --run 2026-03-27 \
  --text "今天讨论了重构方案"

# 语义搜索
python3 cli.py search --user me --agent <your-agent-id> --query "重构" --top-k 5

# 组合搜索（长期 + 近 7 天短期）
python3 cli.py search --user me --agent <your-agent-id> --query "重构" --combined
```

## 记忆分层

| 类型 | run_id | 生命周期 | 使用场景 |
|------|--------|----------|----------|
| **长期记忆** | 无 | 永久保存 | 技术决策、经验教训、用户偏好 |
| **短期记忆** | `YYYY-MM-DD` | 7 天后归档 | 当天讨论、临时决策、任务进展 |

**进入长期记忆的三条路径：**
1. `memory_sync.py` — 每天同步 `MEMORY.md`（当天生效，精选知识）
2. `pipelines/auto_dream.py`（AutoDream）— 7 天后对活跃短期记忆进行升级
3. Agent 主动写入 — 随时调用 CLI，不传 `--run` 参数

## 共享知识库

带有 `category=experience` 的记忆会自动在所有 Agent 和用户之间共享。当任何 Agent 添加标记为 `experience` 的记忆时，它会同时写入个人记忆空间和全局 `shared` 池。

在检索时，每次搜索都会自动包含共享池的结果——因此所有 Agent 都能受益于团队的集体经验，无需任何额外配置。
