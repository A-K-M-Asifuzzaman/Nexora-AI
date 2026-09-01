# Free demo deployment

This deployment runs Nexora on one free ARM64 or AMD64 Linux VM while retaining
the complete runtime: FastAPI, Next.js, PostgreSQL, Redis, Celery worker, Celery
beat, transactional outbox, MinIO, Qdrant, ClamAV and Caddy. The consolidation
is a cost decision for the demo, not an architectural rewrite.

Production remains defined by `docker-compose.prod.yml` and
`docs/DEPLOYMENT.md`. The additive `docker-compose.demo.yml` changes only
resource limits and adds a private Mailpit SMTP sink. It does not replace any
production service with mocks or in-process substitutes.

## Host sizing

Use an ARM64 or AMD64 Linux VM with at least 4 CPU cores, 16 GB RAM and 100 GB
of persistent storage. Oracle Cloud's Always Free Ampere A1 allowance is a
reasonable target when capacity is available. Free-tier availability and
account eligibility are controlled by Oracle and are not guaranteed by this
repository.

## First deployment

1. Point a hostname at the VM and open inbound TCP 80 and 443 only.
2. Install Git, Docker Engine and the Docker Compose plugin.
3. Clone this repository onto the VM.
4. Copy `.env.demo.example` to `.env.demo` and generate every secret.
5. Run `./infra/demo/deploy.sh`.

The command validates the merged Compose configuration, builds the application,
runs migrations, starts every service, and idempotently creates the large demo
tenant. The published login is printed by the seeder.

## Updating

```bash
git pull --ff-only origin main
./infra/demo/deploy.sh
```

After the first manual deployment, GitHub's `Deploy demo` workflow can perform
the same update over SSH. Create a protected GitHub environment named `demo`
with `DEMO_HOST`, `DEMO_USER`, `DEMO_SSH_KEY`, and `DEMO_KNOWN_HOSTS` secrets.
The repository is expected at `~/nexora-ai` on that host. The workflow never
stores `.env.demo`; deployment secrets remain on the VM.

Tagged releases publish both `linux/amd64` and `linux/arm64` images, so the
production artifacts also remain portable between conventional x86 servers and
free Ampere hosts.

Only Caddy exposes a host port. PostgreSQL, Redis, MinIO, Qdrant, ClamAV,
Mailpit, the raw API, metrics, worker and scheduler remain private on the
Compose network.
