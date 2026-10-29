import assert from "node:assert/strict";
import test from "node:test";

import {
  copperPaths,
  missingDrills,
  suggestDrill,
  boardShape,
  holeColors,
  isRectangle,
  holeSummary,
  placedBoards,
  panelUsage,
  polygonPath,
  previewId,
  validCount,
} from "../site/js/geometry.js";

const node = {
  name: "node",
  width_mm: 10,
  height_mm: 26,
  holes: [
    { x_mm: 2, y_mm: 3, diameter_mm: 0.8, plated: true },
    { x_mm: 8, y_mm: 3, diameter_mm: 1.0, plated: true },
  ],
};
const round = {
  name: "round",
  width_mm: 20,
  height_mm: 20,
  holes: [],
  contour: {
    outer: [
      [0, 0],
      [20, 0],
      [20, 20],
    ],
    cutouts: [
      [
        [5, 5],
        [6, 5],
        [6, 6],
      ],
    ],
  },
};
const layout = {
  panel: { width_mm: 160, height_mm: 100 },
  placements: [
    { board_id: "a", x_mm: 3, y_mm: 3, rotation_deg: 0 },
    { board_id: "b", x_mm: 20, y_mm: 3, rotation_deg: 0 },
  ],
};
const boards = { a: node, b: round };

test("a board without contour is its rectangle", () => {
  assert.deepEqual(boardShape(node).outer, [
    [0, 0],
    [10, 0],
    [10, 26],
    [0, 26],
  ]);
  assert.deepEqual(boardShape(node).cutouts, []);
});

test("a board with contour keeps it", () => {
  assert.equal(boardShape(round), round.contour);
});

test("placed boards move shapes and holes to panel coordinates", () => {
  const [first, second] = placedBoards(layout, boards);
  assert.deepEqual(first.outer[2], [13, 29]);
  assert.deepEqual(first.holes[0], { x: 5, y: 6, diameter: 0.8 });
  assert.deepEqual(second.outer[1], [40, 3]);
  assert.deepEqual(second.cutouts[0][0], [25, 8]);
  assert.equal(first.name, "node");
});

test("polygon path draws closed polygons with a mapping", () => {
  const path = polygonPath([[[0, 0], [2, 0], [2, 1]]], (x) => x * 10, (y) => 100 - y);
  assert.equal(path, "M0.000 100.000 L20.000 100.000 L20.000 99.000 Z");
  assert.equal(polygonPath([[[0, 0], [1, 1], [0, 1]], [[5, 5], [6, 5], [6, 6]]]).split("M").length, 3);
});

test("holes are counted per diameter with copies", () => {
  const summary = holeSummary([{ id: "a", count: 3 }, { id: "b", count: 2 }, { id: "missing", count: 1 }], boards);
  assert.deepEqual(summary, [
    [0.8, 3],
    [1, 3],
  ]);
});

test("panel usage is the share of the boxes", () => {
  assert.equal(panelUsage(layout, boards), (10 * 26 + 20 * 20) / (160 * 100));
});

test("hole colours are stable per diameter", () => {
  const colors = holeColors([0.8, 1.0, 1.2, 2.2, 3, 4, 5]);
  assert.equal(colors.size, 7);
  assert.equal(colors.get(0.8), colors.get(5)); // the palette repeats after six colours
  assert.notEqual(colors.get(0.8), colors.get(1.0));
});

test("preview ids and counts", () => {
  assert.match(previewId(12), /^[A-Za-z0-9_-]{1,40}$/);
  assert.ok(validCount(1, 200) && validCount(200, 200));
  assert.ok(!validCount(0, 200) && !validCount(201, 200) && !validCount(1.5, 200) && !validCount(NaN, 200));
});

test("rectangles are told from real contours", () => {
  const rect = { width_mm: 10, height_mm: 20, contour: { outer: [[0, 0], [10, 0], [10, 20], [0, 20]], cutouts: [] } };
  assert.ok(isRectangle(node));
  assert.ok(isRectangle(rect));
  assert.ok(!isRectangle(round));
  assert.ok(!isRectangle({ ...rect, contour: { ...rect.contour, cutouts: [[[1, 1], [2, 1], [2, 2]]] } }));
  assert.ok(!isRectangle({ ...rect, contour: { outer: [[0, 0], [10, 0], [10, 20], [5, 25]], cutouts: [] } }));
});

test("a file with several boards draws all of their outlines", () => {
  const two = {
    name: "two",
    width_mm: 50,
    height_mm: 20,
    holes: [],
    contour: {
      outer: [[0, 0], [20, 0], [20, 20], [0, 20]],
      cutouts: [],
      others: [{ outer: [[30, 0], [50, 0], [50, 20], [30, 20]], cutouts: [[[35, 5], [40, 5], [40, 10]]] }],
    },
  };
  assert.ok(!isRectangle(two));
  const [placed] = placedBoards({ panel: { width_mm: 160, height_mm: 100 }, placements: [{ board_id: "t", x_mm: 3, y_mm: 3, rotation_deg: 0 }] }, { t: two });
  assert.equal(placed.extra.length, 2);
  assert.deepEqual(placed.extra[0][0], [33, 3]);
});

test("hole sizes without a drill need a choice, large holes are milled", () => {
  const drills = [0.6, 0.8, 1.0, 1.2];
  const holes = [[0.6, 3], [0.7, 2], [0.95, 4], [1.0, 1], [1.2, 1], [1.3, 5], [3.2, 2], [0.4, 1]];
  assert.deepEqual(missingDrills(holes, drills), [[0.7, 2], [0.95, 4], [0.4, 1]]);
  assert.deepEqual(missingDrills([[0.605, 1], [1.21, 1]], drills), []); // within the tolerance
  assert.deepEqual(missingDrills(holes, []), []);
});

test("the suggested drill is the next larger one", () => {
  const drills = [0.6, 0.8, 1.0, 1.2];
  assert.equal(suggestDrill(0.7, drills), 0.8);
  assert.equal(suggestDrill(0.95, drills), 1.0);
  assert.equal(suggestDrill(0.4, drills), 0.6);
  assert.equal(suggestDrill(1.25, drills), 1.2); // nothing larger: the largest
});

test("copperPaths groups tracks by width and turns every filled shape the same way round", () => {
  const copper = {
    strokes: [[0, 0, 1, 0, 0.5], [1, 0, 1, 1, 0.5], [0, 2, 1, 2, 0.2]],
    discs: [[2, 2, 0.5]],
    polygons: [
      [[0, 0], [1, 0], [1, 1], [0, 1]],
      [[0, 0], [0, 1], [1, 1], [1, 0]],
    ],
  };
  const { tracks, fills } = copperPaths(copper, 10, 20);
  assert.deepEqual(tracks.map((track) => track.width).sort(), [0.2, 0.5]);
  assert.match(tracks.find((track) => track.width === 0.5).d, /^M10\.00 20\.00L11\.00 20\.00M11\.00 20\.00L11\.00 21\.00M12\.00 22\.00L12\.00 22\.00$/);
  const area = (path) => {
    const points = path.match(/-?\d+\.\d+ -?\d+\.\d+/g).map((p) => p.split(" ").map(Number));
    return points.reduce((sum, [x, y], i) => sum + (x * points[(i + 1) % points.length][1] - points[(i + 1) % points.length][0] * y), 0);
  };
  const [first, second] = fills.split("Z").filter(Boolean);
  assert.ok(area(first) * area(second) > 0);
  // mirrored drawing: the x of the first pad end goes from 10 to width - 10
  const mirrored = copperPaths(copper, 10, 20, (x) => 100 - x, (y) => y);
  assert.match(mirrored.tracks[0].d, /^M90\.00 /);
});

test("zoomAt keeps the point under the mouse and panBy stays inside the drawing", async () => {
  const { MAX_SCALE, panBy, resetView, zoomAt, zoomedBox } = await import("../site/js/panzoom.js");
  const base = { x: -2, y: -2, w: 164, h: 104 };
  let view = resetView(base);
  assert.deepEqual(zoomedBox(base, view), base);
  view = zoomAt(base, view, 4, 100, 50);
  const box = zoomedBox(base, view);
  assert.equal(box.w, 41);
  assert.ok(Math.abs((100 - box.x) / box.w - (100 - base.x) / base.w) < 1e-9); // same place on the screen
  assert.equal(zoomAt(base, view, 1e6, 100, 50).scale, MAX_SCALE);
  assert.equal(zoomAt(base, view, 1e-6, 100, 50).scale, 1);
  const panned = panBy(base, view, -1000, 1000); // far beyond the edge
  const edge = zoomedBox(base, panned);
  assert.ok(edge.x + edge.w <= base.x + base.w + 1e-9 && edge.y >= base.y - 1e-9);
  assert.deepEqual(zoomedBox(base, zoomAt(base, view, 1e-6, 0, 0)), base); // zoomed out completely: the whole drawing
});
