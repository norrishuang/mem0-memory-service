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

pip3 install -r requirements.txt

cp .env.example .env
vim .env  # Fill in your OpenSearch and AWS configuration

python3 test_connection.py   # Verify connectivity
python3 server.py            # Start the service
```

### Method 3: Let Your AI Agent Deploy

Tell your Agent:

> Deploy the mem0 memory service for me.
> The code repository is at https://github.com/norrishuang/mem0-memory-service
> OpenSearch address is xxx, username admin, password xxx.

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
