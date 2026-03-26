#!/usr/bin/env python3
"""
session_snapshot.py - 实时保存当前活跃 session 的对话到 memory 文件

解决痛点：session 压缩时对话内容丢失
解决思路：直接读取 session jsonl 文件，定期保存到日记

优化：过滤噪音内容，只记录用户消息和最终 AI 响应

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
WORKSPACE_BASE = Path("/home/ec2-user/.openclaw/")
DEFAULT_AGENT = "dev"
SESSION_STORE = WORKSPACE_BASE / "agents" / DEFAULT_AGENT / "sessions" / "sessions.json"

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
    
    # 跳过太短的
    if len(text) < 15:
        return True
    
    # 跳过包含 heartbeat 的消息（自动触发的检查）
    if 'heartbeat' in text.lower() and 'HEARTBEAT.md' not in text:
        return True
    
    # 跳过各种噪音模式
    if NOISE_REGEX.search(text):
        # 例外：仍然保留用户实际消息
        # 用户消息通常包含实际对话内容
        if text.startswith('黄霄') or text.startswith('Boss:'):
            return False
        return True
    
    # 跳过命令行提示符输出
    if text.startswith('$ ') or text.startswith('> '):
        return True
    
    return False


def clean_content(text: str) -> str:
    """清理内容"""
    # 移除多余的空白
    text = re.sub(r'\s+', ' ', text)
    
    # 截断太长的
    if len(text) > 500:
        text = text[:500] + '...'
    
    return text.strip()


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


def extract_user_message(text: str) -> str | None:
    """从用户消息中提取实际对话内容"""
    # 如果消息包含 "msg:" 之后的内容，提取出来
    if 'msg:' in text:
        # 找到最后一个 msg: 之后的内容
        idx = text.rfind('msg:')
        content = text[idx + 4:]
        # 去掉前面的 [ 和其他标记
        content = re.sub(r'^\[[^\]]+\]\s*', '', content)
        if len(content) > 20:
            return content
    
    # 否则返回原始文本，但移除 System: 等前缀
    text = re.sub(r'^System:.*?\【.*?】', '', text)
    text = re.sub(r'^\[.*?\]\s*', '', text)
    
    return text if len(text) > 20 else None


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
                    
                    if not text:
                        continue
                    
                    # 过滤噪音
                    if is_noise(text):
                        # 用户消息例外处理
                        if role == 'user':
                            extracted = extract_user_message(text)
                            if extracted:
                                messages.append({
                                    'role': role,
                                    'content': clean_content(extracted)
                                })
                        continue
                    
                    # 清理并保存
                    if role == 'user':
                        extracted = extract_user_message(text)
                        content = clean_content(extracted) if extracted else clean_content(text)
                    else:
                        content = clean_content(text)
                    
                    if content and len(content) > 15:
                        messages.append({
                            'role': role,
                            'content': content
                        })
            except json.JSONDecodeError:
                continue
        
        return messages
    except Exception as e:
        logger.error(f"Failed to read session: {e}")
        return []


def write_to_memory(messages: list, path: Path) -> int:
    """写入 session 消息到 memory 文件"""
    if not messages:
        return 0
    
    init_memory_file(path)
    
    now = datetime.now()
    time_marker = now.strftime("%H:%M")
    
    # 构建新内容
    new_content = f"\n### [{time_marker}] Session snapshot\n"
    
    # 去重：检查与最后一条是否相同
    try:
        existing = path.read_text(encoding='utf-8')
        last_lines = existing.split('\n')[-20:]
        last_text = '\n'.join(last_lines)
    except:
        last_text = ""
    
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        
        # 人类消息显示为 Boss，AI 显示为 Dev
        label = "Boss" if role == "user" else "Dev"
        
        new_content += f"- {label}: {content}\n"
    
    # 检查去重
    if new_content in last_text:
        logger.debug("No new messages to write")
        return 0
    
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