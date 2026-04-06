# 最佳实践：借助 Agent 提升记忆质量

部署 mem0 Memory Service 之后，真正的价值来自于**调教好你的 Agent**，让它主动使用记忆系统。本文提供可直接复制粘贴给 OpenClaw Agent 的提示词。

## 核心原则：静态 vs 动态分离

OpenClaw 会把所有 Project Context 文件（MEMORY.md、SOUL.md、AGENTS.md 等）全量注入每次 session 的 context，这是 token 浪费的最大来源：

```
优化前：
  MEMORY.md（完整版，80+ 行）→ 每次 session 全量加载，不管任务是什么
  = 90% 的内容与当前任务无关

优化后：
  MEMORY.md（骨架版，~25 行）→ 只保留稳定索引
  mem0（动态记忆）→ 按相关性按需召回
  = 每次任务只加载相关的上下文
```

**MEMORY.md 内容取舍标准：**

| 留在 MEMORY.md | 移到 mem0 |
|---|---|
| 项目名称 + GitHub URL + 本地路径 | PR 状态、近期进展 |
| 服务端口、systemd 服务名 | 技术决策及原因 |
| 关键团队成员的 ID | 踩坑记录、经验教训 |
| 一句话项目描述 | 工作流规范细节 |
| | 待办事项（用 GitHub Issues 代替）|

**目标：每个 agent 的 MEMORY.md 控制在 30 行以内。仅此一项可节省 MEMORY.md 60–80% 的 token。**

---

## 一次性初始化（部署后执行一次）

### 1. 精简 MEMORY.md

> ⚠️ **注意：** `MEMORY.md` 是 **OpenClaw workspace 配置文件**，路径在 `~/.openclaw/workspace-&lt;agent&gt;/MEMORY.md`。它**不属于** mem0 Memory Service 本身，而是你的 OpenClaw 安装目录里的文件。需要你（或你的 Agent）直接在该路径下修改。

`MEMORY.md` 应该只保留稳定的索引骨架信息——项目名称、GitHub URL、服务端口、关键路径。动态状态（任务进展、决策记录、经验教训）应该存入 mem0。

**为什么重要：** OpenClaw 每次 session 启动时都会把完整的 `MEMORY.md` 注入 context。臃肿的 MEMORY.md 意味着每次 session 浪费数百个 token，即使当前任务与其中 90% 的内容毫无关系。

**把这段提示词发给你的 Agent：**

```
请帮我 review 并精简所有 Agent 的 MEMORY.md 文件。

文件路径：~/.openclaw/workspace-&lt;agent&gt;/MEMORY.md
（每个 agent 一份，请检查全部）

目标：
1. 只保留稳定的结构性信息：
   - 项目名称 + GitHub URL + 本地工作区路径
   - 服务端口和 systemd 服务名
   - 关键团队成员 ID（open_id 等）
   - 一句话项目描述
2. 移除频繁变化的内容：
   - 任务进展、PR 状态、近期决策
   - 日常记录、工作流规范细节
   - 踩坑记录、经验教训
   - 待办事项（改用 GitHub Issues 跟踪）
3. 移除的内容如果有长期保留价值，写入 mem0：
   - 经验/踩坑 → category=experience（自动共享给所有 agent）
   - 项目决策 → category=decision
   - 项目状态 → category=project

目标：每个 MEMORY.md 控制在 30 行以内。

完成后按 agent 汇报：
- 精简前 → 精简后行数
- 移入 mem0 的内容（使用的 category）
- 直接删除的内容（原因）
```

---

### 2. 为所有 Agent 的 HEARTBEAT.md 添加 Experience 写入规范

每个 Agent 的 `HEARTBEAT.md` 都应该包含明确的规则，说明什么时候要把 `category=experience` 的记忆写入共享知识库。

**把这段提示词发给你的 Agent：**

```
请检查所有 OpenClaw workspace 下的 HEARTBEAT.md 文件（通常在 ~/.openclaw/workspace-*/HEARTBEAT.md）。

对于没有"experience 记忆写入"章节的 HEARTBEAT.md，添加以下内容：

---
## Experience 记忆写入（每次 heartbeat + session 结束前）

回顾最近的工作，触发以下任一条件时必须写入 category=experience：

- 修复了 bug 或发现了踩坑（记录：现象、根因、解决方法）
- 做了技术决策（记录：为什么选 A 而非 B）
- 发现了更好的工具/工作流用法
- 经过长时间讨论才达成的重要结论

不需要写入：日常任务完成、一次性操作、已在 MEMORY.md 稳定骨架中的信息。

python3 /path/to/mem0-memory-service/cli.py add \
  --user boss --agent &lt;你的-agent-id&gt; \
  --text "<背景>：<结论/解决方法>" \
  --metadata '{"category":"experience"}'
---

告诉我哪些文件已更新、哪些已有该章节。
```

---

### 3. 验证记忆管道健康状态

检查自动化管道（session 快照 → 日记 → digest → mem0）是否正常运行。

**把这段提示词发给你的 Agent：**

```
请检查 mem0 记忆管道的健康状态：

1. 检查 systemd timer 状态：systemctl --user status mem0-snapshot.timer mem0-digest.timer mem0-dream.timer
2. 检查今天的日记文件是否存在：memory/YYYY-MM-DD.md
3. 检查 auto_digest 最近一次运行时间：查看 auto_digest.log 或 auto_digest_offset.json
4. 搜索 mem0 中的近期记忆：python3 cli.py search --user boss --agent &lt;your-agent&gt; --query "近期工作" --combined --recent-days 3
5. 检查共享库是否有记录：python3 cli.py search --user shared --query "experience"

如发现问题或空缺，详细汇报。
```

---

## 持续优化（定期执行）

### 4. 审计共享知识库健康状态

共享库（`user_id=shared`，`category=experience`）是跨 Agent 的知识库，应该随时间不断积累。

**每周把这段提示词发给你的 Agent：**

```
请审计共享记忆库的健康状态：

1. 统计共享库总记忆数：python3 cli.py list --user shared
2. 查看哪些 agent 写入了共享库（看结果中的 agent_id）
3. 搜索最近的 experience 记录：python3 cli.py search --user shared --query "experience 经验 踩坑" --combined --recent-days 7
4. 找出最近没有写入共享库的 agent

如发现某些 agent 没有写入记录，检查其 HEARTBEAT.md 是否有 experience 写入规范，没有的话补上。

汇报：共享库总记忆数、各 agent 覆盖情况、缺口。
```

---

### 5. 记忆质量 Review

低质量记忆是 token 负担而非助力。定期清理。

**每月把这段提示词发给你的 Agent：**

```
请 review mem0 中的记忆质量：

1. 列出所有长期记忆：python3 cli.py list --user boss --agent &lt;your-agent&gt;
2. 识别以下类型的低质量记忆：
   - 过于模糊（如"讨论了项目 X"但没有可操作的细节）
   - 已过时（指向已解决的问题、已废弃的决策）
   - 重复（同一个事实被略有不同地存了多次）
3. 过时/重复的记录直接删除：python3 cli.py delete --id <memory_id>
4. 模糊的记录考虑改写，加入更具体的背景

汇报：review 总数、删除数、改写数。
```

---

### 6. 诊断日记空档期（缺失日期）

如果管道曾中断（服务重启、路径配置错误），某些日期的日记会缺失，那几天的对话就没有被提炼进 mem0。

**把这段提示词发给你的 Agent：**

```
请检查记忆日记是否有空档：

1. 列出所有日记文件：ls memory/*.md | sort
2. 检查最近 30 天是否有缺失日期
3. 对于缺失日期，检查当天是否有活跃的 OpenClaw session
4. 如果有重要的空档期，考虑是否需要从 session 历史回填

汇报：日记覆盖的日期范围、缺失的日期、预估影响。
```

---

## Token 优化技巧

### 核心原则：动态召回替代静态注入

最大的 token 节省来自于用按需召回替代静态的 Project Context 文件全量加载。

| 静态加载（昂贵） | 动态召回（高效） |
|---|---|
| 每次 session 都全量加载 MEMORY.md | 精简的 MEMORY.md 骨架 + session 开始时按需召回 |
| 所有项目细节始终在 context 中 | 只召回当前任务相关的项目细节 |
| 历史对话不断在 context 中积累 | 提炼后的记忆替代原始历史 |

**把这段提示词发给 Agent，建立动态召回习惯：**

```
在每次新 session 开始时，在回答用户的第一条消息之前，根据用户问的内容做一次针对性的 mem0 搜索：

python3 /path/to/mem0-memory-service/cli.py search \
  --user boss --agent &lt;your-agent-id&gt; \
  --query "<从用户消息中提取的 2-3 个关键词>" \
  --combined --recent-days 7 --min-score 0.3

只使用 score >= 0.3 的结果。如果用户的请求是纯概念性的（不涉及项目历史），跳过搜索。
```

---

## 快速参考：什么时候写什么

| 场景 | 记忆类型 | 命令 |
|------|---------|------|
| 修复 bug、发现踩坑 | `experience`（共享） | `--metadata '{"category":"experience"}'` |
| 做了技术决策 | `experience`（共享） | `--metadata '{"category":"experience"}'` |
| 项目状态变更 | `project`（agent 专属） | `--metadata '{"category":"project"}'` |
| 发现配置/环境信息 | `environment` | `--metadata '{"category":"environment"}'` |
| 今天的讨论记录 | `short_term` | `--run YYYY-MM-DD --metadata '{"category":"short_term"}'` |
| 观察到用户偏好 | `preference` | `--metadata '{"category":"preference"}'` |
