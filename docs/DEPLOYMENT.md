# Nexora AI — Deployment (Phase 12)

> Covers a single-host Docker Compose deployment. There is no chosen cloud
> provider, no managed database, no autoscaling, and no WAF here — this is
> the honest baseline the project has actually built and rehearsed, not an
> aspirational architecture. Extending it to a managed/multi-host setup is a
> real piece of future work, not a checkbox.

## 1. Prerequisites

- A host with Docker and Docker Compose v2.
- A domain name with an A/AAAA record already pointing at the host, and
  ports 80/443 reachable from the internet — Caddy (the reverse proxy)
  requests a Let's Encrypt certificate for it on first boot and will not
  serve HTTPS until that succeeds.
- Outbound network access from the host, for the certificate request and
  for any configured LLM provider / SMTP relay.

## 2. First deployment

```bash
cp .env.production.example .env
# Fill in every value in .env — see that file's own comments for how to
# generate each secret. docker compose refuses to start with any left blank.

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f caddy   # watch for the certificate issuance
```

`migrate` runs once and exits (`restart: "no"`); `backend`, `worker`, and
`beat` all wait on it completing successfully before starting.

Confirm:

```bash
curl -sf https://your-domain.example/health   # {"status":"ok"}
curl -sf https://your-domain.example/ready    # {"status":"ready"} — checks Postgres and Redis
```

## 3. What is and is not exposed

Only `caddy` publishes ports to the host (80/443). Postgres, Redis, MinIO,
Qdrant, and ClamAV are reachable only on the compose network — see
`SECURITY.md` §11. The raw backend API is *not* routed through Caddy either,
deliberately: the frontend's own BFF (`ARCHITECTURE.md`'s token-custody
design) is the only party that ever calls it, so nothing external needs a
direct path to it beyond `/health` and `/ready`, which `infra/caddy/Caddyfile`
proxies explicitly. `/metrics` stays internal-only — scrape it via
`docker compose exec backend curl localhost:8000/metrics` or a monitoring
agent joined to the same compose network, not over the public domain.

## 4. Migrations

`docker-compose.prod.yml`'s `migrate` service runs `alembic upgrade head` on
every `docker compose up`. To check status or roll back one revision without
restarting the whole stack:

```bash
docker compose -f docker-compose.prod.yml run --rm migrate alembic current
docker compose -f docker-compose.prod.yml run --rm migrate alembic downgrade -1
```

CI's `migrations` job already proves every migration's `downgrade()` is real
(`upgrade head && alembic check && downgrade -1 && upgrade head`, on every
push) — this is the same command, run against production data instead of a
disposable CI database, which is the only part CI cannot rehearse for you.
Take a backup (§5) before running a downgrade against real data regardless.

## 5. Backup and restore

`scripts/backup.sh` and `scripts/restore.sh` wrap `pg_dump --format=custom` /
`pg_restore` through `docker compose exec`, so no Postgres client tools are
needed on the host.

```bash
POSTGRES_USER=nexora_owner POSTGRES_DB=nexora ./scripts/backup.sh
# writes backups/nexora-<timestamp>.dump

POSTGRES_USER=nexora_owner POSTGRES_DB=nexora ./scripts/restore.sh backups/nexora-<timestamp>.dump
# destructive — asks for confirmation by typing the database name
```

**This procedure has been rehearsed, not just written**: dumped a live
database, restored it into a separate database in the same cluster, and
diffed row counts, the Alembic version, RLS policy count, and the audit
chain's own triggers — all matched exactly. `restore.sh` targets the
*current* database by design (disaster recovery into the same environment);
restoring into a fresh environment additionally needs the `nexora_owner` /
`nexora_app` roles to already exist in that Postgres cluster, since a
single-database dump does not include cluster-level role definitions —
`infra/postgres/init` (used by `migrate`'s first run) creates them.

Schedule `backup.sh` via host cron for routine backups; nothing in this
repo runs it on a timer, deliberately — retention policy and off-host
storage are an operational decision this project does not make for you.

## 6. Secret rotation

- **`JWT_SECRET_KEY`**: rotating it invalidates every outstanding access and
  refresh token instantly — every user is logged out. Fine for a genuine
  compromise, disruptive otherwise.
- **`FIELD_ENCRYPTION_KEY`**: rotating it without a re-encryption pass makes
  every already-encrypted field (MFA secrets) undecryptable — affected users
  would need to re-enroll MFA. There is no key-rotation tooling in this repo
  yet; treat this key as close to permanent as `JWT_SECRET_KEY` for now.
- **Database/Redis passwords**: update `.env`, then
  `docker compose -f docker-compose.prod.yml up -d` — Compose recreates only
  the containers whose config changed.

## 7. Monitoring, as far as this repo goes

`/metrics` (Prometheus text format, `app/modules/platform/router.py`) and
structured JSON logs to stdout (`docker compose logs`) are what exists.
There is no shipped Prometheus/Grafana/alerting stack, no error tracker
(Sentry or equivalent), and no log aggregation — wiring one up is real
future work, not assumed here. `/health` and `/ready` are suitable targets
for a third-party uptime check pointed at your domain.

## 8. Known gaps at this phase

Tracked here rather than silently assumed away, the same discipline
`SECURITY.md` §12 applies to its own list:

- **No WAF / bot management.** A deployment-layer choice (e.g. Cloudflare in
  front of this host) left to whoever operates it — not something this
  compose file provides.
- **No metrics/alerting stack shipped.** See §7.
- **Single host, no autoscaling, no managed database.** `worker` can be
  scaled with `docker compose up -d --scale worker=N` safely (the outbox
  drain uses `FOR UPDATE SKIP LOCKED`); `backend` behind Caddy's built-in
  load balancing likewise. Postgres itself is a single container with a
  named volume — no replica, no managed failover.
- **No key-rotation tooling.** See §6.
- **No penetration test.** Needs an external service; `SECURITY.md` §12
  lists it as a pre-production gate this project has not passed through.
