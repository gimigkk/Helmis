#!/usr/bin/env bash
# =============================================================================
# scripts/rollback.sh — One-command agent rollback on the VPS
#
# Rolls the `agent` service back to the previous deployed commit and rebuilds
# it. Never touches data/, .env, or the waha/scheduler services — the WhatsApp
# session and production data are preserved.
#
# Usage (on the VPS, from the project root):
#   ./scripts/rollback.sh            # roll back to HEAD~1 and rebuild agent
#   ./scripts/rollback.sh <commit>   # roll back to an explicit commit
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

TARGET="${1:-HEAD~1}"

CURRENT="$(git rev-parse --short HEAD)"
TARGET_SHA="$(git rev-parse --short "${TARGET}")"

echo "[rollback] current: ${CURRENT} -> target: ${TARGET_SHA}"

# Snapshot data before touching anything (best effort, never aborts rollback).
if [[ -x scripts/backup.sh ]]; then
  echo "[rollback] taking a safety backup first..."
  ./scripts/backup.sh || echo "[rollback] WARN: backup failed, continuing" >&2
fi

# -----------------------------------------------------------------------
# Refuse to roll back through the SQLite migration boundary.
# The old code expects JSON task state; rolling back below the migration
# commit with a migrated data/ layout would silently drop task writes.
# -----------------------------------------------------------------------
MIGRATE_COMMIT="$(git log --format='%h %s' | awk '/refactor.*SQLite|migrate/ {print $1; exit}')"
if [[ -n "${MIGRATE_COMMIT}" ]] && git merge-base --is-ancestor "${MIGRATE_COMMIT}" "${TARGET_SHA}" 2>/dev/null; then
  :
else
  echo "[rollback] NOTE: target predates the SQLite migration commit (${MIGRATE_COMMIT:-unknown})."
  echo "[rollback] New writes since migration live ONLY in data/helmis.db and will not"
  echo "[rollback] be visible to the old code. Restore data/helmis.db from a pre-migration"
  echo "[rollback] backup if that is acceptable, or choose a newer target commit."
  read -r -p "Continue anyway? [y/N] " ANSWER
  [[ "${ANSWER}" =~ ^[Yy]$ ]] || { echo "[rollback] aborted."; exit 1; }
fi

# -----------------------------------------------------------------------
# Move the code, rebuild ONLY the agent, keep waha + scheduler + volumes.
# -----------------------------------------------------------------------
git checkout "${TARGET_SHA}"
git reset --hard "${TARGET_SHA}"

docker compose build agent
docker compose up -d agent

echo "[rollback] agent recreated at ${TARGET_SHA}. Health check:"
for _ in $(seq 1 12); do
  if docker compose ps agent | grep -q "healthy"; then
    echo "[rollback] agent healthy."
    docker compose logs agent --no-log-prefix | tail -5
    exit 0
  fi
  sleep 5
done

echo "[rollback] WARN: agent not healthy within 60s — inspect with: docker compose logs agent" >&2
exit 1
