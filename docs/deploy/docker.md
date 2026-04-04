# Docker Deployment

Deploy mem0 Memory Service using Docker Compose. This is an alternative to the [systemd deployment](./systemd.md) — both methods are fully supported.

## Prerequisites

- Docker Engine 20.10+
- Docker Compose V2 (`docker compose`)
- OpenClaw installed on the host machine
- AWS credentials configured (IAM Role or Access Key)

### Required AWS Permissions

The AWS identity used (IAM Role or Access Key) must have the following permissions:

**S3 Vectors** (when `VECTOR_STORE=s3vectors`):
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
> ⚠️ Both the bucket ARN and `/*` (for index-level operations like `GetIndex`, `PutVectors`) are required. Only specifying the bucket ARN will cause `AccessDeniedException` on index operations.

**AWS Bedrock** (LLM + Embedding):
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

**On EC2 with IAM Role**: Attach the above policy to the instance's IAM Role. The Docker container accesses credentials via the EC2 Instance Metadata Service (IMDS) automatically — no `AWS_ACCESS_KEY_ID` needed in `.env`.

**Outside EC2**: Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in `.env`.

## 🚀 Quick Trial: Local pgvector (Demo / Local Dev, No Cloud Required)

If you just want to try mem0 Memory Service locally without setting up S3 Vectors or OpenSearch, use the built-in PostgreSQL + pgvector backend. No AWS vector store credentials needed — only AWS Bedrock (LLM + Embedding) is required.

```bash
# 1. Clone the repo
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 2. Configure .env
cp .env.example .env
```

Edit `.env` with minimal settings:

```env
# Switch to local pgvector
VECTOR_STORE=pgvector

# PostgreSQL connection (matches docker-compose defaults)
PGVECTOR_HOST=mem0-postgres
PGVECTOR_DB=mem0
PGVECTOR_USER=mem0
PGVECTOR_PASSWORD=change-me-in-production

# AWS region and Bedrock models (still needed for LLM + Embedding)
AWS_REGION=us-east-1
LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0

# Your OpenClaw data directory
OPENCLAW_BASE=~/.openclaw
```

```bash
# 3. Start all services (including PostgreSQL)
docker compose --profile pgvector up -d

# 4. Verify
curl http://localhost:8230/health
```

Three containers will start:
- `mem0-postgres` — PostgreSQL 17 with pgvector extension
- `mem0-api` — FastAPI HTTP service on port 8230
- `mem0-pipeline` — Cron-based pipeline (snapshot / digest / dream)

> **pgvector data is stored locally** in a Docker named volume (`pgvector_data`). It persists across container restarts and is managed by Docker.

### When to switch to S3 Vectors or OpenSearch

pgvector is great for local development and single-machine deployments. Consider switching to a managed vector store when:

| Scenario | Recommended backend |
|----------|-------------------|
| Single machine, local dev, quick trial | **pgvector** (this guide) |
| AWS-hosted, want serverless storage | **S3 Vectors** |
| Need full-text + vector hybrid search | **OpenSearch** |
| High-availability, multi-node | **OpenSearch** or **S3 Vectors** |

To migrate data from pgvector to S3 Vectors later, use the built-in migration tool:

```bash
# Start new service with S3 Vectors on port 8231, then:
python3 tools/migrate_s3vectors_to_pgvector.py migrate \
  --source-url http://127.0.0.1:8230 \
  --target-url http://127.0.0.1:8231 \
  --user-ids boss
```

## 🐳 Production Deployment: Docker with Managed Vector Store (S3 Vectors / OpenSearch)

```bash
# 1. Clone the repo
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 2. Configure .env
cp .env.example .env
vim .env   # Fill in OpenSearch/S3Vectors + AWS region + model settings

# 3. Start services
docker compose up -d
```

That's it. Two containers will start:
- `mem0-api` — FastAPI HTTP service on port 8230
- `mem0-pipeline` — Cron-based pipeline (snapshot / digest / dream)

## Configuration

### .env Settings

All standard settings (OpenSearch, S3Vectors, LLM, Embedding) work the same as systemd deployment. Docker-specific settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENCLAW_BASE` | `~/.openclaw` | OpenClaw data directory on the host. The pipeline container bind-mounts this path to read/write diary files. |
| `DATA_DIR` | `./data` | State and log files directory. Mapped to `/app/data` inside containers. |
| `AWS_CONFIG_DIR` | `~/.aws` | AWS credentials directory on the host. Mounted read-only into the pipeline container. |
| `MEM0_API_URL` | `http://127.0.0.1:8230` | mem0 API URL. The pipeline container overrides this to `http://mem0-api:8230` automatically. |

### OPENCLAW_BASE

This is the most important Docker-specific setting. Set it to the path where OpenClaw stores its data on your host machine:

```bash
# In .env
OPENCLAW_BASE=/home/youruser/.openclaw
```

The pipeline container mounts this directory to `/openclaw` and sets `OPENCLAW_BASE=/openclaw` internally, so all scripts can find agent workspaces, session files, and diary files.

### AWS Credentials

Two options:

**Option 1: Mount ~/.aws (recommended for EC2 with IAM Role)**

The default `docker-compose.yml` already mounts `~/.aws:/root/.aws:ro`. If your host uses an IAM Role, this just works.

```bash
# In .env (optional, only if your .aws is elsewhere)
AWS_CONFIG_DIR=/home/youruser/.aws
```

**Option 2: Environment variables**

```bash
# In .env
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

### S3Vectors Filter Patch

If using S3Vectors as vector store, apply the patch before starting:

```bash
docker compose run --rm mem0-api python3 tools/patch_s3vectors_filter.py
docker compose restart mem0-api
```

## Directory Structure

After running, the `data/` directory contains:

```
data/
├── .snapshot_offsets.json    # Session snapshot offsets
├── auto_digest_offset.json  # Digest incremental offsets
├── .memory_sync_state.json  # MEMORY.md sync hashes
├── snapshot.log             # Session snapshot logs
├── auto_digest.log          # Auto digest logs
└── auto_dream.log           # AutoDream logs
```

This directory is shared between both containers via volume mount.

## Common Commands

```bash
# View service status
docker compose ps

# View API logs
docker compose logs -f mem0-api

# View pipeline logs (cron output)
docker compose logs -f mem0-pipeline

# View specific pipeline log
tail -f data/auto_digest.log

# Restart services
docker compose restart

# Restart only API
docker compose restart mem0-api

# Stop all services
docker compose down

# Rebuild after code update
docker compose build
docker compose up -d

# Run CLI commands
docker compose exec mem0-api python3 cli.py search --user boss --agent agent1 --query "deploy"

# Manually trigger a pipeline
docker compose exec mem0-pipeline python3 pipelines/session_snapshot.py
docker compose exec mem0-pipeline python3 pipelines/auto_digest.py --today
docker compose exec mem0-pipeline python3 pipelines/auto_dream.py

# Health check
curl http://localhost:8230/health
```

## Pipeline Schedule

The pipeline container runs three cron jobs:

| Script | Schedule | Purpose |
|--------|----------|---------|
| `session_snapshot.py` | Every 5 min | Save active session conversations to diary files |
| `auto_digest.py --today` | Every 15 min | Extract short-term memories from today's diary |
| `auto_dream.py` | Daily UTC 02:00 | Consolidate diary→long-term + archive old short-term |

## Docker vs systemd Comparison

| Aspect | Docker | systemd |
|--------|--------|---------|
| Setup | `docker compose up -d` | `install.sh` + systemd units |
| Dependencies | Docker only | Python 3.9+, pip, systemd |
| Isolation | Full container isolation | Shares host Python env |
| Scheduling | cron in container | systemd timers |
| Logs | `docker compose logs` + `data/*.log` | `journalctl` + project root `*.log` |
| Upgrade | `git pull && docker compose build && docker compose up -d` | `git pull && pip install -r requirements.txt && systemctl restart` |
| AWS credentials | Mount `~/.aws` or env vars | Host IAM Role or env vars |
| OpenClaw access | Bind mount `OPENCLAW_BASE` | Direct filesystem access |

Both methods are fully supported and can coexist on the same machine (use different ports if needed).
