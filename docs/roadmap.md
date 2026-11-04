# Roadmap

| # | Milestone | Result | State |
|---|---|---|---|
| 1 | Foundation | Repository, MIT license, project layout, CI, `CLAUDE.md`, docs | done |
| 2 | Core port | Gerber ZIP ingest, direct rasterizing, panelizing, mask with correct polarity, G-code. Reference tests for each | done, CLI included |
| 3 | `.pm3` output | Native writer (no UVtools) with round-trip test and a cross-check against UVtools | done, file opens in Photon Workshop (confirmed 2026-10-26) |
| 4 | API and jobs | Upload, parameters, job status, download, upload/CPU limits, rate limit | done |
| 5 | Frontend | Panel editor (counts, spacing, order), previews of mask and tool paths, profile selection, download | done 2026-10-26 without a drag-and-drop panel editor: boards, copies, order and spacing with live plate preview, settings, job page with previews and downloads, tool library page. Open: manual positioning, rotation. Languages English and German (switchable, JSON language files) added 2026-10-27 |
| 6 | Operation | Accounts (Keycloak, 0.24.0, before: anonymous job links with expiry), Docker Compose with TLS, monitoring | Compose with gateway, services, Keycloak, smoke and golden test done; runs on an Alpine VM in the homelab (VM 974, since 0.25) and on the WSL test host; hardened after a security review (0.26.0); monitoring open |
| 7 | Calibration and quality | Test pattern job for printer and mill alignment (mirroring, frame offset, zero point), user docs | in part: user manual (0.23.2), positioning marks and the rotation of the panel on the mill (0.25.0), exposure series to find the exposure time (0.27.0); a test pattern for the frame offsets and the zero point is open |
| 8 | Service split | Independent services that talk only through REST, contracts first ([ADR-001](architecture.md), [plan](migration.md)) | done 2026-10-26, no feature changes; outputs equal the golden outputs |

Out of scope for now: double-sided boards, other printers and controllers (the profile model leaves room for them).
