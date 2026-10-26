# Roadmap

| # | Milestone | Result | State |
|---|---|---|---|
| 1 | Foundation | Repository, MIT license, project layout, CI, `CLAUDE.md`, docs | done |
| 2 | Core port | Gerber ZIP ingest, direct rasterizing, panelizing, mask with correct polarity, G-code. Reference tests for each | done, CLI included |
| 3 | `.pm3` output | Native writer (no UVtools) with round-trip test and a cross-check against UVtools | done, still to confirm with Photon Workshop |
| 4 | API and jobs | Upload, parameters, job status, download, upload/CPU limits, rate limit | open |
| 5 | Frontend | Panel editor (counts, spacing, order), previews of mask and tool paths, profile selection, download | open |
| 6 | Operation | Anonymous sessions with job links, expiry cleanup, Docker Compose with TLS, monitoring | open |
| 7 | Calibration and quality | Test pattern job for printer and mill alignment (mirroring, frame offset, zero point), user docs | open |

Out of scope for now: double-sided boards, accounts, other printers and controllers (the profile model leaves
room for them), KiCad `.kicad_pcb` input.
