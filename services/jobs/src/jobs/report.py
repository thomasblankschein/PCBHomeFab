"""The job description as a PDF: header data, pictures, tools with their programs and how long the mill works."""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Circle, Drawing, Rect
from reportlab.graphics.shapes import Path as DrawingPath
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .store import JobRecord

#: A job made before the panel size became a choice used this panel.
LEGACY_PANEL = {"width_mm": 160, "height_mm": 100}
PROGRAM_NAME = re.compile(r"(\d+)_(drill|mill)_([\d.]+)mm\.nc$")
#: The preview of ``mill`` draws this many units per mm.
PREVIEW_UNITS_PER_MM = 5.0
_FILL_EVEN_ODD = 1
_GREY = colors.HexColor("#cccccc")

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "title": "Job description",
        "job": "Job",
        "created": "Created",
        "boards": "Boards",
        "outputs": "Outputs",
        "output_exposure": "Exposure {seconds} s",
        "output_mill": "Drill and mill G-code",
        "drill_map": "Drill assignment",
        "marks": "Positioning marks",
        "marks_off": "none",
        "marks_on": "Lower left mark = X0 Y0, upper right mark at X {x}, Y {y} mm",
        "panel": "Panel",
        "panel_summary": "{size}, gap {gap}, margin {margin}, {thickness} thick",
        "mask": "Exposure mask",
        "mask_note": "The picture is the mask on the display of the printer, white is exposed.",
        "mill": "Drilling and milling",
        "mill_note": "The panel as it lies on the mill bed. The holes are coloured by diameter.",
        "hole_legend": "{diameter} mm, {count} holes",
        "tools": "Tools and programs",
        "step": "No.",
        "tool": "Tool",
        "file": "File",
        "holes": "Holes",
        "outlines": "Outlines",
        "time": "Time",
        "program_drill": "Drill {diameter} mm",
        "program_mill": "End mill {diameter} mm",
        "duration": "Production time",
        "drilling": "Drilling",
        "milling": "Milling",
        "total": "Total",
        "duration_note": (
            "Estimated from the moves and feed rates of the programs (rapid moves at 1500 mm/min). Not counted: "
            "exposure, changing tools, setting Z0 and aligning the panel; the machine accelerates too, so the real "
            "time is somewhat longer."
        ),
        "no_time": "No time estimate for this job.",
        "page": "Page",
    },
    "de": {
        "title": "Auftragsbeschreibung",
        "job": "Auftrag",
        "created": "Erstellt",
        "boards": "Platinen",
        "outputs": "Ausgaben",
        "output_exposure": "Belichtung {seconds} s",
        "output_mill": "Bohr- und Fräs-G-Code",
        "drill_map": "Bohrer-Zuordnung",
        "marks": "Positionsmarken",
        "marks_off": "keine",
        "marks_on": "Marke unten links = X0 Y0, Marke oben rechts bei X {x}, Y {y} mm",
        "panel": "Nutzen",
        "panel_summary": "{size}, Abstand {gap}, Rand {margin}, {thickness} dick",
        "mask": "Belichtungsmaske",
        "mask_note": "Das Bild ist die Maske auf dem Display des Druckers, Weiß wird belichtet.",
        "mill": "Bohren und Fräsen",
        "mill_note": "Der Nutzen, wie er auf dem Fräsbett liegt. Die Bohrungen sind nach Durchmesser eingefärbt.",
        "hole_legend": "{diameter} mm, {count} Bohrungen",
        "tools": "Werkzeuge und Programme",
        "step": "Nr.",
        "tool": "Werkzeug",
        "file": "Datei",
        "holes": "Bohrungen",
        "outlines": "Konturen",
        "time": "Dauer",
        "program_drill": "Bohrer {diameter} mm",
        "program_mill": "Fräser {diameter} mm",
        "duration": "Fertigungsdauer",
        "drilling": "Bohren",
        "milling": "Fräsen",
        "total": "Gesamt",
        "duration_note": (
            "Geschätzt aus den Bewegungen und Vorschüben der Programme (Eilgang mit 1500 mm/min). Nicht eingerechnet: "
            "Belichtung, Werkzeugwechsel, Z0 einstellen und den Nutzen ausrichten; die Maschine beschleunigt außerdem, "
            "die tatsächliche Zeit ist also etwas länger."
        ),
        "no_time": "Für diesen Auftrag gibt es keine Zeitschätzung.",
        "page": "Seite",
    },
}


class _Texts:
    def __init__(self, lang: str) -> None:
        self.lang = lang if lang in TEXTS else "en"
        self.texts = TEXTS[self.lang]

    def __call__(self, key: str, **values: Any) -> str:
        return self.texts[key].format(**{name: self.number(value) for name, value in values.items()})

    def number(self, value: Any) -> str:
        """Numbers the way the language writes them (decimal comma in German)."""
        text = f"{value:g}" if isinstance(value, float) else str(value)
        return text.replace(".", ",") if self.lang == "de" and isinstance(value, float | int) else text


def clock(seconds: float) -> str:
    """Time as minutes:seconds, with hours (hours:minutes:seconds) from 60 minutes on."""
    total = round(seconds)
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}:{total % 60:02d}"
    return f"{minutes // 60}:{minutes % 60:02d}:{total % 60:02d}"


def _mm(t: _Texts, value: float) -> str:
    return f"{t.number(round(value, 2))} mm"


class _SvgPicture(Flowable):  # type: ignore[misc]
    """The mill preview of ``mill`` (a few rectangles, circles and paths) drawn as vector graphics."""

    def __init__(self, svg: str, width: float) -> None:
        super().__init__()
        root = ET.fromstring(svg)
        view = [float(v) for v in root.attrib["viewBox"].split()]
        self.view_h = view[3]
        scale = width / view[2]
        self.width = width
        self.height = self.view_h * scale
        self.circles: list[tuple[str, float]] = []
        self.drawing = Drawing(self.width, self.height)
        self.group_scale = scale
        for element in root:
            self._add(element)

    @staticmethod
    def _style(shape: Any, element: ET.Element) -> None:
        fill = element.attrib.get("fill", "none")
        shape.fillColor = None if fill == "none" else colors.toColor(fill)
        stroke = element.attrib.get("stroke")
        shape.strokeColor = colors.toColor(stroke) if stroke else None
        shape.strokeWidth = float(element.attrib.get("stroke-width", 1)) if stroke else 0

    def _add(self, element: ET.Element) -> None:
        tag = element.tag.split("}")[-1]
        attrib = element.attrib
        s = self.group_scale
        if tag == "rect":
            x, y = float(attrib["x"]), float(attrib["y"])
            w, h = float(attrib["width"]), float(attrib["height"])
            shape: Any = Rect(x * s, (self.view_h - y - h) * s, w * s, h * s)
        elif tag == "circle":
            shape = Circle(float(attrib["cx"]) * s, (self.view_h - float(attrib["cy"])) * s, float(attrib["r"]) * s)
            self.circles.append((attrib["fill"], float(attrib["r"])))
        elif tag == "path":
            shape = DrawingPath(fillMode=_FILL_EVEN_ODD)
            for ring in re.findall(r"M([^M]*)", attrib["d"]):
                pairs = [pair.split() for pair in ring.replace("Z", "").split("L") if pair.strip()]
                points = [(float(x) * s, (self.view_h - float(y)) * s) for x, y in pairs]
                shape.moveTo(*points[0])
                for point in points[1:]:
                    shape.lineTo(*point)
                shape.closePath()
        else:
            return
        self._style(shape, element)
        shape.strokeWidth *= s if shape.strokeColor is not None else 0
        self.drawing.add(shape)

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:  # noqa: N803
        return self.width, self.height

    def draw(self) -> None:
        renderPDF.draw(self.drawing, self.canv, 0, 0)

    def hole_legend(self) -> list[tuple[str, float, int]]:
        """Colour, diameter in mm and number of the holes. The diameter follows from the radius of the circle."""
        counts = Counter(self.circles)
        entries = sorted(counts.items(), key=lambda item: item[0][1])
        return [(color, round(2 * radius / PREVIEW_UNITS_PER_MM, 2), count) for (color, radius), count in entries]


def _dot(color: str) -> Drawing:
    """A small round chip in the colour of a hole size, with an outline (the colour can be white)."""
    chip = Drawing(3 * mm, 3 * mm)
    chip.add(
        Circle(1.5 * mm, 1.5 * mm, 1.2 * mm, fillColor=colors.toColor(color), strokeColor=colors.black, strokeWidth=0.4)
    )
    return chip


def _read_programs(output: Path) -> list[dict[str, Any]]:
    path = output / "programs.json"
    if not path.is_file():
        return []
    try:
        programs = json.loads(path.read_text(encoding="utf-8")).get("programs", [])
    except (OSError, ValueError):
        return []
    return programs if isinstance(programs, list) else []


def _facts(t: _Texts, record: JobRecord) -> list[tuple[str, str]]:
    p = record.params
    panel = p.get("panel") or LEGACY_PANEL
    boards = ", ".join(
        f"{b['count']} × {b['name']} ({_mm(t, b['width_mm'])} × {_mm(t, b['height_mm'])})" for b in p.get("boards", [])
    )
    outputs = [
        t("output_exposure", seconds=p["exposure_s"]) if p.get("exposure") else None,
        t("output_mill") if p.get("mill_gcode") else None,
    ]
    facts = [(t("boards"), boards), (t("outputs"), ", ".join(o for o in outputs if o))]
    if p.get("drill_map"):
        assigned = ", ".join(f"{t.number(float(h))} → {t.number(float(d))} mm" for h, d in p["drill_map"].items())
        facts.append((t("drill_map"), assigned))
    marks = p.get("marks")
    second = (marks or {}).get("second_mm")
    facts.append(
        (t("marks"), t("marks_on", x=second["x_mm"], y=second["y_mm"]) if marks and second else t("marks_off"))
    )
    size = f"{t.number(panel['width_mm'])} × {t.number(panel['height_mm'])} mm"
    summary = t.texts["panel_summary"].format(
        size=size, gap=_mm(t, p["gap_mm"]), margin=_mm(t, p["margin_mm"]), thickness=_mm(t, p["thickness_mm"])
    )
    facts.append((t("panel"), summary))
    return facts


def _tool_rows(
    t: _Texts, base: ParagraphStyle, programs: list[dict[str, Any]]
) -> tuple[list[list[Any]], float, float, bool]:
    """Table rows for the programs, the drilling and the milling time, and whether every program has a time."""
    rows: list[list[Any]] = [
        [Paragraph(f"<b>{t(key)}</b>", base) for key in ("step", "tool", "file", "holes", "outlines", "time")]
    ]
    drilling = milling = 0.0
    timed = True
    for program in programs:
        name = PROGRAM_NAME.search(program["filename"])
        kind = name.group(2) if name else ""
        tool = (
            t(
                "program_drill" if kind == "drill" else "program_mill",
                diameter=name.group(3).replace(".", "," if t.lang == "de" else "."),
            )
            if name
            else program["title"]
        )
        seconds = program.get("estimated_s")
        if seconds is None:
            timed = False
        elif kind == "drill":
            drilling += seconds
        else:
            milling += seconds
        rows.append(
            [
                Paragraph(name.group(1) if name else "", base),
                Paragraph(tool, base),
                Paragraph(Path(program["filename"]).name, base),
                Paragraph(str(program["holes"]), base),
                Paragraph(str(program["outlines"]), base),
                Paragraph(clock(seconds) if seconds is not None else "–", base),
            ]
        )
    return rows, drilling, milling, timed


def build_report(record: JobRecord, output: Path, lang: str = "en") -> bytes:
    """The PDF for a finished job; ``output`` is the folder with the files of the job."""
    t = _Texts(lang)
    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=12.5)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    heading = ParagraphStyle(
        "heading", parent=base, fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=12, spaceAfter=5
    )
    title = ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=2)
    label = ParagraphStyle("label", parent=base, fontName="Helvetica-Bold")
    width = A4[0] - 30 * mm
    lines = TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, _GREY),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
    )

    story: list[Any] = [Paragraph(t("title"), title)]
    created = datetime.fromtimestamp(record.created, UTC).strftime("%d.%m.%Y" if t.lang == "de" else "%Y-%m-%d")
    story += [Paragraph(f"{t('job')} {record.id} · {t('created')} {created}", small), Spacer(1, 4 * mm)]
    facts = Table(
        [[Paragraph(key, label), Paragraph(value, base)] for key, value in _facts(t, record)],
        colWidths=[38 * mm, width - 38 * mm],
    )
    facts.setStyle(lines)
    story.append(facts)

    mask = output / "mask_preview.png"
    if mask.is_file():
        picture = Image(str(mask))
        picture.drawWidth, picture.drawHeight = width, width * picture.imageHeight / picture.imageWidth
        story.append(KeepTogether([Paragraph(t("mask"), heading), picture, Paragraph(t("mask_note"), small)]))

    svg_path = output / "mill_preview.svg"
    if svg_path.is_file():
        svg = _SvgPicture(svg_path.read_text(encoding="utf-8"), width)
        legend = [
            Table(
                [[_dot(color), Paragraph(t("hole_legend", diameter=diameter, count=count), small)]],
                colWidths=[5 * mm, 60 * mm],
                hAlign="LEFT",
                style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1)]),
            )
            for color, diameter, count in svg.hole_legend()
        ]
        story.append(
            KeepTogether([Paragraph(t("mill"), heading), svg, Spacer(1, 2), Paragraph(t("mill_note"), small), *legend])
        )

    programs = _read_programs(output)
    if programs:
        rows, drilling, milling, timed = _tool_rows(t, base, programs)
        columns = [10 * mm, 38 * mm, 50 * mm, 26 * mm, 22 * mm]
        table = Table(rows, colWidths=[*columns, width - sum(columns)], repeatRows=1)
        table.setStyle(lines)
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecef"))]))
        story.append(KeepTogether([Paragraph(t("tools"), heading), table]))
        if timed:
            times = Table(
                [
                    [Paragraph(t("drilling"), base), Paragraph(clock(drilling), base)],
                    [Paragraph(t("milling"), base), Paragraph(clock(milling), base)],
                    [Paragraph(f"<b>{t('total')}</b>", base), Paragraph(f"<b>{clock(drilling + milling)}</b>", base)],
                ],
                colWidths=[38 * mm, 26 * mm],
                hAlign="LEFT",
            )
            times.setStyle(
                TableStyle(
                    [
                        ("LINEABOVE", (0, 2), (-1, 2), 0.5, colors.black),
                        ("TOPPADDING", (0, 0), (-1, -1), 1),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            story.append(
                KeepTogether(
                    [Paragraph(t("duration"), heading), times, Spacer(1, 3), Paragraph(t("duration_note"), small)]
                )
            )
        else:
            story.append(KeepTogether([Paragraph(t("duration"), heading), Paragraph(t("no_time"), base)]))

    def footer(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(15 * mm, 9 * mm, f"PCBHomeFab · {record.id[:8]}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"{t('page')} {document.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=17 * mm,
        title=f"{t('title')} {record.id[:8]}",
        author="PCBHomeFab",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
