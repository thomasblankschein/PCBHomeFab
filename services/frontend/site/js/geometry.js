// Pure functions for the plate preview: no DOM, no network, so they can be tested with `node --test`.

/** Shape of a board (outer polygon and cutouts) relative to its lower left corner. */
export function boardShape(board) {
  if (board.contour) return board.contour;
  const w = board.width_mm;
  const h = board.height_mm;
  return {
    outer: [
      [0, 0],
      [w, 0],
      [w, h],
      [0, h],
    ],
    cutouts: [],
  };
}

/** Whether the board is a plain rectangle: no contour, or a four point contour along its box without cutouts. */
export function isRectangle(board) {
  if (!board.contour) return true;
  const { outer, cutouts, others = [] } = board.contour;
  if (cutouts.length > 0 || others.length > 0 || outer.length !== 4) return false;
  const eps = 1e-3;
  return outer.every(
    ([x, y]) =>
      (Math.abs(x) < eps || Math.abs(x - board.width_mm) < eps) && (Math.abs(y) < eps || Math.abs(y - board.height_mm) < eps),
  );
}

const move = (points, dx, dy) => points.map(([x, y]) => [x + dx, y + dy]);

/**
 * Boards as placed by a layout: shapes and holes in plate coordinates (mm, Y up).
 * `boardsById` maps the ids used in the layout to board info (board.json).
 */
export function placedBoards(layout, boardsById) {
  return layout.placements.map((placement) => {
    const board = boardsById[placement.board_id];
    const shape = boardShape(board);
    return {
      boardId: placement.board_id,
      name: board.name,
      x: placement.x_mm,
      y: placement.y_mm,
      width: board.width_mm,
      height: board.height_mm,
      outer: move(shape.outer, placement.x_mm, placement.y_mm),
      cutouts: shape.cutouts.map((cutout) => move(cutout, placement.x_mm, placement.y_mm)),
      // the other boards of a file that holds several: their outlines and cutouts, drawn with the first one
      extra: (shape.others ?? []).flatMap((part) => [part.outer, ...part.cutouts]).map((polygon) => move(polygon, placement.x_mm, placement.y_mm)),
      holes: board.holes.map((hole) => ({
        x: placement.x_mm + hole.x_mm,
        y: placement.y_mm + hole.y_mm,
        diameter: hole.diameter_mm,
      })),
    };
  });
}

/** SVG path data for polygons. `toX` and `toY` map plate millimetres to drawing units. */
export function polygonPath(polygons, toX = (x) => x, toY = (y) => y) {
  return polygons
    .map((points) => `M${points.map(([x, y]) => `${toX(x).toFixed(3)} ${toY(y).toFixed(3)}`).join(" L")} Z`)
    .join(" ");
}

/** Number of holes per diameter for rows `{id, count}` of boards (copies included), sorted by diameter. */
export function holeSummary(rows, boardsById) {
  const counts = new Map();
  for (const row of rows) {
    const board = boardsById[row.id];
    if (!board) continue;
    for (const hole of board.holes) {
      counts.set(hole.diameter_mm, (counts.get(hole.diameter_mm) ?? 0) + row.count);
    }
  }
  return [...counts.entries()].sort((a, b) => a[0] - b[0]);
}

/** Share of the plate covered by the boxes of the boards, 0 to 1. */
export function plateUsage(layout, boardsById) {
  const plate = layout.plate.width_mm * layout.plate.height_mm;
  const used = layout.placements.reduce((sum, p) => {
    const board = boardsById[p.board_id];
    return sum + board.width_mm * board.height_mm;
  }, 0);
  return plate > 0 ? used / plate : 0;
}

const PALETTE = ["#d9a400", "#0096c7", "#e5e5e5", "#e0006a", "#7a5cff", "#2a9d4b"];

/** Colour of a hole diameter: the same diameter always gets the same colour within one preview. */
export function holeColors(diameters) {
  return new Map(diameters.map((d, i) => [d, PALETTE[i % PALETTE.length]]));
}

/** Board ids for the preview request: unique and valid for the API (`^[A-Za-z0-9_-]{1,40}$`). */
export function previewId(index) {
  return `b${index}`;
}

/** Whether `x` is a usable count of copies. */
export function validCount(x, max) {
  return Number.isInteger(x) && x >= 1 && x <= max;
}
