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
#   SCHEDULER_WEBHOOK_SECRET — optional shared secret for scheduler ingress
# =============================================================================

TARGET_URL="${AGENT_WEBHOOK_URL:-${HELMIS_WEBHOOK_URL:-${HERMES_WEBHOOK_URL}}}"

if [ -z "${TARGET_URL}" ]; then
  echo "[trigger] ERROR: AGENT_WEBHOOK_URL / HELMIS_WEBHOOK_URL is not set" >&2
  exit 1
fi

# Send the trigger with a timestamp so Hermes knows when the check ran
PAYLOAD=$(printf '{"event":"scheduler.tick","timestamp":"%s","source":"cron"}' "$(date -u +%Y-%m-%dT%H:%M:%SZ)")

set -- \
  --silent \
  --show-error \
  --max-time 10 \
  --write-out "%{http_code}" \
  --output /dev/null \
  --request POST \
  --header "Content-Type: application/json"
if [ -n "${SCHEDULER_WEBHOOK_SECRET:-}" ]; then
  set -- "$@" --header "X-Scheduler-Webhook-Secret: ${SCHEDULER_WEBHOOK_SECRET}"
fi
set -- "$@" --data "${PAYLOAD}" "${TARGET_URL}"
RESPONSE=$(curl "$@" 2>&1)

if [ "${RESPONSE}" = "200" ] || [ "${RESPONSE}" = "202" ]; then
  echo "[trigger] Proactive check triggered successfully (HTTP ${RESPONSE})"
else
  echo "[trigger] WARNING: Hermes responded with HTTP ${RESPONSE}" >&2
fi
