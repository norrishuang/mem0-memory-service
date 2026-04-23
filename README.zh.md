# mem0 Memory Service for OpenClaw

**中文** | [English](./README.md)

---

基于 [mem0](https://github.com/mem0ai/mem0) 的统一记忆层，为 [OpenClaw](https://github.com/openclaw/openclaw) Agent 提供持久化语义记忆存储。

Agent 可以通过对话自动存储和检索记忆，无需手动管理文件。

## 功能特性

- **跨 Session 持久记忆** — OpenClaw 每次对话都是独立 session，原生不带任何记忆。本服务打通了 session 之间的隔阂：每轮对话结束后通过 openclaw-plugin 的 `agent_end` hook 实时写入日记文件，每 15 分钟增量 digest 将日记内容提炼存入向量库，新 session 启动时 Agent 自动检索相关记忆——上下文永不丢失。

- **多 Agent 隔离记忆** — 支持多个 Agent 并行运行（agent1 / agent2 / agent3 等），各 Agent 记忆空间完全隔离、互不干扰。从 `openclaw.json` 自动发现所有 Agent，无需手动注册。标记为 `experience` 的记忆自动在所有 Agent 间共享，沉淀团队集体经验。

- **短期 + 长期分层存储** — 对话通过 openclaw-plugin 的 `agent_end` hook 实时写入日记文件，每 15 分钟通过 `auto_digest --today` 提炼为短期记忆；Agent 精心维护的 `MEMORY.md` 直接同步到长期记忆。每晚 `auto_dream` 通过 mem0 原生推理将短期记忆整合为长期记忆。完整链路：实时对话 → 实时日记 → 增量 digest → 每晚 dream → 向量记忆。

- **低成本高效运营** — 增量 digest（每 15 分钟）使用 `infer=False` 直接存储日记文本——短期记忆写入零 LLM 开销。每晚 `auto_dream` 使用 `infer=True` 进行高质量长期记忆整合。`MEMORY.md` 同步基于 hash 去重——内容未变化时零 LLM 调用。

- **低成本向量存储（S3 Vectors）** — 支持 Amazon S3 Vectors 作为向量存储后端，相比自建 OpenSearch 集群成本极低，按实际用量付费。同时也支持 OpenSearch，适合已有集群的场景。

- **全自动运维** — Docker pipeline 容器（或 systemd timer）全程自动化：openclaw-plugin `agent_end` hook 实时写入日记、每 15 分钟增量 digest、UTC 01:00 MEMORY.md 同步、UTC 02:00 每晚 dream 整合。零人工干预，服务重启后自动恢复。

## 设计理念

### 为什么在 mem0 之上加生命周期管理？

mem0 的核心定位是**记忆提取和去重**——从对话中自动抽取关键事实、智能合并相似记忆、提供语义检索。但 mem0 本身不区分"短期事件"和"长期知识"，所有写入的内容默认永久保存。

这会带来一个问题：**临时性的讨论、当天的任务进展、还未确定的临时决策**，如果永久保留，会随时间堆积，污染长期记忆的质量。

本服务在 mem0 之上增加了一层**记忆生命周期管理**，分工如下：

```
mem0 负责：语义提取、智能去重、向量检索
本服务负责：分层存储、生命周期管理、每晚整合
```

### 长短期分层的核心设计

**短期记忆**用 mem0 原生的 `run_id`（按天隔离）机制实现，天然与长期记忆隔离，不需要额外的 TTL 字段。

**归档判断**由 mem0 原生处理。每条超过 7 天的短期记忆通过 `infer=True` 重新添加到 mem0 — mem0 的 LLM 与现有长期记忆比对后决定 ADD/UPDATE/DELETE/NONE。无论决定如何，原始短期条目处理后一律删除。

这样既充分利用了 mem0 的语义能力，又解决了 mem0 原生不具备的生命周期管理问题。

## 架构

```
OpenClaw Agents (agent1, agent2, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (Docker / systemd)  │
│                      │  ┌─────────────────────────┐
│  长短期分层记忆:     │  │ 长期记忆 (无 run_id)    │
│  - 长期: 技术决策、  │  │ 短期记忆 (run_id=日期)  │
│    经验教训、偏好   │  │ 归档: mem0 原生决策     │
│  - 短期: 当天讨论、  │  └─────────────────────────┘
│    临时决策、进展   │
└──────────┬───────────┘
           │
     ┌─────▼─────┐       ┌──────────────────┐
     │   mem0    │──────▶│  LLM (Bedrock /   │  记忆提取/去重/合并
     │           │       │  OpenAI / ...)     │
     │           │──────▶│  Embedder (Titan / │  文本向量化
     └─────┬─────┘       │  OpenAI / ...)     │
           │             └──────────────────┘
           ▼
┌──────────────────────┐
│  OpenSearch           │  向量存储 (k-NN)
│  (self-hosted / AWS)  │
│  ── 或 ──            │
│  Amazon S3 Vectors    │  低成本向量存储
└──────────────────────┘
```

### 长短期记忆分层

**长期记忆**（无 run_id）
- 技术决策、项目状态、经验教训、用户偏好
- 永久保存
- 用法: 不传 `run_id` 参数

**短期记忆**（有 run_id）
- 当天讨论、临时决策、任务进展
- `run_id=YYYY-MM-DD`
- 7天后自动归档：mem0 原生决策 ADD/UPDATE/DELETE/NONE；原始短期条目一律删除
- 用法: 传 `run_id=<日期>` 参数

**检索策略**
- 单独检索：长期（无 run_id）或特定日期短期（run_id=日期）
- 组合检索：长期 + 近N天短期（`--combined`），自动合并去重

## 前置条件

- **Docker 20.10+** 和 **docker compose** (v2) — 推荐的 Docker 部署方式
- **OpenSearch** 集群（2.x 或 3.x，需启用 k-NN 插件）或 **AWS S3 Vectors**
- **AWS Bedrock** 访问权限（或自行修改 config.py 使用 OpenAI 等其他 LLM/Embedder）
- **OpenClaw** 安装并运行

### Amazon Bedrock 权限

本服务使用 Amazon Bedrock 调用 LLM（用于记忆提取）和 Embedding 模型（用于向量化）。部署服务器必须有调用 Bedrock 模型的权限。

- **EC2 部署（推荐）**：将 IAM Role 附加到实例，无需配置 Access Key
- **其他环境**：使用 IAM User 的 Access Key（`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`）

**最小权限 IAM 策略：**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0"
      ]
    }
  ]
}
```

> **说明：**
> - 默认 Embedding 模型：`amazon.titan-embed-text-v2:0`（1024 维）
> - 默认 LLM：Claude Haiku 4.5 (claude-haiku-4-5-20251001)（可通过 `.env` 配置修改）
> - 如果修改了模型配置，需要相应调整 Resource ARN
> - 如果使用跨区域推理 profile（`us.anthropic.claude-*`），Resource 需要包含对应的 profile ARN

## 快速部署

### 方法 1：Docker 安装（推荐）

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
cp .env.example .env
# 编辑 .env：设置 VECTOR_STORE、OpenSearch/S3Vectors 配置、OPENCLAW_BASE 路径
docker compose up -d
```

> 💡 EC2 用户：将 IAM Role 附加到实例即可，无需在 `.env` 中配置 Access Key。

或使用交互式安装器：`./tools/install.sh`（检查 Docker、引导 `.env` 配置、启动容器、验证健康状态）。

所有自动化 pipeline（digest、记忆同步、dream）都在 Docker pipeline 容器内运行，无需单独配置定时器。

### 方法 2：systemd（高级）

如需不使用 Docker 的主机原生部署，请参见 [systemd 部署](./docs/deploy/systemd.md)。

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
pip3 install -r requirements.txt
cp .env.example .env
vim .env
python3 test_connection.py
python3 server.py
```

## 使用

### CLI

```bash
# 添加长期记忆（技术决策、经验教训等）
python3 cli.py add --user me --agent agent1 --text "重要经验教训..." \
  --metadata '{"category":"experience"}'

# 添加短期记忆（当天讨论、临时决策）
python3 cli.py add --user me --agent agent1 --run 2026-03-23 \
  --text "今天 Luke 和 Zoe 讨论了记忆系统重构方案" \
  --metadata '{"category":"short_term"}'

# 对话消息（mem0 自动提取关键事实）
python3 cli.py add --user me --agent agent1 --run 2026-03-23 \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# 语义搜索（单独搜索长期或短期）
python3 cli.py search --user me --agent agent1 --query "关键词" --top-k 5

# 组合搜索（长期 + 近7天短期，推荐）
python3 cli.py search --user me --agent agent1 --query "关键词" --combined --recent-days 7

# 列出所有记忆
python3 cli.py list --user me --agent agent1

# 列出特定日期的短期记忆
python3 cli.py list --user me --agent agent1 --run 2026-03-23

# 获取 / 删除 / 查看历史
python3 cli.py get --id <memory_id>
python3 cli.py delete --id <memory_id>
python3 cli.py history --id <memory_id>
```

#### 短期记忆（基于 run_id）

短期记忆使用 `run_id=YYYY-MM-DD`标识，7天后自动归档：

```bash
# 添加短期记忆（用当天日期作为 run_id）
python3 cli.py add --user me --agent agent1 --run 2026-03-23 \
  --text "今天讨论的临时决策..." \
  --metadata '{"category":"short_term"}'

# 搜索特定日期的短期记忆
python3 cli.py search --user me --agent agent1 --run 2026-03-23 --query "讨论"

# 组合搜索（长期 + 近7天短期）
python3 cli.py search --user me --agent agent1 --query "关键词" \
  --combined --recent-days 7
```

**自动归档机制**（每天 UTC 02:00 由 `auto_dream.py` 运行）：
- 7天前的短期记忆自动处理
- 每条记忆以 `infer=True`（无 run_id）重新添加到 mem0 — mem0 决策 ADD/UPDATE/DELETE/NONE
- 原始短期条目处理后一律删除

**使用场景：**
- 当天讨论记录
- 会议纪要
- 临时决策或假设
- 任务进展
```

### 自动短期记忆提取

`auto_digest.py` 脚本每 15 分钟以 `--today` 模式运行，从今天的日记文件中提取短期事件，以 `infer=False` 存入 mem0（日记文本直接传入，不经过自定义 LLM 提取层）。

#### 工作原理

1. **读取今日日记**：从各 Agent 的 workspace 读取**今天**的日记（`YYYY-MM-DD.md`）。Agent workspace 路径自动从 `openclaw.json` 解析，无需硬编码路径。
2. **以 infer=False 写入 mem0**：每条日记内容通过 `mem0.add(infer=False)` 存储，`run_id=今天日期`。日记文本直接传入 mem0，不经过自定义 LLM 提取层。
3. **元数据**：`category=short_term, source=auto_digest`

> 不再使用 `.digest_state.json` 增量状态文件。使用 `infer=False`，日记文本直接存储，不经过 LLM 提取。

#### 配置定时任务（systemd timer）

```bash
mkdir -p ~/.config/systemd/user/
cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mem0-auto-digest.timer
```

#### 手动运行和测试

```bash
# 手动运行一次
cd /home/ec2-user/workspace/mem0-memory-service
python3 auto_digest.py

# 查看日志
tail -f auto_digest.log

# 验证写入的短期记忆
python3 cli.py search --user boss --agent agent1 --query "今天" --top-k 10
python3 cli.py list --user boss --agent agent1 | grep short_term
```

#### 文件说明

- **`auto_digest.py`**：主脚本
- **`.digest_state.json`**：~~状态文件，记录已处理位置~~ （已移除，不再使用）
- **`auto_digest.log`**：运行日志，追加模式（git 已忽略）

### 自定义配置

如需修改配置，编辑 `auto_digest.py` 中的以下变量：

```python
# Agent workspace 路径自动从 openclaw.json 解析，无需手动配置路径。
# 如果 OpenClaw 数据目录不在默认的 ~/.openclaw，通过环境变量覆盖：
# export OPENCLAW_HOME=/path/to/openclaw/data

MEM0_API_URL = "http://127.0.0.1:8230/memory/add"                   # mem0 API 地址
BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"    # LLM 模型
```

### AutoDream — 每晚记忆整合

`auto_dream.py` 脚本每天 UTC 02:00 运行，通过 mem0 原生推理将短期记忆整合为长期记忆。

#### 工作原理

1. **Step 1 — 日记 → 长期记忆**：读取昨天的完整日记，调用 `mem0.add(infer=True)` 且不传 `run_id` — mem0 的 LLM 自动提取关键事实并直接存为长期记忆。
2. **Step 2 — 短期记忆清理**：对每条超过 7 天的短期记忆，调用 `mem0.add(infer=True)` 且不传 `run_id` — mem0 的 LLM 与现有长期记忆比对后决定 ADD/UPDATE/DELETE/NONE。无论决定如何，原始短期条目处理后一律删除。

#### 配置定时任务（systemd timer）

```bash
# 安装 systemd timer（每天 UTC 02:00 运行）
sudo cp systemd/mem0-dream.service /etc/systemd/system/
sudo cp systemd/mem0-dream.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mem0-dream.timer

# 查看 timer 状态
sudo systemctl status mem0-dream.timer
sudo systemctl list-timers mem0-dream.timer

# 手动触发一次
sudo systemctl start mem0-dream.service

# 查看日志
journalctl -u mem0-dream.service -f
```

#### 手动运行和测试

```bash
cd /home/ec2-user/workspace/mem0-memory-service
python3 auto_dream.py

# 查看日志
tail -f auto_dream.log
```

#### 文件说明

- **`auto_dream.py`**：主脚本
- **`auto_dream.log`**：运行日志，追加模式（git 已忽略）

### HTTP API

```bash
# 健康检查
curl http://127.0.0.1:8230/health

# 添加长期记忆
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"agent1","text":"重要经验教训..."}'

# 添加短期记忆
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"agent1","run_id":"2026-03-23","text":"今天的讨论..."}'

# 语义搜索（单独搜索）
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"关键词","user_id":"me","agent_id":"agent1","top_k":5}'

# 组合搜索（长期 + 近7天短期）
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"关键词","user_id":"me","agent_id":"agent1","top_k":10,"recent_days":7}'

# 列出记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=agent1'

# 列出特定日期的短期记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=agent1&run_id=2026-03-23'
```

### Agent 自动使用

安装 Skill 后，OpenClaw Agent 会自动在对话中使用记忆系统：

- 当你说 **"记住..."** → Agent 自动存储到 mem0
- 当你问 **"之前那个项目..."** → Agent 自动从 mem0 检索
- **Heartbeat** 时 → Agent 自动沉淀有价值的对话内容

## API 接口

| Method | Path | 说明 |
|--------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/memory/add` | 添加记忆 (`messages` 或 `text`，支持 `run_id` 字段用于短期记忆) |
| POST | `/memory/search` | 语义搜索 (支持 `run_id` 过滤) |
| POST | `/memory/search_combined` | 组合搜索（长期 + 近N天短期） |
| GET | `/memory/list` | 列出记忆 (支持 `user_id`, `agent_id`, `run_id` 过滤) |
| GET | `/memory/{id}` | 获取单条记忆 |
| PUT | `/memory/update` | 更新记忆 |
| DELETE | `/memory/{id}` | 删除记忆 |
| GET | `/memory/history/{id}` | 查看记忆变更历史 |

## 数据隔离

使用 `user_id` + `agent_id` 二维隔离：

- **user_id**: 用户级别 — 不同用户的记忆完全隔离
- **agent_id**: Agent 级别 — 同一用户的不同 Agent 各自管理记忆
- 不传 `agent_id` 可跨 Agent 检索所有记忆

## 配置

所有配置通过环境变量或 `.env` 文件管理（`install.sh` 自动生成）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AWS_REGION` | `us-east-1` | AWS 区域 |
| `VECTOR_STORE` | `opensearch` | 向量引擎：`opensearch` 或 `s3vectors` |
| `OPENSEARCH_HOST` | `localhost` | OpenSearch 地址 |
| `OPENSEARCH_PORT` | `9200` | 端口 |
| `OPENSEARCH_USER` | `admin` | 用户名 |
| `OPENSEARCH_PASSWORD` | - | 密码 |
| `OPENSEARCH_USE_SSL` | `false` | 是否使用 SSL |
| `OPENSEARCH_COLLECTION` | `mem0_memories` | 索引名 |
| `S3VECTORS_BUCKET_NAME` | - | S3Vectors bucket 名称（`s3vectors` 模式必填） |
| `S3VECTORS_INDEX_NAME` | `mem0` | S3Vectors 向量索引名称 |
| `EMBEDDING_MODEL` | `amazon.titan-embed-text-v2:0` | Embedding 模型 |
| `EMBEDDING_DIMS` | `1024` | 向量维度 |
| `LLM_MODEL` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | LLM 模型 |
| `SERVICE_PORT` | `8230` | 服务端口 |

### Vector Store 配置

#### OpenSearch（默认）

默认使用 OpenSearch 作为向量引擎，无需额外配置。确保 `.env` 中 OpenSearch 相关变量正确即可：

```bash
VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
```

#### AWS S3 Vectors

[Amazon S3 Vectors](https://aws.amazon.com/s3/features/vectors/) 是 AWS 提供的低成本向量存储服务，具有 S3 级别的弹性和持久性，支持亚秒级查询。

**配置方式：**

```bash
export VECTOR_STORE=s3vectors
export S3VECTORS_BUCKET_NAME=your-bucket-name
export S3VECTORS_INDEX_NAME=mem0          # 可选，默认 mem0
export AWS_REGION=us-east-1               # 可选，默认 us-east-1
```

或在 `.env` 文件中配置：

```env
VECTOR_STORE=s3vectors
S3VECTORS_BUCKET_NAME=your-bucket-name
S3VECTORS_INDEX_NAME=mem0
AWS_REGION=us-east-1
```

**所需 IAM 权限（最小权限原则）：**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateVectorBucket",
        "s3vectors:GetVectorBucket",
        "s3vectors:CreateIndex",
        "s3vectors:GetIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:ListVectors"
      ],
      "Resource": "*"
    }
  ]
}
```

> 参考文档：[S3 Vectors Security & Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-security-access.html) | [mem0 S3 Vectors 配置](https://docs.mem0.ai/components/vectordbs/dbs/s3_vectors)

#### 从 OpenSearch 迁移到 S3Vectors

如果你已经在使用 OpenSearch 存储记忆，可以使用 `migrate_to_s3vectors.py` 将数据迁移到 S3Vectors。

**前提条件：** 需要同时配置 OpenSearch 和 S3Vectors 的环境变量（`.env` 中保留 OpenSearch 配置，同时设置 `S3VECTORS_BUCKET_NAME` 等）。

```bash
# 迁移所有用户的记忆
python3 migrate_to_s3vectors.py

# 只迁移指定用户
python3 migrate_to_s3vectors.py --user boss

# 指定用户和 agent
python3 migrate_to_s3vectors.py --user boss --agent agent1

# dry-run 模式（只预览，不写入）
python3 migrate_to_s3vectors.py --dry-run
```

> ⚠️ **安全提示**：迁移过程不会删除 OpenSearch 中的源数据。确认 S3Vectors 数据完整后，再手动清理 OpenSearch。

#### 已知问题：Filter 格式 Patch（必须应用）

mem0 上游 `s3_vectors.py` 存在 bug：`search()` 时传给 S3Vectors API 的 filter 格式不正确，导致 `add()` 操作报 `Invalid query filter` 错误。已向上游提交修复 [PR #4554](https://github.com/mem0ai/mem0/pull/4554)，等待合并中。

**在 PR 合并之前，必须手动应用 patch：**

```bash
python3 patch_s3vectors_filter.py
sudo systemctl restart mem0-memory.service
```

**验证 patch 是否生效：**

```bash
python3 -c "
from mem0.vector_stores.s3_vectors import S3Vectors
vs = S3Vectors.__new__(S3Vectors)
print(vs._convert_filters({'user_id': 'boss'}))
# 预期输出: {'user_id': {'\$eq': 'boss'}}
"
```

> ⚠️ 此 patch 直接修改已安装的 mem0 包。**每次 `pip upgrade mem0ai` 后需要重新执行 patch。**

## 迁移现有记忆

如果你之前使用 `MEMORY.md` 管理记忆，可以一键迁移到 mem0：

```bash
# 编辑脚本中的 MEMORY_FILE 路径、USER_ID、AGENT_ID
vim migrate_memory_md.py

# 运行迁移
python3 migrate_memory_md.py
```

## 文件结构

```
mem0-memory-service/
├── server.py               # FastAPI 主服务
├── config.py               # 配置管理（读取 .env）
├── cli.py                  # 命令行客户端
├── requirements.txt        # Python 依赖
├── Dockerfile
├── docker-compose.yml
├── .env.example            # 配置模板
├── pipelines/
│   ├── auto_digest.py      # 自动从日记提取短期记忆（每15分钟）
│   ├── auto_dream.py       # 每晚记忆整合：日记→长期记忆（每天 UTC 02:00）
│   ├── memory_sync.py      # 记忆同步管道
│   └── audit_shipper.py    # 审计日志上传
├── systemd/
│   ├── mem0-memory.service # systemd 服务模板
│   ├── mem0-dream.service  # Auto-dream 服务
│   ├── mem0-dream.timer    # Auto-dream 定时器
│   └── ...                 # 其他 systemd 单元
├── tools/
│   ├── install.sh          # 一键安装脚本
│   ├── update-services.sh  # 更新 systemd 单元
│   └── patch_minimax_support.py  # MiniMax 模型 patch 脚本
├── docs/
│   ├── PATCHES.md          # mem0 已知问题和 patch 记录
│   └── ...                 # 其他文档
├── skill/
│   └── SKILL.md            # OpenClaw Skill 定义
└── README.md
```

## mem0 已知问题 & Patches

使用 AWS Bedrock + OpenSearch 时 mem0 有两个已知 bug，我们已提交 PR 修复：

| 问题 | PR | 状态 |
|------|-----|------|
| OpenSearch 3.x nmslib 引擎废弃 | [#4392](https://github.com/mem0ai/mem0/pull/4392) | 待合并 |
| Converse API temperature + top_p 冲突 (Claude Haiku 4.5) | [#4393](https://github.com/mem0ai/mem0/pull/4393) | ✅ Merged via [#4469](https://github.com/mem0ai/mem0/pull/4469) |
| S3Vectors `query_vectors` filter 格式错误 | [#4554](https://github.com/mem0ai/mem0/pull/4554) | 待合并 |

在 PR 合并前需要手动 patch，详见 [PATCHES.md](./docs/PATCHES.md)。

## License

MIT
