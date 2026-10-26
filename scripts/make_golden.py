"""Record the golden outputs of the single-package code (tag ``pre-services``).

Runs the old job runner for the two real test boards and stores a SHA-256 per output file and the board layout in
``tests/golden/``. The end to end test ``tests/e2e/test_golden.py`` compares a running stack with these values.
This script needs the old ``pcbhomefab`` package and only works at the tag ``pre-services``.
"""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from pcbhomefab.board import load_board
from pcbhomefab.panel import pack
from pcbhomefab.profiles import Plate
from pcbhomefab.service.runner import run_job

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data"
GOLDEN = ROOT / "tests" / "golden"

BOARDS = [("basisplatine", 1), ("fuehlerknoten", 15)]
PARAMS = {
    "printer": "photon-m3",
    "mill": "3018pro",
    "exposure": True,
    "mill_gcode": True,
    "exposure_s": 60.0,
    "holes": "full",
    "gap_mm": 3.0,
    "margin_mm": 3.0,
    "flip": "x",
    "thickness_mm": 1.5,
    "tabs": True,
    "frame_left_mm": 1.8,
    "frame_bottom_mm": 0.8,
    "mirror_x": True,
    "boards": [{"file": f"{n}.zip", "name": n, "count": c} for n, c in BOARDS],
}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        (job / "input").mkdir()
        for name, _ in BOARDS:
            shutil.copy(DATA / f"{name}.zip", job / "input" / f"{name}.zip")
        files = run_job(job, PARAMS)
        manifest = {}
        for f in files:
            path = job / "output" / f["name"]
            if path.suffix == ".zip":
                continue  # ZIP bytes contain timestamps, the files inside are compared instead
            if path.suffix == ".png":
                with Image.open(path) as image:  # PNG bytes depend on the encoder, compare the pixels
                    data = image.convert("L").tobytes()
            else:
                data = path.read_bytes().replace(b"\r\n", b"\n")  # text written on Windows has CRLF line ends
            manifest[f["name"]] = {"sha256": hashlib.sha256(data).hexdigest(), "size": f["size"]}
    boards = [load_board(DATA / f"{n}.zip", name=n) for n, _ in BOARDS]
    expanded = [b for b, (_, c) in zip(boards, BOARDS, strict=True) for _ in range(c)]
    placements = pack(expanded, Plate(), gap_mm=3.0, margin_mm=3.0)
    layout = [{"board": p.board.name, "x_mm": p.x_mm, "y_mm": p.y_mm} for p in placements]
    GOLDEN.mkdir(exist_ok=True)
    (GOLDEN / "manifest.json").write_text(json.dumps({"params": PARAMS, "files": manifest}, indent=2) + "\n")
    (GOLDEN / "layout.json").write_text(json.dumps(layout, indent=1) + "\n")
    print(f"{len(manifest)} files, {len(layout)} placements")


if __name__ == "__main__":
    main()
