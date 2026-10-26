# Deployment

PCBHomeFab runs as three containers from one `docker-compose.yml`:

| Service | Task |
|---|---|
| `web` | the FastAPI app (uploads, status, downloads); not published, only the proxy reaches it |
| `worker` | takes queued jobs and runs them, one process per job with a time limit; scale with `--scale worker=N` |
| `proxy` | Caddy: HTTPS, request size limit, forwards to `web` |

All services share one volume (`data`) with the job database (SQLite) and the job folders. SQLite works across
containers because they share one host and one file system. Do not put the volume on NFS or SMB.

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

## Homelab on Proxmox

Run the compose project in a VM, or in an LXC container with Docker:

1. Create a Debian 12 (or Ubuntu LTS) container, 2 cores, 2 GB RAM, 8 GB disk are enough for a few users. Enable the
   container features **nesting** and **keyctl** (Options → Features), without them Docker does not start in an LXC.
2. Install Docker Engine and the compose plugin (see the Docker documentation for Debian).
3. Follow "First start". Give the container a fixed address and point a DNS name of your network to it.
4. Back up the `data` volume only if you want to keep job results. Jobs expire after seven days anyway.

Memory: rasterizing one board needs about 100 MB, a panel with many boards a few hundred MB per running job.
Plan for `workers x 500 MB`.

## Moving to a root server on the internet

The same `docker-compose.yml` works unchanged. What changes:

- `SITE_ADDRESS` is the public name and the DNS record points to the server.
- Open only ports 80 and 443 in the firewall, nothing else; `web` is not published.
- Keep `PCBHOMEFAB_TRUST_PROXY=1` (compose sets it) because the client address comes from the proxy. Never publish
  the `web` container directly with that setting, anyone could fake the address.
- Tighten the limits in `.env` if needed: `PCBHOMEFAB_RATE_LIMIT_PER_HOUR`, `PCBHOMEFAB_MAX_QUEUED`,
  `PCBHOMEFAB_MAX_UPLOAD_MB`, `PCBHOMEFAB_JOB_TTL_HOURS`.
- Consider a rate limit or a firewall rule (for example fail2ban on the Caddy log) against abuse; the service limits
  the number of jobs per client and the queue length, but not the number of requests.

## Operation

- Update: `git pull && docker compose up -d --build`. Jobs in the queue survive a restart; jobs that were running are
  put back into the queue by a worker after a restart.
- Logs: `docker compose logs -f web worker`.
- Health: `GET /healthz` (the `web` container has a Docker health check).
- Clean up: expired jobs and their files are deleted by the workers every ten minutes.
