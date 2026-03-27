#!/usr/bin/env bash
#
# mem0 Memory Service - One-click installer for OpenClaw
#
# Usage:
#   ./install.sh
#
# Prerequisites:
#   - Python 3.9+
#   - AWS credentials configured (for Bedrock)
#   - OpenSearch cluster accessible
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="mem0-memory"

echo "🧠 mem0 Memory Service Installer"
echo "================================="

# ─── 1. Collect config ───
echo ""
echo "📋 Configuration (press Enter for defaults):"
echo ""

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

read -rp "AWS region [us-east-1]: " AWS_REG
AWS_REG=${AWS_REG:-us-east-1}

read -rp "Embedding model [amazon.titan-embed-text-v2:0]: " EMB_MODEL
EMB_MODEL=${EMB_MODEL:-amazon.titan-embed-text-v2:0}

read -rp "Embedding dimensions [1024]: " EMB_DIMS
EMB_DIMS=${EMB_DIMS:-1024}

read -rp "LLM model [us.anthropic.claude-3-5-haiku-20241022-v1:0]: " LLM_MODEL
LLM_MODEL=${LLM_MODEL:-us.anthropic.claude-3-5-haiku-20241022-v1:0}

read -rp "Service port [8230]: " SVC_PORT
SVC_PORT=${SVC_PORT:-8230}

read -rp "Index/collection name [mem0_memories]: " COLLECTION
COLLECTION=${COLLECTION:-mem0_memories}

# ─── 2. Install dependencies ───
echo ""
echo "📦 Installing Python dependencies..."
pip3 install --quiet mem0ai fastapi uvicorn opensearch-py boto3 requests

# ─── 3. Write .env file ───
ENV_FILE="${SCRIPT_DIR}/.env"
cat > "$ENV_FILE" <<EOF
AWS_REGION=${AWS_REG}
OPENSEARCH_HOST=${OS_HOST}
OPENSEARCH_PORT=${OS_PORT}
OPENSEARCH_USER=${OS_USER}
OPENSEARCH_PASSWORD=${OS_PASS}
OPENSEARCH_USE_SSL=${OS_SSL}
OPENSEARCH_VERIFY_CERTS=true
OPENSEARCH_COLLECTION=${COLLECTION}
EMBEDDING_MODEL=${EMB_MODEL}
EMBEDDING_DIMS=${EMB_DIMS}
LLM_MODEL=${LLM_MODEL}
SERVICE_HOST=0.0.0.0
SERVICE_PORT=${SVC_PORT}
EOF
chmod 600 "$ENV_FILE"
echo "   ✅ Config written to ${ENV_FILE}"

# ─── 4. Test connection ───
echo ""
echo "🔍 Testing OpenSearch connection..."
PROTO="http"
if [ "$OS_SSL" = "true" ]; then PROTO="https"; fi
if curl -sk -u "${OS_USER}:${OS_PASS}" "${PROTO}://${OS_HOST}:${OS_PORT}" >/dev/null 2>&1; then
    echo "   ✅ OpenSearch reachable"
else
    echo "   ⚠️  Warning: Cannot reach OpenSearch at ${OS_HOST}:${OS_PORT}. Continuing anyway..."
fi

echo "🔍 Testing AWS Bedrock access..."
if aws bedrock list-foundation-models --region "$AWS_REG" --max-results 1 >/dev/null 2>&1; then
    echo "   ✅ AWS Bedrock accessible"
else
    echo "   ⚠️  Warning: Cannot access Bedrock. Ensure AWS credentials are configured."
fi

# ─── 5. Install systemd service ───
echo ""
echo "🔧 Setting up systemd service..."

CURRENT_USER=$(whoami)
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=mem0 Memory Service - OpenClaw Agent Memory Layer
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=$(which python3) ${SCRIPT_DIR}/server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sleep 3

if sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "   ✅ Service running"
else
    echo "   ❌ Service failed to start. Check: sudo journalctl -u ${SERVICE_NAME} -n 30"
    exit 1
fi

# ─── 6. Verify API ───
echo ""
echo "🧪 Verifying API..."
if curl -s "http://127.0.0.1:${SVC_PORT}/health" | grep -q '"ok"'; then
    echo "   ✅ API healthy at http://127.0.0.1:${SVC_PORT}"
else
    echo "   ❌ API health check failed"
    exit 1
fi

# ─── 7. Install OpenClaw Skill ───
echo ""
SKILL_DIR="${HOME}/.openclaw/skills/mem0-memory"
echo "📝 Installing OpenClaw Skill to ${SKILL_DIR}..."
mkdir -p "${SKILL_DIR}/scripts"

# Copy SKILL.md (no substitution needed — uses {baseDir} which OpenClaw resolves)
cp "${SCRIPT_DIR}/skill/SKILL.md" "${SKILL_DIR}/SKILL.md"

# Generate mem0.sh wrapper with actual path
sed "s|\$MEM0_HOME|${SCRIPT_DIR}|g" \
    "${SCRIPT_DIR}/skill/scripts/mem0.sh.template" \
    > "${SKILL_DIR}/scripts/mem0.sh"
chmod +x "${SKILL_DIR}/scripts/mem0.sh"
echo "   ✅ Skill installed (CLI: ${SKILL_DIR}/scripts/mem0.sh)"

# ─── Done ───
echo ""
echo "════════════════════════════════════════"
echo "🎉 mem0 Memory Service installed!"
echo ""
echo "  Service:  sudo systemctl status ${SERVICE_NAME}"
echo "  API:      http://127.0.0.1:${SVC_PORT}"
echo "  CLI:      python3 ${SCRIPT_DIR}/cli.py --help"
echo "  Skill:    ${SKILL_DIR}/SKILL.md"
echo "  Logs:     sudo journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  Quick test:"
echo "    python3 ${SCRIPT_DIR}/cli.py add --user me --agent dev --text 'Hello mem0!'"
echo "    python3 ${SCRIPT_DIR}/cli.py search --user me --agent dev --query 'hello'"
echo "════════════════════════════════════════"
