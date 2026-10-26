# Migration: from one package to REST services

Implements [ADR-001](architecture.md). Goal: the services `gateway`, `frontend`, `jobs`, `ingest`, `panel`,
`exposure` and `mill`, no shared code, REST only.

**State (2026-10-26): done.** All steps were carried out in one go, each as its own commit, and checked against the
golden outputs of the old code (tag `pre-services`).

## Approach

- **Contracts first, then one service at a time.** Each step extracted one service from the existing code and proved
  it with its own tests (the old tests were ported, the reference tests kept).
- **Behaviour must not change.** Outputs are compared with golden values recorded in step 1
  (`tests/golden/manifest.json`, checked by `tests/e2e/test_golden.py` against a running stack): mask and preview
  pixel-identical, `.pm3` and all G-code programs and the SVG preview byte-identical (line ends normalised, the old
  files were written on Windows).
- No shared code also means: code was copied into the service and then reduced to what the service needs.

## Steps

| # | Step | Result | State |
|---|---|---|---|
| 1 | Baseline | `scripts/make_golden.py` ran the old runner for the two real test boards; hashes in `tests/golden/`. Tag `pre-services`. | done |
| 2 | Contracts | `contracts/`: OpenAPI per service, JSON schemas (board, layout, settings, programs, job, problem), `errors.md`, examples; `scripts/check_contracts.py`. | done |
| 3 | Scaffold | `services/<name>/` with `common.py` (problem+json, request ids, health, per-request process with time limit and parallel limit), `pyproject.toml`, `Dockerfile`, contract tests. Per-service CI with path filters, `scripts/check_service.sh`. | done |
| 4 | `panel` (pilot) | Packing code and tests; `POST /v1/layouts`. Example request gives the example layout of the contract. | done |
| 5 | `ingest` | Safe unzip, layer detection and the package builder; `POST /v1/packages`. Hostile ZIPs (not a ZIP, too many files, zip bomb, path names) are refused with the right code. | done |
| 6 | `mill` | G-code, tool library, mill profiles; `GET /v1/profiles`, `GET /v1/tools`, `POST /v1/programs`. G-code of the old reference scripts still matches. | done |
| 7 | `exposure` | Rasterizer, mask, `.pm3` writer, printer profiles; `GET /v1/profiles`, `POST /v1/masks`. Polarity, border, reference mask and Photon Workshop machine table tests kept. | done |
| 8 | `jobs` | Store, workflow and API over HTTP calls to the other services, worker threads, rate limit, expiry. Tested with fake downstream services built from the contracts. | done |
| 9 | Gateway, frontend, cleanup | `gateway` (routing, TLS), `frontend` (static pages), `docker-compose.yaml` with an internal network; deleted `src/pcbhomefab`, the CLI, the root `pyproject.toml`, the old tests and the old compose file. `scripts/check_boundaries.py`. | done |
| 10 | Roll out | Started the new compose project next to the old test instance on WSL (other project name and ports), ran `scripts/smoke_test.sh` and `tests/e2e`: 9 of 9 golden checks pass through the gateway. The old test instance was not touched. | done, switching the old instance over is the maintainer's call |

## Deviations from the plan

- No `PCBHOMEFAB_<SERVICE>_URL` switch between old library and new service. The steps were done in one sequence, so
  an intermediate state with both paths was not needed. The tag `pre-services` is the way back.
- The canonical package carries only `copper.gbr` and `board.json` (see ADR-001, contracts). `outline.gbr` and
  `drills.drl` were dropped because nothing downstream needs them.
- `exposure` and `mill` answer with a ZIP of files instead of one file per request (`outputs` selects the files for
  `exposure`), so the copper is rasterized once for mask, preview and `.pm3`.
- `jobs` calls `ingest` while the upload is received (a bad ZIP is refused at once) instead of in the worker.
- The CLI `pcbhomefab tools --export` is gone; `docs/deployment.md` shows how to copy the default tool library.
- The `--template` option for `.pm3` files is not reachable through the API; the code in `exposure/pm3.py` and its
  tests remain.

## Checks that enforce the principle (run in CI, `ci-architecture.yml`)

- `scripts/check_boundaries.py`: no file under `services/<a>/` imports or refers to another service; no Dockerfile
  copies from outside its folder; only the gateway publishes ports and is on the outside network; no volume is used
  by two services; no bind mounts; the network `internal` is internal.
- Contract tests per service against `contracts/`; `scripts/check_contracts.py` validates schemas, OpenAPI files
  and examples.
- `ci-stack.yml` builds all images, starts the compose project, runs the smoke test and the golden test.

## Risks that remain

| Risk | Mitigation |
|---|---|
| Large payloads between services (`.pm3` is about 300 KB, PNG 40 KB, packages 5 to 15 KB) | measure with bigger panels; limits are in the contract and the services |
| Synchronous call too slow for big panels | per-request time limit (exposure 120 s); if it is hit, revisit asynchronous calls in a new ADR |
| Duplicated code drifts apart | accepted by ADR-001; `common.py` copies are identical today (check by hand or add a CI step if it becomes a problem) |
| Many invalid uploads cost `ingest` time without creating jobs | `ingest` limits parallel requests; add a rate limit at the gateway if abused |

## Open points for later

- Authentication between services (the internal network is enough for now; a shared token can be added to the
  contract).
- Whether `jobs` should be split into storage and workflow if it grows.
- A real frontend (milestone 5): the current pages only upload a ZIP and show the job.
