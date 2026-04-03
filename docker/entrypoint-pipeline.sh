#!/bin/bash
set -e

# Export all env vars so cron jobs can access them
printenv | grep -v "no_proxy" >> /etc/environment

# Install crontab
crontab /app/docker/crontab

echo "$(date) - Pipeline container started, cron jobs installed:"
crontab -l

# Run cron in foreground
exec cron -f
