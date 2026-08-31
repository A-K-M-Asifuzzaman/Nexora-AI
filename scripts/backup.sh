#!/usr/bin/env bash
# Postgres backup (docs/DEPLOYMENT.md). Runs `pg_dump` inside the running
# `postgres` container via `docker compose exec` — no client tools required
# on the host, and no risk of a host `pg_dump` version mismatching the
# server's, which the custom format (`-Fc`) is stricter about than plain SQL.
#
# Usage: ./scripts/backup.sh [output-directory]   (default: ./backups)
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
OUT_DIR="${1:-backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${OUT_DIR}/nexora-${TIMESTAMP}.dump"

: "${POSTGRES_USER:?POSTGRES_USER must be set (same value used to start the stack)}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"

mkdir -p "$OUT_DIR"

echo "Backing up '${POSTGRES_DB}' to ${OUT_FILE} ..."
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom \
  > "$OUT_FILE"

echo "Done: $(du -h "$OUT_FILE" | cut -f1) written."
echo "Restore with: ./scripts/restore.sh ${OUT_FILE}"
