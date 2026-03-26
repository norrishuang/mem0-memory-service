# Getting Started

## Overview

mem0 Memory Service for OpenClaw is a unified memory layer based on [mem0](https://github.com/mem0ai/mem0), providing persistent semantic memory storage for AI agents.

Agents can automatically store and retrieve memories through conversations, without manual file management.

### Design Philosophy

mem0's core strength is **memory extraction and deduplication** — automatically extracting key facts from conversations, intelligently merging similar memories, and providing semantic retrieval. However, mem0 itself does not distinguish between "short-term events" and "long-term knowledge".

This service adds a **memory lifecycle management** layer on top of mem0:

```
mem0 handles:           Semantic extraction, intelligent deduplication, vector retrieval
This service handles:   Tiered storage, lifecycle management, activity-based archiving
```

### Architecture

```
OpenClaw Agents (dev, main, ...)
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
     │           │──────▶│  Embedder (Titan)  │
     └─────┬─────┘       └──────────────────┘
           ▼
   OpenSearch / S3 Vectors
```

## Prerequisites

- **Python 3.9+**
- **OpenSearch** cluster (2.x or 3.x, k-NN plugin required) or **AWS S3 Vectors**
- **AWS Bedrock** access (or modify `config.py` for other LLM/Embedder providers)
- **Amazon Bedrock IAM permissions** — the deployment server needs `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` for the Embedding and LLM models. See [README](../../README.md#amazon-bedrock-permissions) for the minimum IAM policy example.

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

### Method 2: Manual Installation

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service

# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Configure
cp .env.example .env
vim .env  # Fill in your OpenSearch and AWS configuration

# 3. Test connectivity
python3 test_connection.py

# 4. Start the service
python3 server.py

# 5. (Optional) Set up systemd auto-start
sudo cp mem0-memory.service /etc/systemd/system/
# Edit the service file to update User/WorkingDirectory/EnvironmentFile paths
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory

# 6. Set up memory automation timers
# Digest timer (extract memories from diary every 15 min):
sudo cp mem0-digest.service mem0-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-digest.timer

# Archive timer (archive old short-term memories daily):
sudo cp mem0-archive.service mem0-archive.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-archive.timer

# Session snapshot timer (capture session conversations every 5 min — run as current user):
mkdir -p ~/.config/systemd/user/
cp mem0-snapshot.service mem0-snapshot.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
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
> This patches a known upstream mem0 bug (PR #4554 pending). Re-run after `pip upgrade mem0`.
>
> **Step 4: Verify connectivity**
> ```bash
> python3 test_connection.py
> ```
>
> **Step 5: Set up systemd service (auto-start)**
> ```bash
> sudo cp mem0-memory.service /etc/systemd/system/
> sudo systemctl daemon-reload
> sudo systemctl enable --now mem0-memory.service
> ```
>
> **Step 6: Set up memory automation timers**
>
> Digest timer (extract memories from diary every 15 min):
> ```bash
> sudo cp mem0-digest.service mem0-digest.timer /etc/systemd/system/
> sudo systemctl daemon-reload
> sudo systemctl enable --now mem0-digest.timer
> ```
>
> Archive timer (archive old short-term memories daily):
> ```bash
> sudo cp mem0-archive.service mem0-archive.timer /etc/systemd/system/
> sudo systemctl daemon-reload
> sudo systemctl enable --now mem0-archive.timer
> ```
>
> Session snapshot timer (capture session conversations every 5 min — run as current user):
> ```bash
> mkdir -p ~/.config/systemd/user/
> cp mem0-snapshot.service mem0-snapshot.timer ~/.config/systemd/user/
> systemctl --user daemon-reload
> systemctl --user enable --now mem0-snapshot.timer
> ```
>
> **Step 7: Test write and search**
> ```bash
> python3 cli.py add --user me --agent dev --text "mem0 memory service deployed successfully" --metadata '{"category":"experience"}'
> python3 cli.py search --user me --agent dev --query "deploy"
> ```

### Known Issues

If using **S3Vectors** as the vector backend, you must apply a filter format patch before use. See [PATCHES.md](../../PATCHES.md) for details.

```bash
python3 patch_s3vectors_filter.py
```

> ⚠️ Re-run the patch after every `pip upgrade mem0ai`.

## Quick Usage

```bash
# Add a long-term memory
python3 cli.py add --user me --agent dev --text "Important lesson learned..."

# Add a short-term memory (today's date)
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "Today's discussion about refactoring"

# Semantic search
python3 cli.py search --user me --agent dev --query "refactoring" --top-k 5

# Combined search (long-term + recent 7 days)
python3 cli.py search --user me --agent dev --query "refactoring" --combined
```

## Memory Tiering

| Type | run_id | Lifetime | Use Case |
|------|--------|----------|----------|
| **Long-term** | None | Permanent | Tech decisions, lessons, preferences |
| **Short-term** | `YYYY-MM-DD` | 7 days → archive | Daily discussions, temp decisions, task progress |

**Archival logic** (runs daily): after 7 days, short-term memories are semantically compared against recent activity. Active topics are upgraded to long-term; inactive ones are deleted.
