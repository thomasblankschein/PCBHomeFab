# Changelog

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
