#!/usr/bin/env python3
"""
Quick smoke test: mem0 + OpenSearch + Bedrock (or other LLM/Embedder)
Reads config from .env / environment variables via config.py.
"""
import sys
import os

# Ensure config.py is importable (parent directory)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from config import get_mem0_config, OPENSEARCH_HOST, SERVICE_PORT
from mem0 import Memory

print("🧪 mem0 Memory Service - Connection Test")
print("=========================================")
print(f"   OpenSearch: {OPENSEARCH_HOST}")

print("\n1. Initializing Memory with config...")
try:
    config = get_mem0_config()
    m = Memory.from_config(config)
    print("   ✅ Memory initialized")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

print("\n2. Adding test memory...")
try:
    result = m.add("This is a test memory for connection verification.", user_id="test_user", agent_id="test_agent")
    print(f"   ✅ Added: {result}")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

print("\n3. Searching memories...")
try:
    results = m.search("test memory", user_id="test_user", agent_id="test_agent")
    print(f"   ✅ Search returned {len(results.get('results', []))} results")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

print("\n4. Listing memories...")
try:
    all_mem = m.get_all(user_id="test_user", agent_id="test_agent")
    count = len(all_mem.get("results", []))
    print(f"   ✅ Total: {count} memories")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

# Cleanup test data
print("\n5. Cleaning up test data...")
try:
    for mem in all_mem.get("results", []):
        m.delete(mem["id"])
    print("   ✅ Test data cleaned")
except Exception as e:
    print(f"   ⚠️  Cleanup failed (non-critical): {e}")

print("\n🎉 All tests passed! The service is ready.")
