import assert from "node:assert/strict";
import test from "node:test";

import {
  boardShape,
  holeColors,
  isRectangle,
  holeSummary,
  placedBoards,
  plateUsage,
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
  plate: { width_mm: 160, height_mm: 100 },
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

test("placed boards move shapes and holes to plate coordinates", () => {
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

test("plate usage is the share of the boxes", () => {
  assert.equal(plateUsage(layout, boards), (10 * 26 + 20 * 20) / (160 * 100));
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
