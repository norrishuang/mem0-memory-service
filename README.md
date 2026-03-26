# mem0 Memory Service for OpenClaw

[中文文档](./README.zh.md) | **English**

---

A unified memory layer based on [mem0](https://github.com/mem0ai/mem0), providing persistent semantic memory storage for [OpenClaw](https://github.com/openclaw/openclaw) Agents.

Agents can automatically store and retrieve memories through conversations, without manual file management.

## Features

- **Cross-Session Persistent Memory** — OpenClaw starts every conversation as an isolated session with no built-in memory. This service bridges sessions: every 5 minutes the session snapshot is captured to a diary file, an LLM periodically distills key facts into the vector store, and when a new session starts the Agent automatically retrieves relevant memories — so context is never lost between conversations.

- **Multi-Agent Isolated Memory** — Supports multiple Agents running in parallel (dev / blog / pjm / pm / prototype / researcher, etc.), each with a fully isolated memory space. Agents are auto-discovered by scanning workspaces — no manual registration required.

- **Short-Term + Long-Term Tiered Storage** — Conversations are first captured as diary files (short-term, archived daily), then an LLM automatically distills key facts into a mem0 vector store (long-term). The pipeline: live session → diary snapshot → LLM extraction → vector memory.

- **Cost-Optimized Vector Storage (S3 Vectors)** — Supports Amazon S3 Vectors as a vector backend, offering dramatically lower cost than self-managed OpenSearch clusters with pay-per-use pricing. OpenSearch is also supported for existing-cluster scenarios.

- **Fully Automated Operations** — systemd timers handle the entire lifecycle: session snapshots every 5 minutes, diary digest every 15 minutes, short-term memory archival daily. Zero manual intervention; services auto-recover on restart.

## Design Philosophy

### Why Add Lifecycle Management on Top of mem0?

mem0's core strength is **memory extraction and deduplication** — automatically extracting key facts from conversations, intelligently merging similar memories, and providing semantic retrieval. However, mem0 itself does not distinguish between "short-term events" and "long-term knowledge"; all written content is permanently stored by default.

This creates a problem: **temporary discussions, daily task progress, and tentative decisions**, if permanently retained, will accumulate over time and pollute the quality of long-term memory.

This service adds a **memory lifecycle management** layer on top of mem0, with the following division of responsibilities:

```
mem0 handles: Semantic extraction, intelligent deduplication, vector retrieval
This service handles: Tiered storage, lifecycle management, activity-based archiving
```

### Core Design of Short/Long-Term Tiering

**Short-term memory** is implemented using mem0's native `run_id` (daily isolation) mechanism, naturally isolated from long-term memory without requiring additional TTL fields.

**Archival decisions** leverage mem0's semantic search capability to determine whether to upgrade: after 7 days, the short-term memory content is used for semantic search in recent memories — if the topic is still active (has related discussions), it indicates sustained value and gets upgraded to long-term memory; otherwise it is deleted. This is smarter than simple time-based hard deletion and won't accidentally remove topics that are still ongoing.

This approach fully leverages mem0's semantic capabilities while solving the lifecycle management problem that mem0 doesn't natively address.

## Architecture

```
OpenClaw Agents (dev, main, ...)
        │
        │  HTTP API (localhost:8230)
        ▼
┌──────────────────────┐
│  Memory Service      │  FastAPI + mem0
│  (systemd managed)   │
│                      │  ┌─────────────────────────┐
│  Tiered Memory:      │  │ Long-term (no run_id)   │
│  - Long: tech        │  │ Short-term (run_id=date) │
│    decisions,        │  │ Archive: activity-based  │
│    lessons, prefs    │  │ upgrade/delete           │
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
- `run_id=YYYY-MM-DD` (Beijing time date)
- Auto-archived after 7 days: active topics upgraded to long-term, inactive ones deleted
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
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
        "arn:aws:bedrock:*::foundation-model/us.anthropic.claude-3-5-haiku-20241022-v1:0"
      ]
    }
  ]
}
```

> **Notes:**
> - Default Embedding model: `amazon.titan-embed-text-v2:0` (1024 dimensions)
> - Default LLM: Claude Haiku (claude-3-5-haiku-20241022) (configurable via `.env`)
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

## Usage

### CLI

```bash
# Add long-term memory (technical decisions, lessons learned, etc.)
python3 cli.py add --user me --agent dev --text "Important lesson learned..." \
  --metadata '{"category":"experience"}'

# Add short-term memory (daily discussions, temporary decisions)
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "Today Luke and Zoe discussed the memory system refactoring plan" \
  --metadata '{"category":"short_term"}'

# Conversation messages (mem0 automatically extracts key facts)
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# Semantic search (search long-term or short-term individually)
python3 cli.py search --user me --agent dev --query "keywords" --top-k 5

# Combined search (long-term + recent 7 days short-term, recommended)
python3 cli.py search --user me --agent dev --query "keywords" --combined --recent-days 7

# List all memories
python3 cli.py list --user me --agent dev

# List short-term memories for a specific date
python3 cli.py list --user me --agent dev --run 2026-03-23

# Get / Delete / View history
python3 cli.py get --id <memory_id>
python3 cli.py delete --id <memory_id>
python3 cli.py history --id <memory_id>
```

#### Short-Term Memory (run_id Based)

Short-term memory uses `run_id=YYYY-MM-DD` (Beijing time date) as identifier, auto-archived after 7 days:

```bash
# Add short-term memory (use today's date as run_id)
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "Temporary decisions discussed today..." \
  --metadata '{"category":"short_term"}'

# Search short-term memories for a specific date
python3 cli.py search --user me --agent dev --run 2026-03-23 --query "discussion"

# Combined search (long-term + recent 7 days short-term)
python3 cli.py search --user me --agent dev --query "keywords" \
  --combined --recent-days 7
```

**Auto-archival mechanism** (runs daily):
- Short-term memories older than 7 days are automatically processed
- Active topics (recent related discussions) → upgraded to long-term memory
- Inactive topics → deleted

**Use cases:**
- Daily discussion records
- Meeting notes
- Temporary decisions or hypotheses
- Task progress
```

### Automatic Short-Term Memory Extraction

The `auto_digest.py` script automatically extracts short-term events from diary files every 15 minutes and stores them in mem0 (`run_id=YYYY-MM-DD`).

#### How It Works

1. **Read diary files**: Reads today's diary (`YYYY-MM-DD.md`, Beijing time UTC+8) from `/home/ec2-user/.openclaw/workspace-{agent}/memory/`
2. **Incremental processing**: Tracks file read offsets via `.digest_state.json`, only processes new content
3. **LLM extraction**: Calls AWS Bedrock Claude 3.5 Haiku to extract key short-term events (discussions, task progress, temporary decisions, etc.)
4. **Write to mem0**: Each event is stored individually, `run_id=today's date`, metadata tags `category=short_term, source=auto_digest`

#### Configure Scheduled Task (systemd timer)

```bash
sudo cp mem0-digest.service mem0-digest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-digest.timer
```

#### Manual Run and Testing

```bash
# Run manually once
cd /home/ec2-user/workspace/mem0-memory-service
python3 auto_digest.py

# View logs
tail -f auto_digest.log

# Verify stored short-term memories
python3 cli.py search --user boss --agent dev --query "today" --top-k 10
python3 cli.py list --user boss --agent dev | grep short_term
```

#### File Descriptions

- **`auto_digest.py`**: Main script
- **`.digest_state.json`**: State file, tracks processed position for each diary file (git ignored)
- **`auto_digest.log`**: Runtime log, append mode (git ignored)

### Real-Time Session Snapshot

The `session_snapshot.py` script automatically saves conversations from the current active session to diary files every 5 minutes, solving the problem of recent conversation loss due to session compression.

#### How It Works

1. **Read session files**: Reads the current active session from OpenClaw's session store
2. **Extract messages**: Parses JSONL format, extracts user and AI conversation messages
3. **Deduplicated writing**: Checks for existing identical content to avoid duplicate writes
4. **Format organization**: Human messages labeled as Boss, AI messages labeled as Dev

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
DIARY_DIR = Path("/home/ec2-user/.openclaw/workspace-dev/memory/")  # Diary directory
MEM0_API_URL = "http://127.0.0.1:8230/memory/add"                   # mem0 API URL
BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"    # LLM model
```

### Automatic Short-Term Memory Archival

The `archive.py` script runs daily to process short-term memories older than 7 days, determining whether to upgrade or delete based on activity level.

#### How It Works

1. **Find short-term memories from 7 days ago**: Query all memories with `run_id=date from 7 days ago`
2. **Activity assessment**: For each memory, perform semantic search in recent 7 days of short-term memories
3. **Upgrade or delete**:
   - Active topics (similarity > 0.75) → upgraded to long-term memory (no run_id)
   - Inactive topics → deleted

#### Configure Scheduled Task (systemd timer)

```bash
# Install systemd timer (runs daily at UTC 02:00 / Beijing time 10:00)
sudo cp mem0-archive.service /etc/systemd/system/
sudo cp mem0-archive.timer /etc/systemd/system/

# Edit service file to verify paths are correct
sudo vim /etc/systemd/system/mem0-archive.service

# Enable and start timer
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-archive.timer

# Check timer status
sudo systemctl status mem0-archive.timer
sudo systemctl list-timers mem0-archive.timer

# Manually trigger archival once
sudo systemctl start mem0-archive.service

# View logs
tail -f archive.log
journalctl -u mem0-archive.service -f
```

#### Manual Run and Testing

```bash
# Run manually once
cd /home/ec2-user/workspace/mem0-memory-service
python3 archive.py

# View logs
tail -f archive.log
```

#### File Descriptions

- **`archive.py`**: Main archival script
- **`archive.log`**: Archival log, append mode (git ignored)
- **`mem0-archive.service`**: systemd service unit
- **`mem0-archive.timer`**: systemd timer unit

#### Custom Configuration

To modify configuration, edit the following variables in `archive.py`:

```python
ARCHIVE_DAYS = 7        # Process short-term memories older than this many days
ACTIVE_THRESHOLD = 0.75  # Activity threshold (semantic similarity)
```

### HTTP API

```bash
# Health check
curl http://127.0.0.1:8230/health

# Add long-term memory
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","text":"Important lesson learned..."}'

# Add short-term memory
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","run_id":"2026-03-23","text":"Today'\''s discussion..."}'

# Semantic search (individual search)
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":5}'

# Combined search (long-term + recent 7 days short-term)
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":10,"recent_days":7}'

# List memories
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev'

# List short-term memories for a specific date
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev&run_id=2026-03-23'
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
| `LLM_MODEL` | `us.anthropic.claude-3-5-haiku-...` | LLM model |
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
python3 migrate_to_s3vectors.py --user boss --agent dev

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
├── auto_digest.py          # Auto-extract short-term memories from diary (every 15 min)
├── session_snapshot.py     # Real-time session conversation saving (every 5 min)
├── archive.py              # Short-term memory auto-archival (daily)
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
