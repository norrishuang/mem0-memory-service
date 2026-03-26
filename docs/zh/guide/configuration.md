# 配置

所有配置通过环境变量或 `.env` 文件管理。`install.sh` 脚本会自动生成该文件。

## 设置

```bash
cp .env.example .env
vim .env
```

## 环境变量

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS 区域 |
| `VECTOR_STORE` | `opensearch` | 向量引擎：`opensearch` 或 `s3vectors` |
| `OPENSEARCH_HOST` | `localhost` | OpenSearch 主机地址 |
| `OPENSEARCH_PORT` | `9200` | OpenSearch 端口 |
| `OPENSEARCH_USER` | `admin` | 用户名 |
| `OPENSEARCH_PASSWORD` | — | 密码 |
| `OPENSEARCH_USE_SSL` | `false` | 启用 SSL |
| `OPENSEARCH_VERIFY_CERTS` | `false` | 验证 SSL 证书 |
| `OPENSEARCH_COLLECTION` | `mem0_memories` | 索引名称 |
| `S3VECTORS_BUCKET_NAME` | — | S3Vectors 存储桶（`s3vectors` 模式必填） |
| `S3VECTORS_INDEX_NAME` | `mem0` | S3Vectors 索引名称 |
| `EMBEDDING_MODEL` | `amazon.titan-embed-text-v2:0` | 嵌入模型 |
| `EMBEDDING_DIMS` | `1024` | 向量维度 |
| `LLM_MODEL` | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | LLM 模型 |
| `LLM_TEMPERATURE` | `0.1` | LLM 温度参数 |
| `LLM_MAX_TOKENS` | `2000` | 最大 token 数 |
| `SERVICE_HOST` | `0.0.0.0` | 服务绑定地址 |
| `SERVICE_PORT` | `8230` | 服务端口 |

## `.env` 示例

```env
AWS_REGION=us-east-1

VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_COLLECTION=mem0_memories

EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIMS=1024

LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=2000

SERVICE_HOST=0.0.0.0
SERVICE_PORT=8230
```

## 数据隔离

使用 `user_id` + `agent_id` 进行二维隔离：

- **user_id** — 不同用户的记忆完全隔离
- **agent_id** — 同一用户的不同代理独立管理记忆
- 省略 `agent_id` 可实现跨代理检索
