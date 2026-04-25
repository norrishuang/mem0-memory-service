#!/usr/bin/env python3
"""
auto_dream.py - AutoDream 记忆沉淀（夜间自动巩固）

每天 UTC 02:00 运行，对每个 agent 执行三步：
  Step 1: 读取近 7 天日记 → 两步处理：
          1A. 每天日记单独用 LLM 提炼摘要 facts（不写入 mem0）
          1B. 把所有日摘要合并，用 REFLECTION_PROMPT 做跨日规律分析 → 写入 mem0 长期记忆
          （改造原因：一次性 258K chars 导致 LLM 返回空结果，分块后每步输入量可控）
  Step 2: 找到 7 天前的短期记忆 → 逐条 re-add 到 mem0(infer=True, 无 run_id) → 删除原始短期条目
         mem0 原生决定 ADD/UPDATE/DELETE/NONE，不再手写语义搜索判断。
  Step 3: 扫描已有长期记忆，找出语义高度相似的冗余对，用 mem0 infer=True 合并去冗余。
         每次处理一个批次（轮转），避免单次运行时间过长。
"""

import json
import logging
import os
import re
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

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

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import DIGEST_LLM_MODEL, AWS_REGION

bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)

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


# ─── LLM Helper (direct Bedrock call for daily summary) ───

def _call_llm_for_summary(text: str, prompt: str) -> list[str]:
    """
    直接调 Bedrock Converse API 提炼摘要，不经过 mem0（避免写入存储）。
    返回 facts 字符串列表；失败时返回空列表。
    """
    messages = [
        {
            "role": "user",
            "content": [{"text": f"{prompt}\n\n---\n\n{text}"}]
        }
    ]

    try:
        response = bedrock_client.converse(
            modelId=DIGEST_LLM_MODEL,
            messages=messages,
            inferenceConfig={"maxTokens": 4000, "temperature": 0.1},
        )
        # MiniMax 将 reasoningContent 和 text 分两个 block 返回，只取 text block
        content_blocks = response["output"]["message"]["content"]
        output = ""
        for block in content_blocks:
            if "text" in block:
                output = block["text"].strip()
                break
        if not output:
            logger.warning(f"No text block in LLM response: {content_blocks}")
            return []
        # 尝试解析 JSON
        # 先尝试直接解析
        try:
            data = json.loads(output)
            return data.get("facts", [])
        except json.JSONDecodeError:
            pass
        # 容错：提取 ```json ... ``` 块
        m = re.search(r'```(?:json)?\s*({.*?})\s*```', output, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            return data.get("facts", [])
        # 容错：找 { ... } 块
        m = re.search(r'({[^{}]+})', output, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            return data.get("facts", [])
        logger.warning(f"LLM output could not be parsed as JSON: {output[:200]}")
        return []
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return []


# ─── Custom Extraction Prompts ───

# Step 1A：单日日记摘要（不写 mem0，只用于中间处理）
DAILY_SUMMARY_PROMPT = """\
你是一位技术助理，请阅读以下单日工作日记，提炼出最重要的技术事件、决策和问题（每条20-50字，中文）。
只提炼有实质内容的事实，不要写流水账，不要重复相似内容。
输出格式（必须严格遵守）：{"facts": ["事实1", "事实2", ...]}
如无实质内容，返回：{"facts": []}
"""

# Step 1B：引导 mem0 从多天日记摘要中提炼跨日规律性结论，而非单次事件。
REFLECTION_PROMPT = """
你是一位资深技术助理，专门从多天工作日记中提炼具有规律性和反思价值的长期经验。

请阅读以下多天工作日记，**不要提炼单次事件的结论**（那是 auto_digest 的工作），而是聚焦以下几个维度：

【维度一：反复出现的问题】
- 同类错误在多天中出现 2 次以上
- 反复踩的坑、反复遗忘的步骤
- 举例：「XXX 参数名连续两次传错，应该固定记住正确参数名是 YYY」

【维度二：Agent 自身失误模式】
- Agent 判断错误、遗漏确认步骤、自作主张导致返工
- 举例：「两次在未确认 Boss 意图的情况下直接执行了有副作用的操作」

【维度三：被 Boss 纠正的行为规律】
- Boss 明确纠正或提出异议的操作方式
- 多次被指出的沟通/汇报问题
- 举例：「Boss 多次要求先查看状态再操作，不要直接执行」

【维度四：耗时/绕路模式】
- 反复出现走弯路、回退操作的任务类型
- 可以提前规避的排查路径
- 举例：「SSH 连接问题每次都要试多种 key，应该提前记录哪个 key 对应哪个集群」

**提炼原则：**
- 必须是跨越多天、有规律性的观察，单次事件不写
- 每条结论应自完备、可独立理解
- 用中文，直接表述结论和建议
- 如果日记天数太少（不足 3 天有内容）或找不到规律，返回空列表

**输出格式（必须严格遵守）：**
{"facts": ["规律性结论1", "规律性结论2", ...]}

如无规律性内容，返回：{"facts": []}
"""


# ─── Chunking ───

CHUNK_SIZE = 20_000    # 单 chunk 上限
OVERLAP_SIZE = 3_000   # overlap 大小（约 15%），必须是完整语义块

# 语义分割标记，按优先级从高到低
_SPLIT_PATTERNS = [
    re.compile(r'(?=^#{2,3} )', re.MULTILINE),   # Markdown 标题行
    re.compile(r'(?=^---\s*$)', re.MULTILINE),    # 分隔线
    re.compile(r'\n\n'),                           # 双空行
    re.compile(r'\n'),                             # 单行
]


def _split_at_level(text: str, level: int) -> list[str]:
    """用第 level 级分隔符切割 text，返回非空片段列表。"""
    if level >= len(_SPLIT_PATTERNS):
        return [text]
    parts = _SPLIT_PATTERNS[level].split(text)
    return [p for p in parts if p.strip()]


def split_by_markers(content: str, chunk_size: int = CHUNK_SIZE, overlap_size: int = OVERLAP_SIZE) -> list[str]:
    """将长文本按语义边界切割为多个 chunk，带 overlap 保持上下文连贯。"""
    if len(content) <= chunk_size:
        return [content]

    # 用最高优先级能产生多段的分隔符切割
    segments = None
    for level in range(len(_SPLIT_PATTERNS)):
        parts = _split_at_level(content, level)
        if len(parts) > 1:
            segments = parts
            break
    if segments is None:
        # 所有分隔符都无法切割，硬切
        segments = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]

    # 递归细化超限 segment
    expanded = []
    for seg in segments:
        if len(seg) > chunk_size:
            expanded.extend(split_by_markers(seg, chunk_size, overlap_size))
        else:
            expanded.append(seg)
    segments = expanded

    # 贪心合并 segments 为 chunks，保证每个 chunk <= chunk_size
    chunks: list[str] = []
    current = ""
    current_seg_indices: list[int] = []  # 当前 chunk 包含的 segment 索引

    for idx, seg in enumerate(segments):
        candidate = current + seg if current else seg
        if len(candidate) > chunk_size and current:
            chunks.append(current)
            # overlap: 从当前 chunk 末尾回溯完整语义块
            overlap_parts: list[str] = []
            overlap_len = 0
            for si in reversed(current_seg_indices):
                if overlap_len + len(segments[si]) > overlap_size:
                    break
                overlap_parts.insert(0, segments[si])
                overlap_len += len(segments[si])
            current = "".join(overlap_parts) + seg
            current_seg_indices = [idx]
        else:
            current = candidate
            current_seg_indices.append(idx)

    if current.strip():
        chunks.append(current)

    return chunks


MERGE_FACTS_PROMPT = """你是一个记忆管理专家。以下是从同一天日记的多个片段中提取的技术事实列表，可能存在重复或相似内容。
请合并重复项，保留最重要的不超过10条事实。每条不超过80字，聚焦技术决策、问题根因、解决方案。

格式：每行一条，不加序号和标点前缀。

事实列表：
{facts}"""


def _call_llm_merge_facts(facts: list[str]) -> list[str]:
    """合并去重多个 chunk 提取的 facts，超过 20 条时调用 LLM。"""
    facts_text = "\n".join(f"- {f}" for f in facts)
    prompt = MERGE_FACTS_PROMPT.format(facts=facts_text)

    try:
        response = bedrock_client.converse(
            modelId=DIGEST_LLM_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 2000, "temperature": 0.1},
        )
        content_blocks = response["output"]["message"]["content"]
        output = ""
        for block in content_blocks:
            if "text" in block:
                output = block["text"].strip()
                break
        if not output:
            return facts[:10]
        # 按行解析，过滤空行和前缀
        merged = []
        for line in output.splitlines():
            line = line.strip().lstrip("-•·0123456789.） ").strip()
            if line:
                merged.append(line)
        return merged[:10] if merged else facts[:10]
    except Exception as e:
        logger.warning(f"Merge facts LLM call failed: {e}, returning first 10")
        return facts[:10]


# ─── Step 1: Reflect on Recent Week Diaries ───


def reflect_week(agent_id: str, workspace: Path):
    """
    两步法反思近 7 天日记：
    Step 1A：每天日记单独用 LLM 提炼摘要 facts（直接调 Bedrock，不写 mem0）
    Step 1B：把所有日摘要合并，用 REFLECTION_PROMPT 做跨日规律分析 → 写入 mem0 长期记忆
    """
    today = datetime.utcnow().date()

    # ── Step 1A: 每日摘要 ──
    daily_summaries = {}  # date_str → list[str]
    for i in range(1, 8):  # 昨天到 7 天前
        date = today - timedelta(days=i)
        diary_file = workspace / "memory" / f"{date}.md"
        if not diary_file.exists():
            continue
        content = diary_file.read_text(encoding="utf-8").strip()
        if not content:
            continue
        # 分段处理超长日记
        if len(content) > CHUNK_SIZE:
            chunks = split_by_markers(content, CHUNK_SIZE, OVERLAP_SIZE)
            logger.info(f"[{agent_id}] Daily diary {date} split into {len(chunks)} chunks ({len(content)} chars total)")
            all_facts: list[str] = []
            for ci, chunk in enumerate(chunks):
                chunk_facts = _call_llm_for_summary(chunk, DAILY_SUMMARY_PROMPT)
                logger.info(f"[{agent_id}] Chunk {ci+1}/{len(chunks)}: {len(chunk_facts)} facts")
                all_facts.extend(chunk_facts)
            if len(all_facts) > 20:
                facts = _call_llm_merge_facts(all_facts)
                logger.info(f"[{agent_id}] Merged {len(all_facts)} facts → {len(facts)} facts")
            else:
                seen: set[str] = set()
                facts = [f for f in all_facts if not (f in seen or seen.add(f))]
        else:
            facts = _call_llm_for_summary(content, DAILY_SUMMARY_PROMPT)
        logger.info(f"[{agent_id}] Daily summary for {date}: {len(facts)} facts")
        if facts:
            daily_summaries[str(date)] = facts

    if not daily_summaries:
        logger.info(f"[{agent_id}] No diaries found in past 7 days, skipping reflect")
        return

    # ── Step 1B: 跨日规律反思 ──
    # 把每日摘要拼成结构化文本，大幅压缩输入量
    summary_sections = []
    for date_str, facts in sorted(daily_summaries.items()):
        facts_text = "\n".join(f"- {f}" for f in facts)
        summary_sections.append(f"=== {date_str} 摘要 ===\n{facts_text}")
    combined_summary = "\n\n".join(summary_sections)

    date_range = f"{today - timedelta(days=7)}~{today - timedelta(days=1)}"
    logger.info(f"[{agent_id}] Cross-day reflection input: {len(daily_summaries)} days, {len(combined_summary)} chars")

    resp = requests.post(f"{BASE_URL}/memory/dream", json={
        "user_id": USER_ID,
        "agent_id": agent_id,
        "text": combined_summary,
        "infer": True,
        "custom_extraction_prompt": REFLECTION_PROMPT,
        "metadata": {"source": "auto_dream_reflect", "reflect_range": date_range}
    }, timeout=180)
    resp.raise_for_status()
    logger.info(f"[{agent_id}] Reflected on {len(daily_summaries)} days into long-term memory")


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
            # Step 1: reflect on recent week diaries → long-term memory
            reflect_week(agent_id, workspace)
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
