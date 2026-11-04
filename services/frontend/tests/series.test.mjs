import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { maxSteps, planSeries, stripLeft, stripWidth } from "../site/js/series.js";

const M3 = { lift_height_mm: 6, lift_speed_mms: 3, retract_speed_mms: 4 };
const contract = (name) => JSON.parse(readFileSync(new URL(`../../../contracts/examples/${name}`, import.meta.url), "utf8"));

test("the plan equals the example of the contract (series.json of the service)", () => {
  const expected = contract("exposure-series.json");
  const plan = planSeries(60, 180, 5, M3);
  assert.equal(plan.unit, expected.unit_s);
  assert.equal(plan.layers, expected.layers);
  assert.equal(plan.printTime, expected.print_time_s);
  assert.deepEqual(plan.sections, expected.sections.map((s) => s.exposure_s));
  assert.deepEqual(
    plan.exposures.map((e) => [e.exposure, e.strips, e.duration, e.layers]),
    expected.exposures.map((e) => [e.exposure, e.sections, e.duration_s, e.layers]),
  );
});

test("every strip gets its time and the times round half up like the service", () => {
  for (const [shortest, longest, steps] of [[60, 180, 7], [50, 180, 4], [1, 200, 2], [10, 19, 10], [33, 97, 3]]) {
    const plan = planSeries(shortest, longest, steps, M3);
    assert.equal(plan.sections[0], longest);
    assert.equal(plan.sections.at(-1), shortest);
    plan.sections.forEach((total, i) => assert.equal(plan.exposures.slice(i).reduce((sum, e) => sum + e.duration, 0), total));
    assert.ok(plan.exposures.every((e) => Number.isInteger(e.layers) && e.layers >= 1));
  }
  assert.deepEqual(planSeries(50, 100, 5, M3).sections, [100, 87, 75, 62, 50]);
  assert.equal(planSeries(50, 180, 4, M3).unit, 1);
});

test("values that give no series name the reason", () => {
  assert.equal(planSeries(60, 60, 2, M3).error.key, "series.err_order");
  assert.equal(planSeries(60, 64, 6, M3).error.key, "series.err_span");
  assert.equal(planSeries(50, 251, 4, M3).error.key, "series.err_layers");
  assert.equal(planSeries(60.5, 180, 4, M3).error.key, "series.err_range");
  assert.equal(planSeries(60, 180, 11, M3).error.key, "series.err_range");
  const narrow = planSeries(60, 180, 5, M3, 75);
  assert.equal(narrow.error.key, "series.err_width");
  assert.equal(narrow.error.params.most, 4);
});

test("strips fill the panel between the margins", () => {
  assert.equal(maxSteps(160), 10);
  const width = stripWidth(160, 5);
  assert.ok(Math.abs(stripLeft(4, width) + width - (160 - 3)) < 1e-9);
});
