# Configuration

All configuration is managed through environment variables or a `.env` file. The `install.sh` script auto-generates it.

## Setup

```bash
cp .env.example .env
vim .env
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |
| `VECTOR_STORE` | `opensearch` | Vector engine: `opensearch` or `s3vectors` |
| `OPENSEARCH_HOST` | `localhost` | OpenSearch host |
| `OPENSEARCH_PORT` | `9200` | OpenSearch port |
| `OPENSEARCH_USER` | `admin` | Username |
| `OPENSEARCH_PASSWORD` | — | Password |
| `OPENSEARCH_USE_SSL` | `false` | Enable SSL |
| `OPENSEARCH_VERIFY_CERTS` | `false` | Verify SSL certificates |
| `OPENSEARCH_COLLECTION` | `mem0_memories` | Index name |
| `S3VECTORS_BUCKET_NAME` | — | S3Vectors bucket (required for `s3vectors` mode) |
| `S3VECTORS_INDEX_NAME` | `mem0` | S3Vectors index name |
| `EMBEDDING_MODEL` | `amazon.titan-embed-text-v2:0` | Embedding model |
| `EMBEDDING_DIMS` | `1024` | Vector dimensions |
| `LLM_MODEL` | `minimax.minimax-m2.5` | LLM model for mem0 memory extraction / dedup (see [LLM selection guide](#llm-selection)) |
| `LLM_TEMPERATURE` | `0.1` | LLM temperature |
| `LLM_MAX_TOKENS` | `2000` | Max tokens |
| `DIGEST_LLM_MODEL` | `minimax.minimax-m2.5` | LLM model for `auto_digest.py` summarization pipeline (defaults to `LLM_MODEL` if unset) |
| `DIGEST_LLM_REGION` | same as `AWS_REGION` | AWS region override for the digest LLM |
| `SERVICE_HOST` | `0.0.0.0` | Service bind address |
| `SERVICE_PORT` | `8230` | Service port |
| `MEM0_TELEMETRY` | `true` | **⚠️ 建议关闭。** mem0 默认开启匿名遥测，每次 `add/search/delete` 都向 `us.i.posthog.com` 上报操作元数据（collection 名、LLM 类型、vector store 类型等），**同时每次调用都创建一个新的 PostHog Consumer 线程**，长时间运行后（尤其是 auto_dream 批量处理记忆后）会积累大量僵尸线程（测试中观察到 135 个）。私有部署请设为 `false`。 |
| `SEARCH_TOP_K` | `5` | Default `top_k` for `/memory/search` and `/memory/search_combined` |
| `SEARCH_RECENT_DAYS` | `3` | Default recent days window for `/memory/search_combined` |

## Example `.env`

```env
AWS_REGION=us-east-1

VECTOR_STORE=opensearch
OPENSEARCH_HOST=your-opensearch-host.es.amazonaws.com
OPENSEARCH_PORT=443
OPENSEARCH_USER=admin
OPENSEARCH_PASSWORD=your-password
OPENSEARCH_USE_SSL=true
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_COLLECTION=mem0_memories

EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIMS=1024

# LLM — mem0 memory extraction + digest pipeline
LLM_MODEL=minimax.minimax-m2.5
DIGEST_LLM_MODEL=minimax.minimax-m2.5
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=2000

SERVICE_HOST=0.0.0.0
SERVICE_PORT=8230

# 关闭 mem0 匿名遥测（强烈建议，避免线程泄漏）
MEM0_TELEMETRY=false
```

## LLM Selection

mem0 uses an LLM for two purposes:
- **Memory extraction / dedup** (`LLM_MODEL`) — called on every `memory/add` request
- **Digest summarization** (`DIGEST_LLM_MODEL`) — called by `auto_digest.py` to summarize diary entries

Both default to `minimax.minimax-m2.5`. Here's a comparison of supported models on AWS Bedrock `us-east-1`:

| Model | `LLM_MODEL` value | Avg latency | Input | Output | Notes |
|-------|-------------------|------------|-------|--------|-------|
| **MiniMax M2.5** ✅ | `minimax.minimax-m2.5` | ~2-3s | $0.30/1M | $1.20/1M | Default. Best cost (~3× cheaper than Haiku) |
| Claude Haiku 4.5 | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | ~1s | $1.00/1M | $5.00/1M | Fastest; no patch required |
| DeepSeek V3.2 | `deepseek.v3.2` | ~2-4s | $0.62/1M | $1.85/1M | No clear advantage over MiniMax |

::: warning
**MiniMax requires a patch.** Before using any `minimax.*` model, run:
```bash
python3 tools/patch_minimax_support.py
```
See [Known Issues](./known-issues.md#pr-4609-minimax-models-not-recognized-on-aws-bedrock) for details.
:::

## Data Isolation

Two-dimensional isolation using `user_id` + `agent_id`:

- **user_id** — different users' memories are completely isolated
- **agent_id** — different agents of the same user manage memories independently
- Omitting `agent_id` allows cross-agent retrieval

## Token Tracking

The service automatically tracks LLM token consumption for every `/memory/add` call via `TrackedAWSBedrockLLM` — a thin wrapper around `AWSBedrockLLM` that monkey-patches `client.converse()` to capture `inputTokens / outputTokens / totalTokens` from Bedrock Converse API responses.

**How it works:**

1. Before each `memory.add()` call, a global counter (protected by a threading lock) is reset.
2. Every Bedrock `converse()` call inside mem0 accumulates tokens into the counter.
3. After `memory.add()` returns, the counter snapshot is:
   - Returned in the API response as `token_usage`
   - Written to the daily audit log (`audit_logs/audit-YYYY-MM-DD.jsonl`) as a `type=token_usage` entry

**Analyzing token usage:**

```bash
# Daily summary
cat audit_logs/audit-$(date +%Y-%m-%d).jsonl | python3 -c "
import sys, json
from collections import defaultdict
records = [json.loads(l) for l in sys.stdin if l.strip()]
tok = [r for r in records if r.get('type') == 'token_usage']
total = sum(r.get('total_tokens', 0) for r in tok)
print(f'{len(tok)} calls, {total:,} total tokens')
"
```

::: tip
Token tracking adds negligible overhead (a single dict write per Bedrock API call). It requires no extra configuration — it is always enabled when the service starts.
:::
