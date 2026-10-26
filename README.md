# PCBHomeFab

Turn the Gerber files of a single-sided PCB into everything you need to make it at home:

- **Exposure file** (`.pm3`) for UV exposure of photoresist boards on an Anycubic Photon M3 resin printer
  (used as a UV mask: white pixels expose, black pixels block).
- **Drill and mill G-code** for a GRBL hobby CNC mill (tested target: 3018Pro, 20,000 rpm spindle).
- **Panelizing:** several boards (and copies of a board) are packed onto one blank, so one exposure and one
  milling run makes the whole batch.

The project is meant to run as a small web service that many users can use at the same time, with anonymous
sessions and a link per job. It can also be used as a plain Python library and command line tool.

> **Status:** early development. The conversion core (Gerber ZIP, panelizing, exposure mask, `.pm3`, G-code) and a
> command line tool work; the web service is next. See [docs/roadmap.md](docs/roadmap.md).

## How it works

```
Gerber ZIP ──▶ parse (B.Cu, Edge.Cuts, Excellon) ──▶ panelize ──▶ raster mask (40 µm/px)
                                                          │              │
                                                          │              └──▶ .pm3 (Photon M3)
                                                          └──▶ G-code (drill bits, end mill, outline with tabs)
```

Mask polarity: **white = exposed = copper is etched away**, black = copper stays. A copper pour is kept
automatically.

## Command line

```bash
# exposure mask (PNG) and .pm3 for the Photon M3; ":15" puts 15 copies of a board on the plate
pcbhomefab exposure base.zip node.zip:15 --pm3 --exposure 120 --template reference.pm3 -o out --name panel

# drill and mill G-code (GRBL) plus an SVG preview, same board order as for the mask
pcbhomefab mill base.zip node.zip:15 -o out --name panel
```

The `.pm3` file is written natively, no other tool is needed. The machine table in it is the one Photon Workshop
writes for the Photon M3 (it refuses files with an unknown printer name). `--template` takes a `.pm3` file written by
Photon Workshop and copies its lift/retract parameters and machine table. Boards must be given in the same order for
`exposure` and `mill` so that the masks and the holes line up.

## Development

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows; use .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest
ruff check .
```

Requires Python 3.12 or newer. See [CLAUDE.md](CLAUDE.md) for the project conventions and
[docs/architecture.md](docs/architecture.md) for the design decisions.

## License

[MIT](LICENSE)
