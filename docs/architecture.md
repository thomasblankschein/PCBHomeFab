# Architecture

## Decision: independent services that talk only through REST (ADR-001, 2026-10-26)

**Status:** accepted. The code base is still the single package `pcbhomefab` plus the web service; it is moved to
the target below step by step, see [migration.md](migration.md). Until a step is done, the text under "Current
state" is what runs.

### Context

`web` and `worker` share one SQLite file and one volume, and both import the core library `pcbhomefab`. None of the
parts can be built, tested or replaced alone. The maintainer wants a clear separation of tasks and one architecture
principle that is kept everywhere.

### Decision

1. The system consists of **independent services**. Each one has one task, its own code, tests, `pyproject.toml`,
   `Dockerfile` and OpenAPI specification, and can be built, deployed and maintained without the others.
2. Services talk to each other and to the outside **only through REST APIs**. No shared database, no shared volume,
   no message broker, no calls into another service's code.
3. **No shared code between services.** There is no common library. What two services must agree on is written down
   as a **contract** in `contracts/` (OpenAPI files and JSON schemas), and every service implements its side itself.
   Small duplication (error handling, unit conversion) is accepted on purpose.
4. **Only `jobs` owns state** (job database, input and output files). All other services are stateless: a request
   carries everything the service needs and the response carries the result.
5. **Calls between services are synchronous.** A processing service answers a `POST` with the result, has a time
   limit per request (each request runs in its own process, so a broken or slow job cannot take the service down)
   and a limit for parallel requests (`503` with `Retry-After` when busy). Only `jobs` offers the asynchronous
   pattern to the browser (`202`, status URL, polling).
6. **Only the gateway is reachable from outside.** All services sit in an internal network. The gateway terminates
   TLS, limits request sizes and rates, and routes to `frontend` and `jobs`.
7. Services run in a **monorepo** (`services/<name>/`) with separate build and test per service. A change to a
   contract needs the matching change in every service that uses it and is checked in CI.

### Services

```
Browser ─▶ gateway (Caddy: TLS, size and rate limits, routing)
              ├─▶ frontend     static single page app (later)
              └─▶ jobs         uploads, job state, files, expiry, workflow
                     ├─▶ ingest     Gerber ZIP  ─▶ canonical board package
                     ├─▶ panel      boards + counts ─▶ placements on the blank
                     ├─▶ exposure   packages + placements ─▶ mask PNG / .pm3
                     └─▶ mill       packages + placements ─▶ G-code programs
```

| Service | Task | Owns | State |
|---|---|---|---|
| `gateway` | TLS, request size and rate limits, routing | Caddy config | none |
| `frontend` | user interface | static files | none |
| `jobs` | accept uploads, run the workflow (ingest → panel → exposure / mill), store results, expire jobs, give anonymous job links | job database, job files | **yes** |
| `ingest` | unpack a ZIP safely, detect the layers, build the canonical board package | ZIP and layer rules | none |
| `panel` | place boards (with counts) on the blank | packing rules | none |
| `exposure` | rasterize copper, build the mask, write `.pm3` | printer profiles, `.pm3` writer | none |
| `mill` | drill and outline G-code | tool library, mill profiles | none |

`jobs` is the only orchestrator. The processing services never call each other; `jobs` passes results from one to
the next. This keeps the dependencies a star instead of a web.

### Contracts

All contracts live in `contracts/` and are the single source of truth. A service may use any tool to generate its
side from them, but it must pass the contract tests.

- **Canonical board package** (`application/zip`, output of `ingest`, input of `exposure` and `mill`): a ZIP with
  exactly `copper.gbr` (bottom copper), `outline.gbr`, `drills.drl` (Excellon, metric) and `board.json`
  (schema version, size and bounding box in mm, hole list with diameter and plating, layer roles). Downstream
  services accept only this layout and fixed file names. They need no ZIP safety logic and read the Gerber and
  Excellon data themselves.
- **Layout** (JSON, output of `panel`, input of `exposure` and `mill`): the blank size and a list of placements
  `{board_id, x_mm, y_mm, rotation_deg}`. `exposure` and `mill` apply the transform themselves.
- **Errors:** `application/problem+json` (RFC 9457) with a stable `code` per error kind. The list of codes is part
  of the contract so `jobs` can show a useful message.
- **Operational rules for every service:** `GET /healthz`, versioned paths (`/v1/...`), an `X-Request-Id` header
  that is passed on and logged, structured logs to stdout, configuration only through environment variables.
- **Units:** millimetres and degrees everywhere in the API; pixels exist only inside `exposure`.

Planned endpoints (the OpenAPI files are authoritative once they exist):

| Service | Endpoint | Purpose |
|---|---|---|
| `ingest` | `POST /v1/packages` | ZIP in, canonical package out |
| `panel` | `POST /v1/layouts` | blank, boards, counts, spacing in; placements out |
| `exposure` | `GET /v1/profiles` | available printer profiles |
| `exposure` | `POST /v1/masks` | packages, layout, profile in; PNG or `.pm3` out (`format` parameter) |
| `mill` | `GET /v1/tools` | tool library |
| `mill` | `POST /v1/programs` | packages, layout, options in; G-code programs out (one per tool) |
| `jobs` | `POST /v1/jobs`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/files/{name}` | what the browser uses |

### Consequences

- Positive: each service has a small surface and can be rebuilt, tested and replaced alone; the principle is easy to
  check (no import across services, no shared mount).
- Negative: more containers and more moving parts than today, debugging crosses processes (hence `X-Request-Id`),
  and tests that used direct function calls become contract and HTTP tests.
- Accepted duplication: error mapping, request handling and a few helpers exist in several services.
- The command line interface and the importable library are dropped. Everything runs through the services.
- Redis stays out of the design. The queue is the job table inside `jobs`.

## Anonymous sessions (owned by `jobs`)

- Creating a job returns a random, unguessable job id; the link `/jobs/<id>` is the only credential.
- Jobs and files expire after a fixed time (default 7 days).
- Limits per job: upload size, number of files, unpacked size, CPU time, memory. Rate limit per IP at the gateway.

## Pipeline

1. **Ingest** (`ingest`): unpack the ZIP safely (no path traversal, size and file-count limits), detect the layers by
   file function (`TF.FileFunction` attributes or name patterns): bottom copper, profile, drill (PTH/NPTH).
2. **Panelize** (`panel`): pack boards (with counts) onto the blank in rows from the bottom left.
3. **Rasterize and mask** (`exposure`): draw the bottom copper Gerber directly to a bitmap (40 µm per pixel). Dark =
   copper. White = no copper = exposed. Mirror in X. Output 1-bit PNG at display resolution.
4. **`.pm3`** (`exposure`): build the file for the selected printer profile.
5. **G-code** (`mill`): group holes by diameter, one program per tool, outline with tabs, optional preview.

## Profiles and tool library (data, not code)

- **Printer profile** (`exposure`): display resolution and size, frame offsets (calibration), mirror mode, border
  width, machine name and machine table template, default exposure.
- **Mill profile** (`mill`): controller dialect (GRBL), highest spindle speed, outline end mill, safe height, tab
  size, flip mode, work area.
- **Tool library** (`mill`, `tools.toml`): every drill bit and end mill with its cutting data (spindle rpm, feeds,
  peck / step down). TOML was chosen because it is readable, diffable, needs no extra dependency (`tomllib`) and fits
  a git repository or a Docker volume. `[defaults.drill]` and `[defaults.endmill]` hold shared values, each
  `[[tool]]` overrides them; `enabled = false` hides a tool. A user file (`PCBHOMEFAB_TOOLS_FILE`) replaces the
  built-in library as a whole.
  Hole rules: a hole gets the drill of the same diameter (tolerance 0.02 mm); holes larger than the largest drill
  are milled with the outline end mill (or a smaller one if it does not fit); anything in between is an error that
  lists the available drills. One G-code program per tool, spindle speed per tool, limited by the machine.

## `.pm3` writer (`exposure`)

Native (format version 516). It follows the layout of the open source UVtools implementation and is checked three
ways: reading the file back with its own reader (pixel-exact), reading it with UVtools (optional test) and comparing
the MACHINE table with a file written by Photon Workshop. No UVtools, .NET or GPL code is needed at run time, so the
container stays small.

## Deployment

Docker Compose with one image per service, one internal network, and only the gateway publishes ports 80 and 443.
The `jobs` container is the only one with a volume. Runs on a VM or LXC with Docker in the Proxmox homelab first;
the same compose file must work unchanged on an internet-facing root server (only the gateway and limits change).

## Current state (until the migration is done)

```
frontend (later)  ──HTTP──▶  api (FastAPI)  ──queue──▶  worker  ──▶  pcbhomefab (core library)
                                │                          │
                                └────── storage (files with expiry, job metadata) ──┘
```

- **Core library `pcbhomefab`** (`src/pcbhomefab/`): pure Python, no web dependencies; contains all of the logic
  above.
- **API and worker** (`src/pcbhomefab/service/`): the API accepts uploads and serves results; workers run jobs, each
  in its own process with a time limit. The job database (SQLite, WAL mode) is the queue and the worker claims the
  oldest queued job with an atomic update. Files live in one folder per job (`input/`, `output/`).
- **Compose:** `proxy` (Caddy), `web`, `worker`, one shared volume.
