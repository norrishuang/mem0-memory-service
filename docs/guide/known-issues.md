# Known Issues & Patches

mem0 has known upstream bugs that affect AWS Bedrock + OpenSearch / S3 Vectors usage. PRs have been submitted but are not yet merged. **You must apply patches manually before using this service.**

## Summary

| Issue | PR | Affects | Status |
|-------|----|---------|--------|
| OpenSearch 3.x `nmslib` engine deprecated | [#4392](https://github.com/mem0ai/mem0/pull/4392) | OpenSearch 3.0+ | Pending merge |
| Converse API `temperature` + `top_p` conflict | [#4393](https://github.com/mem0ai/mem0/pull/4393) | Claude Haiku 4.5 and newer models | ✅ Merged via [#4469](https://github.com/mem0ai/mem0/pull/4469) |
| S3Vectors invalid filter format | [#4554](https://github.com/mem0ai/mem0/pull/4554) | S3 Vectors backend | Pending merge |
| MiniMax models not recognized as valid provider | [#4609](https://github.com/mem0ai/mem0/pull/4609) | All MiniMax models on Bedrock | Pending merge |

## PR #4392: OpenSearch 3.x nmslib Engine Deprecated

mem0's OpenSearch adapter hardcodes `"engine": "nmslib"` for k-NN index creation. OpenSearch 3.0+ has deprecated the nmslib engine, causing `mapper_parsing_exception` when creating indices.

**Patch steps:**

```bash
# Locate the file
python3 -c "import mem0; import os; print(os.path.join(os.path.dirname(mem0.__file__), 'vector_stores/opensearch.py'))"

# Replace nmslib → lucene
sed -i 's/"engine": "nmslib"/"engine": "lucene"/g' <path>
```

## PR #4393: Converse API temperature + top_p Conflict

> ✅ **Resolved**: Fixed in upstream via [PR #4469](https://github.com/mem0ai/mem0/pull/4469) (merged 2025-03-25). Run `pip install --upgrade mem0ai` — no manual patch needed.

Claude Haiku 4.5 and newer models reject requests that include both `temperature` and `top_p` simultaneously. mem0 defaults `top_p=0.9`, causing `ValidationException` on Bedrock Converse API calls.

**Patch steps:**

```bash
# Locate the file
python3 -c "import mem0; import os; print(os.path.join(os.path.dirname(mem0.__file__), 'llms/aws_bedrock.py'))"
```

Edit the file: comment out the `topP` line in the Converse API `inferenceConfig` block. Also change `top_p` default to `None` in `mem0/configs/llms/aws_bedrock.py`.

## PR #4554: S3Vectors Filter Format

`s3_vectors.py`'s `_convert_filters()` generates an incorrect filter format for the S3Vectors `query_vectors` API. It produces `{"equals": {"key": "...", "value": {"stringValue": "..."}}}` instead of the required MongoDB-style `{"field": {"$eq": "value"}}`.

**Patch steps:**

```bash
# One-click patch (provided by this project)
python3 patch_s3vectors_filter.py
```

## PR #4609: MiniMax Models Not Recognized on AWS Bedrock

mem0's `aws_bedrock` LLM provider maintains an internal `PROVIDERS` allowlist. MiniMax models (e.g. `minimax.minimax-m2.5`) are not in this list, causing a `ValueError: Unknown provider in model` at startup.

There are three bugs that need to be fixed together:

**Bug 1 — `PROVIDERS` allowlist**  
`minimax` is missing from the list, so any `minimax.*` model ID raises `ValueError`.

**Bug 2 — Reasoning model response format**  
MiniMax M2.5 (and M2.1) are reasoning models. Their Bedrock Converse API response includes a `reasoningContent` block *before* the actual `text` block. Taking `content[0]["text"]` directly raises a `KeyError`.

**Bug 3 — System messages discarded**  
mem0 passes a `role=system` message instructing the LLM to return JSON. The original code only forwarded the last user message to the Converse API, silently dropping the system prompt. Without the JSON instruction, MiniMax returns free-form markdown, causing `json.JSONDecodeError` in mem0's fact-extraction pipeline.

**Patch steps:**

```bash
# One-click patch (provided by this project — fixes all 3 bugs)
python3 patch_minimax_support.py
```

**Configuration after patching:**

```env
LLM_MODEL=minimax.minimax-m2.5
DIGEST_LLM_MODEL=minimax.minimax-m2.5
```

### Why MiniMax M2.5?

We benchmarked MiniMax M2.5 against Claude Haiku 4.5 and DeepSeek V3.2 for mem0's fact-extraction workload (short text in, short JSON out) on AWS Bedrock `us-east-1`:

| Model | Avg latency | Input price | Output price | Notes |
|-------|------------|-------------|--------------|-------|
| **Claude Haiku 4.5** | ~1.0s | $1.00 / 1M tokens | $5.00 / 1M tokens | Fastest; most expensive |
| **DeepSeek V3.2** | ~2.4s | $0.62 / 1M tokens | $1.85 / 1M tokens | No clear advantage over MiniMax |
| **MiniMax M2.5** ✅ | ~2.6s | **$0.30 / 1M tokens** | **$1.20 / 1M tokens** | **Best cost; ~3× cheaper than Haiku** |

MiniMax M2.5 is our default choice: **~3× cheaper than Claude Haiku 4.5** at an acceptable ~2-3 s latency for background memory extraction tasks.

::: tip
If raw speed matters more than cost, switch back to Claude Haiku 4.5 by setting `LLM_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0`. No patch needed for Haiku.
:::

::: warning
`minimax.minimax-m2` (non-reasoning variant) does **not** work — its Converse API response contains only `reasoningContent` with no `text` block. Use **M2.1** or **M2.5** instead.
:::

## After PRs Are Merged

Once all PRs are merged upstream, simply upgrade mem0 and patches are no longer needed:

```bash
pip install --upgrade mem0ai
```

Check PR status:

```bash
gh pr view 4392 --repo mem0ai/mem0 --json state -q .state
gh pr view 4554 --repo mem0ai/mem0 --json state -q .state
gh pr view 4609 --repo mem0ai/mem0 --json state -q .state
```

::: warning
After every `pip install --upgrade mem0ai`, re-apply patches until the corresponding PR is merged.
:::
