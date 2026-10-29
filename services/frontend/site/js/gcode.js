// Reads the GRBL G-code of the mill service into moves and times them. Pure functions, no DOM: tested with `node --test`.
//
// Understood: G0 (rapid), G1 (linear), G2/G3 (arcs with I and J, also full circles and helixes), absolute millimetres,
// F (feed, modal). Everything else (spindle, dwell, comments, messages) does not move the tool and is skipped.

const WORD = /([A-Z])\s*(-?\d*\.?\d+)/g;
const TWO_PI = 2 * Math.PI;

/** A move: `{ kind: "rapid" | "cut", x0, y0, z0, x1, y1, z1, feed }`, feed in mm/min (0 for rapids). */
function move(kind, from, to, feed) {
  return { kind, x0: from[0], y0: from[1], z0: from[2], x1: to[0], y1: to[1], z1: to[2], feed };
}

function arcPoints(from, to, i, j, clockwise, tolerance) {
  const cx = from[0] + i;
  const cy = from[1] + j;
  const radius = Math.hypot(from[0] - cx, from[1] - cy);
  const start = Math.atan2(from[1] - cy, from[0] - cx);
  let sweep = Math.atan2(to[1] - cy, to[0] - cx) - start;
  // start equal to end is a full circle
  if (clockwise && sweep >= 0) sweep -= TWO_PI;
  if (!clockwise && sweep <= 0) sweep += TWO_PI;
  const step = radius > tolerance ? 2 * Math.acos(1 - tolerance / radius) : Math.PI / 2;
  const count = Math.min(360, Math.max(4, Math.ceil(Math.abs(sweep) / step)));
  const points = [];
  for (let k = 1; k < count; k++) {
    const angle = start + (sweep * k) / count;
    points.push([cx + radius * Math.cos(angle), cy + radius * Math.sin(angle), from[2] + ((to[2] - from[2]) * k) / count]);
  }
  points.push([...to]);
  return points;
}

export function parseGcode(text, { arcTolerance = 0.01 } = {}) {
  const moves = [];
  let mode = null;
  let feed = 0;
  let position = [0, 0, 0];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\([^)]*\)/g, "").replace(/;.*$/, "").toUpperCase();
    const target = [...position];
    let i = 0;
    let j = 0;
    let hasMove = false;
    for (const match of line.matchAll(WORD)) {
      const value = Number.parseFloat(match[2]);
      switch (match[1]) {
        case "G":
          if (Number.isInteger(value) && value >= 0 && value <= 3) mode = value;
          break;
        case "F":
          feed = value;
          break;
        case "X":
          target[0] = value;
          hasMove = true;
          break;
        case "Y":
          target[1] = value;
          hasMove = true;
          break;
        case "Z":
          target[2] = value;
          hasMove = true;
          break;
        case "I":
          i = value;
          break;
        case "J":
          j = value;
          break;
        default:
      }
    }
    if (!hasMove || mode === null) continue;
    if (mode === 0) {
      moves.push(move("rapid", position, target, 0));
    } else if (mode === 1) {
      moves.push(move("cut", position, target, feed));
    } else {
      let from = position;
      for (const point of arcPoints(position, target, i, j, mode === 2, arcTolerance)) {
        moves.push(move("cut", from, point, feed));
        from = point;
      }
    }
    position = target;
  }
  return moves;
}

const DEFAULT_FEED = 100;

/** Time (s) at which each move ends. Rapids run at `rapidFeed` mm/min, an assumption: GRBL uses `$110` and so on. */
export function buildTimeline(moves, rapidFeed = 1500) {
  const ends = new Float64Array(moves.length);
  let time = 0;
  moves.forEach((m, index) => {
    const length = Math.hypot(m.x1 - m.x0, m.y1 - m.y0, m.z1 - m.z0);
    time += length / ((m.kind === "rapid" ? rapidFeed : m.feed || DEFAULT_FEED) / 60);
    ends[index] = time;
  });
  return { ends, total: time };
}

/** Where the tool is at `time`: `done` moves are finished, `point` is the tool position. */
export function positionAt(moves, timeline, time) {
  const { ends } = timeline;
  if (!moves.length) return { done: 0, point: [0, 0, 0] };
  if (time >= timeline.total) {
    const last = moves[moves.length - 1];
    return { done: moves.length, point: [last.x1, last.y1, last.z1] };
  }
  let low = 0;
  let high = ends.length - 1;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (ends[mid] > time) high = mid;
    else low = mid + 1;
  }
  const m = moves[low];
  const begin = low === 0 ? 0 : ends[low - 1];
  const span = ends[low] - begin;
  const f = span > 0 ? Math.min(1, Math.max(0, (time - begin) / span)) : 1;
  return { done: low, point: [m.x0 + (m.x1 - m.x0) * f, m.y0 + (m.y1 - m.y0) * f, m.z0 + (m.z1 - m.z0) * f] };
}

/** Time as minutes:seconds, with hours (hours:minutes:seconds) from 60 minutes on. */
export function formatClock(seconds) {
  const total = Math.round(seconds);
  const pad = (value) => String(value).padStart(2, "0");
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}:${pad(total % 60)}`;
  return `${Math.floor(minutes / 60)}:${pad(minutes % 60)}:${pad(total % 60)}`;
}

/** The convex hull of points [[x, y], ...] as a list of corners, always going the same way round (Andrew's monotone chain). */
export function convexHull(points) {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (sorted.length < 3) return sorted;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const build = (list) => {
    const chain = [];
    for (const point of list) {
      while (chain.length >= 2 && cross(chain[chain.length - 2], chain[chain.length - 1], point) <= 0) chain.pop();
      chain.push(point);
    }
    chain.pop();
    return chain;
  };
  return [...build(sorted), ...build([...sorted].reverse())];
}
