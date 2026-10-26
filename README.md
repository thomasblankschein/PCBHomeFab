# PCBHomeFab

Turn the Gerber files of a single-sided PCB into everything you need to make it at home:

- **Exposure file** (`.pm3`) for UV exposure of photoresist boards on an Anycubic Photon M3 resin printer
  (used as a UV mask: white pixels expose, black pixels block).
- **Drill and mill G-code** for a GRBL hobby CNC mill (tested target: 3018Pro, 20,000 rpm spindle).
- **Panelizing:** several boards (and copies of a board) are packed onto one blank, so one exposure and one
  milling run makes the whole batch.

PCBHomeFab is a small web service that many users can use at the same time, with anonymous sessions and a link per
job. It consists of independent services that talk to each other only through REST APIs.

> **Status:** early development. Gerber ZIP in, `.pm3` and G-code out works end to end. A real frontend and the
> calibration on the real printer and mill are next. See [docs/roadmap.md](docs/roadmap.md).

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

## Run it

```bash
cp .env.example .env            # set PCBHOMEFAB_IP_SALT (openssl rand -hex 32)
docker compose up -d --build
scripts/smoke_test.sh http://localhost
```

Open `http://localhost/`. In the editor you add one or more Gerber ZIPs (drag and drop), see size, holes and board
shape of each, set the copies, the order and the spacing, and watch the boards on the plate (design view, holes coloured
by diameter). Printer, mill, exposure time, hole mode, tabs, flip and the calibration of the printer are in the settings;
they are remembered in the browser. "Create job" leads to the job page with the exposure mask, the mill preview and
the files to download (`exposure.pm3`, one G-code program per tool, all programs as ZIP). `/tools` shows the tool
library. Without accounts, every job gets a random id and the job link `/jobs/<id>` is the only credential. Jobs and
files are deleted after seven days.

The same through the REST API (the gateway publishes the `jobs` service under `/api`):

```bash
curl -F boards=@base.zip -F boards=@node.zip -F counts=1 -F counts=15 -F exposure_s=120 http://localhost/api/v1/jobs
# {"id":"...","status":"queued"}
curl http://localhost/api/v1/jobs/<id>                       # status and file list
curl -O http://localhost/api/v1/jobs/<id>/files/exposure.pm3
```

Other options of `POST /api/v1/jobs`: `exposure`, `mill_gcode` (choose the outputs), `holes`, `gap_mm`, `margin_mm`,
`flip`, `thickness_mm`, `tabs`, `printer`, `mill`, `frame_left_mm`, `frame_bottom_mm`, `mirror_x`.
`GET /api/v1/profiles` lists printers, mills and limits, `GET /api/v1/tools` the tool library. For previews the editor
uses `POST /api/v1/boards` (shape, size and holes of one ZIP) and `POST /api/v1/layouts` (placement on the plate); both
store nothing.

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
node --test services/frontend/tests/geometry.test.mjs   # geometry of the plate preview (Node 20 or newer)
PCBHOMEFAB_URL=http://localhost pytest tests/e2e   # a running stack gives the golden outputs
```

See [CLAUDE.md](CLAUDE.md) for the project conventions and [contracts/README.md](contracts/README.md) for how to
change a contract.

## License

[MIT](LICENSE)
