# Roadmap

| # | Milestone | Result | State |
|---|---|---|---|
| 1 | Foundation | Repository, MIT license, project layout, CI, `CLAUDE.md`, docs | done |
| 2 | Core port | Gerber ZIP ingest, direct rasterizing, panelizing, mask with correct polarity, G-code. Reference tests for each | done, CLI included |
| 3 | `.pm3` output | Native writer (no UVtools) with round-trip test and a cross-check against UVtools | done, file opens in Photon Workshop (confirmed 2026-10-26) |
| 4 | API and jobs | Upload, parameters, job status, download, upload/CPU limits, rate limit | done |
| 5 | Frontend | Panel editor (counts, spacing, order), previews of mask and tool paths, profile selection, download | done 2026-10-26 without a drag-and-drop panel editor: boards, copies, order and spacing with live plate preview, settings, job page with previews and downloads, tool library page. Open: manual positioning, rotation |
| 6 | Operation | Anonymous sessions with job links, expiry cleanup, Docker Compose with TLS, monitoring | Compose with gateway, services, smoke and golden test done and run on the WSL test host; monitoring open |
| 7 | Calibration and quality | Test pattern job for printer and mill alignment (mirroring, frame offset, zero point), user docs | open |
| 8 | Service split | Independent services that talk only through REST, contracts first ([ADR-001](architecture.md), [plan](migration.md)) | done 2026-10-26, no feature changes; outputs equal the golden outputs |

Out of scope for now: double-sided boards, accounts, other printers and controllers (the profile model leaves
room for them), KiCad `.kicad_pcb` input.
