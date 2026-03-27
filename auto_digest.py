#!/usr/bin/env python3
"""
auto_digest.py - 自动从昨天的日记文件提取短期记忆

每天 UTC 01:30 运行，读取北京时间昨天的完整日记文件，
用 LLM 提炼关键短期事件，写入 mem0（run_id=昨天日期）。
"""
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
MEM0_API_URL = "http://127.0.0.1:8230/memory/add"
BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"
AWS_REGION = "us-east-1"

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


def write_to_mem0(event: str, run_id: str, agent_id: str) -> bool:
    """写入单条事件到 mem0"""
    try:
        resp = requests.post(MEM0_API_URL, json={
            "user_id": "boss",
            "agent_id": agent_id,
            "run_id": run_id,
            "text": event,
            "metadata": {
                "category": "short_term",
                "source": "auto_digest",
                "digest_date": run_id,
                "workspace_agent": agent_id
            }
        }, timeout=10)
        resp.raise_for_status()
        logger.info(f"✓ Wrote to mem0: {event[:80]}...")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to write to mem0: {event[:80]}... | Error: {e}")
        return False


def process_agent(agent_id: str, workspace: Path, yesterday: str):
    """处理单个 agent 昨天的完整日记"""
    diary_file = workspace / "memory" / f"{yesterday}.md"
    if not diary_file.exists():
        logger.debug(f"[{agent_id}] No diary for {yesterday}")
        return

    content = diary_file.read_text(encoding='utf-8')
    if not content.strip():
        logger.info(f"[{agent_id}] Diary for {yesterday} is empty")
        return

    logger.info(f"[{agent_id}] Processing diary for {yesterday} ({len(content)} bytes)")

    events = call_llm_extract(content)
    if not events:
        return

    success = sum(1 for e in events if write_to_mem0(e, yesterday, agent_id))
    logger.info(f"[{agent_id}] Wrote {success}/{len(events)} events to mem0")


def main():
    logger.info("=" * 80)
    logger.info("Starting auto_digest.py")

    yesterday = get_beijing_yesterday()
    logger.info(f"Processing diary for: {yesterday}")

    workspaces = load_agent_workspaces()
    logger.info(f"Discovered {len(workspaces)} agents: {list(workspaces.keys())}")

    for agent_id, workspace in sorted(workspaces.items()):
        try:
            process_agent(agent_id, workspace, yesterday)
        except Exception as e:
            logger.error(f"[{agent_id}] Error: {e}", exc_info=True)

    logger.info("Auto digest completed")
    logger.info("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
