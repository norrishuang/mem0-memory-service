---
name: mem0-memory
description: |
  mem0 向量记忆系统。通过 HTTP API 访问本地 mem0 Memory Service，实现语义记忆的存储、检索和管理。
  后端支持 OpenSearch 向量引擎 + AWS Bedrock / OpenAI Embedding。

  **当以下情况时使用此 Skill**：
  (1) 需要存储重要信息到长期记忆（项目进展、决策、经验教训等）
  (2) 需要回忆/检索之前存储的信息
  (3) 用户提到"记住"、"记忆"、"记一下"、"recall"、"remember"
  (4) 对话中出现值得长期保存的关键事实
  (5) 需要列出、更新或删除已有记忆
  (6) Heartbeat 时自动沉淀有价值的对话内容
---

# mem0 Memory Skill

为 OpenClaw Agent 提供基于 mem0 的持久化语义记忆能力。

## 服务信息

- **地址**: `http://127.0.0.1:8230`
- **健康检查**: `curl -s http://127.0.0.1:8230/health`
- **CLI 路径**: 安装目录下的 `cli.py`

## 操作指南

通过 `exec` 工具调用 CLI。以下 `$MEM0_HOME` 指安装目录（如 `/home/ec2-user/workspace/mem0-memory-service`）。

### 写入记忆

```bash
# 文本
python3 $MEM0_HOME/cli.py add --user <user_id> --agent <agent_id> --text "关键信息"

# 对话消息（mem0 自动提取关键事实）
python3 $MEM0_HOME/cli.py add --user <user_id> --agent <agent_id> \
  --messages '[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]'

# 带元数据
python3 $MEM0_HOME/cli.py add --user <user_id> --agent <agent_id> \
  --text "..." --metadata '{"project":"xxx","category":"experience"}'
```

### 语义搜索

```bash
python3 $MEM0_HOME/cli.py search --user <user_id> --agent <agent_id> \
  --query "自然语言查询" --top-k 5
```

### 列出 / 获取 / 删除

```bash
python3 $MEM0_HOME/cli.py list --user <user_id> --agent <agent_id>
python3 $MEM0_HOME/cli.py get --id <memory_id>
python3 $MEM0_HOME/cli.py delete --id <memory_id>
```

## 数据隔离

- `user_id`: 用户标识（如 `boss`）
- `agent_id`: Agent 标识（如 `dev`、`main`）
- 不传 `agent_id` 可跨 agent 检索所有记忆

## 何时写入

- 用户明确要求"记住这个"
- 重要项目状态变更（PR 合并、部署完成等）
- 新的技术经验和教训
- 重要决策和原因
- Heartbeat 时沉淀当日有价值的对话

## 何时检索

- 用户问及之前的工作、项目状态
- 需要回忆技术细节、配置信息
- 开始新任务前检索相关背景
- 回答"上次..."、"之前..."类问题

## 注意

- mem0 自动做记忆提取和去重，不用担心重复写入
- 搜索是语义级别的，不需要精确关键词
- 服务管理：`sudo systemctl status/restart mem0-memory`
