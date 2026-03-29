# How It Works

This page explains the end-to-end memory flow — from a conversation happening to a memory being available in the next session.

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
         Heartbeat      Every 15min    UTC 01:30      UTC 01:00
         (agent         auto_digest    auto_digest    memory_sync
          self-         --today        (full mode,    (sync
          distills)     (incremental,  LLM extract    MEMORY.md)
                        direct write)  yesterday)
              │             │              │              │
              ▼             ▼              ▼              ▼
         MEMORY.md     mem0 short-    mem0 short-    mem0 long-
         (updated)     term memory    term memory    term memory
                       (today,        (yesterday,    (no run_id)
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

## Daily Automation Timeline

All automation runs as systemd user timers:

| Time (UTC) | Script | What it does |
|-----------|--------|--------------|
| Every 5 min | `pipelines/session_snapshot.py` | Capture session conversations → diary file |
| Every 15 min | `pipelines/auto_digest.py --today` | Incremental: read new diary content → mem0 short-term (infer=True, mem0 handles dedup) |
| 01:00 | `pipelines/memory_sync.py` | Sync `MEMORY.md` → mem0 long-term (hash dedup) |
| 01:30 | `pipelines/auto_digest.py` | Full mode: LLM-extract yesterday's complete diary → mem0 short-term |
| 02:00 | `pipelines/auto_dream.py` | **AutoDream**: Step 1: yesterday diary → mem0 long-term (infer=True); Step 2: 7-day-old short-term → re-add to long-term (infer=True) then delete |

## Two Modes of auto_digest

`auto_digest.py` runs in two different modes:

**`--today` mode (every 15 min, incremental)**
Picks up new content from today's diary since the last run (offset-based). Writes to mem0 short-term memory with `infer=True` — mem0 handles fact extraction and deduplication automatically. Skips batches smaller than 500 bytes to avoid noisy micro-writes. On failure, retains the offset so the next run resumes from the same point.

**Default mode (UTC 01:30, full)**
Reads yesterday's complete diary, calls a local Bedrock LLM (Claude Haiku) to extract meaningful short-term events, and writes each event individually to mem0. Higher quality output than incremental mode; acts as a cleanup pass to catch anything the 15-min incremental runs may have missed.

```
Every 15 min (--today):  diary new content → POST to mem0 (infer=True, mem0 dedup)
UTC 01:30 (default):     yesterday's full diary → LLM extract → mem0
```

## Two Roles of session_snapshot

`session_snapshot.py` serves two purposes:

**Primary: Cross-Session Memory Bridge**
Agents reset daily. Without snapshot, conversations would be lost between sessions. Snapshot captures every conversation into diary files, which are then distilled into mem0 by `auto_digest.py`. When a new session starts, the agent retrieves relevant memories from mem0 — restoring context seamlessly.

**Secondary: Compaction Guard**
When a session's context window grows too large, OpenClaw compresses (compacts) the history. The most recent few minutes of conversation might not survive compaction. Snapshot running every 5 minutes ensures that content is captured to disk before compaction can lose it.

**Tertiary: Near-real-time cross-session memory sharing**
Each agent may have multiple concurrent sessions — a direct chat session and one or more group chat sessions. Without a sharing mechanism, what an agent says in a group chat is invisible to its direct chat session (and vice versa).

`session_snapshot.py` writes new conversation to the diary file every 5 minutes. `auto_digest.py --today` then picks up new diary content every 15 minutes and writes it to mem0 short-term memory with `infer=True` (run_id=today, mem0 handles dedup). Any other session of the same agent can search mem0 and retrieve that content within ~20 minutes (5 min snapshot + 15 min digest) — no session restart required.

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

## Session Start: Restoring Context

### Why today's AND yesterday's diary files are both needed

When a new session starts, the skill instructs the agent to read **both diary files** before querying mem0:

```
Session start
  ├── Read memory/today.md      ← today's raw diary (real-time, not yet in mem0)
  ├── Read memory/yesterday.md  ← yesterday's raw diary (coverage gap buffer)
  └── Search mem0 --combined    ← distilled memories (T+1 after 01:30 digest)
```

**Why today's diary?**
`auto_digest.py` runs at UTC 01:30, processing *yesterday's* complete diary. Anything that happened today hasn't been digested yet — it only exists in `memory/today.md`. Reading this file is the only way to recover same-day context after a session reset.

**Why yesterday's diary?**
There is a coverage gap: the window between yesterday's late-night conversations and when `auto_digest` finishes running (UTC 01:30). For example:

```
Yesterday 23:50  Important discussion happens → written to memory/yesterday.md
Today     00:10  Session resets, new session starts
Today     01:30  auto_digest runs → yesterday's diary enters mem0
```

If the new session starts before 01:30, mem0 doesn't have last night's content yet. Reading `memory/yesterday.md` directly covers this gap.

**The complete coverage map:**

| Time window | Covered by |
|-------------|------------|
| Today (T+0) | `memory/today.md` (real-time) |
| Yesterday after-midnight to 01:30 | `memory/yesterday.md` (gap buffer) |
| Yesterday 01:30 onward | mem0 short-term (distilled) |
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
