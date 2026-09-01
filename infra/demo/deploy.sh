#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${repo_root}/.env.demo"

if [[ ! -f "${env_file}" ]]; then
  echo "Missing ${env_file}. Copy .env.demo.example and fill every secret." >&2
  exit 1
fi

compose=(
  docker compose
  --env-file "${env_file}"
  -f "${repo_root}/docker-compose.prod.yml"
  -f "${repo_root}/docker-compose.demo.yml"
  --profile demo
)

"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --remove-orphans
"${compose[@]}" run --rm seed-demo
"${compose[@]}" ps

domain="$(sed -n 's/^DOMAIN=//p' "${env_file}" | tail -1)"
if [[ -n "${domain}" ]]; then
  echo "Demo deployment started at https://${domain}"
else
  echo "Demo deployment started; DOMAIN is empty, so Caddy cannot provision TLS."
fi
