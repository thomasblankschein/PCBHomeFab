# PCBHomeFab

Turn the Gerber files of a single-sided PCB into everything you need to make it at home:

- **Exposure file** (`.pm3`) for UV exposure of photoresist boards on an Anycubic Photon M3 resin printer
  (used as a UV mask: white pixels expose, black pixels block).
- **Drill and mill G-code** for a GRBL hobby CNC mill (tested target: 3018Pro, 20,000 rpm spindle).
- **Panelizing:** several boards (and copies of a board) are packed onto one blank, so one exposure and one
  milling run makes the whole batch.

The project is meant to run as a small web service that many users can use at the same time, with anonymous
sessions and a link per job. It can also be used as a plain Python library and command line tool.

> **Status:** early development. The foundation is in place; the conversion core is being ported from the
> scripts of the [fbh-monitor](https://github.com/thomasblankschein/fbh-monitor) project. See
> [docs/roadmap.md](docs/roadmap.md).

## How it works

```
Gerber ZIP ──▶ parse (B.Cu, Edge.Cuts, Excellon) ──▶ panelize ──▶ raster mask (40 µm/px)
                                                          │              │
                                                          │              └──▶ .pm3 (Photon M3)
                                                          └──▶ G-code (drill bits, end mill, outline with tabs)
```

Mask polarity: **white = exposed = copper is etched away**, black = copper stays. A copper pour is kept
automatically.

## Development

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest
ruff check .
```

Requires Python 3.11 or newer. See [CLAUDE.md](CLAUDE.md) for the project conventions and
[docs/architecture.md](docs/architecture.md) for the design decisions.

## License

[MIT](LICENSE)
