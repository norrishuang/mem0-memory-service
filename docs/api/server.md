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
