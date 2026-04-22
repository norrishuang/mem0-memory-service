# 工作原理

本页解释端到端的记忆流转过程——从一次对话发生，到记忆在下次 session 中可用。

## 设计理念一览

| 设计理念 | 含义 | 核心机制 |
|---|---|---|
| **Session 重置零盲区** | 无论 session 何时结束，对话内容不丢失 | 今日日记 + 昨日日记 + mem0 三路覆盖，消除所有时间窗口空白 |
| **短期→长期两级记忆** | 近期内容独立隔离，只有经过验证的事实才升级为长期记忆 | `auto_digest` 以 `run_id=today` 写入（有界去重）；`auto_dream` 在 UTC 02:00 执行全局去重并晋升 |
| **按 category 定向抽取** | 不同记忆类型需要不同的抽取视角 | 每次 `/memory/add` 可传 `custom_extraction_prompt`；`auto_digest` 对每个 session block 自动执行任务专项 pass |
| **双路日记写入** | Agent 主动写入质量高；自动化是兜底保障 | Agent 实时写日记；`session_snapshot` 每 5 分钟兜底抓取 |
| **语义检索，非关键词匹配** | 按语义含义查找记忆，无需精确措辞 | 向量相似度 + 时间衰减混合排序（`0.7 × 相似度 + 0.3 × 新鲜度`） |
| **跨 Agent 知识共享** | 一个 Agent 的经验教训，所有 Agent 即时受益 | `category=experience` / `procedural` 自动写入共享池；每次搜索自动包含共享池结果 |
| **放量写入，自动去重** | Agent 无需担心重复，mem0 内部处理 | `infer=True` 触发内部 fact extraction；同日去重由 `run_id` 边界隔离 |
| **三条路径通往长期记忆** | 不同来源以不同速度落入长期记忆 | CLI 直写（即时）→ `memory_sync`（当日）→ `auto_dream`（7 天周期） |
| **多 Session、多 Agent 连续性** | 群聊里发生的事，私聊 session 也能感知 | `session_snapshot` 覆盖所有 `agent:{id}:*` session；约 20 分钟传播延迟 |

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
              ┌─────────────┼──────────────┬──────────────┐
              │             │              │              │
              ▼             ▼              ▼              ▼
          Heartbeat      每 15 分钟     UTC 02:00      UTC 01:00
          （agent        auto_digest   auto_dream     memory_sync
           自我提炼）    --today       （Step1:        （同步
                         (infer=True,   昨日日记 +     MEMORY.md）
                          DIGEST_       Step2: 7天STM）
                          EXTRACTION_
                          PROMPT)
              │             │              │              │
              ▼             ▼              ▼              ▼
          MEMORY.md     mem0 短期记忆  mem0 短期记忆  mem0 长期记忆
          （已更新）     （今日，       （昨日，        （无 run_id）
                          约 20 分钟    次日生效）
                          延迟）
                             │
                        UTC 02:00
                        AutoDream
                             │
                   ┌─────────┴──────────┐
                   ▼                    ▼
             Step 1: 消化            Step 2: 整合
             昨日日记               7天前短期记忆
             → 长期记忆             → re-add 长期
             (infer=True)          (infer=True) + 删除
```

## 部署方式：Docker vs. systemd

记忆管线脚本（`session_snapshot`、`auto_digest`、`auto_dream`、`memory_sync`）无论哪种部署方式都以相同逻辑运行，区别仅在于进程管理器：

| | Docker（推荐） | systemd |
|---|---|---|
| **API 服务** | `mem0-api` 容器 | systemd service |
| **管线执行** | `mem0-pipeline` 容器（cron） | systemd user timers |
| **日记文件访问** | 通过 bind mount `~/.openclaw → /openclaw` | 直接文件系统 |
| **补丁管理** | 构建时自动应用 | 手动 `python3 tools/patch_s3vectors_filter.py` |
| **崩溃重启** | `restart: unless-stopped` | systemd `Restart=on-failure` |

部署详情参见 [Docker 部署](../deploy/docker) 或 [systemd 部署](../deploy/systemd)。

## 每日自动化时序

| 时间（UTC） | 脚本 | 做什么 |
|------------|------|--------|
| 每 5 分钟 | `pipelines/session_snapshot.py` | 捕获会话对话 → 日记文件 |
| 每 15 分钟 | `pipelines/auto_digest.py --today` | 增量模式：读取日记新增内容 → mem0 短期记忆（infer=True，fact extraction）+ 任务专项 pass（custom_extraction_prompt → category=task） |
| 01:00 | `pipelines/memory_sync.py` | 同步 `MEMORY.md` → mem0 长期记忆（hash 去重） |
| 02:00 | `pipelines/auto_dream.py` | **AutoDream**：Step1: 昨日日记 → mem0 长期记忆（infer=True）；Step2: 7天前短期记忆 → re-add 到长期（infer=True）后删除 |

> Docker 部署中，这些脚本以 cron 任务的形式在 `mem0-pipeline` 容器内运行；systemd 部署中，以用户 timer 形式运行。两种方式的调度时间和行为完全一致。

## auto_digest 模式

`auto_digest.py` 只有一种活跃模式：

**`--today` 增量模式（每 15 分钟）**
基于 offset 记录，每次只读取日记文件自上次运行以来的新增内容。以 `infer=True` 配合专属的 `DIGEST_EXTRACTION_PROMPT` 写入 mem0——该 prompt 专为工程师工作日记设计，重点保留技术标识符（项目名、集群 ID、服务名、端口号、路径）、性能数据、工作进展、关键决策和踩坑经验。提炼阈值为 2000 字节（从 5000 降低，以捕获较短但有意义的工作片段）。写入失败时保留 offset，下次从同一断点续传。

```
每 15 分钟 (--today)：  日记新增内容 → POST 给 mem0（infer=True，DIGEST_EXTRACTION_PROMPT）
                       + 任务专项 pass（TASK_EXTRACTION_PROMPT → category=task）
```

> **注**：之前的默认全量模式（UTC 01:30，LLM 提取昨日日记 → mem0 短期记忆）已被 `auto_dream.py` Step 1 取代——后者直接写入长期记忆（无 run_id），质量更高。

### 定向抽取 Pass（category=task）

每个 session block 写入短期记忆后，`auto_digest` 立即执行第二轮专项抽取，使用**任务维度的 `custom_extraction_prompt`**：

```
Session block
  ├─ 第①轮  infer=True（默认 prompt）→ category=short_term   （通用事实）
  └─ 第②轮  infer=True + custom_extraction_prompt → category=task  （已完成工作任务）
```

第②轮只抽取最终完成的工作成果，格式为 `[类型] 描述`（例如 `[开发] 实现了 X 功能，PR #129 已开`）。这让"最近做了哪些工作"类查询精准命中任务条目，而不是散碎的事实片段。

**扩展到其他分类：** 同样的模式适用于任意 category。在任何 `/memory/add` 调用中传入 `custom_extraction_prompt`，即可按需提炼决策、配置变更或自定义维度的记忆——不影响全局 mem0 配置。

## session_snapshot 的两个角色

`session_snapshot.py` 有两个用途：

**主要角色：跨 Session 记忆桥梁**
Agent 每天重置。没有 snapshot，session 之间的对话就会丢失。Snapshot 将每次对话捕获到日记文件，再由 `auto_digest.py` 提炼进 mem0。新 session 启动时，agent 从 mem0 检索相关记忆——无缝恢复上下文。

**辅助角色：Compaction 保底**
当 session 上下文窗口增长过大时，OpenClaw 会压缩（compact）历史记录。最近几分钟的对话可能在 compaction 中丢失。Snapshot 每 5 分钟运行一次，确保内容在被 compaction 丢失之前已写入磁盘。

**第三个角色：近实时跨 session 记忆共享**
同一个 agent 可能有多个并发 session——一个单聊 session 和一个或多个群聊 session。没有共享机制的话，agent 在群聊里说的内容，单聊 session 完全看不到（反之亦然）。

`session_snapshot.py` 每 5 分钟将新对话写入日记文件，`auto_digest.py --today` 再每 15 分钟增量读取日记新增内容，以 `infer=True` 写入 mem0 短期记忆（run_id=今天，fact extraction）。同一 agent 的其他 session 搜索 mem0 即可在约 **20 分钟内**（5 分钟 snapshot + 15 分钟 digest）获取到这些内容——无需重启 session。

session 来源记录在 metadata 的 `session_key` 字段中，需要时可按来源过滤。

## 日记文件的两条写入路径

由于并非所有 agent 都会主动维护日记，存在两条并行的捕获路径：

| 路径 | 写入者 | 质量 | 时机 |
|------|--------|------|------|
| **Agent 主动写** | Agent 自身（SKILL.md 指导） | 高——精选的有意义条目 | 实时，对话中 |
| **Snapshot 自动写** | `session_snapshot.py`（自动化） | 较低——原始对话片段 | 每 5 分钟，不分内容 |

两条路径都写入同一个 `memory/YYYY-MM-DD.md` 文件。内容级去重确保每条消息不重复写入。

**Agent 主动写的质量更高。** 自动化是安全网。

> **群聊 session 现已纳入捕获范围。** 之前 snapshot 只捕获 `main`（单聊）session。现在处理所有匹配 `agent:{id}:*` 的 session——群聊对话同样写入日记文件和 mem0，实现同一 agent 跨上下文的记忆共享。

## 进入长期记忆的三条路径

| 路径 | 来源 | 延迟 | 适用场景 |
|------|------|------|---------|
| **memory_sync.py** | `MEMORY.md` | 当天生效 | Agent 精选知识、重要决策 |
| **auto_digest + AutoDream** | 每日日记 | 7 天后 | 持续讨论的话题、渐进式上下文积累 |
| **CLI 主动写入** | Agent 按需调用 | 立即 | 时效性强的事实、对话中的临时决策 |

```bash
# 主动写入长期记忆（不传 --run = 长期记忆）
python3 cli.py add \
  --user boss --agent <your-agent-id> \
  --text "决定使用 S3 Vectors 作为主要向量存储" \
  --metadata '{"category":"decision"}'
```

## 跨 Agent 记忆共享

记忆服务最强大的功能之一是通过 `shared` 用户空间实现的**自动跨 Agent 知识共享**。

### 工作原理

当任何 Agent 写入 `category=experience` 或 `category=procedural` 的记忆时，CLI 会自动将一份副本写入共享知识库（`user_id=shared`）。无需额外操作。

```bash
# 自动同时写入该 Agent 的个人空间和 user_id=shared
python3 cli.py add \
  --user boss --agent dev \
  --text "kiro-cli: 必须用 exec(pty=true, background=true, workdir=...)，不能在 command 里加 &" \
  --metadata '{"category":"procedural"}'
```

### 搜索时自动包含共享库结果

每次搜索（`/memory/search` 和 `/memory/search_combined`）都会自动包含 `user_id=shared` 的结果，无论哪个 Agent 在搜索。这在 server 层透明完成，调用方无需额外请求。

```
Agent A 写入 experience → 个人空间 + shared 库
                                        │
                                        ▼
                         Agent B 搜索相关话题
                         → 自动获得 Agent A 的经验
                         （结果标记 memory_type="shared"）
```

这意味着：
- 某个 Agent 发现了 bug 修复方法或正确操作流程，**所有 Agent 立刻受益**
- 无需手动在 Agent 间传播知识
- 共享结果带有 `"memory_type": "shared"` 标记，Agent 可以区分来源

### Memory Category 参考

| category | 用途 | 是否共享 | 示例 |
|----------|------|---------|------|
| `experience` | 踩坑记录、bug 修复、事后复盘 | ✅ 自动共享 | "PR #94 修复了搜索不包含 shared 库的问题——根因是缺少 _search_shared() 调用" |
| `procedural` | 操作步骤指南、正确工具用法 | ✅ 自动共享 | "kiro-cli：exec(pty=true, background=true, workdir=...)——不能在 command 里加 &" |
| `project` | 项目状态、进展 | ❌ Agent 专属 | "mem0-memory-service 端口 8230，systemd: mem0-memory.service" |
| `decision` | 技术决策及原因 | ❌ Agent 专属 | "选 pgvector 而非 OpenSearch 用于本地开发：成本低、配置简单" |
| `environment` | 服务地址、配置、路径 | ❌ Agent 专属 | "EC2 us-east-1，LLM 和 Embedding 使用 AWS Bedrock" |
| `preference` | 用户习惯和沟通偏好 | ❌ Agent 专属 | "用中文沟通，简洁直接" |
| `short_term` | 今天的讨论、临时任务记录 | ❌ Agent 专属 | "今天讨论了 issue #93 token 优化方案" |

> **`experience` vs `procedural` 的区别**：`experience` = "发生了什么 + 怎么解决的"（事后复盘型）。`procedural` = "如何正确做某件事"（可复用操作指南型）。判断方法：读起来像事故复盘 → `experience`；读起来像操作手册 → `procedural`。

---

## 搜索排序

### 分数归一化

不同向量引擎返回的分数语义不同：

| 向量引擎 | 原始分数含义 | 归一化处理 |
|---|---|---|
| **OpenSearch** | 相似度（越大越相关） | 直接透传 |
| **pgvector** | 余弦距离（越小越相关） | `1 - distance` |
| **S3 Vectors** | 余弦距离（越小越相关） | `1 - distance` |

服务在执行 `min_score` 过滤、时间衰减加权和返回结果之前，会自动将所有分数归一化为统一的**相似度区间 [0, 1]**（越大越相关），确保无论使用哪种向量引擎，行为都保持一致。

### 时间衰减加权

默认情况下，搜索结果按**向量相似度**与**时间新鲜度**的混合得分排序。这避免了较旧、可能已过时的记忆排名高于更新、更相关的记忆。

### 计算公式

```
final_score = 0.7 × 向量相似度 + 0.3 × 时间衰减权重

时间衰减权重 = 0.5 ^ (距今天数 / 30)
# 30 天前的记忆，时间权重约 0.5x
# 7 天前的记忆，时间权重约 0.85x
# 1 天前的记忆，时间权重约 0.98x
```

### 返回结果的变化

启用时间衰减后，每条结果都会包含 `original_score`（原始向量相似度）和最终的混合 `score`：

```json
{
  "id": "...",
  "memory": "kiro-cli 不能在 command 里加 &",
  "score": 0.87,
  "original_score": 0.83,
  "created_at": "2026-04-06T09:00:00Z"
}
```

### 关闭时间衰减

在请求体中传 `time_decay: false` 可以退回纯向量相似度排序（例如搜索历史记录时，时效性不重要）：

```bash
curl -X POST http://localhost:8230/memory/search \
  -H "Content-Type: application/json" \
  -d '{"query": "...", "user_id": "boss", "agent_id": "dev", "time_decay": false}'
```

---

## Session 启动：恢复上下文

### 为什么今天和昨天的日记文件都要读

新 session 启动时，skill 指导 agent 先读**两个日记文件**，再查 mem0：

```
Session 启动
  ├── 读 memory/今天.md      ← 今天的原始日记（实时，尚未进 mem0）
  ├── 读 memory/昨天.md      ← 昨天的原始日记（覆盖时间窗口盲区）
  └── search mem0 --combined ← 提炼后的记忆（长期 + 近期短期记忆）
```

**为什么要读今天的日记？**
`auto_dream.py` Step 1 在 UTC 02:00 运行，处理的是*昨天*的完整日记。今天发生的所有事情还没有被提炼——只存在于 `memory/今天.md` 里。Session 重置后，读这个文件是恢复当天上下文的唯一途径。

**为什么要读昨天的日记？**
存在一个覆盖盲区：昨天深夜的对话，到 `auto_dream` 完成运行（UTC 02:00）之间的时间窗口。例如：

```
昨天 23:50  发生了重要讨论 → 写入 memory/昨天.md
今天 00:10  Session 重置，新 session 启动
今天 02:00  auto_dream 运行 → 昨天日记进入 mem0 长期记忆
```

如果新 session 在 02:00 之前启动，mem0 里还没有昨晚的内容。直接读 `memory/昨天.md` 可以覆盖这个盲区。

**完整的时间覆盖地图：**

| 时间窗口 | 覆盖手段 |
|---------|---------|
| 今天（T+0） | `memory/今天.md`（实时） |
| 昨天深夜到今天 02:00 | `memory/昨天.md`（盲区缓冲） |
| 昨天 02:00 之后 | mem0 长期记忆（AutoDream Step1 提炼） |
| 最近 7 天 | mem0 短期记忆（`--combined`） |
| 7 天以上 | mem0 长期记忆（AutoDream 整合后） |

三个来源组合——今天日记 + 昨天日记 + mem0——在所有 session 重置场景下实现**零盲区**覆盖。

### mem0 检索

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

## AutoDream：沉睡的大脑

> *「每天夜里，当 Agent 进入「睡眠」，它的记忆正在被悄悄整理、晋升和精简——就像人类大脑在 REM 睡眠中所做的事情。」*

记忆管道分两个阶段，灵感来自人类记忆巩固机制：

- **Auto Digest（潜意识）** — 每 15 分钟持续运行，将新日记内容通过双 Pass 提取写入短期记忆
- **Auto Dream（深度睡眠）** — 每晚 UTC 02:00 运行一次，完成跨日规律反思、将 7 天前短期记忆晋升为长期、并清除长期记忆中的冗余

两个阶段均无需人工干预。Agent 第二天醒来时，拥有更丰富、更有条理的记忆。

完整的设计说明、流程拆解和真实端到端示例，请参见 **[AutoDream：沉睡的大脑](./auto-dream)**。

---

## 可视化监控

如需通过 Web 界面浏览、搜索和管理记忆，请参见 [可视化监控](./memory-dashboard)。
