"""
Smoke test: verify retrieval_detail audit log entries are written by
/memory/search and /memory/search_combined.

This test guards against silent regression where the audit logging code
is accidentally deleted during merges (as happened in PR #133).

Usage:
    pytest tests/test_audit_retrieval.py -v

Environment variables:
    MEM0_SERVICE_URL  - service base URL (default: http://localhost:8230)
    AUDIT_LOG_DIR     - path to audit_logs directory (default: ./audit_logs)
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

SERVICE_URL = os.getenv("MEM0_SERVICE_URL", "http://localhost:8230")
AUDIT_LOG_DIR = Path(os.getenv("AUDIT_LOG_DIR", "./audit_logs"))

TEST_USER = "ci-smoke-test"
TEST_AGENT = "ci"
TEST_QUERY = "smoke test retrieval audit"


def get_today_audit_log() -> Path:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return AUDIT_LOG_DIR / f"audit-{today}.jsonl"


def read_retrieval_detail_entries(path: Path, endpoint: str) -> list[dict]:
    """Read all retrieval_detail entries for the given endpoint from audit log."""
    entries = []
    if not path.exists():
        return entries
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("event") == "retrieval_detail" and entry.get("path") == endpoint:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def test_service_health():
    """Service must be up before running audit tests."""
    resp = requests.get(f"{SERVICE_URL}/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_retrieval_detail_audit_for_search():
    """
    /memory/search must write a retrieval_detail entry to the audit log
    containing all required fields: event, path, query, results, agent_id, user_id.
    """
    audit_log = get_today_audit_log()
    count_before = len(read_retrieval_detail_entries(audit_log, "/memory/search"))

    resp = requests.post(
        f"{SERVICE_URL}/memory/search",
        json={"query": TEST_QUERY, "user_id": TEST_USER, "agent_id": TEST_AGENT, "top_k": 3},
        timeout=30,
    )
    assert resp.status_code == 200, f"search returned {resp.status_code}: {resp.text}"

    # Give the service a moment to flush the log (it's synchronous, but be safe)
    time.sleep(0.5)

    entries_after = read_retrieval_detail_entries(audit_log, "/memory/search")
    new_entries = entries_after[count_before:]

    assert len(new_entries) >= 1, (
        f"No new retrieval_detail entry found in {audit_log} for /memory/search. "
        "AUDIT_LOG_RETRIEVAL_DETAIL may be disabled or the logging code was deleted."
    )

    entry = new_entries[-1]
    for field in ("event", "path", "query", "results", "agent_id", "user_id"):
        assert field in entry, f"Required field '{field}' missing from retrieval_detail entry: {entry}"

    assert entry["event"] == "retrieval_detail"
    assert entry["path"] == "/memory/search"
    assert entry["query"] == TEST_QUERY
    assert entry["agent_id"] == TEST_AGENT
    assert entry["user_id"] == TEST_USER
    assert isinstance(entry["results"], list)


def test_retrieval_detail_audit_for_search_combined():
    """
    /memory/search_combined must write a retrieval_detail entry to the audit log
    containing all required fields: event, path, query, results, agent_id, user_id.
    """
    audit_log = get_today_audit_log()
    count_before = len(read_retrieval_detail_entries(audit_log, "/memory/search_combined"))

    resp = requests.post(
        f"{SERVICE_URL}/memory/search_combined",
        json={"query": TEST_QUERY, "user_id": TEST_USER, "agent_id": TEST_AGENT, "top_k": 3},
        timeout=30,
    )
    assert resp.status_code == 200, f"search_combined returned {resp.status_code}: {resp.text}"

    time.sleep(0.5)

    entries_after = read_retrieval_detail_entries(audit_log, "/memory/search_combined")
    new_entries = entries_after[count_before:]

    assert len(new_entries) >= 1, (
        f"No new retrieval_detail entry found in {audit_log} for /memory/search_combined. "
        "AUDIT_LOG_RETRIEVAL_DETAIL may be disabled or the logging code was deleted."
    )

    entry = new_entries[-1]
    for field in ("event", "path", "query", "results", "agent_id", "user_id"):
        assert field in entry, f"Required field '{field}' missing from retrieval_detail entry: {entry}"

    assert entry["event"] == "retrieval_detail"
    assert entry["path"] == "/memory/search_combined"
    assert entry["query"] == TEST_QUERY
    assert entry["agent_id"] == TEST_AGENT
    assert entry["user_id"] == TEST_USER
    assert isinstance(entry["results"], list)
