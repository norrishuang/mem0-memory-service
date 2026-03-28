#!/usr/bin/env python3
"""
auto_digest.py - 自动从日记文件提取短期记忆

两种模式：
  默认模式：每天 UTC 01:30 运行，读取北京时间昨天的完整日记，用 LLM 提炼后写入 mem0（run_id=昨天日期）
  --today 模式：每 15 分钟增量运行，读取今天日记的新增部分，直接 POST 给 mem0（由 mem0 内部做 fact extraction）
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import boto3
import requests

# ─── Configuration ───

WORKSPACE_BASE = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
OPENCLAW_CONFIG = WORKSPACE_BASE / "openclaw.json"

LOG_FILE = Path(__file__).parent / "auto_digest.log"
OFFSET_FILE = Path(__file__).parent / "auto_digest_offset.json"
MEM0_API_URL = "http://127.0.0.1:8230/memory/add"
BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
AWS_REGION = "us-east-1"
MIN_CONTENT_BYTES = 500   # 新增内容少于此值则跳过（避免无意义的小更新）
BATCH_SIZE_BYTES = 50000  # 每批读取的字节数（50KB）
BATCH_SLEEP_SECS = 5      # 批次间 sleep，避免打爆 mem0

EXTRACT_PROMPT = """你是一个记忆提取助手。以下是一段工作日记内容，请从中提取今天发生的关键短期事件。

要提取的内容：
- 人与人之间的讨论（谁和谁讨论了什么）
- 任务进展（完成了什么、进行中的什么）
- 临时决策或假设（做了某个决定但还未确定）
- 重要会议或沟通

不需要提取的内容：
- 长期技术方案（已有长期记忆处理）
- 环境配置信息（已有长期记忆处理）
- 已经是明确结论的长期决策

请用简洁的中文输出，每条事件一行，格式：
[事件类型] 具体描述

如果没有值得记录的短期事件，输出：NO_EVENTS

日记内容：
{content}"""

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


# ─── Agent Discovery ───

def load_agent_workspaces() -> dict:
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
        for ws_dir in sorted(WORKSPACE_BASE.glob("workspace-*")):
            agent_id = ws_dir.name.replace("workspace-", "")
            mapping[agent_id] = ws_dir

    return mapping


def get_beijing_yesterday() -> str:
    """获取北京时间昨天的日期字符串"""
    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    yesterday = beijing_now - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def get_beijing_today() -> str:
    """获取北京时间今天的日期字符串"""
    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    return beijing_now.strftime("%Y-%m-%d")


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

def call_llm_extract(content: str) -> list[str] | None:
    """调用 Bedrock LLM 提取短期事件"""
    try:
        bedrock = boto3.client(service_name='bedrock-runtime', region_name=AWS_REGION)
        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2000,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": EXTRACT_PROMPT.format(content=content)}]
            })
        )
        text = json.loads(response['body'].read())['content'][0]['text'].strip()

        if text == "NO_EVENTS":
            logger.info("LLM returned NO_EVENTS")
            return None

        events = [line.strip() for line in text.split('\n') if line.strip()]
        logger.info(f"LLM extracted {len(events)} events")
        return events
    except Exception as e:
        logger.error(f"Error calling LLM: {e}", exc_info=True)
        return None


def write_to_mem0(event: str, run_id: str, agent_id: str, incremental: bool = False) -> bool:
    """写入单条事件到 mem0"""
    try:
        metadata = {
            "category": "short_term",
            "source": "auto_digest",
            "digest_date": run_id,
            "workspace_agent": agent_id
        }
        if incremental:
            metadata["mode"] = "direct"  # 直接写，不经过本地 LLM

        resp = requests.post(MEM0_API_URL, json={
            "user_id": "boss",
            "agent_id": agent_id,
            "run_id": run_id,
            "text": event,
            "metadata": metadata
        }, timeout=30)
        resp.raise_for_status()
        logger.info(f"✓ Wrote to mem0: {event[:80]}...")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to write to mem0: {event[:80]}... | Error: {e}")
        return False




def process_agent(agent_id: str, workspace: Path, date: str, incremental: bool = False,
                  offsets: dict | None = None):
    """处理单个 agent 的日记

    incremental=False: 读取整个日记文件，LLM 提炼后写 mem0（昨日全量模式）
    incremental=True:  从 offset 开始分批读取（每批 50KB），逐批 POST 给 mem0，
                       批次间 sleep 避免打爆服务。处理完更新 offset，下次只读新增。
    """
    import time

    diary_file = workspace / "memory" / f"{date}.md"
    if not diary_file.exists():
        logger.debug(f"[{agent_id}] No diary for {date}")
        return

    file_size = diary_file.stat().st_size

    if incremental:
        agent_offsets = offsets.setdefault(agent_id, {})
        prev_offset = agent_offsets.get(date, 0)

        total_new = file_size - prev_offset
        if total_new <= 0:
            logger.debug(f"[{agent_id}] No new content (offset={prev_offset})")
            return

        if total_new < MIN_CONTENT_BYTES:
            logger.info(f"[{agent_id}] New content too small ({total_new} bytes < {MIN_CONTENT_BYTES}), skipping")
            return

        logger.info(f"[{agent_id}] Incremental: {total_new} new bytes to process in batches of {BATCH_SIZE_BYTES}B")

        current_offset = prev_offset
        batch_num = 0
        total_batches = (total_new + BATCH_SIZE_BYTES - 1) // BATCH_SIZE_BYTES

        with open(diary_file, 'rb') as f:
            while current_offset < file_size:
                f.seek(current_offset)
                raw = f.read(BATCH_SIZE_BYTES)
                if not raw:
                    break

                batch_content = raw.decode('utf-8', errors='replace')
                next_offset = current_offset + len(raw)
                batch_num += 1

                logger.info(f"[{agent_id}] Batch {batch_num}/{total_batches}: "
                            f"offset {current_offset} -> {next_offset} ({len(raw)} bytes)")

                if batch_content.strip():
                    ok = write_to_mem0(batch_content, date, agent_id, incremental=True)
                    if ok:
                        # 每批成功后立即更新 offset，下次可从断点续传
                        current_offset = next_offset
                        agent_offsets[date] = current_offset
                        save_offsets(offsets)
                    else:
                        logger.warning(f"[{agent_id}] Batch {batch_num} failed, stopping to retry next run")
                        break
                else:
                    current_offset = next_offset
                    agent_offsets[date] = current_offset

                if current_offset < file_size:
                    time.sleep(BATCH_SLEEP_SECS)

        logger.info(f"[{agent_id}] Done: processed up to offset {agent_offsets.get(date, prev_offset)}/{file_size}")

    else:
        # 全量模式：读取整个文件，LLM 提炼后写 mem0
        content = diary_file.read_text(encoding='utf-8')
        logger.info(f"[{agent_id}] Full mode: processing diary for {date} ({file_size} bytes)")

        if not content.strip():
            logger.info(f"[{agent_id}] Content is empty, skipping")
            return

        events = call_llm_extract(content)
        if not events:
            return

        success = sum(1 for e in events if write_to_mem0(e, date, agent_id, incremental=False))
        logger.info(f"[{agent_id}] Wrote {success}/{len(events)} events to mem0 (run_id={date})")


def main():
    parser = argparse.ArgumentParser(description="auto_digest: extract memories from diary")
    parser.add_argument("--today", action="store_true",
                        help="Incremental mode: process today's diary (run every 15 min)")
    args = parser.parse_args()

    logger.info("=" * 80)

    workspaces = load_agent_workspaces()
    logger.info(f"Discovered {len(workspaces)} agents: {list(workspaces.keys())}")

    if args.today:
        # 今日增量模式
        today = get_beijing_today()
        logger.info(f"Starting auto_digest.py --today (incremental, date={today})")
        offsets = load_offsets()

        for agent_id, workspace in sorted(workspaces.items()):
            try:
                process_agent(agent_id, workspace, today, incremental=True, offsets=offsets)
            except Exception as e:
                logger.error(f"[{agent_id}] Error: {e}", exc_info=True)

        save_offsets(offsets)
        logger.info("Incremental digest completed")
    else:
        # 昨日全量模式（原有逻辑）
        yesterday = get_beijing_yesterday()
        logger.info(f"Starting auto_digest.py (full mode, date={yesterday})")

        for agent_id, workspace in sorted(workspaces.items()):
            try:
                process_agent(agent_id, workspace, yesterday, incremental=False)
            except Exception as e:
                logger.error(f"[{agent_id}] Error: {e}", exc_info=True)

        logger.info("Full digest completed")

    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
