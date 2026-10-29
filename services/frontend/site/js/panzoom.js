// Zoom with the mouse wheel and pan with the held middle button for an SVG whose viewBox is set by the page.
//
// The page tells the base box (the whole drawing) with `setBase`; this module narrows the viewBox down to the part that
// is zoomed in. The arithmetic is plain functions on {scale, cx, cy} (the centre of the shown part, in drawing units).

export const MAX_SCALE = 40;
const WHEEL_STEP = 1.0015; // zoom factor per wheel delta unit

const clamp = (value, low, high) => Math.min(Math.max(value, low), high);

/** The part of the base box that is shown. */
export function zoomedBox(base, view) {
  const w = base.w / view.scale;
  const h = base.h / view.scale;
  return { x: view.cx - w / 2, y: view.cy - h / 2, w, h };
}

/** Keep the shown part inside the base box. */
function keepInside(base, view) {
  const w = base.w / view.scale;
  const h = base.h / view.scale;
  return {
    scale: view.scale,
    cx: clamp(view.cx, base.x + w / 2, base.x + base.w - w / 2),
    cy: clamp(view.cy, base.y + h / 2, base.y + base.h - h / 2),
  };
}

export function resetView(base) {
  return { scale: 1, cx: base.x + base.w / 2, cy: base.y + base.h / 2 };
}

/** Zoom by `factor` so that the point (px, py) of the drawing stays where it is on the screen. */
export function zoomAt(base, view, factor, px, py) {
  const scale = clamp(view.scale * factor, 1, MAX_SCALE);
  const box = zoomedBox(base, view);
  const w = base.w / scale;
  const h = base.h / scale;
  const x = px - ((px - box.x) / box.w) * w;
  const y = py - ((py - box.y) / box.h) * h;
  return keepInside(base, { scale, cx: x + w / 2, cy: y + h / 2 });
}

/** Move the picture by (dx, dy) drawing units (the content follows the mouse). */
export function panBy(base, view, dx, dy) {
  return keepInside(base, { scale: view.scale, cx: view.cx - dx, cy: view.cy - dy });
}

/**
 * Wire up the events of `svg`. Returns `{ setBase(box), reset() }`; call `setBase({ x, y, w, h })` whenever the page sets
 * a new drawing size (the zoom starts again when the size changed).
 */
export function attachPanZoom(svg) {
  let base = { x: 0, y: 0, w: 1, h: 1 };
  let view = resetView(base);

  function apply() {
    const box = zoomedBox(base, view);
    svg.setAttribute("viewBox", `${box.x} ${box.y} ${box.w} ${box.h}`);
    svg.classList.toggle("zoomed", view.scale > 1);
  }

  /** Drawing units of a screen position. */
  function toDrawing(clientX, clientY) {
    const point = new DOMPoint(clientX, clientY).matrixTransform(svg.getScreenCTM().inverse());
    return [point.x, point.y];
  }

  svg.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const [px, py] = toDrawing(event.clientX, event.clientY);
      const unit = event.deltaMode === 1 ? 33 : event.deltaMode === 2 ? 400 : 1;
      view = zoomAt(base, view, WHEEL_STEP ** (-event.deltaY * unit), px, py);
      apply();
    },
    { passive: false },
  );

  let drag = null;
  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 1) return;
    event.preventDefault(); // no auto-scroll cursor of the browser
    svg.setPointerCapture(event.pointerId);
    drag = { x: event.clientX, y: event.clientY };
    svg.classList.add("panning");
  });
  svg.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const factor = svg.getScreenCTM().a; // screen pixels per drawing unit
    view = panBy(base, view, (event.clientX - drag.x) / factor, (event.clientY - drag.y) / factor);
    drag = { x: event.clientX, y: event.clientY };
    apply();
  });
  const stop = () => {
    drag = null;
    svg.classList.remove("panning");
  };
  svg.addEventListener("pointerup", stop);
  svg.addEventListener("pointercancel", stop);
  svg.addEventListener("auxclick", (event) => event.preventDefault());
  svg.addEventListener("dblclick", () => {
    view = resetView(base);
    apply();
  });

  return {
    setBase(box) {
      const same = box.x === base.x && box.y === base.y && box.w === base.w && box.h === base.h;
      base = box;
      view = same ? keepInside(base, view) : resetView(base);
      apply();
    },
    reset() {
      view = resetView(base);
      apply();
    },
  };
}
