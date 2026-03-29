#!/usr/bin/env python3
"""
patch_minimax_support.py - 一键为 mem0 库添加 MiniMax 模型 (Bedrock) 支持

问题：mem0 的 aws_bedrock provider PROVIDERS 列表不包含 "minimax"，
     导致使用 minimax.minimax-m2.5 时报 ValueError: Unknown provider。

修复：
  1. PROVIDERS 列表加入 "minimax"
  2. _generate_standard 方法加入 MiniMax Converse API 分支

运行方法：
  python3 patch_minimax_support.py

注意：pip install --upgrade mem0ai 后需重新执行本脚本。
"""
import os
import re
import sys

try:
    import mem0
except ImportError:
    print("❌ mem0 not installed. Run: pip install mem0ai")
    sys.exit(1)

aws_bedrock_path = os.path.join(os.path.dirname(mem0.__file__), "llms", "aws_bedrock.py")
print(f"Target file: {aws_bedrock_path}")

if not os.path.exists(aws_bedrock_path):
    print(f"❌ File not found: {aws_bedrock_path}")
    sys.exit(1)

with open(aws_bedrock_path, "r", encoding="utf-8") as f:
    content = f.read()

changed = False

# ── Patch 1: Add "minimax" to PROVIDERS list ──────────────────────────────────
if '"minimax"' not in content:
    # Find PROVIDERS = [...] and append "minimax" before closing bracket
    new_content = re.sub(
        r'(PROVIDERS\s*=\s*\[)(.*?)(\])',
        lambda m: m.group(1) + m.group(2).rstrip() + ', "minimax"' + m.group(3),
        content,
        flags=re.DOTALL,
    )
    if new_content != content:
        content = new_content
        changed = True
        print("✅ Patch 1: Added 'minimax' to PROVIDERS list")
    else:
        print("⚠️  Patch 1: Could not locate PROVIDERS list — skipping")
else:
    print("ℹ️  Patch 1: 'minimax' already in PROVIDERS — skipping")

# ── Patch 2: Add MiniMax branch in _generate_standard ────────────────────────
MINIMAX_BRANCH = '''\
        elif self.provider == "minimax":
            # MiniMax models use Bedrock Converse API
            # M2.5 is a reasoning model: content array may contain reasoningContent before text
            # Build system prompt and user/assistant messages separately for Converse API
            system_parts = []
            converse_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if not isinstance(content, str):
                    content = str(content)
                if role == "system":
                    system_parts.append(content)
                else:
                    converse_messages.append({"role": role, "content": [{"text": content}]})
            if not converse_messages:
                converse_messages = [{"role": "user", "content": [{"text": ""}]}]
            converse_params = {
                "modelId": self.config.model,
                "messages": converse_messages,
                "inferenceConfig": {
                    "maxTokens": self.model_config.get("max_tokens", 2000),
                    "temperature": self.model_config.get("temperature", 0.1),
                },
            }
            if system_parts:
                converse_params["system"] = [{"text": "\\n".join(system_parts)}]
            response = self.client.converse(**converse_params)
            # Find the first content block that has a "text" key (skip reasoningContent)
            for block in response["output"]["message"]["content"]:
                if "text" in block:
                    return block["text"]
            return ""
'''

ANCHOR = '        elif self.provider == "amazon" and "nova" in self.config.model.lower():'

if 'self.provider == "minimax"' not in content:
    if ANCHOR in content:
        content = content.replace(ANCHOR, MINIMAX_BRANCH + ANCHOR)
        changed = True
        print("✅ Patch 2: Added MiniMax branch in _generate_standard")
    else:
        print("⚠️  Patch 2: Could not locate anchor line in _generate_standard — skipping")
else:
    print("ℹ️  Patch 2: MiniMax branch already present — skipping")

# ── Write back ────────────────────────────────────────────────────────────────
if changed:
    # Backup original
    backup_path = aws_bedrock_path + ".bak"
    import shutil
    shutil.copy2(aws_bedrock_path, backup_path)
    print(f"   Backup saved: {backup_path}")

    with open(aws_bedrock_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Patch applied: {aws_bedrock_path}")
else:
    print("ℹ️  No changes needed — patch already applied or skipped.")
