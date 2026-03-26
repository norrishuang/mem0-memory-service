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

## Search

```bash
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":5}'
```

## Combined Search

Searches long-term memory + recent N days of short-term memory, merged and deduplicated.

```bash
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":10,"recent_days":7}'
```

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
