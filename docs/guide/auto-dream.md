# AutoDream: The Sleeping Brain

> *"Every night, while the agent sleeps, its memories are quietly being sorted, promoted, and pruned — just like a human brain during REM sleep."*

## The Concept

Human memory consolidation happens in two stages: the **subconscious** processes and encodes experiences continuously throughout the day, while **deep sleep** reorganizes and promotes what matters into long-term storage.

The AutoDream pipeline mirrors this design exactly:

- **Auto Digest = Subconscious Processing** — runs continuously during the day, quietly absorbing each conversation as it happens
- **Auto Dream = Deep Sleep** — runs once at night (UTC 02:00), doing the heavy cognitive work: reflecting on patterns across the week, promoting aged short-term memories, and pruning redundancy from long-term storage

Neither stage requires human intervention. The agent wakes up the next morning with a richer, more organized memory.

---

## Stage 1: Auto Digest (The Subconscious)

`auto_digest.py --today` runs every **15 minutes** throughout the day. It reads new content from the agent's diary (`memory/YYYY-MM-DD.md`) since the last run and passes it to mem0 for fact extraction.

**What it does:**

For each new diary block, `auto_digest` runs **two extraction passes in parallel**:

| Pass | Prompt | Output | Purpose |
|------|--------|--------|---------|
| **Pass ①** | Default mem0 prompt | `category=short_term` | General facts, context, project state |
| **Pass ②** | Task-focused `custom_extraction_prompt` | `category=task` | Only finalized work outcomes, in `[type] description` format |

Pass ② exists because general-purpose fact extraction tends to produce noisy, mixed-level entries. A dedicated task pass extracts clean, actionable records like:

```
[开发] 完成 Step 3 候选对处理，找到12个候选对（dev agent）
[分析] 分析 auto_dream_reflect 写入数为0的原因（记忆重复问题）
[配置] 将当前会话关键记忆写入 memory/2026-04-17.md 日记文件
```

These entries are tagged `category=task` and can be retrieved with precise recall queries like *"最近完成的任务"* — without sifting through scattered facts.

**Key design: bounded dedup via `run_id`**

Every entry written by `auto_digest` carries `run_id = YYYY-MM-DD` (today's date). When mem0 processes an `infer=True` write, it deduplicates only within the same `run_id` scope. This means:

- Writing every 15 minutes is safe — same-day entries merge with each other but never silently overwrite long-term memories
- Today's short-term entries accumulate in their own isolated namespace, staying out of long-term storage until Auto Dream decides what to keep

```
Every 15 min:
  diary new content
    ├─ Pass ①  → mem0 short-term  (run_id=today, category=short_term)
    └─ Pass ②  → mem0 short-term  (run_id=today, category=task)
```

---

## Stage 2: Auto Dream (Deep Sleep)

`auto_dream.py` runs once per night at **UTC 02:00**, performing three sequential steps.

### Step 1: Cross-Day Reflection

Auto Dream reads the **past 7 days of diary files** for each agent, concatenates them into a single text corpus, and submits it to mem0 with a specialized `REFLECTION_PROMPT`.

This prompt is fundamentally different from Auto Digest's general-purpose extraction. It instructs the LLM to **ignore single-event entries** and focus exclusively on patterns that recur across multiple days:

> *"是同类错误在多天中出现 2 次以上？Agent 自身失误模式？被 Boss 纠正的行为规律？反复出现的绕路模式？"*

The four reflection dimensions it looks for:

| Dimension | What It Captures |
|---|---|
| **Recurring errors** | Same class of mistake appearing 2+ times across different days |
| **Agent failure patterns** | Wrong judgment calls, skipped confirmation steps, self-directed actions that caused rework |
| **Behavior corrected by the user** | Things the user explicitly pushed back on or corrected, repeatedly |
| **Detour patterns** | Task types that consistently took longer due to a wrong starting approach |

The output — cross-day, recurring insights — is written **directly to long-term memory** (no `run_id`). This is deliberate: single-occurrence facts stay short-term; only patterns that survive multiple days earn long-term status through reflection.

```
7-day diary corpus
    │
    ▼  REFLECTION_PROMPT (cross-day patterns only)
    ▼  mem0 infer=True
    │
    ▼  long-term memory (no run_id)
       metadata: source=auto_dream_reflect, reflect_range=YYYY-MM-DD~YYYY-MM-DD
```

### Step 2: Short-Term → Long-Term Promotion

Auto Dream targets short-term memories that are exactly **7 days old** (by `run_id`). For each such memory, it:

1. Re-submits the memory text to mem0 with `infer=True` and **no `run_id`**
2. mem0 searches the entire long-term store and decides: `ADD`, `UPDATE`, `DELETE`, or `NONE`
3. The original short-term entry is deleted regardless of the decision

This is the **one moment of global dedup** across the entire memory history. Removing the `run_id` lifts the dedup scope from "same day" to "all time" — mem0 can now detect if this memory is already captured in long-term and choose to merge, update, or drop it accordingly.

```
7-day-old short-term memory
    │
    ▼  re-add to mem0 (infer=True, no run_id)
    ▼  mem0 global dedup: ADD / UPDATE / DELETE / NONE
    │
    ├─ ADD     → new long-term entry created
    ├─ UPDATE  → existing long-term entry updated
    ├─ DELETE  → contradicts existing knowledge, discarded
    └─ NONE    → already captured, silently dropped
    (original short-term entry deleted in all cases)
```

**Why 7 days?**

Seven days is enough time for a short-term memory to be "seen" by reflection (Step 1 looks at the past 7 days of diaries). By the time Step 2 runs on a given `run_id`, Step 1 has already had multiple opportunities to extract any cross-day patterns from that period. What reaches Step 2 is the raw short-term layer — individual facts that didn't get absorbed into a pattern — and those are the ones that need one final decision: keep, merge, or drop.

### Step 3: Long-Term Memory Consolidation

Even after clean promotion, long-term memories can accumulate semantic redundancy over time as more entries are added across weeks and months. Step 3 runs a periodic cleanup pass.

**How it works:**

1. Loads all long-term memories for the agent
2. Picks the current batch using a rotating offset (50 entries per run)
3. For each entry in the batch, runs a vector similarity search against all long-term memories
4. If a near-duplicate pair is found (score > 0.85), submits both texts together to mem0 with `infer=True`
5. If mem0 produces an `ADD` or `UPDATE` event → both originals are deleted, leaving the merged entry
6. If mem0 returns `NONE` → the pair is not actually redundant; left unchanged
7. Saves the updated offset for the next run

The rotation mechanism ensures all long-term memories are reviewed over time without making any single run unboundedly long.

```
Long-term memory store
    │
    ▼  Rotating batch scan (offset=N, batch=50)
    ▼  Vector similarity search per entry
    │
    For each near-duplicate pair (score > 0.85):
    ├─ Submit merged text → mem0 infer=True
    ├─ ADD/UPDATE → delete both originals, keep merged
    └─ NONE → leave unchanged (not actually redundant)
```

---

## Why This Design

| Design Goal | How AutoDream Achieves It |
|---|---|
| **Daytime writes are low-risk** | `auto_digest` uses `run_id` scoping — never touches long-term storage |
| **Long-term memory stays compact** | Global dedup only at Auto Dream time, not on every write |
| **Patterns outlast individual events** | `REFLECTION_PROMPT` explicitly filters out single-occurrence facts |
| **No human curation required** | mem0's own LLM decides ADD/UPDATE/DELETE/NONE — agents don't write dedup logic |
| **Memory never grows unboundedly** | Step 2 deletes originals after promotion; Step 3 consolidates redundant pairs |
| **Different extraction granularity per stage** | Subconscious (Auto Digest) = fast + broad; Deep sleep (Auto Dream) = slow + selective |

The net result: **the agent accumulates knowledge like a person would** — daily experiences flow in continuously, recurring patterns crystallize into long-term memory over time, and redundant facts are quietly pruned while sleeping.

---

## A Real Example

Here is a concrete trace of how a piece of knowledge traveled through the full pipeline in this very deployment.

### Day T: The work happens

On 2026-04-17, the dev agent was working on the `auto_dream.py` Step 3 consolidation logic. During the session, `session_snapshot.py` was capturing conversations into `memory/2026-04-17.md` every 5 minutes.

Within 15 minutes, `auto_digest --today` ran its two passes on the new diary content.

**Pass ① (general facts) produced:**
```
- Python developer (based on code snippets)
- The project involves server.py and Memory.from_config()
- Using reflect_week function for memory reflection
```

**Pass ② (task extraction) produced:**
```
[开发] 完成 Step 3 候选对处理，找到12个候选对（dev agent）
[分析] 分析 auto_dream_reflect 写入数为0的原因（记忆重复问题）
[分析] 验证 reflect_week 逻辑工作正常，7天日记合并读取成功
[开发] blog agent 完成7天日记反射，生成88,923字符记忆
```

Both sets of entries live in short-term memory with `run_id=2026-04-17`. They are immediately queryable — within 20 minutes of the work happening, another session of the same agent could search mem0 and find:

```json
{
  "memory": "[开发] 完成 Step 3 候选对处理，找到12个候选对（dev agent）",
  "memory_type": "short_term",
  "run_id": "2026-04-17",
  "metadata": { "source": "auto_digest_task", "category": "task" }
}
```

### The same night: Auto Dream runs

At UTC 02:00, `auto_dream.py` ran Step 1: it read the 7-day diary corpus (2026-04-11 through 2026-04-17) and submitted it with the `REFLECTION_PROMPT`. The LLM identified a cross-day pattern — the agent had been repeatedly analyzing and debugging Auto Dream internals across multiple sessions — and wrote this observation directly to long-term memory with no `run_id`:

```json
{
  "memory": "Agent repeatedly analyzed and debugged auto_dream pipeline internals across multiple days — reflects an ongoing focus on memory system reliability and correctness",
  "memory_type": "long_term",
  "metadata": { "source": "auto_dream_reflect", "reflect_range": "2026-04-11~2026-04-17" }
}
```

Step 3 (consolidation) also ran that night and found several long-term entries about `mem0-memory-service` project state were semantically near-duplicate. Nine such pairs were consolidated into cleaner merged entries tagged `source=auto_dream_consolidation`:

```json
{
  "memory": "mem0-memory-service is actively developed; dev agent is the primary contributor working on pipeline reliability, embedding model switching, and memory consolidation features",
  "metadata": { "source": "auto_dream_consolidation" }
}
```

### Day T+7: Promotion happens

On 2026-04-24, Auto Dream's Step 2 targets `run_id=2026-04-17`. Each short-term entry is re-submitted to mem0 without a `run_id`. mem0 now searches the full long-term store and decides:

| Short-term entry | mem0 decision | Reason |
|---|---|---|
| `[开发] 完成 Step 3 候选对处理，找到12个候选对` | `ADD` → long-term | No equivalent in long-term |
| `Using reflect_week function for memory reflection` | `NONE` | Already captured by Step 1's reflection entry |
| `Python developer (based on code snippets)` | `UPDATE` | Merges into existing "dev agent tech stack" memory |

The original short-term entries are deleted. The knowledge that mattered — task completion records, technical patterns — survives in long-term storage. The generic or redundant entries are quietly dropped.

### The outcome

What started as raw conversation fragments became:
- **Within 15 min** → structured task records, queryable by category
- **Same night** → recurring pattern crystallized into long-term insight
- **After 7 days** → individual facts promoted, redundant ones dropped, long-term store compacted

All without any explicit human curation. This is AutoDream working as intended: *not just archiving the past, but distilling it.*

---

## Timeline Summary

| Time | Script | What happens |
|------|--------|--------------|
| Every 5 min | `session_snapshot.py` | Conversation → diary file |
| Every 15 min | `auto_digest.py --today` | Diary → short-term (Pass ①: general facts + Pass ②: task extraction) |
| UTC 02:00 | `auto_dream.py` Step 1 | 7-day diary corpus → long-term (cross-day reflection via `REFLECTION_PROMPT`) |
| UTC 02:00 | `auto_dream.py` Step 2 | 7-day-old short-term → re-add to long-term (global dedup) → delete originals |
| UTC 02:00 | `auto_dream.py` Step 3 | Long-term consolidation: rotating batch scan → merge near-duplicate pairs |
