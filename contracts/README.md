# Contracts

The contracts are the single source of truth for everything two services must agree on (ADR-001 in
[../docs/architecture.md](../docs/architecture.md)). There is no shared code: each service implements its side
itself and proves it with contract tests.

| File | Content |
|---|---|
| `<service>.openapi.yaml` | endpoints of `ingest`, `panel`, `exposure`, `mill` and `jobs` |
| `schemas/*.json` | JSON Schema (2020-12) for bodies and files: board, layout, settings, problem, job |
| `errors.md` | stable error codes |
| `examples/` | real examples (made from the two test boards), used as test fixtures |

## The canonical board package

`application/zip` with exactly two files:

- `copper.gbr`: the bottom copper Gerber file, byte for byte as in the upload.
- `board.json`: size, outline box in Gerber coordinates, the holes and the real board contour (`contour`: outer
  polygon and cutouts from the Edge.Cuts layer), see `schemas/board.schema.json`. `contour` is optional: without it
  (open or unreadable outline) the board is milled as its box.

`ingest` makes it. `exposure` rasterizes `copper.gbr`; `mill` needs only `board.json` and mills along the contour. Services accept only this
layout and these two file names.

## Rules for every service

- `GET /healthz`, paths under `/v1/`, errors as `application/problem+json` with a code from `errors.md`.
- The header `X-Request-Id` is accepted (or made up), returned and written to every log line of the request.
- Lengths are millimetres, angles degrees. Pixels exist only inside `exposure`.
- One request is answered synchronously. It runs in its own process under a time limit (`REQUEST_TIMEOUT_S`) and
  at most `MAX_PARALLEL` requests run at the same time, further ones get `503` with `Retry-After`.

## Changing a contract

1. Change the files here (additive changes first: new optional fields, new endpoints).
2. Update every service that uses the changed part in the same commit; its contract tests fail until it follows.
3. A breaking change gets a new path version (`/v2/...`) next to the old one until all users have moved.
4. Run `python scripts/check_contracts.py` (validates the schemas, the OpenAPI files and the examples).
