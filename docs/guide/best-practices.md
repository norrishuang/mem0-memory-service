# Best Practices: Maximizing Memory Quality with Agent Assistance

After deploying mem0 Memory Service, the real value comes from **tuning your agents** to actively use the memory system. This guide provides ready-to-use prompts you can paste directly to your OpenClaw agent.

## Core Principle: Static vs Dynamic Separation

OpenClaw loads all Project Context files (MEMORY.md, SOUL.md, AGENTS.md, etc.) into every session's context. This is the biggest source of token waste:

```
Before optimization:
  MEMORY.md (full, 80+ lines) → loaded every session regardless of task
  = 90% of content irrelevant to current task

After optimization:
  MEMORY.md (skeleton, ~25 lines) → stable index only
  mem0 (dynamic memories) → recalled on-demand by relevance
  = Only relevant context loaded per task
```

**Rule of thumb for MEMORY.md:**

| Keep in MEMORY.md | Move to mem0 |
|---|---|
| Project name + GitHub URL + local path | PR status, recent progress |
| Service ports, systemd names | Technical decisions and rationale |
| Key team member IDs | Pitfalls, lessons learned |
| One-line project description | Workflow conventions and rules |
| | Pending tasks (use GitHub Issues instead) |

**Target: MEMORY.md under 30 lines per agent. Token savings: 60–80% on MEMORY.md alone.**

---

## One-Time Setup (Run After Deployment)

### 1. Slim Down MEMORY.md

`MEMORY.md` should only contain stable "index skeleton" information — project names, GitHub URLs, service ports, key paths. Dynamic state (task progress, decisions, lessons learned) should live in mem0.

**Paste this prompt to your agent:**

```
Please review my MEMORY.md file and help me slim it down.

Goals:
1. Keep only stable, structural information: project names, GitHub URLs, service ports, key paths, team member roles
2. Remove anything that changes frequently: task progress, PR status, recent decisions, daily notes
3. For any removed content that's worth keeping long-term, write it to mem0 as category=experience or category=project

After slimming MEMORY.md, tell me:
- How many lines were removed
- What categories of content were moved to mem0
- What was deleted entirely (and why)
```

---

### 2. Add Experience Writing Rules to All Agent HEATBEATs

Each agent's `HEARTBEAT.md` should include explicit rules for when to write `category=experience` memories to the shared knowledge pool.

**Paste this prompt to your agent:**

```
Please check all HEARTBEAT.md files across my OpenClaw workspaces (usually at ~/.openclaw/workspace-*/HEARTBEAT.md).

For any HEARTBEAT.md that does NOT already have an "experience memory writing" section, add the following section:

---
## Experience Memory Writing (Every heartbeat + before session ends)

Review recent work. When any of the following apply, MUST write category=experience:

- Fixed a bug or discovered a pitfall (record: symptom, root cause, solution)
- Made a technical decision (record: why A over B)
- Found a better way to use a tool or workflow
- Reached an important conclusion after extended discussion

Not needed for: routine task completions, one-off operations, info already in MEMORY.md stable skeleton.

```bash
python3 /path/to/mem0-memory-service/cli.py add \
  --user boss --agent <your-agent-id> \
  --text "<context>: <conclusion/solution>" \
  --metadata '{"category":"experience"}'
```
---

Report which files were updated and which already had this section.
```

---

### 3. Verify Memory Pipeline Health

Check that the automated pipelines (session snapshot → diary → digest → mem0) are running correctly.

**Paste this prompt to your agent:**

```
Please check the health of the mem0 memory pipeline:

1. Check systemd timer status: systemctl --user status mem0-snapshot.timer mem0-digest.timer mem0-dream.timer (or equivalent)
2. Check if today's diary file exists at memory/YYYY-MM-DD.md
3. Check the last run time of auto_digest: look at auto_digest.log or auto_digest_offset.json
4. Search mem0 for recent memories: python3 cli.py search --user boss --agent <your-agent> --query "recent work" --combined --recent-days 3
5. Check if the shared pool has any entries: python3 cli.py search --user shared --query "experience"

Report any gaps or issues found.
```

---

## Ongoing Optimization (Run Periodically)

### 4. Audit Shared Knowledge Pool Health

The shared pool (`user_id=shared`, `category=experience`) is the cross-agent knowledge base. It should grow over time as agents record lessons learned.

**Paste this prompt to your agent (weekly):**

```
Please audit the shared memory pool health:

1. Count total memories in shared pool: python3 cli.py list --user shared
2. Check which agents have written to the shared pool (look at agent_id in results)
3. Search for recent experience entries: python3 cli.py search --user shared --query "experience lesson pitfall" --combined --recent-days 7
4. Identify any agents that have NOT written any experience memories recently

If any agents are missing from the shared pool, check their HEARTBEAT.md for the experience writing rules and add them if missing.

Report: total shared memories, agent coverage, any gaps.
```

---

### 5. Memory Quality Review

Low-quality memories are a token burden, not an asset. Periodically review and clean up.

**Paste this prompt to your agent (monthly):**

```
Please review memory quality in mem0:

1. List all long-term memories: python3 cli.py list --user boss --agent <your-agent>
2. Identify entries that are:
   - Too vague (e.g., "discussed project X" with no actionable detail)
   - Outdated (refer to resolved issues, superseded decisions)
   - Duplicated (same fact stored multiple times with slight variations)
3. For outdated/duplicate entries, delete them: python3 cli.py delete --id <memory_id>
4. For vague entries, consider rewriting them with more specific context

Report: total reviewed, deleted, rewritten.
```

---

### 6. Diagnose Memory Gaps (Missing Diary Dates)

If the pipeline was interrupted (service restart, path misconfiguration), some dates may be missing from the diary, meaning those conversations were never distilled into mem0.

**Paste this prompt to your agent:**

```
Please check for gaps in the memory diary:

1. List all diary files: ls memory/*.md | sort
2. Check for missing dates in the past 30 days
3. For any missing dates, check if there were active OpenClaw sessions that day using: openclaw sessions list (or check session logs)
4. If there are important gaps, consider whether to backfill using session history

Report: date range covered, missing dates, estimated impact.
```

---

## Token Optimization Tips

### Principle: Dynamic Recall Over Static Injection

The biggest token saving comes from replacing static Project Context files with on-demand memory retrieval.

| Static (expensive) | Dynamic (efficient) |
|---|---|
| Full MEMORY.md loaded every session | Slim MEMORY.md skeleton + mem0 recall at session start |
| All project details always present | Only relevant project details recalled per task |
| History accumulates in context | Distilled memories replace raw history |

**Paste this prompt to establish dynamic recall habits:**

```
At the start of each new session, before answering the user's first message, do a targeted mem0 search based on what they're asking about. Use:

python3 /path/to/mem0-memory-service/cli.py search \
  --user boss --agent <your-agent-id> \
  --query "<2-3 keywords from user's message>" \
  --combined --recent-days 7 --min-score 0.3

Only inject results with score >= 0.3. Skip the search entirely if the user's request is purely conceptual (no project/history context needed).
```

---

## Quick Reference: When to Write What

| Situation | Memory type | Command |
|-----------|-------------|---------|
| Bug fixed, pitfall found | `experience` (shared) | `--metadata '{"category":"experience"}'` |
| Technical decision made | `experience` (shared) | `--metadata '{"category":"experience"}'` |
| Project status changed | `project` (agent-specific) | `--metadata '{"category":"project"}'` |
| Config/env info discovered | `environment` | `--metadata '{"category":"environment"}'` |
| Today's discussion notes | `short_term` | `--run YYYY-MM-DD --metadata '{"category":"short_term"}'` |
| User preference observed | `preference` | `--metadata '{"category":"preference"}'` |
