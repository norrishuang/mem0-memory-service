#!/usr/bin/env python3
"""
session_snapshot.py - 实时保存当前活跃 session 的对话到 memory 文件

解决痛点：session 压缩时对话内容丢失
解决思路：直接读取 session jsonl 文件，定期保存到日记

建议 crontab: 每 15 分钟执行一次
*/15 * * * * /home/ec2-user/workspace/mem0-memory-service/session_snapshot.py >> /var/log/mem0-snapshot.log 2>&1
"""
import os
import json
import logging
from datetime import datetime
from pathlib import Path

# 配置
WORKSPACE_BASE = Path("/home/ec2-user/.openclaw/")
DEFAULT_AGENT = "dev"
SESSION_STORE = WORKSPACE_BASE / "agents" / DEFAULT_AGENT / "sessions" / "sessions.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_today_memory_path(agent_id: str = DEFAULT_AGENT) -> Path:
    """获取今天的日记文件"""
    workspace = WORKSPACE_BASE / f"workspace-{agent_id}"
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    return memory_dir / f"{today}.md"


def init_memory_file(path: Path) -> None:
    """初始化日记文件头"""
    if not path.exists():
        date_str = datetime.now().strftime("%Y-%m-%d")
        content = f"""# {date_str} - Dev Agent 日记

## Session 记录

"""
        path.write_text(content, encoding='utf-8')
        logger.info(f"Created memory file: {path}")


def get_active_session_path() -> Path:
    """获取当前活跃的 session 文件路径"""
    try:
        if not SESSION_STORE.exists():
            logger.debug(f"Session store not found: {SESSION_STORE}")
            return None
        
        with open(SESSION_STORE, 'r') as f:
            data = json.load(f)
        
        # 尝试找 agent:dev:main
        main_key = f"agent:{DEFAULT_AGENT}:main"
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
        logger.debug(f"Failed to get session path: {e}")
        return None


def read_session_messages(session_path: Path, max_lines: int = 100) -> list:
    """读取 session 文件中的消息"""
    try:
        messages = []
        with open(session_path, 'r') as f:
            lines = f.readlines()
        
        # 只取最后 max_lines 行
        for line in lines[-max_lines:]:
            try:
                event = json.loads(line.strip())
                if event.get('type') == 'message':
                    msg = event.get('message', {})
                    role = msg.get('role', 'unknown')
                    content_list = msg.get('content', [])
                    
                    text = ""
                    for c in content_list:
                        if c.get('type') == 'text':
                            text = c.get('text', '')
                            break
                    
                    if text:
                        # 过滤掉太短的（心跳等）和包含 System: 的内部消息
                        if len(text) < 20:
                            continue
                        if text.startswith('System:') or 'heartbeat' in text.lower():
                            # 保留用户实际消息，只过滤掉很短的
                            pass
                        
                        # 提取前 400 字符
                        preview = text[:400].replace('\n', ' ')
                        messages.append({
                            'role': role,
                            'content': preview
                        })
            except json.JSONDecodeError:
                continue
        
        return messages
    except Exception as e:
        logger.error(f"Failed to read session: {e}")
        return []


def get_file_mtime(path: Path) -> float:
    """获取文件修改时间"""
    try:
        return path.stat().st_mtime
    except Exception:
        return 0


def write_to_memory(messages: list, path: Path) -> int:
    """写入 session 消息到 memory 文件"""
    if not messages:
        return 0
    
    init_memory_file(path)
    
    now = datetime.now()
    time_marker = now.strftime("%H:%M")
    
    # 构建新内容
    new_content = f"\n### [{time_marker}] Session snapshot\n"
    
    # 反转顺序，最新的在后面
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        
        # 人类消息显示为 Boss，AI 显示为 Dev
        label = "Boss" if role == "user" else "Dev"
        
        new_content += f"- {label}: {content}\n"
    
    # 检查是否需要写入（简单的去重：如果最后 100 字符相同就不写）
    try:
        existing = path.read_text(encoding='utf-8')
        if new_content in existing[-500:]:
            logger.debug("No new messages to write")
            return 0
    except Exception:
        pass
    
    try:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(new_content)
        logger.info(f"Wrote {len(messages)} messages to {path}")
        return len(messages)
    except Exception as e:
        logger.error(f"Failed to write: {e}")
        return 0


def main():
    """主函数"""
    memory_path = get_today_memory_path()
    session_path = get_active_session_path()
    
    if not session_path:
        logger.debug("No active session found")
        return
    
    messages = read_session_messages(session_path)
    
    if messages:
        written = write_to_memory(messages, memory_path)
        if written > 0:
            logger.info(f"Session snapshot complete: {written} messages written")


if __name__ == "__main__":
    main()