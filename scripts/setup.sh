#!/usr/bin/env bash
# =============================================================================
# scripts/setup.sh — Helmis one-command setup
#
# Runs on the VPS after cloning the repo. Guides through API key entry,
# phone number config, and brings all Docker services up.
#
# Usage:
#   chmod +x scripts/setup.sh
#   ./scripts/setup.sh
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${CYAN}[info]${RESET}  $*"; }
success() { echo -e "${GREEN}[ok]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${RESET}  $*"; }
error()   { echo -e "${RED}[error]${RESET} $*" >&2; exit 1; }
prompt()  { echo -e "${BOLD}$*${RESET}"; }

# -----------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------

echo ""
echo -e "${CYAN}${BOLD}"
echo "  ██╗  ██╗███████╗██╗     ███╗   ███╗██╗███████╗"
echo "  ██║  ██║██╔════╝██║     ████╗ ████║██║██╔════╝"
echo "  ███████║█████╗  ██║     ██╔████╔██║██║███████╗"
echo "  ██╔══██║██╔══╝  ██║     ██║╚██╔╝██║██║╚════██║"
echo "  ██║  ██║███████╗███████╗██║ ╚═╝ ██║██║███████║"
echo "  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝     ╚═╝╚═╝╚══════╝"
echo -e "${RESET}"
echo "  Personal AI Secretary — Setup"
echo ""

# -----------------------------------------------------------------------
# Prerequisites check
# -----------------------------------------------------------------------

info "Checking prerequisites..."

command -v docker >/dev/null 2>&1 || error "Docker is not installed. Install it first: https://docs.docker.com/engine/install/"
command -v docker compose >/dev/null 2>&1 || error "Docker Compose v2 is not installed. Update Docker or install the plugin."

DOCKER_VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
success "Docker found (version ${DOCKER_VERSION})"

# -----------------------------------------------------------------------
# .env setup
# -----------------------------------------------------------------------

if [ -f .env ]; then
  warn ".env already exists. Skipping — edit it manually to change values."
else
  info "Creating .env from template..."
  cp .env.example .env

  echo ""
  prompt "=== Gemini API Keys ==="
  echo "Enter your Gemini API keys (from separate Google accounts for independent quotas)."
  echo "Press Enter to skip keys you don't have yet."
  echo ""

  for i in 1 2 3; do
    read -rsp "  Gemini Key ${i}: " key
    echo ""
    if [ -n "${key}" ]; then
      sed -i "s|^GEMINI_KEY_${i}=.*|GEMINI_KEY_${i}=${key}|" .env
      success "Key ${i} saved"
    else
      warn "Key ${i} skipped — you can add it later in .env"
    fi
  done

  echo ""
  prompt "=== WAHA Configuration ==="
  echo ""

  read -rp "  WAHA API key (leave blank to use default 'helmis-secret-change-me'): " waha_key
  if [ -n "${waha_key}" ]; then
    sed -i "s|^WAHA_API_KEY=.*|WAHA_API_KEY=${waha_key}|" .env
  fi

  read -rsp "  WAHA dashboard password: " waha_pass
  echo ""
  if [ -n "${waha_pass}" ]; then
    sed -i "s|^WAHA_DASHBOARD_PASSWORD=.*|WAHA_DASHBOARD_PASSWORD=${waha_pass}|" .env
    success "WAHA config saved"
  fi

  echo ""
  prompt "=== Phone Numbers ==="
  echo "Format: country code + number, no spaces or symbols (e.g. 628123456789)"
  echo ""

  read -rp "  Gilang's WhatsApp number: " gilang_phone
  [ -n "${gilang_phone}" ] && sed -i "s|^GILANG_PHONE=.*|GILANG_PHONE=${gilang_phone}|" .env

  read -rp "  Bunga's WhatsApp number: " bunga_phone
  [ -n "${bunga_phone}" ] && sed -i "s|^BUNGA_PHONE=.*|BUNGA_PHONE=${bunga_phone}|" .env

  read -rp "  Helmis bot's WhatsApp number: " bot_phone
  [ -n "${bot_phone}" ] && sed -i "s|^BOT_PHONE=.*|BOT_PHONE=${bot_phone}|" .env

  success ".env configured"
fi

# -----------------------------------------------------------------------
# Validate required env vars
# -----------------------------------------------------------------------

info "Validating configuration..."
source .env

MISSING=()
[ -z "${GEMINI_KEY_1:-}" ] && MISSING+=("GEMINI_KEY_1")
[ -z "${WAHA_API_KEY:-}" ] && MISSING+=("WAHA_API_KEY")
[ -z "${GILANG_PHONE:-}" ] && MISSING+=("GILANG_PHONE")
[ -z "${BUNGA_PHONE:-}" ] && MISSING+=("BUNGA_PHONE")
[ -z "${BOT_PHONE:-}" ] && MISSING+=("BOT_PHONE")

if [ ${#MISSING[@]} -gt 0 ]; then
  warn "The following required values are missing from .env:"
  for var in "${MISSING[@]}"; do
    echo "  - ${var}"
  done
  warn "Edit .env and re-run setup, or continue and fix later."
fi

# -----------------------------------------------------------------------
# Build and start services
# -----------------------------------------------------------------------

echo ""
info "Building Docker images..."
docker compose build --no-cache

echo ""
info "Starting all services..."
docker compose up -d

# -----------------------------------------------------------------------
# Wait for WAHA to be healthy
# -----------------------------------------------------------------------

echo ""
info "Waiting for WAHA to be ready..."
MAX_WAIT=60
ELAPSED=0
while ! curl -s -f http://localhost:3000/health >/dev/null 2>&1; do
  sleep 3
  ELAPSED=$((ELAPSED + 3))
  if [ "${ELAPSED}" -ge "${MAX_WAIT}" ]; then
    error "WAHA did not become healthy within ${MAX_WAIT} seconds. Check logs: docker compose logs waha"
  fi
  echo -n "."
done
echo ""
success "WAHA is up"

# -----------------------------------------------------------------------
# Create WAHA session
# -----------------------------------------------------------------------

info "Creating WAHA session '${WAHA_SESSION_NAME:-helmis}'..."
SESSION_NAME="${WAHA_SESSION_NAME:-helmis}"

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "http://localhost:3000/api/sessions" \
  -H "X-Api-Key: ${WAHA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"${SESSION_NAME}\"}")

if [ "${RESPONSE}" = "201" ] || [ "${RESPONSE}" = "200" ]; then
  success "WAHA session created"
elif [ "${RESPONSE}" = "409" ]; then
  success "WAHA session already exists"
else
  warn "WAHA session creation returned HTTP ${RESPONSE} — you may need to create it manually via the dashboard"
fi

# -----------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------

echo ""
echo -e "${GREEN}${BOLD}=============================================${RESET}"
echo -e "${GREEN}${BOLD}  Helmis is running! 🎉${RESET}"
echo -e "${GREEN}${BOLD}=============================================${RESET}"
echo ""
echo "  Next step: Scan the WhatsApp QR code"
echo ""
echo "  → Open the WAHA dashboard:"
echo "    http://YOUR_VPS_IP:3000/dashboard"
echo "    (or SSH tunnel: ssh -L 3000:localhost:3000 user@your-vps)"
echo ""
echo "  → Scan the QR code with the Helmis bot's WhatsApp number"
echo ""
echo "  Useful commands:"
echo "    docker compose logs -f hermes    # watch Helmis's brain"
echo "    docker compose logs -f waha      # watch WhatsApp bridge"
echo "    docker compose logs -f scheduler # watch proactive triggers"
echo "    docker compose ps                # check all service health"
echo "    docker compose down              # stop everything"
echo ""
