"""Plate sizes: the blanks a job can be made for.

The list is a TOML file (see ``data/plates.toml``). The packaged file is the default; a user file replaces it
completely and is chosen with ``PCBHOMEFAB_PLATES_FILE``. A job stores the size it was made with, so changing the
list does not change old jobs.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
MAX_SIDE_MM = 1000.0


class PlatesError(ValueError):
    """The list of plate sizes is not usable. Raised at start, so a wrong file is noticed at once."""


@dataclass(frozen=True)
class PlateSize:
    id: str
    name: str
    width_mm: float
    height_mm: float
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "width_mm": self.width_mm, "height_mm": self.height_mm}


class PlateLibrary:
    def __init__(self, plates: list[PlateSize], source: str = "") -> None:
        self.source = source
        self.plates = plates

    @property
    def active(self) -> list[PlateSize]:
        return [plate for plate in self.plates if plate.enabled]

    def find(self, plate_id: str) -> PlateSize | None:
        return next((plate for plate in self.active if plate.id == plate_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "plates": [plate.to_dict() for plate in self.active]}


def _side(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= MAX_SIDE_MM:
        raise PlatesError(f"{where}: expected a number between 0 and {MAX_SIDE_MM:g}, got {value!r}.")
    return float(value)


def parse_plates(text: str, source: str = "") -> PlateLibrary:
    """Parse and validate a list of plate sizes given as TOML text."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PlatesError(f"Plate sizes {source}: invalid TOML ({exc}).") from exc
    entries = data.get("plate", [])
    if not isinstance(entries, list) or not entries:
        raise PlatesError("The list of plate sizes needs at least one [[plate]] entry.")
    plates: list[PlateSize] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        plate_id = str(entry.get("id", ""))
        where = f"plate #{index} ({plate_id or 'no id'})"
        if not ID.match(plate_id) or plate_id in seen:
            raise PlatesError(f"{where}: needs a unique id of letters, digits, '_', '.' and '-'.")
        seen.add(plate_id)
        unknown = set(entry) - {"id", "name", "width_mm", "height_mm", "enabled"}
        if unknown:
            raise PlatesError(f"{where}: unknown keys {sorted(unknown)}.")
        width = _side(entry.get("width_mm"), f"{where}.width_mm")
        height = _side(entry.get("height_mm"), f"{where}.height_mm")
        plates.append(
            PlateSize(
                id=plate_id,
                name=str(entry.get("name") or f"{width:g} × {height:g} mm"),
                width_mm=width,
                height_mm=height,
                enabled=bool(entry.get("enabled", True)),
            )
        )
    if not any(plate.enabled for plate in plates):
        raise PlatesError("At least one plate size must be enabled.")
    return PlateLibrary(plates, source)


def default_text() -> str:
    return resources.files("jobs").joinpath("data/plates.toml").read_text(encoding="utf-8")


def load_plates(path: str | Path | None = None) -> PlateLibrary:
    """Load the plate sizes: the given file, else ``PCBHOMEFAB_PLATES_FILE``, else the packaged default."""
    chosen = path or os.environ.get("PCBHOMEFAB_PLATES_FILE") or None
    if chosen is None:
        return parse_plates(default_text(), "built-in")
    file = Path(chosen)
    try:
        return parse_plates(file.read_text(encoding="utf-8"), str(file))
    except OSError as exc:
        raise PlatesError(f"The list of plate sizes {file} could not be read: {exc.strerror}.") from exc
