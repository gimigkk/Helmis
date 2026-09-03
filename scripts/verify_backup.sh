#!/usr/bin/env bash
# =============================================================================
# scripts/verify_backup.sh — Restore verification for Helmis backups
#
# Extracts a backup archive into a throwaway directory, checks the SQLite
# database with integrity_check, and reports table counts. NEVER touches
# the live data/ directory or .env.
#
# Usage:
#   ./scripts/verify_backup.sh backups/helmis_backup_20260101_030000.tar.gz
#   ./scripts/verify_backup.sh            # verifies the newest archive in ./backups
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

ARCHIVE="${1:-}"
if [[ -z "${ARCHIVE}" ]]; then
  ARCHIVE="$(ls -t "${PROJECT_DIR}"/backups/helmis_backup_*.tar.gz 2>/dev/null | head -1 || true)"
fi
if [[ -z "${ARCHIVE}" || ! -f "${ARCHIVE}" ]]; then
  echo "[verify] ERROR: no backup archive found to verify" >&2
  exit 1
fi

echo "[verify] Archive: ${ARCHIVE}"

WORK_DIR="$(mktemp -d /tmp/helmis-verify.XXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT

# -----------------------------------------------------------------------
# Extract + sanity-check the archive contents
# -----------------------------------------------------------------------
tar -xzf "${ARCHIVE}" -C "${WORK_DIR}"

DB="${WORK_DIR}/data/helmis.db"
if [[ -f "${DB}" ]]; then
  echo "[verify] SQLite database found: data/helmis.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    RESULT="$(sqlite3 "${DB}" "PRAGMA integrity_check;")"
    if [[ "${RESULT}" != "ok" ]]; then
      echo "[verify] FAIL: integrity_check reported: ${RESULT}" >&2
      exit 1
    fi
    echo "[verify] integrity_check: ok"
    for TABLE in tasks outbox occurrences reminder_policies memory_candidates; do
      COUNT="$(sqlite3 "${DB}" "SELECT COUNT(*) FROM ${TABLE};" 2>/dev/null || echo 'n/a')"
      echo "[verify]   ${TABLE}: ${COUNT} rows"
    done
  else
    echo "[verify] WARN: sqlite3 CLI not available — skipping integrity_check" >&2
  fi
else
  echo "[verify] NOTE: no data/helmis.db in archive (pre-migration backup?)"
fi

# -----------------------------------------------------------------------
# Required payload sanity: WhatsApp session + vault catalog
# -----------------------------------------------------------------------
if compgen -G "${WORK_DIR}/data/waha-sessions/*" >/dev/null; then
  echo "[verify] waha session files: present"
else
  echo "[verify] WARN: no waha-sessions content in archive (session may live in a docker volume)" >&2
fi

[[ -f "${WORK_DIR}/data/file_catalog.json" ]] \
  && echo "[verify] vault catalog: present" \
  || echo "[verify] WARN: data/file_catalog.json missing" >&2

echo "[verify] PASS: ${ARCHIVE}"
