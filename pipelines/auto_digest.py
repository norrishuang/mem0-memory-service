#!/usr/bin/env python3
"""
auto_digest.py - 自动从日记文件提取短期记忆

两种模式：
  默认模式：每天 UTC 01:30 运行，读取 UTC 昨天的完整日记，分批 POST 给 mem0（infer=True，由 mem0 内部做 fact extraction）
  --today 模式：每 15 分钟增量运行，读取今天日记的新增部分，分批 POST 给 mem0（由 mem0 内部做 fact extraction）
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── Configuration ───

WORKSPACE_BASE = Path(os.environ.get("OPENCLAW_BASE",
                      os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")))
OPENCLAW_CONFIG = WORKSPACE_BASE / "openclaw.json"

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent))

LOG_FILE = DATA_DIR / "auto_digest.log"
OFFSET_FILE = DATA_DIR / "auto_digest_offset.json"
_raw_url = os.environ.get("MEM0_API_URL", "http://127.0.0.1:8230")
MEM0_BASE_URL = _raw_url.removesuffix("/memory/add").removesuffix("/")
MEM0_API_URL = f"{MEM0_BASE_URL}/memory/add"
MIN_CONTENT_BYTES = 500   # 新增内容少于此值则跳过（避免无意义的小更新）
BATCH_SIZE_BYTES = 50000  # 每批读取的字节数（50KB）
BATCH_SLEEP_SECS = 5      # 批次间 sleep，避免打爆 mem0

# ─── Setup Logging ───

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # cron >> /app/data/auto_digest.log handles file writing
    ]
)
logger = logging.getLogger(__name__)


# ─── Agent Discovery ───

def load_agent_workspaces() -> dict:
    """从 openclaw.json 读取每个 agent 的 workspace 路径，兜底扫描目录"""
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
                        remapped = Path(str(WORKSPACE_BASE) + ws_str[len(host_prefix):])
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
            logger.debug(f"Loaded {len(mapping)} agent workspaces from openclaw.json")
        except Exception as e:
            logger.warning(f"Failed to parse openclaw.json: {e}, falling back to directory scan")

    if not mapping:
        for ws_dir in sorted(WORKSPACE_BASE.glob("workspace-*")):
            agent_id = ws_dir.name.replace("workspace-", "")
            mapping[agent_id] = ws_dir

    return mapping


def get_utc_yesterday() -> str:
    """获取 UTC 昨天的日期字符串"""
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")


def get_utc_today() -> str:
    """获取 UTC 今天的日期字符串"""
    return datetime.utcnow().strftime("%Y-%m-%d")


# ─── Offset Management (for incremental mode) ───

def load_offsets() -> dict:
    """加载 offset 记录文件"""
    if OFFSET_FILE.exists():
        try:
            return json.loads(OFFSET_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"Failed to load offset file: {e}, starting fresh")
    return {}


def save_offsets(offsets: dict):
    """保存 offset 记录文件"""
    try:
        OFFSET_FILE.write_text(json.dumps(offsets, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to save offset file: {e}")


# ─── Core Functions ───


def write_to_mem0(event: str, run_id: str, agent_id: str, incremental: bool = False) -> bool:
    """写入单条事件到 mem0"""
    try:
        metadata = {
            "category": "short_term",
            "source": "auto_digest",
            "digest_date": run_id,
            "workspace_agent": agent_id
        }

        resp = requests.post(MEM0_API_URL, json={
            "user_id": "boss",
            "agent_id": agent_id,
            "run_id": run_id,
            "text": event,
            "infer": True,
            "metadata": metadata
        }, timeout=30)
        resp.raise_for_status()
        logger.info(f"✓ Wrote to mem0: {event[:80]}...")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to write to mem0: {event[:80]}... | Error: {e}")
        return False




def process_agent(agent_id: str, workspace: Path, date: str, incremental: bool = False,
                  offsets: dict | None = None) -> dict:
    """处理单个 agent 的日记

    incremental=False: 读取整个日记文件，LLM 提炼后写 mem0（昨日全量模式）
    incremental=True:  从 offset 开始分批读取（每批 50KB），逐批 POST 给 mem0，
                       批次间 sleep 避免打爆服务。处理完更新 offset，下次只读新增。
    Batches are aligned to '## ' section boundaries to avoid cutting context mid-paragraph.

    Returns a stats dict: {status, new_bytes, memories_added, batches_sent}
    """
    import time

    diary_file = workspace / "memory" / f"{date}.md"
    if not diary_file.exists():
        logger.debug(f"[{agent_id}] No diary for {date}")
        return {"status": "no_diary", "new_bytes": 0, "memories_added": 0, "batches_sent": 0}

    file_size = diary_file.stat().st_size

    if incremental:
        agent_offsets = offsets.setdefault(agent_id, {})
        prev_offset = agent_offsets.get(date, 0)

        total_new = file_size - prev_offset
        if total_new <= 0:
            logger.debug(f"[{agent_id}] No new content (offset={prev_offset})")
            return {"status": "skipped", "new_bytes": 0, "memories_added": 0, "batches_sent": 0}

        if total_new < MIN_CONTENT_BYTES:
            logger.info(f"[{agent_id}] New content too small ({total_new} bytes < {MIN_CONTENT_BYTES}), skipping")
            return {"status": "too_small", "new_bytes": total_new, "memories_added": 0, "batches_sent": 0}

        logger.info(f"[{agent_id}] Incremental: {total_new} new bytes to process in batches of {BATCH_SIZE_BYTES}B")

        current_offset = prev_offset
        batch_num = 0
        batches_sent = 0
        batches_failed = 0
        total_batches = (total_new + BATCH_SIZE_BYTES - 1) // BATCH_SIZE_BYTES

        with open(diary_file, 'rb') as f:
            while current_offset < file_size:
                f.seek(current_offset)
                raw = f.read(BATCH_SIZE_BYTES)
                if not raw:
                    break

                # Align to next section boundary "\n## " to avoid cutting context mid-paragraph
                lookahead_raw = f.read(4096)
                cut = lookahead_raw.find(b'\n## ')
                if cut >= 0:
                    raw = raw + lookahead_raw[:cut + 1]
                else:
                    raw = raw + lookahead_raw

                batch_content = raw.decode("utf-8", errors="replace")
                next_offset = current_offset + len(raw)
                batch_num += 1

                logger.info(f"[{agent_id}] Batch {batch_num}/{total_batches}: "
                            f"offset {current_offset} -> {next_offset} ({len(raw)} bytes, section-aligned)")

                if batch_content.strip():
                    ok = write_to_mem0(batch_content, date, agent_id, incremental=True)
                    if ok:
                        batches_sent += 1
                        # 每批成功后立即更新 offset，下次可从断点续传
                        current_offset = next_offset
                        agent_offsets[date] = current_offset
                        save_offsets(offsets)
                    else:
                        batches_failed += 1
                        logger.warning(f"[{agent_id}] Batch {batch_num} failed, stopping to retry next run")
                        break
                else:
                    current_offset = next_offset
                    agent_offsets[date] = current_offset

                if current_offset < file_size:
                    time.sleep(BATCH_SLEEP_SECS)

        logger.info(f"[{agent_id}] Done: processed up to offset {agent_offsets.get(date, prev_offset)}/{file_size}")
        status = "failed" if batches_failed > 0 and batches_sent == 0 else "ok"
        return {"status": status, "new_bytes": total_new, "memories_added": 0, "batches_sent": batches_sent}

    else:
        # 全量模式：读取整个文件，分批直接 POST 给 mem0（infer=True，由 mem0 内部做 fact extraction）
        content = diary_file.read_text(encoding='utf-8')
        logger.info(f"[{agent_id}] Full mode: processing diary for {date} ({file_size} bytes)")

        if not content.strip():
            logger.info(f"[{agent_id}] Content is empty, skipping")
            return {"status": "skipped", "new_bytes": 0, "memories_added": 0, "batches_sent": 0}

        content_bytes = content.encode('utf-8')
        batches_sent = 0
        batches_failed = 0
        offset = 0
        while offset < len(content_bytes):
            chunk = content_bytes[offset:offset + BATCH_SIZE_BYTES].decode('utf-8', errors='replace')
            if write_to_mem0(chunk, date, agent_id, incremental=False):
                batches_sent += 1
            else:
                batches_failed += 1
            offset += BATCH_SIZE_BYTES
            if offset < len(content_bytes):
                time.sleep(BATCH_SLEEP_SECS)

        logger.info(f"[{agent_id}] Full mode done: {batches_sent} batches sent, {batches_failed} failed")
        status = "failed" if batches_failed > 0 and batches_sent == 0 else "ok"
        return {"status": status, "new_bytes": file_size, "memories_added": 0, "batches_sent": batches_sent}


def _log_run_summary(results: list[tuple[str, dict]], elapsed: float):
    """打印本次运行的汇总统计日志"""
    total_memories = 0
    agents_processed = 0

    for agent_id, stats in results:
        s = stats["status"]
        if s in ("ok", "failed"):
            agents_processed += 1
            mem_count = stats["memories_added"] or stats["batches_sent"]
            total_memories += mem_count
            extra = f"新内容 {stats['new_bytes']} bytes"
            if s == "failed":
                extra += "，mem0 写入失败"
            logger.info(f"[{agent_id}] 新增 {mem_count} 条记忆（{extra}）")
        elif s == "no_diary":
            logger.debug(f"[{agent_id}] 无日记，跳过")
        else:
            logger.debug(f"[{agent_id}] 无新内容，跳过")

    logger.info(f"--- 本次合计: 处理 {agents_processed} 个 agent，"
                f"新增 {total_memories} 条记忆，耗时 {int(elapsed)}s ---")


def main():
    import time as _time

    parser = argparse.ArgumentParser(description="auto_digest: extract memories from diary")
    parser.add_argument("--today", action="store_true",
                        help="Incremental mode: process today's diary (run every 15 min)")
    args = parser.parse_args()

    logger.info("=" * 80)

    workspaces = load_agent_workspaces()
    logger.info(f"Discovered {len(workspaces)} agents: {list(workspaces.keys())}")

    t0 = _time.monotonic()
    results: list[tuple[str, dict]] = []

    if args.today:
        # 今日增量模式
        today = get_utc_today()
        logger.info(f"Starting auto_digest.py --today (incremental, date={today})")
        offsets = load_offsets()

        for agent_id, workspace in sorted(workspaces.items()):
            try:
                stats = process_agent(agent_id, workspace, today, incremental=True, offsets=offsets)
            except Exception as e:
                logger.error(f"[{agent_id}] Error: {e}", exc_info=True)
                stats = {"status": "failed", "new_bytes": 0, "memories_added": 0, "batches_sent": 0}
            results.append((agent_id, stats))

        save_offsets(offsets)
        logger.info("Incremental digest completed")
    else:
        # 昨日全量模式（原有逻辑）
        yesterday = get_utc_yesterday()
        logger.info(f"Starting auto_digest.py (full mode, date={yesterday})")

        for agent_id, workspace in sorted(workspaces.items()):
            try:
                stats = process_agent(agent_id, workspace, yesterday, incremental=False)
            except Exception as e:
                logger.error(f"[{agent_id}] Error: {e}", exc_info=True)
                stats = {"status": "failed", "new_bytes": 0, "memories_added": 0, "batches_sent": 0}
            results.append((agent_id, stats))

        logger.info("Full digest completed")

    _log_run_summary(results, _time.monotonic() - t0)
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
