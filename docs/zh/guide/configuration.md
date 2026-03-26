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
| `LLM_MODEL` | `us.anthropic.claude-3-5-haiku-20241022-v1:0` | LLM model |
| `LLM_TEMPERATURE` | `0.1` | LLM temperature |
| `LLM_MAX_TOKENS` | `2000` | Max tokens |
| `SERVICE_HOST` | `0.0.0.0` | Service bind address |
| `SERVICE_PORT` | `8230` | Service port |

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

LLM_MODEL=us.anthropic.claude-3-5-haiku-20241022-v1:0
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=2000

SERVICE_HOST=0.0.0.0
SERVICE_PORT=8230
```

## Data Isolation

Two-dimensional isolation using `user_id` + `agent_id`:

- **user_id** — different users' memories are completely isolated
- **agent_id** — different agents of the same user manage memories independently
- Omitting `agent_id` allows cross-agent retrieval
