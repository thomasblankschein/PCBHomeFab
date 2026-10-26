"""Tool library: drill bits and end mills with their cutting parameters.

The library is a TOML file (see ``data/tools.toml``). The packaged file is the default; a user file replaces it
completely and is chosen with ``PCBHOMEFAB_TOOLS_FILE``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from .common import Problem


def _invalid(detail: str) -> Problem:
    return Problem(422, "mill.invalid_tools", detail)


KINDS = ("drill", "endmill")
#: Parameters that apply to a kind of tool, with their allowed value range (exclusive minimum).
_PARAMETERS: dict[str, tuple[str, ...]] = {
    "drill": ("spindle_rpm", "plunge_feed", "peck_mm"),
    "endmill": ("spindle_rpm", "feed", "plunge_feed", "step_down_mm"),
}
_ZERO_ALLOWED = {"peck_mm"}
#: A hole counts as drillable by a bit when the diameters differ by at most this much.
DRILL_TOLERANCE_MM = 0.02
#: An end mill needs at least this much room on each side to circle a hole out.
MIN_MILL_RADIUS_MM = 0.05


@dataclass(frozen=True)
class Tool:
    """One drill bit or end mill. Unused parameters of the other kind stay 0."""

    id: str
    kind: str
    diameter_mm: float
    spindle_rpm: int
    plunge_feed: float
    #: Feed in the material (end mill only).
    feed: float = 0.0
    #: Drilling depth per peck, 0 drills in one go (drill only).
    peck_mm: float = 0.0
    #: Depth per pass (end mill only).
    step_down_mm: float = 0.0
    name: str = ""
    notes: str = ""
    enabled: bool = True

    @property
    def label(self) -> str:
        return self.name or f"{'Drill' if self.kind == 'drill' else 'End mill'} {self.diameter_mm:g} mm"


class ToolLibrary:
    def __init__(self, tools: list[Tool], source: str = "") -> None:
        self.source = source
        self.tools = tools

    @property
    def active(self) -> list[Tool]:
        return [tool for tool in self.tools if tool.enabled]

    def drills(self) -> list[Tool]:
        return sorted((t for t in self.active if t.kind == "drill"), key=lambda t: t.diameter_mm)

    def endmills(self) -> list[Tool]:
        return sorted((t for t in self.active if t.kind == "endmill"), key=lambda t: t.diameter_mm)

    def find_drill(self, diameter_mm: float) -> Tool | None:
        """The drill bit for a hole of this diameter, or ``None`` when no bit matches closely enough."""
        matches = [t for t in self.drills() if abs(t.diameter_mm - diameter_mm) <= DRILL_TOLERANCE_MM]
        return min(matches, key=lambda t: abs(t.diameter_mm - diameter_mm)) if matches else None

    def largest_drill(self) -> float:
        drills = self.drills()
        return drills[-1].diameter_mm if drills else 0.0

    def endmill(self, diameter_mm: float) -> Tool:
        for tool in self.endmills():
            if abs(tool.diameter_mm - diameter_mm) <= DRILL_TOLERANCE_MM:
                return tool
        sizes = ", ".join(f"{t.diameter_mm:g}" for t in self.endmills()) or "none"
        raise Problem(
            422, "mill.no_endmill", f"No {diameter_mm:g} mm end mill in the tool library (available: {sizes} mm)."
        )

    def mill_for_hole(self, hole_mm: float, preferred_mm: float) -> Tool:
        """The end mill to circle out a hole: the preferred one if it fits, else the largest smaller one."""
        candidates = [t for t in self.endmills() if t.diameter_mm <= preferred_mm + DRILL_TOLERANCE_MM]
        for tool in reversed(candidates):
            if (hole_mm - tool.diameter_mm) / 2 >= MIN_MILL_RADIUS_MM:
                return tool
        raise Problem(
            422,
            "mill.no_drill",
            f"A {hole_mm:g} mm hole has no matching drill and is too small for any end mill of the library.",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "tools": [tool.__dict__ for tool in self.tools]}


def _number(value: Any, where: str, *, zero_ok: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(f"{where}: expected a number, got {value!r}.")
    if value < 0 or (value == 0 and not zero_ok):
        raise _invalid(f"{where}: must be {'zero or ' if zero_ok else ''}greater than zero.")
    return float(value)


def parse_tools(text: str, source: str = "") -> ToolLibrary:
    """Parse and validate a tool library given as TOML text."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise _invalid(f"Tool library {source or ''}: invalid TOML ({exc}).") from exc
    defaults = data.get("defaults", {})
    entries = data.get("tool", [])
    if not isinstance(entries, list) or not entries:
        raise _invalid("The tool library needs at least one [[tool]] entry.")
    tools: list[Tool] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        tool_id = str(entry.get("id", ""))
        where = f"tool #{index} ({tool_id or 'no id'})"
        if not tool_id or tool_id in seen:
            raise _invalid(f"{where}: needs a unique id.")
        seen.add(tool_id)
        kind = entry.get("kind")
        if kind not in KINDS:
            raise _invalid(f"{where}: kind must be 'drill' or 'endmill'.")
        merged = {**defaults.get(kind, {}), **entry}
        values: dict[str, float] = {}
        for key in _PARAMETERS[kind]:
            if key not in merged:
                raise _invalid(f"{where}: missing '{key}'.")
            values[key] = _number(merged[key], f"{where}.{key}", zero_ok=key in _ZERO_ALLOWED)
        unknown = set(entry) - {"id", "kind", "diameter_mm", "name", "notes", "enabled", *_PARAMETERS[kind]}
        if unknown:
            raise _invalid(f"{where}: unknown or misplaced keys {sorted(unknown)} for a {kind}.")
        tools.append(
            Tool(
                id=tool_id,
                kind=kind,
                diameter_mm=_number(entry.get("diameter_mm"), f"{where}.diameter_mm"),
                spindle_rpm=int(values["spindle_rpm"]),
                plunge_feed=values["plunge_feed"],
                feed=values.get("feed", 0.0),
                peck_mm=values.get("peck_mm", 0.0),
                step_down_mm=values.get("step_down_mm", 0.0),
                name=str(entry.get("name", "")),
                notes=str(entry.get("notes", "")),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return ToolLibrary(tools, source)


def default_text() -> str:
    return resources.files("mill").joinpath("data/tools.toml").read_text(encoding="utf-8")


def load_tools(path: str | Path | None = None) -> ToolLibrary:
    """Load a tool library: the given file, else ``PCBHOMEFAB_TOOLS_FILE``, else the packaged default."""
    chosen = path or os.environ.get("PCBHOMEFAB_TOOLS_FILE") or None
    if chosen is None:
        return parse_tools(default_text(), "built-in")
    file = Path(chosen)
    try:
        return parse_tools(file.read_text(encoding="utf-8"), str(file))
    except OSError as exc:
        raise _invalid(f"The tool library {file} could not be read: {exc.strerror}.") from exc
