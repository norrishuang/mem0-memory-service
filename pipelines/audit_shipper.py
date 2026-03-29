#!/usr/bin/env python3
"""
audit_shipper.py - 将审计日志实时推送到 OpenSearch
- tail -f 监听 audit_logs/audit-YYYY-MM-DD.jsonl
- 每条日志推送到 mem0-audit-YYYY.MM.DD 索引（每天一个）
- 断点续传：记录已发送的行数，重启后从断点继续
"""
import json
import time
import logging
import requests
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── 配置 ───────────────────────────────────────────
AUDIT_LOG_DIR = Path(__file__).parent.parent / "audit_logs"
STATE_FILE = Path(__file__).parent.parent / ".audit_shipper_state.json"
LOG_FILE = Path(__file__).parent.parent / "audit_shipper.log"

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "vpc-internal-logs-analysis-lr7bsxv3u4szmdeik722czxlki.us-east-1.es.amazonaws.com")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "443"))
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "Amazon123!")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"

INDEX_PREFIX = "mem0-audit"
POLL_INTERVAL = 5  # 秒
BJT = timezone(timedelta(hours=8))

# ─── 日志配置 ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# ─── OpenSearch 客户端 ────────────────────────────────
SCHEME = "https" if OPENSEARCH_USE_SSL else "http"
OS_BASE = f"{SCHEME}://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}"
OS_AUTH = (OPENSEARCH_USER, OPENSEARCH_PASSWORD)
OS_HEADERS = {"Content-Type": "application/json"}


def index_name_for(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts).astimezone(BJT)
    except Exception:
        dt = datetime.now(BJT)
    return f"{INDEX_PREFIX}-{dt.strftime('%Y.%m.%d')}"


def ensure_index(index: str) -> bool:
    url = f"{OS_BASE}/{index}"
    r = requests.head(url, auth=OS_AUTH, verify=True, timeout=10)
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        mapping = {
            "mappings": {
                "properties": {
                    "ts":         {"type": "date"},
                    "method":     {"type": "keyword"},
                    "path":       {"type": "keyword"},
                    "status":     {"type": "integer"},
                    "elapsed_ms": {"type": "integer"},
                    "ip":         {"type": "ip"},
                    "agent_id":   {"type": "keyword"},
                    "user_id":    {"type": "keyword"},
                }
            }
        }
        r2 = requests.put(url, auth=OS_AUTH, headers=OS_HEADERS,
                          json=mapping, verify=True, timeout=10)
        if r2.status_code in (200, 201):
            logger.info(f"Created index: {index}")
            return True
        logger.error(f"Failed to create index {index}: {r2.status_code} {r2.text[:200]}")
    return False


def ship_doc(index: str, doc: dict) -> bool:
    url = f"{OS_BASE}/{index}/_doc"
    r = requests.post(url, auth=OS_AUTH, headers=OS_HEADERS,
                      json=doc, verify=True, timeout=10)
    return r.status_code in (200, 201)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_today_log_path() -> Path:
    today = datetime.now(BJT).strftime("%Y-%m-%d")
    return AUDIT_LOG_DIR / f"audit-{today}.jsonl"


def process_file(log_path: Path, state: dict) -> int:
    key = log_path.name
    offset = state.get(key, 0)
    shipped = 0

    if not log_path.exists():
        return 0

    with log_path.open("r", encoding="utf-8") as f:
        f.seek(0, 2)
        file_size = f.tell()

        if offset > file_size:
            logger.warning(f"File shrunk ({key}), resetting offset")
            offset = 0

        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
                idx = index_name_for(doc.get("ts", ""))
                ensure_index(idx)
                if ship_doc(idx, doc):
                    shipped += 1
                else:
                    logger.warning(f"Failed to ship: {line[:100]}")
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON line: {line[:100]}")
            except Exception as e:
                logger.error(f"Error shipping line: {e}")

        state[key] = f.tell()

    return shipped


def main():
    logger.info("audit_shipper.py started")
    logger.info(f"OpenSearch: {OS_BASE}")

    state = load_state()

    while True:
        try:
            log_path = get_today_log_path()
            n = process_file(log_path, state)
            if n > 0:
                logger.info(f"Shipped {n} records to OpenSearch")
                save_state(state)
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
