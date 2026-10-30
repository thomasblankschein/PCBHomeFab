import assert from "node:assert/strict";
import test from "node:test";

import { distanceDeviation, rotationDegrees } from "../site/js/rotation.js";

test("the rotation equals the result of the spreadsheet Drehung_Estlcam.ods", () => {
  const turn = rotationDegrees({ x: 83.965, y: 72.885 }, { x: 83.93, y: 73.08 });
  assert.equal(turn.toFixed(4), "0.0876");
});

test("no rotation when the mark is where it should be", () => {
  assert.equal(rotationDegrees({ x: 156, y: 96 }, { x: 156, y: 96 }), 0);
});

test("a mark whose angle is one degree smaller than it should be gives a rotation of 1 degree", () => {
  const a = (1 * Math.PI) / 180;
  const nominal = { x: 156, y: 96 };
  const r = Math.hypot(nominal.x, nominal.y);
  const base = Math.atan2(nominal.x, nominal.y);
  const measured = { x: r * Math.sin(base - a), y: r * Math.cos(base - a) };
  assert.ok(Math.abs(rotationDegrees(nominal, measured) - 1) < 1e-9);
});

test("missing or impossible values give no rotation", () => {
  assert.equal(rotationDegrees({ x: 156, y: 96 }, { x: Number.NaN, y: 96 }), null);
  assert.equal(rotationDegrees({ x: 156, y: 96 }, { x: 0, y: 0 }), null);
});

test("the deviation of the distance matches the spreadsheet", () => {
  const d = distanceDeviation({ x: 83.965, y: 72.885 }, { x: 83.93, y: 73.08 });
  assert.equal(d.mm.toFixed(3), "0.102");
  assert.equal(d.percent.toFixed(3), "0.091");
});
