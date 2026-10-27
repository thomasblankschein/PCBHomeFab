# Changelog

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
