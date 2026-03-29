# systemd Deployment

The service uses systemd for process management and scheduled tasks.

## Main Service

```bash
sudo cp mem0-memory.service /etc/systemd/system/
# Edit User/WorkingDirectory/EnvironmentFile paths as needed
sudo systemctl daemon-reload
sudo systemctl enable --now mem0-memory
```

## Scheduled Tasks

### Session Snapshot (every 5 minutes)

Saves current active session conversations to diary files, preventing data loss from session compression.

```bash
mkdir -p ~/.config/systemd/user/
cp systemd/mem0-snapshot.service ~/.config/systemd/user/
cp systemd/mem0-snapshot.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now mem0-snapshot.timer
```

### Auto Digest (every 15 minutes)

Extracts short-term events from diary files and stores them in mem0 with `run_id=YYYY-MM-DD`.

```bash
# Using cron
(crontab -l 2>/dev/null; echo "*/15 * * * * /usr/bin/python3 /path/to/auto_digest.py >> /path/to/auto_digest.log 2>&1") | crontab -
```

### AutoDream (daily at UTC 02:00)

Processes short-term memories older than 7 days — active topics are upgraded to long-term, inactive ones are deleted.

```bash
sudo cp mem0-dream.service /etc/systemd/system/
sudo cp mem0-dream.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mem0-dream.timer
```

### Verify Timers

```bash
# Check timer status
systemctl --user list-timers mem0-snapshot.timer
sudo systemctl list-timers mem0-dream.timer

# Manually trigger
systemctl --user start mem0-snapshot.service
sudo systemctl start mem0-dream.service

# View logs
journalctl --user -u mem0-snapshot.service -f
journalctl -u mem0-dream.service -f
```

## Task Summary

| Task | Frequency | Method | Purpose |
|------|-----------|--------|---------|
| `pipelines/session_snapshot.py` | Every 5 min | systemd user timer | Save session conversations to diary |
| `pipelines/auto_digest.py` | Every 15 min | cron | Extract short-term memories from diary |
| `pipelines/auto_dream.py` | Daily 02:00 UTC | systemd system timer | **AutoDream**: Archive/delete old short-term memories |
