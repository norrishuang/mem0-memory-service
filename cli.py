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
import sys

import requests

BASE_URL = "http://127.0.0.1:8230"


def add_memory(args):
    payload = {"user_id": args.user}
    if args.agent:
        payload["agent_id"] = args.agent
    if args.run:
        payload["run_id"] = args.run
    if args.metadata:
        payload["metadata"] = json.loads(args.metadata)
    if args.ttl_days:
        payload["ttl_days"] = args.ttl_days
    if args.expires_at:
        payload["expires_at"] = args.expires_at

    if args.messages:
        payload["messages"] = json.loads(args.messages)
    elif args.text:
        payload["text"] = args.text
    else:
        print("Error: --text or --messages required", file=sys.stderr)
        sys.exit(1)

    resp = requests.post(f"{BASE_URL}/memory/add", json=payload, timeout=60)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def search_memory(args):
    payload = {
        "query": args.query,
        "user_id": args.user,
        "top_k": args.top_k,
    }
    if args.agent:
        payload["agent_id"] = args.agent
    if args.run:
        payload["run_id"] = args.run

    resp = requests.post(f"{BASE_URL}/memory/search", json=payload, timeout=30)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def list_memories(args):
    params = {"user_id": args.user}
    if args.agent:
        params["agent_id"] = args.agent
    if args.run:
        params["run_id"] = args.run

    resp = requests.get(f"{BASE_URL}/memory/list", params=params, timeout=30)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


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


def cleanup_expired(args):
    params = {"user_id": args.user}
    if args.agent:
        params["agent_id"] = args.agent
    resp = requests.delete(f"{BASE_URL}/memory/cleanup/expired", params=params, timeout=30)
    resp.raise_for_status()
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="mem0 Memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add memory")
    p_add.add_argument("--user", required=True)
    p_add.add_argument("--agent", default=None)
    p_add.add_argument("--run", default=None)
    p_add.add_argument("--text", default=None)
    p_add.add_argument("--messages", default=None, help="JSON array of {role, content}")
    p_add.add_argument("--metadata", default=None, help="JSON object of metadata")
    p_add.add_argument("--ttl-days", type=int, default=None, dest="ttl_days",
                       help="Short-term TTL in days (e.g. 7 for 7-day expiry)")
    p_add.add_argument("--expires-at", default=None, dest="expires_at",
                       help="Explicit expiry date YYYY-MM-DD")
    p_add.set_defaults(func=add_memory)

    # search
    p_search = sub.add_parser("search", help="Search memories")
    p_search.add_argument("--user", required=True)
    p_search.add_argument("--agent", default=None)
    p_search.add_argument("--run", default=None)
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--top-k", type=int, default=10)
    p_search.set_defaults(func=search_memory)

    # list
    p_list = sub.add_parser("list", help="List memories")
    p_list.add_argument("--user", required=True)
    p_list.add_argument("--agent", default=None)
    p_list.add_argument("--run", default=None)
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

    # cleanup
    p_cleanup = sub.add_parser("cleanup", help="Delete expired short-term memories")
    p_cleanup.add_argument("--user", required=True)
    p_cleanup.add_argument("--agent", default=None)
    p_cleanup.set_defaults(func=cleanup_expired)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
