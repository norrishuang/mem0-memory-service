#!/usr/bin/env python3
"""
session_snapshot.py - 实时保存当前活跃 session 的对话到 memory 文件

解决痛点：session 压缩时对话内容丢失
解决思路：直接读取 session jsonl 文件，定期保存到日记（增量写入，offset 追踪）

优化：
- 过滤噪音内容，只记录用户消息和最终 AI 响应
- 基于文件 offset 增量读取，永不重复写入旧消息
- 单日日记大小保护（默认 200KB），超限时裁剪保留最新内容
- 写入前文件锁防止并发重复写入

建议 crontab: 每 5 分钟执行一次
*/5 * * * * /home/ec2-user/workspace/mem0-memory-service/session_snapshot.py >> /var/log/mem0-snapshot.log 2>&1
"""
import fcntl
import os
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── 单日日记大小保护 ──────────────────────────────────────────────────────────
# 超过此阈值时，日记文件将被裁剪为只保留最新内容（保留最后 MAX_DIARY_LINES 行）
MAX_DIARY_BYTES = int(os.environ.get("MAX_DIARY_BYTES", 200 * 1024))   # 200 KB
MAX_DIARY_LINES = int(os.environ.get("MAX_DIARY_LINES", 800))           # 裁剪后保留最新 800 行

# 配置：优先读环境变量 OPENCLAW_HOME，其次 ~/.openclaw
OPENCLAW_BASE = Path(os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw"))
AGENTS_DIR = OPENCLAW_BASE / "agents"
OPENCLAW_CONFIG = OPENCLAW_BASE / "openclaw.json"

# mem0 配置
MEM0_API_URL = os.environ.get("MEM0_API_URL", "http://127.0.0.1:8230")
USER_ID = "boss"
BJT = timezone(timedelta(hours=8))
OFFSET_FILE = Path(__file__).parent / ".snapshot_offsets.json"

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


def load_agent_workspaces() -> dict[str, Path]:
    """从 openclaw.json 读取每个 agent 的真实 workspace 路径。

    优先级：
    1. openclaw.json 中明确配置的 workspace（最权威）
    2. 回退：扫描 workspace-{agent_id} 目录（兼容旧部署）
    """
    mapping: dict[str, Path] = {}

    # 方式1：从 openclaw.json 读取
    if OPENCLAW_CONFIG.exists():
        try:
            with open(OPENCLAW_CONFIG) as f:
                config = json.load(f)

            def _extract(obj):
                if isinstance(obj, dict):
                    if 'id' in obj and 'workspace' in obj and isinstance(obj.get('workspace'), str):
                        ws = Path(obj['workspace'])
                        mapping[obj['id']] = ws
                    for v in obj.values():
                        _extract(v)
                elif isinstance(obj, list):
                    for v in obj:
                        _extract(v)

            _extract(config)
            logger.debug(f"Loaded {len(mapping)} agent workspaces from openclaw.json: {list(mapping.keys())}")
        except Exception as e:
            logger.warning(f"Failed to parse openclaw.json: {e}, falling back to directory scan")

    # 方式2：兜底扫描 workspace-* 目录（openclaw.json 没有或解析失败时）
    if not mapping and AGENTS_DIR.is_dir():
        for entry in sorted(AGENTS_DIR.iterdir()):
            if entry.is_dir():
                agent_id = entry.name
                ws = OPENCLAW_BASE / f"workspace-{agent_id}"
                if ws.is_dir():
                    mapping[agent_id] = ws
        logger.debug(f"Fallback scan found {len(mapping)} agents: {list(mapping.keys())}")

    return mapping


# 全局 workspace 映射，启动时加载一次
_AGENT_WORKSPACES: dict[str, Path] = {}


def get_agent_workspace(agent_id: str) -> Path | None:
    """获取指定 agent 的 workspace 路径"""
    return _AGENT_WORKSPACES.get(agent_id)


def get_today_memory_path(agent_id: str) -> Path:
    """获取今天的日记文件路径，自动创建 memory 目录"""
    workspace = get_agent_workspace(agent_id)
    if workspace is None:
        # 兜底
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


def trim_diary_if_oversized(path: Path, agent_id: str) -> bool:
    """日记大小保护：超过 MAX_DIARY_BYTES 时裁剪，只保留最新 MAX_DIARY_LINES 行。

    保留文件头（# 标题 + ## Session 记录 段落），再追加最新 MAX_DIARY_LINES 行。
    返回 True 表示执行了裁剪，False 表示未超限。
    """
    try:
        if not path.exists():
            return False
        size = path.stat().st_size
        if size <= MAX_DIARY_BYTES:
            return False

        logger.warning(
            f"[{agent_id}] Diary {path.name} is {size // 1024}KB (>{MAX_DIARY_BYTES // 1024}KB limit), trimming..."
        )
        content = path.read_text(encoding='utf-8')
        lines = content.splitlines()

        # 提取文件头（前两个 ## 章节之前的内容）
        header_end = 0
        section_count = 0
        for i, line in enumerate(lines):
            if line.startswith('## '):
                section_count += 1
                if section_count >= 2:
                    header_end = i
                    break
        else:
            header_end = min(10, len(lines))

        header = '\n'.join(lines[:header_end])
        tail = lines[-MAX_DIARY_LINES:]

        trimmed = (
            header
            + f"\n\n> ⚠️ 日记超过 {MAX_DIARY_BYTES // 1024}KB 上限，已自动裁剪，仅保留最新 {MAX_DIARY_LINES} 行。"
              f" 裁剪时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            + '\n'.join(tail)
            + '\n'
        )

        path.write_text(trimmed, encoding='utf-8')
        new_size = path.stat().st_size
        logger.info(
            f"[{agent_id}] Trimmed diary from {size // 1024}KB to {new_size // 1024}KB "
            f"(kept last {MAX_DIARY_LINES} lines)"
        )
        return True
    except Exception as e:
        logger.error(f"[{agent_id}] Failed to trim diary: {e}")
        return False


def get_active_session_paths(agent_id: str) -> list[tuple[str, Path]]:
    """返回 [(session_key, session_path), ...] 列表，包含所有活跃 session"""
    session_store = AGENTS_DIR / agent_id / "sessions" / "sessions.json"
    try:
        if not session_store.exists():
            return []
        with open(session_store, 'r') as f:
            data = json.load(f)

        prefix = f"agent:{agent_id}:"
        result = []
        for key, val in data.items():
            if key.startswith(prefix) and isinstance(val, dict):
                sf = val.get('sessionFile')
                if sf and Path(sf).exists():
                    result.append((key, Path(sf)))
        return result
    except Exception as e:
        logger.debug(f"[{agent_id}] Failed to get session paths: {e}")
        return []


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


def read_session_messages(session_path: Path, offset: int = 0) -> tuple[list, int]:
    """从 offset 开始读取新消息，返回 (messages, new_offset)"""
    try:
        messages = []
        file_size = session_path.stat().st_size
        if file_size < offset:
            # 文件被轮转/重建，从头读
            offset = 0
        with open(session_path, 'r') as f:
            f.seek(offset)
            data = f.read()
            new_offset = f.tell()
        if not data:
            return [], new_offset
        for line in data.splitlines():
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
        return messages, new_offset
    except Exception as e:
        logger.error(f"Failed to read session: {e}")
        return [], offset


def build_message_lines(messages: list, agent_id: str) -> list[str]:
    """将 messages 转成日记行列表（不含时间戳头部）"""
    lines = []
    for msg in messages:
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')
        label = "Boss" if role == "user" else agent_id.capitalize()
        lines.append(f"- {label}: {content}")
    return lines


def write_to_memory(messages: list, path: Path, agent_id: str, session_key: str = "") -> tuple[int, list[dict]]:
    """写入 session 消息到 memory 文件，只写入尚未出现过的新消息行。

    使用文件级互斥锁（LOCK_EX）防止并发进程重复写入同一文件。
    写入前检查日记大小，超过 MAX_DIARY_BYTES 时自动裁剪。

    返回 (写入行数, 新消息列表)
    """
    if not messages:
        return 0, []

    init_memory_file(path, agent_id)

    # 使用文件锁防止并发写入导致重复（lock file 与 diary 同目录）
    lock_path = path.with_suffix('.lock')
    try:
        lock_fd = open(lock_path, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.warning(f"[{agent_id}] Another process is writing to {path.name}, skipping this round")
        return 0, []
    except Exception as e:
        logger.warning(f"[{agent_id}] Could not acquire lock: {e}, proceeding without lock")
        lock_fd = None

    try:
        # 先做日记大小保护（裁剪超大日记）
        trim_diary_if_oversized(path, agent_id)

        # 读取已有内容，用于内容级去重（双重保险：offset 是主防线，内容比较是后备）
        try:
            existing = path.read_text(encoding='utf-8')
        except Exception:
            existing = ""

        # 过滤掉已经写过的行（纯内容比较，不依赖时间戳）
        all_lines = build_message_lines(messages, agent_id)
        new_indices = [i for i, line in enumerate(all_lines) if line not in existing]
        new_lines = [all_lines[i] for i in new_indices]

        if not new_lines:
            logger.debug(f"[{agent_id}] All messages already recorded, skipping")
            return 0, []

        time_marker = datetime.now().strftime("%H:%M")
        label = f" Session {session_key}" if session_key else " Session snapshot"
        block = f"\n### [{time_marker}]{label}\n" + "\n".join(new_lines) + "\n"

        new_messages = [messages[i] for i in new_indices]

        with open(path, 'a', encoding='utf-8') as f:
            f.write(block)
        logger.info(f"[{agent_id}] Wrote {len(new_lines)} new messages to {path}")
        return len(new_lines), new_messages

    except Exception as e:
        logger.error(f"[{agent_id}] Failed to write: {e}")
        return 0, []
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass


def discover_agents() -> list[str]:
    """返回所有有效 agent 列表（workspace 存在且可写）"""
    agents = []
    for agent_id, workspace in _AGENT_WORKSPACES.items():
        if workspace.exists():
            agents.append(agent_id)
        else:
            logger.debug(f"[{agent_id}] Workspace {workspace} does not exist, skipping")
    return sorted(agents)


def write_to_mem0(agent_id: str, new_messages: list[dict], session_key: str, today: str):
    """把新消息写入 mem0 短期记忆"""
    payload = {
        "messages": new_messages,
        "user_id": USER_ID,
        "agent_id": agent_id,
        "run_id": today,
        "metadata": {"category": "short_term", "source": "snapshot", "session_key": session_key}
    }
    resp = requests.post(f"{MEM0_API_URL}/memory/add", json=payload, timeout=60)
    resp.raise_for_status()


def load_offsets() -> dict:
    try:
        return json.loads(OFFSET_FILE.read_text()) if OFFSET_FILE.exists() else {}
    except Exception:
        return {}


def save_offsets(offsets: dict) -> None:
    OFFSET_FILE.write_text(json.dumps(offsets, indent=2))


def process_agent(agent_id: str) -> None:
    """处理单个 agent 的所有 session snapshot"""
    sessions = get_active_session_paths(agent_id)
    if not sessions:
        logger.debug(f"[{agent_id}] No active sessions found")
        return

    diary_path = get_today_memory_path(agent_id)
    today = datetime.now(BJT).strftime("%Y-%m-%d")
    offsets = load_offsets()

    for session_key, session_path in sessions:
        try:
            logger.info(f"[{agent_id}] Processing session {session_key}")
            prev = offsets.get(session_key, {}).get("offset", 0)
            messages, new_offset = read_session_messages(session_path, prev)
            if not messages:
                # 即使没消息也更新 offset（文件可能只有非消息行）
                offsets[session_key] = {"path": str(session_path), "offset": new_offset}
                continue

            written, new_messages = write_to_memory(messages, diary_path, agent_id, session_key)

            if written > 0 and new_messages:
                logger.info(f"[{agent_id}] {len(new_messages)} new messages written to diary (mem0 write skipped, handled by auto_digest)")

            offsets[session_key] = {"path": str(session_path), "offset": new_offset}
        except Exception as e:
            logger.error(f"[{agent_id}] Error processing session {session_key}: {e}")

    save_offsets(offsets)


def main():
    """主函数：遍历所有 agent 执行 snapshot"""
    global _AGENT_WORKSPACES
    _AGENT_WORKSPACES = load_agent_workspaces()

    agents = discover_agents()
    logger.info(f"Discovered {len(agents)} agents with workspaces: {agents}")

    for agent_id in agents:
        try:
            process_agent(agent_id)
        except Exception as e:
            logger.error(f"[{agent_id}] Error: {e}")


if __name__ == "__main__":
    main()
