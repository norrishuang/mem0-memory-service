# Migration Tool

## OpenSearch → S3 Vectors

Use `migrate_to_s3vectors.py` to migrate existing memories from OpenSearch to S3Vectors.

### Prerequisites

Both OpenSearch and S3Vectors environment variables must be configured simultaneously — keep OpenSearch config in `.env` and also set `S3VECTORS_BUCKET_NAME`.

### Usage

```bash
# Migrate all users' memories
python3 migrate_to_s3vectors.py

# Migrate a specific user only
python3 migrate_to_s3vectors.py --user boss

# Specific user and agent
python3 migrate_to_s3vectors.py --user boss --agent dev

# Dry-run mode (preview only, no writes)
python3 migrate_to_s3vectors.py --dry-run
```

::: warning Safety Note
The migration does **not** delete source data in OpenSearch. Verify S3Vectors data integrity before manually cleaning up OpenSearch.
:::

## MEMORY.md → mem0

If you previously used `MEMORY.md` to manage memories, migrate to mem0:

```bash
# Edit MEMORY_FILE path, USER_ID, AGENT_ID in the script
vim migrate_memory_md.py

# Run migration
python3 migrate_memory_md.py
```

## pgvector → S3 Vectors

Use `tools/migrate_between_stores.py` to migrate from local pgvector to AWS S3 Vectors.

### Step 1: Start source service (pgvector, port 8230)

Ensure your current service is running with `VECTOR_STORE=pgvector`:

```bash
docker compose --profile pgvector up -d
curl http://localhost:8230/health  # verify
```

### Step 2: Start target service (S3 Vectors, port 8231)

Create a temporary `.env.s3vectors` with S3 Vectors configuration:

```env
VECTOR_STORE=s3vectors
S3VECTORS_BUCKET_NAME=your-bucket-name
S3VECTORS_INDEX_NAME=mem0
AWS_REGION=us-east-1
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
SERVICE_PORT=8231
```

Start a second API container using this config:

```bash
docker run -d \
  --name mem0-api-s3vectors \
  --network mem0-memory-service_default \
  -p 8231:8231 \
  --env-file .env.s3vectors \
  mem0-memory-service-mem0-api
curl http://localhost:8231/health  # verify
```

### Step 3: Migrate data

```bash
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared
```

### Step 4: Verify and switch

```bash
# Search in target to confirm data integrity
python3 cli.py search --user boss --agent dev --query "test" \
  --top-k 3  # set MEM0_API_URL=http://127.0.0.1:8231

# Update .env to switch main service
sed -i 's/VECTOR_STORE=pgvector/VECTOR_STORE=s3vectors/' .env
# Add S3Vectors settings to .env, then restart
docker compose up -d mem0-api
```

### Step 5: Cleanup

```bash
docker stop mem0-api-s3vectors && docker rm mem0-api-s3vectors
rm .env.s3vectors migration_state.json
```

::: warning Safety Note
Migration does **not** delete source data. Verify S3 Vectors data integrity before decommissioning the pgvector container.
:::

## pgvector → OpenSearch

Use `tools/migrate_between_stores.py` to migrate from local pgvector to OpenSearch.

### Step 1: Start source service (pgvector, port 8230)

```bash
docker compose --profile pgvector up -d
curl http://localhost:8230/health
```

### Step 2: Start target service (OpenSearch, port 8231)

Create a temporary `.env.opensearch` with OpenSearch configuration:

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

Start a second API container:

```bash
docker run -d \
  --name mem0-api-opensearch \
  --network mem0-memory-service_default \
  -p 8231:8231 \
  --env-file .env.opensearch \
  mem0-memory-service-mem0-api
curl http://localhost:8231/health
```

### Step 3: Migrate data

```bash
python3 tools/migrate_between_stores.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss,shared
```

### Step 4: Verify and switch

```bash
# Update .env and restart
sed -i 's/VECTOR_STORE=pgvector/VECTOR_STORE=opensearch/' .env
# Add OpenSearch settings to .env, then restart
docker compose up -d mem0-api
```

### Step 5: Cleanup

```bash
docker stop mem0-api-opensearch && docker rm mem0-api-opensearch
rm .env.opensearch migration_state.json
```

::: warning Safety Note
Migration does **not** delete source data in pgvector. Verify OpenSearch data integrity before stopping the pgvector container.
:::
