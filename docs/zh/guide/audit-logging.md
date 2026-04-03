# 审计日志与 Token 追踪

mem0 Memory Service 内置审计日志和 Token 用量追踪，每次 API 调用均自动记录。可用于监控 API 使用情况、评估 LLM 成本、对接外部日志采集系统。

## 日志位置

Docker 部署时，审计日志写入 `./audit_logs/` 目录（在 `docker-compose.yml` 中挂载为 `./audit_logs:/app/audit_logs`），宿主机可直接访问。

- **格式**：JSONL（每行一个 JSON 对象）
- **滚动**：按天滚动，每天生成新文件
- **保留**：30 天前的文件自动清理

## 日志格式

每次 API 调用产生两条日志：一条**请求日志**和一条 **Token 用量日志**。

### 请求日志

```json
{"ts":"2026-04-03T15:24:51.973471+00:00","method":"POST","path":"/memory/add","status":200,"elapsed_ms":36294,"ip":"127.0.0.1","agent_id":"dev","user_id":"boss"}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | string | ISO 8601 时间戳（含时区） |
| `method` | string | HTTP 方法（`GET`、`POST`、`PUT`、`DELETE`） |
| `path` | string | API 端点路径 |
| `status` | int | HTTP 响应状态码 |
| `elapsed_ms` | int | 请求耗时（毫秒） |
| `ip` | string | 客户端 IP 地址 |
| `agent_id` | string | Agent 标识 |
| `user_id` | string | 用户标识 |

### Token 用量日志

```json
{"ts":"2026-04-03T15:24:51.973128+00:00","type":"token_usage","path":"/memory/add","agent_id":"dev","user_id":"boss","llm_calls":19,"input_tokens":42256,"output_tokens":38000,"total_tokens":80256}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `ts` | string | ISO 8601 时间戳（含时区） |
| `type` | string | 固定值 `token_usage` |
| `path` | string | API 端点路径 |
| `agent_id` | string | Agent 标识 |
| `user_id` | string | 用户标识 |
| `llm_calls` | int | 本次请求中 LLM 调用次数 |
| `input_tokens` | int | 消耗的输入 token 总数 |
| `output_tokens` | int | 消耗的输出 token 总数 |
| `total_tokens` | int | 输入 + 输出 token 总和 |

## Token 追踪与成本估算

### Bedrock 定价参考

| 模型 | 输入 | 输出 |
|------|------|------|
| Claude Haiku 3.5 | $0.80 / 1M tokens | $4.00 / 1M tokens |
| Titan Embed Text v2 | $0.02 / 1M tokens | — |

### 成本计算示例

以上面的 Token 用量日志为例（一次 `add` with `infer=True`）：

- **输入**：42,256 tokens × $0.80 / 1M = **$0.0338**
- **输出**：38,000 tokens × $4.00 / 1M = **$0.1520**
- **本次请求总计**：**~$0.186**

::: warning
`add` with `infer=True` 会触发多次 LLM 调用（本例中为 19 次），用于记忆提取和去重——这是成本最高的操作。`search` 仅触发 embedding（Titan Embed v2，$0.02/1M tokens），成本几乎可忽略。
:::

## 对接外部日志采集

`audit_logs/` 目录下的 JSONL 文件可被任何支持文件 tail 的日志采集工具读取。以下是三种常见配置。

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

## 查询审计日志

使用 `jq` 直接在宿主机上查询 JSONL 文件。

**今日 Token 总用量：**

```bash
cat audit_logs/$(date +%Y-%m-%d)*.jsonl | \
  jq -s '[.[] | select(.type=="token_usage")] | {total_input: (map(.input_tokens) | add), total_output: (map(.output_tokens) | add), total: (map(.total_tokens) | add)}'
```

**按 Agent 汇总 Token 用量：**

```bash
cat audit_logs/*.jsonl | \
  jq -s 'group_by(.agent_id) | map({agent: .[0].agent_id, total_tokens: (map(.total_tokens // 0) | add)}) | sort_by(-.total_tokens)'
```

**最慢的 5 个请求：**

```bash
cat audit_logs/*.jsonl | \
  jq -s '[.[] | select(.elapsed_ms)] | sort_by(-.elapsed_ms) | .[:5] | .[] | {path, elapsed_ms, agent_id, ts}'
```

**错误率（非 2xx 响应）：**

```bash
cat audit_logs/*.jsonl | \
  jq -s '[.[] | select(.status)] | {total: length, errors: ([.[] | select(.status >= 400)] | length)} | .rate = (.errors / .total * 100 | round | tostring + "%")'
```
