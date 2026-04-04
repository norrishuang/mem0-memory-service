#!/usr/bin/env bash
#
# mem0 Memory Service - One-Line Docker Installer for OpenClaw
#
# Usage:
#   ./install.sh
#
# Prerequisites:
#   - Docker 20.10+ with docker compose (v2)
#   - AWS Bedrock access (IAM Role on EC2, or configured credentials)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🧠 mem0 Memory Service Installer"
echo "=================================="

# ─── 0. Check Docker ───
echo ""
echo "🔍 Checking prerequisites..."

if ! command -v docker &>/dev/null; then
    echo "❌ Docker is not installed. Please install Docker 20.10+ first:"
    echo "   https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker compose version &>/dev/null; then
    echo "❌ docker compose (v2) is not available. Please install it:"
    echo "   https://docs.docker.com/compose/install/"
    exit 1
fi

echo "   ✅ Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
echo "   ✅ $(docker compose version)"

# ─── 1. Auto-detect AWS Region ───
echo ""
echo "🌍 Detecting AWS Region..."

AWS_REG=""
if [ -n "${AWS_REGION:-}" ]; then
    AWS_REG="$AWS_REGION"
    echo "   ✅ From \$AWS_REGION: ${AWS_REG}"
elif command -v aws &>/dev/null && AWS_CLI_REG=$(aws configure get region 2>/dev/null) && [ -n "$AWS_CLI_REG" ]; then
    AWS_REG="$AWS_CLI_REG"
    echo "   ✅ From aws configure: ${AWS_REG}"
elif [ -n "${AWS_DEFAULT_REGION:-}" ]; then
    AWS_REG="$AWS_DEFAULT_REGION"
    echo "   ✅ From \$AWS_DEFAULT_REGION: ${AWS_REG}"
else
    AWS_REG="us-east-1"
    echo "   ℹ️  No region detected, using default: ${AWS_REG}"
fi

# ─── 2. One question: OpenClaw directory ───
echo ""
read -rp "📂 OpenClaw data directory [~/.openclaw]: " OPENCLAW_BASE
OPENCLAW_BASE=${OPENCLAW_BASE:-~/.openclaw}

# ─── 3. Write .env ───
echo ""
echo "📝 Writing .env..."
ENV_FILE="${SCRIPT_DIR}/.env"

cat > "$ENV_FILE" <<EOF
# Auto-detected or default
AWS_REGION=${AWS_REG}

# pgvector (local, no cloud vector store needed)
VECTOR_STORE=pgvector
PGVECTOR_HOST=mem0-postgres
PGVECTOR_DB=mem0
PGVECTOR_USER=mem0
PGVECTOR_PASSWORD=mem0-local

# Models (Bedrock)
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIMS=1024
LLM_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0

# Service
SERVICE_HOST=0.0.0.0
SERVICE_PORT=8230

# OpenClaw
OPENCLAW_BASE=${OPENCLAW_BASE}
EOF

chmod 600 "$ENV_FILE"
echo "   ✅ Config written to ${ENV_FILE}"

# ─── 4. Start Docker containers ───
echo ""
echo "🐳 Starting Docker containers (pgvector mode)..."
cd "$SCRIPT_DIR"
docker compose --profile pgvector up -d --build

# ─── 5. Wait for health check ───
echo ""
echo "🧪 Waiting for service to be healthy..."
MAX_WAIT=90
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s "http://127.0.0.1:8230/health" 2>/dev/null | grep -q '"ok"'; then
        echo "   ✅ API healthy at http://127.0.0.1:8230"
        break
    fi
    sleep 3
    WAITED=$((WAITED + 3))
    echo "   ⏳ Waiting... (${WAITED}s)"
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo "   ⚠️  Service not healthy after ${MAX_WAIT}s. Check logs:"
    echo "      docker compose logs"
    exit 1
fi

# ─── 6. Install OpenClaw Skill ───
echo ""
SKILL_DIR="${HOME}/.openclaw/skills/mem0-memory"
echo "📝 Installing OpenClaw Skill to ${SKILL_DIR}..."
mkdir -p "${SKILL_DIR}/scripts"
cp "${SCRIPT_DIR}/skill/SKILL.md" "${SKILL_DIR}/SKILL.md"
if [ -f "${SCRIPT_DIR}/skill/scripts/mem0.sh.template" ]; then
    sed "s|\$MEM0_HOME|${SCRIPT_DIR}|g" \
        "${SCRIPT_DIR}/skill/scripts/mem0.sh.template" \
        > "${SKILL_DIR}/scripts/mem0.sh"
    chmod +x "${SKILL_DIR}/scripts/mem0.sh"
fi
echo "   ✅ Skill installed"

# ─── Done ───
echo ""
echo "════════════════════════════════════════"
echo "🎉 mem0 Memory Service installed!"
echo ""
echo "  Containers: docker compose ps"
echo "  API:        http://127.0.0.1:8230"
echo "  Logs:       docker compose logs -f"
echo "  Stop:       docker compose down"
echo "  Skill:      ${SKILL_DIR}/SKILL.md"
echo ""
echo "  Quick test:"
echo "    docker compose exec mem0-api python3 cli.py add --user me --agent dev --text 'Hello mem0!'"
echo "    docker compose exec mem0-api python3 cli.py search --user me --agent dev --query 'hello'"
echo ""
echo "  💡 EC2 users: Use IAM Role — no Access Key needed in .env"
echo "  💡 Want to switch to S3 Vectors or OpenSearch? See docs/deploy/docker.md"
echo "════════════════════════════════════════"
