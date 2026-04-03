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

## Deployment

Choose the deployment method that fits your setup:

### 🚀 Option A: Local pgvector (Quickest, No Cloud Vector Store)

Just want to try it out? Start with the built-in PostgreSQL + pgvector — no S3 Vectors or OpenSearch needed. Only requires AWS Bedrock (LLM + Embedding).

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
cp .env.example .env  # Set VECTOR_STORE=pgvector + AWS Bedrock credentials
docker compose --profile pgvector up -d
```

→ [Full guide: Docker + pgvector Quickstart](../deploy/docker#quickest-start-local-pgvector-no-cloud-required)

---

### 🐳 Option B: Docker (Recommended)

Production-ready. Uses Docker Compose with your choice of vector store (S3 Vectors, OpenSearch, or pgvector). All pipelines run as cron jobs inside the container.

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
cp .env.example .env  # Configure VECTOR_STORE + credentials
docker compose up -d
```

→ [Full guide: Docker Deployment](../deploy/docker)

---

### ⚙️ Option C: systemd (Advanced)

Run directly on the host without Docker. Suitable for environments where Docker is not available or not preferred.

→ [Full guide: systemd Deployment](../deploy/systemd)

---

> **Not sure which to pick?** Start with **Option A** (pgvector) for a quick local trial. When ready for production, switch to **Option B** with S3 Vectors or OpenSearch. See [When to switch backends](../deploy/docker#when-to-switch-to-s3-vectors-or-opensearch).

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
