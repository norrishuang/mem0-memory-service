#!/usr/bin/env python3
"""
archive.py - 归档短期记忆

每天运行一次：
1. 找到7天前（run_id=7天前日期）的所有短期记忆
2. 对每条记忆，用其内容在近7天短期记忆中做语义搜索
3. 如果有相关讨论（score > 0.75）→ 升级为长期记忆（无 run_id 写入）
4. 如果没有相关讨论 → 直接删除
"""

import json
import logging
import sys
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Configuration ───

BASE_URL = "http://127.0.0.1:8230"
USER_ID = "boss"
AGENT_ID = "dev"
ARCHIVE_DAYS = 7        # 处理多少天前的短期记忆
ACTIVE_THRESHOLD = 0.75  # 活跃度判断阈值（语义相似度）
LOG_FILE = Path(__file__).parent / "archive.log"

# ─── Setup Logging ───

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# ─── Core Functions ───

def get_short_term_memories(run_id: str) -> list:
    """获取指定 run_id 的所有短期记忆"""
    params = {"user_id": USER_ID, "agent_id": AGENT_ID, "run_id": run_id}
    try:
        resp = requests.get(f"{BASE_URL}/memory/list", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        # 兼容 mem0 返回格式
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        return results if isinstance(results, list) else []
    except Exception as e:
        logger.error(f"Error getting memories for run_id={run_id}: {e}")
        return []


def is_topic_active(memory_text: str, exclude_run_id: str) -> bool:
    """判断话题是否在近7天还活跃（语义搜索近期短期记忆）"""
    tz_beijing = timezone(timedelta(hours=8))
    today = datetime.now(tz_beijing).date()

    for i in range(1, ARCHIVE_DAYS):  # 查最近1~6天（排除要归档的那天）
        day = today - timedelta(days=i)
        run_id = day.strftime("%Y-%m-%d")
        if run_id == exclude_run_id:
            continue

        payload = {
            "query": memory_text,
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "run_id": run_id,
            "top_k": 3
        }
        try:
            resp = requests.post(f"{BASE_URL}/memory/search", json=payload, timeout=30)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if isinstance(results, dict):
                results = results.get("results", [])
            for r in results:
                score = r.get("score", 0)
                if score >= ACTIVE_THRESHOLD:
                    logger.debug(f"  Found active match (score={score:.2f}) in run_id={run_id}")
                    return True
        except Exception as e:
            logger.debug(f"  Error searching run_id={run_id}: {e}")
            pass

    return False


def promote_to_long_term(memory_text: str, original_metadata: dict):
    """升级为长期记忆（不带 run_id）"""
    metadata = {k: v for k, v in (original_metadata or {}).items()
                if k not in ("category", "source", "digest_date")}
    metadata["category"] = "experience"
    metadata["source"] = "archive_promoted"

    payload = {
        "user_id": USER_ID,
        "agent_id": AGENT_ID,
        "text": memory_text,
        "metadata": metadata
    }
    try:
        resp = requests.post(f"{BASE_URL}/memory/add", json=payload, timeout=60)
        resp.raise_for_status()
        logger.info(f"  ✓ Promoted to long-term memory")
    except Exception as e:
        logger.error(f"  ✗ Failed to promote: {e}")
        raise


def delete_memory(memory_id: str):
    """删除记忆"""
    try:
        resp = requests.delete(f"{BASE_URL}/memory/{memory_id}", timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"  ✗ Failed to delete {memory_id}: {e}")
        raise


def main():
    """Main entry point."""
    logger.info("=" * 80)
    logger.info("Starting archive.py")

    # Get current date in Beijing timezone
    tz_beijing = timezone(timedelta(hours=8))
    today = datetime.now(tz_beijing).date()
    target_date = today - timedelta(days=ARCHIVE_DAYS)
    target_run_id = target_date.strftime("%Y-%m-%d")

    logger.info(f"Beijing date: {today}")
    logger.info(f"Archiving short-term memories for run_id={target_run_id}")

    # Get memories to archive
    memories = get_short_term_memories(target_run_id)
    if not memories:
        logger.info(f"No short-term memories found for {target_run_id}")
        logger.info("=" * 80)
        return

    logger.info(f"Found {len(memories)} memories to process")
    promoted = 0
    deleted = 0

    for mem in memories:
        mem_id = mem.get("id")
        mem_text = mem.get("memory", "")
        mem_metadata = mem.get("metadata", {})

        if not mem_text or not mem_id:
            logger.warning(f"Skipping memory with missing id or text: {mem}")
            continue

        logger.info(f"\nProcessing: {mem_text[:60]}...")

        # Check if topic is still active
        if is_topic_active(mem_text, target_run_id):
            logger.info(f"  → Active topic detected, promoting to long-term")
            try:
                promote_to_long_term(mem_text, mem_metadata)
                delete_memory(mem_id)
                promoted += 1
            except Exception as e:
                logger.error(f"  → Failed to promote/delete: {e}")
        else:
            logger.info(f"  → Inactive topic, deleting")
            try:
                delete_memory(mem_id)
                deleted += 1
            except Exception as e:
                logger.error(f"  → Failed to delete: {e}")

    logger.info(f"\nArchive complete:")
    logger.info(f"  - Promoted to long-term: {promoted}")
    logger.info(f"  - Deleted as inactive: {deleted}")
    logger.info(f"  - Total processed: {promoted + deleted}")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)
