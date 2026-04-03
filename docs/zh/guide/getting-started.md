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

## 安装

### 方法 1：Docker 一键安装（推荐）

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
./install.sh
```

安装脚本会交互式引导你填写配置，然后自动：
1. 检查 Docker 和 docker compose 是否可用
2. 生成 `.env` 配置文件
3. 运行 `docker compose up -d`（构建并启动所有容器）
4. 验证服务健康状态
5. 安装 OpenClaw Skill

所有自动化 pipeline（会话快照、digest、记忆同步、dream）都在 Docker pipeline 容器内运行，无需单独配置定时器。

### 方法 2：AI 部署提示词

将以下提示词发送给你的 AI 助手，即可自动完成部署：

> 帮我部署 **mem0 Memory Service for OpenClaw**。代码仓库：https://github.com/norrishuang/mem0-memory-service
>
> **步骤 1：克隆**
> ```bash
> git clone https://github.com/norrishuang/mem0-memory-service.git
> cd mem0-memory-service
> ```
>
> **步骤 2：配置 .env**
> 将 `.env.example` 复制为 `.env` 并设置：
> - `VECTOR_STORE`：`opensearch`（默认）或 `s3vectors`
> - 如果用 OpenSearch：设置 `OPENSEARCH_HOST`、`OPENSEARCH_PORT`、`OPENSEARCH_PASSWORD`
> - 如果用 S3Vectors：设置 `S3VECTORS_BUCKET_NAME`、`S3VECTORS_INDEX_NAME`、`AWS_REGION`
> - `OPENCLAW_BASE`：OpenClaw 数据目录路径（默认 `~/.openclaw`）
> - `EMBEDDING_MODEL`：默认 `amazon.titan-embed-text-v2:0`
> - `LLM_MODEL`：默认 `us.anthropic.claude-haiku-4-5-20251001-v1:0`
>
> **步骤 3：Docker 启动**
> ```bash
> docker compose up -d
> ```
>
> **步骤 4：验证**
> ```bash
> curl http://localhost:8230/health
> ```
>
> **步骤 5：安装 OpenClaw Skill**
> ```bash
> mkdir -p ~/.openclaw/skills/mem0-memory
> cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
> ```
> 然后在 OpenClaw 设置 → Skills → mem0-memory 中启用。
>
> **步骤 6：测试**
> ```bash
> docker compose exec mem0-api python3 cli.py add --user me --agent dev \
>   --text "mem0 memory service deployed successfully" \
>   --metadata '{"category":"experience"}'
> docker compose exec mem0-api python3 cli.py search --user me --agent dev --query "deploy"
> ```

### 方法 3：systemd（高级/自定义）

如果你更倾向于不使用 Docker，直接在主机上运行：

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 1. 安装依赖
pip3 install -r requirements.txt

# 2. 配置
cp .env.example .env
vim .env  # 填入你的 OpenSearch/S3Vectors 和 AWS 配置

# 3. 测试连通性
python3 test_connection.py

# 4. 启动服务
sudo cp systemd/mem0-memory.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory.service

# 5. 设置自动化定时器（以当前用户运行）
mkdir -p ~/.config/systemd/user/

# Session snapshot — 每 5 分钟捕获会话对话（跨 session 记忆桥梁）
cp systemd/mem0-snapshot.service systemd/mem0-snapshot.timer ~/.config/systemd/user/

# MEMORY.md 同步 — 每天 UTC 01:00 将精选知识同步到长期记忆
cp systemd/mem0-memory-sync.service systemd/mem0-memory-sync.timer ~/.config/systemd/user/

# 日记 digest — 每天 UTC 01:30 将昨日日记提炼为短期记忆
cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/

# 归档 — 每天 UTC 02:00 对 7 天前短期记忆进行升级或删除
cp systemd/mem0-dream.service systemd/mem0-dream.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
systemctl --user enable --now mem0-memory-sync.timer
systemctl --user enable --now mem0-auto-digest.timer
systemctl --user enable --now mem0-dream.timer
```

完整 systemd 部署说明请参见 [systemd 配置](../deploy/systemd)。

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

### 已知问题

如果使用 **S3Vectors** 作为向量后端，必须在使用前应用 filter 格式 patch。详见 [PATCHES.md](https://github.com/norrishuang/mem0-memory-service/blob/main/PATCHES.md)。

```bash
python3 patch_s3vectors_filter.py
```

> ⚠️ 每次 `pip upgrade mem0ai` 后需要重新执行此 patch。

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
