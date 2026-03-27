# 工作原理

本页解释端到端的记忆流转过程——从一次对话发生，到记忆在下次 session 中可用。

## 核心问题：Session 是无状态的

OpenClaw 默认每天（本地时间 4:00 AM）或空闲超时后重置 session。每次新 session 启动时，上下文窗口是空白的——没有任何历史对话记忆。

这是有意为之的设计：保持上下文新鲜，避免 token 膨胀。但这意味着 agent 需要一个外部机制来维持连续性。

**mem0 Memory Service 就是这个机制。**

## Agent 如何知道该做什么：Skill 系统

OpenClaw 内置了 skill 系统。当一个 skill 被启用后，其 `SKILL.md` 文件会在每次 session 启动时自动注入到 agent 的系统提示中。

**mem0-memory** skill 的 `SKILL.md` 包含 `🔴 Agent Memory Behavior` 章节，其中有明确的行为规则。Agent 读到这些规则后，就知道：

- 什么时候写日记（`memory/YYYY-MM-DD.md`）
- 什么时候更新 `MEMORY.md`
- 如何通过 CLI 搜索和写入 mem0

**这就是为什么不需要修改 AGENTS.md 的原因。** 启用一次 skill，每个 agent、每次 session 启动时都会自动继承这套行为规范。

```
OpenClaw 设置中启用 Skill
         │
         ▼
session 启动时，SKILL.md 注入系统提示
         │
         ▼
Agent 读到「🔴 Agent Memory Behavior」规则
         │
         ├─ 对话中 → 主动写日记条目
         └─ Heartbeat → 更新 MEMORY.md
```

## Agent 行为规范（Skill 的指令内容）

### 对话中

以下情况发生时，agent 主动写入 `memory/YYYY-MM-DD.md`：

| 触发条件 | 示例 |
|---------|------|
| 完成了任务 | 提交 PR、修复 bug、完成部署 |
| 做了技术决策 | 为什么选 A 而不是 B |
| 踩坑/发现经验 | 某次构建失败的根因 |
| 用户表达了偏好 | "总是用中文回复我" |
| 状态发生变化 | PR 被 merge、服务重启 |

日记条目格式：
```markdown
## 14:30

- 修复了 session_snapshot 重复写入 bug：从块级比较改为逐行内容比对
- PR #7 提交并 merge
```

### Heartbeat 时

每次 heartbeat 触发时，agent 按顺序执行记忆维护：

1. **写日记** — 将当次 session 的新对话追加到今天的 `memory/YYYY-MM-DD.md`
2. **回顾近期文件** — 浏览最近 2-3 天的日记，找出值得长期保留的洞察
3. **更新 MEMORY.md** — 将持久性事实提炼进 `MEMORY.md`；删除过时条目

`MEMORY.md` 是 agent 精心维护的知识库——项目卡片、当前决策、关键配置。由 agent 自己维护，不依赖自动化脚本。

## 完整记忆流转图

```
┌─────────────────────────────────────────────────────────────┐
│                           对话                               │
└────────────────┬──────────────────────┬─────────────────────┘
                 │                      │
                 ▼                      ▼
         Agent 主动写日记         session_snapshot 兜底
         （SKILL.md 指导，        （每 5 分钟自动捕获，
          高质量，精选内容）        原始对话片段）
                 │                      │
                 └──────────┬───────────┘
                            ▼
                  memory/YYYY-MM-DD.md
                  （原始日记文件）
                            │
              ┌─────────────┼──────────────┐
              │             │              │
              ▼             ▼              ▼
          Heartbeat      UTC 01:30      UTC 01:00
          （agent         auto_digest   memory_sync
           自我提炼）     （LLM 提取     （同步
                          昨日日记）     MEMORY.md）
              │             │              │
              ▼             ▼              ▼
          MEMORY.md     mem0 短期记忆   mem0 长期记忆
          （已更新）     （run_id=日期） （无 run_id）
                            │
                       UTC 02:00
                        archive
                            │
                  ┌─────────┴──────────┐
                  ▼                    ▼
            升级为长期记忆          删除
            （活跃话题）           （不活跃）
```

## 每日自动化时序

所有自动化任务以 systemd user timer 方式运行：

| 时间（UTC） | 脚本 | 做什么 |
|------------|------|--------|
| 每 5 分钟 | `session_snapshot.py` | 捕获会话对话 → 日记文件 |
| 01:00 | `memory_sync.py` | 同步 `MEMORY.md` → mem0 长期记忆（hash 去重） |
| 01:30 | `auto_digest.py` | 提取昨日完整日记 → mem0 短期记忆 |
| 02:00 | `archive.py` | 评估 7 天前短期记忆 → 升级或删除 |

## session_snapshot 的两个角色

`session_snapshot.py` 有两个用途：

**主要角色：跨 Session 记忆桥梁**
Agent 每天重置。没有 snapshot，session 之间的对话就会丢失。Snapshot 将每次对话捕获到日记文件，再由 `auto_digest.py` 提炼进 mem0。新 session 启动时，agent 从 mem0 检索相关记忆——无缝恢复上下文。

**辅助角色：Compaction 保底**
当 session 上下文窗口增长过大时，OpenClaw 会压缩（compact）历史记录。最近几分钟的对话可能在 compaction 中丢失。Snapshot 每 5 分钟运行一次，确保内容在被 compaction 丢失之前已写入磁盘。

## 日记文件的两条写入路径

由于并非所有 agent 都会主动维护日记，存在两条并行的捕获路径：

| 路径 | 写入者 | 质量 | 时机 |
|------|--------|------|------|
| **Agent 主动写** | Agent 自身（SKILL.md 指导） | 高——精选的有意义条目 | 实时，对话中 |
| **Snapshot 自动写** | `session_snapshot.py`（自动化） | 较低——原始对话片段 | 每 5 分钟，不分内容 |

两条路径都写入同一个 `memory/YYYY-MM-DD.md` 文件。内容级去重确保每条消息不重复写入。

**Agent 主动写的质量更高。** 自动化是安全网。

## 进入长期记忆的三条路径

| 路径 | 来源 | 延迟 | 适用场景 |
|------|------|------|---------|
| **memory_sync.py** | `MEMORY.md` | 当天生效 | Agent 精选知识、重要决策 |
| **auto_digest + archive** | 每日日记 | 7 天后 | 持续讨论的话题、渐进式上下文积累 |
| **CLI 主动写入** | Agent 按需调用 | 立即 | 时效性强的事实、对话中的临时决策 |

```bash
# 主动写入长期记忆（不传 --run = 长期记忆）
python3 cli.py add \
  --user boss --agent <your-agent-id> \
  --text "决定使用 S3 Vectors 作为主要向量存储" \
  --metadata '{"category":"decision"}'
```

## Session 启动：恢复上下文

新 session 启动时，skill 指导 agent 从 mem0 检索相关上下文：

```bash
# 组合搜索：长期记忆 + 最近 7 天短期记忆
python3 cli.py search \
  --user boss --agent <your-agent-id> \
  --query "<当前对话的话题关键词>" \
  --combined --recent-days 7
```

这给了 agent：
- 近期讨论（来自短期记忆，最近 7 天）
- 持久性知识（来自长期记忆：决策、经验教训、偏好）
- 团队共享知识（来自 `category=experience` 共享池，所有 agent 共享）

结果是：agent「记得」相关上下文，用户无需重新解释任何背景。

## 找到你的 Agent ID

所有 CLI 命令都需要 `--agent <your-agent-id>`。你的 agent ID 是 `openclaw.json` 中 `agents.entries` 下的键名：

```bash
cat ~/.openclaw/openclaw.json | python3 -c "
import json, sys
config = json.load(sys.stdin)
entries = config.get('agents', {}).get('entries', {})
for agent_id, cfg in entries.items():
    ws = cfg.get('workspace', 'N/A')
    print(f'  {agent_id}: workspace={ws}')
"
```

输出示例：
```
  main: workspace=/home/user/workspace-main
  dev:  workspace=/home/user/workspace-dev
  blog: workspace=/home/user/workspace-blog
```

使用键名（如 `dev`、`main`、`blog`）作为 `--agent` 的值。
