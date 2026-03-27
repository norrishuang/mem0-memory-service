#!/usr/bin/env python3
"""
session_snapshot.py - 实时保存当前活跃 session 的对话到 memory 文件

解决痛点：session 压缩时对话内容丢失
解决思路：直接读取 session jsonl 文件，定期保存到日记

优化：过滤噪音内容，只记录用户消息和最终 AI 响应

方案 A：覆盖所有 agent，每个 agent 的对话写入各自的 workspace memory 目录

建议 crontab: 每 15 分钟执行一次
*/15 * * * * /home/ec2-user/workspace/mem0-memory-service/session_snapshot.py >> /var/log/mem0-snapshot.log 2>&1
"""
import os
import json
import logging
import re
from datetime import datetime
from pathlib import Path

# 配置
# 配置：优先读环境变量 OPENCLAW_HOME，其次 ~/.openclaw
OPENCLAW_BASE = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
AGENTS_DIR = OPENCLAW_BASE / "agents"

# 噪音模式：需要过滤的内容
NOISE_PATTERNS = [
    # OpenClaw 内部消息
    r'^System:',
    r'^\[message_id=',
    r'^Conversation info',
    r'^Sender .untrusted',
    r'^<forwarded_messages>',
    r'^Replied message',
    # 命令行输出
    r'^🦞 OpenClaw',
    r'^Usage: openclaw',
    r'^Commands:',
    r'^Options:',
    r'^  --',
    r'^-{20,}',  # 分隔线
    # JSON/代码格式
    r'^{\s*"',
    r'^\[',
    r'^{"type":',
    r'^<[^>]+>',  # HTML/XML标签
    r'^```',
    r'^ Bous',
    # Python traceback
    r'^Traceback',
    r'^  File ',
    # 日志格式
    r'^\d{4}-\d{2}-\d{2}',
    # 空输出或单行标记
    r'^\(no output\)$',
    r'^{.*error.*}',
    r'^{"success"',
    r'^Successfully',
    r'^Failed',
    r'^Created',
    r'^Command.*exited',
    # 自动触发消息
    r'^HEARTBEAT',
]

NOISE_REGEX = re.compile('|'.join(f'({p})' for p in NOISE_PATTERNS), re.IGNORECASE)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def is_noise(text: str) -> bool:
    """判断是否为噪音内容"""
    text = text.strip()
    if len(text) < 15:
        return True
    if 'heartbeat' in text.lower() and 'HEARTBEAT.md' not in text:
        return True
    if NOISE_REGEX.search(text):
        if text.startswith('黄霄') or text.startswith('Boss:'):
            return False
        return True
    if text.startswith('$ ') or text.startswith('> '):
        return True
    return False


def clean_content(text: str) -> str:
    """清理内容"""
    text = re.sub(r'\s+', ' ', text)
    if len(text) > 500:
        text = text[:500] + '...'
    return text.strip()


def get_today_memory_path(agent_id: str) -> Path:
    """获取今天的日记文件"""
    workspace = OPENCLAW_BASE / f"workspace-{agent_id}"
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return memory_dir / f"{today}.md"


def init_memory_file(path: Path, agent_id: str) -> None:
    """初始化日记文件头"""
    if not path.exists():
        date_str = datetime.now().strftime("%Y-%m-%d")
        label = agent_id.capitalize()
        content = f"""# {date_str} - {label} Agent 日记

## Session 记录

"""
        path.write_text(content, encoding='utf-8')
        logger.info(f"Created memory file: {path}")


def get_active_session_path(agent_id: str) -> Path:
    """获取指定 agent 当前活跃的 session 文件路径"""
    session_store = AGENTS_DIR / agent_id / "sessions" / "sessions.json"
    try:
        if not session_store.exists():
            return None
        with open(session_store, 'r') as f:
            data = json.load(f)

        # 尝试找 agent:{agent_id}:main
        main_key = f"agent:{agent_id}:main"
        session_data = data.get(main_key, {})
        session_file = session_data.get('sessionFile')
        if session_file and Path(session_file).exists():
            return Path(session_file)

        # 备用：遍历所有 key 找最新的
        latest_time = 0
        latest_path = None
        for key, val in data.items():
            if isinstance(val, dict):
                sf = val.get('sessionFile')
                ut = val.get('updatedAt', 0)
                if sf and Path(sf).exists() and ut > latest_time:
                    latest_time = ut
                    latest_path = Path(sf)
        return latest_path
    except Exception as e:
        logger.debug(f"[{agent_id}] Failed to get session path: {e}")
        return None


def extract_user_message(text: str) -> str | None:
    """从用户消息中提取实际对话内容"""
    if 'msg:' in text:
        idx = text.rfind('msg:')
        content = text[idx + 4:]
        content = re.sub(r'^\[[^\]]+\]\s*', '', content)
        if len(content) > 20:
            return content
    text = re.sub(r'^System:.*?\【.*?】', '', text)
    text = re.sub(r'^\[.*?\]\s*', '', text)
    return text if len(text) > 20 else None


def read_session_messages(session_path: Path, max_lines: int = 100) -> list:
    """读取 session 文件中的消息"""
    try:
        messages = []
        with open(session_path, 'r') as f:
            lines = f.readlines()
        for line in lines[-max_lines:]:
            try:
                event = json.loads(line.strip())
                if event.get('type') == 'message':
                    msg = event.get('message', {})
                    role = msg.get('role', 'unknown')
                    content_list = msg.get('content', [])
                    text = ""
                    for c in content_list:
                        if not isinstance(c, dict):
                            if isinstance(c, str) and c.strip():
                                text = c
                            continue
                        if c.get('type') == 'text':
                            text = c.get('text', '')
                            break
                    if not text:
                        continue
                    if is_noise(text):
                        if role == 'user':
                            extracted = extract_user_message(text)
                            if extracted:
                                messages.append({'role': role, 'content': clean_content(extracted)})
                        continue
                    if role == 'user':
                        extracted = extract_user_message(text)
                        content = clean_content(extracted) if extracted else clean_content(text)
                    else:
                        content = clean_content(text)
                    if content and len(content) > 15:
                        messages.append({'role': role, 'content': content})
            except json.JSONDecodeError:
                continue
        return messages
    except Exception as e:
        logger.error(f"Failed to read session: {e}")
        return []


def build_message_lines(messages: list, agent_id: str) -> list[str]:
    """将 messages 转成日记行列表（不含时间戳头部）"""
    lines = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        label = "Boss" if role == "user" else agent_id.capitalize()
        lines.append(f"- {label}: {content}")
    return lines


def write_to_memory(messages: list, path: Path, agent_id: str) -> int:
    """写入 session 消息到 memory 文件，只写入尚未出现过的新消息行"""
    if not messages:
        return 0

    init_memory_file(path, agent_id)

    # 读取已有内容，用于去重
    try:
        existing = path.read_text(encoding='utf-8')
    except:
        existing = ""

    # 过滤掉已经写过的行（不带时间戳，纯内容比较）
    all_lines = build_message_lines(messages, agent_id)
    new_lines = [line for line in all_lines if line not in existing]

    if not new_lines:
        logger.debug(f"[{agent_id}] All messages already recorded, skipping")
        return 0

    time_marker = datetime.now().strftime("%H:%M")
    block = f"\n### [{time_marker}] Session snapshot\n" + "\n".join(new_lines) + "\n"

    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(block)
        logger.info(f"[{agent_id}] Wrote {len(new_lines)} new messages to {path}")
        return len(new_lines)
    except Exception as e:
        logger.error(f"[{agent_id}] Failed to write: {e}")
        return 0


def discover_agents() -> list[str]:
    """扫描所有 agent 目录，返回有对应 workspace 的 agent_id 列表"""
    agents = []
    if not AGENTS_DIR.is_dir():
        return agents
    for entry in sorted(AGENTS_DIR.iterdir()):
        if entry.is_dir():
            agent_id = entry.name
            workspace = OPENCLAW_BASE / f"workspace-{agent_id}"
            if workspace.is_dir():
                agents.append(agent_id)
            else:
                logger.debug(f"[{agent_id}] No workspace directory, skipping")
    return agents


def process_agent(agent_id: str) -> None:
    """处理单个 agent 的 session snapshot"""
    session_path = get_active_session_path(agent_id)
    if not session_path:
        logger.debug(f"[{agent_id}] No active session found")
        return

    messages = read_session_messages(session_path)
    if messages:
        written = write_to_memory(messages, get_today_memory_path(agent_id), agent_id)
        if written > 0:
            logger.info(f"[{agent_id}] Snapshot complete: {written} messages")


def main():
    """主函数：遍历所有 agent 执行 snapshot"""
    agents = discover_agents()
    logger.info(f"Discovered {len(agents)} agents with workspaces: {agents}")

    for agent_id in agents:
        try:
            process_agent(agent_id)
        except Exception as e:
            logger.error(f"[{agent_id}] Error: {e}")


if __name__ == "__main__":
    main()
