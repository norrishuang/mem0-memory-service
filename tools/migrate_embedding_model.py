#!/usr/bin/env python3
"""
迁移 embedding 模型脚本
将 pgvector 中所有记忆从旧模型重新用新模型生成 embedding

用法:
  python3 tools/migrate_embedding_model.py [--dry-run] [--batch-size 50]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

# 加载 .env
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

# 配置
PG_HOST = os.getenv("PGVECTOR_HOST", "mem0-postgres")
PG_DB = os.getenv("PGVECTOR_DB", "mem0")
PG_USER = os.getenv("PGVECTOR_USER", "mem0")
PG_PASSWORD = os.getenv("PGVECTOR_PASSWORD", "mem0")
PG_PORT = int(os.getenv("PGVECTOR_PORT", "5432"))
COLLECTION = os.getenv("PGVECTOR_COLLECTION", "mem0_memories")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

NEW_MODEL = "cohere.embed-multilingual-v3"
NEW_DIMS = 1024


def get_pg_conn():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )


def get_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=AWS_REGION)


def embed_batch(bedrock, texts: List[str]) -> List[List[float]]:
    """用 Cohere multilingual-v3 批量生成 embedding"""
    body = json.dumps({
        "texts": texts,
        "input_type": "search_document",
        "truncate": "END",
    })
    resp = bedrock.invoke_model(
        modelId=NEW_MODEL,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["body"].read())
    return result["embeddings"]


def fetch_all_records(conn) -> List[Tuple]:
    """获取所有记忆记录 (id, payload)"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(f"SELECT id, payload FROM {COLLECTION} ORDER BY id")
        return cur.fetchall()


def update_vector(conn, record_id: str, vector: List[float]):
    """更新单条记录的 vector"""
    vector_str = "[" + ",".join(str(v) for v in vector) + "]"
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {COLLECTION} SET vector = %s::vector WHERE id = %s",
            (vector_str, record_id),
        )


def extract_text(payload: dict) -> str:
    """从 payload 中提取文本内容"""
    if isinstance(payload, str):
        payload = json.loads(payload)
    # mem0 存储格式：payload.data 或 payload.text
    return (
        payload.get("data")
        or payload.get("text")
        or payload.get("memory")
        or str(payload)
    )


def main():
    parser = argparse.ArgumentParser(description="迁移 embedding 模型")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不实际写入")
    parser.add_argument("--batch-size", type=int, default=50, help="每批处理记录数 (默认50，Cohere 最大96)")
    args = parser.parse_args()

    print(f"🔄 开始迁移 embedding 模型 → {NEW_MODEL}")
    print(f"   数据库: {PG_HOST}/{PG_DB}.{COLLECTION}")
    print(f"   模式: {'DRY RUN（不写入）' if args.dry_run else '实际写入'}")
    print()

    conn = get_pg_conn()
    bedrock = get_bedrock_client()

    # 获取所有记录
    print("📖 读取所有记忆记录...")
    records = fetch_all_records(conn)
    total = len(records)
    print(f"   共 {total} 条记录")
    print()

    if args.dry_run:
        print("=== DRY RUN 模式，不实际更新向量 ===")
        # 抽样验证 embedding 是否正常
        sample = records[:3]
        texts = [extract_text(r["payload"]) for r in sample]
        print("抽样文本:")
        for t in texts:
            print(f"  - {t[:80]}")
        embeddings = embed_batch(bedrock, texts)
        print(f"\n✅ 抽样 embedding 成功，维度: {len(embeddings[0])}")
        return

    # 分批处理
    batch_size = min(args.batch_size, 96)  # Cohere 最大 96
    success = 0
    failed = 0
    start_time = time.time()

    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        batch_texts = []
        batch_ids = []

        for r in batch:
            text = extract_text(r["payload"])
            batch_texts.append(text)
            batch_ids.append(str(r["id"]))

        try:
            embeddings = embed_batch(bedrock, batch_texts)

            # 批量更新
            for record_id, vector in zip(batch_ids, embeddings):
                update_vector(conn, record_id, vector)

            conn.commit()
            success += len(batch)
            elapsed = time.time() - start_time
            print(f"  ✅ [{i + len(batch)}/{total}] 已处理 {success} 条 | 耗时 {elapsed:.1f}s")

        except Exception as e:
            conn.rollback()
            failed += len(batch)
            print(f"  ❌ 批次 [{i}~{i+len(batch)}] 失败: {e}", file=sys.stderr)
            # 继续下一批
            continue

        # 适当休眠避免限流
        time.sleep(0.3)

    elapsed = time.time() - start_time
    print()
    print(f"🎉 迁移完成！成功: {success} | 失败: {failed} | 耗时: {elapsed:.1f}s")

    if failed > 0:
        print(f"⚠️  有 {failed} 条记录失败，请检查错误日志后重新运行")
        sys.exit(1)

    conn.close()


if __name__ == "__main__":
    main()
