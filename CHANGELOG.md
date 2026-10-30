# Changelog

## 0.25.0 - 2026-10-30

- New on the job page: "Rotation of the panel". After X0 Y0 is set at the lower left mark, the X and Y of the upper right mark
  read in the control are typed in (they start with the place the mark should have) and the rotation for the control
  (`drehen 0,0876`) is calculated, together with the deviation of the distance as a check. The manual describes the procedure.

## 0.24.2 - 2026-10-30

- Docs: the README has a section "Configure Keycloak" (settings in the `.env`, creating accounts, changing passwords, optional features).

## 0.24.1 - 2026-10-30

- Fix: `scripts/create_user.sh` made accounts without a first and last name, which Keycloak counts as not fully set up
  ("Account is not fully set up", no login possible). The script now sets both (the username and a dash unless given), and the
  deployment guide says to fill them in when creating an account in the console.

## 0.24.0 - 2026-10-30

- **Breaking: accounts instead of anonymous jobs** (ADR-002). The login is Keycloak (OpenID Connect, realm `pcbhomefab`),
  published by the gateway under `/auth`; new containers `keycloak` and `keycloak-db` (PostgreSQL). Every call of the API
  except `/healthz` needs the access token of an account (`Authorization: Bearer`, otherwise `401 jobs.unauthorized`).
- Jobs belong to the account that made them and are **kept until the owner deletes them**: no expiry any more
  (`expires` is `null`). New: `GET /v1/jobs` (list, newest first, `limit` and `offset`), `DELETE /v1/jobs/{id}`,
  `GET /v1/me`. A job of another account gives 404. Limits count per account: jobs per hour, previews per hour and the new
  limit of jobs kept (`PCBHOMEFAB_MAX_JOBS_PER_USER`, default 200, error `jobs.quota_exceeded`).
- User interface: login page of Keycloak (English and German), name and "Log out" in the header, new page "My jobs"
  (`/jobs`) with open and delete; the job page no longer talks about expiry or keeping the link. Files, pictures, the PDF and the
  ZIP are fetched with the token and shown or saved from blobs.
- Accounts are created by the administrator (Keycloak console or `scripts/create_user.sh`); there is no self-registration (it
  would need an SMTP server). `scripts/smoke_test.sh` and the e2e tests need an account (`PCBHOMEFAB_USER`,
  `PCBHOMEFAB_PASSWORD`), the CI creates one.
- Upgrading: set `PCBHOMEFAB_PUBLIC_URL`, `KEYCLOAK_ADMIN_PASSWORD` and `KEYCLOAK_DB_PASSWORD` in the `.env` (the compose file
  stops without them), create the accounts, see `docs/deployment.md`. `PCBHOMEFAB_IP_SALT` and `PCBHOMEFAB_JOB_TTL_HOURS` are gone.
  Jobs of the anonymous time have no owner: nobody can open them, they expire after their seven days and are deleted.
- `jobs` depends on `pyjwt[crypto]`. Documentation: ADR-002 in `docs/architecture.md`, a chapter about the login in the manual.

## 0.23.2 - 2026-10-30

- Documentation: the README describes the installation from git and the features; new manual `docs/manual.md` (from the KiCad
  file to the finished board, all settings, mill procedure, maintaining tool and machine data, REST API, troubleshooting).

## 0.23.1 - 2026-10-29

- The ZIP archive with all files now also holds the job description as `auftragsbeschreibung.pdf` or `job-description.pdf`
  (language of the page, `lang` parameter of `/archive`).

## 0.23.0 - 2026-10-29

- New: job description as a PDF (`GET /v1/jobs/{id}/report.pdf?lang=de|en`, link on the job page). It holds the header data of
  the job, the exposure mask, the drill and mill view with a legend of the hole sizes, the tools with the program (.nc file)
  of each, and the production time for drilling and milling (without exposure).
- `mill` estimates the run time of every program from its G-code and reports it as `estimated_s` in `programs.json`; `jobs`
  now keeps `programs.json` in the job files. Jobs made before this release have no times, their PDF omits the tool table.
- `jobs` depends on `reportlab`.

## 0.22.9 - 2026-10-29

- Fix: the holes of the 3D simulation started below the copper level when the drill works in steps (pecking). Every hole now
  starts at the surface and goes as deep as the tool got there.

## 0.22.8 - 2026-10-29

- Fix: the holes of the 3D simulation looked like flat rectangles from above since 0.22.7. Every hole (drilling and plunging) is
  now drawn as a cylinder: round opening from above, flat top edge from the side, an ellipse in between. The paths of the
  mill keep their round ends.

## 0.22.7 - 2026-10-29

- The removed material of holes (drilling and plunging) is drawn with flat ends in the 3D simulation, no longer with half
  circles; the paths of the mill keep their round ends, the shape of the tool.

## 0.22.6 - 2026-10-29

- Fix: the copper in the 3D simulation was cut by wedge shaped gaps when the view was steep or zoomed in (the picture was drawn
  in tiles that did not fit together in perspective). It is now drawn as a mesh of 2880 small triangles that share their edges.
- The copper picture has 20 px/mm again (as tried in 0.22.3, taken back in 0.22.5) and smooth edges, so tracks and pads do not
  look pixelated when zoomed in.

## 0.22.5 - 2026-10-29

- Back to the state of 0.22.2: the finer copper picture of 0.22.3 and the tile changes of 0.22.4 are taken out again, because
  the copper of the 3D simulation showed gaps for the maintainer. The copper picture has 10 px/mm again.

## 0.22.4 - 2026-10-29

- Fix: the copper in the 3D simulation could show wedge shaped gaps between the tiles it is drawn from when zoomed in
  (since 0.22.3). The tiles are smaller (48 x 30), overlap by 0.15 mm whatever the resolution, and the extra image smoothing
  of 0.22.3 is removed again.

## 0.22.3 - 2026-10-29

- The copper picture of the 3D simulation (`copper.png`) has 20 px/mm instead of 10 px/mm and smooth edges (drawn three times
  finer and scaled down), so tracks and pads no longer look pixelated when zoomed in.

## 0.22.2 - 2026-10-29

- Fix: the panel was drawn very dark in the 3D simulation since 0.22.0 (the renamed colour variable was not found).

## 0.22.1 - 2026-10-29

- The time in the 3D simulation shows hours (h:mm:ss) from 60 minutes on, below that it stays m:ss.

## 0.22.0 - 2026-10-29

- The blank is called "panel" in the code as well (it was "plate"): API field and form field `panel`, endpoint `/api/v1/panels`,
  error code `jobs.invalid_panel`, `panels.toml` with `[[panel]]` entries, `PCBHOMEFAB_PANELS_FILE`, `panel` and `panel_origin_mm`
  in the job and layout JSON, and the comments in the G-code files ("panel surface"). The old names are not accepted any more.
- Upgrading: an own list of panel sizes needs `[[panel]]` instead of `[[plate]]` and the new environment variable. Jobs created
  before the update still open, but their panel size and positions of the marks may be missing; create them again. The
  selected panel size is not remembered once in the editor.

## 0.21.1 - 2026-10-29

- Texts: the blank that carries the boards is called "Nutzen" (German) and "panel" (English) instead of "Platte" and "plate" in
  the pages and in the error messages of the services. Code, API fields and G-code comments are unchanged.
- The introduction of the editor is worded more formally and no longer names the `.pm3` file.

## 0.21.0 - 2026-10-29

- The plate views of the editor (design view and underside) zoom with the mouse wheel (towards the mouse position, up to 40
  times), move with the held middle mouse button and show everything again on a double click.

## 0.20.0 - 2026-10-29

- The plate preview of the editor has a second view, the underside: the copper side seen from below (mirrored left to
  right), with the copper tracks, pads and pours, the boards and the holes. A button above the plate switches between the
  design view and the underside. `ingest` writes the simple copper geometry as `copper` into `board.json` (Gerber ZIP and
  KiCad file); `exposure` and `mill` ignore it.
- Fix: the hint above the plate said the copper side is up; the copper side (B.Cu) is at the bottom in the KiCad view.

## 0.19.1 - 2026-10-29

- Fix: choosing a drill for an unusual hole size took effect only on the second try. The form redrew the rows on the
  `input` event before the select box had stored its choice; the choice is now stored on `input`.

## 0.19.0 - 2026-10-29

- Defaults taken over from the maintainer's proven FlatCAM programs: end mill feed 70 mm/min, plunge feed 50 mm/min for
  end mills and drills, cutting and drilling depth 1.75 mm for a 1.6 mm board (overshoot below the board 0.15 mm),
  tool change height Z 30.
- Default material thickness is 1.6 mm (was 1.5 mm).
- Tool library: drills from 0.6 to 1.5 mm in 0.1 mm steps (1.3, 1.4 and 1.5 mm added), end mill 3 mm added; the 2 mm end mill
  uses the same cutting values as the 1 mm end mill.

## 0.18.1 - 2026-10-29

- Fix: a mounting hole that is also drawn as a circle on Edge.Cuts was milled twice (once as a hole, once as a cutout
  of the outline). A hole whose centre and diameter agree with a cutout of the outline (0.15 mm) is now skipped.

## 0.18.0 - 2026-10-29

- Hole sizes without a drill of their own in the tool library can be assigned to an existing drill. The editor shows a select
  box for every such size (default: the next larger drill); the choice is sent as `drill_map` (`{"0.95": 1.0}`), stored in
  the job (`params.drill_map`) and shown on the job page. `mill` drills these holes with the chosen drill, together with its
  own holes, and names them in the program title. Without a mapping the board is still refused (`mill.no_drill`); an unknown
  drill gives `mill.invalid_drill_map`, a bad `drill_map` gives `jobs.invalid_drill_map`.
- Tool library: the 0.95 mm drill is removed again.

## 0.17.1 - 2026-10-29

- Fix: a select box with a long text ("All programs one after the other" in the 3D simulation) no longer reaches over the
  neighbouring controls, such as the "Exaggerated depth" slider.

## 0.17.0 - 2026-10-29

- The positioning mark is now two quarter circles of copper that face each other diagonally (inside a free disc, 2.4 mm
  across plus a 0.5 mm ring) instead of a square with two free quadrants. The centre is where the tips touch.
- The mark that is X0 Y0 of the G-code stands as close to the boards as possible: diagonally outside the corner of the area
  of all placed boards (2 mm in X and Y) instead of in the corner of the plate. The other mark stays in the opposite corner.
  The marks are therefore computed when the job runs, after panelizing; `params.marks` (positions, `second_mm`,
  `plate_origin_mm`) is updated then, and the coordinates in the program headers and on the labels follow.

## 0.16.0 - 2026-10-27

- Fix: a file that holds several boards, each with its own outline in Edge.Cuts, is milled along every outline. Before, such
  an outline was not recognised and only the outer box of the whole file was milled. `board.json` lists the largest board
  in `contour` and the others in the new `contour.others`; the size and the outline box cover all of them. The plate
  preview draws all outlines. The file is still placed on the plate as one block.

## 0.15.1 - 2026-10-27

- Tool library: drill 0.95 mm added.

## 0.15.0 - 2026-10-27

- A KiCad PCB file (`.kicad_pcb`) can be uploaded instead of a Gerber ZIP, no Gerber export needed. `ingest` recognises the
  file by its content and reads the bottom copper (tracks, arcs, vias, pads, filled zones, graphics and stroke font text on
  B.Cu), the outline (Edge.Cuts, lines, arcs, circles, rectangles, polygons) and the holes. The rest of the pipeline is
  unchanged. Zones must be filled in the file (a file with an unfilled B.Cu zone is refused: `ingest.zone_not_filled`).
  Trapezoid pads and bezier curves are refused (`ingest.unsupported_kicad`), chamfered pad corners are drawn square.
  Checked against the Gerber exports of the two test boards: same size, outline, holes and G-code, mask differs in a few
  edge pixels. New error codes: `ingest.invalid_kicad`, `ingest.unsupported_kicad`, `ingest.zone_not_filled`.
## 0.14.1 - 2026-10-27

- Fix: the user interface asks for every page and script whether it is still current (`Cache-Control: no-cache`). A browser
  that had cached an older script could mix it with a new one and show an empty job page after an update.
- The mask caption on the job page no longer says "mirrored".

## 0.14.0 - 2026-10-27

- The job page has a download of all result files in one ZIP archive (`GET /api/v1/jobs/{id}/archive`), with the folders
  `exposure/` (`.pm3`, mask, preview) and `drill-mill/` (G-code programs and the milling preview).

## 0.13.0 - 2026-10-27

- The text next to the positioning marks uses DejaVu Sans Mono Bold (equal width, thick strokes, dotted zero; bundled in
  `exposure` with its licence) and is 2 mm high, so it survives etching better.

## 0.12.0 - 2026-10-27

- Positioning marks get their G-code coordinates as text next to them on the copper layer (`X0 Y0` at the mark that is the
  origin, e.g. `X156 Y96` at the other one). The text is mirrored like the plate is turned over for milling, so it reads
  correctly on the finished copper. Switchable with `mark_labels` (default on, only with `marks`); marks in the shared
  mark format have the new optional fields `label`, `label_flip` and `label_side`.

## 0.11.0 - 2026-10-27

- **Breaking:** the exposure mask is no longer mirrored by default (`PrinterProfile.mirror_x` is now `false`). The Gerber of
  the back copper layer is a top view, and the plate lies copper side down on the display, so the unmirrored mask gives
  copper that reads correctly when seen from the copper side. Text in the B.Cu layer now appears mirrored on the mask. The
  plate now sits at `frame_left_mm` from the left edge of the display. `mask.png`, `mask_preview.png` and `exposure.pm3`
  change, the G-code does not. Set `mirror_x` in the printer settings to get the old orientation.

## 0.10.0 - 2026-10-27

- Positioning marks: the copper layer gets two marks diagonally opposite in the margin (a copper square with two diagonal
  quadrants etched free; the centre stays put when too much is etched). The mark at the lower left after turning the plate
  over is X0 Y0 of all G-code programs; the other one is named in the program headers, in `programs.json` and on the job page
  (upper right: X 156, Y 96 mm on a 160 x 100 mm plate). Switchable with `marks` (default on); needs a margin of at least
  4.5 mm (the editor default is now 5 mm). Marks are also in the copper picture of the 3D view.
- **Breaking:** `POST /api/v1/jobs` with the default `marks` refuses a margin below 4.5 mm (`jobs.invalid_marks`); send `marks=false`
  for the old behaviour.

## 0.9.0 - 2026-10-27

- 3D simulation: the copper of the boards is shown faintly on the plate and can be switched off ("Show copper"). `exposure`
  has a new output `copper` (`copper.png`: the copper of the plate in top view, RGBA, 10 px/mm), `jobs` stores it with every
  job (also without the exposure output; a failure there does not fail the job).

## 0.8.0 - 2026-10-27

- Tool change in the G-code: every drill and mill program starts at the tool change position (Z, then X0 Y0, spindle off) and
  waits with `M0`, so the tool can be inserted and Z0 set before the program is resumed; at the end it parks at the same
  position. The height is the new parameter `tool_change_z_mm` of the mill profile (50 mm), shown on the Machines page.

## 0.7.0 - 2026-10-27

- The exposure mask no longer has an exposed frame around the display; `border_mm` is gone from the printer profile and from
  `GET /v1/profiles` of `exposure` (the golden outputs of the mask and the `.pm3` file changed with it).
- The job page tells to copy the `.pm3` file to the printer (USB stick); it is not opened in Photon Workshop.

## 0.6.0 - 2026-10-27

- Plate sizes: a job is made for a plate size chosen from a list (160 x 100, 75 x 100 and 100 x 75 mm built in). The list is
  data of the `jobs` service (`plates.toml`, own file with `PCBHOMEFAB_PLATES_FILE`), `GET /api/v1/plates` shows it.
- **Breaking:** `POST /api/v1/jobs` and `POST /api/v1/layouts` need `plate` (the id of a plate size).
- The editor has a plate size field, the job page and the 3D simulation use the size of the job, the Machines page lists the
  sizes. `exposure` refuses a plate that does not fit on the display (`exposure.plate_too_large`). The mill profile gives
  `default_thickness_mm` instead of a plate size.

## 0.5.0 - 2026-10-27

- New page "Machines": the parameters of the printers and mills (display, resolution, calibration, lift, spindle, safe height,
  tabs, plate and so on). `GET /v1/profiles` of `exposure` and `mill` return the full parameter set (contracts extended).

## 0.4.0 - 2026-10-27

- 3D simulation: drag with the middle mouse button to move the view; the two view buttons bring the plate back to the middle.

## 0.3.0 - 2026-10-27

- 3D simulation of the drill and mill paths on the job page: turn and zoom, play the programs with the tool moving along the
  paths, show one program or all, estimated machine time. Plain canvas, no library.

## 0.2.0 - 2026-10-27

- The frontend shows the version of the release in the footer (`site/version.json`, kept equal to this file by a test).

## 0.1.0 - 2026-10-27

First release.

- Gerber ZIP of a single-sided board in; exposure mask, `.pm3` file for the Anycubic Photon M3 and GRBL G-code
  (drilling, milling along the real Edge.Cuts contour with tabs and cutouts) out.
- Panelizing of several boards and copies onto a 160 x 100 mm blank.
- Independent services behind one gateway (`gateway`, `frontend`, `jobs`, `ingest`, `panel`, `exposure`, `mill`)
  that talk only through REST; contracts in `contracts/` (ADR-001, see `docs/architecture.md`).
- Web interface without a build step: editor with live plate preview, job page with previews and downloads, tool
  library. English and German with JSON language files in `services/frontend/site/locales/`.
- Anonymous jobs with a link per job, upload and rate limits, expiry after seven days.
- Docker Compose stack, golden-output end-to-end test, CI per service.

Not yet done: manual positioning and rotation of boards, calibration on the real printer and mill, monitoring.
