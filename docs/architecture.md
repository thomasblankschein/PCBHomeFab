# Architecture

## Decision: independent services that talk only through REST (ADR-001, 2026-10-26)

**Status:** accepted and implemented, see [migration.md](migration.md) for how the code got here.

### Context

`web` and `worker` shared one SQLite file and one volume, and both imported the core library `pcbhomefab`. None of
the parts could be built, tested or replaced alone. The maintainer wants a clear separation of tasks and one
architecture principle that is kept everywhere.

### Decision

1. The system consists of **independent services**. Each one has one task, its own code, tests, `pyproject.toml`,
   `Dockerfile` and OpenAPI specification, and can be built, deployed and maintained without the others.
2. Services talk to each other and to the outside **only through REST APIs**. No shared database, no shared volume,
   no message broker, no calls into another service's code.
3. **No shared code between services.** There is no common library. What two services must agree on is written down
   as a **contract** in `contracts/` (OpenAPI files and JSON schemas), and every service implements its side itself.
   Small duplication (error handling, request ids, the isolation of requests in `common.py`) is accepted on purpose.
4. **Only `jobs` owns state** (job database, input and output files). All other services are stateless: a request
   carries everything the service needs and the response carries the result.
5. **Calls between services are synchronous.** A processing service answers a `POST` with the result, has a time
   limit per request (each request runs in its own process, so a broken or slow job cannot take the service down)
   and a limit for parallel requests (`503` with `Retry-After` when busy). Only `jobs` offers the asynchronous
   pattern to the browser (`202`-like: the job is created, its state is polled).
6. **Only the gateway is reachable from outside.** All services sit in an internal network without access to the
   internet. The gateway terminates TLS, limits request sizes, and routes to `frontend` and `jobs`.
7. Services live in a **monorepo** (`services/<name>/`) with separate build, tests and CI per service. A change to a
   contract needs the matching change in every service that uses it and is checked in CI.

### Services

```
Browser ─▶ gateway (Caddy: TLS, size limits, routing)
              ├─▶ frontend     static pages
              └─▶ jobs         uploads, job state, files, expiry, workflow
                     ├─▶ ingest     Gerber ZIP  ─▶ canonical board package
                     ├─▶ panel      boards + counts ─▶ placements on the blank
                     ├─▶ exposure   packages + placements ─▶ mask PNG / .pm3
                     └─▶ mill       packages + placements ─▶ G-code programs
```

| Service | Task | Owns | State |
|---|---|---|---|
| `gateway` | TLS, request size limits, routing | Caddy config | none |
| `frontend` | user interface: editor with panel preview, job page, tool library (plain ES modules, no build step); 3D simulation of the G-code on the job page (canvas, no library; the programs are read in the browser); English and German from JSON language files in `site/locales/` (`js/i18n.js`) | static files | none |
| `jobs` | accept uploads, run the workflow (ingest → panel → exposure / mill), store results, expire jobs, give anonymous job links, rate limits, the list of panel sizes (`panels.toml`, configurable like the tool library) | job database, job files | **yes** |
| `ingest` | unpack a ZIP safely, detect the layers, build the canonical board package | ZIP and layer rules | none |
| `panel` | place boards (with counts) on the blank | packing rules | none |
| `exposure` | rasterize copper, build the mask, write `.pm3` | printer profiles, `.pm3` writer | none |
| `mill` | drill and outline G-code | tool library, mill profiles | none |

`jobs` is the only orchestrator. The processing services never call each other; `jobs` passes results from one to
the next. This keeps the dependencies a star instead of a web. `jobs` calls `ingest` while the upload is received, so
a bad ZIP is refused at once with a clear error. `panel`, `exposure` and `mill` are called by the worker threads of
`jobs`; they only wait for HTTP answers, so no separate worker process is needed.

### Contracts

All contracts live in `contracts/` and are the single source of truth. A service may use any tool to generate its
side from them, but it must pass its contract tests (routes of the OpenAPI file exist, bodies validate against the
JSON schemas, errors are `problem+json` with a documented code).

- **Canonical board package** (`application/zip`, output of `ingest`, input of `exposure` and `mill`): a ZIP with
  exactly `copper.gbr` (the bottom copper file as uploaded) and `board.json` (schema version, name, outline box in the
  coordinates of the Gerber file, size, hole list with position, diameter and plating, and the real board contour as
  polygons: outer shape and cutouts from the Edge.Cuts layer, arcs approximated to 0.005 mm). Downstream services accept
  only this layout and these two file names. They need no ZIP safety logic and no Excellon parser: `exposure`
  rasterizes `copper.gbr` and takes the holes from `board.json`, `mill` needs only `board.json`.
  *Changed from the first draft:* the draft also carried `outline.gbr` and `drills.drl`. Everything downstream
  needs from them is the outline box and the holes, which `ingest` extracts once; copying the files would only make
  `exposure` and `mill` parse them again.
- **Layout** (JSON, output of `panel`, input of `exposure` and `mill`): the panel size and a list of placements
  `{board_id, x_mm, y_mm, rotation_deg}`. `exposure` and `mill` apply the transform themselves.
- **Errors:** `application/problem+json` (RFC 9457) with a stable `code` per error kind (`contracts/errors.md`).
- **Operational rules for every service:** `GET /healthz`, versioned paths (`/v1/...`), an `X-Request-Id` header
  that is passed on and logged, structured logs to stdout, configuration only through environment variables.
- **Units:** millimetres and degrees everywhere in the API; pixels exist only inside `exposure`.

Endpoints (the OpenAPI files are authoritative):

| Service | Endpoint | Purpose |
|---|---|---|
| `ingest` | `POST /v1/packages` | ZIP (and a name) in, canonical package out |
| `panel` | `POST /v1/layouts` | panel, boards, counts, spacing in; placements out |
| `exposure` | `GET /v1/profiles` | available printer profiles |
| `exposure` | `POST /v1/masks` | packages, layout, settings in; ZIP with `mask.png`, `mask_preview.png`, `exposure.pm3` out |
| `mill` | `GET /v1/profiles`, `GET /v1/tools` | mill profiles, tool library |
| `mill` | `POST /v1/programs` | packages, layout, settings in; ZIP with one `.nc` per tool, `preview.svg`, `programs.json` out |
| `jobs` | `POST /v1/jobs`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/files/{name}`, `GET /v1/profiles`, `GET /v1/tools` | what the browser uses (behind `/api` at the gateway) |
| `jobs` | `POST /v1/boards`, `POST /v1/layouts` | previews for the editor: board info from `ingest`, placement from `panel`; nothing is stored, limited per client |

### Consequences

- Positive: each service has a small surface and can be rebuilt, tested and replaced alone; the principle is easy to
  check (`scripts/check_boundaries.py`: no import across services, no shared volume, only the gateway has ports).
- Negative: more containers and more moving parts than before, debugging crosses processes (hence `X-Request-Id`),
  and tests that used direct function calls became contract and HTTP tests.
- Accepted duplication: `common.py` exists once per service, the package reader once in `exposure` and `mill`.
- The command line interface and the importable library `pcbhomefab` are gone. Everything runs through the services.
  The option to take lift and retract parameters from a Photon Workshop `.pm3` file as a template still exists in
  `exposure/pm3.py` but is not reachable through the API yet.
- Redis stays out of the design. The queue is the job table inside `jobs`.

## Anonymous sessions (owned by `jobs`)

- Creating a job returns a random, unguessable job id; the link `/jobs/<id>` is the only credential.
- Jobs and files expire after a fixed time (default 7 days).
- Limits per job: upload size, number of files, number of boards. Rate limit per client (hashed address) and a
  limit for the queue length. Time and memory limits per request live in the processing services.

## Pipeline

1. **Ingest** (`ingest`): unpack the ZIP safely (no path traversal, size and file-count limits), detect the layers by
   file function (`TF.FileFunction` attributes or name patterns): bottom copper, profile, drill (PTH/NPTH).
2. **Panelize** (`panel`): pack boards (with counts) onto the blank in rows from the bottom left.
3. **Rasterize and mask** (`exposure`): draw the bottom copper Gerber directly to a bitmap (40 µm per pixel). Dark =
   copper. White = no copper = exposed. Mirror in X. Output 1-bit PNG at display resolution.
4. **`.pm3`** (`exposure`): build the file for the selected printer profile.
5. **G-code** (`mill`): group holes by diameter, one program per tool, outline along the real contour (offset by the
   tool radius, tabs on the long sides, cutouts first), preview as SVG. A board whose Edge.Cuts layer is not made of
   closed loops of lines and arcs is milled as its box. Panelizing still uses the box of each board.

## Profiles and tool library (data, not code)

- **Printer profile** (`exposure`): display resolution and size, frame offsets (calibration), mirror mode,
  machine name and machine table template, default exposure. The job can override the calibration values.
- **Positioning marks:** `jobs` decides where they go (`marks.py`), `exposure` draws them into the mask and into `copper.png`,
  `mill` shifts X0 Y0 to the lower left mark (contract `mark.schema.json`).
- **Mill profile** (`mill`): controller dialect (GRBL), highest spindle speed, outline end mill, safe height, tool change height, tab
  size, flip mode, work area.
- **Tool library** (`mill`, `tools.toml`): every drill bit and end mill with its cutting data (spindle rpm, feeds,
  peck / step down). TOML was chosen because it is readable, diffable, needs no extra dependency (`tomllib`) and fits
  a git repository or a Docker volume. `[defaults.drill]` and `[defaults.endmill]` hold shared values, each
  `[[tool]]` overrides them; `enabled = false` hides a tool. A user file (`PCBHOMEFAB_TOOLS_FILE` in the mill
  container) replaces the built-in library as a whole.
  Hole rules: a hole gets the drill of the same diameter (tolerance 0.02 mm); holes larger than the largest drill
  are milled with the outline end mill (or a smaller one if it does not fit); anything in between is an error that
  lists the available drills. One G-code program per tool, spindle speed per tool, limited by the machine.

## `.pm3` writer (`exposure`)

Native (format version 516). It follows the layout of the open source UVtools implementation and is checked three
ways: reading the file back with its own reader (pixel-exact), reading it with UVtools (optional test) and comparing
the MACHINE table with a file written by Photon Workshop. No UVtools, .NET or GPL code is needed at run time, so the
container stays small.

## Deployment

Docker Compose with one image per service, an internal network without internet access, and only the gateway
publishes ports 80 and 443. The `jobs` container is the only one with the job volume. Runs on a VM or LXC with Docker
in the Proxmox homelab first; the same compose file must work unchanged on an internet-facing root server (only the
gateway settings and limits change). See [deployment.md](deployment.md).
