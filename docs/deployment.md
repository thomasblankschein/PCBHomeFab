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
capabilities, a memory limit and a limit of processes (`gateway` keeps only the right to bind ports below 1024;
`keycloak` and `keycloak-db` write to their own folders and have no read-only file system, `keycloak-db` keeps the few
rights its entry point needs to switch to the user `postgres`). The logs of every container are rotated (5 files of 10 MB). State lives in named volumes: `jobs_data` (job database and files, only `jobs`), `keycloak_db` (the accounts,
only `keycloak-db`), `mill_data` (own tool library, only `mill`) and the Caddy volumes (only `gateway`). Do not put the volumes on NFS or
SMB: SQLite needs a local file system.

## First start

```bash
git clone https://github.com/thomasblankschein/PCBHomeFab.git
cd PCBHomeFab
cp .env.example .env
# edit .env: PCBHOMEFAB_PUBLIC_URL, KEYCLOAK_ADMIN_PASSWORD, KEYCLOAK_DB_PASSWORD (openssl rand -hex 24) and SITE_ADDRESS
docker compose up -d --build                # Keycloak needs about a minute to start
scripts/create_user.sh thomas                # asks for the password of the new account (12 or more characters)
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
| `:80` | plain HTTP on port 80: only for a trial on the same computer, or behind another proxy that does TLS. Over a network, passwords and login tokens would travel in plain text. |
| `pcbhomefab.example.org` | public name, Caddy gets a Let's Encrypt certificate (ports 80 and 443 must be reachable) |
| `pcbhomefab.home.arpa` with `CADDY_TLS=tls internal` | HTTPS in the homelab with Caddy's own CA (import its root certificate into the browsers, it is in the `caddy_data` volume under `pki/authorities/local/root.crt`) |

Use HTTPS as soon as other computers use the service, also at home: set `SITE_ADDRESS` to the name, `CADDY_TLS=tls internal`
(or a certificate of your own CA) and `PCBHOMEFAB_PUBLIC_URL=https://<name>`. Plain HTTP redirects to HTTPS then. After the
change set the address in the realm too (see "Login (Keycloak)") and, in the console, Realm settings, General, "Require SSL"
to "all requests".

To try the stack next to another one on the same host, give it another project name and other ports:
`docker compose -p pcbhomefab-trial up -d --build` with `PCBHOMEFAB_HTTP_PORT=8081` and `PCBHOMEFAB_HTTPS_PORT=8444`
in `.env`.

## Login (Keycloak)

The users log in at Keycloak, which the gateway publishes under `/auth`; `jobs` checks the tokens it issues and keeps a
list of jobs per account (ADR-002 in [architecture.md](architecture.md)). The realm `pcbhomefab` is created from
`services/keycloak/realm/pcbhomefab-realm.json` at the first start with an empty database; later starts leave it alone, so
changes in the Keycloak console stay.

**Accounts.** Registration by the users is off. The administrator creates accounts:

- with the script, on the Docker host in the folder of the repository: `scripts/create_user.sh <username> [email] [first name] [last name]`.
  It asks for the password (or takes it from `PCBHOMEFAB_NEW_PASSWORD`) and runs the admin tool of Keycloak inside the
  `keycloak` container, so neither password goes over the network. After a change of the administrator password give the new
  one in `KEYCLOAK_ADMIN_PASSWORD`. Or
- in the console at `<PCBHOMEFAB_PUBLIC_URL>/auth/admin` (user `KEYCLOAK_ADMIN_USER`, default `admin`, and
  `KEYCLOAK_ADMIN_PASSWORD` of the `.env`): realm `pcbhomefab` (switch it at the top left), Users, Add user (fill in e-mail, first
  name and last name: without them the account cannot log in), then the tab Credentials, Set password (turn off
  "Temporary").

Passwords need at least 12 characters and must not equal the username, the e-mail address or one of the last three
passwords. Five wrong tries lock an account for a while (brute-force protection). A login lasts a day without use and a week
at most; the refresh token changes with every renewal.

**Administration.** The gateway passes the console (`/auth/admin`) and the realm `master` of the administrator only to the
addresses in `KEYCLOAK_ADMIN_NETWORKS` (`.env`), for example `192.168.2.10/32` for the computer of the administrator,
several separated by spaces, or `private_ranges` for every private address. By default nobody gets there (404). Behind
another proxy or a tunnel every request comes from the address of that proxy, so do not allow that address. The
`KEYCLOAK_ADMIN_*` values create the administrator of the `master` realm at the first start only. Afterwards, in the
console: create an administrator with your own name and two factors (Authentication, Required actions, "Configure OTP"),
delete the account `admin`, switch on the brute-force protection of the realm `master` (Realm settings, Security defenses)
and remove `KEYCLOAK_ADMIN_PASSWORD` from the `.env` (give it to `create_user.sh` when needed). Keep the `.env` readable for
its owner only: `chmod 600 .env`.

**Events.** The realm stores logins, failed logins and changes of the administrators for 30 days (console, realm
`pcbhomefab`, Events).

**Installations from before 0.26.0.** The realm file is read only at the first start, so an existing realm keeps its old
settings. Change them in the console (realm `pcbhomefab`): Realm settings, Sessions: "SSO Session Idle" 1 day, "SSO Session
Max" 7 days; Realm settings, Tokens: "Revoke Refresh Token" on, "Refresh Token Max Reuse" 0; Authentication, Policies:
length 12, not username, not email, password history 3; Realm settings, Events: save user events and admin events;
Clients, `pcbhomefab-web`: "Valid redirect URIs" `<PCBHOMEFAB_PUBLIC_URL>/auth-callback`, "Valid post logout redirect URIs"
`<PCBHOMEFAB_PUBLIC_URL>/`.

**Registration, password reset, e-mail.** Both need an SMTP server, and the internal network has no access to the
internet. Give the `keycloak` container the network `edge` (or an own network with a mail relay) in the compose file,
set the mail server in the console (realm settings, Email), then switch on "User registration" and "Forgot password"
(realm settings, Login) and "Verify email".

**Other logins.** Two factors, passkeys and social login (Google, GitHub, ...) are settings of the realm in the console;
`jobs` does not change.

**Scripts.** The client `pcbhomefab-cli` allows the password grant (`curl`, `scripts/smoke_test.sh` and the tests of
`tests/e2e` use it). It skips the login page, so it allows no second factor and lets anybody try passwords by script. Switch
it off in the console (realm `pcbhomefab`, Clients, `pcbhomefab-cli`, Enabled) when you do not run the tests, and always on
a public server; `smoke_test.sh` also takes a ready token in `PCBHOMEFAB_TOKEN`.

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
with `503` and `Retry-After` when it is busy; `jobs` waits and retries up to three times. A request that runs into the
time limit of a service is not repeated, and no call lasts longer than the time that is left for the job
(`PCBHOMEFAB_JOB_TIMEOUT_S`). There is exactly one `jobs` container, because it owns the database.

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

1. Create a container (Alpine, Debian 12 or Ubuntu LTS) with **2 cores, 2 GB RAM and 10 GB disk**; that is enough for one or
   two users working one after the other (see "Sizing" below). Enable the container features **nesting** and **keyctl**
   (Options -> Features), without them Docker does not start in an LXC.
2. Install Docker Engine and the compose plugin (see the Docker documentation for Debian; for Alpine see below).
3. Follow "First start". Give the container a fixed address and point a DNS name of your network to it.
4. Back up the volumes `keycloak_db` (the accounts; better a `pg_dump` of the database) and `jobs_data` (the jobs of the
   accounts, which are kept for good now).

Memory: rasterizing one board needs about 100 MB, a panel with many boards a few hundred MB per running request.
The limits in the compose file (`exposure` 1 GB, `ingest`, `mill` and `jobs` 512 MB) fit two parallel requests.

### Sizing

Measured at rest: the nine containers use about 1.1 GB, of which Keycloak takes about 830 MB (its limit is 1 GB). The images
need about 2 GB on disk, and a build leaves a little cache behind. On a 10 GB disk made by the Alpine installer about 7 GB are left for the root file system (the rest is `/boot` and swap); a running installation with the images used 3.4 GB of it.

| | Small (2 cores, 2 GB, 10 GB) | Comfortable (2 cores, 4 GB, 20 GB) |
|---|---|---|
| For | one or two users, one after the other | several users at the same time |
| Host system | Alpine (about 0.2 GB RAM, 0.5 GB disk) | Debian or Ubuntu |
| `PCBHOMEFAB_WORKERS` | 1 (one rasterization at a time) | 2 (default) |
| Swap | the 2.5 GB partition the Alpine installer makes is enough | optional |

With the small size, free the build cache after every update (`docker builder prune -f`, `docker image prune -f`; it is small, so do not expect much), watch the
disk (the jobs are never deleted automatically) and lower `PCBHOMEFAB_MAX_JOBS_PER_USER` if needed. If a container is
killed for lack of memory (`docker inspect` shows `OOMKilled`), give the machine more RAM.

### Alpine as the host

Alpine has no Bash, which `scripts/create_user.sh` and `scripts/smoke_test.sh` need:

```bash
apk add docker docker-cli-compose bash curl git python3 openssl
rc-update add docker default
service docker start
```

In an LXC container Swap is set in the container resources in Proxmox. In a VM the Alpine installer already makes a swap partition of about 2.5 GB, so no swap file is needed (a swap file would only use up the small disk). The containers bring their own
system, so nothing else differs from Debian. The scripts were run on Debian only; if a command of BusyBox behaves differently,
install the full package (`apk add coreutils sed grep`).

## Moving to a root server on the internet

The same `docker-compose.yaml` works unchanged. What changes:

- `SITE_ADDRESS` is the public name and the DNS record points to the server.
- Open only ports 80 and 443 in the firewall, nothing else; the services are not published.
- Never publish the `jobs` or `keycloak` containers directly, only the gateway.
- Keep `KEYCLOAK_ADMIN_NETWORKS` at its default (nobody) or at the fixed address of the administrator; switch off the
  client `pcbhomefab-cli`.
- Tighten the limits in `.env` if needed: `PCBHOMEFAB_RATE_LIMIT_PER_HOUR`, `PCBHOMEFAB_MAX_QUEUED`,
  `PCBHOMEFAB_MAX_UPLOAD_MB`, `PCBHOMEFAB_MAX_JOBS_PER_USER`.
- The rate limits count per account (the login is required for every call). An upload is checked by `ingest` before the job
  exists, so many invalid uploads of one account are not counted as jobs. Consider a firewall rule (for example fail2ban on
  the Caddy log) against abuse of the login page; Keycloak locks accounts after wrong passwords, `ingest` limits its
  parallel requests and answers `503` when busy. Open registration invites abuse of the disk: keep the limit of jobs.

## Operation

- Update: `git pull && docker compose build --pull && docker compose pull keycloak-db && docker compose up -d` (Keycloak
  restarts and the users have to log in again once). `--pull` brings the security updates of the base images, so update
  about once a month even without a new release; take a snapshot of the machine first. Jobs in the queue survive a
  restart; a job that was running at the restart is put back into the queue at the next start.
- Logs: `docker compose logs -f jobs ingest panel exposure mill`. A request carries one `X-Request-Id` through the
  services (`<id>-panel`, `<id>-exposure`, ...), so a job can be followed across the logs. The gateway writes one JSON line
  per request (`docker compose logs gateway`), without the `Authorization` header and cookies.
- API documentation: off, because it needs no login; `PCBHOMEFAB_API_DOCS=true` serves it at `/api/docs`. The contracts in
  `contracts/` describe the same API.
- Health: `GET /healthz` of each service; the containers have Docker health checks.
- Clean up: nothing is deleted automatically (only jobs from before the accounts expire); accounts delete their jobs
  themselves. To see the size: `docker system df -v` (volume `jobs_data`).
