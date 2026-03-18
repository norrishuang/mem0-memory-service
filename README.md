# mem0 Memory Service

基于 [mem0](https://github.com/mem0ai/mem0) 的统一记忆层，为 [OpenClaw](https://github.com/openclaw/openclaw) Agent 提供持久化语义记忆存储。

Agent 可以通过对话自动存储和检索记忆，无需手动管理文件。

## 架构

```
OpenClaw Agents (dev, main, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (systemd managed)   │
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
└──────────────────────┘
```

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

## 使用

### CLI

```bash
# 添加记忆（文本）
python3 cli.py add --user me --agent dev --text "重要信息..."

# 添加记忆（对话消息，mem0 自动提取关键事实）
python3 cli.py add --user me --agent dev \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# 带元数据标签
python3 cli.py add --user me --agent dev --text "..." \
  --metadata '{"project":"xxx","category":"experience"}'

# 语义搜索
python3 cli.py search --user me --agent dev --query "关键词" --top-k 5

# 列出所有记忆
python3 cli.py list --user me --agent dev

# 获取 / 删除 / 查看历史
python3 cli.py get --id <memory_id>
python3 cli.py delete --id <memory_id>
python3 cli.py history --id <memory_id>
```

### HTTP API

```bash
# 健康检查
curl http://127.0.0.1:8230/health

# 添加记忆
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","text":"重要信息..."}'

# 语义搜索
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"关键词","user_id":"me","agent_id":"dev","top_k":5}'

# 列出记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev'
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
| POST | `/memory/add` | 添加记忆 (`messages` 或 `text`) |
| POST | `/memory/search` | 语义搜索 |
| GET | `/memory/list` | 列出记忆 (支持 `user_id`, `agent_id` 过滤) |
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
| `OPENSEARCH_HOST` | `localhost` | OpenSearch 地址 |
| `OPENSEARCH_PORT` | `9200` | 端口 |
| `OPENSEARCH_USER` | `admin` | 用户名 |
| `OPENSEARCH_PASSWORD` | - | 密码 |
| `OPENSEARCH_USE_SSL` | `false` | 是否使用 SSL |
| `OPENSEARCH_COLLECTION` | `mem0_memories` | 索引名 |
| `EMBEDDING_MODEL` | `amazon.titan-embed-text-v2:0` | Embedding 模型 |
| `EMBEDDING_DIMS` | `1024` | 向量维度 |
| `LLM_MODEL` | `us.anthropic.claude-3-5-haiku-...` | LLM 模型 |
| `SERVICE_PORT` | `8230` | 服务端口 |

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
├── mem0-memory.service     # systemd 服务模板
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板
└── README.md
```

## OpenSearch 3.x 兼容性

mem0 v1.0.x 的 OpenSearch adapter 默认使用 `nmslib` 引擎，而 OpenSearch 3.0+ 已废弃 nmslib。

我们已提交 PR 修复此问题：[mem0ai/mem0#4392](https://github.com/mem0ai/mem0/pull/4392)

在 PR 合并前，如果你使用 OpenSearch 3.x，需要手动 patch：

```bash
# 找到 mem0 的 opensearch.py
python3 -c "import mem0; print(mem0.__file__)"
# 编辑 .../mem0/vector_stores/opensearch.py
# 将所有 "engine": "nmslib" 改为 "engine": "faiss" 或 "lucene"
# 将 "space_type": "cosinesimil" 改为适配的 space_type
```

## License

MIT
