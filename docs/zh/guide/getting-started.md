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
│  (systemd managed)   │
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

- **Python 3.9+**
- **OpenSearch** 集群（2.x 或 3.x，需启用 k-NN 插件）或 **AWS S3 Vectors**
- **AWS Bedrock** 访问权限（或修改 `config.py` 使用其他 LLM/Embedder）
- **Amazon Bedrock IAM 权限** — 部署服务器需要 `bedrock:InvokeModel` 和 `bedrock:InvokeModelWithResponseStream` 权限。最小 IAM 策略示例参见 [README](https://github.com/norrishuang/mem0-memory-service/blob/main/README.zh.md#amazon-bedrock-权限)。

## 安装

### 方法 1：一键安装（推荐）

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
./install.sh
```

安装脚本会交互式引导你填写配置，然后自动：
1. 安装 Python 依赖
2. 生成 `.env` 配置文件
3. 测试 OpenSearch 和 Bedrock 连通性
4. 创建 systemd 服务（开机自启）
5. 设置所有自动化定时器

### 方法 2：手动安装

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
cp systemd/mem0-archive.service systemd/mem0-archive.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
systemctl --user enable --now mem0-memory-sync.timer
systemctl --user enable --now mem0-auto-digest.timer
systemctl --user enable --now mem0-archive.timer
```

### 方法 3：一键 AI 部署提示词

将以下提示词发送给你的 AI 助手，即可自动完成部署：

> 帮我部署 **mem0 Memory Service for OpenClaw**。代码仓库：https://github.com/norrishuang/mem0-memory-service
>
> **步骤 1：克隆并安装**
> ```bash
> git clone https://github.com/norrishuang/mem0-memory-service.git
> cd mem0-memory-service
> pip3 install -r requirements.txt
> ```
>
> **步骤 2：配置 .env**
> 将 `.env.example` 复制为 `.env` 并设置：
> - `VECTOR_STORE`：`opensearch`（默认）或 `s3vectors`
> - 如果用 OpenSearch：设置 `OPENSEARCH_HOST`、`OPENSEARCH_PORT`、`OPENSEARCH_INDEX`
> - 如果用 S3Vectors：设置 `S3VECTORS_BUCKET_NAME`、`S3VECTORS_INDEX_NAME`、`AWS_REGION`
> - `EMBEDDING_MODEL`：默认 `amazon.titan-embed-text-v2:0`
> - `LLM_MODEL`：默认 `us.anthropic.claude-haiku-4-5-20251001-v1:0`
>
> **步骤 3：（仅 S3Vectors）应用 filter patch**
> ```bash
> python3 patch_s3vectors_filter.py
> ```
> 这是修复 mem0 上游已知 bug（PR #4554 待合并）。每次 `pip upgrade mem0ai` 后需重新执行。
>
> **步骤 4：验证连通性**
> ```bash
> python3 test_connection.py
> ```
>
> **步骤 5：启动记忆服务**
> ```bash
> sudo cp systemd/mem0-memory.service /etc/systemd/system/
> sudo systemctl daemon-reload
> sudo systemctl enable --now mem0-memory.service
> ```
>
> **步骤 6：设置自动化定时器（以当前用户运行）**
> ```bash
> mkdir -p ~/.config/systemd/user/
> cp systemd/mem0-snapshot.service systemd/mem0-snapshot.timer ~/.config/systemd/user/
> cp systemd/mem0-memory-sync.service systemd/mem0-memory-sync.timer ~/.config/systemd/user/
> cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/
> cp systemd/mem0-archive.service systemd/mem0-archive.timer ~/.config/systemd/user/
> systemctl --user daemon-reload
> systemctl --user enable --now mem0-snapshot.timer
> systemctl --user enable --now mem0-memory-sync.timer
> systemctl --user enable --now mem0-auto-digest.timer
> systemctl --user enable --now mem0-archive.timer
> ```
>
> **步骤 7：为 OpenClaw Agent 启用 mem0-memory Skill**
>
> 将 skill 复制到 OpenClaw skills 目录：
> ```bash
> mkdir -p ~/.openclaw/skills/mem0-memory
> cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
> ```
> 然后在 OpenClaw 设置 → Skills → mem0-memory 中启用。
>
> **步骤 8：测试写入和搜索**
> ```bash
> python3 cli.py add --user me --agent dev \
>   --text "mem0 memory service deployed successfully" \
>   --metadata '{"category":"experience"}'
> python3 cli.py search --user me --agent dev --query "deploy"
> ```

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
2. `archive.py` — 7 天后对活跃短期记忆进行升级
3. Agent 主动写入 — 随时调用 CLI，不传 `--run` 参数

## 共享知识库

带有 `category=experience` 的记忆会自动在所有 Agent 和用户之间共享。当任何 Agent 添加标记为 `experience` 的记忆时，它会同时写入个人记忆空间和全局 `shared` 池。

在检索时，每次搜索都会自动包含共享池的结果——因此所有 Agent 都能受益于团队的集体经验，无需任何额外配置。
