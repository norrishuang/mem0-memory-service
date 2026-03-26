# Known Issues & Patches

mem0 has 3 known upstream bugs that affect AWS Bedrock + OpenSearch / S3 Vectors usage. PRs have been submitted but are not yet merged. **You must apply patches manually before using this service.**

## Summary

| Issue | PR | Affects | Status |
|-------|----|---------|--------|
| OpenSearch 3.x `nmslib` engine deprecated | [#4392](https://github.com/mem0ai/mem0/pull/4392) | OpenSearch 3.0+ | Pending merge |
| Converse API `temperature` + `top_p` conflict | [#4393](https://github.com/mem0ai/mem0/pull/4393) | Claude Haiku 4.5 and newer models | ✅ Merged via [#4469](https://github.com/mem0ai/mem0/pull/4469) |
| S3Vectors invalid filter format | [#4554](https://github.com/mem0ai/mem0/pull/4554) | S3 Vectors backend | Pending merge |

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

## After PRs Are Merged

Once all PRs are merged upstream, simply upgrade mem0 and patches are no longer needed:

```bash
pip install --upgrade mem0ai
```

Check PR status:

```bash
gh pr view 4392 --repo mem0ai/mem0 --json state -q .state
gh pr view 4393 --repo mem0ai/mem0 --json state -q .state
gh pr view 4554 --repo mem0ai/mem0 --json state -q .state
```

::: warning
After every `pip install --upgrade mem0ai`, re-apply patches until the corresponding PR is merged.
:::
