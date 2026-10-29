"""Panel sizes: the blanks a job can be made for.

The list is a TOML file (see ``data/panels.toml``). The packaged file is the default; a user file replaces it
completely and is chosen with ``PCBHOMEFAB_PANELS_FILE``. A job stores the size it was made with, so changing the
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


class PanelsError(ValueError):
    """The list of panel sizes is not usable. Raised at start, so a wrong file is noticed at once."""


@dataclass(frozen=True)
class PanelSize:
    id: str
    name: str
    width_mm: float
    height_mm: float
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "width_mm": self.width_mm, "height_mm": self.height_mm}


class PanelLibrary:
    def __init__(self, panels: list[PanelSize], source: str = "") -> None:
        self.source = source
        self.panels = panels

    @property
    def active(self) -> list[PanelSize]:
        return [panel for panel in self.panels if panel.enabled]

    def find(self, panel_id: str) -> PanelSize | None:
        return next((panel for panel in self.active if panel.id == panel_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "panels": [panel.to_dict() for panel in self.active]}


def _side(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value <= MAX_SIDE_MM:
        raise PanelsError(f"{where}: expected a number between 0 and {MAX_SIDE_MM:g}, got {value!r}.")
    return float(value)


def parse_panels(text: str, source: str = "") -> PanelLibrary:
    """Parse and validate a list of panel sizes given as TOML text."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PanelsError(f"Panel sizes {source}: invalid TOML ({exc}).") from exc
    entries = data.get("panel", [])
    if not isinstance(entries, list) or not entries:
        raise PanelsError("The list of panel sizes needs at least one [[panel]] entry.")
    panels: list[PanelSize] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        panel_id = str(entry.get("id", ""))
        where = f"panel #{index} ({panel_id or 'no id'})"
        if not ID.match(panel_id) or panel_id in seen:
            raise PanelsError(f"{where}: needs a unique id of letters, digits, '_', '.' and '-'.")
        seen.add(panel_id)
        unknown = set(entry) - {"id", "name", "width_mm", "height_mm", "enabled"}
        if unknown:
            raise PanelsError(f"{where}: unknown keys {sorted(unknown)}.")
        width = _side(entry.get("width_mm"), f"{where}.width_mm")
        height = _side(entry.get("height_mm"), f"{where}.height_mm")
        panels.append(
            PanelSize(
                id=panel_id,
                name=str(entry.get("name") or f"{width:g} × {height:g} mm"),
                width_mm=width,
                height_mm=height,
                enabled=bool(entry.get("enabled", True)),
            )
        )
    if not any(panel.enabled for panel in panels):
        raise PanelsError("At least one panel size must be enabled.")
    return PanelLibrary(panels, source)


def default_text() -> str:
    return resources.files("jobs").joinpath("data/panels.toml").read_text(encoding="utf-8")


def load_panels(path: str | Path | None = None) -> PanelLibrary:
    """Load the panel sizes: the given file, else ``PCBHOMEFAB_PANELS_FILE``, else the packaged default."""
    chosen = path or os.environ.get("PCBHOMEFAB_PANELS_FILE") or None
    if chosen is None:
        return parse_panels(default_text(), "built-in")
    file = Path(chosen)
    try:
        return parse_panels(file.read_text(encoding="utf-8"), str(file))
    except OSError as exc:
        raise PanelsError(f"The list of panel sizes {file} could not be read: {exc.strerror}.") from exc
