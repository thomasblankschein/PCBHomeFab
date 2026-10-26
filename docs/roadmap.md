# Roadmap

| # | Milestone | Result |
|---|---|---|
| 1 | Foundation | Repository, MIT license, project layout, CI, `CLAUDE.md`, docs |
| 2 | Core port | Gerber ZIP ingest, direct rasterizing, panelizing, mask with correct polarity, G-code. Reference tests for each |
| 3 | `.pm3` output | Phase 1 via UVtools in a container with round-trip test; phase 2 native writer |
| 4 | API and jobs | Upload, parameters, job status, download, upload/CPU limits, rate limit |
| 5 | Frontend | Panel editor (counts, spacing, order), previews of mask and tool paths, profile selection, download |
| 6 | Operation | Anonymous sessions with job links, expiry cleanup, Docker Compose with TLS, monitoring |
| 7 | Calibration and quality | Test pattern job for printer and mill alignment (mirroring, frame offset, zero point), user docs |

Out of scope for now: double-sided boards, accounts, other printers and controllers (the profile model leaves
room for them), KiCad `.kicad_pcb` input.
