# 迁移工具

## OpenSearch → S3 Vectors

使用 `migrate_to_s3vectors.py` 将现有记忆从 OpenSearch 迁移到 S3Vectors。

### 前提条件

需要同时配置 OpenSearch 和 S3Vectors 的环境变量 — 在 `.env` 中保留 OpenSearch 配置，同时设置 `S3VECTORS_BUCKET_NAME`。

### 用法

```bash
# 迁移所有用户的记忆
python3 migrate_to_s3vectors.py

# 仅迁移指定用户
python3 migrate_to_s3vectors.py --user boss

# 指定用户和代理
python3 migrate_to_s3vectors.py --user boss --agent dev

# 试运行模式（仅预览，不写入）
python3 migrate_to_s3vectors.py --dry-run
```

::: warning 安全提示
迁移过程**不会**删除 OpenSearch 中的源数据。请在验证 S3Vectors 数据完整性后，再手动清理 OpenSearch。
:::

## MEMORY.md → mem0

如果你之前使用 `MEMORY.md` 管理记忆，可以迁移到 mem0：

```bash
# 编辑脚本中的 MEMORY_FILE 路径、USER_ID、AGENT_ID
vim migrate_memory_md.py

# 执行迁移
python3 migrate_memory_md.py
```
