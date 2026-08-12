#!/usr/bin/env bash
# =============================================================================
# scripts/backup.sh — Helmis data backup
#
# Backs up persistent data:
#   - data/waha-sessions/  (WhatsApp session — avoids re-scanning QR)
#   - data/hermes/         (memory database, learned skills, logs)
#
# Can be run manually or scheduled on the host VPS:
#   0 3 * * * /path/to/helmis/scripts/backup.sh >> /var/log/helmis-backup.log 2>&1
#
# Usage:
#   ./scripts/backup.sh [DESTINATION]
#   Default destination: ./backups/
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DESTINATION="${1:-${PROJECT_DIR}/backups}"
ARCHIVE_NAME="helmis_backup_${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="${DESTINATION}/${ARCHIVE_NAME}"

# Keep the last N backups, delete older ones
KEEP_BACKUPS=7

echo "[backup] Starting Helmis backup — ${TIMESTAMP}"

# -----------------------------------------------------------------------
# Ensure backup destination exists
# -----------------------------------------------------------------------

mkdir -p "${DESTINATION}"

# -----------------------------------------------------------------------
# Create compressed archive
# -----------------------------------------------------------------------

echo "[backup] Archiving data directories..."
tar -czf "${ARCHIVE_PATH}" \
  -C "${PROJECT_DIR}" \
  --exclude='data/waha-sessions/.*lock*' \
  data/

echo "[backup] Archive created: ${ARCHIVE_PATH}"
echo "[backup] Size: $(du -sh "${ARCHIVE_PATH}" | cut -f1)"

# -----------------------------------------------------------------------
# Prune old backups
# -----------------------------------------------------------------------

echo "[backup] Pruning old backups (keeping last ${KEEP_BACKUPS})..."
ls -t "${DESTINATION}"/helmis_backup_*.tar.gz 2>/dev/null \
  | tail -n +$((KEEP_BACKUPS + 1)) \
  | xargs -r rm -v

echo "[backup] Done. Current backups:"
ls -lh "${DESTINATION}"/helmis_backup_*.tar.gz 2>/dev/null || echo "  (none)"
