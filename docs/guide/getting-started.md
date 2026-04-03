# Getting Started

## Overview

mem0 Memory Service for OpenClaw is a unified memory layer based on [mem0](https://github.com/mem0ai/mem0), providing persistent semantic memory storage for AI agents.

Agents automatically store and retrieve memories through conversations — no manual file management required.

### Design Philosophy

mem0's core strength is **memory extraction and deduplication** — automatically extracting key facts from conversations, intelligently merging similar memories, and providing semantic retrieval. However, mem0 itself does not distinguish between "short-term events" and "long-term knowledge".

This service adds a **memory lifecycle management** layer on top of mem0:

```
mem0 handles:           Semantic extraction, intelligent deduplication, vector retrieval
This service handles:   Tiered storage, lifecycle management, activity-based archiving
```

### Architecture

```
OpenClaw Agents (agent1, agent2, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (Docker / systemd)  │
│                      │
│  Tiered Memory:      │  Long-term (no run_id)
│  - Long: tech        │  Short-term (run_id=date)
│    decisions,        │  Archive: activity-based
│    lessons, prefs    │  upgrade/delete
│  - Short: daily      │
│    discussions       │
└──────────┬───────────┘
           │
     ┌─────▼─────┐       ┌──────────────────┐
     │   mem0    │──────▶│  LLM (Bedrock)    │
     │           │──────▶│  Embedder (Titan) │
     └─────┬─────┘       └──────────────────┘
           ▼
   OpenSearch / S3 Vectors
```

## Prerequisites

- **Docker 20.10+** and **docker compose** (v2)
- **OpenSearch** cluster (2.x or 3.x, k-NN plugin required) or **AWS S3 Vectors**
- **AWS Bedrock** access (or modify `config.py` for other LLM/Embedder providers)
- **AWS IAM permissions** — the deployment environment needs:
  - `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for the Embedding and LLM models
  - If using S3Vectors: `s3vectors:*` on the bucket resource
  - EC2 users: attach an IAM Role to the instance — no Access Key needed

## Installation

### Method 1: Docker One-Click Install (Recommended)

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
./install.sh
```

The install script will interactively guide you through configuration, then automatically:
1. Check Docker and docker compose availability
2. Generate `.env` configuration file
3. Run `docker compose up -d` (builds and starts all containers)
4. Verify service health
5. Install OpenClaw Skill

All automation pipelines (session snapshot, digest, memory sync, dream) run inside the Docker pipeline container — no separate timer setup needed.

### Method 2: AI Deploy Prompt

Send the following prompt to your AI assistant to auto-deploy:

> Deploy the **mem0 Memory Service for OpenClaw** for me. Repo: https://github.com/norrishuang/mem0-memory-service
>
> **Step 1: Clone**
> ```bash
> git clone https://github.com/norrishuang/mem0-memory-service.git
> cd mem0-memory-service
> ```
>
> **Step 2: Configure .env**
> Copy `.env.example` to `.env` and set:
> - `VECTOR_STORE`: `opensearch` (default) or `s3vectors`
> - If OpenSearch: set `OPENSEARCH_HOST`, `OPENSEARCH_PORT`, `OPENSEARCH_PASSWORD`
> - If S3Vectors: set `S3VECTORS_BUCKET_NAME`, `S3VECTORS_INDEX_NAME`, `AWS_REGION`
> - `OPENCLAW_BASE`: path to your OpenClaw data directory (default `~/.openclaw`)
> - `EMBEDDING_MODEL`: default `amazon.titan-embed-text-v2:0`
> - `LLM_MODEL`: default `us.anthropic.claude-haiku-4-5-20251001-v1:0`
>
> **Step 3: Start with Docker**
> ```bash
> docker compose up -d
> ```
>
> **Step 4: Verify**
> ```bash
> curl http://localhost:8230/health
> ```
>
> **Step 5: Install OpenClaw Skill**
> ```bash
> mkdir -p ~/.openclaw/skills/mem0-memory
> cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
> ```
> Then enable it in OpenClaw Settings → Skills → mem0-memory.
>
> **Step 6: Test**
> ```bash
> docker compose exec mem0-api python3 cli.py add --user me --agent dev \
>   --text "mem0 memory service deployed successfully" \
>   --metadata '{"category":"experience"}'
> docker compose exec mem0-api python3 cli.py search --user me --agent dev --query "deploy"
> ```

### Method 3: systemd (Advanced)

If you prefer running directly on the host without Docker:

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Configure
cp .env.example .env
vim .env  # Fill in your OpenSearch/S3Vectors and AWS configuration

# 3. Test connectivity
python3 test_connection.py

# 4. Start the service
sudo cp systemd/mem0-memory.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory.service

# 5. Set up automation timers (run as current user)
mkdir -p ~/.config/systemd/user/

# Session snapshot — captures conversations every 5 min (cross-session memory bridge)
cp systemd/mem0-snapshot.service systemd/mem0-snapshot.timer ~/.config/systemd/user/

# MEMORY.md sync — syncs curated knowledge to long-term memory daily at UTC 01:00
cp systemd/mem0-memory-sync.service systemd/mem0-memory-sync.timer ~/.config/systemd/user/

# Auto digest — distills yesterday's diary into short-term memory daily at UTC 01:30
cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/

# Archive — promotes/deletes 7-day-old short-term memories daily at UTC 02:00
cp systemd/mem0-dream.service systemd/mem0-dream.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
systemctl --user enable --now mem0-memory-sync.timer
systemctl --user enable --now mem0-auto-digest.timer
systemctl --user enable --now mem0-dream.timer
```

For full systemd details, see [systemd Setup](../deploy/systemd).

## Enabling the Skill for OpenClaw Agents

After installation, enable the **mem0-memory** skill in OpenClaw so all agents automatically get memory behavior:

```bash
# Copy skill to OpenClaw skills directory
mkdir -p ~/.openclaw/skills/mem0-memory
cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
```

Then go to **OpenClaw Settings → Skills** and enable `mem0-memory`.

**That's it.** Every agent (new or existing) automatically inherits the full memory behavior on their next session start:
- Proactive memory retrieval before answering
- Diary writing during conversations
- MEMORY.md maintenance during heartbeats
- Correct `--agent <id>` targeting without any AGENTS.md changes

> No need to modify individual `AGENTS.md` files. The skill applies to all agents uniformly.

**Want to understand why this works?** See [How It Works](./how-it-works) for the full explanation of the skill system, memory flow, and agent behavior rules.

### Known Issues

If using **S3Vectors** as the vector backend, you must apply a filter format patch before use. See [PATCHES.md](https://github.com/norrishuang/mem0-memory-service/blob/main/PATCHES.md) for details.

```bash
python3 patch_s3vectors_filter.py
```

> ⚠️ Re-run the patch after every `pip upgrade mem0ai`.

## Quick Usage

```bash
# Add a long-term memory
python3 cli.py add --user me --agent <your-agent-id> --text "Important lesson learned..."

# Add a short-term memory (today's date)
python3 cli.py add --user me --agent <your-agent-id> --run 2026-03-27 \
  --text "Today's discussion about refactoring"

# Semantic search
python3 cli.py search --user me --agent <your-agent-id> --query "refactoring" --top-k 5

# Combined search (long-term + recent 7 days)
python3 cli.py search --user me --agent <your-agent-id> --query "refactoring" --combined
```

## Memory Tiering

| Type | run_id | Lifetime | Use Case |
|------|--------|----------|----------|
| **Long-term** | None | Permanent | Tech decisions, lessons, preferences |
| **Short-term** | `YYYY-MM-DD` | 7 days → AutoDream | Daily discussions, temp decisions, task progress |

**Three paths to long-term memory:**
1. `memory_sync.py` — syncs `MEMORY.md` daily (same-day, curated knowledge)
2. `pipelines/auto_dream.py` (AutoDream) — promotes active short-term memories after 7 days
3. Agent explicit write — call CLI without `--run` at any time

## Shared Knowledge Base

Memories with `category=experience` are automatically shared across all agents and users. When any agent adds a memory tagged as `experience`, it is written to both the personal memory space and a global `shared` pool.

During retrieval, every search automatically includes results from the shared pool — so all agents benefit from the team's collective experience without any extra configuration.
