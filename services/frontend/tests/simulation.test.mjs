import assert from "node:assert/strict";
import test from "node:test";

import { basisOf, makeCamera, orbit, pan, project, topView, zoom } from "../site/js/camera.js";
import { buildTimeline, parseGcode, positionAt } from "../site/js/gcode.js";

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} is not ${b}`);

const PROGRAM = `(Fraesen mit 1.0-mm-Fraeser)
G21 G90 G17 G94
G0 Z3
M3 S20000
G4 P3
(MSG, Fraeser einspannen)
G0 X10.000 Y20.000
G0 Z0.500
G1 Z-0.400 F40
G1 X20.000 F150
G3 X20.000 Y20.000 I-5 J0
M5
M30
`;

test("moves are read with modal mode and feed, other lines do not move", () => {
  const moves = parseGcode(PROGRAM);
  assert.deepEqual(
    moves.slice(0, 5).map((m) => [m.kind, m.x1, m.y1, m.z1, m.feed]),
    [
      ["rapid", 0, 0, 3, 0],
      ["rapid", 10, 20, 3, 0],
      ["rapid", 10, 20, 0.5, 0],
      ["cut", 10, 20, -0.4, 40],
      ["cut", 20, 20, -0.4, 150],
    ],
  );
  assert.deepEqual([moves[1].x0, moves[1].y0, moves[1].z0], [0, 0, 3]);
});

test("a counter clockwise arc with the same start and end is a full circle", () => {
  const moves = parseGcode("G0 X20 Y20\nG3 X20 Y20 I-5 J0 F100\n").slice(1);
  assert.ok(moves.length >= 4);
  for (const m of moves) near(Math.hypot(m.x1 - 15, m.y1 - 20), 5, 0.02);
  const last = moves[moves.length - 1];
  assert.deepEqual([last.x1, last.y1], [20, 20]);
  // counter clockwise: the first step from (20, 20) goes up
  assert.ok(moves[0].y1 > 20);
});

test("a clockwise half circle starts downwards and ends where it should", () => {
  const moves = parseGcode("G0 X10 Y0\nG2 X-10 Y0 I-10 J0 F100\n").slice(1);
  assert.ok(moves[0].y1 < 0);
  const last = moves[moves.length - 1];
  assert.deepEqual([last.x1, last.y1], [-10, 0]);
});

test("arcs with a change of Z are helixes", () => {
  const moves = parseGcode("G0 X1 Y0\nG3 X1 Y0 Z-1 I-1 J0 F100\n").slice(1);
  const last = moves[moves.length - 1];
  near(last.z1, -1);
  assert.ok(moves.every((m, i) => i === 0 || m.z1 <= moves[i - 1].z1));
});

test("the timeline uses feed rates for cuts and the rapid rate for rapids", () => {
  const moves = parseGcode("G0 X150\nG1 X0 F150\n");
  const timeline = buildTimeline(moves, 1500);
  near(timeline.ends[0], 150 / 25);
  near(timeline.total, 150 / 25 + 150 / 2.5);
});

test("position at a time is interpolated inside a move", () => {
  const moves = parseGcode("G1 X10 F60\nG1 Y10 F60\n");
  const timeline = buildTimeline(moves);
  near(timeline.total, 20);
  let at = positionAt(moves, timeline, 5);
  assert.equal(at.done, 0);
  near(at.point[0], 5);
  at = positionAt(moves, timeline, 15);
  assert.equal(at.done, 1);
  assert.deepEqual([at.point[0], at.point[1]], [10, 5]);
  at = positionAt(moves, timeline, 99);
  assert.equal(at.done, 2);
  assert.deepEqual(at.point, [10, 10, 0]);
});

test("no moves, no position", () => {
  assert.deepEqual(positionAt([], buildTimeline([]), 3), { done: 0, point: [0, 0, 0] });
});

test("the camera shows its target in the middle, X to the right and Z up", () => {
  const camera = makeCamera({ target: [0, 0, 0], distance: 100, yaw: 0, pitch: 0.5 });
  const basis = basisOf(camera);
  const centre = project([0, 0, 0], basis, 800, 600);
  near(centre.x, 400);
  near(centre.y, 300);
  assert.ok(project([10, 0, 0], basis, 800, 600).x > 400);
  assert.ok(project([0, 0, 10], basis, 800, 600).y < 300);
  assert.ok(project([0, 10, 0], basis, 800, 600).y < 300, "farther away is higher on the screen when looking down");
});

test("points behind the camera are not drawn", () => {
  const camera = makeCamera({ target: [0, 0, 0], distance: 100, yaw: 0, pitch: 0 });
  assert.equal(project([0, -500, 0], basisOf(camera), 800, 600), null);
});

test("orbit keeps the pitch inside its limits and zoom its distance", () => {
  const camera = makeCamera();
  assert.ok(orbit(camera, 0, 10).pitch < Math.PI / 2);
  assert.ok(orbit(camera, 0, -10).pitch < 0.1);
  assert.equal(zoom(camera, 1e-6).distance, 30);
  assert.equal(zoom(camera, 1e6).distance, 2000);
  const top = topView(camera);
  assert.ok(Number.isFinite(project([0, 0, 0], basisOf(top), 800, 600).x));
});

test("panning moves the scene with the mouse and stays on the panel", () => {
  const camera = makeCamera({ target: [0, 0, 0], distance: 200, yaw: 0, pitch: 0.7 });
  const before = project([0, 0, 0], basisOf(camera), 800, 600);
  const moved = pan(camera, 40, 0, 600);
  assert.equal(moved.target[2], 0);
  const after = project([0, 0, 0], basisOf(moved), 800, 600);
  near(after.x - before.x, 40, 0.5);
  near(after.y, before.y, 0.5);
  const down = project([0, 0, 0], basisOf(pan(camera, 0, 30, 600)), 800, 600);
  assert.ok(down.y > before.y, "dragging down moves the scene down");
});
