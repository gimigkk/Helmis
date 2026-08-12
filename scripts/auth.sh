#!/usr/bin/env bash
# =============================================================================
# scripts/auth.sh — Terminal-based WhatsApp authentication for Helmis
#
# Starts WAHA, initializes the session, and streams the ASCII QR code
# directly in your terminal for scanning.
#
# Usage:
#   ./scripts/auth.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

cd "${PROJECT_DIR}"

source .env 2>/dev/null || true

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}=== Helmis WhatsApp Terminal Pairing ===${RESET}"
echo ""

# 1. Start WAHA if not running
echo -e "${CYAN}[1/3] Ensuring WAHA container is running...${RESET}"
docker compose up -d waha

# 2. Wait for WAHA API health
echo -e "${CYAN}[2/3] Waiting for WAHA API to be ready...${RESET}"
MAX_WAIT=30
ELAPSED=0
while ! curl -s -f http://localhost:3000/health >/dev/null 2>&1; do
  sleep 2
  ELAPSED=$((ELAPSED + 2))
  if [ "${ELAPSED}" -ge "${MAX_WAIT}" ]; then
    echo -e "${YELLOW}Warning: WAHA is taking longer than usual to respond. Continuing...${RESET}"
    break
  fi
  echo -n "."
done
echo ""

# 3. Create or start session
SESSION_NAME="${WAHA_SESSION_NAME:-helmis}"
API_KEY="${WAHA_API_KEY:-helmis-secret-change-me}"

echo -e "${CYAN}[3/3] Requesting session '${SESSION_NAME}' and QR code...${RESET}"

# Attempt to create/start session
curl -s -X POST "http://localhost:3000/api/sessions" \
  -H "X-Api-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"${SESSION_NAME}\", \"start\": true}" >/dev/null 2>&1 || true

# Start session if already created
curl -s -X POST "http://localhost:3000/api/sessions/${SESSION_NAME}/start" \
  -H "X-Api-Key: ${API_KEY}" >/dev/null 2>&1 || true

echo ""
echo -e "${GREEN}${BOLD}Scan the QR code below using the bot's phone (+62 877-9672-8527):${RESET}"
echo -e "Open WhatsApp -> Linked Devices -> Link a Device"
echo ""

# Stream logs from WAHA until authenticated
docker compose logs -f --tail=30 waha
