#!/usr/bin/env python3
"""
Migrate existing MEMORY.md content into mem0 Memory Service.
Splits MEMORY.md by sections and stores each as a separate memory.
"""
import re
import sys
import requests
import json

BASE_URL = "http://127.0.0.1:8230"
MEMORY_FILE = "/home/ec2-user/.openclaw/workspace-dev/MEMORY.md"
USER_ID = "boss"
AGENT_ID = "dev"


def parse_memory_file(filepath: str) -> list[dict]:
    """Parse MEMORY.md into structured chunks."""
    with open(filepath, "r") as f:
        content = f.read()

    memories = []

    # Split by ## or ### headers
    sections = re.split(r'\n(?=###?\s)', content)

    for section in sections:
        section = section.strip()
        if not section or section.startswith("# MEMORY.md") or section.startswith("> 最后更新"):
            continue

        # Extract title
        title_match = re.match(r'^(#{2,3})\s+(.+)', section)
        if title_match:
            title = title_match.group(2).strip()
        else:
            title = section[:50]

        # Skip empty sections
        body = section.strip()
        if len(body) < 10:
            continue

        # Determine category from context
        category = "general"
        if any(kw in section.lower() for kw in ["项目", "project", "pr ", "仓库", "repo"]):
            category = "project"
        elif any(kw in section.lower() for kw in ["环境", "ssh", "key", "目录"]):
            category = "environment"
        elif any(kw in section.lower() for kw in ["待办", "todo", "等待"]):
            category = "todo"
        elif any(kw in section.lower() for kw in ["经验", "教训", "注意"]):
            category = "experience"

        memories.append({
            "text": body,
            "metadata": {
                "category": category,
                "title": title,
                "source": "memory_md_migration",
            },
        })

    return memories


def migrate():
    # Check service health
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Memory service not available: {e}")
        sys.exit(1)

    print(f"📖 Parsing {MEMORY_FILE}...")
    memories = parse_memory_file(MEMORY_FILE)
    print(f"   Found {len(memories)} memory sections")

    for i, mem in enumerate(memories):
        print(f"\n[{i+1}/{len(memories)}] Adding: {mem['metadata']['title'][:60]}...")
        payload = {
            "text": mem["text"],
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "metadata": mem["metadata"],
        }
        try:
            resp = requests.post(f"{BASE_URL}/memory/add", json=payload, timeout=60)
            resp.raise_for_status()
            result = resp.json()
            added = result.get("result", {}).get("results", [])
            if added:
                for item in added:
                    print(f"   ✅ {item.get('event', '?')}: {item.get('memory', '?')[:80]}")
            else:
                print(f"   ⚪ No new memories extracted (may be duplicate)")
        except Exception as e:
            print(f"   ❌ Error: {e}")

    print(f"\n🎉 Migration complete!")

    # Show total count
    resp = requests.get(f"{BASE_URL}/memory/list", params={"user_id": USER_ID, "agent_id": AGENT_ID})
    total = len(resp.json().get("results", {}).get("results", []))
    print(f"   Total memories in store: {total}")


if __name__ == "__main__":
    migrate()
