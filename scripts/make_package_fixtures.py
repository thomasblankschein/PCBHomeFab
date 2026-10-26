"""Make the canonical board packages that the tests of `exposure` and `mill` use as fixtures.

The packages are what the ingest service returns for the two real test boards in ``tests/data``. Run this after
a change of the package format and commit the result. It is a tool script, not part of any service.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "ingest" / "src"))

from ingest.package import build_package  # noqa: E402

BOARDS = ["basisplatine", "fuehlerknoten"]
TARGETS = ["exposure", "mill"]


def main() -> None:
    for name in BOARDS:
        package = build_package((ROOT / "tests" / "data" / f"{name}.zip").read_bytes(), name)
        for service in TARGETS:
            target = ROOT / "services" / service / "tests" / "data"
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{name}.zip").write_bytes(package)
        print(f"{name}: {len(package)} bytes")


if __name__ == "__main__":
    main()
