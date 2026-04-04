# 数据迁移

所有迁移均使用 `tools/migrate_between_stores.py` — 一个通用工具，通过 HTTP API 在**任意两个向量存储后端**（pgvector、S3 Vectors、OpenSearch）之间迁移数据。

## 工作原理

迁移分两步执行：
1. **Dump** — 从源服务导出所有记忆到 JSONL 文件
2. **Load** — 将 JSONL 文件导入目标服务

你需要**同时运行两个 mem0 API 实例**：源服务在一个端口，目标服务在另一个端口。

## 快速参考

```bash
# 从源服务导出（端口 8230）
python3 tools/migrate_between_stores.py dump \
  --source-url http://127.0.0.1:8230 --user-ids boss,shared --output dump.jsonl

# 导入到目标服务（端口 8231）
python3 tools/migrate_between_stores.py load \
  --target-url http://127.0.0.1:8231 --input dump.jsonl

# 或一条命令完成
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared
```

> **断点续传支持**：进度保存在 `migration_state.json`。如果中断，重新运行相同命令即可跳过已迁移的记录。

## 迁移场景

### pgvector → S3 Vectors

```bash
# 1. 源服务已在端口 8230 运行（VECTOR_STORE=pgvector）

# 2. 启动目标服务（S3 Vectors）在端口 8231
docker run -d --name mem0-target \
  --network mem0-memory-service_default \
  -p 8231:8230 \
  -e VECTOR_STORE=s3vectors \
  -e S3VECTORS_BUCKET_NAME=your-bucket \
  -e S3VECTORS_INDEX_NAME=mem0 \
  -e AWS_REGION=us-east-1 \
  -e EMBEDDING_MODEL=amazon.titan-embed-text-v2:0 \
  -e LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0 \
  mem0-memory-service-mem0-api

# 3. 迁移
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared

# 4. 切换主服务到 S3 Vectors
#    编辑 .env: VECTOR_STORE=s3vectors（添加 S3Vectors 配置）
#    docker compose up -d mem0-api

# 5. 清理
docker rm -f mem0-target && rm -f migration_state.json
```

### pgvector → OpenSearch

```bash
# 1. 源服务已在端口 8230 运行（VECTOR_STORE=pgvector）

# 2. 启动目标服务（OpenSearch）在端口 8231
docker run -d --name mem0-target \
  --network mem0-memory-service_default \
  -p 8231:8230 \
  -e VECTOR_STORE=opensearch \
  -e OPENSEARCH_HOST=your-host.es.amazonaws.com \
  -e OPENSEARCH_PORT=443 \
  -e OPENSEARCH_USER=admin \
  -e OPENSEARCH_PASSWORD=your-password \
  -e OPENSEARCH_USE_SSL=true \
  -e AWS_REGION=us-east-1 \
  -e EMBEDDING_MODEL=amazon.titan-embed-text-v2:0 \
  -e LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0 \
  mem0-memory-service-mem0-api

# 3. 迁移
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared

# 4. 切换：编辑 .env → VECTOR_STORE=opensearch，docker compose up -d mem0-api
# 5. 清理：docker rm -f mem0-target && rm -f migration_state.json
```

### S3 Vectors → OpenSearch（或其他任意方向）

同样的模式 — 源服务在 8230，目标服务在 8231 并设置对应的 `VECTOR_STORE` 环境变量，运行 `migrate`。

## OpenSearch → S3 Vectors（直连方式）

如果不想同时运行两个服务，可以使用旧版直连工具：

```bash
# 需要在 .env 中同时配置 OpenSearch 和 S3Vectors 的环境变量
python3 tools/migrate_to_s3vectors.py --user boss
python3 tools/migrate_to_s3vectors.py --dry-run  # 先预览
```

> 迁移工具**不会删除**源数据。切换前请务必验证目标数据完整性。
