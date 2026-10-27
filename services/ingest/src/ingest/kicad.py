"""Reading a KiCad ``.kicad_pcb`` file directly: bottom copper, board outline and holes.

The file is parsed here (an S-expression reader, nothing of KiCad is needed) and the bottom copper is written as a small
Gerber file, so the rest of the pipeline sees the same thing as for an uploaded Gerber ZIP. All geometry is in the
coordinates of a KiCad Gerber export: X to the right, Y **up** (KiCad's own Y points down, it is negated here), top
view.

Supported on B.Cu: tracks and arcs, vias, pads (circle, rect, roundrect, oval, custom with polygon primitives), filled
zones, lines, arcs, circles, rectangles and polygons (also inside footprints) and stroke font text. Chamfered pad
corners
are drawn as plain corners. Not supported (the file is refused): trapezoid pads, bezier curves, routed slots, zones that
are not filled.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from gerbonara.newstroke import Newstroke

from .common import Problem
from .contour import MAX_ARC_ERROR_MM

Node = list[Any]
Point = tuple[float, float]
Transform = Callable[[float, float], Point]

MAX_NODES = 2_000_000
_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))')


def _problem(code: str, detail: str) -> Problem:
    return Problem(422, code, detail)


# -- S-expressions ---------------------------------------------------------------------------------------------------


def parse_sexp(text: str) -> Node:
    """Nested lists; the first item of a list is its name. Atoms and quoted strings are both ``str``."""
    stack: list[Node] = [[]]
    for count, match in enumerate(_TOKEN.finditer(text), start=1):
        if count > MAX_NODES:
            raise _problem("ingest.invalid_kicad", "The KiCad file is too large.")
        opening, closing, quoted, atom = match.groups()
        if opening:
            stack.append([])
        elif closing:
            if len(stack) < 2:
                raise _problem("ingest.invalid_kicad", "The KiCad file is not valid (unbalanced brackets).")
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else atom)
    if len(stack) != 1 or not stack[0] or not isinstance(stack[0][0], list):
        raise _problem("ingest.invalid_kicad", "The KiCad file is not valid (unbalanced brackets).")
    return stack[0][0]


def children(node: Node, name: str) -> list[Node]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == name]


def child(node: Node, name: str) -> Node | None:
    found = children(node, name)
    return found[0] if found else None


def number(node: Node | None, index: int = 1, default: float = 0.0) -> float:
    if node is None or len(node) <= index:
        return default
    try:
        return float(node[index])
    except ValueError as exc:
        raise _problem("ingest.invalid_kicad", f"Not a number in the KiCad file: {node[index]}") from exc


def point_of(node: Node | None) -> Point:
    return (number(node, 1), number(node, 2))


def has_flag(node: Node, name: str) -> bool:
    return any(
        c == name or (isinstance(c, list) and c and c[0] == name and (len(c) < 2 or c[1] != "no")) for c in node[1:]
    )


# -- geometry --------------------------------------------------------------------------------------------------------


def _rotation(angle_deg: float) -> Callable[[float, float], Point]:
    """KiCad's positive angle turns counterclockwise on screen, with Y pointing down."""
    cos, sin = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return lambda x, y: (x * cos + y * sin, -x * sin + y * cos)


def placed(origin: Point, angle_deg: float, parent: Transform | None = None) -> Transform:
    """The transform of something at ``origin`` turned by ``angle_deg`` inside ``parent`` (the board if None)."""
    rotate = _rotation(angle_deg)

    def transform(x: float, y: float) -> Point:
        rx, ry = rotate(x, y)
        point = (origin[0] + rx, origin[1] + ry)
        return parent(*point) if parent else point

    return transform


def identity(x: float, y: float) -> Point:
    return (x, y)


def arc_points(start: Point, mid: Point, end: Point) -> list[Point]:
    """Points along the arc from ``start`` over ``mid`` to ``end`` (at most MAX_ARC_ERROR_MM away from the arc)."""
    (x1, y1), (x2, y2), (x3, y3) = start, mid, end
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return [start, end]
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
    radius = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (start, mid, end))
    sweep = (a3 - a1) % (2 * math.pi)
    if (a2 - a1) % (2 * math.pi) > sweep:  # the middle point is on the other side: turn the other way
        sweep -= 2 * math.pi
    step = 2 * math.acos(max(0.0, 1 - MAX_ARC_ERROR_MM / radius)) if radius > MAX_ARC_ERROR_MM else math.pi / 4
    count = max(2, math.ceil(abs(sweep) / max(step, 1e-3)))
    points = [
        (ux + radius * math.cos(a1 + sweep * i / count), uy + radius * math.sin(a1 + sweep * i / count))
        for i in range(count + 1)
    ]
    points[0], points[-1] = start, end
    return points


def circle_points(center: Point, radius: float) -> list[Point]:
    step = 2 * math.acos(max(0.0, 1 - MAX_ARC_ERROR_MM / radius)) if radius > MAX_ARC_ERROR_MM else math.pi / 4
    count = max(8, math.ceil(2 * math.pi / max(step, 1e-3)))
    return [
        (center[0] + radius * math.cos(2 * math.pi * i / count), center[1] + radius * math.sin(2 * math.pi * i / count))
        for i in range(count)
    ]


def _pts(node: Node | None, transform: Transform) -> list[Point]:
    """The points of a ``(pts ...)`` node, ``(xy x y)`` and ``(arc (start) (mid) (end))`` items."""
    points: list[Point] = []
    for item in (node or [])[1:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "xy":
            points.append(transform(number(item, 1), number(item, 2)))
        elif item[0] == "arc":
            start, mid, end = (transform(*point_of(child(item, n))) for n in ("start", "mid", "end"))
            points += arc_points(start, mid, end)
    return points


# -- the drawing ------------------------------------------------------------------------------------------------------


class Drawing:
    """What goes on the bottom copper layer, and the outline and the holes. Coordinates already in Gerber frame."""

    def __init__(self) -> None:
        self.strokes: list[tuple[float, list[Point]]] = []
        self.regions: list[list[Point]] = []
        self.flashes: list[tuple[float, Point]] = []
        self.outline: list[list[Point]] = []
        self.holes: list[dict[str, Any]] = []

    @staticmethod
    def _g(point: Point) -> Point:
        return (point[0], -point[1])

    def stroke(self, width: float, points: list[Point]) -> None:
        self.strokes.append((max(width, 0.001), [self._g(p) for p in points]))

    def region(self, points: list[Point]) -> None:
        if len(points) >= 3:
            self.regions.append([self._g(p) for p in points])

    def flash(self, diameter: float, point: Point) -> None:
        self.flashes.append((diameter, self._g(point)))

    def edge(self, points: list[Point]) -> None:
        self.outline.append([self._g(p) for p in points])


def _on(node: Node, layer: str) -> bool:
    found = child(node, "layer")
    if found is not None:
        return len(found) > 1 and found[1] == layer
    layers = child(node, "layers")
    return layers is not None and layer in layers[1:]


def _graphic(drawing: Drawing, node: Node, transform: Transform, copper: bool, edge: bool) -> None:
    """A ``gr_*`` or ``fp_*`` shape (the prefix is already stripped) on B.Cu and/or Edge.Cuts."""
    kind = node[0].split("_", 1)[1]
    width = number(child(node, "width"), 1, 0.0)
    fill = child(node, "fill")
    filled = fill is not None and len(fill) > 1 and fill[1] in ("yes", "solid")
    if kind == "line":
        points = [transform(*point_of(child(node, "start"))), transform(*point_of(child(node, "end")))]
    elif kind == "arc":
        points = arc_points(*(transform(*point_of(child(node, n))) for n in ("start", "mid", "end")))
    elif kind == "circle":
        center, rim = point_of(child(node, "center")), point_of(child(node, "end"))
        radius = math.hypot(rim[0] - center[0], rim[1] - center[1])
        points = [transform(*p) for p in circle_points(center, radius)]
        if copper and filled:
            drawing.region(points)
        points.append(points[0])
    elif kind == "rect":
        (x1, y1), (x2, y2) = point_of(child(node, "start")), point_of(child(node, "end"))
        points = [transform(x1, y1), transform(x2, y1), transform(x2, y2), transform(x1, y2)]
        if copper and filled:
            drawing.region(points)
        points.append(points[0])
    elif kind == "poly":
        points = _pts(child(node, "pts"), transform)
        if copper and filled:
            drawing.region(points)
        if points:
            points.append(points[0])
    elif kind in ("curve", "bezier"):
        raise _problem("ingest.unsupported_kicad", "Bezier curves are not supported. Replace them by lines or arcs.")
    else:
        return
    if edge:
        drawing.edge(points)
    if copper and (not filled or width > 0) and len(points) >= 2:
        drawing.stroke(width or 0.001, points)


_FONT: Newstroke | None = None


def _text(drawing: Drawing, node: Node, transform: Transform, text: str) -> None:
    """Stroke font text. ``node`` has ``(at x y [angle])`` and ``(effects (font (size h w) (thickness t)) ...)``."""
    global _FONT
    effects = child(node, "effects")
    if effects is None or has_flag(effects, "hide"):
        return
    font = child(effects, "font")
    size = child(font, "size") if font else None
    height = number(size, 1, 1.0)
    width = number(size, 2, height)
    thickness = number(child(font, "thickness"), 1, 0.15) if font else 0.15
    justify = [str(j) for j in (child(effects, "justify") or [])[1:]]
    at = child(node, "at")
    origin, angle = point_of(at), number(at, 3, 0.0)
    if _FONT is None:
        _FONT = Newstroke.load()
    glyphs = [[(x, y) for x, y in stroke] for stroke in _FONT.render(text, size=height)]
    if not glyphs:
        return
    (min_x, min_y), (max_x, max_y) = _FONT.bounding_box(text, size=height)[:2]
    text_w = max_x - min_x
    shift_x = -text_w if "right" in justify else 0.0 if "left" in justify else -text_w / 2
    # the glyphs stand on y = 0 and reach up to y = -height (Y points down)
    shift_y = {"top": height, "bottom": 0.0}.get(next((j for j in justify if j in ("top", "bottom")), ""), height / 2)
    mirror = -1.0 if "mirror" in justify else 1.0
    place = placed(origin, angle, transform)
    for stroke in glyphs:
        points = [place(mirror * ((x + shift_x) * (width / height)), y + shift_y) for x, y in stroke]
        drawing.stroke(thickness, points)


def _pad_polygon(shape: str, w: float, h: float, ratio: float) -> list[Point]:
    hw, hh = w / 2, h / 2
    if shape == "rect":
        return [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    radius = min(hw, hh, ratio * min(w, h))
    points: list[Point] = []
    for cx, cy, start in (
        (hw - radius, -hh + radius, -90),
        (hw - radius, hh - radius, 0),
        (-hw + radius, hh - radius, 90),
        (-hw + radius, -hh + radius, 180),
    ):
        mid = start + 45
        arc = arc_points(
            (cx + radius * math.cos(math.radians(start)), cy + radius * math.sin(math.radians(start))),
            (cx + radius * math.cos(math.radians(mid)), cy + radius * math.sin(math.radians(mid))),
            (cx + radius * math.cos(math.radians(start + 90)), cy + radius * math.sin(math.radians(start + 90))),
        )
        points += arc
    return points


def _pad(drawing: Drawing, pad: Node, footprint: Transform) -> None:
    """Copper of a pad on B.Cu, and its hole."""
    kind, shape = pad[2], pad[3]
    at = child(pad, "at")
    position, angle = point_of(at), number(at, 3, 0.0)
    # the position is inside the footprint, the angle of a pad in a board file is already the total one
    transform = placed(footprint(*position), angle)
    size = child(pad, "size")
    w, h = number(size, 1), number(size, 2, number(size, 1))
    layers = child(pad, "layers") or []
    on_copper = any(layer in ("B.Cu", "*.Cu") or str(layer).endswith("&B.Cu") for layer in layers[1:])

    drill = child(pad, "drill")
    if drill is not None:
        values = [v for v in drill[1:] if isinstance(v, str)]
        if values and values[0] == "oval":
            if abs(float(values[1]) - float(values[2])) > 1e-6:
                raise _problem("ingest.slots_unsupported", "Routed slots in the drill files are not supported yet.")
            diameter = float(values[1])
        else:
            diameter = float(values[0]) if values else 0.0
        offset = point_of(child(drill, "offset")) if child(drill, "offset") else (0.0, 0.0)
        if diameter > 0:
            x, y = transform(*offset)
            drawing.holes.append({"x": x, "y": -y, "diameter_mm": round(diameter, 3), "plated": kind != "np_thru_hole"})

    if not on_copper or w <= 0 or h <= 0:
        return
    if kind == "np_thru_hole" and drill is not None and w <= diameter + 1e-6 and h <= diameter + 1e-6:
        return  # a mounting hole without a ring: KiCad plots no copper for it
    if shape == "circle":
        drawing.flash(w, transform(0, 0))
    elif shape == "oval":
        if abs(w - h) < 1e-9:
            drawing.flash(w, transform(0, 0))
        elif w > h:
            drawing.stroke(h, [transform(-(w - h) / 2, 0), transform((w - h) / 2, 0)])
        else:
            drawing.stroke(w, [transform(0, -(h - w) / 2), transform(0, (h - w) / 2)])
    elif shape in ("rect", "roundrect"):
        ratio = number(child(pad, "roundrect_rratio"), 1, 0.25) if shape == "roundrect" else 0.0
        drawing.region([transform(*p) for p in _pad_polygon("rect" if ratio <= 0 else "roundrect", w, h, ratio)])
    elif shape == "custom":
        options = child(pad, "options")
        anchor = (child(options, "anchor") or ["anchor", "circle"])[1] if options else "circle"
        if anchor == "rect":
            drawing.region([transform(*p) for p in _pad_polygon("rect", w, h, 0)])
        else:
            drawing.flash(w, transform(0, 0))
        for primitives in children(pad, "primitives"):
            for item in primitives[1:]:
                if isinstance(item, list) and item and str(item[0]).startswith("gr_"):
                    _graphic(drawing, [*item, ["layer", "B.Cu"]], transform, copper=True, edge=False)
    else:
        raise _problem("ingest.unsupported_kicad", f"Pad shape '{shape}' is not supported.")


def read_drawing(text: str) -> Drawing:
    root = parse_sexp(text)
    if not root or root[0] != "kicad_pcb":
        raise _problem("ingest.invalid_kicad", "The file is not a KiCad PCB file (.kicad_pcb).")
    drawing = Drawing()

    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        name = node[0]
        if name in ("segment", "arc") and _on(node, "B.Cu"):
            width = number(child(node, "width"), 1)
            if name == "segment":
                drawing.stroke(width, [point_of(child(node, "start")), point_of(child(node, "end"))])
            else:
                drawing.stroke(width, arc_points(*(point_of(child(node, n)) for n in ("start", "mid", "end"))))
        elif name == "via":
            layers = child(node, "layers") or []
            at, size, drill = (
                point_of(child(node, "at")),
                number(child(node, "size"), 1),
                number(child(node, "drill"), 1),
            )
            if "B.Cu" in layers[1:]:
                drawing.flash(size, at)
            if drill > 0:
                drawing.holes.append({"x": at[0], "y": -at[1], "diameter_mm": round(drill, 3), "plated": True})
        elif name.startswith("gr_") and name != "gr_text":
            _graphic(drawing, node, identity, copper=_on(node, "B.Cu"), edge=_on(node, "Edge.Cuts"))
        elif name in ("gr_text", "gr_text_box") and _on(node, "B.Cu") and len(node) > 1:
            _text(drawing, node, identity, str(node[1]))
        elif name == "zone" and "B.Cu" in (child(node, "layers") or child(node, "layer") or [])[1:]:
            _zone(drawing, node)
        elif name == "footprint":
            _footprint(drawing, node)
    return drawing


def _zone(drawing: Drawing, zone: Node) -> None:
    if child(zone, "keepout") is not None:
        return
    fill = child(zone, "fill")
    if fill is None or len(fill) < 2 or fill[1] != "yes":
        return  # an outline only, nothing is poured
    polygons = [p for p in children(zone, "filled_polygon") if _on(p, "B.Cu")]
    if not polygons:
        raise _problem(
            "ingest.zone_not_filled",
            "A copper zone on B.Cu is not filled. Fill all zones in KiCad (Edit > Fill all zones, key B) and save.",
        )
    for polygon in polygons:
        drawing.region(_pts(child(polygon, "pts"), identity))


def _footprint(drawing: Drawing, footprint: Node) -> None:
    at = child(footprint, "at")
    transform = placed(point_of(at), number(at, 3, 0.0))
    for item in footprint[1:]:
        if not isinstance(item, list) or not item:
            continue
        if item[0] == "pad" and len(item) > 3:
            _pad(drawing, item, transform)
        elif item[0].startswith("fp_") and item[0] != "fp_text":
            _graphic(drawing, item, transform, copper=_on(item, "B.Cu"), edge=_on(item, "Edge.Cuts"))
        elif item[0] == "fp_text" and _on(item, "B.Cu") and len(item) > 2:
            _text(drawing, item, transform, _expand(str(item[2]), footprint))


def _expand(text: str, footprint: Node) -> str:
    reference = next((p[2] for p in children(footprint, "property") if len(p) > 2 and p[1] == "Reference"), "")
    value = next((p[2] for p in children(footprint, "property") if len(p) > 2 and p[1] == "Value"), "")
    return text.replace("${REFERENCE}", str(reference)).replace("${VALUE}", str(value))


# -- the Gerber file -------------------------------------------------------------------------------------------------


def _coordinate(value: float) -> str:
    return str(round(value * 1_000_000))


def write_gerber(drawing: Drawing) -> bytes:
    """The bottom copper as an RS-274X file in millimetres (dark polarity only)."""
    widths = sorted({round(w, 4) for w, _ in drawing.strokes} | {round(d, 4) for d, _ in drawing.flashes})
    codes = {width: 10 + index for index, width in enumerate(widths)}
    lines = ["G04 PCBHomeFab: bottom copper read from a KiCad PCB file*", "%FSLAX46Y46*%", "%MOMM*%", "%LPD*%"]
    lines += [f"%ADD{code}C,{width:.4f}*%" for width, code in codes.items()]
    lines.append("G01*")

    def move(point: Point, op: str) -> str:
        return f"X{_coordinate(point[0])}Y{_coordinate(point[1])}D0{op}*"

    for width, points in drawing.strokes:
        lines.append(f"D{codes[round(width, 4)]}*")
        lines.append(move(points[0], "2"))
        lines += [move(point, "1") for point in points[1:]]
    for diameter, point in drawing.flashes:
        lines.append(f"D{codes[round(diameter, 4)]}*")
        lines.append(move(point, "3"))
    for points in drawing.regions:
        lines.append("G36*")
        lines.append(move(points[0], "2"))
        lines += [move(point, "1") for point in [*points[1:], points[0]]]
        lines.append("G37*")
    lines.append("M02*")
    return ("\n".join(lines) + "\n").encode()
