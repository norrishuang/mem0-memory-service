# Audit Logging and Token Tracking

mem0 Memory Service includes built-in audit logging and token usage tracking for every API call. Use it to monitor API usage, estimate LLM costs, and feed logs into external collectors.

## Log Location

When deployed via Docker, audit logs are written to the `./audit_logs/` directory (mounted as `./audit_logs:/app/audit_logs` in `docker-compose.yml`), directly accessible from the host.

- **Format**: JSONL (one JSON object per line)
- **Rotation**: Daily — a new file is created each day
- **Retention**: Files older than 30 days are automatically deleted

## Log Format

Every API call produces two log entries: a **request log** and a **token usage log**.

### Request Log

```json
{"ts":"2026-04-03T15:24:51.973471+00:00","method":"POST","path":"/memory/add","status":200,"elapsed_ms":36294,"ip":"127.0.0.1","agent_id":"dev","user_id":"boss"}
```

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string | ISO 8601 timestamp with timezone |
| `method` | string | HTTP method (`GET`, `POST`, `PUT`, `DELETE`) |
| `path` | string | API endpoint path |
| `status` | int | HTTP response status code |
| `elapsed_ms` | int | Request duration in milliseconds |
| `ip` | string | Client IP address |
| `agent_id` | string | Agent identifier |
| `user_id` | string | User identifier |

### Token Usage Log

```json
{"ts":"2026-04-03T15:24:51.973128+00:00","type":"token_usage","path":"/memory/add","agent_id":"dev","user_id":"boss","llm_calls":19,"input_tokens":42256,"output_tokens":38000,"total_tokens":80256}
```

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string | ISO 8601 timestamp with timezone |
| `type` | string | Always `token_usage` |
| `path` | string | API endpoint path |
| `agent_id` | string | Agent identifier |
| `user_id` | string | User identifier |
| `llm_calls` | int | Number of LLM invocations in this request |
| `input_tokens` | int | Total input tokens consumed |
| `output_tokens` | int | Total output tokens consumed |
| `total_tokens` | int | Sum of input + output tokens |

## Token Tracking and Cost Estimation

### Bedrock Pricing Reference

| Model | Input | Output |
|-------|-------|--------|
| Claude Haiku 3.5 | $0.80 / 1M tokens | $4.00 / 1M tokens |
| Titan Embed Text v2 | $0.02 / 1M tokens | — |

### Example Cost Calculation

Given the sample token usage log above (a single `add` with `infer=True`):

- **Input**: 42,256 tokens × $0.80 / 1M = **$0.0338**
- **Output**: 38,000 tokens × $4.00 / 1M = **$0.1520**
- **Total for this request**: **~$0.186**

::: warning
`add` with `infer=True` triggers multiple LLM calls (19 in this example) for memory extraction and deduplication — this is the most expensive operation. `search` only triggers embedding (Titan Embed v2 at $0.02/1M tokens), making it negligible in cost.
:::

## Integrating External Log Collectors

The JSONL files in `audit_logs/` can be tailed by any file-based log shipper. Below are three common configurations.

### Fluent Bit → OpenSearch

```ini
[INPUT]
    Name        tail
    Path        /path/to/mem0-memory-service/audit_logs/*.jsonl
    Tag         mem0.audit
    Parser      json
    Refresh_Interval 5

[OUTPUT]
    Name        opensearch
    Match       mem0.audit
    Host        your-opensearch-host
    Port        443
    Index       mem0-audit-logs
    Type        _doc
    tls         On
    HTTP_User   admin
    HTTP_Passwd your-password
```

### Vector → Elasticsearch

```yaml
sources:
  mem0_audit:
    type: file
    include:
      - /path/to/mem0-memory-service/audit_logs/*.jsonl

transforms:
  parse_json:
    type: remap
    inputs:
      - mem0_audit
    source: '. = parse_json!(string!(.message))'

sinks:
  elasticsearch:
    type: elasticsearch
    inputs:
      - parse_json
    endpoints:
      - https://your-elasticsearch-host:9200
    bulk:
      index: mem0-audit-logs
```

### AWS CloudWatch Logs Agent

```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/path/to/mem0-memory-service/audit_logs/*.jsonl",
            "log_group_name": "/mem0/audit-logs",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
```

## Querying Audit Logs

Use `jq` to query JSONL files directly from the host.

**Today's total token usage:**

```bash
cat audit_logs/$(date +%Y-%m-%d)*.jsonl | \
  jq -s '[.[] | select(.type=="token_usage")] | {total_input: (map(.input_tokens) | add), total_output: (map(.output_tokens) | add), total: (map(.total_tokens) | add)}'
```

**Token usage grouped by agent:**

```bash
cat audit_logs/*.jsonl | \
  jq -s 'group_by(.agent_id) | map({agent: .[0].agent_id, total_tokens: (map(.total_tokens // 0) | add)}) | sort_by(-.total_tokens)'
```

**Top 5 slowest requests:**

```bash
cat audit_logs/*.jsonl | \
  jq -s '[.[] | select(.elapsed_ms)] | sort_by(-.elapsed_ms) | .[:5] | .[] | {path, elapsed_ms, agent_id, ts}'
```

**Error rate (non-2xx responses):**

```bash
cat audit_logs/*.jsonl | \
  jq -s '[.[] | select(.status)] | {total: length, errors: ([.[] | select(.status >= 400)] | length)} | .rate = (.errors / .total * 100 | round | tostring + "%")'
```
