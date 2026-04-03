FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends cron && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Apply S3Vectors filter format patch (fixes upstream mem0 bug, PR #4554)
RUN python3 tools/patch_s3vectors_filter.py

RUN mkdir -p /app/data

EXPOSE 8230

# Default: run API server
CMD ["python3", "server.py"]
