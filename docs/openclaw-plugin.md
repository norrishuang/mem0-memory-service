# OpenClaw Plugin

The mem0 Memory Plugin hooks into OpenClaw's agent lifecycle to provide real-time diary capture and memory retrieval. Every meaningful conversation turn is written to a diary file as it happens via the `agent_end` hook, and relevant memories are injected into the system prompt before each response.

## Architecture

### How the Plugin Fits into the Memory System

```mermaid
flowchart LR
    subgraph Realtime["Real-time (Plugin)"]
        P["OpenClaw Plugin"]
    end
    subgraph Batch["Batch (Pipelines)"]
        D["auto_digest\n(every 15 min)"]
        DR["auto_dream\n(daily UTC 02:00)"]
    end

    Conv["Conversations"] --> P -->|"writeDiaryEntry\n(real-time)"| Diary["Diary Files\n(memory/YYYY-MM-DD.md)"]
    Diary --> D -->|"infer=True"| Mem0[("mem0\nVector Store")]
    Mem0 -->|"7-day short-term"| DR -->|"consolidate"| Mem0
    Mem0 -->|"search"| P -->|"inject into\nsystem prompt"| Conv
```

The plugin and the existing pipelines are complementary:

| Component | Trigger | Write Mode | Purpose |
|-----------|---------|------------|---------|
| **Plugin** (`agent_end`) | Every conversation turn | Diary file (`writeDiaryEntry`) | Real-time diary capture, zero LLM cost |
| **Plugin** (`before_compaction`) | Before session compaction | `infer=true` to mem0 | LLM-distilled write before context is lost |
| **Plugin** (`before_prompt_build`) | Before each response | Search only | Inject relevant memories into prompt |
| `auto_digest` | Every 15 min (cron) | `infer=true` to mem0 | Extract facts from diary files |
| `auto_dream` | Daily UTC 02:00 (cron) | `infer=true` to mem0 | Consolidate short-term → long-term |

### Sequence: Normal Conversation Turn

```mermaid
sequenceDiagram
    participant U as User
    participant OC as OpenClaw Agent
    participant P as Plugin
    participant M as mem0 Service
    participant FS as Diary File

    U->>OC: Send message
    P->>M: Search relevant memories (before_prompt_build)
    M-->>P: Return matching memories
    P-->>OC: Inject memories into system prompt
    OC->>U: Respond
    OC->>P: agent_end event
    P->>FS: writeDiaryEntry → memory/YYYY-MM-DD.md
    Note over P,FS: Written to diary file, no LLM cost
```

### Sequence: Session Compaction

```mermaid
sequenceDiagram
    participant OC as OpenClaw
    participant P as Plugin
    participant M as mem0 Service
    participant LLM as AWS Bedrock

    OC->>P: before_compaction event
    P->>M: POST /memory/add (infer=true)
    M->>LLM: Extract key facts
    LLM-->>M: Distilled memories
    M-->>P: OK
    OC->>OC: Execute compaction
    Note over OC: Context window compressed,<br/>but memories are preserved in mem0
```

## Plugin Hooks

### `agent_end` — Write Conversation to Diary

Fires after each agent turn completes successfully. Extracts the last user+assistant exchange and writes it to the agent's diary file via `writeDiaryEntry`.

**Behavior:**
- Writes to `~/.openclaw/workspace-{agentId}/memory/YYYY-MM-DD.md` — diary entries are routed by `agentId` to each agent's workspace
- Skips if the exchange is shorter than `minExchangeLength` (default 100 chars)
- Filters noise (greetings, trivial exchanges) via `isNoise`
- Cleans content (removes system artifacts) via `cleanContent`
- Debounced per session — at most one write per `debounceMs` (default 60s)
- Workspace base path resolved via `getWorkspaceBase` from `openclaw.json`

### `before_compaction` — Flush Before Context Loss

Fires when OpenClaw is about to compress the session context. Writes the last exchange to mem0 with `infer=true` so the LLM distills key facts before the full context is lost.

**Behavior:**
- Always uses `infer=true` — this is the last chance to capture context
- No debounce — compaction is infrequent and critical

### `before_prompt_build` — Inject Memories

Fires before each agent response is generated. Searches mem0 for memories relevant to the current user prompt and prepends them to the system context.

**Behavior:**
- Extracts the first 200 characters of the user prompt as the search query
- Returns up to `injectLimit` results (default 5), truncated to `injectMaxChars` (default 800)
- Times out after `injectTimeoutMs` (default 3s) — silently skips on timeout
- Injected as a `## Relevant Memories` section prepended to the prompt

## Key Functions

### `writeDiaryEntry(agentId, content)`

Writes a conversation entry to the agent's daily diary file. The diary path is resolved as `{diaryBasePath}/workspace-{agentId}/memory/YYYY-MM-DD.md`. Creates the directory structure if it doesn't exist. Appends content with a timestamp header.

### `cleanContent(text)`

Removes system artifacts, excessive whitespace, and formatting noise from conversation text before writing to the diary file. Ensures diary entries are clean and readable.

### `isNoise(exchange)`

Determines whether a conversation exchange is noise (greetings, trivial acknowledgments, very short exchanges) that should be skipped. Returns `true` if the exchange should not be written to the diary.

### `getWorkspaceBase(agentId)`

Resolves the workspace base path for a given agent from `openclaw.json`. Returns the path where diary files should be written (e.g., `~/.openclaw/workspace-{agentId}`). Falls back to `{diaryBasePath}/workspace-{agentId}` if not found in config.

## Configuration

All configuration is set in `openclaw.plugin.json` or passed via OpenClaw's plugin config system.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mem0Url` | string | `http://localhost:8230` | mem0 service endpoint |
| `userId` | string | `boss` | User ID for mem0 operations |
| `agentIds` | string[] | `["dev","main","pm","researcher","pjm","prototype"]` | Agent IDs to process (empty = all) |
| `diaryBasePath` | string | `~/.openclaw` | Base path for diary files. Diary entries are written to `{diaryBasePath}/workspace-{agentId}/memory/YYYY-MM-DD.md` |
| `enableWrite` | boolean | `false` | Enable `before_compaction` writes with `infer=true` to mem0 |
| `enableRawWrite` | boolean | `true` | Enable `agent_end` diary file writes (writes conversation to diary file, not to mem0) |
| `enableInject` | boolean | `false` | Enable memory injection via `before_prompt_build` |
| `enableCompactionFlush` | boolean | `true` | Enable `before_compaction` flush to mem0 |
| `minExchangeLength` | number | `100` | Minimum exchange length (chars) to trigger a write |
| `injectLimit` | number | `5` | Max memories to inject per prompt |
| `injectMaxChars` | number | `800` | Max total chars for injected memories |
| `debounceMs` | number | `60000` | Debounce interval per session (ms) |
| `injectTimeoutMs` | number | `3000` | Timeout for memory search (ms) |

> **`enableRawWrite`**: When `true`, the `agent_end` hook writes conversation content to diary files (`memory/YYYY-MM-DD.md`) in the agent's workspace. This is the primary diary capture mechanism — zero LLM cost, real-time. The diary files are later processed by `auto_digest` (every 15 min) and `auto_dream` (nightly) to distill into mem0 vector memory.
>
> **`enableWrite`**: Controls `before_compaction` behavior. When `true`, compaction events trigger `infer=true` writes directly to mem0 — this is the last chance to capture context before the session is compressed.

## Installation

### 1. Copy the Plugin

```bash
cp -r openclaw-plugin ~/.openclaw/plugins/mem0-memory-plugin
```

### 2. Enable in OpenClaw Settings

Add the plugin to your `openclaw.json`:

```json
{
  "plugins": {
    "mem0-memory-plugin": {
      "enabled": true,
      "config": {
        "mem0Url": "http://localhost:8230",
        "userId": "boss",
        "enableWrite": false,
        "enableRawWrite": true,
        "enableInject": true
      }
    }
  }
}
```

### 3. Verify

After enabling, check the OpenClaw logs for:

```
[mem0-plugin] Registered. mem0Url=http://localhost:8230 userId=boss agentIds=dev,main,pm,researcher,pjm,prototype
```

## Recommended Setup

For most users, we recommend **diary write mode** (`enableRawWrite=true`):

```json
{
  "enableWrite": false,
  "enableRawWrite": true,
  "enableInject": true
}
```

**Why?**
- `agent_end` writes conversation to diary files with zero LLM cost — captured immediately after each turn
- `before_compaction` always uses `infer=true` — critical context is distilled before loss
- `auto_digest` (every 15 min) picks up new diary content and writes to mem0 short-term memory
- `auto_dream` (nightly) consolidates into high-quality long-term knowledge
- Memory injection gives agents context from past conversations in real time

This gives you the best balance of cost, latency, and memory quality.

## Relationship with Existing Pipelines

The plugin does **not** replace the existing pipeline system. They work together:

```
Real-time path (Plugin):
  Conversation → agent_end → diary file (real-time, per turn)
  Compaction   → before_compaction → mem0 (infer, critical)
  Prompt       → before_prompt_build → search → inject

Batch path (Pipelines):
  Diary   → auto_digest --today (every 15 min) → mem0 short-term
  Nightly → auto_dream (UTC 02:00) → long-term consolidation
```

- **Plugin** provides real-time diary capture and memory retrieval — no delay between conversation and diary file
- **Pipelines** provide structured diary-to-mem0 distillation and nightly consolidation — higher quality long-term memories
- Both paths contribute to the same diary files and mem0 instance — `auto_digest` reads the diary files written by the plugin
