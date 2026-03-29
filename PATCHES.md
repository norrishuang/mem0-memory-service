# mem0 Patches

记录 mem0 的已知问题和 patch 说明。当 mem0 升级版本后需要检查这些 PR 是否已合并。

## Patch 1: OpenSearch 3.x nmslib 引擎废弃

- **问题**: mem0 的 OpenSearch adapter 硬编码 `nmslib` 引擎，OpenSearch 3.0+ 已废弃，创建索引报 `mapper_parsing_exception`
- **PR**: [mem0ai/mem0#4392](https://github.com/mem0ai/mem0/pull/4392)
- **修复**: 新增 `knn_engine` / `knn_space_type` 配置项，默认 `lucene`（兼容所有版本）
- **临时 patch**: 修改 `mem0/vector_stores/opensearch.py`，将 `"engine": "nmslib"` 改为 `"engine": "faiss"` 或 `"engine": "lucene"`

```bash
# 找到文件
python3 -c "import mem0; import os; print(os.path.join(os.path.dirname(mem0.__file__), 'vector_stores/opensearch.py'))"
# 替换所有 nmslib → lucene (或 faiss)
sed -i 's/"engine": "nmslib"/"engine": "lucene"/g' <path>
```

## Patch 2: Bedrock Converse API temperature + top_p 冲突

> ✅ **已解决**：此问题已通过 upstream PR [#4469](https://github.com/mem0ai/mem0/pull/4469) 修复（2026-03-25 合并）。`pip install --upgrade mem0ai` 即可，无需手动 patch。

- **问题**: Claude Haiku 4.5 等新模型不允许同时传 `temperature` 和 `top_p`，mem0 默认 `top_p=0.9` 导致 `ValidationException`
- **PR**: [mem0ai/mem0#4393](https://github.com/mem0ai/mem0/pull/4393)
- **修复**: `top_p` 默认值改为 `None`，Converse API 调用仅在用户显式设置时才传 `topP`
- **临时 patch**: 修改 `mem0/llms/aws_bedrock.py`，注释掉 Converse API `inferenceConfig` 中的 `topP` 行；以及 `mem0/configs/llms/aws_bedrock.py` 中 `top_p` 默认值改为 `None`

```bash
# 找到文件
python3 -c "import mem0; import os; print(os.path.join(os.path.dirname(mem0.__file__), 'llms/aws_bedrock.py'))"
# 手动编辑，或等 PR 合并后升级 mem0
```

## Patch 3: S3Vectors Filter Format

- **问题**: `s3_vectors.py` 的 `_convert_filters()` 方法生成的 filter 格式不正确，传给 `query_vectors` 时报 `Invalid query filter`。S3Vectors API 要求 MongoDB-style 操作符（`{"field": {"$eq": "value"}}`），而原代码生成的是 `{"equals": {"key": "...", "value": {"stringValue": "..."}}}`
- **PR**: [mem0ai/mem0#4554](https://github.com/mem0ai/mem0/pull/4554)
- **修复**: `_convert_filters()` 改用 `$eq` 操作符，多条件用 `$and` 组合
- **一键 patch**: 项目提供了 `patch_s3vectors_filter.py` 脚本

```bash
python3 patch_s3vectors_filter.py
```

> ⚠️ `pip upgrade mem0ai` 后需重新执行 patch，直到 PR 合并为止。

## Patch 4: 添加 MiniMax M2.5 模型支持 (Bedrock)

- **问题**: mem0 的 `aws_bedrock` provider 的 `PROVIDERS` 列表不包含 `minimax`，导致使用 `minimax.minimax-m2.5` 时报 `ValueError: Unknown provider`；另外 MiniMax M2.5 是推理模型，响应 `content` 数组中第一个是 `reasoningContent`，不能直接取 `[0]["text"]`
- **修复**: 在 `mem0/llms/aws_bedrock.py` 中：
  1. `PROVIDERS` 列表加入 `"minimax"`
  2. `_generate_standard` 方法加入 MiniMax Converse API 分支，遍历 content blocks 找第一个含 `text` 的块（跳过 reasoningContent）
- **一键 patch**：
  ```bash
  python3 patch_minimax_support.py
  ```

> ⚠️ `pip install --upgrade mem0ai` 后需重新执行本脚本，直到 mem0 官方支持 MiniMax 为止。

## 检查 PR 状态

```bash
gh pr view 4392 --repo mem0ai/mem0 --json state -q .state
gh pr view 4554 --repo mem0ai/mem0 --json state -q .state
```

当所有 PR 都 `MERGED` 后，直接 `pip install --upgrade mem0ai` 即可，无需再手动 patch。
