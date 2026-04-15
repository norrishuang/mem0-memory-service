#!/usr/bin/env python3
"""
auto_dream.py - AutoDream 记忆沉淀（夜间自动巩固）

每天 UTC 02:00 运行，对每个 agent 执行三步：
  Step 1: 读取昨日日记 → POST mem0.add(infer=True, 无 run_id) → 长期记忆
  Step 2: 找到 7 天前的短期记忆 → 逐条 re-add 到 mem0(infer=True, 无 run_id) → 删除原始短期条目
         mem0 原生决定 ADD/UPDATE/DELETE/NONE，不再手写语义搜索判断。
  Step 3: 扫描已有长期记忆，找出语义高度相似的冗余对，用 mem0 infer=True 合并去冗余。
         每次处理一个批次（轮转），避免单次运行时间过长。
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

CONSOLIDATION_BATCH = 50
CONSOLIDATION_THRESHOLD = 0.85
CONSOLIDATION_OFFSET_FILE = DATA_DIR / "auto_dream_consolidation_offset.json"

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

def get_utc_yesterday() -> str:
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")


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


# ─── Custom Extraction Prompt ───

# 引导 mem0 从技术工作日记中提炼有价值的长期经验，而非碎片化事实。
# 覆盖两个维度：
#   1. 技术开发：踩坑记录、方案决策、配置要点
#   2. 沟通协作：与 Boss 交互中需要注意的行为规范和偏好
DIARY_EXTRACTION_PROMPT = """
你是一位资深技术助理，负责从工作日记中提炼有长期价值的经验和规范，供未来工作参考。

请阅读以下工作日记，提炼以下两个维度的内容：

【维度一：技术开发经验】
- 遇到了什么技术问题，最终怎么解决的
- 做了哪些技术决策，为什么选这个方案而不是其他方案
- 哪些做法踩坑了，下次应该避免
- 重要的配置、环境、接口信息（端口、服务名、路径等）

【维度二：与 Boss 的沟通协作规范】
- Boss 明确要求或反复强调的工作方式（例如：某类操作前必须先确认）
- Boss 表达不满或纠正 agent 行为的情况，以及正确做法是什么
- Boss 的偏好和习惯（例如：沟通风格、汇报方式、工具选择）

**输出要求：**
- 每条经验用独立的自然语言段落描述，直接表述结论和规范，便于日后快速检索
- 忽略流水账操作（如"执行了 git pull"、"切换了分支"）
- 忽略未完成的事项，只记录已确认的结论和规范
- 如果日记内容不涉及某个维度，该维度可以不输出
"""


# ─── Step 1: Digest Yesterday Diary ───

def digest_yesterday(agent_id: str, workspace: Path):
    """读取昨日日记 → POST mem0.add(infer=True, custom_extraction_prompt) → 长期记忆"""
    yesterday = get_utc_yesterday()
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
        "custom_extraction_prompt": DIARY_EXTRACTION_PROMPT,
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


# ─── Step 3: Long-Term Memory Consolidation ───

def _load_consolidation_offset() -> dict:
    if CONSOLIDATION_OFFSET_FILE.exists():
        try:
            return json.loads(CONSOLIDATION_OFFSET_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_consolidation_offset(offsets: dict):
    CONSOLIDATION_OFFSET_FILE.write_text(json.dumps(offsets, indent=2), encoding="utf-8")


def consolidate_longterm_memories(agent_id: str) -> int:
    """Step 3: 扫描本批次长期记忆，找冗余对，用 mem0 infer=True 合并。返回合并对数。"""
    # 拉取全量长期记忆
    resp = requests.get(f"{BASE_URL}/memory/list", params={
        "user_id": USER_ID, "agent_id": agent_id, "limit": 10000
    }, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    all_memories = data.get("results", data) if isinstance(data, dict) else data
    if isinstance(all_memories, dict) and "results" in all_memories:
        all_memories = all_memories["results"]
    if not isinstance(all_memories, list) or not all_memories:
        logger.info(f"[{agent_id}] No long-term memories for consolidation")
        return 0

    # offset 轮转
    offsets = _load_consolidation_offset()
    offset = offsets.get(agent_id, 0)
    total = len(all_memories)
    if offset >= total:
        offset = 0
    batch = all_memories[offset:offset + CONSOLIDATION_BATCH]
    new_offset = offset + CONSOLIDATION_BATCH
    offsets[agent_id] = 0 if new_offset >= total else new_offset
    _save_consolidation_offset(offsets)

    logger.info(f"[{agent_id}] Step 3: scanning batch offset={offset}, size={len(batch)}, total={total}")

    # 候选对识别
    paired_ids = set()
    candidates = []
    for m in batch:
        mid = m.get("id")
        text = m.get("memory", "")
        if not mid or not text or mid in paired_ids:
            continue
        try:
            sr = requests.post(f"{BASE_URL}/memory/search", json={
                "query": text, "user_id": USER_ID, "agent_id": agent_id,
                "top_k": 3, "time_decay": False
            }, timeout=30)
            sr.raise_for_status()
            sr_data = sr.json()
            hits = sr_data.get("results", {})
            if isinstance(hits, dict):
                hits = hits.get("results", [])
        except Exception as e:
            logger.warning(f"[{agent_id}] Search failed for {mid}: {e}")
            continue

        for hit in hits:
            hid = hit.get("id")
            if hid == mid or hid in paired_ids:
                continue
            if hit.get("score", 0) > CONSOLIDATION_THRESHOLD:
                candidates.append((m, hit))
                paired_ids.add(mid)
                paired_ids.add(hid)
            break  # 只看排名第一

    logger.info(f"[{agent_id}] Step 3: found {len(candidates)} candidate pairs")

    # LLM 合并
    merged = 0
    for m1, m2 in candidates:
        combined = f"{m1['memory']}\n{m2['memory']}"
        try:
            ar = requests.post(f"{BASE_URL}/memory/add", json={
                "user_id": USER_ID, "agent_id": agent_id,
                "text": combined, "infer": True,
                "metadata": {"source": "auto_dream_consolidation"}
            }, timeout=120)
            ar.raise_for_status()
            result = ar.json()
            events = result.get("results", result) if isinstance(result, dict) else result
            if isinstance(events, dict) and "results" in events:
                events = events["results"]
            events = events if isinstance(events, list) else [events] if isinstance(events, dict) else []
            actions = {e.get("event") for e in events if isinstance(e, dict)}
            if actions & {"ADD", "UPDATE"}:
                delete_memory(m1["id"])
                delete_memory(m2["id"])
                merged += 1
                logger.info(f"[{agent_id}] Merged: [{m1['memory'][:40]}...] + [{m2['memory'][:40]}...]")
            else:
                logger.info(f"[{agent_id}] Skipped (NONE): [{m1['memory'][:40]}...]")
        except Exception as e:
            logger.warning(f"[{agent_id}] Merge failed: {e}")
        time.sleep(INTER_MEMORY_SLEEP)

    logger.info(f"[{agent_id}] Step 3 complete: merged {merged} pairs")
    return merged


# ─── Main ───

def main():
    logger.info("=" * 80)
    logger.info("Starting auto_dream.py (AutoDream consolidation)")

    tz_utc = timezone.utc
    today = datetime.now(tz_utc).date()
    target_date = today - timedelta(days=ARCHIVE_DAYS)
    target_run_id = target_date.strftime("%Y-%m-%d")

    logger.info(f"UTC date: {today}")
    logger.info(f"Target run_id for consolidation: {target_run_id}")

    workspaces = load_agent_workspaces()
    logger.info(f"Discovered {len(workspaces)} agents: {list(workspaces.keys())}")

    total_consolidated = 0
    total_merged = 0

    for agent_id, workspace in sorted(workspaces.items()):
        try:
            # Step 1: digest yesterday diary → long-term memory
            digest_yesterday(agent_id, workspace)
            # Step 2: consolidate 7-day-old short-term → long-term, then delete
            total_consolidated += consolidate_old_memories(agent_id, target_run_id)
        except Exception as e:
            logger.error(f"[{agent_id}] Fatal error: {e}", exc_info=True)
        # Step 3: long-term memory consolidation (non-fatal)
        try:
            total_merged += consolidate_longterm_memories(agent_id)
        except Exception as e:
            logger.warning(f"[{agent_id}] Step 3 consolidation failed (non-fatal): {e}", exc_info=True)

    logger.info(f"\nAutoDream complete: consolidated {total_consolidated} memories, merged {total_merged} pairs")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)
