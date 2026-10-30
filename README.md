# PCBHomeFab

Turn the Gerber files or the KiCad PCB file of a single-sided board into everything you need to make it at home:

- **Exposure file** (`.pm3`) for UV exposure of photoresist boards on an Anycubic Photon M3 resin printer
  (used as a UV mask: white pixels expose, black pixels block).
- **Drill and mill G-code** for a GRBL hobby CNC mill (tested target: 3018Pro, 20,000 rpm spindle).
- **Panelizing:** several boards (and copies of a board) are packed onto one blank, so one exposure and one
  milling run makes the whole batch.

PCBHomeFab is a small web service that many users can use at the same time, with anonymous sessions and a link per
job. It consists of independent services that talk to each other only through REST APIs.

## Features

- **Input:** Gerber ZIP (B.Cu, Edge.Cuts, Excellon drill files) or a KiCad `.kicad_pcb` file read directly (zones filled).
  Several boards per job, several copies per board, files with several outlines.
- **Panelizing:** boards are packed onto a panel of a chosen size (160 x 100, 75 x 100 and 100 x 75 mm built in, own sizes
  possible), with gap and margin. The editor shows the layout live, as design view and as copper underside, with zoom and pan.
- **Exposure:** mask PNG and `.pm3` file for the Anycubic Photon M3 (native writer), exposure time, hole mode
  (full, centre mark, none) and calibration of the panel position and mirroring per printer profile.
- **Positioning marks:** two marks on the copper layer give the zero point of the mill and the rotation of the panel; the
  G-code coordinates are exposed next to them as text.
- **Drilling and milling:** GRBL G-code with one program per tool, tool change pause (`M0`), pecking, outline along the
  real Edge.Cuts contour with tabs, and large holes milled. Tool library with drills 0.6-1.5 mm and end mills 1, 2 and 3 mm
  (replaceable); holes without a drill of their own can be assigned to another drill.
- **Checks before the mill runs:** drill and mill view with hole legend, 3D simulation of the tool paths with copper,
  estimated run times.
- **Job description (PDF):** header data, mask, drill and mill view, tools with their `.nc` files and the production time.
- **Downloads:** every file, all programs as ZIP, or everything (including the PDF) in one ZIP.
- **Service:** anonymous jobs with a link, upload and rate limits, expiry after seven days, Docker Compose with TLS
  (Caddy), English and German pages, REST API with OpenAPI contracts.

How to use it: [docs/manual.md](docs/manual.md).

## How it works

```
Browser ─▶ gateway ─┬─▶ frontend   static pages
                    └─▶ jobs ──┬─▶ ingest     Gerber ZIP  ─▶ canonical board package
                               ├─▶ panel      boards + counts ─▶ placements on the blank
                               ├─▶ exposure   packages + placements ─▶ mask PNG, .pm3
                               └─▶ mill       packages + placements ─▶ G-code programs
```

Each service lives in `services/<name>/` with its own code, tests and `Dockerfile`. The agreements between them
are the contracts in [contracts/](contracts/) (OpenAPI files, JSON schemas, error codes). There is no shared
code. Details and reasons: [docs/architecture.md](docs/architecture.md).

Mask polarity: **white = exposed = copper is etched away**, black = copper stays. A copper pour is kept
automatically.

## Documentation

- [Manual](docs/manual.md): from the KiCad file to the finished board, every setting, the mill procedure, troubleshooting.
- [Deployment](docs/deployment.md): Compose, limits, own tool library and panel sizes, Proxmox, root server.
- [Architecture](docs/architecture.md), [roadmap](docs/roadmap.md), [changelog](CHANGELOG.md).

## Install from git

You need [git](https://git-scm.com/), Docker Engine with the compose plugin (Docker Desktop on Windows or macOS) and
a Bash shell for the smoke test (on Windows: WSL or Git Bash). Nothing else is installed on the host, the images are
built from the repository.

```bash
git clone https://github.com/thomasblankschein/PCBHomeFab.git
cd PCBHomeFab
git checkout vX.Y.Z             # optional: a released version instead of main (list: git tag, notes: CHANGELOG.md)
cp .env.example .env            # set PCBHOMEFAB_IP_SALT (openssl rand -hex 32)
docker compose up -d --build    # the first build takes a few minutes
scripts/smoke_test.sh http://localhost
```

Open `http://localhost/`. With the default `SITE_ADDRESS=:80` the gateway serves plain HTTP on port 80; for a public
name with HTTPS, other ports or a homelab see [docs/deployment.md](docs/deployment.md).

To update an installation:

```bash
git pull                        # or: git fetch --tags && git checkout vX.Y.Z
docker compose up -d --build    # jobs in the queue survive the restart
```

Your `.env` and the Docker volumes (jobs, own tool library) are not touched by an update; read the entry of the new
version in [CHANGELOG.md](CHANGELOG.md) for changed settings. To remove everything: `docker compose down -v` (this
also deletes the stored jobs).

## Use it

In the editor you add one or more Gerber ZIPs or KiCad PCB files (`.kicad_pcb`, zones filled; drag and drop), see size, holes and board
shape of each, set the copies, the order and the spacing, and watch the boards on the panel (design view, holes coloured
by diameter). Printer, mill, exposure time, hole mode, tabs, flip and the calibration of the printer are in the settings;
they are remembered in the browser. "Create job" leads to the job page with the exposure mask, the mill preview and
the files to download (`exposure.pm3`, one G-code program per tool, all programs as ZIP, everything in one ZIP), a job description as PDF (tools, run times) and a 3D simulation of
the drill and mill paths (turn, zoom, play with the tool moving along the paths, copper of the boards shown faintly on the panel; it
can be switched off). `/tools` shows the tool
library. Without accounts, every job gets a random id and the job link `/jobs/<id>` is the only credential. Jobs and
files are deleted after seven days.

The same through the REST API (the gateway publishes the `jobs` service under `/api`):

```bash
curl -F boards=@base.zip -F boards=@node.zip -F counts=1 -F counts=15 -F panel=160x100 -F exposure_s=120 http://localhost/api/v1/jobs
# {"id":"...","status":"queued"}
curl http://localhost/api/v1/jobs/<id>                       # status and file list
curl -O http://localhost/api/v1/jobs/<id>/files/exposure.pm3
```

`panel` (required) is the id of a panel size from `GET /api/v1/panels` (160x100, 75x100 and 100x75 mm built in, the list
is configurable, see [docs/deployment.md](docs/deployment.md)). Other options of `POST /api/v1/jobs`: `exposure`, `mill_gcode` (choose the outputs), `holes`, `gap_mm`, `margin_mm`,
`flip`, `thickness_mm`, `tabs`, `marks`, `printer`, `mill`, `frame_left_mm`, `frame_bottom_mm`, `mirror_x`.
The OpenAPI description is at `GET /api/openapi.json` of the running service and, maintained by hand, in
[contracts/jobs.openapi.yaml](contracts/jobs.openapi.yaml). `GET /api/v1/profiles` lists printers, mills and limits, `GET /api/v1/tools` the tool library. For previews the editor
uses `POST /api/v1/boards` (shape, size and holes of one ZIP) and `POST /api/v1/layouts` (placement on the panel); both
store nothing.

The pages come in English and German; the language switch is in the header (the choice is remembered in the browser, the first
visit follows the browser language). Texts live in `services/frontend/site/locales/<code>.json`; to add a language copy
`en.json`, translate it and add one line to `locales/index.json`. A test checks that every language has all keys and
placeholders. Error messages that come from the services (for example a refused Gerber file) stay in English.

Compose file, limits, own tool library, Proxmox homelab notes and the move to a root server:
[docs/deployment.md](docs/deployment.md).

## Development

Each service is a small Python project (Python 3.12 or newer):

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use .venv/bin/activate elsewhere
pip install -e "services/panel[dev]"
scripts/check_service.sh panel  # ruff, mypy and pytest of one service
```

Checks for the whole repository:

```bash
python scripts/check_contracts.py     # schemas, OpenAPI files and examples are valid
python scripts/check_boundaries.py    # no code shared between services, one volume per service, ports
node --test services/frontend/tests/*.test.mjs   # panel geometry and language files (Node 20 or newer)
PCBHOMEFAB_URL=http://localhost pytest tests/e2e   # a running stack gives the golden outputs
```

See [CLAUDE.md](CLAUDE.md) for the project conventions and [contracts/README.md](contracts/README.md) for how to
change a contract.

## License

[MIT](LICENSE)
