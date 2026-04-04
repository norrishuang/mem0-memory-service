#!/usr/bin/env python3
"""
auto_dream.py - AutoDream 记忆沉淀（夜间自动巩固）

每天 UTC 02:00 运行，对每个 agent 执行两步：
  Step 1: 读取昨日日记 → POST mem0.add(infer=True, 无 run_id) → 长期记忆
  Step 2: 找到 7 天前的短期记忆 → 逐条 re-add 到 mem0(infer=True, 无 run_id) → 删除原始短期条目
         mem0 原生决定 ADD/UPDATE/DELETE/NONE，不再手写语义搜索判断。
"""

import json
import logging
import os
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── Configuration ───

BASE_URL = os.environ.get("MEM0_API_URL", "http://127.0.0.1:8230")
USER_ID = "boss"
ARCHIVE_DAYS = 7
MAX_MEMORIES_PER_RUN = 300
MAX_CONSECUTIVE_ERRORS = 3
INTER_MEMORY_SLEEP = 0.2  # mem0 串行处理，瓶颈在 Bedrock LLM (~6s/条)，0.2s 足够防止请求堆积
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent))
LOG_FILE = DATA_DIR / "auto_dream.log"

OPENCLAW_BASE = Path(os.environ.get("OPENCLAW_BASE",
                     os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")))
OPENCLAW_CONFIG = OPENCLAW_BASE / "openclaw.json"

# ─── Setup Logging ───

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # cron >> /app/data/auto_dream.log handles file writing
    ]
)
logger = logging.getLogger(__name__)


# ─── Agent Discovery ───

def load_agent_ids() -> list[str]:
    """从 openclaw.json 读取所有 agent id，兜底扫描 workspace-* 目录"""
    agent_ids = []

    if OPENCLAW_CONFIG.exists():
        try:
            with open(OPENCLAW_CONFIG) as f:
                config = json.load(f)

            def _extract(obj):
                if isinstance(obj, dict):
                    if 'id' in obj and 'workspace' in obj and isinstance(obj.get('workspace'), str):
                        agent_ids.append(obj['id'])
                    for v in obj.values():
                        _extract(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _extract(v)

            _extract(config)
            return agent_ids
        except Exception as e:
            logger.warning(f"Failed to parse openclaw.json: {e}, falling back to directory scan")

    for ws_dir in sorted(OPENCLAW_BASE.glob("workspace-*")):
        agent_ids.append(ws_dir.name.replace("workspace-", ""))
    return agent_ids


def load_agent_workspaces() -> dict[str, Path]:
    """从 openclaw.json 读取 agent_id → workspace Path 映射"""
    mapping = {}

    if OPENCLAW_CONFIG.exists():
        try:
            with open(OPENCLAW_CONFIG) as f:
                config = json.load(f)

            def _remap_workspace(ws: Path) -> Path:
                """将宿主机 workspace 路径重映射到容器内挂载路径。"""
                if ws.exists():
                    return ws
                ws_str = str(ws)
                for host_prefix in [
                    str(Path.home() / ".openclaw"),
                    "/home/ec2-user/.openclaw",
                ]:
                    if ws_str.startswith(host_prefix):
                        remapped = Path(str(OPENCLAW_BASE) + ws_str[len(host_prefix):])
                        if remapped.exists():
                            return remapped
                return ws

            def _extract(obj):
                if isinstance(obj, dict):
                    if 'id' in obj and 'workspace' in obj and isinstance(obj.get('workspace'), str):
                        mapping[obj['id']] = _remap_workspace(Path(obj['workspace']))
                    for v in obj.values():
                        _extract(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _extract(v)

            _extract(config)
        except Exception as e:
            logger.warning(f"Failed to parse openclaw.json: {e}, falling back to directory scan")

    if not mapping:
        for ws_dir in sorted(OPENCLAW_BASE.glob("workspace-*")):
            agent_id = ws_dir.name.replace("workspace-", "")
            mapping[agent_id] = ws_dir

    return mapping


# ─── Helpers ───

def get_beijing_yesterday() -> str:
    tz_beijing = timezone(timedelta(hours=8))
    yesterday = datetime.now(tz_beijing).date() - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def get_short_term_memories(agent_id: str, run_id: str) -> list:
    """获取指定 agent + run_id 的所有短期记忆"""
    params = {"user_id": USER_ID, "agent_id": agent_id, "run_id": run_id}
    try:
        resp = requests.get(f"{BASE_URL}/memory/list", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", data) if isinstance(data, dict) else data
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        return results if isinstance(results, list) else []
    except Exception as e:
        logger.error(f"[{agent_id}] Error getting memories for run_id={run_id}: {e}")
        return []


def delete_memory(memory_id: str):
    """删除记忆"""
    try:
        resp = requests.delete(
            f"{BASE_URL}/memory/{memory_id}",
            params={"agent_id": "auto_dream", "user_id": USER_ID},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"  ✗ Failed to delete {memory_id}: {e}")
        raise


# ─── Step 1: Digest Yesterday Diary ───

def digest_yesterday(agent_id: str, workspace: Path):
    """读取昨日日记 → POST mem0.add(infer=True, 无 run_id) → 长期记忆"""
    yesterday = get_beijing_yesterday()
    diary_file = workspace / "memory" / f"{yesterday}.md"
    if not diary_file.exists():
        logger.info(f"[{agent_id}] No diary for {yesterday}, skipping digest")
        return
    content = diary_file.read_text(encoding="utf-8").strip()
    if not content:
        logger.info(f"[{agent_id}] Empty diary for {yesterday}, skipping digest")
        return
    resp = requests.post(f"{BASE_URL}/memory/add", json={
        "user_id": USER_ID,
        "agent_id": agent_id,
        "text": content,
        "infer": True,
        "metadata": {"source": "auto_dream_digest", "digest_date": yesterday}
    }, timeout=120)
    resp.raise_for_status()
    logger.info(f"[{agent_id}] Digested yesterday diary ({len(content)} chars) into long-term memory")


# ─── Step 2: Consolidate Old Short-Term Memories ───

def consolidate_old_memories(agent_id: str, target_run_id: str) -> int:
    """逐条 re-add 7天前短期记忆到长期(infer=True, 无 run_id)，然后删除原始条目"""
    memories = get_short_term_memories(agent_id, target_run_id)
    if not memories:
        logger.info(f"[{agent_id}] No short-term memories for {target_run_id}")
        return 0

    processed = 0
    consecutive_errors = 0
    cap = min(len(memories), MAX_MEMORIES_PER_RUN)
    if len(memories) > MAX_MEMORIES_PER_RUN:
        logger.warning(f"[{agent_id}] {len(memories)} memories, processing first {cap} (paging)")

    for mem in memories[:cap]:
        mem_id = mem.get("id")
        mem_text = mem.get("memory", "")
        if not mem_id or not mem_text:
            continue
        try:
            resp = requests.post(f"{BASE_URL}/memory/add", json={
                "user_id": USER_ID,
                "agent_id": agent_id,
                "text": mem_text,
                "infer": True,
                "metadata": {"source": "auto_dream_consolidated", "original_run_id": target_run_id}
            }, timeout=120)
            resp.raise_for_status()
            delete_memory(mem_id)
            processed += 1
            consecutive_errors = 0
            logger.info(f"[{agent_id}] Consolidated: {mem_text[:60]}...")
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"[{agent_id}] Error ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.error(f"[{agent_id}] Aborting after {MAX_CONSECUTIVE_ERRORS} consecutive errors")
                break
        time.sleep(INTER_MEMORY_SLEEP)

    return processed


# ─── Main ───

def main():
    logger.info("=" * 80)
    logger.info("Starting auto_dream.py (AutoDream consolidation)")

    tz_beijing = timezone(timedelta(hours=8))
    today = datetime.now(tz_beijing).date()
    target_date = today - timedelta(days=ARCHIVE_DAYS)
    target_run_id = target_date.strftime("%Y-%m-%d")

    logger.info(f"Beijing date: {today}")
    logger.info(f"Target run_id for consolidation: {target_run_id}")

    workspaces = load_agent_workspaces()
    logger.info(f"Discovered {len(workspaces)} agents: {list(workspaces.keys())}")

    total_consolidated = 0

    for agent_id, workspace in sorted(workspaces.items()):
        try:
            # Step 1: digest yesterday diary → long-term memory
            digest_yesterday(agent_id, workspace)
            # Step 2: consolidate 7-day-old short-term → long-term, then delete
            total_consolidated += consolidate_old_memories(agent_id, target_run_id)
        except Exception as e:
            logger.error(f"[{agent_id}] Fatal error: {e}", exc_info=True)

    logger.info(f"\nAutoDream complete: consolidated {total_consolidated} memories")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)
