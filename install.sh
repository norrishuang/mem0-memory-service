#!/usr/bin/env bash
#
# mem0 Memory Service - Docker installer for OpenClaw
#
# Usage:
#   ./install.sh
#
# Prerequisites:
#   - Docker 20.10+
#   - docker compose (v2)
#   - AWS credentials configured (IAM Role on EC2, or Access Key)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🧠 mem0 Memory Service Installer (Docker)"
echo "============================================"

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

# ─── 1. Collect config ───
echo ""
echo "📋 Configuration (press Enter for defaults):"
echo ""

# Vector store choice
echo "Vector store backend:"
echo "  1) opensearch (default)"
echo "  2) s3vectors (AWS S3 Vectors — lower cost, pay-per-use)"
read -rp "Choose [1]: " VS_CHOICE
case "${VS_CHOICE}" in
    2) VECTOR_STORE="s3vectors" ;;
    *) VECTOR_STORE="opensearch" ;;
esac

read -rp "AWS region [us-east-1]: " AWS_REG
AWS_REG=${AWS_REG:-us-east-1}

# Vector store specific config
if [ "$VECTOR_STORE" = "opensearch" ]; then
    read -rp "OpenSearch host: " OS_HOST
    if [ -z "$OS_HOST" ]; then
        echo "❌ OpenSearch host is required."
        exit 1
    fi
    read -rp "OpenSearch port [443]: " OS_PORT
    OS_PORT=${OS_PORT:-443}
    read -rp "OpenSearch username [admin]: " OS_USER
    OS_USER=${OS_USER:-admin}
    read -rsp "OpenSearch password: " OS_PASS
    echo ""
    if [ -z "$OS_PASS" ]; then
        echo "❌ OpenSearch password is required."
        exit 1
    fi
    read -rp "Use SSL? [true]: " OS_SSL
    OS_SSL=${OS_SSL:-true}
    read -rp "Index/collection name [mem0_memories]: " COLLECTION
    COLLECTION=${COLLECTION:-mem0_memories}
else
    read -rp "S3Vectors bucket name: " S3V_BUCKET
    if [ -z "$S3V_BUCKET" ]; then
        echo "❌ S3Vectors bucket name is required."
        exit 1
    fi
    read -rp "S3Vectors index name [mem0]: " S3V_INDEX
    S3V_INDEX=${S3V_INDEX:-mem0}
fi

read -rp "OpenClaw data directory [~/.openclaw]: " OPENCLAW_BASE
OPENCLAW_BASE=${OPENCLAW_BASE:-~/.openclaw}

read -rp "Embedding model [amazon.titan-embed-text-v2:0]: " EMB_MODEL
EMB_MODEL=${EMB_MODEL:-amazon.titan-embed-text-v2:0}

read -rp "LLM model [us.anthropic.claude-haiku-4-5-20251001-v1:0]: " LLM_MODEL
LLM_MODEL=${LLM_MODEL:-us.anthropic.claude-haiku-4-5-20251001-v1:0}

read -rp "Service port [8230]: " SVC_PORT
SVC_PORT=${SVC_PORT:-8230}

# ─── 2. Write .env file ───
echo ""
echo "📝 Writing .env..."
ENV_FILE="${SCRIPT_DIR}/.env"

cat > "$ENV_FILE" <<EOF
AWS_REGION=${AWS_REG}
VECTOR_STORE=${VECTOR_STORE}
EOF

if [ "$VECTOR_STORE" = "opensearch" ]; then
    cat >> "$ENV_FILE" <<EOF
OPENSEARCH_HOST=${OS_HOST}
OPENSEARCH_PORT=${OS_PORT}
OPENSEARCH_USER=${OS_USER}
OPENSEARCH_PASSWORD=${OS_PASS}
OPENSEARCH_USE_SSL=${OS_SSL}
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_COLLECTION=${COLLECTION}
EOF
else
    cat >> "$ENV_FILE" <<EOF
S3VECTORS_BUCKET_NAME=${S3V_BUCKET}
S3VECTORS_INDEX_NAME=${S3V_INDEX}
EOF
fi

cat >> "$ENV_FILE" <<EOF
EMBEDDING_MODEL=${EMB_MODEL}
EMBEDDING_DIMS=1024
LLM_MODEL=${LLM_MODEL}
SERVICE_HOST=0.0.0.0
SERVICE_PORT=${SVC_PORT}
OPENCLAW_BASE=${OPENCLAW_BASE}
EOF

chmod 600 "$ENV_FILE"
echo "   ✅ Config written to ${ENV_FILE}"

# ─── 3. Start Docker containers ───
echo ""
echo "🐳 Starting Docker containers..."
cd "$SCRIPT_DIR"
docker compose up -d --build

# ─── 4. Wait for health check ───
echo ""
echo "🧪 Waiting for service to be healthy..."
MAX_WAIT=60
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s "http://127.0.0.1:${SVC_PORT}/health" 2>/dev/null | grep -q '"ok"'; then
        echo "   ✅ API healthy at http://127.0.0.1:${SVC_PORT}"
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

# ─── 5. Install OpenClaw Skill ───
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
echo "  API:        http://127.0.0.1:${SVC_PORT}"
echo "  Logs:       docker compose logs -f"
echo "  Stop:       docker compose down"
echo "  Skill:      ${SKILL_DIR}/SKILL.md"
echo ""
echo "  Quick test:"
echo "    docker compose exec mem0-api python3 cli.py add --user me --agent dev --text 'Hello mem0!'"
echo "    docker compose exec mem0-api python3 cli.py search --user me --agent dev --query 'hello'"
echo ""
echo "  💡 EC2 users: Use IAM Role — no Access Key needed in .env"
echo "════════════════════════════════════════"

# If you prefer systemd deployment, see docs/deploy/systemd.md
