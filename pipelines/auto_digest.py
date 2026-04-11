#!/usr/bin/env python3
"""
auto_digest.py - 自动从日记文件提取短期记忆

两种模式：
  默认模式：每天 UTC 01:30 运行，读取 UTC 昨天的完整日记，分批 POST 给 mem0（infer=True，由 mem0 内部做 fact extraction 提炼为简洁事实）
  --today 模式：每 15 分钟增量运行，读取今天日记的新增部分，分批 POST 给 mem0（由 mem0 内部做 fact extraction）
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
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
MIN_CONTENT_BYTES = 5000   # 新增内容少于此值则跳过（避免无意义的小更新）
MAX_BLOCK_BYTES = 100 * 1024  # Max bytes per session block before sub-splitting (100KB)
BATCH_SIZE_BYTES = MAX_BLOCK_BYTES  # Legacy alias — only used as fallback for oversized blocks
BATCH_SLEEP_SECS = 5      # 批次间 sleep，避免打爆 mem0

# ─── Task Extraction ───
TASK_EXTRACTION_ENABLED = os.environ.get("DIGEST_TASK_EXTRACTION", "true").lower() == "true"

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
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def get_utc_today() -> str:
    """获取 UTC 今天的日期字符串"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_TS_RE = re.compile(r'(?:###?\s+\[?(\d{1,2}:\d{2})\]?|##\s+(\d{1,2}:\d{2}))')


def _is_stale_batch(content: str, date: str) -> bool:
    """返回 True 表示批次内所有时间戳均早于当前北京时间（UTC+8），应跳过。
    若无法提取时间戳则返回 False（正常处理）。
    """
    matches = _TS_RE.findall(content)
    times = [t1 or t2 for t1, t2 in matches]
    if not times:
        return False

    now_bj = datetime.now(timezone(timedelta(hours=8)))
    current_hm = now_bj.hour * 60 + now_bj.minute

    for t in times:
        h, m = map(int, t.split(":"))
        if h * 60 + m >= current_hm:
            return False
    return True


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
        }, timeout=120)
        resp.raise_for_status()
        logger.info(f"✓ Wrote to mem0: {event[:80]}...")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to write to mem0: {event[:80]}... | Error: {e}")
        return False




TASK_EXTRACTION_PROMPT = (
    "从以下对话日记中列出agent实际完成的工作任务（最终成果），每行一条，"
    "格式：[类型] 描述。类型：开发/修复/文档/配置/分析/部署/其他。"
    "要求：只写最终成果不写步骤，不超过5条，每条不超过60字，没有任务只写'无'，直接输出列表不要分析。"
)


def extract_and_write_task_memories(block: str, run_id: str, agent_id: str) -> int:
    """通过 /memory/add + custom_extraction_prompt 提炼并写入任务记忆（category=task）。
    返回成功写入数量（0 表示无任务或失败）。
    """
    if not TASK_EXTRACTION_ENABLED:
        return 0
    try:
        metadata = {
            "category": "task",
            "source": "auto_digest_task",
            "digest_date": run_id,
            "workspace_agent": agent_id,
        }
        resp = requests.post(MEM0_API_URL, json={
            "user_id": "boss",
            "agent_id": agent_id,
            "run_id": run_id,
            "text": block[:3000],
            "infer": True,
            "metadata": metadata,
            "custom_extraction_prompt": TASK_EXTRACTION_PROMPT,
        }, timeout=120)
        resp.raise_for_status()
        result = resp.json().get("result", {})
        written = len([r for r in result.get("results", []) if r.get("event") in ("ADD", "UPDATE")])
        if written:
            logger.info(f"[{agent_id}] ✓ Task extraction: {written} task memories written")
        else:
            logger.debug(f"[{agent_id}] Task extraction: no new tasks from this block")
        return written
    except Exception as e:
        logger.warning(f"[{agent_id}] Task extraction failed: {e}")
        return 0


def split_into_session_blocks(content: str) -> list[str]:
    """Split diary content by '### [HH:MM]' session time markers.

    Each returned block starts with '### ['. If a single block exceeds
    MAX_BLOCK_BYTES, it is sub-split at paragraph boundaries ('\\n\\n').
    """
    parts = re.split(r'(?=\n### \[)', content)
    blocks: list[str] = []
    for p in parts:
        stripped = p.strip()
        if not stripped:
            continue
        # Ensure block starts with the marker (first part may be preamble text)
        if not stripped.startswith('### [') and blocks:
            # Preamble before first marker — prepend to nothing, keep as own block
            pass
        encoded = stripped.encode('utf-8')
        if len(encoded) <= MAX_BLOCK_BYTES:
            blocks.append(stripped)
        else:
            # Sub-split oversized block at paragraph boundaries
            sub_parts = stripped.split('\n\n')
            chunk = sub_parts[0]
            for sp in sub_parts[1:]:
                candidate = chunk + '\n\n' + sp
                if len(candidate.encode('utf-8')) > MAX_BLOCK_BYTES:
                    if chunk.strip():
                        blocks.append(chunk.strip())
                    chunk = sp
                else:
                    chunk = candidate
            if chunk.strip():
                blocks.append(chunk.strip())
    return blocks


def process_agent(agent_id: str, workspace: Path, date: str, incremental: bool = False,
                  offsets: dict | None = None) -> dict:
    """处理单个 agent 的日记

    incremental=False: 读取整个日记文件，按 ### [HH:MM] session blocks 分批 POST 给 mem0
    incremental=True:  从 offset 开始读取新增内容，按 session blocks 逐批 POST 给 mem0

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

        # Read all new content and split by session blocks
        # Use binary mode + manual UTF-8 boundary alignment to avoid
        # UnicodeDecodeError when prev_offset lands mid-character (#125)
        with open(diary_file, 'rb') as f:
            f.seek(prev_offset)
            raw = f.read()
        # Align to valid UTF-8 start byte (skip continuation bytes 0x80-0xBF)
        skip = 0
        while skip < len(raw) and (raw[skip] & 0xC0) == 0x80:
            skip += 1
        if skip:
            logger.warning(f"[{agent_id}] offset {prev_offset} landed mid-char, skipped {skip} bytes to align")
        new_content = raw[skip:].decode('utf-8', errors='replace')

        blocks = split_into_session_blocks(new_content)
        logger.info(f"[{agent_id}] Incremental: {total_new} new bytes, {len(blocks)} session blocks")

        batches_sent = 0
        batches_failed = 0
        cumulative_bytes = 0

        for i, block in enumerate(blocks):
            block_bytes = len(block.encode('utf-8'))

            if _is_stale_batch(block, date):
                logger.info(f"[{agent_id}] Block {i+1}/{len(blocks)}: skipped (stale)")
                cumulative_bytes += block_bytes
                agent_offsets[date] = prev_offset + cumulative_bytes
                save_offsets(offsets)
            elif block.strip():
                ok = write_to_mem0(block, date, agent_id, incremental=True)
                if ok:
                    batches_sent += 1
                    cumulative_bytes += block_bytes
                    agent_offsets[date] = prev_offset + cumulative_bytes
                    save_offsets(offsets)
                    # 任务专项抽取（通过 custom_extraction_prompt，失败不阻塞主流程）
                    extract_and_write_task_memories(block, date, agent_id)
                else:
                    batches_failed += 1
                    logger.warning(f"[{agent_id}] Block {i+1} failed, stopping to retry next run")
                    break
            else:
                cumulative_bytes += block_bytes
                agent_offsets[date] = prev_offset + cumulative_bytes
                save_offsets(offsets)

            if i < len(blocks) - 1:
                time.sleep(BATCH_SLEEP_SECS)

        logger.info(f"[{agent_id}] Done: processed up to offset {agent_offsets.get(date, prev_offset)}/{file_size}")
        status = "failed" if batches_failed > 0 and batches_sent == 0 else "ok"
        return {"status": status, "new_bytes": total_new, "memories_added": 0, "batches_sent": batches_sent}

    else:
        # 全量模式：读取整个文件，按 session blocks 分批 POST 给 mem0
        content = diary_file.read_text(encoding='utf-8')
        logger.info(f"[{agent_id}] Full mode: processing diary for {date} ({file_size} bytes)")

        if not content.strip():
            logger.info(f"[{agent_id}] Content is empty, skipping")
            return {"status": "skipped", "new_bytes": 0, "memories_added": 0, "batches_sent": 0}

        blocks = split_into_session_blocks(content)
        batches_sent = 0
        batches_failed = 0

        for i, block in enumerate(blocks):
            if block.strip():
                if write_to_mem0(block, date, agent_id, incremental=False):
                    batches_sent += 1
                    # 任务专项抽取（通过 custom_extraction_prompt）
                    extract_and_write_task_memories(block, date, agent_id)
                else:
                    batches_failed += 1
            if i < len(blocks) - 1:
                time.sleep(BATCH_SLEEP_SECS)

        logger.info(f"[{agent_id}] Full mode done: {batches_sent} batches sent, {batches_failed} failed")
        status = "failed" if batches_failed > 0 and batches_sent == 0 else "ok"
        return {"status": status, "new_bytes": file_size, "memories_added": 0, "batches_sent": batches_sent}


def _log_run_summary(results: list[tuple[str, dict]], elapsed: float):
    """打印本次运行的汇总统计日志"""
    total_memories = 0
    agents_processed = 0
    elapsed_s = int(elapsed)

    for agent_id, stats in results:
        s = stats["status"]
        if s in ("ok", "failed"):
            agents_processed += 1
            mem_count = stats["memories_added"] or stats["batches_sent"]
            total_memories += mem_count
            suffix = "，mem0 写入失败" if s == "failed" else ""
            logger.info(f"[{agent_id}] 处理日记 {stats['new_bytes']} 字节，新增 {mem_count} 条记忆，耗时 {elapsed_s}s{suffix}")
        elif s == "stale":
            logger.info(f"[{agent_id}] 无新内容，跳过")
        else:
            logger.info(f"[{agent_id}] 无新内容，跳过")

    logger.info(f"--- 本次合计：处理 {agents_processed} 个 agent，新增 {total_memories} 条记忆，耗时 {elapsed_s}s ---")


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
