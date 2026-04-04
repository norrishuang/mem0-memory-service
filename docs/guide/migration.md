# Data Migration

All migrations use `tools/migrate_between_stores.py` — a universal tool that works between **any two vector store backends** (pgvector, S3 Vectors, OpenSearch) via the HTTP API.

## How It Works

Migration runs in two steps:
1. **Dump** — export all memories from the source service to a JSONL file
2. **Load** — import the JSONL file into the target service

You need **two mem0 API instances running simultaneously**: the source on one port, the target on another.

## Quick Reference

```bash
# Export from source (port 8230)
python3 tools/migrate_between_stores.py dump \
  --source-url http://127.0.0.1:8230 --user-ids boss,shared --output dump.jsonl

# Import to target (port 8231)
python3 tools/migrate_between_stores.py load \
  --target-url http://127.0.0.1:8231 --input dump.jsonl

# Or do both in one command
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared
```

> **Resume support**: progress is saved to `migration_state.json`. If interrupted, re-run the same command to skip already-migrated records.

## Migration Scenarios

### pgvector → S3 Vectors

```bash
# 1. Source is already running on port 8230 (VECTOR_STORE=pgvector)

# 2. Start target service (S3 Vectors) on port 8231
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

# 3. Migrate
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared

# 4. Switch main service to S3 Vectors
#    Edit .env: VECTOR_STORE=s3vectors (add S3Vectors settings)
#    docker compose up -d mem0-api

# 5. Cleanup
docker rm -f mem0-target && rm -f migration_state.json
```

### pgvector → OpenSearch

```bash
# 1. Source is already running on port 8230 (VECTOR_STORE=pgvector)

# 2. Start target service (OpenSearch) on port 8231
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

# 3. Migrate
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared

# 4. Switch: edit .env → VECTOR_STORE=opensearch, docker compose up -d mem0-api
# 5. Cleanup: docker rm -f mem0-target && rm -f migration_state.json
```

### S3 Vectors → OpenSearch (or any other direction)

Same pattern — start source on 8230, start target on 8231 with the right `VECTOR_STORE` env vars, run `migrate`.

## OpenSearch → S3 Vectors (Direct Method)

If you prefer not to run two services simultaneously, use the legacy direct-connection tool:

```bash
# Requires both OpenSearch and S3Vectors env vars in .env simultaneously
python3 tools/migrate_to_s3vectors.py --user boss
python3 tools/migrate_to_s3vectors.py --dry-run  # preview first
```

> Source data is **never deleted** by any migration tool. Always verify the target before switching.
