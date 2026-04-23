# systemd 部署

服务使用 systemd 进行进程管理和定时任务调度。

## 主服务

```bash
sudo cp systemd/mem0-memory.service /etc/systemd/system/
# 根据需要编辑 User/WorkingDirectory/EnvironmentFile 路径
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory
```

## 定时任务

### 日记捕获（openclaw-plugin 实时写入）

日记文件由 openclaw-plugin 的 `agent_end` hook 实时写入——无需单独的定时器或轮询进程。Plugin 在每轮 agent 对话结束后触发，将对话内容写入 agent 的日记文件。

> **注**：之前的 `session_snapshot.py`（每 5 分钟）及其 `mem0-snapshot.timer` 已停用。如果已安装，可以安全地禁用并删除：
> ```bash
> systemctl --user disable --now mem0-snapshot.timer
> rm ~/.config/systemd/user/mem0-snapshot.{service,timer}
> systemctl --user daemon-reload
> ```

### 自动摘要（每 15 分钟）

从日记文件中提取短期事件，以 `infer=True` 和 `run_id=YYYY-MM-DD` 的形式存入 mem0。mem0 内部做 fact extraction，提炼为简洁短期记忆。

```bash
# 使用 cron
(crontab -l 2>/dev/null; echo "*/15 * * * * /usr/bin/python3 /path/to/auto_digest.py >> /path/to/auto_digest.log 2>&1") | crontab -
```

### AutoDream（每天 UTC 02:00）

每晚运行两步整合：
- **Step 1**：读取昨天日记 → `mem0.add(infer=True, 无 run_id)` → 长期记忆
- **Step 2**：对每条超过 7 天的短期记忆，调用 `mem0.add(infer=True, 无 run_id)` — mem0 决策 ADD/UPDATE/DELETE/NONE — 然后删除原始条目

```bash
sudo cp systemd/mem0-dream.service /etc/systemd/system/
sudo cp systemd/mem0-dream.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mem0-dream.timer
```

### 验证定时器

```bash
# 检查定时器状态
systemctl --user list-timers mem0-digest.timer
sudo systemctl list-timers mem0-dream.timer

# 手动触发
systemctl --user start mem0-digest.service
sudo systemctl start mem0-dream.service

# 查看日志
journalctl --user -u mem0-digest.service -f
journalctl -u mem0-dream.service -f
```

## 任务总览

| 任务 | 频率 | 方式 | 用途 |
|------|-----------|--------|---------|
| openclaw-plugin `agent_end` hook | 实时 | Plugin（在 OpenClaw 中运行） | 每轮对话结束后写入日记 |
| `pipelines/auto_digest.py` | 每 15 分钟 | cron | 从日记中提取短期记忆 |
| `pipelines/auto_dream.py` | 每天 02:00 UTC | systemd 系统定时器 | **AutoDream**：日记→长期记忆 + 通过 mem0 原生推理清理短期记忆 |
