#!/bin/sh
# =============================================================================
# trigger.sh — Proactive check trigger
#
# Called by supercronic on schedule. Sends a lightweight POST to Hermes's
# scheduler webhook endpoint, prompting it to run the proactive-check skill.
#
# Hermes will then:
#   - Check for due reminders
#   - Check for tasks approaching deadlines
#   - Send WhatsApp messages for anything that needs attention
#
# Environment variables (set in docker-compose.yml):
#   HERMES_WEBHOOK_URL — full URL to Hermes's scheduler webhook endpoint
# =============================================================================

set -e

if [ -z "${HERMES_WEBHOOK_URL}" ]; then
  echo "[trigger] ERROR: HERMES_WEBHOOK_URL is not set" >&2
  exit 1
fi

# Send the trigger with a timestamp so Hermes knows when the check ran
PAYLOAD=$(printf '{"event":"scheduler.tick","timestamp":"%s","source":"cron"}' "$(date -u +%Y-%m-%dT%H:%M:%SZ)")

RESPONSE=$(curl \
  --silent \
  --show-error \
  --max-time 10 \
  --write-out "%{http_code}" \
  --output /dev/null \
  --request POST \
  --header "Content-Type: application/json" \
  --data "${PAYLOAD}" \
  "${HERMES_WEBHOOK_URL}" 2>&1)

if [ "${RESPONSE}" = "200" ] || [ "${RESPONSE}" = "202" ]; then
  echo "[trigger] Proactive check triggered successfully (HTTP ${RESPONSE})"
else
  echo "[trigger] WARNING: Hermes responded with HTTP ${RESPONSE}" >&2
fi
