# REST API 参考

Memory Service 运行一个 FastAPI 服务器，默认端口为 `8230`。

## 接口列表

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/memory/add` | 添加记忆 |
| `POST` | `/memory/search` | 语义搜索 |
| `POST` | `/memory/search_combined` | 组合搜索（长期 + 近期短期记忆） |
| `GET` | `/memory/list` | 列出记忆 |
| `GET` | `/memory/{id}` | 获取单条记忆 |
| `PUT` | `/memory/update` | 更新记忆 |
| `DELETE` | `/memory/{id}` | 删除记忆 |
| `GET` | `/memory/history/{id}` | 记忆变更历史 |

## 健康检查

```bash
curl http://127.0.0.1:8230/health
```

```json
{"status": "ok", "service": "mem0-memory-service"}
```

## 添加记忆

```bash
# 长期记忆（文本）
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","text":"Important lesson..."}'

# 短期记忆（带 run_id）
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","run_id":"2026-03-23","text":"Today discussion..."}'

# 从对话消息添加
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"me","agent_id":"dev","messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}'
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|-------|------|----------|-------------|
| `user_id` | string | ✅ | 用户标识 |
| `agent_id` | string | | 代理标识 |
| `run_id` | string | | 短期记忆的运行 ID（`YYYY-MM-DD`） |
| `text` | string | ✅* | 要记忆的原始文本 |
| `messages` | array | ✅* | 对话消息 `[{role, content}]` |
| `metadata` | object | | 额外元数据标签 |
| `infer` | boolean | | 是否让 mem0 提炼事实（默认 `true`）。设为 `false` 则原文存储。 |
| `custom_extraction_prompt` | string | | 自定义提炼提示词，覆盖默认 prompt（仅在 `infer=true` 时生效）。详见[定向记忆抽取](#定向记忆抽取)。 |

\* `text` 或 `messages` 二选一，必须提供其一。


## 定向记忆抽取

默认情况下，mem0 使用通用的事实提炼 prompt。通过 `custom_extraction_prompt` 可以指定特定维度进行抽取，无需修改全局配置。

```bash
# 从 session block 抽取已完成工作任务
curl -X POST http://127.0.0.1:8230/memory/add \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "boss",
    "agent_id": "dev",
    "run_id": "2026-04-11",
    "text": "<session block 内容>",
    "infer": true,
    "metadata": {"category": "task"},
    "custom_extraction_prompt": "从以下对话中列出agent实际完成的工作任务（最终成果），每行一条，格式：[类型] 描述。类型：开发/修复/文档/配置/分析/部署/其他。只写最终成果，不超过5条。"
  }'
```

**使用场景：**

| 场景 | 推荐 `custom_extraction_prompt` |
|------|--------------------------------|
| 工作任务汇总 | `"列出agent实际完成的工作任务（最终成果），格式：[类型] 描述..."` |
| 技术决策记录 | `"提取重要技术决策及原因，格式：[决策] 原因..."` |
| 配置/环境发现 | `"提取新增的服务配置、端口、路径等环境信息..."` |
| 默认（不传） | mem0 使用通用提炼，适合混合内容 |

> **注意：** `custom_extraction_prompt` 仅对当次调用生效，不影响全局 mem0 配置。

## 搜索

```bash
curl -X POST http://127.0.0.1:8230/memory/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":5}'
```

## 组合搜索

搜索长期记忆 + 最近 N 天的短期记忆，合并去重后返回。

```bash
curl -X POST http://127.0.0.1:8230/memory/search_combined \
  -H 'Content-Type: application/json' \
  -d '{"query":"keywords","user_id":"me","agent_id":"dev","top_k":10,"recent_days":7}'
```

## 列出记忆

```bash
# 列出用户的所有记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev'

# 列出指定日期的短期记忆
curl 'http://127.0.0.1:8230/memory/list?user_id=me&agent_id=dev&run_id=2026-03-23'
```

## 获取 / 更新 / 删除

```bash
# 获取
curl http://127.0.0.1:8230/memory/<memory_id>

# 更新
curl -X PUT http://127.0.0.1:8230/memory/update \
  -H 'Content-Type: application/json' \
  -d '{"memory_id":"<id>","text":"Updated text"}'

# 删除
curl -X DELETE http://127.0.0.1:8230/memory/<memory_id>
```

## 记忆历史

```bash
curl http://127.0.0.1:8230/memory/history/<memory_id>
```
