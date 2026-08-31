#!/usr/bin/env bash
# Postgres restore (docs/DEPLOYMENT.md) — the other half of backup.sh.
# Destructive: drops and recreates every object the dump contains. Intended
# for disaster recovery or standing up a fresh environment from a backup,
# not for routine use against a database with traffic on it.
#
# Usage: ./scripts/restore.sh path/to/nexora-*.dump
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
DUMP_FILE="${1:?Usage: restore.sh path/to/backup.dump}"

: "${POSTGRES_USER:?POSTGRES_USER must be set (same value used to start the stack)}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"

if [ ! -f "$DUMP_FILE" ]; then
  echo "No such file: $DUMP_FILE" >&2
  exit 1
fi

echo "This will overwrite every object in '${POSTGRES_DB}' with the contents of ${DUMP_FILE}."
read -r -p "Type the database name to confirm: " confirmation
if [ "$confirmation" != "$POSTGRES_DB" ]; then
  echo "Confirmation did not match. Aborted." >&2
  exit 1
fi

echo "Restoring ..."
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner \
  < "$DUMP_FILE"

echo "Restore complete. Run 'alembic check' (via the migrate service) to confirm the schema matches head."
