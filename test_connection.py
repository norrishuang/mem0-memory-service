#!/usr/bin/env python3
"""
Quick smoke test: mem0 + OpenSearch + Bedrock Titan Embedding + Bedrock Claude Haiku
"""
import os

# AWS region
os.environ["AWS_REGION"] = "us-east-1"

from mem0 import Memory

config = {
    "vector_store": {
        "provider": "opensearch",
        "config": {
            "collection_name": "mem0_test",
            "host": "vpc-internal-logs-analysis-lr7bsxv3u4szmdeik722czxlki.us-east-1.es.amazonaws.com",
            "port": 443,
            "http_auth": ("admin", "Amazon123!"),
            "embedding_model_dims": 1024,
            "use_ssl": True,
            "verify_certs": True,
        },
    },
    "embedder": {
        "provider": "aws_bedrock",
        "config": {
            "model": "amazon.titan-embed-text-v2:0",
        },
    },
    "llm": {
        "provider": "aws_bedrock",
        "config": {
            "model": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "temperature": 0.1,
            "max_tokens": 2000,
        },
    },
}

print("1. Initializing Memory with config...")
m = Memory.from_config(config)
print("   ✅ Memory initialized")

print("\n2. Adding test memories...")
messages = [
    {"role": "user", "content": "I'm working on DolphinScheduler EMR Serverless plugin"},
    {"role": "assistant", "content": "That sounds like a great project! EMR Serverless is a good fit for DolphinScheduler task scheduling."},
    {"role": "user", "content": "The PR #18069 is waiting for reviewer feedback on CI AWS authentication."},
]
result = m.add(messages, user_id="boss", agent_id="dev", metadata={"project": "dolphinscheduler"})
print(f"   ✅ Added memories: {result}")

print("\n3. Searching memories...")
search_results = m.search("DolphinScheduler EMR", user_id="boss", agent_id="dev")
print(f"   ✅ Search results: {search_results}")

print("\n4. Listing all memories for user...")
all_memories = m.get_all(user_id="boss", agent_id="dev")
print(f"   ✅ Total memories: {len(all_memories.get('results', []))}")
for mem in all_memories.get("results", []):
    print(f"      - [{mem.get('id', 'N/A')[:8]}...] {mem.get('memory', 'N/A')[:80]}")

print("\n🎉 All tests passed!")
