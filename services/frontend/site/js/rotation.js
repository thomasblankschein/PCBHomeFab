// Rotation of the panel on the mill, worked out from the second positioning mark.
//
// With the lower left mark as X0 Y0 the upper right mark should be at (x, y) of the job. If the panel is turned, the mill
// reads another place (measuredX, measuredY). The angle of the line from X0 Y0 to the mark differs by the rotation; the
// control (Estlcam: "drehen") needs it with the opposite sign.

/** Rotation in degrees for the control, or null when a mark lies at X0 Y0 or a value is missing. */
export function rotationDegrees(nominal, measured) {
  const values = [nominal.x, nominal.y, measured.x, measured.y];
  if (!values.every(Number.isFinite)) return null;
  if ((nominal.x === 0 && nominal.y === 0) || (measured.x === 0 && measured.y === 0)) return null;
  const angle = (point) => (Math.atan2(point.x, point.y) * 180) / Math.PI;
  const turn = -(angle(measured) - angle(nominal));
  return Object.is(turn, -0) ? 0 : turn;
}

/** Difference of the distances from X0 Y0 (mm) and in percent of the nominal one: a sign of a wrong scale or a misread value. */
export function distanceDeviation(nominal, measured) {
  const d1 = Math.hypot(nominal.x, nominal.y);
  const d2 = Math.hypot(measured.x, measured.y);
  if (!Number.isFinite(d1) || !Number.isFinite(d2) || d1 === 0) return null;
  return { mm: d2 - d1, percent: (100 * (d2 - d1)) / d1 };
}
