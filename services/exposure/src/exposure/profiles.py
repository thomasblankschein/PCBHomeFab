"""Printer profiles: resin printer used as UV mask.

Profiles are plain data. Values that depend on the physical setup (frame offsets, mirroring) are calibration
values and meant to be adjusted per user, not constants of the program.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrinterProfile:
    """Resin printer whose LCD is used as a UV mask."""

    name: str
    #: Printer name written into the slice file. Photon Workshop rejects unknown names.
    machine_name: str
    resolution_x: int
    resolution_y: int
    display_width_mm: float
    display_height_mm: float
    #: Distance of the plate's lower left corner from the lower left corner of the display (calibration).
    frame_left_mm: float = 0.0
    frame_bottom_mm: float = 0.0
    #: The image is mirrored in X because the copper side faces the LCD.
    mirror_x: bool = True
    default_exposure_s: float = 120.0
    #: Width of an exposed (white) frame along the outer edge of the whole display, even outside the plate.
    #: Photon Workshop needs a closed outer contour to slice the image as an object. 0 switches the frame off.
    border_mm: float = 1.0
    #: Lift/retract parameters written to the slice file.
    lift_height_mm: float = 6.0
    lift_speed_mms: float = 3.0
    retract_speed_mms: float = 4.0
    #: Values of the MACHINE table as Photon Workshop writes them (display width differs slightly).
    machine_properties: int = 7
    machine_display_width_mm: float = 163.92
    machine_display_height_mm: float = 102.4
    machine_z_mm: float = 180.0
    machine_background: int = 4150478593

    @property
    def pixel_mm(self) -> float:
        return self.display_width_mm / self.resolution_x


PHOTON_M3 = PrinterProfile(
    name="Anycubic Photon M3",
    machine_name="Anycubic Photon M3",
    resolution_x=4096,
    resolution_y=2560,
    display_width_mm=163.84,
    display_height_mm=102.4,
    frame_left_mm=1.8,
    frame_bottom_mm=0.8,
)


#: Profiles by the id used in the API.
PRINTERS: dict[str, PrinterProfile] = {"photon-m3": PHOTON_M3}
