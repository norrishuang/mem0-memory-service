# systemd 部署

服务使用 systemd 进行进程管理和定时任务调度。

## 主服务

```bash
sudo cp mem0-memory.service /etc/systemd/system/
# 根据需要编辑 User/WorkingDirectory/EnvironmentFile 路径
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory
```

## 定时任务

### 会话快照（每 5 分钟）

将当前活跃会话的对话保存到日记文件，防止会话压缩导致数据丢失。

```bash
mkdir -p ~/.config/systemd/user/
cp systemd/mem0-snapshot.service ~/.config/systemd/user/
cp systemd/mem0-snapshot.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
```

### 自动摘要（每 15 分钟）

从日记文件中提取短期事件，以 `run_id=YYYY-MM-DD` 的形式存入 mem0。

```bash
# 使用 cron
(crontab -l 2>/dev/null; echo "*/15 * * * * /usr/bin/python3 /path/to/auto_digest.py >> /path/to/auto_digest.log 2>&1") | crontab -
```

### AutoDream（每天 UTC 02:00）

处理超过 7 天的短期记忆 — 活跃主题升级为长期记忆，不活跃的则删除。

```bash
sudo cp mem0-dream.service /etc/systemd/system/
sudo cp mem0-dream.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mem0-dream.timer
```

### 验证定时器

```bash
# 检查定时器状态
systemctl --user list-timers mem0-snapshot.timer
sudo systemctl list-timers mem0-dream.timer

# 手动触发
systemctl --user start mem0-snapshot.service
sudo systemctl start mem0-dream.service

# 查看日志
journalctl --user -u mem0-snapshot.service -f
journalctl -u mem0-dream.service -f
```

## 任务总览

| 任务 | 频率 | 方式 | 用途 |
|------|-----------|--------|---------|
| `pipelines/session_snapshot.py` | 每 5 分钟 | systemd 用户定时器 | 保存会话对话到日记 |
| `pipelines/auto_digest.py` | 每 15 分钟 | cron | 从日记中提取短期记忆 |
| `pipelines/auto_dream.py` | 每天 02:00 UTC | systemd 系统定时器 | **AutoDream**：归档/删除过期短期记忆 |
