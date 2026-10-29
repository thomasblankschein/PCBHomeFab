# Deployment

PCBHomeFab runs as seven containers from one `docker-compose.yaml`:

| Service | Task | Reachable from |
|---|---|---|
| `gateway` | Caddy: HTTPS, request size limit, routes `/` to `frontend` and `/api/...` to `jobs` | outside (ports 80, 443) |
| `frontend` | static pages | `gateway` |
| `jobs` | uploads, job state, workflow, downloads, expiry; the only service with state | `gateway` |
| `ingest` | Gerber ZIP to canonical board package | `jobs` |
| `panel` | places boards on the blank | `jobs` |
| `exposure` | exposure mask and `.pm3` | `jobs` |
| `mill` | G-code, tool library | `jobs` |

Only `gateway` publishes ports. All services share the network `internal`, which has no access to the internet or
the host; only `gateway` is also on the network `edge`. Every service has its own image, a read-only file system, no
capabilities and a memory limit. State lives in named volumes: `jobs_data` (job database and files, only `jobs`),
`mill_data` (own tool library, only `mill`) and the Caddy volumes (only `gateway`). Do not put the volumes on NFS or
SMB: SQLite needs a local file system.

## First start

```bash
git clone https://github.com/thomasblankschein/PCBHomeFab.git
cd PCBHomeFab
cp .env.example .env
# edit .env: set PCBHOMEFAB_IP_SALT (openssl rand -hex 32) and SITE_ADDRESS
docker compose up -d --build
scripts/smoke_test.sh http://localhost      # creates a job and checks the result
```

`SITE_ADDRESS` in `.env`:

| Value | Result |
|---|---|
| `:80` | plain HTTP on port 80 (trial, or behind another proxy) |
| `pcbhomefab.example.org` | public name, Caddy gets a Let's Encrypt certificate (ports 80 and 443 must be reachable) |
| `pcbhomefab.home.arpa` with `CADDY_TLS=tls internal` | HTTPS in the homelab with Caddy's own CA (import its root certificate into the browsers, it is in the `caddy_data` volume under `pki/authorities/local/root.crt`) |

To try the stack next to another one on the same host, give it another project name and other ports:
`docker compose -p pcbhomefab-trial up -d --build` with `PCBHOMEFAB_HTTP_PORT=8081` and `PCBHOMEFAB_HTTPS_PORT=8444`
in `.env`.

## Scaling

The processing services keep no state. Run more of them when jobs wait for each other:
`docker compose up -d --scale exposure=2 --scale mill=2`. Docker's DNS spreads the calls of `jobs` over the copies.
Each copy runs at most `MAX_PARALLEL` requests at the same time (`exposure` 2, `ingest` and `mill` 4, `panel` 8) and answers
with `503` and `Retry-After` when it is busy; `jobs` waits and retries up to three times. There is exactly one
`jobs` container, because it owns the database.

## Own panel sizes

The panel sizes a user can choose are data of the `jobs` service (`services/jobs/src/jobs/data/panels.toml`: 160 x 100,
75 x 100 and 100 x 75 mm). Replace the list the same way as the tool library, with the file in the `jobs_data` volume:

```bash
docker compose run --rm --no-deps jobs python -c "from jobs.panels import default_text; print(default_text())" > panels.toml
# edit panels.toml, then copy it into the volume:
docker run --rm -v pcbhomefab_jobs_data:/data -v "$PWD":/src alpine cp /src/panels.toml /data/panels.toml
# in .env:  PCBHOMEFAB_PANELS_FILE=/data/panels.toml
docker compose up -d jobs
```

A wrong file stops the `jobs` service at start with a message that names the problem. The file is read at start, so
restart `jobs` after a change. A job keeps the size it was made with. The panel and the offsets of the printer must fit
on its display, otherwise `exposure` refuses the job (`exposure.panel_too_large`). `GET /api/v1/panels` shows the list
in use.

## Own tool library

The built-in tool library (drills 0.6-1.5 mm, end mills 1, 2 and 3 mm) can be replaced. Copy it out, edit it, put it
into the `mill_data` volume and point the mill service to it:

```bash
docker compose run --rm --no-deps mill python -c "from mill.tools import default_text; print(default_text())" > tools.toml
# edit tools.toml, then copy it into the volume:
docker run --rm -v pcbhomefab_mill_data:/data -v "$PWD":/src alpine cp /src/tools.toml /data/tools.toml
# in .env:  PCBHOMEFAB_TOOLS_FILE=/data/tools.toml
docker compose up -d mill
```

The file is read for each request, so later edits apply to the next job without a restart. `GET /api/v1/tools`
shows the library in use.

## Homelab on Proxmox

Run the compose project in a VM, or in an LXC container with Docker:

1. Create a Debian 12 (or Ubuntu LTS) container, 2 cores, 3 GB RAM, 8 GB disk are enough for a few users. Enable the
   container features **nesting** and **keyctl** (Options -> Features), without them Docker does not start in an LXC.
2. Install Docker Engine and the compose plugin (see the Docker documentation for Debian).
3. Follow "First start". Give the container a fixed address and point a DNS name of your network to it.
4. Back up the `jobs_data` volume only if you want to keep job results. Jobs expire after seven days anyway.

Memory: rasterizing one board needs about 100 MB, a panel with many boards a few hundred MB per running request.
The limits in the compose file (`exposure` 1 GB, `ingest`, `mill` and `jobs` 512 MB) fit two parallel requests.

## Moving to a root server on the internet

The same `docker-compose.yaml` works unchanged. What changes:

- `SITE_ADDRESS` is the public name and the DNS record points to the server.
- Open only ports 80 and 443 in the firewall, nothing else; the services are not published.
- `jobs` trusts the `X-Forwarded-For` header of the gateway (`TRUST_PROXY=1`, set by the compose file) to see the
  client address. Never publish the `jobs` container directly, anyone could fake the address.
- Tighten the limits in `.env` if needed: `PCBHOMEFAB_RATE_LIMIT_PER_HOUR`, `PCBHOMEFAB_MAX_QUEUED`,
  `PCBHOMEFAB_MAX_UPLOAD_MB`, `PCBHOMEFAB_JOB_TTL_HOURS`.
- The rate limit counts created jobs. An upload is checked by `ingest` before the job exists, so many invalid
  uploads are not counted. Consider a rate limit or a firewall rule (for example fail2ban on the Caddy log) against
  abuse; `ingest` limits its parallel requests and answers `503` when busy.

## Operation

- Update: `git pull && docker compose up -d --build`. Jobs in the queue survive a restart; a job that was running at the
  restart is put back into the queue at the next start once it has been running for more than twice the job
  time limit.
- Logs: `docker compose logs -f jobs ingest panel exposure mill`. A request carries one `X-Request-Id` through the
  services (`<id>-panel`, `<id>-exposure`, ...), so a job can be followed across the logs.
- Health: `GET /healthz` of each service; the containers have Docker health checks.
- Clean up: expired jobs and their files are deleted by `jobs` every ten minutes.
