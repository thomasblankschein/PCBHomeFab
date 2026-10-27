"""Drill and mill G-code for a GRBL hobby mill.

Coordinates: X0 Y0 is the lower left corner of the plate (``MillProfile.offset_*`` shifts it), copper side up,
Z0 is the plate surface. One program per tool so the tool can be changed by hand between the programs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import MultiPolygon, Polygon

from .common import Problem
from .profiles import MillProfile, Plate
from .tools import Tool, ToolLibrary, load_tools

Point = tuple[float, float]
#: A board shape: the outer polygon and the polygons of cutouts.
Shape = tuple[list[Point], list[list[Point]]]


@dataclass(frozen=True)
class Placement:
    """A board on the plate: lower left corner, size and holes (relative to the board's lower left corner)."""

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    #: ``(x, y, diameter)`` of every hole.
    holes: list[tuple[float, float, float]]
    #: Real shape (outer polygon and cutouts) relative to the lower left corner; ``None`` means the rectangle.
    contour: Shape | None = None

    def shape(self) -> Shape:
        if self.contour is not None:
            return self.contour
        w, h = self.width_mm, self.height_mm
        return [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)], []


@dataclass(frozen=True)
class Program:
    """G-code for one tool."""

    filename: str
    title: str
    code: str
    holes: int = 0
    outlines: int = 0
    tool: str = ""


@dataclass(frozen=True)
class Layout:
    """Everything the programs and the preview need, in machine coordinates."""

    #: Holes by diameter.
    holes: dict[float, list[Point]]
    #: Board shapes.
    outlines: list[Shape]


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


def build_layout(placements: list[Placement], plate: Plate, mill: MillProfile) -> Layout:
    frame = _Frame(plate, mill)
    holes: dict[float, list[Point]] = {}
    outlines: list[Shape] = []
    for placement in placements:
        outer, cutouts = placement.shape()

        def move(points: list[Point], p: Placement = placement) -> list[Point]:
            return [frame.point(p.x_mm + x, p.y_mm + y) for x, y in points]

        outlines.append((move(outer), [move(cutout) for cutout in cutouts]))
        for x, y, diameter in placement.holes:
            holes.setdefault(diameter, []).append(frame.point(placement.x_mm + x, placement.y_mm + y))
    return Layout(holes, outlines)


def _nearest_order(points: list[Point]) -> list[Point]:
    """Greedy nearest neighbour order starting at the machine origin, saves travel moves."""
    remaining = list(points)
    ordered: list[Point] = []
    x, y = 0.0, 0.0
    while remaining:
        nearest = min(range(len(remaining)), key=lambda i: (remaining[i][0] - x) ** 2 + (remaining[i][1] - y) ** 2)
        x, y = remaining.pop(nearest)
        ordered.append((x, y))
    return ordered


class _Writer:
    def __init__(self, title: str, mill: MillProfile, tool: Tool, tool_message: str) -> None:
        if tool.spindle_rpm > mill.max_spindle_rpm:
            raise Problem(
                422,
                "mill.spindle_too_fast",
                f"{tool.label} asks for {tool.spindle_rpm} rpm, the machine allows {mill.max_spindle_rpm} rpm.",
            )
        self.mill = mill
        self.tool = tool
        self.z = mill.safe_z_mm
        self.lines = [
            f"({title})",
            "(GRBL, X0 Y0 = lower left corner of the plate, copper side up, Z0 = plate surface)",
            "G21 G90 G17 G94",
            # tool change position: spindle off, up, to X0 Y0, then wait (M0) until the user resumes
            "M5",
            f"G0 Z{mill.tool_change_z_mm:.3f}",
            "G0 X0.000 Y0.000",
            f"(MSG, {tool_message}, then resume)",
            "M0",
            f"G0 Z{mill.safe_z_mm:g}",
            f"M3 S{tool.spindle_rpm}",
            f"G4 P{mill.spindle_spinup_s:g}",
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
        # park at the tool change position: up, to X0 Y0 (lower left corner of the plate), spindle off
        self.up(self.mill.tool_change_z_mm)
        self.add("G0 X0.000 Y0.000")
        self.add("M5")
        self.add("M30")
        return "\n".join(self.lines) + "\n"


def _drill(writer: _Writer, holes: list[Point], plate: Plate, mill: MillProfile) -> None:
    tool = writer.tool
    depth = plate.thickness_mm + mill.drill_overshoot_mm
    for x, y in _nearest_order(holes):
        writer.rapid(x, y)
        writer.up(1.0)
        reached = 0.0
        while reached < depth:
            reached = min(reached + tool.peck_mm, depth) if tool.peck_mm > 0 else depth
            writer.down(-reached, tool.plunge_feed)
            writer.up(1.0)
            if reached < depth:
                writer.add(f"G0 Z{-reached + 0.3:.3f}")
        writer.up()


def _mill_hole(writer: _Writer, x: float, y: float, diameter: float, plate: Plate, mill: MillProfile) -> None:
    """Circle a hole out with the end mill (path inside the hole edge)."""
    tool = writer.tool
    radius = (diameter - tool.diameter_mm) / 2
    depth = plate.thickness_mm + mill.mill_overshoot_mm
    writer.rapid(x + radius, y)
    writer.up(0.5)
    z = 0.0
    while z < depth:
        z = min(z + tool.step_down_mm, depth)
        writer.down(-z, tool.plunge_feed)
        writer.add(f"G3 X{x + radius:.3f} Y{y:.3f} I{-radius:.3f} J0 F{tool.feed:g}")
    writer.up()


def _area(points: list[Point]) -> float:
    """Signed area, positive when the points run counter-clockwise."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True)) / 2


def _closed_path(points: list[Point], counter_clockwise: bool) -> list[Point]:
    """Closed path (last point = first) in the wanted direction, starting at the lowest, then leftmost point."""
    ring = list(points[:-1] if points[0] == points[-1] else points)
    if (_area(ring) > 0) != counter_clockwise:
        ring.reverse()
    start = min(range(len(ring)), key=lambda i: (ring[i][1], ring[i][0]))
    ring = ring[start:] + ring[:start]
    return ring + [ring[0]]


def _polygons(geometry: object) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry] if not geometry.is_empty else []
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return []


def tool_paths(shape: Shape, radius: float) -> list[tuple[list[Point], bool]]:
    """Paths of the tool centre for one board: first the cutouts (inside, clockwise), last the outer contour
    (outside, counter-clockwise, climb milling). The flag says whether tabs hold the piece in place.
    """
    paths: list[tuple[list[Point], bool]] = []
    outer, cutouts = shape
    for cutout in cutouts:
        pieces = _polygons(Polygon(cutout).buffer(-radius, join_style="mitre"))
        if not pieces:
            raise Problem(422, "mill.cutout_too_small", "A cutout in the board outline is too small for the end mill.")
        paths += [(_closed_path(list(piece.exterior.coords)[:-1], False), False) for piece in pieces]
    polygon = Polygon(outer)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    grown = max(_polygons(polygon.buffer(radius, join_style="mitre")), key=lambda p: p.area)
    paths.append((_closed_path(list(grown.exterior.coords)[:-1], True), True))
    return paths


def _sections(path: list[Point], mill: MillProfile, with_tabs: bool) -> list[tuple[float, float, float, float, bool]]:
    """Pieces of the path as ``(x0, y0, x1, y1, is_tab)``. A tab sits in the middle of every straight side that is
    at least three tab widths long; a path without two such sides (a circle) gets tabs spread over its length.
    """
    width = mill.tab_width_mm
    segments = list(zip(path, path[1:], strict=False))
    lengths = [math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in segments]
    tabs: dict[int, list[tuple[float, float]]] = {}
    if with_tabs and mill.tabs:
        for index, length in enumerate(lengths):
            if length >= 3 * width:
                tabs[index] = [(length / 2 - width / 2, length / 2 + width / 2)]
        total = sum(lengths)
        if len(tabs) < 2:
            count = 4 if total >= 12 * width else 2 if total >= 6 * width else 0
            tabs = {}
            for k in range(count):
                centre = total * (k + 0.5) / count
                first, last = centre - width / 2, centre + width / 2
                start = 0.0
                for index, length in enumerate(lengths):
                    low, high = max(first, start), min(last, start + length)
                    if low < high:
                        # snap to the ends of the side so that sections join up exactly
                        local = (
                            0.0 if low - start < 1e-9 else low - start,
                            length if start + length - high < 1e-9 else high - start,
                        )
                        tabs.setdefault(index, []).append(local)
                    start += length
    sections: list[tuple[float, float, float, float, bool]] = []
    for index, ((ax, ay), (bx, by)) in enumerate(segments):
        length = lengths[index]
        ranges = sorted(tabs.get(index, []))
        if not ranges or length <= 0:
            sections.append((ax, ay, bx, by, False))
            continue
        dx, dy = (bx - ax) / length, (by - ay) / length
        cuts = [0.0]
        for low, high in ranges:
            cuts += [low, high]
        cuts.append(length)
        for s0, s1 in zip(cuts, cuts[1:], strict=False):
            if s1 <= s0:
                continue
            is_tab = any(low <= (s0 + s1) / 2 <= high for low, high in ranges)
            p0 = (ax, ay) if s0 == 0.0 else (ax + dx * s0, ay + dy * s0)
            p1 = (bx, by) if s1 == length else (ax + dx * s1, ay + dy * s1)
            sections.append((p0[0], p0[1], p1[0], p1[1], is_tab))
    return sections


def _mill_outline(writer: _Writer, path: list[Point], with_tabs: bool, plate: Plate, mill: MillProfile) -> None:
    """Walk along a tool path (see ``tool_paths``), with tabs if asked for."""
    tool = writer.tool
    depth = plate.thickness_mm + mill.mill_overshoot_mm
    tab_z = -(plate.thickness_mm - mill.tab_height_mm)
    sections = _sections(path, mill, with_tabs)
    writer.rapid(*path[0])
    writer.up(0.5)
    z = 0.0
    while z < depth:
        z = min(z + tool.step_down_mm, depth)
        writer.down(-z, tool.plunge_feed)
        for _ax, _ay, bx, by, is_tab in sections:
            target = max(-z, tab_z) if is_tab else -z
            if abs(writer.z - target) > 1e-6:
                writer.down(target, tool.plunge_feed)
            writer.line(bx, by, tool.feed)
    writer.up()


def generate(
    placements: list[Placement], plate: Plate, mill: MillProfile, tools: ToolLibrary | None = None
) -> list[Program]:
    """Programs in tool order: one per drill bit, then one per end mill (large holes and outlines)."""
    tools = tools or load_tools()
    layout = build_layout(placements, plate, mill)
    outline_tool = tools.endmill(mill.outline_endmill_mm)
    drilled: dict[str, tuple[Tool, list[Point]]] = {}
    milled: dict[str, tuple[Tool, dict[float, list[Point]]]] = {outline_tool.id: (outline_tool, {})}
    for diameter in sorted(layout.holes):
        holes = layout.holes[diameter]
        drill = tools.find_drill(diameter)
        if drill is not None:
            drilled.setdefault(drill.id, (drill, []))[1].extend(holes)
        elif diameter > tools.largest_drill():
            cutter = tools.mill_for_hole(diameter, outline_tool.diameter_mm)
            milled.setdefault(cutter.id, (cutter, {}))[1][diameter] = holes
        else:
            sizes = ", ".join(f"{t.diameter_mm:g}" for t in tools.drills())
            raise Problem(
                422, "mill.no_drill", f"No drill for a {diameter:g} mm hole (drills in the library: {sizes} mm)."
            )

    programs: list[Program] = []
    for drill, holes in sorted(drilled.values(), key=lambda entry: entry[0].diameter_mm):
        title = f"Drill {drill.diameter_mm:.1f} mm, {len(holes)} holes"
        message = f"Insert the {drill.diameter_mm:.1f} mm drill and set Z0 to the plate surface"
        writer = _Writer(title, mill, drill, message)
        _drill(writer, holes, plate, mill)
        name = f"{len(programs) + 1}_drill_{drill.diameter_mm:.1f}mm.nc"
        programs.append(Program(name, title, writer.finish(), holes=len(holes), tool=drill.id))

    for cutter, by_diameter in milled.values():
        is_outline = cutter.id == outline_tool.id
        scope = "large holes and outlines" if is_outline else "large holes"
        title = f"Mill with {cutter.diameter_mm:.1f} mm end mill: {scope}"
        message = f"Insert the {cutter.diameter_mm:.1f} mm end mill and set Z0 to the plate surface"
        writer = _Writer(title, mill, cutter, message)
        for diameter, holes in by_diameter.items():
            for x, y in _nearest_order(holes):
                _mill_hole(writer, x, y, diameter, plate, mill)
        if is_outline:
            for shape in layout.outlines:
                for path, with_tabs in tool_paths(shape, cutter.diameter_mm / 2):
                    _mill_outline(writer, path, with_tabs, plate, mill)
        name = f"{len(programs) + 1}_mill_{cutter.diameter_mm:.1f}mm.nc"
        programs.append(
            Program(
                name,
                title,
                writer.finish(),
                holes=sum(len(h) for h in by_diameter.values()),
                outlines=len(layout.outlines) if is_outline else 0,
                tool=cutter.id,
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
        f'<rect x="0" y="0" width="{plate.width_mm * scale}" height="{height * scale}" fill="#c9a06a" stroke="black"/>'
    ]
    for outer, cutouts in layout.outlines:
        xs, ys = [x for x, _ in outer], [y for _, y in outer]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if not cutouts and len(outer) == 4 and abs(abs(_area(outer)) - (x1 - x0) * (y1 - y0)) < 1e-6:
            parts.append(
                f'<rect x="{sx(x0)}" y="{sy(y1)}" width="{(x1 - x0) * scale}" height="{(y1 - y0) * scale}" '
                'fill="#2d6a4f" stroke="#d00000" stroke-width="1"/>'
            )
            continue
        rings = [outer, *cutouts]
        data = " ".join("M" + " L".join(f"{sx(x):.2f} {sy(y):.2f}" for x, y in ring) + " Z" for ring in rings)
        parts.append(f'<path d="{data}" fill-rule="evenodd" fill="#2d6a4f" stroke="#d00000" stroke-width="1"/>')
    for diameter, points in layout.holes.items():
        for x, y in points:
            radius = max(diameter * scale / 2, 1.2)
            parts.append(f'<circle cx="{sx(x)}" cy="{sy(y)}" r="{radius}" fill="{by_diameter[diameter]}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{plate.width_mm * scale}" height="{height * scale}" '
        f'viewBox="0 0 {plate.width_mm * scale} {height * scale}">' + "".join(parts) + "</svg>"
    )
