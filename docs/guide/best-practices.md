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

> ⚠️ **Note:** `MEMORY.md` is an **OpenClaw workspace configuration file**, located at `~/.openclaw/workspace-&lt;agent&gt;/MEMORY.md`. It is **not** part of mem0 Memory Service itself — it lives in your OpenClaw installation. You (or your agent) need to edit it directly in that path.

`MEMORY.md` should only contain stable "index skeleton" information — project names, GitHub URLs, service ports, key paths. Dynamic state (task progress, decisions, lessons learned) should live in mem0.

**Why this matters:** OpenClaw injects the full `MEMORY.md` into every session's context on startup. A bloated MEMORY.md means hundreds of wasted tokens per session, even when the current task has nothing to do with 90% of that content.

**Paste this prompt to your agent:**

```
Please review and slim down my MEMORY.md files.

They are located at: ~/.openclaw/workspace-&lt;agent&gt;/MEMORY.md
(There is one per agent — check all of them)

Goals:
1. Keep only stable, structural information:
   - Project name + GitHub URL + local workspace path
   - Service ports and systemd service names
   - Key team member IDs (open_id, etc.)
   - One-line project description
2. Remove anything that changes frequently:
   - Task progress, PR status, recent decisions
   - Daily notes, workflow convention details
   - Pitfall records, lessons learned
   - Pending to-do items (use GitHub Issues instead)
3. For removed content worth keeping long-term, write it to mem0:
   - Lessons/pitfalls → category=experience (shared across agents)
   - Project decisions → category=decision
   - Project status → category=project

Target: each MEMORY.md under 30 lines.

After slimming, report for each agent:
- Lines before → after
- What was moved to mem0 (category used)
- What was deleted entirely (why)
```

---

### 2. Add Experience Writing Rules to All Agent HEATBEATs

Each agent's `HEARTBEAT.md` should include explicit rules for when to write `category=experience` memories to the shared knowledge pool.

**Paste this prompt to your agent:**

````
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
  --user boss --agent &lt;your-agent-id&gt; \
  --text "&lt;context&gt;: &lt;conclusion/solution&gt;" \
  --metadata '{"category":"experience"}'
```
---

Report which files were updated and which already had this section.
````

---

### 3. Verify Memory Pipeline Health

Check that the automated pipelines (session snapshot → diary → digest → mem0) are running correctly.

**Paste this prompt to your agent:**

```
Please check the health of the mem0 memory pipeline:

1. Check systemd timer status: systemctl --user status mem0-digest.timer mem0-dream.timer (or equivalent)
2. Check if today's diary file exists at memory/YYYY-MM-DD.md
3. Check the last run time of auto_digest: look at auto_digest.log or auto_digest_offset.json
4. Search mem0 for recent memories: python3 cli.py search --user boss --agent &lt;your-agent&gt; --query "recent work" --combined --recent-days 3
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

1. List all long-term memories: python3 cli.py list --user boss --agent &lt;your-agent&gt;
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
  --user boss --agent &lt;your-agent-id&gt; \
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
| Discovered the correct way to use a tool/workflow | `procedural` (shared) | `--metadata '{"category":"procedural"}'` |
| Project status changed | `project` (agent-specific) | `--metadata '{"category":"project"}'` |
| Config/env info discovered | `environment` | `--metadata '{"category":"environment"}'` |
| Today's discussion notes | `short_term` | `--run YYYY-MM-DD --metadata '{"category":"short_term"}'` |
| User preference observed | `preference` | `--metadata '{"category":"preference"}'` |
| Completed work tasks (auto_digest) | `task` | `--metadata '{"category":"task"}' --custom-prompt "..."` |

> **`experience` vs `procedural`**: `experience` = "what happened + how it was resolved" (incident-driven). `procedural` = "how to do X correctly" (reusable step-by-step guidance). When in doubt: if it reads like a post-mortem → `experience`; if it reads like a how-to guide → `procedural`.

## Targeted Memory Extraction with `custom_extraction_prompt`

By default, `auto_digest` and direct `add` calls use mem0's generic fact-extraction prompt, which may produce mixed results (preferences, configs, code snippets). Use `custom_extraction_prompt` to extract along a specific dimension.

### When to use

| Goal | Prompt hint |
|------|------------|
| Work task summary | `"列出agent实际完成的工作任务（最终成果），格式：[类型] 描述..."` |
| Technical decisions | `"提取重要技术决策及原因，格式：[决策] 原因..."` |
| Config/env discovery | `"提取新增的服务配置、端口、路径等环境信息..."` |
| Default | Omit — mem0 uses generic extraction |

### How it works

```
POST /memory/add
  text: <session block>
  infer: true
  metadata: {category: "task"}
  custom_extraction_prompt: "..."   ← overrides default prompt for this call only
```

The `custom_extraction_prompt` is passed directly to mem0's `Memory.add(prompt=...)` — it is scoped to the single call and does not change global config.

### auto_digest integration

`auto_digest.py` automatically runs targeted task extraction on every session block:
1. **Pass ①** — generic `infer=True` → `category=short_term`
2. **Pass ②** — `custom_extraction_prompt` (task-focused) → `category=task`

This makes work task recall much more precise: query `"最近完成的任务"` returns clean `[类型] 描述` entries instead of scattered facts.
