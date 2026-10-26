"""Command line interface: ``pcbhomefab exposure`` and ``pcbhomefab mill``."""

from __future__ import annotations

import argparse
import contextlib
import sys
from dataclasses import replace
from pathlib import Path

from . import gcode
from .board import Board, load_board
from .errors import PCBHomeFabError
from .mask import build_mask
from .panel import Placement, pack
from .pm3 import write_pm3
from .profiles import MILL_3018PRO, PHOTON_M3, Plate


def _boards(specs: list[str]) -> list[Board]:
    """``board.zip`` or ``board.zip:15`` (copies). The order decides the order on the plate."""
    loaded: dict[str, Board] = {}
    boards: list[Board] = []
    for spec in specs:
        path, separator, count = spec.rpartition(":")
        if not (separator and path and count.isdigit()):  # also keeps Windows drive letters intact
            path, count = spec, "1"
        if path not in loaded:
            loaded[path] = load_board(path)
        boards += [loaded[path]] * int(count)
    return boards


def _placements(args: argparse.Namespace) -> list[Placement]:
    return pack(_boards(args.boards), Plate(), gap_mm=args.gap, margin_mm=args.margin)


def _exposure(args: argparse.Namespace) -> None:
    placements = _placements(args)
    mask = build_mask(placements, PHOTON_M3, holes=args.holes)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    mask.save(out / f"{args.name}.png", dpi=(25.4 / PHOTON_M3.pixel_mm,) * 2)
    print(f"{out / (args.name + '.png')}: {len(placements)} boards")
    if args.pm3:
        target = out / f"{args.name}.pm3"
        write_pm3(mask, PHOTON_M3, target, args.exposure, template=Path(args.template) if args.template else None)
        print(f"{target}")


def _mill(args: argparse.Namespace) -> None:
    placements = _placements(args)
    plate = Plate(thickness_mm=args.thickness)
    mill = replace(MILL_3018PRO, flip=args.flip, tabs=not args.no_tabs)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for program in gcode.generate(placements, plate, mill):
        (out / f"{args.name}_{program.filename}").write_text(program.code, encoding="ascii", errors="replace")
        print(f"{args.name}_{program.filename}: {program.title}")
    (out / f"{args.name}_preview.svg").write_text(gcode.preview_svg(placements, plate, mill), encoding="utf-8")


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .service.api import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)


def _worker(_args: argparse.Namespace) -> None:
    import logging
    import threading

    from .service.config import Settings
    from .service.store import JobStore
    from .service.worker import worker_loop

    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    with contextlib.suppress(KeyboardInterrupt):
        worker_loop(JobStore(settings), settings, threading.Event())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pcbhomefab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("boards", nargs="+", help="Gerber ZIP, optionally ':count' (e.g. node.zip:15)")
        p.add_argument("-o", "--out", default="out", help="output folder (default: out)")
        p.add_argument("--name", default="panel", help="file name prefix (default: panel)")
        p.add_argument("--gap", type=float, default=3.0, help="gap between boards in mm")
        p.add_argument("--margin", type=float, default=3.0, help="margin to the plate edge in mm")

    exposure = sub.add_parser("exposure", help="exposure mask (PNG) and optional .pm3 for the Photon M3")
    common(exposure)
    exposure.add_argument("--holes", choices=["full", "center", "none"], default="full")
    exposure.add_argument("--pm3", action="store_true", help="also write a .pm3 file (needs UVtools)")
    exposure.add_argument("--exposure", type=float, help="exposure time in seconds")
    exposure.add_argument("--template", help=".pm3 file made by Photon Workshop (machine table, print parameters)")
    exposure.set_defaults(run=_exposure)

    mill = sub.add_parser("mill", help="drill and mill G-code for a GRBL mill")
    common(mill)
    mill.add_argument("--flip", choices=["x", "y", "none"], default="x", help="how the plate is turned over")
    mill.add_argument("--thickness", type=float, default=1.5, help="material thickness in mm")
    mill.add_argument("--no-tabs", action="store_true")
    mill.set_defaults(run=_mill)

    serve = sub.add_parser("serve", help="run the web service (needs the 'web' extra)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(run=_serve)

    worker = sub.add_parser(
        "worker", help="run a separate job worker (set PCBHOMEFAB_EMBEDDED_WORKERS=0 for the web process)"
    )
    worker.set_defaults(run=_worker)

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except PCBHomeFabError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
