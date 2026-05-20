#!/usr/bin/env bash
# A2A Plugin — Environment Bootstrap for Tesla's VPS
# Run: bash setup.sh
# Idempotent — safe to run multiple times.

set -euo pipefail

echo "=== A2A Plugin Bootstrap ==="

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Repo dir: $REPO_DIR"

# ------------------------------------------------------------------
# 1. Detect Hermes venv
# ------------------------------------------------------------------
if [ -d "$HOME/.hermes/hermes-agent/venv" ]; then
    VENV="$HOME/.hermes/hermes-agent/venv"
    echo "[1/5] Found Hermes venv at $VENV"
elif [ -d "$HOME/hermes-agent/venv" ]; then
    VENV="$HOME/hermes-agent/venv"
    echo "[1/5] Found Hermes venv at $VENV"
else
    # Create one if none exists (Tesla may not have Hermes installed the same way)
    echo "[1/5] No Hermes venv found — creating at $HOME/.hermes/hermes-agent/venv"
    mkdir -p "$HOME/.hermes/hermes-agent"
    python3 -m venv "$HOME/.hermes/hermes-agent/venv"
    VENV="$HOME/.hermes/hermes-agent/venv"
fi

source "$VENV/bin/activate"
echo "       Python: $(python --version) at $(which python)"

# ------------------------------------------------------------------
# 2. Install a2a-core with dependencies
# ------------------------------------------------------------------
echo "[2/5] Installing a2a-core and dependencies..."
cd "$REPO_DIR"
pip install -e ".[dev]" 2>&1 | tail -1

# Verify key imports
python -c "from a2a.types import AgentCard; print('       a2a-sdk: OK')" 2>/dev/null || {
    echo "       WARNING: a2a-sdk import failed, retrying with explicit extras..."
    pip install "a2a-sdk[http-server,signing]" 2>&1 | tail -1
}

echo "       Dependencies installed."

# ------------------------------------------------------------------
# 3. Run test suite to verify environment
# ------------------------------------------------------------------
echo "[3/5] Running test suite..."
python -m pytest tests/ -q --tb=short 2>&1 | tail -3
echo "       Tests complete."

# ------------------------------------------------------------------
# 4. Set up profile A2A configs (templates)
# ------------------------------------------------------------------
echo "[4/5] Setting up profile A2A configs..."

PROFILES_DIR="${HOME}/.hermes/profiles"
mkdir -p "$PROFILES_DIR"

# Template function: adds a2a: section to profile config if not present
_add_a2a_config() {
    local profile="$1"
    local intents="$2"
    local tags="$3"
    local desc="$4"
    local config_file="$PROFILES_DIR/$profile/config.yaml"

    if [ -f "$config_file" ] && grep -q "^a2a:" "$config_file" 2>/dev/null; then
        echo "       $profile: already has a2a: config, skipping"
        return
    fi

    mkdir -p "$PROFILES_DIR/$profile"
    if [ ! -f "$config_file" ]; then
        cat > "$config_file" <<CONFIGEOF
model: claude-sonnet-4
provider: anthropic
CONFIGEOF
    fi

    cat >> "$config_file" <<CONFIGEOF

# A2A protocol capabilities (consumed by a2a-server plugin)
a2a:
  intents: [$intents]
  tags: [$tags]
  description: "$desc"
  streaming: false
  push: false
CONFIGEOF
    echo "       $profile: a2a: config added"
}

# Create or update profiles matching Proteus's config for mesh compat
_add_a2a_config "sherlock" '"consultation", "research"' '"research", "perception"' "Research and perception specialist"
_add_a2a_config "builder" '"instruction"' '"build", "implementation"' "Build executor — code, scripts, artifacts"
_add_a2a_config "doris" '"review"' '"review", "audit", "verification"' "Review and verification agent"

echo "       Profile configs ready."

# ------------------------------------------------------------------
# 5. Summary
# ------------------------------------------------------------------
echo "[5/5] Bootstrap complete."
echo ""
echo "=== Next Steps ==="
echo "1. Activate:  source \$VENV/bin/activate"
echo "2. Start A2A server:  python scripts/start-server.py --port 9696"
echo "3. Test:      curl http://127.0.0.1:9696/.well-known/agent-card.json"
echo ""
echo "For gateway integration (real Hermes dispatch):"
echo "  hermes gateway restart"
echo ""
echo "Read the handoff doc:  docs/A2A-PLUGIN-HANDOFF-TO-TESLA.md"
echo "Read founding contracts:  ls docs/founding/"
echo ""
