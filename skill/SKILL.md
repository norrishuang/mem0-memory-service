---
name: mem0-memory
description: |
  mem0 向量记忆系统。通过 CLI 访问本地 mem0 Memory Service，实现语义记忆的存储、检索和管理。

  **当以下情况时使用此 Skill**：
  (1) 每次回答用户问题前，先 search 检索相关记忆
  (2) 每次完成一个任务或一轮有实质内容的对话后（自动沉淀）
  (3) 用户提到"记住"、"记一下"、"remember"、"recall"
  (4) 需要回忆/检索之前的信息
  (5) 需要列出、更新或删除已有记忆
  (6) Heartbeat 时自动沉淀
---

# mem0 Memory Skill

为 OpenClaw Agent 提供持久化语义记忆。mem0 自动做记忆提取和去重，放心多写。

## CLI 路径

```
/home/ec2-user/workspace/mem0-memory-service/cli.py
```

## 🔴 与 MEMORY.md 的分工

mem0 和 workspace 文件系统记忆（MEMORY.md + memory/*.md）各有优势，**不互相替代**：

| | MEMORY.md + memory/*.md | mem0 |
|---|---|---|
| **存什么** | 结构化项目卡片（名称+URL+状态+路径） | 经验教训、技术细节、决策原因、用户偏好 |
| **检索方式** | memory_search 系统自动触发 | 需主动调用 CLI search |
| **优势** | 保留结构和上下文，不会丢信息 | 语义检索，按需获取，不消耗加载 token |
| **劣势** | 文件越大 token 成本越高 | 自动去重可能拆碎结构化信息 |

**原则：**
- **项目卡片**（GitHub URL、架构概览、服务端口、关键路径）→ 写 MEMORY.md
- **经验教训、踩坑记录、技术细节、偏好、决策**→ 写 mem0
- **每日流水账**→ memory/YYYY-MM-DD.md

## 🔴 核心规则：主动检索 + 主动写入

### 检索（每次回答前）

**不要等用户说"你还记得吗"才查。每次回答用户问题前，主动 search：**

**优先使用组合搜索（长期 + 近7天短期）：**

```bash
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "<从用户问题提取的关键词>" \
  --combined --recent-days 7
```

**或单独搜索长期记忆：**

```bash
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "<从用户问题提取的关键词>"
```

### 写入（每次任务完成后）

**不要等用户说"记住"才写。每次对话有以下内容时，主动调用 add 沉淀：**

1. **完成了一个任务**（部署、修 bug、提 PR、写代码等）→ 记录做了什么、结果、关键决策
2. **发现了经验教训**（踩坑、workaround、兼容性问题）→ 记录问题和解决方案
3. **项目状态变更**（PR 合并/拒绝、版本发布、环境变更）→ 记录新状态
4. **用户偏好或习惯**（沟通方式、技术偏好、工作流程）→ 记录偏好
5. **新的配置/环境信息**（服务地址、密码、路径变更）→ 记录信息
6. **重要决策和原因**（为什么选 A 不选 B）→ 记录决策上下文

**写入时机：任务完成后、回复用户前。不需要额外确认。**

### ⚠️ 写入注意：避免信息被拆碎

mem0 的自动去重会将一条记忆拆分成多个零散事实。对于**结构化项目信息**（包含多个关键字段的），
应该合成一条完整记忆写入，而不是拆成多条：

```bash
# ❌ 不好：拆开写，去重后搜索时难以还原全貌
python3 cli.py add --text "mem0-memory-service 用 FastAPI"
python3 cli.py add --text "mem0-memory-service 端口 8230"
python3 cli.py add --text "mem0-memory-service 的 GitHub 地址是 ..."

# ✅ 好：合成一条完整记忆
python3 cli.py add --text "mem0-memory-service: GitHub https://github.com/norrishuang/mem0-memory-service, 架构 FastAPI+mem0→OpenSearch+Bedrock, 端口 8230, systemd mem0-memory.service"
```

**但经验教训和偏好可以分开写**（它们本身就是独立的事实片段）。

## 写入

```bash
# 长期记忆（经验教训、技术决策、用户偏好等）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --text "具体的关键信息" \
  --metadata '{"category":"experience","project":"xxx"}'

# 短期记忆（当天讨论、临时决策、任务进展）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --run 2026-03-23 \
  --text "今天讨论的临时内容..." \
  --metadata '{"category":"short_term","project":"xxx"}'

# 对话消息（mem0 自动提取关键事实，适合沉淀整段对话）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
```

**长短期记忆选择：**
- **长期记忆**（不传 `--run`）：技术决策、经验教训、项目状态、用户偏好
- **短期记忆**（传 `--run YYYY-MM-DD`）：当天讨论、临时决策、任务进展
- 7天后，短期记忆自动归档：活跃话题升级为长期，不活跃的删除

### metadata category 参考

| category | 用途 | 示例 |
|----------|------|------|
| `experience` | 经验教训、踩坑记录 | "较新特性先查官方文档，不要凭经验推断" |
| `project` | 项目状态、进展 | "opensearch-vector-search v1.3.0 已发布" |
| `decision` | 重要决策及原因 | "选择 cron 定时沉淀而非纯 heartbeat" |
| `environment` | 环境配置、服务信息 | "EC2 us-east-1, Bedrock 模型配置" |
| `preference` | 用户偏好、习惯 | "中文交流、简洁直接" |
| `short_term` | 短期记忆，带过期时间 | "今天 Luke 和 Zoe 讨论了 X 问题" |

### 短期记忆（基于 run_id + 自动归档）

短期记忆使用 `run_id=YYYY-MM-DD`（北京时间日期）标识，7天后自动归档：

```bash
# 添加短期记忆（用当天日期作为 run_id）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --run 2026-03-23 \
  --text "今天 Luke 和 Zoe 讨论了记忆系统重构方案" \
  --metadata '{"category":"short_term","project":"mem0"}'

# 带 metadata 分类
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent main \
  --run 2026-03-23 \
  --text "临时讨论：考虑将 Y 功能推迟到下个 sprint" \
  --metadata '{"category":"short_term","project":"xxx"}'
```

**自动归档机制**（每天运行）：
- 7天前的短期记忆自动处理
- 活跃话题（近期有相关讨论）→ 升级为长期记忆
- 不活跃话题 → 删除

**使用场景：**
- 当天讨论记录
- 会议纪要
- 临时决策或假设
- 任务进展

**注意：**
- 不确定是否永久的，优先用短期记忆
- 系统会自动判断是否值得保留

## 检索

```bash
# 组合搜索（长期 + 近7天短期，推荐）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "自然语言查询" --combined --recent-days 7

# 单独搜索长期记忆
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --query "自然语言查询" --top-k 5

# 搜索特定日期的短期记忆
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent main \
  --run 2026-03-23 --query "关键词"

# 跨 agent 搜索（不传 --agent）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --query "关键词" --combined --recent-days 7
```

## 定时沉淀

已配置 cron job（每 4 小时），自动从最近对话中提取有价值信息写入 mem0。
静默模式运行，不打扰用户。

## 其他操作

```bash
# 列出所有长期记忆
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py list --user boss --agent main

# 列出特定日期的短期记忆
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py list --user boss --agent main --run 2026-03-23

# 获取单条
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py get --id <memory_id>

# 删除
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py delete --id <memory_id>

# 变更历史
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py history --id <memory_id>
```

## 数据隔离

- `--user boss` — 固定用 boss
- `--agent main` / `--agent dev` — 按 agent 隔离
- 不传 `--agent` 可跨 agent 检索

## 注意

- mem0 自动去重，语义相似的内容不会重复存储，所以**宁可多写不要少写**
- 但结构化项目信息要**合成一条**写入，避免被拆碎（见上方注意事项）
- 搜索是语义级别的，不需要精确匹配
- 写入失败不影响主流程，静默跳过即可
- 服务管理：`sudo systemctl status/restart mem0-memory`
