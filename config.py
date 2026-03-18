"""
mem0 Memory Service Configuration
Reads from environment variables (supports .env file).
"""
import os
from pathlib import Path

# Auto-load .env from the same directory
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

# AWS
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
# Ensure boto3 picks it up
os.environ.setdefault("AWS_REGION", AWS_REGION)

# OpenSearch
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
OPENSEARCH_COLLECTION = os.getenv("OPENSEARCH_COLLECTION", "mem0_memories")

# Embedding
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "1024"))

# LLM (for mem0 memory extraction / dedup / conflict resolution)
LLM_MODEL = os.getenv("LLM_MODEL", "us.anthropic.claude-3-5-haiku-20241022-v1:0")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

# Service
SERVICE_HOST = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8230"))


def get_mem0_config() -> dict:
    """Build mem0 config dict from settings."""
    return {
        "vector_store": {
            "provider": "opensearch",
            "config": {
                "collection_name": OPENSEARCH_COLLECTION,
                "host": OPENSEARCH_HOST,
                "port": OPENSEARCH_PORT,
                "http_auth": (OPENSEARCH_USER, OPENSEARCH_PASSWORD),
                "embedding_model_dims": EMBEDDING_DIMS,
                "use_ssl": OPENSEARCH_USE_SSL,
                "verify_certs": OPENSEARCH_VERIFY_CERTS,
            },
        },
        "embedder": {
            "provider": "aws_bedrock",
            "config": {
                "model": EMBEDDING_MODEL,
            },
        },
        "llm": {
            "provider": "aws_bedrock",
            "config": {
                "model": LLM_MODEL,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": LLM_MAX_TOKENS,
            },
        },
    }
