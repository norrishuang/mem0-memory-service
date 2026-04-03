#!/usr/bin/env python3
"""
Migrate memories between mem0 service instances via HTTP API.

Usage:
  # Dump from source service to JSONL file
  python3 tools/migrate_s3vectors_to_pgvector.py dump \
    --source-url http://127.0.0.1:8230 --user-ids boss --output migration_dump.jsonl

  # Load from JSONL file to target service
  python3 tools/migrate_s3vectors_to_pgvector.py load \
    --target-url http://127.0.0.1:8231 --input migration_dump.jsonl

  # One-shot migrate (dump + load)
  python3 tools/migrate_s3vectors_to_pgvector.py migrate \
    --source-url http://127.0.0.1:8230 --target-url http://127.0.0.1:8231 --user-ids boss
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import requests

STATE_FILE = "migration_state.json"


def _load_state() -> set:
    if Path(STATE_FILE).exists():
        return set(json.loads(Path(STATE_FILE).read_text()))
    return set()


def _save_state(done_ids: set):
    Path(STATE_FILE).write_text(json.dumps(sorted(done_ids)))


def _state_key(rec: dict) -> str:
    """Unique key = user_id + id, so same memory id under different users is treated separately."""
    return f"{rec['user_id']}:{rec['id']}"


def dump(source_url: str, user_ids: list[str], output: str):
    """Dump all memories from source service to a JSONL file."""
    count = 0
    with open(output, "w") as f:
        for uid in user_ids:
            url = f"{source_url.rstrip('/')}/memory/list"
            resp = requests.get(url, params={"user_id": uid, "limit": 1000}, timeout=60)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if isinstance(results, dict):
                results = results.get("results", [])
            for mem in results:
                record = {
                    "id": mem.get("id"),
                    "memory": mem.get("memory"),
                    "user_id": uid,
                    "agent_id": mem.get("agent_id"),
                    "run_id": mem.get("run_id"),
                    "metadata": mem.get("metadata", {}),
                    "created_at": mem.get("created_at"),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
            print(f"  user={uid}: {len(results)} memories")
    print(f"Dump complete: {count} memories -> {output}")


def load(target_url: str, input_file: str):
    """Load memories from JSONL file into target service."""
    done_ids = _load_state()
    lines = Path(input_file).read_text().strip().splitlines()
    total = len(lines)
    loaded = 0
    skipped = 0

    for i, line in enumerate(lines, 1):
        rec = json.loads(line)
        key = _state_key(rec)
        if key in done_ids:
            skipped += 1
            continue

        body = {
            "user_id": rec["user_id"],
            "text": rec["memory"],
            "infer": False,
        }
        if rec.get("agent_id"):
            body["agent_id"] = rec["agent_id"]
        if rec.get("run_id"):
            body["run_id"] = rec["run_id"]
        if rec.get("metadata"):
            body["metadata"] = rec["metadata"]

        url = f"{target_url.rstrip('/')}/memory/add"
        resp = requests.post(url, json=body, timeout=120)
        resp.raise_for_status()

        done_ids.add(key)
        loaded += 1
        if loaded % 10 == 0:
            _save_state(done_ids)
            print(f"  Progress: {loaded + skipped}/{total} (loaded={loaded}, skipped={skipped})")

    _save_state(done_ids)
    print(f"Load complete: loaded={loaded}, skipped={skipped}, total={total}")


def migrate(source_url: str, target_url: str, user_ids: list[str]):
    """Dump from source then load into target."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        tmp_path = tmp.name
    print(f"Dumping to temp file: {tmp_path}")
    dump(source_url, user_ids, tmp_path)
    print(f"Loading into target: {target_url}")
    load(target_url, tmp_path)
    Path(tmp_path).unlink(missing_ok=True)
    print("Migration complete.")


def main():
    parser = argparse.ArgumentParser(description="Migrate memories between mem0 service instances")
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="Dump memories from source service to JSONL")
    p_dump.add_argument("--source-url", required=True, help="Source mem0 service URL")
    p_dump.add_argument("--user-ids", default="boss", help="Comma-separated user IDs (default: boss)")
    p_dump.add_argument("--output", default="migration_dump.jsonl", help="Output JSONL file")

    p_load = sub.add_parser("load", help="Load memories from JSONL into target service")
    p_load.add_argument("--target-url", required=True, help="Target mem0 service URL")
    p_load.add_argument("--input", default="migration_dump.jsonl", help="Input JSONL file")

    p_mig = sub.add_parser("migrate", help="Dump from source + load into target")
    p_mig.add_argument("--source-url", required=True, help="Source mem0 service URL")
    p_mig.add_argument("--target-url", required=True, help="Target mem0 service URL")
    p_mig.add_argument("--user-ids", default="boss", help="Comma-separated user IDs (default: boss)")

    args = parser.parse_args()

    if args.command == "dump":
        dump(args.source_url, args.user_ids.split(","), args.output)
    elif args.command == "load":
        load(args.target_url, args.input)
    elif args.command == "migrate":
        migrate(args.source_url, args.target_url, args.user_ids.split(","))


if __name__ == "__main__":
    main()
