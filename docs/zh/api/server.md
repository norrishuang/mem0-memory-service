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

\* `text` 或 `messages` 二选一，必须提供其一。

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
