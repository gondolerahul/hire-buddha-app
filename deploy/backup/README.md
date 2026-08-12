# HireBuddha — Database Backup System

## Overview

Automated PostgreSQL backup solution for the **hirebuddha** database. Backups are compressed (`.sql.gz`), timestamped, and old backups are auto-purged after 90 days.

## Directory Structure

```
deploy/backup/
├── db_backup.sh       # Main backup script (pg_dump + prune)
├── setup_cron.sh      # One-time cron installer
├── README.md          # This file
├── dumps/             # Backup files (auto-created)
│   └── hirebuddha_backup_2026-05-16_020000.sql.gz
└── logs/              # Execution logs (auto-created)
    ├── backup_2026-05-16_020000.log
    └── cron.log
```

## Quick Start

### 1. Install & Schedule (one-time)

```bash
./deploy/backup/setup_cron.sh
```

This will:
- Install `postgresql-client` (if `pg_dump` is missing)
- Register a cron job: **1st of every month at 02:00 AM**

### 2. Run a Manual Backup

```bash
PGPASSWORD=postgres ./deploy/backup/db_backup.sh
```

### 3. Configuration

Override defaults via environment variables:

| Variable         | Default                                    | Description                 |
|------------------|--------------------------------------------|-----------------------------|
| `DB_HOST`        | `localhost`                                | PostgreSQL host             |
| `DB_PORT`        | `5433`                                     | PostgreSQL port             |
| `DB_NAME`        | `hirebuddha`                               | Database name               |
| `DB_USER`        | `postgres`                                 | Database user               |
| `PGPASSWORD`     | *(not set)*                                | Database password           |
| `BACKUP_ROOT`    | `deploy/backup/dumps`                      | Where dumps are stored      |
| `LOG_DIR`        | `deploy/backup/logs`                       | Where logs are stored       |
| `RETENTION_DAYS` | `90`                                       | Delete backups older than   |

### 4. Restore from Backup

```bash
gunzip -c dumps/hirebuddha_backup_YYYY-MM-DD_HHMMSS.sql.gz | psql -h localhost -p 5433 -U postgres -d hirebuddha
```

### 5. Remove the Cron Job

```bash
crontab -l | grep -v 'db_backup.sh' | grep -v 'HireBuddha' | crontab -
```

## Backup Policy

| Policy             | Value                      |
|--------------------|----------------------------|
| **Frequency**      | Monthly (1st of each month)|
| **Retention**      | 90 days (≈ 3 months)       |
| **Format**         | gzipped plain SQL          |
| **Verification**   | File size > 100 bytes      |
| **Logging**        | Per-run log + cron.log     |
