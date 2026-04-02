# CLI Reference

The CLI client (`cli.py`) communicates with the Memory Service REST API at `http://127.0.0.1:8230`.

## Commands

### `add` — Add Memory

```bash
# Long-term memory
python3 cli.py add --user me --agent dev --text "Important lesson learned..."

# With metadata
python3 cli.py add --user me --agent dev --text "..." \
  --metadata '{"category":"experience"}'

# Short-term memory (with run_id)
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --text "Today's discussion about refactoring"

# From conversation messages (mem0 auto-extracts key facts)
python3 cli.py add --user me --agent dev --run 2026-03-23 \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
```

| Flag | Required | Description |
|------|----------|-------------|
| `--user` | ✅ | User identifier |
| `--agent` | | Agent identifier |
| `--run` | | Run ID (`YYYY-MM-DD`) for short-term memory |
| `--text` | ✅* | Raw text to memorize |
| `--messages` | ✅* | JSON array of `{role, content}` messages |
| `--metadata` | | JSON object of metadata tags |

\* Either `--text` or `--messages` is required.

### `search` — Semantic Search

```bash
# Search long-term memories
python3 cli.py search --user me --agent dev --query "refactoring" --top-k 5

# Filter low-relevance results (recommended)
python3 cli.py search --user me --agent dev --query "refactoring" --min-score 0.4

# Search specific date's short-term memories
python3 cli.py search --user me --agent dev --run 2026-03-23 --query "discussion"

# Combined search (long-term + recent 3 days short-term)
python3 cli.py search --user me --agent dev --query "refactoring" \
  --combined --recent-days 3
```

| Flag | Required | Description |
|------|----------|-------------|
| `--user` | ✅ | User identifier |
| `--agent` | | Agent identifier |
| `--query` | ✅ | Natural language search query |
| `--top-k` | | Max results (default: `5`) |
| `--min-score` | | Minimum similarity score 0.0–1.0 (default: `0.0`). Recommended: `0.3`–`0.5` to cut noise |
| `--run` | | Filter by specific run ID |
| `--combined` | | Enable combined search mode |
| `--recent-days` | | Days to include in combined search (default: `3`) |

### `list` — List Memories

```bash
python3 cli.py list --user me --agent dev
python3 cli.py list --user me --agent dev --run 2026-03-23
```

### `get` — Get Memory by ID

```bash
python3 cli.py get --id <memory_id>
```

### `delete` — Delete Memory

```bash
python3 cli.py delete --id <memory_id>
```

### `history` — View Change History

```bash
python3 cli.py history --id <memory_id>
```
