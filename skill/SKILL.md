---
name: mem0-memory
description: |
  mem0 vector memory system. Access the local mem0 Memory Service via CLI for semantic memory storage, retrieval, and management.

  **Use this Skill when**:
  (1) Before answering any user question, search to retrieve relevant memories first
  (2) After completing a task or a substantive conversation round (automatic distillation)
  (3) User mentions "记住", "记一下", "remember", "recall"
  (4) Need to recall/retrieve previous information
  (5) Need to list, update, or delete existing memories
  (6) Automatic distillation during heartbeats
---

# mem0 Memory Skill

Provides persistent semantic memory for OpenClaw Agent. mem0 automatically extracts and deduplicates memories — feel free to write generously.

## CLI Path

```
/home/ec2-user/workspace/mem0-memory-service/cli.py
```

## 🔴 Division of Responsibilities with MEMORY.md

mem0 and workspace filesystem memory (MEMORY.md + memory/*.md) each have their strengths — **they don't replace each other**:

| | MEMORY.md + memory/*.md | mem0 |
|---|---|---|
| **What to store** | Structured project cards (name+URL+status+path) | Lessons learned, technical details, decision rationale, user preferences |
| **Retrieval method** | memory_search triggered automatically by the system | Requires actively calling CLI search |
| **Strengths** | Preserves structure and context, no information loss | Semantic retrieval, on-demand fetching, no loading token cost |
| **Weaknesses** | Larger files mean higher token costs | Auto-dedup may fragment structured information |

**Principles:**
- **Project cards** (GitHub URL, architecture overview, service ports, key paths) → Write to MEMORY.md
- **Lessons learned, pitfall records, technical details, preferences, decisions** → Write to mem0
- **Daily logs** → memory/YYYY-MM-DD.md

## 🔴 Core Rules: Proactive Retrieval + Proactive Writing

### Retrieval (Before Every Response)

**Don't wait for the user to ask "do you remember?" — proactively search before answering every question:**

**Prefer combined search (long-term + recent 7-day short-term):**

```bash
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "<keywords extracted from user question>" \
  --combined --recent-days 7
```

**Or search long-term memory only:**

```bash
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "<keywords extracted from user question>"
```

### Writing (After Every Task Completion)

**Don't wait for the user to say "remember this." Proactively call add to distill whenever a conversation contains the following:**

1. **Completed a task** (deployment, bug fix, PR submission, coding, etc.) → Record what was done, the result, and key decisions
2. **Discovered a lesson learned** (pitfall, workaround, compatibility issue) → Record the problem and solution
3. **Project status change** (PR merged/rejected, version release, environment change) → Record the new status
4. **User preferences or habits** (communication style, tech preferences, workflow) → Record preferences
5. **New configuration/environment info** (service addresses, passwords, path changes) → Record the information
6. **Important decisions and rationale** (why choose A over B) → Record the decision context

**Timing: After task completion, before replying to the user. No additional confirmation needed.**

### ⚠️ Writing Caution: Avoid Information Fragmentation

mem0's auto-dedup may split a single memory into multiple scattered facts. For **structured project information** (containing multiple key fields),
compose a single complete memory entry instead of splitting into multiple entries:

```bash
# ❌ Bad: Split entries — hard to reconstruct the full picture after dedup
python3 cli.py add --text "mem0-memory-service uses FastAPI"
python3 cli.py add --text "mem0-memory-service port 8230"
python3 cli.py add --text "mem0-memory-service GitHub URL is ..."

# ✅ Good: Compose a single complete memory
python3 cli.py add --text "mem0-memory-service: GitHub https://github.com/norrishuang/mem0-memory-service, architecture FastAPI+mem0→OpenSearch+Bedrock, port 8230, systemd mem0-memory.service"
```

**However, lessons learned and preferences can be written separately** (they are inherently independent fact fragments).

## Writing

When adding memory with `category=experience`, it is automatically shared to the global shared knowledge base (accessible by all agents and users).

```bash
# Long-term memory (lessons learned, technical decisions, user preferences, etc.)
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --text "specific key information" \
  --metadata '{"category":"experience","project":"xxx"}'

# Short-term memory (today's discussions, temporary decisions, task progress)
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --run 2026-03-23 \
  --text "temporary content discussed today..." \
  --metadata '{"category":"short_term","project":"xxx"}'

# Conversation messages (mem0 auto-extracts key facts, suitable for distilling entire conversations)
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
```

**Long-term vs Short-term Memory:**
- **Long-term memory** (without `--run`): Technical decisions, lessons learned, project status, user preferences
- **Short-term memory** (with `--run YYYY-MM-DD`): Today's discussions, temporary decisions, task progress
- After 7 days, short-term memories are auto-archived: active topics are promoted to long-term, inactive ones are deleted

### metadata category Reference

| category | Purpose | Example |
|----------|---------|---------|
| `experience` | Lessons learned, pitfall records | "Check official docs first for newer features, don't rely on assumptions" |
| `project` | Project status, progress | "opensearch-vector-search v1.3.0 has been released" |
| `decision` | Important decisions and rationale | "Chose cron-based scheduled distillation over pure heartbeat" |
| `environment` | Environment config, service info | "EC2 us-east-1, Bedrock model configuration" |
| `preference` | User preferences, habits | "Communicate in Chinese, concise and direct" |
| `short_term` | Short-term memory, isolated by run_id, archived after 7 days based on activity | "Today Luke and Zoe discussed issue X" |

### Short-term Memory (Based on run_id + Auto-archiving)

Short-term memories use `run_id=YYYY-MM-DD` (Beijing time date) as identifier, auto-archived after 7 days:

```bash
# Add short-term memory (use today's date as run_id)
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --run 2026-03-23 \
  --text "Today Luke and Zoe discussed the memory system refactoring plan" \
  --metadata '{"category":"short_term","project":"mem0"}'

# With metadata category
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --run 2026-03-23 \
  --text "Temporary discussion: considering postponing feature Y to next sprint" \
  --metadata '{"category":"short_term","project":"xxx"}'
```

**Auto-archiving mechanism** (runs daily):
- Short-term memories older than 7 days are automatically processed
- Active topics (recent related discussions) → Promoted to long-term memory
- Inactive topics → Deleted

**Use cases:**
- Same-day discussion records
- Meeting notes
- Temporary decisions or assumptions
- Task progress

**Notes:**
- When unsure if something is permanent, prefer short-term memory
- The system will automatically determine if it's worth keeping

## Retrieval

Shared knowledge (category=experience from all agents/users) is automatically included in every search result.

```bash
# Combined search (long-term + recent 7-day short-term, recommended)
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "natural language query" --combined --recent-days 7

# Search long-term memory only
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "natural language query" --top-k 5

# Search short-term memory for a specific date
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --run 2026-03-23 --query "keywords"

# Cross-agent search (omit --agent)
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --query "keywords" --combined --recent-days 7
```

## Scheduled Distillation

A cron job is configured (every 4 hours) to automatically extract valuable information from recent conversations and write to mem0.
Runs in silent mode without disturbing the user.

## Other Operations

```bash
# List all long-term memories
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py list --user boss --agent main

# List short-term memories for a specific date
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py list --user boss --agent main --run 2026-03-23

# Get a single memory
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py get --id <memory_id>

# Delete
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py delete --id <memory_id>

# Change history
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py history --id <memory_id>
```

## Data Isolation

- `--user boss` — Always use boss
- `--agent agent1` / `--agent agent2` — Isolated by agent
- Omit `--agent` for cross-agent retrieval

## Notes

- mem0 auto-deduplicates — semantically similar content won't be stored twice, so **write more rather than less**
- But structured project information should be **composed into a single entry** to avoid fragmentation (see caution above)
- Search is semantic-level, no exact matching required
- Write failures don't affect the main flow — silently skip
- Service management: `sudo systemctl status/restart mem0-memory`
