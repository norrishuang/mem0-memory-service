# Design Decision: Evolution of the Memory Ingestion Pipeline

> Recorded: 2026-03-28
> Authors: norrishuang + Dev Agent

This page documents the full evolution of the `session_snapshot → mem0` memory ingestion pipeline —
the motivations behind each change, the problems we discovered, and the final trade-offs we made.

---

## Phase 1: Original Design (Snapshot Writes Directly to mem0)

### What We Did

In `session_snapshot.py`, every run would **synchronously push** new session messages to the mem0 API.
The goal was "real-time memory" — messages captured within the 5-minute snapshot cycle would be
immediately distilled into memories and available for recall in the next Agent session.

```
session → [snapshot every 5min] → diary file
                                ↘ mem0 (direct POST, real-time)
```

### Problems Found

1. **Thread explosion**: snapshot processes multiple Agent sessions in a single process. Each direct POST to mem0 waits for Bedrock LLM (fact extraction ~3–10s). With many sessions running concurrently, thread count spiked rapidly and memory usage ballooned.
2. **Low-quality memories**: Feeding 5-minute conversation fragments directly to mem0 produced noisy, low-value short-term memories that cluttered the vector store.
3. **Coupled responsibilities**: snapshot was doing two jobs — writing diary and writing memories. A failure in either affected the other.

### Fix (commit `a841494`)

Removed mem0 write logic from session_snapshot entirely. **Snapshots write diary files only.** All mem0 writes delegated to auto_digest.

---

## Phase 2: More Aggressive Memory Ingestion (Two-Layer Pipeline)

### What We Did

To compensate for the fix above (memories now only updated once a day at UTC 01:30),
we introduced `auto_digest.py --today` incremental mode, running every **15 minutes**:

1. Read **newly appended bytes** from today's diary since the last run (tracked via `auto_digest_offset.json`)
2. POST in **50KB batches** directly to mem0 (fact extraction handled internally by mem0, no local LLM)
3. Persist offset after each successful batch (crash-safe resume)

This formed a two-layer pipeline:

```
session → [snapshot 5min]         → diary
          [digest --today 15min]  → mem0 (STM, near-realtime)
          [digest full 01:30]     → mem0 (STM, high quality)
          [archive 02:00]         → mem0 (LTM)
```

### Problems Found

The approach was technically sound, but running it revealed a cascade of issues:

1. **Diary file bloat out of control**
   - The original dedup logic used `line not in existing_content`.
   - After diary trim/rotation, historical content was gone — dedup broke, and identical messages were re-written on every snapshot run.
   - One diary file grew to **2.6MB** (target: ≤200KB), containing **114 duplicate snapshots** of the same sessions.

2. **Trim size calculation was wrong**
   - `MAX_DIARY_LINES=800` does not bound file size — line lengths vary wildly. 800 lines easily exceeded 200KB. The trim was meaningless.

3. **auto_digest offset vs. diary trim conflict**
   - After trim truncated the diary, `auto_digest_offset.json` held a byte offset pointing to content that no longer existed. The next digest run would either overflow or skip content.

4. **event=NONE log noise**
   - When mem0's internal LLM determines a memory doesn't need updating, it returns `event=NONE`.
   - The update API doesn't accept this value, causing `Parameter validation failed` ERROR logs on every such call. Very noisy.

---

## Phase 3: Regression + Precise Fixes (Current)

### Core Decision: Simpler Architecture + Fix the Actual Bugs

The "more aggressive ingestion" approach added complexity that outweighed its benefits.
We decided to:

- **Keep** `auto_digest.py --today` as a supplementary channel, but not rely on it for "real-time"
- **Fix the root causes** in session_snapshot rather than layering more logic on top

### Specific Fixes

#### Bug 1: Duplicate Writes (PR #20, commit `f3d87f2`)

**Root cause**: Content-based dedup breaks after trim removes historical lines.

**Fix**: Persist each message's MD5 hash in `offsets.json` (`written_hashes` set).
Hash set is unaffected by trim — dedup works correctly regardless of diary size.

```python
# Before: content dedup (breaks after trim)
if line not in existing_content:
    write(line)

# After: hash-persisted dedup (trim-safe)
msg_hash = md5(message_content)
if msg_hash not in offsets["written_hashes"]:
    write(line)
    offsets["written_hashes"].add(msg_hash)
```

**Verified**: Running snapshot twice consecutively — second run writes 0 lines ✅

#### Bug 2: Inaccurate Trim Size (PR #20, commit `f3d87f2`)

**Root cause**: `MAX_DIARY_LINES=800` doesn't bound byte size.

**Fix**: Remove line limit, replace with **byte-budget loop trim** — drop 10% of leading lines per iteration until file ≤ 200KB.

```python
MAX_DIARY_BYTES = 200 * 1024  # strict 200KB ceiling

while len(content.encode()) > MAX_DIARY_BYTES:
    lines = content.splitlines()
    drop = max(1, len(lines) // 10)
    content = "\n".join(lines[drop:])
```

#### Bug 3: event=NONE Log Noise (PR #20, commit `43893fe`)

**Fix**: In server.py `add_memory` exception handler, detect `event=NONE` errors and downgrade from ERROR to `logger.warning()`. Return a normal empty response to the caller — no functional impact.

---

## Current State & Trade-off Analysis

### Current Architecture

```
session → [snapshot 5min]         → diary (hash dedup, 200KB ceiling)
          [digest --today 15min]  → mem0 STM (50KB batches, near-realtime)
          [digest full 01:30]     → mem0 STM (LLM distill, full-day context)
          [archive 02:00]         → mem0 LTM (active↑, inactive→delete)
```

### Strengths

| Strength | Details |
|----------|---------|
| **Reliable dedup** | Hash-persisted; trim doesn't break dedup. Diary no longer bloats. |
| **Controlled size** | Strict 200KB byte budget — diary always manageable. |
| **Near-realtime** | 15-min incremental writes; today's important events don't wait until 01:30. |
| **High-quality full digest** | Daily 01:30 LLM distillation over the full previous day's diary — better context, better memories. |
| **Fault isolation** | snapshot and digest are decoupled; one failing doesn't affect the other. |

### Weaknesses / Known Issues

| Weakness | Details | Mitigation |
|----------|---------|------------|
| **Trim discards early-day content** | When diary exceeds 200KB, leading content is trimmed before the 01:30 full digest runs | digest --today writes every 15min, so trimmed content should already be in mem0 |
| **auto_digest offset can conflict with trim** | Offset may point past EOF after trim | Known issue; fix pending — need to validate offset ≤ current file size before reading |
| **High mem0 write latency** | add average ~9s, occasional >10s | Bedrock LLM overhead; semaphore limits prevent concurrency explosion |
| **Timer may re-trigger same session** | User systemd timer occasionally fires before prior session ends | Hash dedup absorbs this — no duplicate writes |

---

## Key Lessons

1. **"More aggressive ingestion" ≠ "better memories"** — Feeding 5-minute conversation fragments to LLM produces noisy, low-value memories. Accumulating full context first yields much higher quality.

2. **Dedup logic must be robust to storage mutations** — Content-based dedup fails whenever the backing store is trimmed or rotated. Persisted hashes are the correct approach.

3. **Byte budget beats line count** — Using line count to bound file size is an anti-pattern. Line lengths vary; only bytes are an accurate measure.

4. **Separation of concerns beats real-time** — snapshot writes diary only, digest writes mem0 only. Clear boundaries make each component independently debuggable and optimizable.

5. **Ship fast, iterate precisely** — We couldn't anticipate all edge cases before the complex approach broke. Fast iteration + targeted fixes beat trying to design perfectly upfront.
