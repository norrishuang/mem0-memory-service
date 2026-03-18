# mem0 Memory Service

基于 [mem0](https://github.com/mem0ai/mem0) 的统一记忆层，为所有 OpenClaw Agent 提供持久化语义记忆存储。

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
     │   mem0    │──────▶│  Bedrock Claude   │  记忆提取/去重/冲突
     │           │       │  Haiku 3.5        │
     │           │──────▶│  Bedrock Titan    │  Embedding (1024d)
     └─────┬─────┘       │  Embed V2         │
           │             └──────────────────┘
           ▼
┌──────────────────────┐
│  OpenSearch 3.3      │  向量存储 (k-NN / FAISS)
│  (AWS Managed)       │
└──────────────────────┘
```

## 组件

| 组件 | 用途 |
|------|------|
| **OpenSearch 3.3** | 向量存储后端，k-NN (FAISS engine) |
| **Bedrock Titan Embed V2** | 文本向量化，1024 维 |
| **Bedrock Claude 3.5 Haiku** | 记忆提取、去重、冲突检测 |
| **mem0** | 记忆生命周期管理框架 |
| **FastAPI** | HTTP API 层 |

## 快速开始

### 启动服务

```bash
# systemd (已配置开机自启)
sudo systemctl start mem0-memory
sudo systemctl status mem0-memory

# 或手动启动
cd /home/ec2-user/workspace/mem0-memory-service
AWS_REGION=us-east-1 python3 server.py
```

### 使用 CLI

```bash
cd /home/ec2-user/workspace/mem0-memory-service

# 添加记忆 (文本)
python3 cli.py add --user boss --agent dev --text "重要信息..."

# 添加记忆 (对话)
python3 cli.py add --user boss --agent dev \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# 语义搜索
python3 cli.py search --user boss --agent dev --query "DolphinScheduler 进展"

# 列出所有记忆
python3 cli.py list --user boss --agent dev

# 查看单条记忆
python3 cli.py get --id <memory_id>

# 删除记忆
python3 cli.py delete --id <memory_id>
```

### 使用 HTTP API

```bash
# 健康检查
curl http://127.0.0.1:8230/health

# 添加记忆
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"boss","agent_id":"dev","text":"重要信息..."}'

# 搜索
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"关键词","user_id":"boss","agent_id":"dev","top_k":5}'

# 列出
curl 'http://127.0.0.1:8230/memory/list?user_id=boss&agent_id=dev'
```

## API 接口

| Method | Path | 说明 |
|--------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/memory/add` | 添加记忆 (messages 或 text) |
| POST | `/memory/search` | 语义搜索 |
| GET | `/memory/list` | 列出记忆 (支持 user_id, agent_id 过滤) |
| GET | `/memory/{id}` | 获取单条记忆 |
| PUT | `/memory/update` | 更新记忆 |
| DELETE | `/memory/{id}` | 删除记忆 |
| GET | `/memory/history/{id}` | 查看记忆变更历史 |

## 数据隔离

使用 `user_id` + `agent_id` 二维隔离：

- `user_id`: 用户级别（如 `boss`）
- `agent_id`: Agent 级别（如 `dev`, `main`）
- 支持跨 agent 检索（不传 agent_id 即可）

## 配置

环境变量（均有默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AWS_REGION` | us-east-1 | AWS 区域 |
| `OPENSEARCH_HOST` | vpc-internal-logs-... | OpenSearch 地址 |
| `OPENSEARCH_PORT` | 443 | 端口 |
| `OPENSEARCH_USER` | admin | 用户名 |
| `OPENSEARCH_PASSWORD` | Amazon123! | 密码 |
| `OPENSEARCH_COLLECTION` | mem0_memories | 索引名 |
| `EMBEDDING_MODEL` | amazon.titan-embed-text-v2:0 | Embedding 模型 |
| `EMBEDDING_DIMS` | 1024 | 向量维度 |
| `LLM_MODEL` | us.anthropic.claude-3-5-haiku-... | LLM 模型 |
| `SERVICE_PORT` | 8230 | 服务端口 |

## 文件结构

```
mem0-memory-service/
├── server.py               # FastAPI 主服务
├── config.py               # 集中配置
├── cli.py                  # 命令行客户端
├── migrate_memory_md.py    # MEMORY.md 迁移工具
├── test_connection.py      # 连通性测试
├── mem0-memory.service     # systemd 服务配置
└── README.md
```

## 注意事项

### OpenSearch 3.x 兼容性
mem0 官方的 OpenSearch adapter 使用了 `nmslib` 引擎，OpenSearch 3.0+ 已废弃。
已修改 `/home/ec2-user/.local/lib/python3.11/site-packages/mem0/vector_stores/opensearch.py`
将 `engine: nmslib` → `engine: faiss`，`space_type: cosinesimil` → `space_type: innerproduct`。

⚠️ **升级 mem0 版本时需要重新 patch**，直到官方修复此问题。
