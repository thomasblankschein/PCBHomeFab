# Architecture

## Layers

```
frontend (SPA)  ──HTTP──▶  api (FastAPI)  ──queue──▶  worker  ──▶  pcbhomefab (core library)
                              │                          │
                              └────── storage (files with expiry, job metadata) ──┘
```

- **Core library `pcbhomefab`:** pure Python, no web dependencies. Everything that matters for the output lives here
  and is unit-testable without a server.
- **API:** accepts uploads, validates them, creates jobs, reports status, serves results and previews.
- **Worker:** runs the CPU-heavy steps (rasterizing, packing, `.pm3` writing). Each job runs in its own process with a
  time limit, so a broken or slow job cannot block or crash the service. Workers hold no state, any number may run, as
  threads inside the web process or as separate `pcbhomefab worker` processes.
- **Storage and queue:** the job database (SQLite, WAL mode) is the queue: a worker claims the oldest queued job with an
  atomic update. Files live in one folder per job (`input/`, `output/`) and are deleted with the job after the expiry
  time. A broker such as Redis is only needed when workers run on several machines; the store is a small class that can
  be replaced then.

## Anonymous sessions

- Creating a job returns a random, unguessable job id; the link `/jobs/<id>` is the only credential.
- Jobs and files expire after a fixed time (default 7 days).
- Limits per job: upload size, number of files, unpacked size, CPU time, memory. Rate limit per IP.

## Core pipeline

1. **Ingest:** unpack the ZIP safely (no path traversal, size and file-count limits), detect the layers by file
   function (`TF.FileFunction` attributes or name patterns): bottom copper, profile, drill (PTH/NPTH).
2. **Rasterize:** draw the bottom copper Gerber directly to a bitmap (40 µm per pixel). Dark = copper.
3. **Panelize:** pack boards (with counts) onto the blank in rows from the bottom left.
4. **Mask:** white = no copper = exposed. Mirror in X. Output 1-bit PNG at display resolution.
5. **`.pm3`:** build the file for the selected printer profile (see below).
6. **G-code:** group holes by diameter, one program per tool, outline with tabs, optional preview.

## Profiles (data, not code)

- **Printer profile:** display resolution and size, frame offsets (calibration), mirror mode, machine name and
  machine table template, default exposure.
- **Mill profile:** controller dialect (GRBL), highest spindle speed, outline end mill, safe height, tab size,
  flip mode, work area.
- **Tool library** (`src/pcbhomefab/data/tools.toml`, `tools.py`): every drill bit and end mill with its cutting data
  (spindle rpm, feeds, peck / step down). TOML was chosen because it is readable, diffable, needs no extra
  dependency (`tomllib`) and fits a git repository or a Docker volume. `[defaults.drill]` and `[defaults.endmill]`
  hold shared values, each `[[tool]]` overrides them; `enabled = false` hides a tool. A user file
  (`PCBHOMEFAB_TOOLS_FILE`, `pcbhomefab mill --tools`) replaces the built-in library as a whole.
  Hole rules: a hole gets the drill of the same diameter (tolerance 0.02 mm); holes larger than the largest drill
  are milled with the outline end mill (or a smaller one if it does not fit); anything in between is an error that
  lists the available drills. One G-code program per tool, spindle speed per tool, limited by the machine.

## `.pm3` writer

Native, in `pcbhomefab/pm3.py` (format version 516). It follows the layout of the open source UVtools implementation
and is checked three ways: reading the file back with its own reader (pixel-exact), reading it with UVtools
(optional test) and comparing the MACHINE table with a file written by Photon Workshop. No UVtools, .NET or GPL
code is needed at run time, so the worker container stays small.

## Deployment

Docker Compose: reverse proxy with TLS, API, worker, Redis, storage volume. Runs on a VM or LXC with Docker in
the Proxmox homelab first; the same compose file must work unchanged on an internet-facing root server
(only the proxy and limits change).
