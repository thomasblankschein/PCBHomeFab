# CLAUDE.md – PCBHomeFab project context

This file keeps the state and decisions of the project so a new session can continue without the original
chat history. **Language of the project: English** (code, comments, docs, commit messages, UI text).
Conversations with the maintainer are in German.

## Goal

A small web service (and Python library / CLI) that turns the Gerber files of a **single-sided PCB** into
home-fabrication files:

1. UV exposure file `.pm3` for an Anycubic Photon M3 resin printer used as a UV mask for photoresist boards.
2. GRBL G-code for drilling and milling the outline on a hobby CNC (3018Pro, 20,000 rpm spindle).
3. Panelizing of several boards onto one 160 x 100 mm blank, shared by both outputs.

Origin: the scripts `kicad_zu_photon.py` and `kicad_zu_gcode.py` in
[fbh-monitor](https://github.com/thomasblankschein/fbh-monitor) (`tools/platinenbelichtung`, `tools/fraesen`).
They are the reference for behaviour until the port is finished.

## Decisions (made with the maintainer)

- Name **PCBHomeFab**, public repository, **MIT** license, Python package `pcbhomefab`.
- Input: **Gerber ZIP** first (B.Cu, Edge.Cuts, Excellon drill files). KiCad `.kicad_pcb` input is a later option.
- Users: **anonymous sessions**, every job has a link. No accounts for now.
- Hosting: first on the maintainer's Proxmox homelab (Docker), later possibly a root server on the internet.
  Everything must therefore be stateless per request, limits on uploads/CPU time from day one.
- Pure-Python core library `pcbhomefab` without web dependencies; web API and frontend sit on top.
- Planned stack: FastAPI, asynchronous jobs in a queue (Redis + a worker), small SPA frontend, Docker Compose.

## Domain knowledge to keep

- Photon M3: display 4096 x 2560 px, 163.84 x 102.4 mm, **40 µm per pixel**. The plate (160 x 100 mm) sits in a
  frame 1.8 mm from the left and 0.8 mm from the bottom of the display. These offsets are assumptions taken from the
  maintainer's notes and must be **calibration values per profile**, not hard-coded.
- Mask polarity for positive photoresist: **white = exposed = copper is etched away**, black = copper stays.
  A copper pour in the Gerber must stay black. (An early version inverted this by mistake, keep a test for it.)
- The image is mirrored in X before it goes to the printer (copper side faces the LCD).
- `.pm3` (Anycubic format, version 516): Photon Workshop rejects files whose machine table names an unknown printer
  ("Unknown"). The MACHINE table (156 bytes) of a file Photon Workshop wrote for the M3 is stored in the profile
  values (`PHOTON_M3`) and in `tests/data/photon_m3_machine_table.bin`; the name is `Anycubic Photon M3`. The writer is
  native (`pm3.py`). Layer images are run length encoded: black/white runs as two bytes (`nibble << 12 | length`,
  at most 4095). UVtools 7.1 cannot convert a single image and cannot edit a finished `.pm3`, which is why the
  first version of the writer used a long detour; it is no longer needed.
- GRBL: no canned drill cycles, write explicit moves. `$30` must match the `S` value (20,000 rpm needs `$30=20000`).
- Drill file (KiCad Excellon): Y is negative of the KiCad Y, absolute origin, metric.

## Conventions

- Python >= 3.12 (gerbonara 1.6 requires it), type hints everywhere, `ruff` for lint/format rules, `mypy --strict` on `src`.
- Tests with `pytest`; every output format gets a reference test (pixel comparison, drill list, G-code bounds,
  `.pm3` round trip). Test data lives in `tests/data` and must be small.
- Commits: author Thomas Blankschein using the GitHub noreply address (public repo), messages in English,
  imperative mood, short first line.
- No secrets, no uploaded user data, no generated `.pm3`/`.nc` files in the repository.

## State (2026-10-26)

Milestones 1 to 3 are done: `pcbhomefab exposure|mill` produces the mask PNG, the `.pm3` (native writer, 29 tests
green) and G-code. Still to confirm: that Photon Workshop opens the native file. Open: API, frontend, deployment.
The reference for the output is the old scripts; tests compare against their results (`tests/data/reference_*`).

## Repository layout

```
src/pcbhomefab/   board (Gerber ZIP ingest), raster, panel, mask, pm3, gcode, profiles, cli
tests/            pytest tests and small test data (Gerber ZIPs of two real boards)
docs/             architecture and roadmap
```

`api/` (FastAPI), `web/` (frontend) and deployment files are added in later milestones, see `docs/roadmap.md`.
