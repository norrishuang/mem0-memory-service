---
name: mem0-memory
description: |
  mem0 向量记忆系统。通过 CLI 访问本地 mem0 Memory Service，实现语义记忆的存储、检索和管理。

  **当以下情况时使用此 Skill**：
  (1) 每次完成一个任务或一轮有实质内容的对话后（自动沉淀）
  (2) 用户提到"记住"、"记一下"、"remember"、"recall"
  (3) 需要回忆/检索之前的信息
  (4) 需要列出、更新或删除已有记忆
  (5) Heartbeat 时自动沉淀
---

# mem0 Memory Skill

为 OpenClaw Agent 提供持久化语义记忆。mem0 自动做记忆提取和去重，放心多写。

## CLI 路径

```
/home/ec2-user/workspace/mem0-memory-service/cli.py
```

## 🔴 核心规则：主动写入

**不要等用户说"记住"才写。每次对话有以下内容时，主动调用 add 沉淀：**

1. **完成了一个任务**（部署、修 bug、提 PR、写代码等）→ 记录做了什么、结果、关键决策
2. **发现了经验教训**（踩坑、workaround、兼容性问题）→ 记录问题和解决方案
3. **项目状态变更**（PR 合并/拒绝、版本发布、环境变更）→ 记录新状态
4. **用户偏好或习惯**（沟通方式、技术偏好、工作流程）→ 记录偏好
5. **新的配置/环境信息**（服务地址、密码、路径变更）→ 记录信息
6. **重要决策和原因**（为什么选 A 不选 B）→ 记录决策上下文

**写入时机：任务完成后、回复用户前。不需要额外确认。**

## 写入

```bash
# 文本（最常用）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent dev \
  --text "具体的关键信息" \
  --metadata '{"category":"experience","project":"xxx"}'

# 对话消息（mem0 自动提取关键事实，适合沉淀整段对话）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py add \
  --user boss --agent dev \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'
```

### metadata category 参考

| category | 用途 |
|----------|------|
| `experience` | 经验教训、踩坑记录 |
| `project` | 项目状态、进展 |
| `decision` | 重要决策及原因 |
| `environment` | 环境配置、服务信息 |
| `preference` | 用户偏好、习惯 |
| `todo` | 待办事项 |

## 检索

```bash
# 语义搜索（开始任务前、回答"之前..."类问题时用）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --agent dev \
  --query "自然语言查询" --top-k 5

# 跨 agent 搜索（不传 --agent）
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py search \
  --user boss --query "关键词" --top-k 5
```

### 何时检索

- 用户问"之前..."、"上次..."、"那个项目..."
- 开始新任务前，搜索相关背景
- 需要回忆配置、密码、路径等信息
- Session 刚启动时（compaction 后恢复上下文）

## 其他操作

```bash
# 列出所有
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py list --user boss --agent dev

# 获取单条
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py get --id <memory_id>

# 删除
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py delete --id <memory_id>

# 变更历史
python3 /home/ec2-user/workspace/mem0-memory-service/cli.py history --id <memory_id>
```

## 数据隔离

- `--user boss` — 固定用 boss
- `--agent dev` / `--agent main` — 按 agent 隔离
- 不传 `--agent` 可跨 agent 检索

## 注意

- mem0 自动去重，语义相似的内容不会重复存储，所以**宁可多写不要少写**
- 搜索是语义级别的，不需要精确匹配
- 写入失败不影响主流程，静默跳过即可
- 服务管理：`sudo systemctl status/restart mem0-memory`
