# systemd Deployment

The service uses systemd for process management and scheduled tasks.

## Main Service

```bash
sudo cp systemd/mem0-memory.service /etc/systemd/system/
# Edit User/WorkingDirectory/EnvironmentFile paths as needed
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory
```

## Scheduled Tasks

### Diary Capture (Real-time via openclaw-plugin)

Diary files are written in real-time by the openclaw-plugin `agent_end` hook — no separate timer or polling process is needed. The plugin fires after each agent turn and writes the conversation to the agent's diary file.

> **Note**: The previous `session_snapshot.py` (every 5 minutes) and its `mem0-snapshot.timer` have been retired. If you have them installed, you can safely disable and remove them:
> ```bash
> systemctl --user disable --now mem0-snapshot.timer
> rm ~/.config/systemd/user/mem0-snapshot.{service,timer}
> systemctl --user daemon-reload
> ```

### Auto Digest (every 15 minutes)

Extracts short-term events from diary files and stores them in mem0 with `infer=True` (`run_id=YYYY-MM-DD`). mem0 runs internal fact extraction to produce concise short-term memories.

```bash
# Using cron
(crontab -l 2>/dev/null; echo "*/15 * * * * /usr/bin/python3 /path/to/auto_digest.py >> /path/to/auto_digest.log 2>&1") | crontab -
```

### AutoDream (daily at UTC 02:00)

Runs nightly consolidation in two steps:
- **Step 1**: Reads yesterday diary → `mem0.add(infer=True, no run_id)` → long-term memory
- **Step 2**: For each 7-day-old short-term memory, calls `mem0.add(infer=True, no run_id)` — mem0 decides ADD/UPDATE/DELETE/NONE — then deletes the original entry

```bash
sudo cp systemd/mem0-dream.service /etc/systemd/system/
sudo cp systemd/mem0-dream.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mem0-dream.timer
```

### Verify Timers

```bash
# Check timer status
systemctl --user list-timers mem0-digest.timer
sudo systemctl list-timers mem0-dream.timer

# Manually trigger
systemctl --user start mem0-digest.service
sudo systemctl start mem0-dream.service

# View logs
journalctl --user -u mem0-digest.service -f
journalctl -u mem0-dream.service -f
```

## Task Summary

| Task | Frequency | Method | Purpose |
|------|-----------|--------|---------|
| openclaw-plugin `agent_end` hook | Real-time | Plugin (runs in OpenClaw) | Write conversation to diary after each agent turn |
| `pipelines/auto_digest.py` | Every 15 min | cron | Extract short-term memories from diary |
| `pipelines/auto_dream.py` | Daily 02:00 UTC | systemd system timer | **AutoDream**: Diary→long-term + short-term cleanup via mem0 native inference |
