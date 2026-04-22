# How It Works

This page explains the end-to-end memory flow — from a conversation happening to a memory being available in the next session.

## Design at a Glance

| Design Principle | What It Means | Key Mechanism |
|---|---|---|
| **Zero blind spots across session resets** | No conversation is lost when a session ends, even mid-day | Today's diary + yesterday's diary + mem0 combined cover every time window |
| **Two-tier memory: short-term → long-term** | Recent content stays isolated; only proven facts graduate to long-term | `auto_digest` writes with `run_id=today` (bounded dedup); `auto_dream` promotes at UTC 02:00 (global dedup) |
| **Dual capture paths** | Agent-driven entries are high quality; automation is the safety net | Agent writes diary in real-time; `session_snapshot` captures every 5 min as fallback |
| **Semantic retrieval, not keyword search** | Find memories by meaning, not exact phrasing | Vector similarity + time-decay blended ranking (`0.7 × score + 0.3 × recency`) |
| **Cross-agent knowledge sharing** | Lessons learned by one agent instantly benefit all agents | `category=experience` / `procedural` auto-writes to shared pool; every search includes shared pool |
| **Write generously, dedup automatically** | Agents don't need to worry about redundancy — mem0 handles it | `infer=True` triggers internal fact extraction; same-day dedup is bounded by `run_id` |
| **Targeted extraction per category** | Different memory types need different extraction angles | `custom_extraction_prompt` per `/memory/add` call; `auto_digest` uses `DIGEST_EXTRACTION_PROMPT` for technical context preservation + `TASK_EXTRACTION_PROMPT` for task extraction on every session block |
| **Three paths to long-term memory** | Different sources land in long-term at different speeds | Explicit CLI write (immediate) → `memory_sync` (same day) → `auto_dream` (7-day cadence) |
| **Multi-session, multi-agent continuity** | What happens in a group chat is visible to the direct chat session | `session_snapshot` covers all `agent:{id}:*` sessions; ~20 min propagation lag |

## The Core Problem: Sessions Are Stateless

OpenClaw resets the active session daily (default 4:00 AM local time) or after an idle timeout. Every new session starts with a blank context window — no memory of previous conversations.

This is by design: it keeps context fresh and avoids token bloat. But it means agents need an external mechanism to maintain continuity.

**mem0 Memory Service is that mechanism.**

## How Agents Know What to Do: The Skill System

OpenClaw has a built-in skill system. When a skill is enabled, its `SKILL.md` file is automatically injected into the agent's system prompt at session start.

The **mem0-memory** skill's `SKILL.md` contains a `🔴 Agent Memory Behavior` section with explicit behavior rules. When an agent reads these rules, it knows:

- When to write to the diary (`memory/YYYY-MM-DD.md`)
- When to update `MEMORY.md`
- How to search and write mem0 via CLI

**This is why no AGENTS.md changes are needed.** Enabling the skill once applies the behavior to every agent, on every session start, automatically.

```
Skills enabled in OpenClaw Settings
         │
         ▼
SKILL.md injected into system prompt at session start
         │
         ▼
Agent reads "🔴 Agent Memory Behavior" rules
         │
         ├─ During conversation → write diary entries
         └─ During heartbeat   → update MEMORY.md
```

## Agent Behavior Rules (What the Skill Instructs)

### During Conversations

When any of the following occurs, the agent proactively writes to `memory/YYYY-MM-DD.md`:

| Trigger | Example |
|---------|---------|
| Task completed | PR submitted, bug fixed, deployment done |
| Technical decision made | Why A was chosen over B |
| Lesson learned / pitfall discovered | Root cause of a failed build |
| User expressed a preference | "Always reply in Chinese" |
| Status changed | PR merged, service restarted |

Diary entry format:
```markdown
## 14:30

- Fixed session_snapshot dedup bug: changed block-level comparison to line-level content matching
- PR #7 submitted and merged
```

### During Heartbeats

On every heartbeat tick, the agent performs memory maintenance in order:

1. **Write diary** — append new session conversations to today's `memory/YYYY-MM-DD.md`
2. **Review recent files** — skim the last 2–3 days for insights worth keeping long-term
3. **Update MEMORY.md** — distill durable facts into `MEMORY.md`; prune outdated entries

`MEMORY.md` is the agent's curated knowledge base — project cards, active decisions, key configurations. It's maintained by the agent itself, not by automation scripts.

## The Full Memory Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        Conversation                          │
└────────────────┬──────────────────────┬─────────────────────┘
                 │                      │
                 ▼                      ▼
    Agent writes diary           Agent writes diary
    (SKILL.md guided,            (session_snapshot fallback,
     high quality)                every 5 min, auto-captured)
                 │                      │
                 └──────────┬───────────┘
                            ▼
                  memory/YYYY-MM-DD.md
                  (raw daily diary file)
                            │
              ┌─────────────┼──────────────┬──────────────┐
              │             │              │              │
              ▼             ▼              ▼              ▼
         Heartbeat      Every 15min    UTC 02:00      UTC 01:00
         (agent         auto_digest    auto_dream     memory_sync
          self-         --today        (Step1:        (sync
          distills)     (infer=True,   yesterday      MEMORY.md)
                        direct text)   diary +
                                       Step2: 7d STM)
              │             │              │              │
              ▼             ▼              ▼              ▼
         MEMORY.md     mem0 short-    mem0 long-     mem0 long-
         (updated)     term memory    term memory    term memory
                       (today,        (no run_id,    (no run_id)
                        ~20min lag)    next day)
                             │
                        UTC 02:00
                        AutoDream
                             │
                   ┌─────────┴──────────┐
                   ▼                    ▼
             Step 1: digest        Step 2: consolidate
             yesterday diary       7-day-old short-term
             → long-term           → re-add long-term
             (infer=True)          (infer=True) + delete
```

## Deployment: Docker vs. systemd

The memory pipeline scripts (`session_snapshot`, `auto_digest`, `auto_dream`, `memory_sync`) run identically regardless of deployment method. Only the process manager differs:

| | Docker (recommended) | systemd |
|---|---|---|
| **API server** | `mem0-api` container | systemd service |
| **Pipeline runner** | `mem0-pipeline` container (cron) | systemd user timers |
| **Diary file access** | via bind mount `~/.openclaw → /openclaw` | direct filesystem |
| **Patch management** | automatic at build time | manual `python3 tools/patch_s3vectors_filter.py` |
| **Restart on crash** | `restart: unless-stopped` | systemd `Restart=on-failure` |

For deployment details, see [Docker Setup](../deploy/docker) or [systemd Setup](../deploy/systemd).

## Daily Automation Timeline

| Time (UTC) | Script | What it does |
|-----------|--------|--------------|
| Every 5 min | `pipelines/session_snapshot.py` | Capture session conversations → diary file |
| Every 15 min | `pipelines/auto_digest.py --today` | Incremental: read new diary content → mem0 short-term (infer=True, fact extraction) + task-extraction pass (custom_extraction_prompt → category=task) |
| 01:00 | `pipelines/memory_sync.py` | Sync `MEMORY.md` → mem0 long-term (hash dedup) |
| 02:00 | `pipelines/auto_dream.py` | **AutoDream**: Step 1: yesterday diary → mem0 long-term (infer=True); Step 2: 7-day-old short-term → re-add to long-term (infer=True) then delete |

> In Docker deployments, these scripts run as cron jobs inside the `mem0-pipeline` container. In systemd deployments, they run as user timers. The schedule and behavior are identical regardless of deployment method.

## auto_digest Mode

`auto_digest.py` runs in one active mode:

**`--today` mode (every 15 min, incremental)**
Picks up new content from today's diary since the last run (offset-based). Writes to mem0 short-term memory with `infer=True` — mem0 runs internal fact extraction to produce concise memories. Skips batches smaller than 500 bytes to avoid noisy micro-writes. On failure, retains the offset so the next run resumes from the same point.

```
Every 15 min (--today):  diary new content → POST to mem0 (infer=True, fact extraction)
```

**Why short-term entries don't pollute long-term memory**

`auto_digest` writes with a `run_id = YYYY-MM-DD`. This is the key that controls mem0's dedup scope: when `infer=True` is used, mem0 searches for similar memories **only within the same `run_id`**. Since `auto_digest` uses `infer=True`, mem0 runs fact extraction at write time. Dedup scope is bounded by `run_id`, so today's entries only interfere with same-day memories, not existing long-term memories (which have no `run_id`).

This means:
- Writing every 15 minutes is safe — no risk of silently overwriting long-term knowledge
- Today's short-term memories accumulate and refine within their own namespace

**Promotion to long-term: one global dedup at auto_dream time**

The cross-`run_id` merge happens only during `auto_dream` (UTC 02:00). When 7-day-old short-term memories are re-added without `run_id`, mem0 searches the entire long-term store and decides ADD / UPDATE / DELETE / NONE. This is the one moment of global dedup — keeping long-term memory compact and non-redundant.

```
Every 15 min  → short-term  (run_id=today,   dedup within same day only)
UTC 02:00     → long-term   (no run_id,       global dedup across all history)
```

### Targeted Extraction Pass (category=task)

After each session block is written to short-term memory, `auto_digest` runs a second pass with a **task-focused `custom_extraction_prompt`**:

```
Session block
  ├─ Pass ①  infer=True (default prompt) → category=short_term   (general facts)
  └─ Pass ②  infer=True + custom_extraction_prompt → category=task  (completed work tasks)
```

Pass ② extracts only finalized work outcomes in `[type] description` format (e.g. `[开发] 实现了 X 功能，PR #129 已开`). This makes task recall precise: querying `"最近完成的任务"` returns clean task entries instead of scattered facts.

**Extending to other categories:** The same pattern applies to any category. Agents can pass a `custom_extraction_prompt` on any `/memory/add` call to extract decisions, config changes, or custom dimensions — without affecting the global mem0 prompt.

> **Note**: The previous default full mode (UTC 01:30, LLM-extract yesterday's diary → mem0 short-term) has been superseded by `auto_dream.py` Step 1, which writes directly to long-term memory (no run_id) with higher quality.

## Two Roles of session_snapshot

`session_snapshot.py` serves two purposes:

**Primary: Cross-Session Memory Bridge**
Agents reset daily. Without snapshot, conversations would be lost between sessions. Snapshot captures every conversation into diary files, which are then distilled into mem0 by `auto_digest.py`. When a new session starts, the agent retrieves relevant memories from mem0 — restoring context seamlessly.

**Secondary: Compaction Guard**
When a session's context window grows too large, OpenClaw compresses (compacts) the history. The most recent few minutes of conversation might not survive compaction. Snapshot running every 5 minutes ensures that content is captured to disk before compaction can lose it.

**Tertiary: Near-real-time cross-session memory sharing**
Each agent may have multiple concurrent sessions — a direct chat session and one or more group chat sessions. Without a sharing mechanism, what an agent says in a group chat is invisible to its direct chat session (and vice versa).

`session_snapshot.py` writes new conversation to the diary file every 5 minutes. `auto_digest.py --today` then picks up new diary content every 15 minutes and writes it to mem0 short-term memory with `infer=True` and `DIGEST_EXTRACTION_PROMPT` (run_id=today, technical context preservation). Any other session of the same agent can search mem0 and retrieve that content within ~20 minutes (5 min snapshot + 15 min digest) — no session restart required.

Session keys are tagged in metadata (`session_key`), so you can filter by source if needed.

## Two Paths for Writing Diary Files

Because not all agents actively maintain diary files, there are two parallel capture paths:

| Path | Who writes | Quality | When |
|------|------------|---------|------|
| **Agent-driven** | Agent itself (SKILL.md guided) | High — curated, meaningful entries | Real-time, during conversation |
| **Snapshot-driven** | `session_snapshot.py` (automated) | Lower — raw conversation fragments | Every 5 min, regardless of content |

Both paths write to the same `memory/YYYY-MM-DD.md` file. Content-level deduplication ensures no entry is written twice.

**The agent-driven path produces better memories.** Automation is the safety net.

> **Group chat sessions are now included.** Previously, snapshot only captured the `main` (direct chat) session. Now all sessions matching `agent:{id}:*` are processed — group chat conversations are written to the same diary file and mem0, enabling cross-context memory sharing within the same agent.

## Three Paths to Long-Term Memory

| Path | Source | Latency | When to use |
|------|--------|---------|-------------|
| **memory_sync.py** | `MEMORY.md` | Same day | Agent-curated knowledge, important decisions |
| **auto_digest + AutoDream** | Daily diary | 7 days | Recurring discussions, gradual context buildup |
| **Explicit CLI write** | Agent on-demand | Immediate | Time-sensitive facts, mid-conversation decisions |

```bash
# Explicit write to long-term memory (no --run = long-term)
python3 cli.py add \
  --user boss --agent <your-agent-id> \
  --text "Decided to use S3 Vectors as primary vector store" \
  --metadata '{"category":"decision"}'
```

## Cross-Agent Memory Sharing

One of the most powerful features of the memory service is **automatic cross-agent knowledge sharing** via the `shared` user space.

### How It Works

When any agent writes a memory with `category=experience` or `category=procedural`, the CLI automatically writes a copy to the shared knowledge pool (`user_id=shared`). No extra step is needed.

```bash
# This automatically goes to both the agent's personal space AND user_id=shared
python3 cli.py add \
  --user boss --agent dev \
  --text "kiro-cli: always use exec(pty=true, background=true, workdir=...). Never add & in command." \
  --metadata '{"category":"procedural"}'
```

### Automatic Shared Pool Inclusion on Search

Every search (`/memory/search` and `/memory/search_combined`) automatically includes results from `user_id=shared`, regardless of which agent is searching. This is done transparently in the server layer — callers don't need to make a separate request.

```
Agent A writes experience → personal space + shared pool
                                                  │
                                                  ▼
                                   Agent B searches for related topic
                                   → gets Agent A's experience automatically
                                   (result tagged memory_type="shared")
```

This means:
- If one agent discovers a bug fix or correct workflow, **all agents benefit immediately**
- No need to manually propagate knowledge between agents
- Shared results are tagged with `"memory_type": "shared"` so agents can distinguish them

### Memory Category Reference

| category | Purpose | Shared? | Example |
|----------|---------|---------|---------|
| `experience` | Pitfalls discovered, bug fixes, incident post-mortems | ✅ Auto-shared | "PR #94 fixed search not including shared pool — root cause was missing _search_shared()" |
| `procedural` | Step-by-step how-to guides, correct tool usage patterns | ✅ Auto-shared | "kiro-cli: exec(pty=true, background=true, workdir=...) — never add & in command" |
| `project` | Project status, progress | ❌ Agent-specific | "mem0-memory-service port 8230, systemd mem0-memory.service" |
| `decision` | Technical decisions and rationale | ❌ Agent-specific | "Chose pgvector over OpenSearch for local dev: lower cost, simpler setup" |
| `environment` | Service addresses, configs, paths | ❌ Agent-specific | "EC2 us-east-1, AWS Bedrock for LLM and embedding" |
| `preference` | User habits and communication preferences | ❌ Agent-specific | "Communicate in Chinese, concise and direct" |
| `short_term` | Today's discussions, temporary task notes | ❌ Agent-specific | "Today discussed issue #93 token optimization" |

> **`experience` vs `procedural`**: `experience` = "what happened + how it was resolved" (incident-driven, post-mortem style). `procedural` = "how to do X correctly" (reusable step-by-step guidance, how-to style). When in doubt: post-mortem → `experience`; how-to guide → `procedural`.

---

## Search Ranking

### Score Normalization

Different vector stores return scores with different semantics:

| Vector Store | Raw score meaning | Normalized |
|---|---|---|
| **OpenSearch** | Similarity (higher = more similar) | Pass-through |
| **pgvector** | Cosine distance (lower = more similar) | `1 - distance` |
| **S3 Vectors** | Cosine distance (lower = more similar) | `1 - distance` |

The service automatically normalizes all scores to a unified **similarity scale [0, 1]** (higher = more similar) before applying `min_score` filtering, time-decay blending, and returning results. This ensures consistent behavior regardless of which vector store backend is configured.

### Time-Decay Weighting

By default, search results are ranked by a blend of **vector similarity** and **time freshness**. This prevents older, potentially outdated memories from ranking above more recent, relevant ones.

### The Formula

```
final_score = 0.7 × vector_similarity + 0.3 × time_decay_weight

time_decay_weight = 0.5 ^ (age_days / 30)
# A 30-day-old memory gets ~0.5x time weight
# A 7-day-old memory gets ~0.85x time weight
# A 1-day-old memory gets ~0.98x time weight
```

### What Changes in the Response

When time-decay is applied, each result includes an `original_score` field (the raw vector similarity) alongside the final blended `score`:

```json
{
  "id": "...",
  "memory": "kiro-cli: never add & in command",
  "score": 0.87,
  "original_score": 0.83,
  "created_at": "2026-04-06T09:00:00Z"
}
```

### Disabling Time-Decay

Pass `time_decay: false` in the request body if you want pure vector similarity ranking (e.g., when searching historical records where recency doesn't matter):

```bash
curl -X POST http://localhost:8230/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query": "...", "user_id": "boss", "agent_id": "dev", "time_decay": false}'
```

---

## Session Start: Restoring Context

### Why today's AND yesterday's diary files are both needed

When a new session starts, the skill instructs the agent to read **both diary files** before querying mem0:

```
Session start
  ├── Read memory/today.md      ← today's raw diary (real-time, not yet in mem0)
  ├── Read memory/yesterday.md  ← yesterday's raw diary (coverage gap buffer)
  └── Search mem0 --combined    ← distilled memories (long-term + recent short-term)
```

**Why today's diary?**
`auto_dream.py` Step 1 runs at UTC 02:00, digesting *yesterday's* complete diary. Anything that happened today hasn't been digested yet — it only exists in `memory/today.md`. Reading this file is the only way to recover same-day context after a session reset.

**Why yesterday's diary?**
There is a coverage gap: the window between yesterday's late-night conversations and when `auto_dream` finishes running (UTC 02:00). For example:

```
Yesterday 23:50  Important discussion happens → written to memory/yesterday.md
Today     00:10  Session resets, new session starts
Today     02:00  auto_dream runs → yesterday's diary enters mem0 long-term
```

If the new session starts before 02:00, mem0 doesn't have last night's content yet. Reading `memory/yesterday.md` directly covers this gap.

**The complete coverage map:**

| Time window | Covered by |
|-------------|------------|
| Today (T+0) | `memory/today.md` (real-time) |
| Yesterday after-midnight to 02:00 | `memory/yesterday.md` (gap buffer) |
| Yesterday 02:00 onward | mem0 long-term (AutoDream Step1 digested) |
| Last 7 days | mem0 short-term (`--combined`) |
| Older than 7 days | mem0 long-term (AutoDream-consolidated) |

All three sources together — today's diary + yesterday's diary + mem0 — create **zero blind spots** across all session reset scenarios.

### mem0 retrieval

```bash
# Combined search: long-term + recent 7 days short-term
python3 cli.py search \
  --user boss --agent <your-agent-id> \
  --query "<topic from current conversation>" \
  --combined --recent-days 7
```

This gives the agent:
- Recent discussions (from short-term, last 7 days)
- Durable knowledge (from long-term: decisions, lessons, preferences)
- Shared team knowledge (from `category=experience` pool, all agents)

The result: the agent "remembers" relevant context without the user needing to re-explain anything.

## Finding Your Agent ID

All CLI commands use `--agent <your-agent-id>`. Your agent ID is the key under `agents.entries` in `openclaw.json`:

```bash
cat ~/.openclaw/openclaw.json | python3 -c "
import json, sys
config = json.load(sys.stdin)
entries = config.get('agents', {}).get('entries', {})
for agent_id, cfg in entries.items():
    ws = cfg.get('workspace', 'N/A')
    print(f'  {agent_id}: workspace={ws}')
"
```

Example output:
```
  main: workspace=/home/user/workspace-main
  dev:  workspace=/home/user/workspace-dev
  blog: workspace=/home/user/workspace-blog
```

Use the key (e.g. `dev`, `main`, `blog`) as your `--agent` value.

## AutoDream: The Sleeping Brain

> *"Every night, while the agent sleeps, its memories are quietly being sorted, promoted, and pruned — just like a human brain during REM sleep."*

The memory pipeline has two stages inspired by how human memory consolidation works:

- **Auto Digest (The Subconscious)** — runs every 15 minutes during the day, continuously absorbing new diary content into short-term memory via dedicated `DIGEST_EXTRACTION_PROMPT` (technical context preservation) + `TASK_EXTRACTION_PROMPT` (task extraction)
- **Auto Dream (Deep Sleep)** — runs once at night (UTC 02:00), reflecting on cross-day patterns, promoting 7-day-old short-term memories into long-term, and pruning redundancy

Neither stage requires human intervention. The agent wakes up the next morning with a richer, more organized memory.

For the full design, step-by-step pipeline breakdown, and a real end-to-end example, see **[AutoDream: The Sleeping Brain](./auto-dream)**.

---

## Memory Dashboard

For a visual interface to browse, search, and manage memories, see [Memory Dashboard](./memory-dashboard).
