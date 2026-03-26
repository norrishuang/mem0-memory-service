# Migration Tool

## OpenSearch → S3 Vectors

Use `migrate_to_s3vectors.py` to migrate existing memories from OpenSearch to S3Vectors.

### Prerequisites

Both OpenSearch and S3Vectors environment variables must be configured simultaneously — keep OpenSearch config in `.env` and also set `S3VECTORS_BUCKET_NAME`.

### Usage

```bash
# Migrate all users' memories
python3 migrate_to_s3vectors.py

# Migrate a specific user only
python3 migrate_to_s3vectors.py --user boss

# Specific user and agent
python3 migrate_to_s3vectors.py --user boss --agent dev

# Dry-run mode (preview only, no writes)
python3 migrate_to_s3vectors.py --dry-run
```

::: warning Safety Note
The migration does **not** delete source data in OpenSearch. Verify S3Vectors data integrity before manually cleaning up OpenSearch.
:::

## MEMORY.md → mem0

If you previously used `MEMORY.md` to manage memories, migrate to mem0:

```bash
# Edit MEMORY_FILE path, USER_ID, AGENT_ID in the script
vim migrate_memory_md.py

# Run migration
python3 migrate_memory_md.py
```
