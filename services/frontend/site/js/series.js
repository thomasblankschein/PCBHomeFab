// The plan of an exposure series, as the exposure service makes it (services/exposure/src/exposure/series.py): the page
// shows it while the values are typed. The service checks the values again and writes the file.
//
// The panel is divided into strips. Exposure k lights the strips 1 to k, so strip 1 gets the longest time. The printer
// takes the time of the file header for every layer, so a longer exposure is several equal layers of `unit` seconds.

export const MARGIN_MM = 3;
export const GAP_MM = 1.5;
export const MIN_STRIP_MM = 14;
export const MAX_LAYERS = 200;
const MAX_SECONDS = 3600;

const gcd = (a, b) => (b ? gcd(b, a % b) : a);

/** Width of one strip on a panel of `panelWidth` mm. */
export const stripWidth = (panelWidth, steps) => (panelWidth - 2 * MARGIN_MM - (steps - 1) * GAP_MM) / steps;

/** The most strips that are wide enough on a panel of `panelWidth` mm. */
export const maxSteps = (panelWidth) => Math.max(1, Math.floor((panelWidth - 2 * MARGIN_MM + GAP_MM) / (MIN_STRIP_MM + GAP_MM)));

/**
 * Times of the strips and the exposures, or `{ error: { key, params } }` for values that give no series.
 * `printer` needs `lift_height_mm`, `lift_speed_mms` and `retract_speed_mms`.
 */
export function planSeries(shortest, longest, steps, printer, panelWidth = 160) {
  const whole = (value, low, high) => Number.isInteger(value) && value >= low && value <= high;
  if (!whole(shortest, 1, MAX_SECONDS) || !whole(longest, 2, MAX_SECONDS) || !whole(steps, 2, 10)) return { error: { key: "series.err_range", params: {} } };
  if (longest <= shortest) return { error: { key: "series.err_order", params: {} } };
  if (longest - shortest < steps - 1) return { error: { key: "series.err_span", params: { steps, need: steps - 1 } } };
  const width = stripWidth(panelWidth, steps);
  if (width < MIN_STRIP_MM) {
    return { error: { key: "series.err_width", params: { steps, width: width.toFixed(1), most: maxSteps(panelWidth) } } };
  }
  const span = longest - shortest;
  const divisions = steps - 1;
  // round half up with integers only, like the service
  const sections = Array.from({ length: steps }, (_, i) => longest - Math.floor((2 * i * span + divisions) / (2 * divisions)));
  const durations = sections.map((time, i) => (i + 1 < steps ? time - sections[i + 1] : time));
  const unit = durations.reduce(gcd, 0);
  const layers = longest / unit;
  if (layers > MAX_LAYERS) return { error: { key: "series.err_layers", params: { layers, unit, max: MAX_LAYERS } } };
  const moves = printer.lift_height_mm / printer.lift_speed_mms + printer.lift_height_mm / printer.retract_speed_mms;
  return {
    sections,
    exposures: durations.map((duration, i) => ({ exposure: i + 1, strips: i + 1, duration, layers: duration / unit })),
    unit,
    layers,
    printTime: Math.round(layers * (unit + moves)),
    width,
  };
}

/** Left edge of strip `index` (0 first) seen from the copper side. */
export const stripLeft = (index, width) => MARGIN_MM + index * (width + GAP_MM);
