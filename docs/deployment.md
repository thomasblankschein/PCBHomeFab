# Deployment

PCBHomeFab runs as nine containers from one `docker-compose.yaml`:

| Service | Task | Reachable from |
|---|---|---|
| `gateway` | Caddy: HTTPS, request size limit, routes `/` to `frontend`, `/api/...` to `jobs` and `/auth/...` to `keycloak` | outside (ports 80, 443) |
| `keycloak` | the login (OpenID Connect): accounts, passwords, tokens | `gateway`, `jobs` (public keys) |
| `keycloak-db` | PostgreSQL, only for `keycloak` | `keycloak` |
| `frontend` | static pages | `gateway` |
| `jobs` | uploads, job state, workflow, downloads; checks the access tokens; the only one of our own services with state | `gateway` |
| `ingest` | Gerber ZIP to canonical board package | `jobs` |
| `panel` | places boards on the blank | `jobs` |
| `exposure` | exposure mask and `.pm3` | `jobs` |
| `mill` | G-code, tool library | `jobs` |

Only `gateway` publishes ports. All services share the network `internal`, which has no access to the internet or
the host; only `gateway` is also on the network `edge`. Every service has its own image, a read-only file system, no
capabilities and a memory limit (`keycloak` and `keycloak-db` write to their own folders and have no read-only file
system). State lives in named volumes: `jobs_data` (job database and files, only `jobs`), `keycloak_db` (the accounts,
only `keycloak-db`), `mill_data` (own tool library, only `mill`) and the Caddy volumes (only `gateway`). Do not put the volumes on NFS or
SMB: SQLite needs a local file system.

## First start

```bash
git clone https://github.com/thomasblankschein/PCBHomeFab.git
cd PCBHomeFab
cp .env.example .env
# edit .env: PCBHOMEFAB_PUBLIC_URL, KEYCLOAK_ADMIN_PASSWORD, KEYCLOAK_DB_PASSWORD (openssl rand -hex 24) and SITE_ADDRESS
docker compose up -d --build                # Keycloak needs about a minute to start
KEYCLOAK_ADMIN_PASSWORD=... scripts/create_user.sh http://localhost thomas 'a-password-of-10-or-more-characters'
PCBHOMEFAB_USER=thomas PCBHOMEFAB_PASSWORD=... scripts/smoke_test.sh http://localhost   # creates a job and checks the result
```

`PCBHOMEFAB_PUBLIC_URL` is the address the users type, with `http://` or `https://`, a port if it is not 80/443 and no
slash at the end (for example `https://pcbhomefab.example.org` or `http://localhost:8081`). Keycloak puts it into the
login tokens (`iss`) and the registered redirect addresses, and `jobs` accepts only tokens with it. After a change of
the address, the realm has to be changed too (see "Login (Keycloak)" below); the simplest way for a new installation is
to set it right before the first start.

`SITE_ADDRESS` in `.env`:

| Value | Result |
|---|---|
| `:80` | plain HTTP on port 80 (trial, or behind another proxy) |
| `pcbhomefab.example.org` | public name, Caddy gets a Let's Encrypt certificate (ports 80 and 443 must be reachable) |
| `pcbhomefab.home.arpa` with `CADDY_TLS=tls internal` | HTTPS in the homelab with Caddy's own CA (import its root certificate into the browsers, it is in the `caddy_data` volume under `pki/authorities/local/root.crt`) |

To try the stack next to another one on the same host, give it another project name and other ports:
`docker compose -p pcbhomefab-trial up -d --build` with `PCBHOMEFAB_HTTP_PORT=8081` and `PCBHOMEFAB_HTTPS_PORT=8444`
in `.env`.

## Login (Keycloak)

The users log in at Keycloak, which the gateway publishes under `/auth`; `jobs` checks the tokens it issues and keeps a
list of jobs per account (ADR-002 in [architecture.md](architecture.md)). The realm `pcbhomefab` is created from
`services/keycloak/realm/pcbhomefab-realm.json` at the first start with an empty database; later starts leave it alone, so
changes in the Keycloak console stay.

**Accounts.** Registration by the users is off. The administrator creates accounts:

- with the script: `KEYCLOAK_ADMIN_PASSWORD=... scripts/create_user.sh <address> <username> <password> [email] [first name] [last name]`, or
- in the console at `<PCBHOMEFAB_PUBLIC_URL>/auth/admin` (user `KEYCLOAK_ADMIN_USER`, default `admin`, and
  `KEYCLOAK_ADMIN_PASSWORD` of the `.env`): realm `pcbhomefab` (switch it at the top left), Users, Add user (fill in e-mail, first
  name and last name: without them the account cannot log in), then the tab Credentials, Set password (turn off
  "Temporary").

Passwords need at least 10 characters and must not equal the username. Five wrong tries lock an account for a while
(brute-force protection). The `KEYCLOAK_ADMIN_*` values create the administrator of the `master` realm at the first
start only; to change the password later, use the console. For a public server, restrict `/auth/admin` at the gateway
(for example to the home network) or change the Caddyfile.

**Registration, password reset, e-mail.** Both need an SMTP server, and the internal network has no access to the
internet. Give the `keycloak` container the network `edge` (or an own network with a mail relay) in the compose file,
set the mail server in the console (realm settings, Email), then switch on "User registration" and "Forgot password"
(realm settings, Login) and "Verify email".

**Other logins.** Two factors, passkeys and social login (Google, GitHub, ...) are settings of the realm in the console;
`jobs` does not change.

**Scripts.** The client `pcbhomefab-cli` allows the password grant (`curl` and the tests of `tests/e2e` use it). Switch
it off in the console (realm `pcbhomefab`, Clients) if you do not need it.

**Limits.** Jobs are never deleted automatically. `PCBHOMEFAB_MAX_JOBS_PER_USER` (default 200, 0 = unlimited) limits the
jobs of an account, `PCBHOMEFAB_RATE_LIMIT_PER_HOUR` the jobs an account creates per hour. Watch the size of the volume
`jobs_data`.

**Moving from the anonymous version (up to 0.23).** Jobs of that time have no owner: nobody can open them, they expire
(after their seven days) and are deleted. Set the new values in the `.env` (the old `PCBHOMEFAB_IP_SALT` and
`PCBHOMEFAB_JOB_TTL_HOURS` are not used any more), create the accounts, and tell the users the new address.

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
4. Back up the volumes `keycloak_db` (the accounts; better a `pg_dump` of the database) and `jobs_data` (the jobs of the
   accounts, which are kept for good now).

Memory: rasterizing one board needs about 100 MB, a panel with many boards a few hundred MB per running request.
The limits in the compose file (`exposure` 1 GB, `ingest`, `mill` and `jobs` 512 MB) fit two parallel requests.

## Moving to a root server on the internet

The same `docker-compose.yaml` works unchanged. What changes:

- `SITE_ADDRESS` is the public name and the DNS record points to the server.
- Open only ports 80 and 443 in the firewall, nothing else; the services are not published.
- Never publish the `jobs` or `keycloak` containers directly, only the gateway.
- Tighten the limits in `.env` if needed: `PCBHOMEFAB_RATE_LIMIT_PER_HOUR`, `PCBHOMEFAB_MAX_QUEUED`,
  `PCBHOMEFAB_MAX_UPLOAD_MB`, `PCBHOMEFAB_MAX_JOBS_PER_USER`.
- The rate limits count per account (the login is required for every call). An upload is checked by `ingest` before the job
  exists, so many invalid uploads of one account are not counted as jobs. Consider a firewall rule (for example fail2ban on
  the Caddy log) against abuse of the login page; Keycloak locks accounts after wrong passwords, `ingest` limits its
  parallel requests and answers `503` when busy. Open registration invites abuse of the disk: keep the limit of jobs.

## Operation

- Update: `git pull && docker compose up -d --build` (Keycloak restarts and the users have to log in again once). Jobs in the queue survive a restart; a job that was running at the
  restart is put back into the queue at the next start once it has been running for more than twice the job
  time limit.
- Logs: `docker compose logs -f jobs ingest panel exposure mill`. A request carries one `X-Request-Id` through the
  services (`<id>-panel`, `<id>-exposure`, ...), so a job can be followed across the logs.
- Health: `GET /healthz` of each service; the containers have Docker health checks.
- Clean up: nothing is deleted automatically (only jobs from before the accounts expire); accounts delete their jobs
  themselves. To see the size: `docker system df -v` (volume `jobs_data`).
