#!/usr/bin/env bash
# =============================================================================
# scripts/health_check.sh — Synthetic post-deploy health check for Helmis
#
# Verifies the full stack from the host: agent /health + /ready (WAHA
# reachability), waha /ping, scheduler container state, and agent tool
# registration in the logs. Exits non-zero on any failure.
#
# Usage (on the VPS, from the project root):
#   ./scripts/health_check.sh
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

# Load AGENT_WEBHOOK_PORT + WAHA_PORT_MAPPING from .env without printing secrets.
PORT="$(grep -E '^(AGENT_WEBHOOK_PORT|HERMES_WEBHOOK_PORT)=' .env 2>/dev/null | head -1 | cut -d= -f2)"
PORT="${PORT:-8644}"
WAHA_PORT="$(grep -E '^WAHA_PORT_MAPPING=' .env 2>/dev/null | head -1 | cut -d= -f2 | cut -d: -f1)"
WAHA_PORT="${WAHA_PORT:-3000}"

FAIL=0

check() {
  local NAME="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "[health] ok      ${NAME}"
  else
    echo "[health] FAIL    ${NAME}" >&2
    FAIL=1
  fi
}

# -----------------------------------------------------------------------
# Containers: all three services running, agent + waha healthy
# -----------------------------------------------------------------------
for SVC in agent waha scheduler; do
  check "container ${SVC} running" docker compose ps --status running --services | grep -qx "${SVC}"
done
check "container agent healthy"  docker compose ps agent | grep -q healthy
check "container waha healthy"   docker compose ps waha  | grep -q healthy

# -----------------------------------------------------------------------
# HTTP surfaces from the host
# -----------------------------------------------------------------------
check "agent /health" curl -fsS "http://localhost:${PORT}/health"
check "agent /ready (WAHA reachable)" curl -fsS "http://localhost:${PORT}/ready"
check "waha /ping" curl -fsS "http://localhost:${WAHA_PORT}/ping"

# -----------------------------------------------------------------------
# Tool registration + outbox drain present in recent agent logs
# -----------------------------------------------------------------------
LOGS="$(docker compose logs agent --no-log-prefix --since 10m 2>/dev/null || true)"
if echo "${LOGS}" | grep -q "Registered tools: waha_send_message"; then
  echo "[health] ok      MCP tool registration logged"
else
  echo "[health] WARN    'Registered tools' not found in last 10m of logs (may be older boot)" >&2
fi
if echo "${LOGS}" | grep -q "Outbox drain loop started"; then
  echo "[health] ok      Outbox drain loop logged"
else
  echo "[health] WARN    outbox drain line not in last 10m of logs" >&2
fi

if [[ "${FAIL}" -eq 0 ]]; then
  echo "[health] PASS: stack healthy"
else
  echo "[health] FAIL: see errors above" >&2
  exit 1
fi
