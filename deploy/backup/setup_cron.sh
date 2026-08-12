#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Setup cron job for monthly HireBuddha DB backups
# ═══════════════════════════════════════════════════════════════════════════════
#
# This script:
#   1. Installs postgresql-client if pg_dump is missing
#   2. Registers a cron job to run db_backup.sh on the 1st of every month at 2 AM
#   3. Is idempotent — safe to run multiple times
#
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="${SCRIPT_DIR}/db_backup.sh"
LOG_DIR="${SCRIPT_DIR}/logs"
CRON_SCHEDULE="0 2 1 * *"
CRON_COMMENT="# HireBuddha monthly DB backup"
CRON_ENTRY="${CRON_SCHEDULE} ${BACKUP_SCRIPT} >> ${LOG_DIR}/cron.log 2>&1"

echo "═══════════════════════════════════════════════════════════"
echo " HireBuddha DB Backup — Cron Setup"
echo "═══════════════════════════════════════════════════════════"

# ── Step 1: Ensure pg_dump is available ───────────────────────────────────────
if ! command -v pg_dump &>/dev/null; then
    echo ""
    echo "▸ pg_dump not found — installing postgresql-client …"
    sudo apt-get update -qq
    sudo apt-get install -y -qq postgresql-client
    echo "✓ postgresql-client installed ($(pg_dump --version))"
else
    echo "✓ pg_dump already available ($(pg_dump --version))"
fi

# ── Step 2: Ensure directories exist ─────────────────────────────────────────
mkdir -p "${LOG_DIR}" "${SCRIPT_DIR}/dumps"
echo "✓ Directories ready"

# ── Step 3: Register cron job (idempotent) ────────────────────────────────────
echo ""
echo "▸ Registering cron job …"

# Remove any existing HireBuddha backup cron entries, then add the new one
EXISTING_CRONTAB="$(crontab -l 2>/dev/null || true)"
FILTERED="$(echo "${EXISTING_CRONTAB}" | grep -v "db_backup.sh" | grep -v "HireBuddha monthly DB backup" || true)"
( echo "${FILTERED}" ; echo "${CRON_COMMENT}" ; echo "${CRON_ENTRY}" ) | crontab -

echo "✓ Cron job installed:"
echo ""
echo "  Schedule : 1st of every month at 02:00 AM"
echo "  Command  : ${BACKUP_SCRIPT}"
echo "  Log      : ${LOG_DIR}/cron.log"
echo ""

# ── Step 4: Show the installed crontab ────────────────────────────────────────
echo "▸ Current crontab:"
crontab -l 2>/dev/null | tail -5
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Setup complete!"
echo ""
echo " To test the backup manually:"
echo "   PGPASSWORD=postgres ${BACKUP_SCRIPT}"
echo ""
echo " To remove the cron job:"
echo "   crontab -l | grep -v 'db_backup.sh' | grep -v 'HireBuddha' | crontab -"
echo "═══════════════════════════════════════════════════════════"
