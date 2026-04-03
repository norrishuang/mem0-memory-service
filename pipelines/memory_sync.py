#!/usr/bin/env python3
"""
memory_sync.py - 同步各 agent 的 MEMORY.md 到 mem0 长期记忆

每天 UTC 01:00 运行（在 auto_digest 之前）。
读取每个 agent workspace 下的 MEMORY.md，用 MD5 hash 检测变更，
变更时调用 mem0 API 写入长期记忆（无 run_id）。
"""
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import requests

# ─── Configuration ───

OPENCLAW_BASE = Path(os.environ.get("OPENCLAW_BASE",
                     os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")))
OPENCLAW_CONFIG = OPENCLAW_BASE / "openclaw.json"

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent))

STATE_FILE = DATA_DIR / ".memory_sync_state.json"
LOG_FILE = DATA_DIR / "memory_sync.log"

MEM0_API_URL = os.environ.get("MEM0_API_URL", "http://127.0.0.1:8230")
USER_ID = "boss"

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


# ─── Agent Discovery (reuse pattern from session_snapshot.py) ───

def load_agent_workspaces() -> dict[str, Path]:
    """从 openclaw.json 读取每个 agent 的 workspace 路径，兜底扫描目录"""
    mapping = {}

    if OPENCLAW_CONFIG.exists():
        try:
            with open(OPENCLAW_CONFIG) as f:
                config = json.load(f)

            def _extract(obj):
                if isinstance(obj, dict):
                    if 'id' in obj and 'workspace' in obj and isinstance(obj.get('workspace'), str):
                        mapping[obj['id']] = Path(obj['workspace'])
                    for v in obj.values():
                        _extract(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _extract(v)

            _extract(config)
            logger.debug(f"Loaded {len(mapping)} agent workspaces from openclaw.json")
        except Exception as e:
            logger.warning(f"Failed to parse openclaw.json: {e}, falling back to directory scan")

    if not mapping:
        for ws_dir in sorted(OPENCLAW_BASE.glob("workspace-*")):
            agent_id = ws_dir.name.replace("workspace-", "")
            mapping[agent_id] = ws_dir

    return mapping


# ─── State Management ───

def load_state() -> dict[str, str]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict[str, str]):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ─── Core ───

def sync_agent(agent_id: str, workspace: Path, state: dict[str, str]) -> bool:
    """同步单个 agent 的 MEMORY.md，返回是否有变更"""
    memory_file = workspace / "MEMORY.md"
    if not memory_file.exists():
        logger.debug(f"[{agent_id}] No MEMORY.md, skipping")
        return False

    content = memory_file.read_text(encoding='utf-8')
    if not content.strip():
        logger.debug(f"[{agent_id}] MEMORY.md is empty, skipping")
        return False

    current_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
    if state.get(agent_id) == current_hash:
        logger.info(f"[{agent_id}] MEMORY.md unchanged (hash={current_hash[:8]}), skipping")
        return False

    logger.info(f"[{agent_id}] MEMORY.md changed, syncing to mem0 ({len(content)} bytes)")

    payload = {
        "user_id": USER_ID,
        "agent_id": agent_id,
        "text": content,
        "metadata": {
            "category": "knowledge",
            "source": "memory_sync"
        }
    }

    try:
        resp = requests.post(f"{MEM0_API_URL}/memory/add", json=payload, timeout=120)
        resp.raise_for_status()
        state[agent_id] = current_hash
        logger.info(f"[{agent_id}] ✓ Synced to mem0")
        return True
    except Exception as e:
        logger.error(f"[{agent_id}] ✗ Failed to sync: {e}")
        return False


def main():
    logger.info("=" * 80)
    logger.info("Starting memory_sync.py")

    workspaces = load_agent_workspaces()
    logger.info(f"Discovered {len(workspaces)} agents: {list(workspaces.keys())}")

    state = load_state()
    synced = 0

    for agent_id, workspace in sorted(workspaces.items()):
        try:
            if sync_agent(agent_id, workspace, state):
                synced += 1
        except Exception as e:
            logger.error(f"[{agent_id}] Error: {e}", exc_info=True)

    save_state(state)
    logger.info(f"Memory sync complete: {synced} agents synced")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
