# 已知问题与 Patch

mem0 上游有 3 个已知 bug，影响 AWS Bedrock + OpenSearch / S3 Vectors 的使用。已提交 PR 但尚未合并，**使用前需手动 patch**。

## 概览

| 问题 | PR | 影响范围 | 状态 |
|------|----|----------|------|
| OpenSearch 3.x `nmslib` 引擎废弃 | [#4392](https://github.com/mem0ai/mem0/pull/4392) | OpenSearch 3.0+ | 待合并 |
| Converse API `temperature` + `top_p` 冲突 | [#4393](https://github.com/mem0ai/mem0/pull/4393) | Claude Haiku 4.5 及更新模型 | ✅ Merged via [#4469](https://github.com/mem0ai/mem0/pull/4469) |
| S3Vectors filter 格式错误 | [#4554](https://github.com/mem0ai/mem0/pull/4554) | S3 Vectors 后端 | 待合并 |

## PR #4392：OpenSearch 3.x nmslib 引擎废弃

mem0 的 OpenSearch adapter 硬编码 `"engine": "nmslib"` 创建 k-NN 索引。OpenSearch 3.0+ 已废弃 nmslib 引擎，创建索引时报 `mapper_parsing_exception`。

**Patch 步骤：**

```bash
# 找到文件
python3 -c "import mem0; import os; print(os.path.join(os.path.dirname(mem0.__file__), 'vector_stores/opensearch.py'))"

# 替换 nmslib → lucene
sed -i 's/"engine": "nmslib"/"engine": "lucene"/g' <path>
```

## PR #4393：Converse API temperature + top_p 冲突

> ✅ **已解决**：此问题已通过 upstream PR [#4469](https://github.com/mem0ai/mem0/pull/4469) 修复（2026-03-25 合并）。`pip install --upgrade mem0ai` 即可，无需手动 patch。

Claude Haiku 4.5 等新模型不允许同时传 `temperature` 和 `top_p`。mem0 默认 `top_p=0.9`，导致 Bedrock Converse API 调用报 `ValidationException`。

**Patch 步骤：**

```bash
# 找到文件
python3 -c "import mem0; import os; print(os.path.join(os.path.dirname(mem0.__file__), 'llms/aws_bedrock.py'))"
```

编辑文件：注释掉 Converse API `inferenceConfig` 中的 `topP` 行。同时将 `mem0/configs/llms/aws_bedrock.py` 中 `top_p` 默认值改为 `None`。

## PR #4554：S3Vectors Filter 格式错误

`s3_vectors.py` 的 `_convert_filters()` 方法生成的 filter 格式不正确。传给 `query_vectors` 时报 `Invalid query filter`。S3Vectors API 要求 MongoDB 风格操作符（`{"field": {"$eq": "value"}}`），而原代码生成的是 `{"equals": {"key": "...", "value": {"stringValue": "..."}}}`。

**Patch 步骤：**

```bash
# 一键 patch（本项目提供）
python3 patch_s3vectors_filter.py
```

## PR 合并后

所有 PR 合并后，直接升级 mem0 即可，无需再手动 patch：

```bash
pip install --upgrade mem0ai
```

检查 PR 状态：

```bash
gh pr view 4392 --repo mem0ai/mem0 --json state -q .state
gh pr view 4393 --repo mem0ai/mem0 --json state -q .state
gh pr view 4554 --repo mem0ai/mem0 --json state -q .state
```

::: warning
每次 `pip install --upgrade mem0ai` 后，需重新执行 patch，直到对应 PR 合并为止。
:::
