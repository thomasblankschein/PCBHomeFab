# CLAUDE.md – PCBHomeFab project context

This file keeps the state and decisions of the project so a new session can continue without the original
chat history. **Language of the project: English** (code, comments, docs, commit messages, UI text).
Conversations with the maintainer are in German.

## Goal

A small web service (independent services behind one gateway) that turns the Gerber files of a **single-sided PCB** into
home-fabrication files:

1. UV exposure file `.pm3` for an Anycubic Photon M3 resin printer used as a UV mask for photoresist boards.
2. GRBL G-code for drilling and milling the outline on a hobby CNC (3018Pro, 20,000 rpm spindle).
3. Panelizing of several boards onto one 160 x 100 mm blank, shared by both outputs.

Origin: the scripts `kicad_zu_photon.py` and `kicad_zu_gcode.py` in
[fbh-monitor](https://github.com/thomasblankschein/fbh-monitor) (`tools/platinenbelichtung`, `tools/fraesen`).
They are the reference for behaviour until the port is finished.

## Decisions (made with the maintainer)

- Name **PCBHomeFab**, public repository, **MIT** license.
- Input: **Gerber ZIP** first (B.Cu, Edge.Cuts, Excellon drill files). KiCad `.kicad_pcb` input is a later option.
- Users: **anonymous sessions**, every job has a link. No accounts for now.
- Hosting: first on the maintainer's Proxmox homelab (Docker), later possibly a root server on the internet.
  Everything must therefore be stateless per request, limits on uploads/CPU time from day one.
- Stack: FastAPI, jobs queued in SQLite inside `jobs` (no broker, worker threads claim jobs atomically), every
  request to a processing service runs in its own process with a time limit, small SPA frontend later, Docker Compose.
- **Architecture (ADR-001, 2026-10-26, see `docs/architecture.md` and `docs/migration.md`):** independent services
  (`gateway`, `frontend`, `jobs`, `ingest`, `panel`, `exposure`, `mill`) that talk only through REST, **no shared
  code** between services, contracts in `contracts/`, only `jobs` holds state, calls between services are
  synchronous. The CLI and the importable library `pcbhomefab` are gone. Migration done on 2026-10-26, tag
  `pre-services` is the last commit of the single-package code. Keep it that way: `scripts/check_boundaries.py`
  enforces it in CI.

## Domain knowledge to keep

- Photon M3: display 4096 x 2560 px, 163.84 x 102.4 mm, **40 µm per pixel**. The plate (160 x 100 mm) sits in a
  frame 1.8 mm from the left and 0.8 mm from the bottom of the display. These offsets are assumptions taken from the
  maintainer's notes and must be **calibration values per profile**, not hard-coded.
- Mask polarity for positive photoresist: **white = exposed = copper is etched away**, black = copper stays.
  A copper pour in the Gerber must stay black. (An early version inverted this by mistake, keep a test for it.)
- Orientation (corrected 2026-10-27): the Gerber of B.Cu is a top view, text on it is mirrored. The plate lies on the LCD with the
  copper side down, so the mask on the LCD is that top view **as it is, not mirrored** (`PrinterProfile.mirror_x = False`;
  the setting stays as a calibration value). Seen from the copper side the etched copper is then the mirror image of the top
  view, text on B.Cu reads correctly. The mill works on the same side: `flip x` mirrors X, so G-code coordinates are the
  copper-side view.
- `.pm3` (Anycubic format, version 516): Photon Workshop rejects files whose machine table names an unknown printer
  ("Unknown"). The MACHINE table (156 bytes) of a file Photon Workshop wrote for the M3 is stored in the profile
  values (`PHOTON_M3`) and in `services/exposure/tests/data/photon_m3_machine_table.bin`; the name is `Anycubic Photon M3`. The writer is
  native (`services/exposure/src/exposure/pm3.py`). Layer images are run length encoded: black/white runs as two bytes (`nibble << 12 | length`,
  at most 4095). UVtools 7.1 cannot convert a single image and cannot edit a finished `.pm3`, which is why the
  first version of the writer used a long detour; it is no longer needed.
- GRBL: no canned drill cycles, write explicit moves. Every program starts at the tool change position (`MillProfile.tool_change_z_mm`,
  X0 Y0, spindle off) and pauses with `M0` so the tool can be inserted and Z0 set, then the user resumes in the sender; it parks at
  the same position at the end (spindle off). `$30` must match the `S` value (20,000 rpm needs `$30=20000`).
- Drill file (KiCad Excellon): Y is negative of the KiCad Y, absolute origin, metric.

## Conventions

- Python >= 3.12 (gerbonara 1.6 requires it), type hints everywhere, `ruff` for lint and format, `mypy --strict` on
  each service's `src`. One command per service: `scripts/check_service.sh <service>`.
- Tests with `pytest` inside each service (contract tests against `contracts/`); every output format has a reference
  test (pixel comparison, drill list, G-code bounds, `.pm3` round trip). Test data lives next to the service tests and
  must be small. `tests/e2e` compares a running stack with `tests/golden`.
- A change of an API or a JSON format starts in `contracts/` (see `contracts/README.md`). `services/*/src/*/common.py`
  are identical copies on purpose; change all five or none.
- Commits: author Thomas Blankschein using the GitHub noreply address (public repo), messages in English,
  imperative mood, short first line.
- Release: add the version to `CHANGELOG.md` and `services/frontend/site/version.json` (shown in the footer; a test keeps
  both equal), tag `vX.Y.Z`, create the GitHub release from the changelog entry.
- No secrets, no uploaded user data, no generated `.pm3`/`.nc` files in the repository.

## State (2026-10-26)

Milestones 1 to 4 and 8 are done. The system runs as seven containers (`docker-compose.yaml`): Gerber ZIP in, mask PNG,
`.pm3` (native writer) and G-code out; the outputs equal the golden outputs of the old single-package code
(`tests/e2e`). 146 service tests are green (ingest 27, panel 14, exposure 27, mill 47, jobs 31) plus the frontend tests
(`node --test`: geometry, language files).
The outline is milled along the real Edge.Cuts contour (ingest extracts it, mill offsets it); panelizing still uses
each board's box. Photon Workshop opens
the native `.pm3` file and shows the correct mask (confirmed by the maintainer).
The frontend (milestone 5) is done as plain ES modules without a build step: editor with live plate preview, job page,
tool library. Open: manual positioning and rotation of boards, calibration of mirroring and frame offsets on the real
printer, monitoring.
A test instance of the new stack ran on the maintainer's WSL (Ubuntu-26.04, `~/pcbhomefab-new`, project
`pcbhomefab-new`, port 8081) next to the older instance (`~/PCBHomeFab`, ports 80/443); switching over is open.
The reference for the output is the old scripts; tests compare against their results
(`services/mill/tests/data/reference_*`, `services/exposure/tests/data/reference_mask_fbh.png`).

## Repository layout

```
contracts/        OpenAPI files, JSON schemas, error codes, examples: the only thing services share
services/
  gateway/        Caddy: TLS, routing (/ -> frontend, /api -> jobs)
  frontend/       static pages and ES modules (Caddy), tests with `node --test`; no inline styles (CSP default-src 'self')
  jobs/           uploads, job store (SQLite), workflow, worker threads, downloads
  ingest/         Gerber ZIP -> canonical board package (copper.gbr + board.json)
  panel/          packing of boards on the plate
  exposure/       raster, mask, .pm3 writer, printer profiles
  mill/           G-code, tool library (data/tools.toml), mill profiles
tests/            e2e (golden test against a running stack), golden (hashes), data (two real boards)
scripts/          check_service.sh, check_contracts.py, check_boundaries.py, smoke_test.sh, make_golden.py (old code, tag
                  pre-services), make_package_fixtures.py
docs/             architecture (ADR-001), migration, deployment, roadmap
docker-compose.yaml
```

## Tools (mill)
- The tool library is data: `services/mill/src/mill/data/tools.toml`, parsed by `tools.py`. The owner has drills 0.6–1.2 mm in
  0.1 mm steps and end mills 1 mm and 2 mm; holes larger than 1.2 mm are milled. Cutting values in the file are
  starting values, to be tuned on the real mill.

## Positioning marks
- The plate is not always at the same place on the mill and not exactly square. With `marks` (default on, margin of at least
  4.5 mm) the copper layer gets two marks diagonally opposite in the margin (`services/exposure/src/exposure/mask.py`:
  copper square, two diagonal quadrants etched free, free ring around it; the centre is where the two free squares touch, so
  it stays put when too much is etched). `jobs` (`marks.py`) places them so that, after turning the plate over (`flip`), one
  is at the lower left and one at the upper right. `mill` makes the lower left mark X0 Y0 of every program and names the
  other one in the header and in `programs.json`; `jobs` stores the same position as `params.marks.second_mm`.
  With `mark_labels` (default on) `exposure` also writes the G-code coordinates (`X0 Y0`, `X156 Y96`) next to each mark; the
  margin stays copper, so the letters are exposed (etched free), and they are mirrored like the plate is turned (`label_flip`)
  so they read correctly on the finished copper.

## Exposure mask
- The mask has no frame around the display (an earlier version drew an exposed border of 1 mm so that Photon Workshop could
  slice the image; removed on 2026-10-27 at the maintainer's request). The `.pm3` file is not opened in Photon Workshop at
  all: the printer reads it directly (USB stick), so Photon Workshop is only a reference for the file format.
