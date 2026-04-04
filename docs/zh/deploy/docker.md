# Docker 部署

使用 Docker Compose 部署 mem0 Memory Service。这是 [systemd 部署](./systemd.md) 之外的可选方式，两种方式均完全支持。

## 前提条件

- Docker Engine 20.10+
- Docker Compose V2（`docker compose`）
- 宿主机已安装 OpenClaw
- AWS 凭证已配置（IAM Role 或 Access Key）

### 所需 AWS 权限

使用的 AWS 身份（IAM Role 或 Access Key）必须具备以下权限：

**S3 Vectors**（当 `VECTOR_STORE=s3vectors` 时）：
```json
{
  "Effect": "Allow",
  "Action": "s3vectors:*",
  "Resource": [
    "arn:aws:s3vectors:<region>:<account-id>:bucket/<your-bucket-name>",
    "arn:aws:s3vectors:<region>:<account-id>:bucket/<your-bucket-name>/*"
  ]
}
```
> ⚠️ 必须同时指定 bucket ARN 和 `/*`（用于 `GetIndex`、`PutVectors` 等 Index 级别操作）。仅指定 bucket ARN 会导致 Index 操作报 `AccessDeniedException`。

**AWS Bedrock**（LLM + Embedding）：
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream"
  ],
  "Resource": "*"
}
```

**EC2 + IAM Role**：将上述 Policy 附加到实例的 IAM Role 上。Docker 容器会通过 EC2 实例元数据服务（IMDS）自动获取凭证，`.env` 中无需配置 `AWS_ACCESS_KEY_ID`。

**非 EC2 环境**：在 `.env` 中设置 `AWS_ACCESS_KEY_ID` 和 `AWS_SECRET_ACCESS_KEY`。

## 🚀 快速体验：本地 pgvector（Demo / 本地开发，无需云服务）

> **最快方式**：直接运行 `./install.sh`，自动探测 AWS Region，默认配置一键完成。参见[一键部署](../guide/getting-started#一键部署)。

如果只想在本地快速体验 mem0 Memory Service，无需配置 S3 Vectors 或 OpenSearch，可以使用内置的 PostgreSQL + pgvector 后端。只需要 AWS Bedrock（LLM + Embedding）凭证即可。

```bash
# 1. 克隆仓库
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 2. 配置 .env
cp .env.example .env
```

编辑 `.env`，最小配置如下：

```env
# 切换到本地 pgvector
VECTOR_STORE=pgvector

# PostgreSQL 连接（与 docker-compose 默认值一致）
PGVECTOR_HOST=mem0-postgres
PGVECTOR_DB=mem0
PGVECTOR_USER=mem0
PGVECTOR_PASSWORD=change-me-in-production

# AWS 区域和 Bedrock 模型（LLM + Embedding 仍然需要）
AWS_REGION=us-east-1
LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0

# 你的 OpenClaw 数据目录
OPENCLAW_BASE=~/.openclaw
```

```bash
# 3. 启动所有服务（含 PostgreSQL）
docker compose --profile pgvector up -d

# 4. 验证
curl http://localhost:8230/health
```

将会启动三个容器：
- `mem0-postgres` — PostgreSQL 17（含 pgvector 扩展）
- `mem0-api` — FastAPI HTTP 服务，端口 8230
- `mem0-pipeline` — Cron 定时任务（snapshot / digest / dream）

> **pgvector 数据存储在本地**，通过 Docker named volume（`pgvector_data`）持久化，容器重启后数据不丢失。

### 何时切换到 S3 Vectors 或 OpenSearch

pgvector 非常适合本地开发和单机部署。以下场景建议切换到托管向量数据库：

| 场景 | 推荐后端 |
|------|----------|
| 单机、本地开发、快速体验 | **pgvector**（本指南）|
| AWS 托管、希望无服务器存储 | **S3 Vectors** |
| 需要全文检索 + 向量混合搜索 | **OpenSearch** |
| 高可用、多节点 | **OpenSearch** 或 **S3 Vectors** |

如需将数据从 pgvector 迁移到 S3 Vectors，使用内置迁移工具：

```bash
# 先在 8231 端口启动 S3 Vectors 服务，然后执行：
python3 tools/migrate_s3vectors_to_pgvector.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss
```

## 🐳 生产环境部署：Docker + 托管向量数据库（S3 Vectors / OpenSearch）

```bash
# 1. 克隆仓库
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 2. 配置 .env
cp .env.example .env
vim .env   # 填写 OpenSearch/S3Vectors + AWS 区域 + 模型配置

# 3. 启动服务
docker compose up -d
```

完成。两个容器会启动：
- `mem0-api` — FastAPI HTTP 服务，端口 8230
- `mem0-pipeline` — 基于 cron 的定时任务（snapshot / digest / dream）

## 配置说明

### .env 配置

所有标准配置（OpenSearch、S3Vectors、LLM、Embedding）与 systemd 部署方式相同。Docker 特有配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENCLAW_BASE` | `~/.openclaw` | 宿主机上的 OpenClaw 数据目录。pipeline 容器会 bind mount 此路径来读写日记文件。 |
| `DATA_DIR` | `./data` | 状态文件和日志目录。容器内映射为 `/app/data`。 |
| `AWS_CONFIG_DIR` | `~/.aws` | 宿主机上的 AWS 凭证目录。以只读方式挂载到 pipeline 容器。 |
| `MEM0_API_URL` | `http://127.0.0.1:8230` | mem0 API 地址。pipeline 容器内部自动覆盖为 `http://mem0-api:8230`。 |

### OPENCLAW_BASE

这是 Docker 部署最重要的配置项。设置为宿主机上 OpenClaw 存储数据的路径：

```bash
# 在 .env 中
OPENCLAW_BASE=/home/youruser/.openclaw
```

pipeline 容器会将此目录挂载到 `/openclaw`，并在内部设置 `OPENCLAW_BASE=/openclaw`，这样所有脚本都能找到 agent workspace、session 文件和日记文件。

### AWS 凭证配置

两种方式：

**方式一：挂载 ~/.aws（推荐，适用于 EC2 IAM Role）**

默认的 `docker-compose.yml` 已经挂载了 `~/.aws:/root/.aws:ro`。如果宿主机使用 IAM Role，无需额外配置。

```bash
# 在 .env 中（可选，仅当 .aws 目录不在默认位置时）
AWS_CONFIG_DIR=/home/youruser/.aws
```

**方式二：环境变量**

```bash
# 在 .env 中
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

### S3Vectors Filter 补丁

如果使用 S3Vectors 作为向量存储，启动前需要打补丁：

```bash
docker compose run --rm mem0-api python3 tools/patch_s3vectors_filter.py
docker compose restart mem0-api
```

## 目录结构

运行后，`data/` 目录包含：

```
data/
├── .snapshot_offsets.json    # Session snapshot 偏移量
├── auto_digest_offset.json  # Digest 增量偏移量
├── .memory_sync_state.json  # MEMORY.md 同步 hash
├── snapshot.log             # Session snapshot 日志
├── auto_digest.log          # Auto digest 日志
└── auto_dream.log           # AutoDream 日志
```

此目录通过 volume mount 在两个容器间共享。

## 常用命令

```bash
# 查看服务状态
docker compose ps

# 查看 API 日志
docker compose logs -f mem0-api

# 查看 pipeline 日志（cron 输出）
docker compose logs -f mem0-pipeline

# 查看具体 pipeline 日志
tail -f data/auto_digest.log

# 重启服务
docker compose restart

# 仅重启 API
docker compose restart mem0-api

# 停止所有服务
docker compose down

# 代码更新后重新构建
docker compose build
docker compose up -d

# 运行 CLI 命令
docker compose exec mem0-api python3 cli.py search --user boss --agent agent1 --query "deploy"

# 手动触发 pipeline
docker compose exec mem0-pipeline python3 pipelines/session_snapshot.py
docker compose exec mem0-pipeline python3 pipelines/auto_digest.py --today
docker compose exec mem0-pipeline python3 pipelines/auto_dream.py

# 健康检查
curl http://localhost:8230/health
```

## Pipeline 调度

pipeline 容器运行三个 cron 任务：

| 脚本 | 调度 | 用途 |
|------|------|------|
| `session_snapshot.py` | 每 5 分钟 | 保存活跃 session 对话到日记文件 |
| `auto_digest.py --today` | 每 15 分钟 | 从今日日记提取短期记忆 |
| `auto_dream.py` | 每天 UTC 02:00 | 日记→长期记忆 + 归档旧短期记忆 |

## Docker vs systemd 对比

| 方面 | Docker | systemd |
|------|--------|---------|
| 部署 | `docker compose up -d` | `install.sh` + systemd units |
| 依赖 | 仅需 Docker | Python 3.9+、pip、systemd |
| 隔离性 | 完整容器隔离 | 共享宿主机 Python 环境 |
| 定时任务 | 容器内 cron | systemd timers |
| 日志 | `docker compose logs` + `data/*.log` | `journalctl` + 项目根目录 `*.log` |
| 升级 | `git pull && docker compose build && docker compose up -d` | `git pull && pip install -r requirements.txt && systemctl restart` |
| AWS 凭证 | 挂载 `~/.aws` 或环境变量 | 宿主机 IAM Role 或环境变量 |
| OpenClaw 访问 | Bind mount `OPENCLAW_BASE` | 直接文件系统访问 |

两种方式完全兼容，可以在同一台机器上共存（使用不同端口即可）。
