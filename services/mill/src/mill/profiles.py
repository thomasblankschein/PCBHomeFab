"""Mill profile and plate. Profiles are plain data; values that depend on the physical setup are calibration values."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Plate:
    """Copper clad blank. Origin is its lower left corner."""

    width_mm: float = 160.0
    height_mm: float = 100.0
    thickness_mm: float = 1.5


@dataclass(frozen=True)
class MillProfile:
    """GRBL hobby mill."""

    name: str
    #: Highest spindle speed of the machine (S value); tools may not ask for more.
    max_spindle_rpm: int
    #: End mill (diameter in the tool library) that cuts the board outlines. Tools and cutting data: see ``tools.py``.
    outline_endmill_mm: float = 1.0
    safe_z_mm: float = 3.0
    spindle_spinup_s: float = 3.0
    drill_overshoot_mm: float = 0.4
    mill_overshoot_mm: float = 0.15
    tab_width_mm: float = 2.0
    tab_height_mm: float = 0.6
    tabs: bool = True
    #: How the plate is turned over after exposure: "x" mirrors X, "y" mirrors Y, "none" keeps it.
    flip: str = "x"
    #: Position of the plate's lower left corner in machine coordinates.
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0
    notes: list[str] = field(default_factory=list)


MILL_3018PRO = MillProfile(
    name="3018Pro (GRBL)",
    max_spindle_rpm=20000,
    outline_endmill_mm=1.0,
)

#: Profiles by the id used in the API.
MILLS: dict[str, MillProfile] = {"3018pro": MILL_3018PRO}
