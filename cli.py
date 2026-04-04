#!/usr/bin/env python3
"""
mem0 Memory CLI - Command-line client for the Memory Service.
Used by OpenClaw agents via exec tool.

Usage:
  python3 cli.py add --user boss --agent dev --text "Important fact here"
  python3 cli.py add --user boss --agent dev --messages '[{"role":"user","content":"..."}]'
  python3 cli.py search --user boss --agent dev --query "what do I know about X"
  python3 cli.py list --user boss --agent dev
  python3 cli.py get --id <memory_id>
  python3 cli.py delete --id <memory_id>
  python3 cli.py history --id <memory_id>
"""
import argparse
import json
import os
import sys

import requests

BASE_URL = os.environ.get("MEM0_API_URL", "http://127.0.0.1:8230")


def add_memory(args):
    payload = {"user_id": args.user}
    if args.agent:
        payload["agent_id"] = args.agent
    if args.run:
        payload["run_id"] = args.run
    if args.metadata:
        payload["metadata"] = json.loads(args.metadata)

    if args.messages:
        payload["messages"] = json.loads(args.messages)
    elif args.text:
        payload["text"] = args.text
    else:
        print("Error: --text or --messages required", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(f"{BASE_URL}/memory/add", json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()

    # Auto-share experience memories to shared knowledge base
    metadata = payload.get("metadata", {})
    if metadata.get("category") == "experience" and payload.get("user_id") != "shared":
        shared_payload = {**payload, "user_id": "shared"}
        try:
            requests.post(f"{BASE_URL}/memory/add", json=shared_payload, timeout=60)
        except Exception:
            pass  # shared write failure is non-critical

    print(json.dumps(result, indent=2, ensure_ascii=False))


def search_memory(args):
    payload = {
        "query": args.query,
        "user_id": args.user,
        "top_k": args.top_k,
        "min_score": args.min_score,
    }
    if args.agent:
        payload["agent_id"] = args.agent

    # Use combined search if requested
    if args.combined:
        payload["recent_days"] = args.recent_days
        endpoint = f"{BASE_URL}/memory/search_combined"
    else:
        if args.run:
            payload["run_id"] = args.run
        endpoint = f"{BASE_URL}/memory/search"

    resp = requests.post(endpoint, json=payload, timeout=30)
    resp.raise_for_status()
    results = resp.json()

    # Merge shared knowledge base results (skip if already searching as shared)
    if args.user != "shared":
        shared_payload = {**payload, "user_id": "shared"}
        try:
            shared_resp = requests.post(endpoint, json=shared_payload, timeout=30)
            shared_resp.raise_for_status()
            shared_results = shared_resp.json()

            # Merge and deduplicate by memory id
            if isinstance(results, list) and isinstance(shared_results, list):
                seen = {r["id"] for r in results if "id" in r}
                for r in shared_results:
                    if r.get("id") not in seen:
                        results.append(r)
                results.sort(key=lambda r: r.get("score", 0), reverse=True)
            elif isinstance(results, dict) and isinstance(shared_results, dict):
                # Handle nested structures like {status, results: {results: [...]}}
                def _get_list(d):
                    for key in ("results", "memories"):
                        v = d.get(key)
                        if isinstance(v, list):
                            return v
                        if isinstance(v, dict):
                            inner = v.get("results") or v.get("memories")
                            if isinstance(inner, list):
                                return inner
                    return None

                personal = _get_list(results)
                shared = _get_list(shared_results)
                if personal is not None and shared is not None:
                    seen = {r["id"] for r in personal if "id" in r}
                    for r in shared:
                        if r.get("id") not in seen:
                            personal.append(r)
                    personal.sort(key=lambda r: r.get("score", 0), reverse=True)
        except Exception:
            pass  # shared search failure is non-critical

    print(json.dumps(results, indent=2, ensure_ascii=False))


def list_memories(args):
    params = {"user_id": args.user, "limit": args.limit, "offset": args.offset}
    if args.agent:
        params["agent_id"] = args.agent
    if args.run:
        params["run_id"] = args.run

    resp = requests.get(f"{BASE_URL}/memory/list", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if args.count_only:
        agent_label = args.agent or "all"
        print(f"{agent_label} 共 {data.get('total', '?')} 条记忆")
        return

    print(json.dumps(data, indent=2, ensure_ascii=False))

    results = data.get("results", [])
    if len(results) == args.limit:
        next_offset = args.offset + args.limit
        print(f"\n# 提示：已达返回上限({args.limit}条)，使用 --offset {next_offset} 查看更多")


def get_memory(args):
    resp = requests.get(f"{BASE_URL}/memory/{args.id}", timeout=10)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def delete_memory(args):
    resp = requests.delete(f"{BASE_URL}/memory/{args.id}", timeout=10)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def memory_history(args):
    resp = requests.get(f"{BASE_URL}/memory/history/{args.id}", timeout=10)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="mem0 Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add memory")
    p_add.add_argument("--user", required=True)
    p_add.add_argument("--agent", default=None)
    p_add.add_argument("--run", default=None, help="Run/session ID (e.g. YYYY-MM-DD for short-term memories)")
    p_add.add_argument("--text", default=None)
    p_add.add_argument("--messages", default=None, help="JSON array of {role, content}")
    p_add.add_argument("--metadata", default=None, help="JSON object of metadata")
    p_add.set_defaults(func=add_memory)

    # search
    p_search = sub.add_parser("search", help="Search memories")
    p_search.add_argument("--user", required=True)
    p_search.add_argument("--agent", default=None)
    p_search.add_argument("--run", default=None, help="Filter by specific run ID")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--top-k", type=int, default=5,
                          help="Max results to return (default: 5)")
    p_search.add_argument("--min-score", type=float, default=0.0,
                          help="Minimum relevance score to include (0.0–1.0). "
                               "Results below this threshold are dropped. "
                               "Recommended: 0.3–0.5 to filter low-relevance noise.")
    p_search.add_argument("--combined", action="store_true",
                          help="Combined search: long-term + recent short-term memories")
    p_search.add_argument("--recent-days", type=int, default=3,
                          help="Number of recent days to include in combined search (default: 3)")
    p_search.set_defaults(func=search_memory)

    # list
    p_list = sub.add_parser("list", help="List memories")
    p_list.add_argument("--user", required=True)
    p_list.add_argument("--agent", default=None)
    p_list.add_argument("--run", default=None)
    p_list.add_argument("--limit", type=int, default=100, help="Max results to return (default: 100)")
    p_list.add_argument("--offset", type=int, default=0, help="Skip first N results (default: 0)")
    p_list.add_argument("--count-only", action="store_true", help="Only print total count")
    p_list.set_defaults(func=list_memories)

    # get
    p_get = sub.add_parser("get", help="Get a memory by ID")
    p_get.add_argument("--id", required=True)
    p_get.set_defaults(func=get_memory)

    # delete
    p_del = sub.add_parser("delete", help="Delete a memory")
    p_del.add_argument("--id", required=True)
    p_del.set_defaults(func=delete_memory)

    # history
    p_hist = sub.add_parser("history", help="Get memory change history")
    p_hist.add_argument("--id", required=True)
    p_hist.set_defaults(func=memory_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
