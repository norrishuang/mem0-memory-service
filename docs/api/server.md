# REST API Reference

The Memory Service runs a FastAPI server on port `8230` by default.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/memory/add` | Add memory |
| `POST` | `/memory/search` | Semantic search |
| `POST` | `/memory/search_combined` | Combined search (long-term + recent short-term) |
| `GET` | `/memory/list` | List memories |
| `GET` | `/memory/{id}` | Get a single memory |
| `PUT` | `/memory/update` | Update memory |
| `DELETE` | `/memory/{id}` | Delete memory |
| `GET` | `/memory/history/{id}` | Memory change history |

## Health Check

```bash
curl http://127.0.0.1:8230/health
```

```json
{"status": "ok", "service": "mem0-memory-service"}
```

## Add Memory

```bash
# Long-term memory (text)
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","text":"Important lesson..."}'

# Short-term memory (with run_id)
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","run_id":"2026-03-23","text":"Today discussion..."}'

# From conversation messages
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}'
```

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `user_id` | string | ✅ | User identifier |
| `agent_id` | string | | Agent identifier |
| `run_id` | string | | Run ID for short-term memory (`YYYY-MM-DD`) |
| `text` | string | ✅* | Raw text to memorize |
| `messages` | array | ✅* | Conversation messages `[{role, content}]` |
| `metadata` | object | | Extra metadata tags |
| `infer` | boolean | | Whether mem0 should extract facts (default: `true`). Set `false` to store raw text as-is. |
| `custom_extraction_prompt` | string | | Custom prompt to guide fact extraction. Overrides default prompt when `infer=true`. See [Targeted Extraction](#targeted-extraction). |

\* Either `text` or `messages` is required.

**Response** includes a `token_usage` field with LLM consumption for this call:

```json
{
  "results": [...],
  "token_usage": {
    "llm_calls": 3,
    "input_tokens": 2925,
    "output_tokens": 1419,
    "total_tokens": 4344
  }
}
```

::: tip
Token usage is also written to the audit log (`audit_logs/audit-YYYY-MM-DD.jsonl`) as `type=token_usage` entries, enabling daily cost analysis.
:::


## Targeted Extraction

By default mem0 uses a generic fact-extraction prompt. Pass `custom_extraction_prompt` to guide extraction toward a specific dimension without changing global config.

```bash
# Extract completed work tasks from a session block
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "boss",
    "agent_id": "dev",
    "run_id": "2026-04-11",
    "text": "<session block content>",
    "infer": true,
    "metadata": {"category": "task"},
    "custom_extraction_prompt": "从以下对话中列出agent实际完成的工作任务（最终成果），每行一条，格式：[类型] 描述。类型：开发/修复/文档/配置/分析/部署/其他。只写最终成果，不超过5条。"
  }'

# Extract technical decisions
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "boss",
    "agent_id": "dev",
    "text": "<session block>",
    "metadata": {"category": "decision"},
    "custom_extraction_prompt": "从以下对话中提取重要技术决策及原因，每条一行，格式：[决策] 原因。"
  }'
```

**When to use:**
| Situation | Recommended `custom_extraction_prompt` |
|-----------|----------------------------------------|
| Work task summary | `"列出agent实际完成的工作任务（最终成果），格式：[类型] 描述..."` |
| Technical decisions | `"提取重要技术决策及原因，格式：[决策] 原因..."` |
| Config/env discovery | `"提取新增的服务配置、端口、路径等环境信息..."` |
| Default (omit) | mem0 uses generic extraction — good for mixed content |

> **Note:** `custom_extraction_prompt` only affects this single call. It does not change the global mem0 configuration.

## Search

```bash
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":5}'
```

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | ✅ | Natural language search query |
| `user_id` | string | ✅ | User identifier |
| `agent_id` | string | | Agent identifier |
| `top_k` | int | `5` | Max results to return |
| `run_id` | string | | Filter by specific run ID |
| `min_score` | float | `0.0` | Minimum similarity score (0.0–1.0). Recommended: `0.3`–`0.5` to filter low-relevance noise |

## Combined Search

Searches long-term memory + recent N days of short-term memory, merged and deduplicated.

```bash
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":5,"recent_days":3}'
```

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | ✅ | Natural language search query |
| `user_id` | string | ✅ | User identifier |
| `agent_id` | string | | Agent identifier |
| `top_k` | int | `5` | Max results (applied to both long-term and short-term before merge) |
| `recent_days` | int | `3` | How many recent days of short-term memory to include |
| `min_score` | float | `0.0` | Minimum similarity score (0.0–1.0). Recommended: `0.3`–`0.5` |

## List Memories

```bash
# All memories for a user
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev'

# Short-term memories for a specific date
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev&run_id=2026-03-23'
```

## Get / Update / Delete

```bash
# Get
curl http://127.0.0.1:8230/memory/<memory_id>

# Update
curl -X PUT http://127.0.0.1:8230/memory/update \
  -H 'Content-Type: application/json' \
  -d '{"memory_id":"<id>","text":"Updated text"}'

# Delete
curl -X DELETE http://127.0.0.1:8230/memory/<memory_id>
```

## Memory History

```bash
curl http://127.0.0.1:8230/memory/history/<memory_id>
```
