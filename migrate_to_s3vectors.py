#!/usr/bin/env python3
"""
Migrate memories from OpenSearch to S3Vectors.

Usage:
  python3 migrate_to_s3vectors.py                          # migrate all
  python3 migrate_to_s3vectors.py --user boss               # specific user
  python3 migrate_to_s3vectors.py --user boss --agent dev   # specific user+agent
  python3 migrate_to_s3vectors.py --dry-run                 # preview only

Requires both OpenSearch and S3Vectors env vars configured simultaneously.
Source data in OpenSearch is NOT deleted.
"""
import argparse
import logging
import sys

from config import (
    OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_USER, OPENSEARCH_PASSWORD,
    OPENSEARCH_USE_SSL, OPENSEARCH_VERIFY_CERTS, OPENSEARCH_COLLECTION,
    S3VECTORS_BUCKET_NAME, S3VECTORS_INDEX_NAME,
    EMBEDDING_MODEL, EMBEDDING_DIMS, AWS_REGION,
    LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate")


def _base_config():
    """Shared embedder + llm config."""
    return {
        "embedder": {
            "provider": "aws_bedrock",
            "config": {"model": EMBEDDING_MODEL},
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


def build_opensearch_config():
    return {
        **_base_config(),
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
    }


def build_s3vectors_config():
    if not S3VECTORS_BUCKET_NAME:
        logger.error("S3VECTORS_BUCKET_NAME is required. Set it in .env or environment.")
        sys.exit(1)
    return {
        **_base_config(),
        "vector_store": {
            "provider": "s3_vectors",
            "config": {
                "vector_bucket_name": S3VECTORS_BUCKET_NAME,
                "collection_name": S3VECTORS_INDEX_NAME,
                "embedding_model_dims": EMBEDDING_DIMS,
                "distance_metric": "cosine",
                "region_name": AWS_REGION,
            },
        },
    }


def fetch_memories(src, user_id=None, agent_id=None):
    """Fetch all memories from source, with optional filters."""
    kwargs = {}
    if user_id:
        kwargs["user_id"] = user_id
    if agent_id:
        kwargs["agent_id"] = agent_id
    result = src.get_all(**kwargs)
    # Handle both dict {"results": [...]} and direct list
    if isinstance(result, dict):
        return result.get("results", [])
    return result if isinstance(result, list) else []


def migrate(src, dst, memories, dry_run=False):
    """Migrate memories from src to dst. Returns (success, failed_list).

    Writes directly to the vector store, bypassing mem0's add() which
    triggers a QueryVectors dedup search with an invalid filter format.
    """
    total = len(memories)
    success = 0
    failed = []

    for i, mem in enumerate(memories):
        text = mem.get("memory") or mem.get("text", "")
        if not text:
            logger.warning(f"[{i+1}/{total}] Skipping empty memory id={mem.get('id')}")
            failed.append({"id": mem.get("id"), "error": "empty text"})
            continue

        if dry_run:
            logger.info(f"[{i+1}/{total}] [DRY-RUN] {text[:80]}...")
            success += 1
        else:
            try:
                metadata = mem.get("metadata") or {}
                metadata["migrated_from"] = "opensearch"
                if mem.get("user_id"):
                    metadata["user_id"] = mem["user_id"]
                if mem.get("agent_id"):
                    metadata["agent_id"] = mem["agent_id"]
                if mem.get("run_id"):
                    metadata["run_id"] = mem["run_id"]
                metadata["data"] = text

                vector = dst.embedding_model.embed(text, "add")
                mem_id = mem.get("id") or str(__import__('uuid').uuid4())
                dst.vector_store.insert(vectors=[vector], payloads=[metadata], ids=[mem_id])
                success += 1
            except Exception as e:
                logger.error(f"[{i+1}/{total}] Failed id={mem.get('id')}: {e}")
                failed.append({"id": mem.get("id"), "error": str(e)})

        if (i + 1) % 10 == 0:
            logger.info(f"Progress: {i+1}/{total}")

    return success, failed


def main():
    parser = argparse.ArgumentParser(description="Migrate memories from OpenSearch to S3Vectors")
    parser.add_argument("--user", default=None, help="Filter by user_id")
    parser.add_argument("--agent", default=None, help="Filter by agent_id")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    args = parser.parse_args()

    from mem0 import Memory

    logger.info("Initializing OpenSearch source...")
    src = Memory.from_config(build_opensearch_config())

    logger.info("Fetching memories from OpenSearch...")
    memories = fetch_memories(src, args.user, args.agent)
    total = len(memories)
    logger.info(f"Found {total} memories to migrate")

    if total == 0:
        logger.info("Nothing to migrate.")
        return

    if args.dry_run:
        logger.info("=== DRY-RUN MODE (no data will be written) ===")
        dst = None
    else:
        logger.info("Initializing S3Vectors destination...")
        dst = Memory.from_config(build_s3vectors_config())

    success, failed = migrate(src, dst, memories, args.dry_run)

    # Summary
    print("\n" + "=" * 50)
    print(f"Migration complete {'(DRY-RUN)' if args.dry_run else ''}")
    print(f"  Total:   {total}")
    print(f"  Success: {success}")
    print(f"  Failed:  {len(failed)}")
    print("=" * 50)

    if failed:
        print("\nFailed entries:")
        for f in failed:
            print(f"  - id={f['id']}: {f['error']}")


if __name__ == "__main__":
    main()
