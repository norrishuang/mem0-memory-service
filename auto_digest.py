#!/usr/bin/env python3
"""
auto_digest.py - 自动从日记文件提取短期记忆

每小时由 cron 调用，读取今天的日记文件，提取过去1小时内新增的内容，
用 LLM 抽取关键短期事件，写入 mem0（带 run_id=YYYY-MM-DD）。
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

import boto3
import requests

# ─── Configuration ───

# 优先读环境变量 OPENCLAW_HOME，其次 ~/.openclaw
WORKSPACE_BASE = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))

def discover_agents() -> List[tuple]:
    """动态发现所有 agent workspace，自动找出有 memory 目录的 agent"""
    dirs = []
    if not WORKSPACE_BASE.exists():
        logger.warning(f"Workspace base does not exist: {WORKSPACE_BASE}")
        return dirs
    
    for workspace_dir in WORKSPACE_BASE.glob("workspace-*"):
        # workspace-{agent_name} -> agent_name
        agent_id = workspace_dir.name.replace("workspace-", "")
        memory_dir = workspace_dir / "memory"
        
        if memory_dir.exists() and memory_dir.is_dir():
            dirs.append((memory_dir, agent_id))
            logger.info(f"Discovered agent: {agent_id} (memory: {memory_dir})")
        else:
            logger.debug(f"Skipping {workspace_dir.name}: no memory directory")
    
    return dirs

# DIARY_DIRS 延迟初始化（在 main 中调用）
# STATE_FILE = Path(__file__).parent / ".digest_state.json"
LOG_FILE = Path(__file__).parent / "auto_digest.log"
STATE_FILE = Path(__file__).parent / ".digest_state.json"  # 移到这里，在 logger 之后
MEM0_API_URL = "http://127.0.0.1:8230/memory/add"
BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
AWS_REGION = "us-east-1"

# LLM prompt for extracting short-term events
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


# ─── Core Functions ───

def get_beijing_date() -> str:
    """Get current date in Beijing timezone (UTC+8)."""
    utc_now = datetime.utcnow()
    beijing_now = utc_now + timedelta(hours=8)
    return beijing_now.strftime("%Y-%m-%d")


def load_state() -> Dict[str, int]:
    """Load processing state from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state file: {e}. Starting fresh.")
    return {}


def save_state(state: Dict[str, int]):
    """Save processing state to file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def read_new_content(file_path: Path, last_offset: int) -> Optional[str]:
    """Read new content from diary file starting from last_offset."""
    if not file_path.exists():
        logger.info(f"Diary file does not exist: {file_path}")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            f.seek(last_offset)
            new_content = f.read()
            current_offset = f.tell()

        if current_offset == last_offset:
            logger.info(f"No new content in {file_path.name}")
            return None

        logger.info(f"Read {len(new_content)} bytes of new content from {file_path.name} (offset {last_offset} -> {current_offset})")
        return new_content
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return None


def call_llm_extract(content: str) -> Optional[List[str]]:
    """Call AWS Bedrock LLM to extract short-term events."""
    try:
        bedrock = boto3.client(
            service_name='bedrock-runtime',
            region_name=AWS_REGION
        )

        prompt = EXTRACT_PROMPT.format(content=content)

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "temperature": 0.3,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        response = bedrock.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(request_body)
        )

        response_body = json.loads(response['body'].read())
        extracted_text = response_body['content'][0]['text'].strip()

        if extracted_text == "NO_EVENTS":
            logger.info("LLM returned NO_EVENTS - no short-term events to record")
            return None

        # Split by lines and filter empty lines
        events = [line.strip() for line in extracted_text.split('\n') if line.strip()]
        logger.info(f"LLM extracted {len(events)} events")
        return events

    except Exception as e:
        logger.error(f"Error calling LLM: {e}", exc_info=True)
        return None


def write_to_mem0(event: str, digest_date: str, agent_id: str = "dev") -> bool:
    """Write a single event to mem0 via HTTP API with run_id."""
    try:
        payload = {
            "user_id": "boss",
            "agent_id": agent_id,
            "run_id": digest_date,  # Use date as run_id for short-term memory
            "text": event,
            "metadata": {
                "category": "short_term",
                "source": "auto_digest",
                "digest_date": digest_date,
                "workspace_agent": agent_id
            }
        }

        response = requests.post(MEM0_API_URL, json=payload, timeout=10)
        response.raise_for_status()

        logger.info(f"✓ Wrote to mem0: {event[:80]}...")
        return True

    except Exception as e:
        logger.error(f"✗ Failed to write to mem0: {event[:80]}... | Error: {e}")
        return False


def process_diary_file(file_path: Path, state: Dict[str, int], digest_date: str, agent_id: str = "dev"):
    """Process a single diary file."""
    file_key = str(file_path)
    last_offset = state.get(file_key, 0)

    # Read new content
    new_content = read_new_content(file_path, last_offset)
    if not new_content:
        return

    # Extract events using LLM
    events = call_llm_extract(new_content)
    if not events:
        # Even if no events, update offset to avoid reprocessing
        state[file_key] = file_path.stat().st_size
        return

    # Write each event to mem0
    success_count = 0
    for event in events:
        if write_to_mem0(event, digest_date, agent_id):
            success_count += 1

    logger.info(f"Successfully wrote {success_count}/{len(events)} events to mem0 (agent: {agent_id})")

    # Update state with current file size
    state[file_key] = file_path.stat().st_size


def main():
    """Main entry point."""
    logger.info("=" * 80)
    logger.info("Starting auto_digest.py")

    # 动态发现所有 agent workspace
    diary_dirs = discover_agents()
    for diary_dir, agent in diary_dirs:
        logger.info(f"Found diary directory: {diary_dir} (agent: {agent})")

    # Get current date in Beijing timezone
    today = get_beijing_date()
    logger.info(f"Beijing date: {today}")

    # Load state
    state = load_state()

    # Check today's diary file in all workspaces
    yesterday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    files_to_process = []
    for diary_dir, agent in diary_dirs:
        # Check today's file
        today_file = diary_dir / f"{today}.md"
        yesterday_file = diary_dir / f"{yesterday}.md"

        if yesterday_file.exists():
            files_to_process.append((yesterday_file, agent))
            logger.info(f"Found yesterday's file: {yesterday_file} (agent: {agent})")
        if today_file.exists():
            files_to_process.append((today_file, agent))
            logger.info(f"Found today's file: {today_file} (agent: {agent})")

    if not files_to_process:
        logger.info("No diary files to process")
        return

    for file_path, agent_id in files_to_process:
        process_diary_file(file_path, state, today, agent_id)

    # Save state
    save_state(state)

    logger.info("Auto digest completed")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)
