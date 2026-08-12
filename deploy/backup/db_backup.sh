#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# HireBuddha — PostgreSQL Monthly Backup Script
# ═══════════════════════════════════════════════════════════════════════════════
#
# Purpose : Creates a compressed pg_dump of the hirebuddha database and
#           automatically removes backups older than 90 days (≈ 3 months).
#
# Schedule: Intended to run monthly via cron.
#           Example crontab entry (1st of every month at 02:00 AM):
#
#           0 2 1 * * /home/rahul/workspace/hb-proto-3/deploy/backup/db_backup.sh >> /home/rahul/workspace/hb-proto-3/deploy/backup/logs/cron.log 2>&1
#
# Usage   : ./db_backup.sh              — runs with defaults
#           DB_PORT=5432 ./db_backup.sh  — override via env vars
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration (override any of these via environment variables) ───────────
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5433}"
DB_NAME="${DB_NAME:-hirebuddha}"
DB_USER="${DB_USER:-postgres}"
# If a password is needed, export PGPASSWORD before running or use a .pgpass file

BACKUP_ROOT="${BACKUP_ROOT:-/home/rahul/workspace/hb-proto-3/deploy/backup/dumps}"
LOG_DIR="${LOG_DIR:-/home/rahul/workspace/hb-proto-3/deploy/backup/logs}"
RETENTION_DAYS="${RETENTION_DAYS:-90}"   # Delete backups older than this (≈ 3 months)

# ── Derived values ────────────────────────────────────────────────────────────
TIMESTAMP="$(date +%Y-%m-%d_%H%M%S)"
BACKUP_FILE="${BACKUP_ROOT}/hirebuddha_backup_${TIMESTAMP}.sql.gz"
LOG_FILE="${LOG_DIR}/backup_${TIMESTAMP}.log"

# ── Ensure directories exist ─────────────────────────────────────────────────
mkdir -p "${BACKUP_ROOT}" "${LOG_DIR}"

# ── Logging helper ────────────────────────────────────────────────────────────
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "${msg}" | tee -a "${LOG_FILE}"
}

# ── Main ──────────────────────────────────────────────────────────────────────
log "═══════════════════════════════════════════════════════════"
log "HireBuddha DB Backup — START"
log "═══════════════════════════════════════════════════════════"
log "Host     : ${DB_HOST}:${DB_PORT}"
log "Database : ${DB_NAME}"
log "User     : ${DB_USER}"
log "Target   : ${BACKUP_FILE}"
log "Retention: ${RETENTION_DAYS} days"

# ── Step 1: Run pg_dump ───────────────────────────────────────────────────────
log ""
log "▸ Creating backup …"

if pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --no-owner \
    --no-privileges \
    --format=plain \
    --verbose \
    2>>"${LOG_FILE}" \
    | gzip > "${BACKUP_FILE}"; then

    BACKUP_SIZE="$(du -h "${BACKUP_FILE}" | cut -f1)"
    log "✓ Backup completed — ${BACKUP_SIZE} (${BACKUP_FILE})"
else
    log "✗ pg_dump FAILED — exit code $?"
    exit 1
fi

# ── Step 2: Verify backup is not empty ────────────────────────────────────────
FILESIZE=$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || stat -f%z "${BACKUP_FILE}" 2>/dev/null)
if [ "${FILESIZE}" -lt 100 ]; then
    log "✗ Backup file is suspiciously small (${FILESIZE} bytes). Aborting."
    exit 1
fi
log "✓ Backup size verification passed (${FILESIZE} bytes)"

# ── Step 3: Prune old backups ────────────────────────────────────────────────
log ""
log "▸ Pruning backups older than ${RETENTION_DAYS} days …"

DELETED_COUNT=0
while IFS= read -r old_file; do
    log "  🗑  Deleting: $(basename "${old_file}")"
    rm -f "${old_file}"
    ((DELETED_COUNT++))
done < <(find "${BACKUP_ROOT}" -name "hirebuddha_backup_*.sql.gz" -type f -mtime +"${RETENTION_DAYS}" 2>/dev/null)

if [ "${DELETED_COUNT}" -eq 0 ]; then
    log "  (no old backups to remove)"
else
    log "✓ Deleted ${DELETED_COUNT} old backup(s)"
fi

# ── Step 4: Summary ──────────────────────────────────────────────────────────
TOTAL_BACKUPS=$(find "${BACKUP_ROOT}" -name "hirebuddha_backup_*.sql.gz" -type f | wc -l)
TOTAL_SIZE=$(du -sh "${BACKUP_ROOT}" 2>/dev/null | cut -f1)

log ""
log "═══════════════════════════════════════════════════════════"
log "HireBuddha DB Backup — COMPLETE"
log "═══════════════════════════════════════════════════════════"
log "Backups on disk : ${TOTAL_BACKUPS}"
log "Total disk usage: ${TOTAL_SIZE}"
log "Next run        : 1st of next month (via cron)"
log "═══════════════════════════════════════════════════════════"

exit 0
