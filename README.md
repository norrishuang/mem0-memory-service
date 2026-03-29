# mem0 Memory Service for OpenClaw

[中文文档](./README.zh.md) | **English**

---

A unified memory layer based on [mem0](https://github.com/mem0ai/mem0), providing persistent semantic memory storage for [OpenClaw](https://github.com/openclaw/openclaw) Agents.

Agents can automatically store and retrieve memories through conversations, without manual file management.

## Features

- **Cross-Session Persistent Memory** — OpenClaw starts every conversation as an isolated session with no built-in memory. This service bridges sessions: every 5 minutes the session snapshot is captured to a diary file, an LLM distills the previous day's complete diary into the vector store each morning, and when a new session starts the Agent automatically retrieves relevant memories — so context is never lost between conversations.

- **Multi-Agent Isolated Memory** — Supports multiple Agents running in parallel (agent1 / agent2 / agent3, etc.), each with a fully isolated memory space. Agents are auto-discovered from `openclaw.json` — no manual registration required. Memories tagged as `experience` are automatically shared across all agents — building a collective knowledge base that benefits the whole team.

- **Short-Term + Long-Term Tiered Storage** — Conversations are captured as diary files and distilled into short-term memory every 15 minutes via `auto_digest --today`. Agent-curated `MEMORY.md` files are synced directly to long-term memory. Nightly `auto_dream` consolidates short-term into long-term via mem0's native inference. The pipeline: live session → diary snapshot → incremental digest → nightly dream → vector memory.

- **Cost-Optimized Operations** — Daily digest (once per day) vs. the previous incremental approach (every 15 minutes) reduces LLM calls by ~96% while improving memory quality. `MEMORY.md` sync uses hash-based dedup — zero LLM cost if content hasn't changed.

- **Cost-Optimized Vector Storage (S3 Vectors)** — Supports Amazon S3 Vectors as a vector backend, offering dramatically lower cost than self-managed OpenSearch clusters with pay-per-use pricing. OpenSearch is also supported for existing-cluster scenarios.

- **Fully Automated Operations** — systemd timers handle the entire lifecycle: session snapshots every 5 minutes, MEMORY.md sync at UTC 01:00, incremental digest every 15 minutes, nightly dream consolidation at UTC 02:00. Zero manual intervention; services auto-recover on restart.

## Design Philosophy

### Why Add Lifecycle Management on Top of mem0?

mem0's core strength is **memory extraction and deduplication** — automatically extracting key facts from conversations, intelligently merging similar memories, and providing semantic retrieval. However, mem0 itself does not distinguish between "short-term events" and "long-term knowledge"; all written content is permanently stored by default.

This creates a problem: **temporary discussions, daily task progress, and tentative decisions**, if permanently retained, will accumulate over time and pollute the quality of long-term memory.

This service adds a **memory lifecycle management** layer on top of mem0, with the following division of responsibilities:

```
mem0 handles: Semantic extraction, intelligent deduplication, vector retrieval
This service handles: Tiered storage, lifecycle management, nightly consolidation
```

### Core Design of Short/Long-Term Tiering

**Short-term memory** is implemented using mem0's native `run_id` (daily isolation) mechanism, naturally isolated from long-term memory without requiring additional TTL fields.

**Archival decisions** are handled by mem0 natively. Each 7-day-old short-term memory is re-added to mem0 with `infer=True` — mem0's LLM compares against existing long-term memories and decides ADD/UPDATE/DELETE/NONE. The original short-term entry is always deleted after processing.

This approach fully leverages mem0's semantic capabilities while solving the lifecycle management problem that mem0 doesn't natively address.

## Architecture

```
OpenClaw Agents (agent1, agent2, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (systemd managed)   │
│                      │  ┌─────────────────────────┐
│  Tiered Memory:      │  │ Long-term (no run_id)   │
│  - Long: tech        │  │ Short-term (run_id=date) │
│    decisions,        │  │ Archive: mem0 native     │
│    lessons, prefs    │  │ ADD/UPDATE/DELETE/NONE    │
│  - Short: daily      │  └─────────────────────────┘
│    discussions,      │
│    temp decisions    │
└──────────┬───────────┘
           │
     ┌─────▼─────┐       ┌──────────────────┐
     │   mem0    │──────▶│  LLM (Bedrock /   │  Memory extraction/
     │           │       │  OpenAI / ...)     │  dedup/merge
     │           │──────▶│  Embedder (Titan / │  Text vectorization
     └─────┬─────┘       │  OpenAI / ...)     │
           │             └──────────────────┘
           ▼
┌──────────────────────┐
│  OpenSearch           │  Vector store (k-NN)
│  (self-hosted / AWS)  │
│  ── or ──            │
│  Amazon S3 Vectors    │  Cost-optimized vectors
└──────────────────────┘
```

### Short/Long-Term Memory Tiering

**Long-term memory** (no run_id)
- Technical decisions, project status, lessons learned, user preferences
- Permanently stored
- Usage: omit the `run_id` parameter

**Short-term memory** (with run_id)
- Daily discussions, temporary decisions, task progress
- `run_id=YYYY-MM-DD`
- Auto-archived after 7 days: mem0 natively decides ADD/UPDATE/DELETE/NONE; original short-term entry always deleted regardless
- Usage: pass `run_id=<date>` parameter

**Retrieval strategies**
- Individual retrieval: long-term (no run_id) or specific date short-term (run_id=date)
- Combined retrieval: long-term + recent N days short-term (`--combined`), auto-merged and deduplicated

## Prerequisites

- **Python 3.9+**
- **OpenSearch** cluster (2.x or 3.x, k-NN plugin required)
- **AWS Bedrock** access (or modify config.py to use OpenAI or other LLM/Embedder)
- **OpenClaw** installed and running

### Amazon Bedrock Permissions

This service uses Amazon Bedrock to invoke LLM (for memory extraction) and Embedding model (for vectorization). The deployment server must have permissions to call Bedrock models.

- **EC2 deployment (recommended)**: Attach an IAM Role to the instance — no Access Key configuration needed
- **Other environments**: Use an IAM User with Access Key (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`)

**Minimum IAM policy:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeAccess",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:*::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0"
      ]
    }
  ]
}
```

> **Notes:**
> - Default Embedding model: `amazon.titan-embed-text-v2:0` (1024 dimensions)
> - Default LLM: Claude Haiku 4.5 (claude-haiku-4-5-20251001) (configurable via `.env`)
> - If you change model settings, update the Resource ARNs accordingly
> - If using cross-region inference profiles (`us.anthropic.claude-*`), include the corresponding profile ARN in Resource

## Quick Deployment

### Method 1: One-Click Install (Recommended)

```bash
git clone https://github.com/norrishuang/mem0-memory-service.git
cd mem0-memory-service
./install.sh
```

The install script will interactively guide you through OpenSearch connection details, AWS region, and other configurations, then automatically:
1. Install Python dependencies
2. Generate `.env` configuration file
3. Test OpenSearch and Bedrock connectivity
4. Create systemd service (auto-start on boot)
5. Install OpenClaw Skill

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

# 6. Install OpenClaw Skill
mkdir -p ~/.openclaw/skills/mem0-memory
cp skill/SKILL.md ~/.openclaw/skills/mem0-memory/SKILL.md
# Edit SKILL.md, replace $MEM0_HOME with the actual installation path
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
> **Step 6: Set up memory automation timers (run as current user)**
>
> All four timers run as the current user (not root):
> ```bash
> mkdir -p ~/.config/systemd/user/
> cp systemd/mem0-snapshot.service systemd/mem0-snapshot.timer ~/.config/systemd/user/
> cp systemd/mem0-memory-sync.service systemd/mem0-memory-sync.timer ~/.config/systemd/user/
> cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/
> systemctl --user daemon-reload
> systemctl --user enable --now mem0-snapshot.timer
> systemctl --user enable --now mem0-memory-sync.timer
> systemctl --user enable --now mem0-auto-digest.timer
> ```
> Timer schedule: snapshot every 5 min → digest every 15 min → memory-sync UTC 01:00 → auto-dream UTC 02:00
>
> **Step 7: Test write and search**
> ```bash
> python3 cli.py add --user me --agent agent1 --text "mem0 memory service deployed successfully" --metadata '{"category":"experience"}'
> python3 cli.py search --user me --agent agent1 --query "deploy"
> ```

## Usage

### CLI

```bash
# Add long-term memory (technical decisions, lessons learned, etc.)
python3 cli.py add --user me --agent agent1 --text "Important lesson learned..." \
  --metadata '{"category":"experience"}'

# Add short-term memory (daily discussions, temporary decisions)
python3 cli.py add --user me --agent agent1 --run 2026-03-23 \
  --text "Today Luke and Zoe discussed the memory system refactoring plan" \
  --metadata '{"category":"short_term"}'

# Conversation messages (mem0 automatically extracts key facts)
python3 cli.py add --user me --agent agent1 --run 2026-03-23 \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# Semantic search (search long-term or short-term individually)
python3 cli.py search --user me --agent agent1 --query "keywords" --top-k 5

# Combined search (long-term + recent 7 days short-term, recommended)
python3 cli.py search --user me --agent agent1 --query "keywords" --combined --recent-days 7

# List all memories
python3 cli.py list --user me --agent agent1

# List short-term memories for a specific date
python3 cli.py list --user me --agent agent1 --run 2026-03-23

# Get / Delete / View history
python3 cli.py get --id <memory_id>
python3 cli.py delete --id <memory_id>
python3 cli.py history --id <memory_id>
```

#### Short-Term Memory (run_id Based)

Short-term memory uses `run_id=YYYY-MM-DD` as identifier, auto-archived after 7 days:

```bash
# Add short-term memory (use today's date as run_id)
python3 cli.py add --user me --agent agent1 --run 2026-03-23 \
  --text "Temporary decisions discussed today..." \
  --metadata '{"category":"short_term"}'

# Search short-term memories for a specific date
python3 cli.py search --user me --agent agent1 --run 2026-03-23 --query "discussion"

# Combined search (long-term + recent 7 days short-term)
python3 cli.py search --user me --agent agent1 --query "keywords" \
  --combined --recent-days 7
```

**Auto-archival mechanism** (runs daily at UTC 02:00 via `auto_dream.py`):
- Short-term memories older than 7 days are automatically processed
- Each entry is re-added to mem0 with `infer=True` (no run_id) — mem0 decides ADD/UPDATE/DELETE/NONE
- Original short-term entry is always deleted after processing

**Use cases:**
- Daily discussion records
- Meeting notes
- Temporary decisions or hypotheses
- Task progress
```

### Automatic Short-Term Memory Extraction

The `auto_digest.py` script runs every 15 minutes with `--today` mode, extracting short-term events from today's diary and storing them in mem0 with `infer=True` (mem0 handles deduplication automatically).

#### How It Works

1. **Read today's diary**: Reads today's `YYYY-MM-DD.md` from each agent's workspace. Workspace paths are automatically resolved from `openclaw.json`.
2. **Write to mem0 with infer=True**: Each diary entry is stored via `mem0.add(infer=True)` with `run_id=today's date`. mem0's LLM automatically extracts key facts and handles deduplication.
3. **Metadata**: `category=short_term, source=auto_digest`

> No `.digest_state.json` state file needed. Uses `infer=True` so mem0 handles fact extraction and deduplication natively.

#### Configure Scheduled Task (systemd timer)

```bash
mkdir -p ~/.config/systemd/user/
cp systemd/mem0-auto-digest.service systemd/mem0-auto-digest.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now mem0-auto-digest.timer
```

#### Manual Run and Testing

```bash
# Run manually once
cd /home/ec2-user/workspace/mem0-memory-service
python3 auto_digest.py

# View logs
tail -f auto_digest.log

# Verify stored short-term memories
python3 cli.py search --user boss --agent agent1 --query "today" --top-k 10
python3 cli.py list --user boss --agent agent1 | grep short_term
```

#### File Descriptions

- **`auto_digest.py`**: Main script
- **`.digest_state.json`**: ~~State file, tracks processed position for each diary file~~ (removed — no longer used)
- **`auto_digest.log`**: Runtime log, append mode (git ignored)

### Real-Time Session Snapshot

The `session_snapshot.py` script automatically saves conversations from the current active session to diary files every 5 minutes, solving the problem of recent conversation loss due to session compression.

#### How It Works

1. **Read session files**: Reads the current active session from OpenClaw's session store. Agent workspace paths are resolved from `openclaw.json`, supporting non-standard workspace locations (e.g. `main` agent)
2. **Extract messages**: Parses JSONL format, extracts user and AI conversation messages
3. **Content-based deduplication**: Each message line is compared against the full diary file content — only lines not yet recorded are written. The same message is never written twice regardless of how many times the snapshot timer fires.
4. **Format organization**: Human messages labeled as Boss, AI messages labeled as the agent name

#### Configure Scheduled Task (systemd timer, recommended)

```bash
# Copy systemd units to user directory
mkdir -p ~/.config/systemd/user/
cp systemd/mem0-snapshot.service ~/.config/systemd/user/
cp systemd/mem0-snapshot.timer ~/.config/systemd/user/

# Enable timer
systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
```

#### Manual Run and Testing

```bash
python3 session_snapshot.py
```

#### Why Is This Needed?

Session snapshots serve two purposes:

- **Compaction safety**: When a session's context grows too large, OpenClaw compresses (compacts) the history into a summary. Fine-grained details before compaction may be lost. Saving every 5 minutes ensures at most 5 minutes of conversation is unrecorded before compaction.

- **Cross-session memory** (the bigger value): OpenClaw resets the active session daily (default 4:00 AM) or after an idle timeout, starting a fresh context window. Without snapshots, all conversation history would be gone. With snapshots → digest → mem0, when a new session starts the Agent automatically retrieves relevant memories via SKILL.md — so context is seamlessly restored across sessions.

#### File Descriptions

- **`session_snapshot.py`**: Main script
- **`systemd/mem0-snapshot.service`**: systemd service unit
- **`systemd/mem0-snapshot.timer`**: systemd timer unit (every 5 minutes)

### Custom Configuration

To modify configuration, edit the following variables in `auto_digest.py`:

```python
# Agent workspace paths are auto-resolved from openclaw.json — no manual path config needed.
# Override the OpenClaw data directory if it's not at the default ~/.openclaw:
# export OPENCLAW_HOME=/path/to/openclaw/data

MEM0_API_URL = "http://127.0.0.1:8230/memory/add"                   # mem0 API URL
BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"    # LLM model
```

### AutoDream — Nightly Memory Consolidation

The `auto_dream.py` script runs daily at UTC 02:00, consolidating short-term memories into long-term via mem0's native inference.

#### How It Works

1. **Step 1 — Diary → Long-term memory**: Reads yesterday's complete diary and calls `mem0.add(infer=True)` without `run_id` — mem0's LLM extracts key facts and stores them directly as long-term memory.
2. **Step 2 — Short-term cleanup**: For each 7-day-old short-term memory, calls `mem0.add(infer=True)` without `run_id` — mem0's LLM compares against existing long-term memories and decides ADD/UPDATE/DELETE/NONE. The original short-term entry is always deleted after processing, regardless of the decision.

#### Configure Scheduled Task (systemd timer)

```bash
# Install systemd timer (runs daily at UTC 02:00)
sudo cp mem0-dream.service /etc/systemd/system/
sudo cp mem0-dream.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mem0-dream.timer

# Check timer status
sudo systemctl status mem0-dream.timer
sudo systemctl list-timers mem0-dream.timer

# Manually trigger once
sudo systemctl start mem0-dream.service

# View logs
journalctl -u mem0-dream.service -f
```

#### Manual Run and Testing

```bash
cd /home/ec2-user/workspace/mem0-memory-service
python3 auto_dream.py

# View logs
tail -f auto_dream.log
```

#### File Descriptions

- **`auto_dream.py`**: Main script
- **`auto_dream.log`**: Runtime log, append mode (git ignored)

### HTTP API

```bash
# Health check
curl http://127.0.0.1:8230/health

# Add long-term memory
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"agent1","text":"Important lesson learned..."}'

# Add short-term memory
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"agent1","run_id":"2026-03-23","text":"Today'\''s discussion..."}'

# Semantic search (individual search)
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"agent1","top_k":5}'

# Combined search (long-term + recent 7 days short-term)
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"agent1","top_k":10,"recent_days":7}'

# List memories
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=agent1'

# List short-term memories for a specific date
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=agent1&run_id=2026-03-23'
```

### Automatic Agent Usage

After installing the Skill, OpenClaw Agent will automatically use the memory system in conversations:

- When you say **"Remember..."** → Agent automatically stores to mem0
- When you ask **"That project from before..."** → Agent automatically retrieves from mem0
- During **Heartbeat** → Agent automatically distills valuable conversation content

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/memory/add` | Add memory (`messages` or `text`, supports `run_id` field for short-term memory) |
| POST | `/memory/search` | Semantic search (supports `run_id` filtering) |
| POST | `/memory/search_combined` | Combined search (long-term + recent N days short-term) |
| GET | `/memory/list` | List memories (supports `user_id`, `agent_id`, `run_id` filtering) |
| GET | `/memory/{id}` | Get a single memory |
| PUT | `/memory/update` | Update memory |
| DELETE | `/memory/{id}` | Delete memory |
| GET | `/memory/history/{id}` | View memory change history |

## Data Isolation

Two-dimensional isolation using `user_id` + `agent_id`:

- **user_id**: User level — memories of different users are completely isolated
- **agent_id**: Agent level — different Agents of the same user manage memories independently
- Omitting `agent_id` allows cross-Agent retrieval of all memories

## Configuration

All configuration is managed through environment variables or `.env` file (`install.sh` auto-generates it):

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |
| `VECTOR_STORE` | `opensearch` | Vector engine: `opensearch` or `s3vectors` |
| `OPENSEARCH_HOST` | `localhost` | OpenSearch host |
| `OPENSEARCH_PORT` | `9200` | Port |
| `OPENSEARCH_USER` | `admin` | Username |
| `OPENSEARCH_PASSWORD` | - | Password |
| `OPENSEARCH_USE_SSL` | `false` | Whether to use SSL |
| `OPENSEARCH_COLLECTION` | `mem0_memories` | Index name |
| `S3VECTORS_BUCKET_NAME` | - | S3Vectors bucket name (required for `s3vectors` mode) |
| `S3VECTORS_INDEX_NAME` | `mem0` | S3Vectors index name |
| `EMBEDDING_MODEL` | `amazon.titan-embed-text-v2:0` | Embedding model |
| `EMBEDDING_DIMS` | `1024` | Vector dimensions |
| `LLM_MODEL` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | LLM model |
| `SERVICE_PORT` | `8230` | Service port |

### Vector Store Configuration

#### OpenSearch (Default)

OpenSearch is the default vector engine. Just ensure the OpenSearch variables in `.env` are correct:

```bash
VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
```

#### AWS S3 Vectors

[Amazon S3 Vectors](https://aws.amazon.com/s3/features/vectors/) is a cost-optimized vector storage service from AWS with S3-level elasticity and durability, supporting sub-second query performance.

**Configuration:**

```bash
export VECTOR_STORE=s3vectors
export S3VECTORS_BUCKET_NAME=your-bucket-name
export S3VECTORS_INDEX_NAME=mem0          # Optional, defaults to mem0
export AWS_REGION=us-east-1               # Optional, defaults to us-east-1
```

Or configure in `.env`:

```env
VECTOR_STORE=s3vectors
S3VECTORS_BUCKET_NAME=your-bucket-name
S3VECTORS_INDEX_NAME=mem0
AWS_REGION=us-east-1
```

**Required IAM Permissions (least privilege):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3vectors:CreateVectorBucket",
        "s3vectors:GetVectorBucket",
        "s3vectors:CreateIndex",
        "s3vectors:GetIndex",
        "s3vectors:DeleteIndex",
        "s3vectors:PutVectors",
        "s3vectors:GetVectors",
        "s3vectors:DeleteVectors",
        "s3vectors:QueryVectors",
        "s3vectors:ListVectors"
      ],
      "Resource": "*"
    }
  ]
}
```

> References: [S3 Vectors Security & Access](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-security-access.html) | [mem0 S3 Vectors Config](https://docs.mem0.ai/components/vectordbs/dbs/s3_vectors)

#### Migrating from OpenSearch to S3Vectors

If you are already using OpenSearch for memory storage, use `migrate_to_s3vectors.py` to migrate data to S3Vectors.

**Prerequisites:** Both OpenSearch and S3Vectors environment variables must be configured simultaneously (keep OpenSearch config in `.env` and also set `S3VECTORS_BUCKET_NAME`, etc.).

```bash
# Migrate all users' memories
python3 migrate_to_s3vectors.py

# Migrate a specific user only
python3 migrate_to_s3vectors.py --user boss

# Specific user and agent
python3 migrate_to_s3vectors.py --user boss --agent agent1

# Dry-run mode (preview only, no writes)
python3 migrate_to_s3vectors.py --dry-run
```

> ⚠️ **Safety note**: The migration does NOT delete source data in OpenSearch. Verify S3Vectors data integrity before manually cleaning up OpenSearch.

#### Known Issue: Filter Format Patch (Required)

mem0's upstream `s3_vectors.py` has a bug: the filter format passed to the S3Vectors API during `search()` is incorrect, causing `add()` operations to fail with `Invalid query filter` errors. A fix has been submitted as [PR #4554](https://github.com/mem0ai/mem0/pull/4554) but is pending merge.

**Before the PR is merged, you must manually apply the patch:**

```bash
python3 patch_s3vectors_filter.py
sudo systemctl restart mem0-memory.service
```

**Verify the patch is applied correctly:**

```bash
python3 -c "
from mem0.vector_stores.s3_vectors import S3Vectors
vs = S3Vectors.__new__(S3Vectors)
print(vs._convert_filters({'user_id': 'boss'}))
# Expected: {'user_id': {'\$eq': 'boss'}}
"
```

> ⚠️ This patch modifies the installed mem0 package directly. **You need to re-run the patch after every `pip upgrade mem0ai`.**

## Migrating Existing Memories

If you previously used `MEMORY.md` to manage memories, you can migrate to mem0 in one step:

```bash
# Edit MEMORY_FILE path, USER_ID, AGENT_ID in the script
vim migrate_memory_md.py

# Run migration
python3 migrate_memory_md.py
```

## File Structure

```
mem0-memory-service/
├── install.sh              # One-click install script
├── server.py               # FastAPI main service
├── config.py               # Configuration management (reads .env)
├── cli.py                  # Command-line client
├── skill/
│   └── SKILL.md            # OpenClaw Skill definition
├── migrate_memory_md.py    # MEMORY.md migration tool
├── test_connection.py      # Connectivity test
├── auto_digest.py          # Auto-extract short-term memories from diary (every 15 min, --today incremental mode only; daily full mode superseded by auto_dream Step 1)
├── session_snapshot.py     # Real-time session conversation saving (every 5 min)
├── auto_dream.py           # Nightly memory consolidation: diary→long-term + short-term cleanup (daily UTC 02:00)
├── systemd/
│   ├── mem0-snapshot.service   # systemd service
│   ├── mem0-snapshot.timer     # systemd timer (every 5 min)
│   └── ...                 # Other systemd units
├── mem0-memory.service     # systemd service template
├── requirements.txt        # Python dependencies
├── .env.example            # Configuration template
├── patch_s3vectors_filter.py # S3Vectors filter format patch script
├── PATCHES.md              # mem0 known issues and patch records
└── README.md
```

## mem0 Known Issues & Patches

When using AWS Bedrock + OpenSearch, mem0 has two known bugs. We have submitted PRs to fix them:

| Issue | PR | Status |
|-------|-----|--------|
| OpenSearch 3.x nmslib engine deprecated | [#4392](https://github.com/mem0ai/mem0/pull/4392) | Pending merge |
| Converse API temperature + top_p conflict (Claude Haiku 4.5) | [#4393](https://github.com/mem0ai/mem0/pull/4393) | ✅ Merged via [#4469](https://github.com/mem0ai/mem0/pull/4469) |
| S3Vectors `query_vectors` invalid filter format | [#4554](https://github.com/mem0ai/mem0/pull/4554) | Pending merge |

Manual patching is required before the PRs are merged. See [PATCHES.md](./PATCHES.md) for details.

## License

MIT
