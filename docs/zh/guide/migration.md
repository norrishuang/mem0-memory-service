# 迁移工具

## OpenSearch → S3 Vectors

使用 `migrate_to_s3vectors.py` 将现有记忆从 OpenSearch 迁移到 S3Vectors。

### 前提条件

需要同时配置 OpenSearch 和 S3Vectors 的环境变量 — 在 `.env` 中保留 OpenSearch 配置，同时设置 `S3VECTORS_BUCKET_NAME`。

### 用法

```bash
# 迁移所有用户的记忆
python3 migrate_to_s3vectors.py

# 仅迁移指定用户
python3 migrate_to_s3vectors.py --user boss

# 指定用户和代理
python3 migrate_to_s3vectors.py --user boss --agent dev

# 试运行模式（仅预览，不写入）
python3 migrate_to_s3vectors.py --dry-run
```

::: warning 安全提示
迁移过程**不会**删除 OpenSearch 中的源数据。请在验证 S3Vectors 数据完整性后，再手动清理 OpenSearch。
:::

## MEMORY.md → mem0

如果你之前使用 `MEMORY.md` 管理记忆，可以迁移到 mem0：

```bash
# 编辑脚本中的 MEMORY_FILE 路径、USER_ID、AGENT_ID
vim migrate_memory_md.py

# 执行迁移
python3 migrate_memory_md.py
```

## pgvector → S3 Vectors

使用 `tools/migrate_between_stores.py` 将本地 pgvector 中的记忆迁移到 AWS S3 Vectors。

### 步骤 1：启动源服务（pgvector，端口 8230）

确保当前服务以 `VECTOR_STORE=pgvector` 运行：

```bash
docker compose --profile pgvector up -d
curl http://localhost:8230/health  # 验证
```

### 步骤 2：启动目标服务（S3 Vectors，端口 8231）

创建临时配置文件 `.env.s3vectors`：

```env
VECTOR_STORE=s3vectors
S3VECTORS_BUCKET_NAME=your-bucket-name
S3VECTORS_INDEX_NAME=mem0
AWS_REGION=us-east-1
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
SERVICE_PORT=8231
```

使用该配置启动第二个 API 容器：

```bash
docker run -d \
  --name mem0-api-s3vectors \
  --network mem0-memory-service_default \
  -p 8231:8231 \
  --env-file .env.s3vectors \
  mem0-memory-service-mem0-api
curl http://localhost:8231/health  # 验证
```

### 步骤 3：迁移数据

```bash
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared
```

### 步骤 4：验证并切换

```bash
# 在目标服务中搜索以确认数据完整性
python3 cli.py search --user boss --agent dev --query "test" \
  --top-k 3  # 设置 MEM0_API_URL=http://127.0.0.1:8231

# 更新 .env 切换主服务
sed -i 's/VECTOR_STORE=pgvector/VECTOR_STORE=s3vectors/' .env
# 在 .env 中添加 S3Vectors 配置，然后重启
docker compose up -d mem0-api
```

### 步骤 5：清理

```bash
docker stop mem0-api-s3vectors && docker rm mem0-api-s3vectors
rm .env.s3vectors migration_state.json
```

::: warning 安全提示
迁移过程**不会**删除源数据。请在验证 S3 Vectors 数据完整性后，再停用 pgvector 容器。
:::

## pgvector → OpenSearch

使用 `tools/migrate_between_stores.py` 将本地 pgvector 中的记忆迁移到 OpenSearch。

### 步骤 1：启动源服务（pgvector，端口 8230）

```bash
docker compose --profile pgvector up -d
curl http://localhost:8230/health
```

### 步骤 2：启动目标服务（OpenSearch，端口 8231）

创建临时配置文件 `.env.opensearch`：

```env
VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_COLLECTION=mem0_memories
AWS_REGION=us-east-1
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
SERVICE_PORT=8231
```

启动第二个 API 容器：

```bash
docker run -d \
  --name mem0-api-opensearch \
  --network mem0-memory-service_default \
  -p 8231:8231 \
  --env-file .env.opensearch \
  mem0-memory-service-mem0-api
curl http://localhost:8231/health
```

### 步骤 3：迁移数据

```bash
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared
```

### 步骤 4：验证并切换

```bash
# 更新 .env 并重启
sed -i 's/VECTOR_STORE=pgvector/VECTOR_STORE=opensearch/' .env
# 在 .env 中添加 OpenSearch 配置，然后重启
docker compose up -d mem0-api
```

### 步骤 5：清理

```bash
docker stop mem0-api-opensearch && docker rm mem0-api-opensearch
rm .env.opensearch migration_state.json
```

::: warning 安全提示
迁移过程**不会**删除 pgvector 中的源数据。请在验证 OpenSearch 数据完整性后，再停用 pgvector 容器。
:::
