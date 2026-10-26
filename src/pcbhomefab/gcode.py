"""Drill and mill G-code for a GRBL hobby mill.

Coordinates: X0 Y0 is the lower left corner of the plate (``MillProfile.offset_*`` shifts it), copper side up,
Z0 is the plate surface. One program per tool so the tool can be changed by hand between the programs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import LayoutError
from .panel import Placement
from .profiles import MillProfile, Plate

Point = tuple[float, float]
Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class Program:
    """G-code for one tool."""

    filename: str
    title: str
    code: str
    holes: int = 0
    outlines: int = 0


@dataclass(frozen=True)
class Layout:
    """Everything the programs and the preview need, in machine coordinates."""

    #: Holes by diameter.
    holes: dict[float, list[Point]]
    #: Board rectangles (x0, y0, x1, y1).
    outlines: list[Rect]


class _Frame:
    """Plate coordinates (copper side up after turning the plate) to machine coordinates."""

    def __init__(self, plate: Plate, mill: MillProfile) -> None:
        self.plate = plate
        self.mill = mill

    def point(self, x: float, y: float) -> Point:
        if self.mill.flip == "x":
            x = self.plate.width_mm - x
        elif self.mill.flip == "y":
            y = self.plate.height_mm - y
        return x + self.mill.offset_x_mm, y + self.mill.offset_y_mm

    def rect(self, x0: float, y0: float, x1: float, y1: float) -> Rect:
        ax, ay = self.point(x0, y0)
        bx, by = self.point(x1, y1)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)


def build_layout(placements: list[Placement], plate: Plate, mill: MillProfile) -> Layout:
    frame = _Frame(plate, mill)
    holes: dict[float, list[Point]] = {}
    outlines: list[Rect] = []
    for placement in placements:
        outlines.append(frame.rect(placement.x_mm, placement.y_mm, placement.x1_mm, placement.y1_mm))
        for hole in placement.board.holes:
            holes.setdefault(hole.diameter, []).append(
                frame.point(placement.x_mm + hole.x, placement.y_mm + hole.y)
            )
    return Layout(holes, outlines)


def _nearest_order(points: list[Point]) -> list[Point]:
    """Greedy nearest neighbour order starting at the machine origin, saves travel moves."""
    remaining = list(points)
    ordered: list[Point] = []
    x, y = 0.0, 0.0
    while remaining:
        nearest = min(
            range(len(remaining)), key=lambda i: (remaining[i][0] - x) ** 2 + (remaining[i][1] - y) ** 2
        )
        x, y = remaining.pop(nearest)
        ordered.append((x, y))
    return ordered


class _Writer:
    def __init__(self, title: str, mill: MillProfile, tool_message: str) -> None:
        self.mill = mill
        self.z = mill.safe_z_mm
        self.lines = [
            f"({title})",
            "(GRBL, X0 Y0 = lower left corner of the plate, copper side up, Z0 = plate surface)",
            "G21 G90 G17 G94",
            f"G0 Z{mill.safe_z_mm:g}",
            f"M3 S{mill.spindle_rpm}",
            f"G4 P{mill.spindle_spinup_s:g}",
            f"(MSG, {tool_message})",
        ]

    def add(self, line: str) -> None:
        self.lines.append(line)

    def up(self, z: float | None = None) -> None:
        z = self.mill.safe_z_mm if z is None else z
        self.add(f"G0 Z{z:.3f}")
        self.z = z

    def rapid(self, x: float, y: float) -> None:
        if self.z != self.mill.safe_z_mm:
            self.up()
        self.add(f"G0 X{x:.3f} Y{y:.3f}")

    def down(self, z: float, feed: float) -> None:
        self.add(f"G1 Z{z:.3f} F{feed:g}")
        self.z = z

    def line(self, x: float, y: float, feed: float) -> None:
        self.add(f"G1 X{x:.3f} Y{y:.3f} F{feed:g}")

    def finish(self) -> str:
        self.up(self.mill.safe_z_mm + 15)
        self.add("M5")
        self.add("M30")
        return "\n".join(self.lines) + "\n"


def _drill(writer: _Writer, holes: list[Point], plate: Plate, mill: MillProfile) -> None:
    depth = plate.thickness_mm + mill.drill_overshoot_mm
    for x, y in _nearest_order(holes):
        writer.rapid(x, y)
        writer.up(1.0)
        reached = 0.0
        while reached < depth:
            reached = min(reached + mill.peck_mm, depth) if mill.peck_mm > 0 else depth
            writer.down(-reached, mill.drill_feed)
            writer.up(1.0)
            if reached < depth:
                writer.add(f"G0 Z{-reached + 0.3:.3f}")
        writer.up()


def _mill_hole(writer: _Writer, x: float, y: float, diameter: float, plate: Plate, mill: MillProfile) -> None:
    """Circle a hole out with the end mill (path inside the hole edge)."""
    radius = (diameter - mill.endmill_mm) / 2
    if radius < 0.05:
        raise LayoutError(
            f"A {diameter} mm hole is too small for the {mill.endmill_mm} mm end mill "
            "and no drill of that size is listed."
        )
    depth = plate.thickness_mm + mill.mill_overshoot_mm
    writer.rapid(x + radius, y)
    writer.up(0.5)
    z = 0.0
    while z < depth:
        z = min(z + mill.mill_step_mm, depth)
        writer.down(-z, mill.plunge_feed)
        writer.add(f"G3 X{x + radius:.3f} Y{y:.3f} I{-radius:.3f} J0 F{mill.mill_feed:g}")
    writer.up()


def _mill_outline(writer: _Writer, rect: Rect, plate: Plate, mill: MillProfile) -> None:
    """Walk around the board counter-clockwise (climb milling), outside the outline, with tabs."""
    r = mill.endmill_mm / 2
    x0, y0, x1, y1 = rect[0] - r, rect[1] - r, rect[2] + r, rect[3] + r
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    depth = plate.thickness_mm + mill.mill_overshoot_mm
    tab_z = -(plate.thickness_mm - mill.tab_height_mm)
    sections: list[tuple[float, float, float, float, bool]] = []
    for (ax, ay), (bx, by) in zip(corners, corners[1:], strict=False):
        length = math.hypot(bx - ax, by - ay)
        if not mill.tabs or length < 3 * mill.tab_width_mm:
            sections.append((ax, ay, bx, by, False))
            continue
        dx, dy = (bx - ax) / length, (by - ay) / length
        s1, s2 = length / 2 - mill.tab_width_mm / 2, length / 2 + mill.tab_width_mm / 2
        sections += [
            (ax, ay, ax + dx * s1, ay + dy * s1, False),
            (ax + dx * s1, ay + dy * s1, ax + dx * s2, ay + dy * s2, True),
            (ax + dx * s2, ay + dy * s2, bx, by, False),
        ]
    writer.rapid(x0, y0)
    writer.up(0.5)
    z = 0.0
    while z < depth:
        z = min(z + mill.mill_step_mm, depth)
        writer.down(-z, mill.plunge_feed)
        for _ax, _ay, bx, by, is_tab in sections:
            target = max(-z, tab_z) if is_tab else -z
            if abs(writer.z - target) > 1e-6:
                writer.down(target, mill.plunge_feed)
            writer.line(bx, by, mill.mill_feed)
    writer.up()


def generate(placements: list[Placement], plate: Plate, mill: MillProfile) -> list[Program]:
    """Programs in tool order: one per drill size, then the end mill (large holes and outlines)."""
    layout = build_layout(placements, plate, mill)
    programs: list[Program] = []
    milled: dict[float, list[Point]] = {}
    for diameter in sorted(layout.holes):
        holes = layout.holes[diameter]
        if any(abs(diameter - d) < 0.01 for d in mill.drills):
            title = f"Drill {diameter:.1f} mm, {len(holes)} holes"
            writer = _Writer(
                title, mill, f"Insert the {diameter:.1f} mm drill and set Z0 to the plate surface"
            )
            _drill(writer, holes, plate, mill)
            name = f"{len(programs) + 1}_drill_{diameter:.1f}mm.nc"
            programs.append(Program(name, title, writer.finish(), holes=len(holes)))
        else:
            milled[diameter] = holes

    title = f"Mill with {mill.endmill_mm:.1f} mm end mill: large holes and outlines"
    writer = _Writer(
        title, mill, f"Insert the {mill.endmill_mm:.1f} mm end mill and set Z0 to the plate surface"
    )
    for diameter, holes in milled.items():
        for x, y in _nearest_order(holes):
            _mill_hole(writer, x, y, diameter, plate, mill)
    for rect in layout.outlines:
        _mill_outline(writer, rect, plate, mill)
    name = f"{len(programs) + 1}_mill_{mill.endmill_mm:.1f}mm.nc"
    programs.append(
        Program(
            name,
            title,
            writer.finish(),
            holes=sum(len(h) for h in milled.values()),
            outlines=len(layout.outlines),
        )
    )
    return programs


def preview_svg(placements: list[Placement], plate: Plate, mill: MillProfile, scale: float = 5.0) -> str:
    """Plate, board outlines and holes (coloured by diameter) as SVG, as the plate lies on the mill bed."""
    layout = build_layout(placements, plate, mill)
    colors = ["#ffd60a", "#00b4d8", "#ffffff", "#ff006e"]
    by_diameter = {d: colors[i % len(colors)] for i, d in enumerate(sorted(layout.holes))}
    height = plate.height_mm

    def sx(x: float) -> float:
        return (x - mill.offset_x_mm) * scale

    def sy(y: float) -> float:
        return (height - (y - mill.offset_y_mm)) * scale

    parts = [
        f'<rect x="0" y="0" width="{plate.width_mm * scale}" height="{height * scale}" '
        'fill="#c9a06a" stroke="black"/>'
    ]
    for x0, y0, x1, y1 in layout.outlines:
        parts.append(
            f'<rect x="{sx(x0)}" y="{sy(y1)}" width="{(x1 - x0) * scale}" height="{(y1 - y0) * scale}" '
            'fill="#2d6a4f" stroke="#d00000" stroke-width="1"/>'
        )
    for diameter, points in layout.holes.items():
        for x, y in points:
            radius = max(diameter * scale / 2, 1.2)
            parts.append(f'<circle cx="{sx(x)}" cy="{sy(y)}" r="{radius}" fill="{by_diameter[diameter]}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{plate.width_mm * scale}" height="{height * scale}" '
        f'viewBox="0 0 {plate.width_mm * scale} {height * scale}">' + "".join(parts) + "</svg>"
    )
