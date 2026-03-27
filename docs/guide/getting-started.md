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
│  (systemd managed)   │
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

- **Python 3.9+**
- **OpenSearch** cluster (2.x or 3.x, k-NN plugin required) or **AWS S3 Vectors**
- **AWS Bedrock** access (or modify `config.py` for other LLM/Embedder providers)
- **Amazon Bedrock IAM permissions** — the deployment server needs `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for the Embedding and LLM models. See [README](https://github.com/norrishuang/mem0-memory-service#amazon-bedrock-permissions) for the minimum IAM policy example.

## Installation

### Method 1: One-Click Install (Recommended)

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
./install.sh
```

The install script will interactively guide you through configuration, then automatically:
1. Install Python dependencies
2. Generate `.env` configuration file
3. Test OpenSearch and Bedrock connectivity
4. Create systemd service (auto-start on boot)
5. Set up all automation timers

### Method 2: Manual Installation

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
cp systemd/mem0-archive.service systemd/mem0-archive.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
systemctl --user enable --now mem0-memory-sync.timer
systemctl --user enable --now mem0-auto-digest.timer
systemctl --user enable --now mem0-archive.timer
```

### Method 3: One-Line AI Deploy Prompt

Send the following prompt to your AI assistant to auto-deploy:

> Deploy the **mem0 Memory Service for OpenClaw** for me. Repo: https://github.com/norrishuang/mem0-memory-service
>
> **Step 1: Clone and install**
> ```bash
> git clone https://github.com/norrishuang/mem0-memory-service.git
> cd mem0-memory-service
> pip3 install -r requirements.txt
> ```
>
> **Step 2: Configure .env**
> Copy `.env.example` to `.env` and set:
> - `VECTOR_STORE`: `opensearch` (default) or `s3vectors`
> - If OpenSearch: set `OPENSEARCH_HOST`, `OPENSEARCH_PORT`, `OPENSEARCH_INDEX`
> - If S3Vectors: set `S3VECTORS_BUCKET_NAME`, `S3VECTORS_INDEX_NAME`, `AWS_REGION`
> - `EMBEDDING_MODEL`: default `amazon.titan-embed-text-v2:0`
> - `LLM_MODEL`: default `us.anthropic.claude-haiku-4-5-20251001-v1:0`
>
> **Step 3: (S3Vectors only) Apply the filter patch**
> ```bash
> python3 patch_s3vectors_filter.py
> ```
> This patches a known upstream mem0 bug (PR #4554 pending). Re-run after `pip upgrade mem0ai`.
>
> **Step 4: Verify connectivity**
> ```bash
> python3 test_connection.py
> ```
>
> **Step 5: Start the memory service**
> ```bash
> sudo cp systemd/mem0-memory.service /etc/systemd/system/
> sudo systemctl daemon-reload
> sudo systemctl enable --now mem0-memory.service
> ```
>
> **Step 6: Set up automation timers (as current user)**
> ```bash
> mkdir -p ~/.config/systemd/user/
> cp systemd/mem0-snapshot.service systemd/mem0-snapshot.timer ~/.config/systemd/user/
> cp systemd/mem0-memory-sync.service systemd/mem0-memory-sync.timer ~/.config/systemd/user/
> cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/
> cp systemd/mem0-archive.service systemd/mem0-archive.timer ~/.config/systemd/user/
> systemctl --user daemon-reload
> systemctl --user enable --now mem0-snapshot.timer
> systemctl --user enable --now mem0-memory-sync.timer
> systemctl --user enable --now mem0-auto-digest.timer
> systemctl --user enable --now mem0-archive.timer
> ```
>
> **Step 7: Enable the mem0-memory Skill in OpenClaw**
>
> Copy the skill to your OpenClaw skills directory:
> ```bash
> mkdir -p ~/.openclaw/skills/mem0-memory
> cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
> ```
> Then enable it in OpenClaw Settings → Skills → mem0-memory.
>
> **Step 8: Test write and search**
> ```bash
> python3 cli.py add --user me --agent dev \
>   --text "mem0 memory service deployed successfully" \
>   --metadata '{"category":"experience"}'
> python3 cli.py search --user me --agent dev --query "deploy"
> ```

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
| **Short-term** | `YYYY-MM-DD` | 7 days → archive | Daily discussions, temp decisions, task progress |

**Three paths to long-term memory:**
1. `memory_sync.py` — syncs `MEMORY.md` daily (same-day, curated knowledge)
2. `archive.py` — promotes active short-term memories after 7 days
3. Agent explicit write — call CLI without `--run` at any time

## Shared Knowledge Base

Memories with `category=experience` are automatically shared across all agents and users. When any agent adds a memory tagged as `experience`, it is written to both the personal memory space and a global `shared` pool.

During retrieval, every search automatically includes results from the shared pool — so all agents benefit from the team's collective experience without any extra configuration.
