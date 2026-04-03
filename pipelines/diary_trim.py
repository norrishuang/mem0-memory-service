#!/usr/bin/env python3
"""
diary_trim.py - 日记文件大小保护与修复工具

功能：
1. 扫描所有 agent 的当日及历史日记文件
2. 对超过 MAX_DIARY_BYTES 的文件执行裁剪，只保留最新 MAX_DIARY_LINES 行
3. 支持 --dry-run 模式（只输出报告，不实际修改）
4. 支持 --agent 参数（只处理指定 agent）
5. 支持 --date 参数（只处理特定日期的日记，默认为今天）
6. 支持 --all-dates 参数（处理所有历史日记）

使用示例：
  # 查看哪些文件超限（不修改）
  python3 diary_trim.py --dry-run

  # 修复所有超限日记
  python3 diary_trim.py

  # 只修复 dev agent 的日记
  python3 diary_trim.py --agent dev

  # 修复指定日期的日记
  python3 diary_trim.py --date 2026-03-27

  # 修复所有历史日记
  python3 diary_trim.py --all-dates
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────
OPENCLAW_BASE = Path(os.environ.get("OPENCLAW_BASE",
                     os.environ.get("OPENCLAW_HOME", Path.home() / ".openclaw")))
OPENCLAW_CONFIG = OPENCLAW_BASE / "openclaw.json"
BJT = timezone(timedelta(hours=8))

# 大小阈值：超过此值才裁剪
MAX_DIARY_BYTES = int(os.environ.get("MAX_DIARY_BYTES", 200 * 1024))   # 200 KB
# 裁剪后保留的最新行数
MAX_DIARY_LINES = int(os.environ.get("MAX_DIARY_LINES", 800))


# ── Agent Discovery ────────────────────────────────────────────────────────────

def load_agent_workspaces() -> dict[str, Path]:
    """从 openclaw.json 读取每个 agent 的 workspace 路径"""
    mapping: dict[str, Path] = {}

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
        except Exception as e:
            print(f"⚠️  Failed to parse openclaw.json: {e}, falling back to directory scan", file=sys.stderr)

    # 兜底：扫描 workspace-* 目录
    if not mapping:
        for ws_dir in sorted(OPENCLAW_BASE.glob("workspace-*")):
            agent_id = ws_dir.name.replace("workspace-", "")
            mapping[agent_id] = ws_dir

    return mapping


# ── Core Logic ────────────────────────────────────────────────────────────────

def analyze_diary(path: Path) -> dict:
    """分析单个日记文件，返回统计信息"""
    size = path.stat().st_size
    lines = path.read_text(encoding='utf-8').splitlines()
    # 计算重复 session 块数量（### 开头的行）
    session_headers = [l for l in lines if l.startswith('### [')]
    return {
        "path": path,
        "size_bytes": size,
        "size_kb": size / 1024,
        "total_lines": len(lines),
        "session_blocks": len(session_headers),
        "needs_trim": size > MAX_DIARY_BYTES,
    }


def trim_diary(path: Path, dry_run: bool = False) -> dict:
    """裁剪单个日记文件，只保留最新 MAX_DIARY_LINES 行"""
    info = analyze_diary(path)

    if not info["needs_trim"]:
        return {**info, "action": "skip", "reason": "within size limit"}

    content = path.read_text(encoding='utf-8')
    lines = content.splitlines()

    # 提取文件头（第一个 ## 标题之前的内容，通常是 # 标题 + ## Session 记录）
    header_end = 0
    section_count = 0
    for i, line in enumerate(lines):
        if line.startswith('## '):
            section_count += 1
            if section_count >= 2:
                header_end = i
                break
    else:
        # 如果没有找到两个 ## 标题，保留前 10 行作为头部
        header_end = min(10, len(lines))

    header_lines = lines[:header_end]
    tail_lines = lines[-MAX_DIARY_LINES:]

    trim_notice = [
        "",
        f"> ⚠️ 日记超过 {MAX_DIARY_BYTES // 1024}KB 上限，已自动裁剪，",
        f"> 仅保留最新 {MAX_DIARY_LINES} 行（共 {len(lines)} 行）。",
        f"> 裁剪时间：{datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S CST')}",
        "",
    ]

    trimmed_content = '\n'.join(header_lines + trim_notice + tail_lines) + '\n'
    new_size = len(trimmed_content.encode('utf-8'))

    # 如果裁剪后反而更大（不太可能但保险起见），直接用 tail
    if new_size >= info["size_bytes"]:
        tail_only = lines[-MAX_DIARY_LINES:]
        trimmed_content = (
            f"# 日记（自动裁剪版，仅保留最新 {MAX_DIARY_LINES} 行）\n\n"
            + f"> 裁剪时间：{datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S CST')}\n\n"
            + '\n'.join(tail_only) + '\n'
        )
        new_size = len(trimmed_content.encode('utf-8'))

    # 裁剪后如果没有实质性缩小（<5% 节省），跳过
    if new_size >= info["size_bytes"] * 0.95:
        return {**info, "action": "skip", "reason": "trim would not reduce size significantly"}

    result = {
        **info,
        "action": "trimmed" if not dry_run else "would_trim",
        "original_lines": len(lines),
        "kept_lines": MAX_DIARY_LINES,
        "new_size_bytes": new_size,
        "new_size_kb": new_size / 1024,
        "saved_kb": (info["size_bytes"] - new_size) / 1024,
    }

    if not dry_run:
        path.write_text(trimmed_content, encoding='utf-8')

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    global MAX_DIARY_BYTES, MAX_DIARY_LINES

    parser = argparse.ArgumentParser(description="日记文件大小保护工具")
    parser.add_argument("--dry-run", action="store_true", help="只分析，不修改文件")
    parser.add_argument("--agent", help="只处理指定 agent（默认处理所有）")
    parser.add_argument("--date", help="只处理指定日期（格式 YYYY-MM-DD，默认今天）")
    parser.add_argument("--all-dates", action="store_true", help="处理所有历史日记")
    parser.add_argument("--threshold-kb", type=int, default=MAX_DIARY_BYTES // 1024,
                        help=f"裁剪阈值 KB（默认 {MAX_DIARY_BYTES // 1024}）")
    parser.add_argument("--keep-lines", type=int, default=MAX_DIARY_LINES,
                        help=f"裁剪后保留行数（默认 {MAX_DIARY_LINES}）")
    args = parser.parse_args()

    MAX_DIARY_BYTES = args.threshold_kb * 1024
    MAX_DIARY_LINES = args.keep_lines

    workspaces = load_agent_workspaces()
    if args.agent:
        if args.agent not in workspaces:
            print(f"❌ Agent '{args.agent}' not found. Available: {list(workspaces.keys())}")
            sys.exit(1)
        workspaces = {args.agent: workspaces[args.agent]}

    today = datetime.now(BJT).strftime("%Y-%m-%d")

    total_analyzed = 0
    total_trimmed = 0
    total_saved_kb = 0.0

    print(f"{'[DRY RUN] ' if args.dry_run else ''}diary_trim.py — threshold={MAX_DIARY_BYTES//1024}KB, keep={MAX_DIARY_LINES} lines")
    print("=" * 70)

    for agent_id, workspace in sorted(workspaces.items()):
        memory_dir = workspace / "memory"
        if not memory_dir.exists():
            continue

        if args.all_dates:
            diary_files = sorted(memory_dir.glob("????-??-??.md"))
        elif args.date:
            f = memory_dir / f"{args.date}.md"
            diary_files = [f] if f.exists() else []
        else:
            f = memory_dir / f"{today}.md"
            diary_files = [f] if f.exists() else []

        for diary_path in diary_files:
            total_analyzed += 1
            result = trim_diary(diary_path, dry_run=args.dry_run)

            if result["action"] == "skip":
                status = f"  ✅ {agent_id}/{diary_path.name}: {result['size_kb']:.1f}KB (OK)"
            elif result["action"] in ("trimmed", "would_trim"):
                verb = "Would trim" if args.dry_run else "Trimmed"
                saved = result.get("saved_kb", 0)
                status = (
                    f"  ✂️  {agent_id}/{diary_path.name}: "
                    f"{result['size_kb']:.1f}KB → {result.get('new_size_kb', 0):.1f}KB "
                    f"(saved {saved:.1f}KB, {result['session_blocks']} session blocks)"
                )
                total_trimmed += 1
                total_saved_kb += saved
            else:
                status = f"  ❓ {agent_id}/{diary_path.name}: {result}"

            print(status)

    print("=" * 70)
    print(f"Summary: analyzed={total_analyzed}, "
          f"{'would_trim' if args.dry_run else 'trimmed'}={total_trimmed}, "
          f"saved={total_saved_kb:.1f}KB")


if __name__ == "__main__":
    main()
