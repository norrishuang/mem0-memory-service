#!/usr/bin/env python3
"""
backfill_history.py - 补录历史日记到 mem0

将各 agent 历史日记文件（排除今天）批量写入 mem0（infer=False）。
"""
import os
import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime

MEM0_API_URL = os.environ.get("MEM0_API_URL", "http://localhost:8230")
USER_ID = "boss"
BATCH_SIZE = 5_000     # 5KB 每批（Bedrock embedding 限制 8192 tokens，中文日记密度高保守取 5KB）
BATCH_SLEEP = 3        # 批次间隔秒数
TIMEOUT = 120

TODAY = datetime.utcnow().strftime("%Y-%m-%d")

AGENT_WORKSPACES = {
    "dev":        Path("/home/ec2-user/.openclaw/workspace-dev"),
    "main":       Path("/home/ec2-user/clawd"),
    "blog":       Path("/home/ec2-user/.openclaw/workspace-blog"),
    "pm":         Path("/home/ec2-user/.openclaw/workspace-pm"),
    "pjm":        Path("/home/ec2-user/.openclaw/workspace-pjm"),
    "prototype":  Path("/home/ec2-user/.openclaw/workspace-prototype"),
    "researcher": Path("/home/ec2-user/.openclaw/workspace-researcher"),
}

# 已被 auto_dream 处理过的日期（今早手动跑的），跳过避免重复
ALREADY_PROCESSED = {"2026-04-04"}  # auto_dream 今早已归档


def write_batch(text: str, agent_id: str, date: str, batch_num: int) -> bool:
    try:
        resp = requests.post(f"{MEM0_API_URL}/memory/add", json={
            "user_id": USER_ID,
            "agent_id": agent_id,
            "text": text,
            "infer": False,
            "metadata": {
                "category": "backfill",
                "source": "backfill_history",
                "digest_date": date,
                "batch": batch_num,
            }
        }, timeout=TIMEOUT)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"    ✗ 写入失败: {e}")
        return False


def process_file(agent_id: str, diary_path: Path) -> dict:
    date = diary_path.stem
    content = diary_path.read_text(encoding="utf-8").strip()
    if not content:
        return {"status": "empty", "batches": 0}

    content_bytes = content.encode("utf-8")
    total = len(content_bytes)
    batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    success = 0

    print(f"  [{agent_id}] {date} — {total//1024}KB, {batches} 批")

    offset = 0
    batch_num = 0
    while offset < len(content_bytes):
        batch_num += 1
        chunk = content_bytes[offset:offset + BATCH_SIZE].decode("utf-8", errors="replace")
        ok = write_batch(chunk, agent_id, date, batch_num)
        if ok:
            success += 1
            print(f"    ✓ batch {batch_num}/{batches} ({len(chunk.encode())} bytes)")
        else:
            print(f"    ✗ batch {batch_num}/{batches} 失败，继续下一批")
        offset += BATCH_SIZE
        if offset < len(content_bytes):
            time.sleep(BATCH_SLEEP)

    return {"status": "done", "batches": batches, "success": success}


def main():
    print(f"=== 历史日记补录 ===")
    print(f"今天: {TODAY}，跳过今天及已处理日期: {ALREADY_PROCESSED}")
    print()

    # 收集所有待处理文件，按大小排序（小的先处理）
    files = []
    for agent_id, ws in AGENT_WORKSPACES.items():
        memory_dir = ws / "memory"
        if not memory_dir.exists():
            continue
        for f in memory_dir.glob("*.md"):
            date = f.stem
            if date == TODAY or date in ALREADY_PROCESSED:
                continue
            if not date.startswith("2026-"):
                continue
            files.append((f.stat().st_size, agent_id, f, date))

    files.sort()  # 从小到大
    total_files = len(files)
    print(f"待处理文件: {total_files} 个，总大小: {sum(s for s,_,_,_ in files) // 1024 // 1024} MB")
    print()

    stats = {"files": 0, "batches": 0, "skipped": 0}
    for i, (size, agent_id, path, date) in enumerate(files, 1):
        print(f"[{i}/{total_files}] {agent_id}/{date} ({size//1024}KB)")
        result = process_file(agent_id, path)
        if result["status"] == "empty":
            print(f"  跳过（空文件）")
            stats["skipped"] += 1
        else:
            stats["files"] += 1
            stats["batches"] += result["batches"]
        print()

    print(f"=== 完成 ===")
    print(f"处理文件: {stats['files']}，总批次: {stats['batches']}，跳过: {stats['skipped']}")


if __name__ == "__main__":
    main()
