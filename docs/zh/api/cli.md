# CLI 参考

CLI 客户端（`cli.py`）通过 REST API 与 Memory Service 通信，默认地址为 `http://127.0.0.1:8230`。

## 命令

### `add` — 添加记忆

```bash
# 长期记忆
python3 cli.py add --user me --agent dev --text "Important lesson learned..."

# 附带元数据
python3 cli.py add --user me --agent dev --text "..." \
  --metadata '{"category":"experience"}'

# 短期记忆（带 run_id）
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "Today's discussion about refactoring"

# 从对话消息添加（mem0 自动提取关键事实）
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
```

| 参数 | 必填 | 说明 |
|------|----------|-------------|
| `--user` | ✅ | 用户标识 |
| `--agent` | | 代理标识 |
| `--run` | | 运行 ID（`YYYY-MM-DD`），用于短期记忆 |
| `--text` | ✅* | 要记忆的原始文本 |
| `--messages` | ✅* | `{role, content}` 消息的 JSON 数组 |
| `--metadata` | | 元数据标签的 JSON 对象 |

\* `--text` 或 `--messages` 二选一，必须提供其一。

### `search` — 语义搜索

```bash
# 搜索长期记忆
python3 cli.py search --user me --agent dev --query "refactoring" --top-k 5

# 搜索指定日期的短期记忆
python3 cli.py search --user me --agent dev --run 2026-03-23 --query "discussion"

# 组合搜索（长期记忆 + 最近 7 天短期记忆）
python3 cli.py search --user me --agent dev --query "refactoring" \
  --combined --recent-days 7
```

| 参数 | 必填 | 说明 |
|------|----------|-------------|
| `--user` | ✅ | 用户标识 |
| `--agent` | | 代理标识 |
| `--query` | ✅ | 自然语言搜索查询 |
| `--top-k` | | 最大返回结果数（默认：10） |
| `--run` | | 按指定运行 ID 过滤 |
| `--combined` | | 启用组合搜索模式 |
| `--recent-days` | | 组合搜索包含的天数（默认：7） |

### `list` — 列出记忆

```bash
python3 cli.py list --user me --agent dev
python3 cli.py list --user me --agent dev --run 2026-03-23
```

### `get` — 按 ID 获取记忆

```bash
python3 cli.py get --id <memory_id>
```

### `delete` — 删除记忆

```bash
python3 cli.py delete --id <memory_id>
```

### `history` — 查看变更历史

```bash
python3 cli.py history --id <memory_id>
```
