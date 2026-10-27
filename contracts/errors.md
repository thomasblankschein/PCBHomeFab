# Error codes

Every error response has the media type `application/problem+json` and the body described in
`schemas/problem.schema.json`. `code` is stable, `detail` is written for users. A service uses only the codes of
its own prefix, plus `common.*`.

| Code | Status | Meaning |
|---|---|---|
| `common.busy` | 503 | too many parallel requests, retry after `Retry-After` seconds |
| `common.timeout` | 503 | the request took longer than the time limit and was stopped |
| `common.invalid_request` | 422 | the request does not match the contract (missing part, bad JSON, wrong value) |
| `common.not_found` | 404 | no such path |
| `common.too_large` | 413 | a request part is larger than the limit of the service |
| `common.internal` | 500 | unexpected error, details only in the log (look for the `request_id`) |
| `ingest.invalid_zip` | 422 | the upload is not a ZIP file |
| `ingest.too_many_files` | 422 | the ZIP has more files than allowed |
| `ingest.too_large_unpacked` | 422 | the ZIP is too large when unpacked |
| `ingest.unreadable_gerber` | 422 | the Gerber files could not be read |
| `ingest.no_copper` | 422 | no bottom copper layer found |
| `ingest.no_outline` | 422 | no board outline layer found |
| `ingest.empty_outline` | 422 | the board outline layer is empty |
| `ingest.slots_unsupported` | 422 | routed slots in the drill files are not supported |
| `panel.board_too_wide` | 422 | a board is wider than the plate |
| `panel.does_not_fit` | 422 | the boards do not fit on the plate |
| `exposure.unknown_printer` | 422 | no printer profile with this id |
| `exposure.invalid_package` | 422 | a board package is not a canonical package |
| `exposure.unknown_board` | 422 | the layout refers to a board id without package |
| `exposure.unreadable_copper` | 422 | `copper.gbr` could not be read or drawn |
| `exposure.plate_too_large` | 422 | the plate, with the calibration offsets, does not fit on the display of the printer |
| `mill.unknown_mill` | 422 | no mill profile with this id |
| `mill.invalid_package` | 422 | a board package is not a canonical package |
| `mill.unknown_board` | 422 | the layout refers to a board id without package |
| `mill.no_drill` | 422 | a hole has no matching drill and cannot be milled |
| `mill.no_endmill` | 422 | the end mill for the outline is not in the tool library |
| `mill.spindle_too_fast` | 422 | a tool asks for more rpm than the machine allows |
| `mill.invalid_tools` | 422 | the tool library file is invalid |
| `mill.cutout_too_small` | 422 | a cutout in the board outline is too small for the end mill |
| `mill.invalid_marks` | 422 | the two positioning marks do not stand diagonally opposite |
| `jobs.not_found` | 404 | no such job (or it expired) |
| `jobs.rate_limited` | 429 | too many jobs from this client |
| `jobs.queue_full` | 503 | the queue is full |
| `jobs.upstream_unavailable` | 503 | a service that the job needs cannot be reached |
| `jobs.invalid_upload` | 422 | bad upload (count of files, counts, no output selected) |
| `jobs.invalid_plate` | 422 | the plate size is missing or not in the list of plate sizes |
| `jobs.invalid_marks` | 422 | positioning marks asked for, but the margin is too small for them or the plate is too small |
| `jobs.upload_too_large` | 413 | a file is larger than the limit |

`jobs` stores the `detail` of a failing downstream call as the error text of the job when the status was 4xx.
Everything else (5xx, timeouts, unreachable service) becomes the fixed text "Internal error while creating the
files." and is logged.
