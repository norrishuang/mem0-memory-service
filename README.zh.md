# mem0 Memory Service for OpenClaw

**中文** | [English](./README.md)

---

基于 [mem0](https://github.com/mem0ai/mem0) 的统一记忆层，为 [OpenClaw](https://github.com/openclaw/openclaw) Agent 提供持久化语义记忆存储。

Agent 可以通过对话自动存储和检索记忆，无需手动管理文件。

## 设计理念

### 为什么在 mem0 之上加生命周期管理？

mem0 的核心定位是**记忆提取和去重**——从对话中自动抽取关键事实、智能合并相似记忆、提供语义检索。但 mem0 本身不区分"短期事件"和"长期知识"，所有写入的内容默认永久保存。

这会带来一个问题：**临时性的讨论、当天的任务进展、还未确定的临时决策**，如果永久保留，会随时间堆积，污染长期记忆的质量。

本服务在 mem0 之上增加了一层**记忆生命周期管理**，分工如下：

```
mem0 负责：语义提取、智能去重、向量检索
本服务负责：分层存储、生命周期管理、活跃度归档
```

### 长短期分层的核心设计

**短期记忆**用 mem0 原生的 `run_id`（按天隔离）机制实现，天然与长期记忆隔离，不需要额外的 TTL 字段。

**归档判断**利用 mem0 的语义搜索能力来决定是否升级：7天后，用短期记忆的内容在近期记忆中做语义搜索——如果话题还活跃（有相关讨论），说明它有持续价值，升级为长期记忆；否则删除。这比简单的时间硬删更智能，不会误删持续进行中的话题。

这样既充分利用了 mem0 的语义能力，又解决了 mem0 原生不具备的生命周期管理问题。

## 架构

```
OpenClaw Agents (dev, main, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (systemd managed)   │
│                      │  ┌─────────────────────────┐
│  长短期分层记忆:     │  │ 长期记忆 (无 run_id)    │
│  - 长期: 技术决策、  │  │ 短期记忆 (run_id=日期)  │
│    经验教训、偏好   │  │ 归档: 活跃度判断升级/删除│
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
- `run_id=YYYY-MM-DD`（北京时间日期）
- 7天后自动归档：活跃话题升级为长期，不活跃的删除
- 用法: 传 `run_id=<日期>` 参数

**检索策略**
- 单独检索：长期（无 run_id）或特定日期短期（run_id=日期）
- 组合检索：长期 + 近N天短期（`--combined`），自动合并去重

## 前置条件

- **Python 3.9+**
- **OpenSearch** 集群（2.x 或 3.x，需启用 k-NN 插件）
- **AWS Bedrock** 访问权限（或自行修改 config.py 使用 OpenAI 等其他 LLM/Embedder）
- **OpenClaw** 安装并运行

## 快速部署

### 方法 1：一键安装（推荐）

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
./install.sh
```

安装脚本会交互式引导你填写 OpenSearch 连接信息、AWS 区域等配置，然后自动：
1. 安装 Python 依赖
2. 生成 `.env` 配置文件
3. 测试 OpenSearch 和 Bedrock 连通性
4. 创建 systemd 服务（开机自启）
5. 安装 OpenClaw Skill

### 方法 2：手动安装

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 1. 安装依赖
pip3 install -r requirements.txt

# 2. 配置
cp .env.example .env
vim .env  # 填入你的 OpenSearch 和 AWS 配置

# 3. 测试连通性
python3 test_connection.py

# 4. 启动服务
python3 server.py

# 5. (可选) 设置 systemd 开机自启
sudo cp mem0-memory.service /etc/systemd/system/
# 编辑 service 文件，修改 User/WorkingDirectory/EnvironmentFile 路径
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory

# 6. 安装 OpenClaw Skill
mkdir -p ~/.openclaw/skills/mem0-memory
cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
# 编辑 SKILL.md，将 $MEM0_HOME 替换为实际安装路径
```

### 方法 3：让 OpenClaw Agent 帮你部署

直接在对话中告诉你的 Agent：

> 帮我部署 mem0 记忆服务。
> 代码仓库在 https://github.com/norrishuang/mem0-memory-service
> OpenSearch 地址是 xxx，用户名 admin，密码 xxx。

Agent 会自动 clone 代码、运行安装脚本、配置 Skill。

### 方法 4：一键 AI 部署提示词

将以下提示词发送给你的 AI 助手，即可自动完成部署：

> 帮我部署 mem0 Memory Service for OpenClaw。代码仓库：https://github.com/norrishuang/mem0-memory-service 。请 clone 代码，安装 Python 依赖（`pip3 install -r requirements.txt`），复制 `.env.example` 为 `.env` 并配置以下关键项：`VECTOR_STORE`（opensearch 或 s3vectors）、OpenSearch 连接信息或 S3Vectors bucket 名称、`AWS_REGION`、`EMBEDDING_MODEL`、`LLM_MODEL`。配置完成后运行 `python3 test_connection.py` 测试连通性，然后用 `python3 server.py` 启动服务（默认端口 8230），并设置 systemd 开机自启。

## 使用

### CLI

```bash
# 添加长期记忆（技术决策、经验教训等）
python3 cli.py add --user me --agent dev --text "重要经验教训..." \
  --metadata '{"category":"experience"}'

# 添加短期记忆（当天讨论、临时决策）
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "今天 Luke 和 Zoe 讨论了记忆系统重构方案" \
  --metadata '{"category":"short_term"}'

# 对话消息（mem0 自动提取关键事实）
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# 语义搜索（单独搜索长期或短期）
python3 cli.py search --user me --agent dev --query "关键词" --top-k 5

# 组合搜索（长期 + 近7天短期，推荐）
python3 cli.py search --user me --agent dev --query "关键词" --combined --recent-days 7

# 列出所有记忆
python3 cli.py list --user me --agent dev

# 列出特定日期的短期记忆
python3 cli.py list --user me --agent dev --run 2026-03-23

# 获取 / 删除 / 查看历史
python3 cli.py get --id <memory_id>
python3 cli.py delete --id <memory_id>
python3 cli.py history --id <memory_id>
```

#### 短期记忆（基于 run_id）

短期记忆使用 `run_id=YYYY-MM-DD`（北京时间日期）标识，7天后自动归档：

```bash
# 添加短期记忆（用当天日期作为 run_id）
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "今天讨论的临时决策..." \
  --metadata '{"category":"short_term"}'

# 搜索特定日期的短期记忆
python3 cli.py search --user me --agent dev --run 2026-03-23 --query "讨论"

# 组合搜索（长期 + 近7天短期）
python3 cli.py search --user me --agent dev --query "关键词" \
  --combined --recent-days 7
```

**自动归档机制**（每天运行）：
- 7天前的短期记忆自动处理
- 活跃话题（近期有相关讨论）→ 升级为长期记忆
- 不活跃话题 → 删除

**使用场景：**
- 当天讨论记录
- 会议纪要
- 临时决策或假设
- 任务进展
```

### 自动短期记忆提取

`auto_digest.py` 脚本可以每 15 分钟自动从日记文件中提取短期事件，并存入 mem0（`run_id=YYYY-MM-DD`）。

#### 工作原理

1. **读取日记文件**：从 `/home/ec2-user/.openclaw/workspace-{agent}/memory/` 读取今天的日记（`YYYY-MM-DD.md`，按北京时间 UTC+8）
2. **增量处理**：通过 `.digest_state.json` 记录文件读取偏移量，只处理新增内容
3. **LLM 提取**：调用 AWS Bedrock Claude 3.5 Haiku 提取关键短期事件（人物讨论、任务进展、临时决策等）
4. **写入 mem0**：每条事件单独存储，`run_id=当天日期`，元数据标签 `category=short_term, source=auto_digest`

#### 配置定时任务

使用 cron 每 15 分钟自动运行：

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每 15 分钟执行）
*/15 * * * * /usr/bin/python3 /home/ec2-user/workspace/mem0-memory-service/auto_digest.py >> /home/ec2-user/workspace/mem0-memory-service/auto_digest.log 2>&1
```

或者使用以下命令一键添加：

```bash
(crontab -l 2>/dev/null; echo "# 每 15 分钟自动从日记提取短期记忆"; echo "*/15 * * * * /usr/bin/python3 /home/ec2-user/workspace/mem0-memory-service/auto_digest.py >> /home/ec2-user/workspace/mem0-memory-service/auto_digest.log 2>&1") | crontab -
```

#### 手动运行和测试

```bash
# 手动运行一次
cd /home/ec2-user/workspace/mem0-memory-service
python3 auto_digest.py

# 查看日志
tail -f auto_digest.log

# 验证写入的短期记忆
python3 cli.py search --user boss --agent dev --query "今天" --top-k 10
python3 cli.py list --user boss --agent dev | grep short_term
```

#### 文件说明

- **`auto_digest.py`**：主脚本
- **`.digest_state.json`**：状态文件，记录每个日记文件已处理的位置（git 已忽略）
- **`auto_digest.log`**：运行日志，追加模式（git 已忽略）

### 实时会话快照

`session_snapshot.py` 脚本每 5 分钟自动保存当前活跃 session 的对话到日记文件，解决 session 压缩导致最近对话丢失的问题。

#### 工作原理

1. **读取 session 文件**：从 OpenClaw 的 session store 读取当前活跃的 session
2. **提取消息**：解析 JSONL 格式，提取用户和 AI 的对话消息
3. **去重写入**：检查是否已存在相同内容，避免重复写入
4. **格式整理**：human 消息标记为 Boss，AI 消息标记为 Dev

#### 配置定时任务（systemd timer，推荐）

```bash
# 复制 systemd 单元到用户目录
mkdir -p ~/.config/systemd/user/
cp systemd/mem0-snapshot.service ~/.config/systemd/user/
cp systemd/mem0-snapshot.timer ~/.config/systemd/user/

# 启用 timer
systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
```

#### 手动运行和测试

```bash
python3 session_snapshot.py
```

#### 为什么需要这个？

- **问题**：OpenClaw 的 session 会话可能因为上下文过长而"压缩"，压缩前的对话历史可能丢失
- **解决**：每 5 分钟保存一次，确保最多丢失 5 分钟的对话

#### 文件说明

- **`session_snapshot.py`**：主脚本
- **`systemd/mem0-snapshot.service`**：systemd service 单元
- **`systemd/mem0-snapshot.timer`**：systemd timer 单元（每 5 分钟执行）

### 自定义配置

如需修改配置，编辑 `auto_digest.py` 中的以下变量：

```python
DIARY_DIR = Path("/home/ec2-user/.openclaw/workspace-dev/memory/")  # 日记目录
MEM0_API_URL = "http://127.0.0.1:8230/memory/add"                   # mem0 API 地址
BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"    # LLM 模型
```

### 自动归档短期记忆

`archive.py` 脚本每天运行一次，处理7天前的短期记忆，基于活跃度判断是否升级或删除。

#### 工作原理

1. **找到7天前的短期记忆**：查询 `run_id=7天前日期` 的所有记忆
2. **活跃度判断**：对每条记忆，在近7天的短期记忆中进行语义搜索
3. **升级或删除**：
   - 活跃话题（相似度 > 0.75）→ 升级为长期记忆（无 run_id）
   - 不活跃话题 → 直接删除

#### 配置定时任务（systemd timer）

```bash
# 安装 systemd timer（每天 UTC 02:00 / 北京时间 10:00 运行）
sudo cp mem0-archive.service /etc/systemd/system/
sudo cp mem0-archive.timer /etc/systemd/system/

# 编辑 service 文件，确认路径正确
sudo vim /etc/systemd/system/mem0-archive.service

# 启用并启动 timer
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-archive.timer

# 查看 timer 状态
sudo systemctl status mem0-archive.timer
sudo systemctl list-timers mem0-archive.timer

# 手动触发一次归档
sudo systemctl start mem0-archive.service

# 查看日志
tail -f archive.log
journalctl -u mem0-archive.service -f
```

#### 手动运行和测试

```bash
# 手动运行一次
cd /home/ec2-user/workspace/mem0-memory-service
python3 archive.py

# 查看日志
tail -f archive.log
```

#### 文件说明

- **`archive.py`**：归档主脚本
- **`archive.log`**：归档日志，追加模式（git 已忽略）
- **`mem0-archive.service`**：systemd service 单元
- **`mem0-archive.timer`**：systemd timer 单元

#### 自定义配置

如需修改配置，编辑 `archive.py` 中的以下变量：

```python
ARCHIVE_DAYS = 7        # 处理多少天前的短期记忆
ACTIVE_THRESHOLD = 0.75  # 活跃度判断阈值（语义相似度）
```

### HTTP API

```bash
# 健康检查
curl http://127.0.0.1:8230/health

# 添加长期记忆
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","text":"重要经验教训..."}'

# 添加短期记忆
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","run_id":"2026-03-23","text":"今天的讨论..."}'

# 语义搜索（单独搜索）
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"关键词","user_id":"me","agent_id":"dev","top_k":5}'

# 组合搜索（长期 + 近7天短期）
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"关键词","user_id":"me","agent_id":"dev","top_k":10,"recent_days":7}'

# 列出记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev'

# 列出特定日期的短期记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev&run_id=2026-03-23'
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
| `LLM_MODEL` | `us.anthropic.claude-3-5-haiku-...` | LLM 模型 |
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
        "s3vectors:CreateIndex",
        "s3vectors:GetIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:ListVectors"
      ],
      "Resource": "arn:aws:s3vectors:*:*:vector-bucket/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:CreateBucket",
      "Resource": "arn:aws:s3:::your-bucket-name"
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
python3 migrate_to_s3vectors.py --user boss --agent dev

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
├── install.sh              # 一键安装脚本
├── server.py               # FastAPI 主服务
├── config.py               # 配置管理（读取 .env）
├── cli.py                  # 命令行客户端
├── skill/
│   └── SKILL.md            # OpenClaw Skill 定义
├── migrate_memory_md.py    # MEMORY.md 迁移工具
├── test_connection.py      # 连通性测试
├── auto_digest.py          # 自动从日记提取短期记忆（每15分钟）
├── session_snapshot.py     # 实时保存session对话到日记（每5分钟）
├── archive.py              # 短期记忆自动归档（每天）
├── systemd/
│   ├── mem0-snapshot.service   # systemd service
│   ├── mem0-snapshot.timer     # systemd timer (每5分钟)
│   └── ...                 # 其他 systemd 单元
├── mem0-memory.service     # systemd 服务模板
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板
├── patch_s3vectors_filter.py # S3Vectors filter 格式 patch 脚本
├── PATCHES.md              # mem0 已知问题和 patch 记录
└── README.md
```

## mem0 已知问题 & Patches

使用 AWS Bedrock + OpenSearch 时 mem0 有两个已知 bug，我们已提交 PR 修复：

| 问题 | PR | 状态 |
|------|-----|------|
| OpenSearch 3.x nmslib 引擎废弃 | [#4392](https://github.com/mem0ai/mem0/pull/4392) | 待合并 |
| Converse API temperature + top_p 冲突 (Claude Haiku 4.5) | [#4393](https://github.com/mem0ai/mem0/pull/4393) | 待合并 |

在 PR 合并前需要手动 patch，详见 [PATCHES.md](./PATCHES.md)。

## License

MIT
