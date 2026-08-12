# ============================================================
# scheduler/Dockerfile
#
# Minimal Alpine container that runs a cron job to trigger
# Hermes's proactive check every 5 minutes.
# ============================================================

FROM alpine:3.20

RUN apk add --no-cache curl ca-certificates tzdata

WORKDIR /app

COPY trigger.sh /app/trigger.sh
RUN chmod +x /app/trigger.sh

# Copy crontab directly to root's crontab in Alpine
COPY crontab /etc/crontabs/root

# Run crond in foreground (Docker-friendly, logs to stderr/stdout)
CMD ["crond", "-f", "-l", "2"]
