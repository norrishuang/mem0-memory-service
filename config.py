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

# Vector Store selection: "opensearch" (default) or "s3vectors"
VECTOR_STORE = os.getenv("VECTOR_STORE", "opensearch").lower()

# OpenSearch
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
OPENSEARCH_COLLECTION = os.getenv("OPENSEARCH_COLLECTION", "mem0_memories")

# S3Vectors
S3VECTORS_BUCKET_NAME = os.getenv("S3VECTORS_BUCKET_NAME", "")
S3VECTORS_INDEX_NAME = os.getenv("S3VECTORS_INDEX_NAME", "mem0")

# Embedding
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0")
EMBEDDING_DIMS = int(os.getenv("EMBEDDING_DIMS", "1024"))

# LLM (for mem0 memory extraction / dedup / conflict resolution)
LLM_MODEL = os.getenv("LLM_MODEL", "minimax.minimax-m2.5")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2000"))

# LLM for digest/summary (auto_digest.py pipeline)
# Independent from mem0's internal LLM, used exclusively by the digest/summary scripts
DIGEST_LLM_MODEL = os.getenv("DIGEST_LLM_MODEL", "minimax.minimax-m2.5")
DIGEST_LLM_REGION = os.getenv("DIGEST_LLM_REGION", AWS_REGION)

# Service
SERVICE_HOST = os.getenv("SERVICE_HOST", "0.0.0.0")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8230"))


def _get_vector_store_config() -> dict:
    """Build vector_store config based on VECTOR_STORE env var."""
    if VECTOR_STORE == "s3vectors":
        if not S3VECTORS_BUCKET_NAME:
            raise ValueError("S3VECTORS_BUCKET_NAME is required when VECTOR_STORE=s3vectors")
        return {
            "provider": "s3_vectors",
            "config": {
                "vector_bucket_name": S3VECTORS_BUCKET_NAME,
                "collection_name": S3VECTORS_INDEX_NAME,
                "embedding_model_dims": EMBEDDING_DIMS,
                "distance_metric": "cosine",
                "region_name": AWS_REGION,
            },
        }
    # Default: opensearch
    return {
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
    }


def get_mem0_config() -> dict:
    """Build mem0 config dict from settings."""
    return {
        "vector_store": _get_vector_store_config(),
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


def replace_llm_with_tracked(memory_instance):
    """Replace memory.llm with TrackedAWSBedrockLLM (same config, adds token tracking)."""
    from tracked_llm import TrackedAWSBedrockLLM
    memory_instance.llm = TrackedAWSBedrockLLM(memory_instance.llm.config)
