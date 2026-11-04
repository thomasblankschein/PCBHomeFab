// The exposure series page: times and steps in, the plan of the strips and exposures shown, the .pm3 file out.

import { exposureSeriesBlob, getPanels, getProfiles } from "./api.js";
import { fill, h } from "./dom.js";
import { initI18n, onLanguageChange, t } from "./i18n.js";
import { MARGIN_MM, planSeries, stripLeft } from "./series.js";

const STORAGE_KEY = "pcbhomefab.series";
const SAVED_FIELDS = ["panel", "printer", "shortest_s", "longest_s", "steps"];

const form = document.getElementById("form");
const create = document.getElementById("create");
const stateLine = document.getElementById("state");
const planError = document.getElementById("plan-error");
const planBox = document.getElementById("plan");
const strips = document.getElementById("strips");

const state = { profiles: null, panels: [], creating: false, message: null };

const field = (name) => form.elements.namedItem(name);
const value = (name) => (field(name).type === "checkbox" ? field(name).checked : field(name).value);
const number = (name) => Number(value(name));

function saveFields() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(Object.fromEntries(SAVED_FIELDS.map((name) => [name, value(name)]))));
  } catch {
    // storage may be blocked, the page works without it
  }
}

function restoreFields() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    for (const name of SAVED_FIELDS) {
      const element = field(name);
      if (!(name in saved)) continue;
      if (element.tagName !== "SELECT" || [...element.options].some((o) => o.value === saved[name])) element.value = saved[name];
    }
  } catch {
    // ignore broken stored values
  }
}

const currentPanel = () => state.panels.find((panel) => panel.id === value("panel")) ?? state.panels[0];
const currentPrinter = () => state.profiles.printers[value("printer")];

function applyPrinter() {
  const printer = currentPrinter();
  field("frame_left_mm").value = printer.frame_left_mm;
  field("frame_bottom_mm").value = printer.frame_bottom_mm;
  field("mirror_x").checked = printer.mirror_x;
}

function duration(seconds) {
  const minutes = Math.floor(seconds / 60);
  return minutes ? t("series.time_ms", { m: minutes, s: seconds % 60 }) : t("series.time_s", { s: seconds });
}

const plan = () => planSeries(number("shortest_s"), number("longest_s"), number("steps"), currentPrinter(), currentPanel().width_mm);

function drawStrips(result, panel) {
  const longest = result.sections[0];
  strips.setAttribute("viewBox", `0 0 ${panel.width_mm} ${panel.height_mm}`);
  fill(
    strips,
    h("rect", { class: "copper", x: 0, y: 0, width: panel.width_mm, height: panel.height_mm }),
    result.sections.map((seconds, index) => {
      const x = stripLeft(index, result.width);
      const height = panel.height_mm - 2 * MARGIN_MM;
      return h(
        "g",
        {},
        h("rect", { class: "strip", x, y: MARGIN_MM, width: result.width, height, "fill-opacity": (0.25 + (0.75 * seconds) / longest).toFixed(2) }),
        h("text", { class: "strip-time", x: x + result.width / 2, y: MARGIN_MM + 7 }, t("series.seconds", { s: seconds })),
        h("text", { class: "strip-number", x: x + result.width / 2, y: panel.height_mm - MARGIN_MM - 3 }, index + 1),
      );
    }),
  );
}

function render() {
  if (!state.profiles) return;
  const panel = currentPanel();
  const result = plan();
  const failed = Boolean(result.error);
  planError.textContent = failed ? t(result.error.key, result.error.params) : "";
  planBox.hidden = failed;
  create.disabled = failed || state.creating;
  stateLine.textContent = state.message ? t(state.message.key, state.message.params) : "";
  stateLine.className = `state ${state.message?.kind ?? ""}`.trim();
  if (failed) return;
  drawStrips(result, panel);
  document.getElementById("plan-summary").textContent = t("series.summary", {
    layers: result.layers,
    unit: result.unit,
    time: duration(result.printTime),
  });
  fill(
    document.getElementById("exposures"),
    result.exposures.map((exposure) =>
      h(
        "tr",
        {},
        h("td", { class: "num" }, exposure.exposure),
        h("td", {}, exposure.strips === 1 ? "1" : `1–${exposure.strips}`),
        h("td", { class: "num" }, t("series.seconds", { s: exposure.duration })),
        h("td", { class: "num" }, exposure.layers),
      ),
    ),
  );
}

function save(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

async function createFile(event) {
  event.preventDefault();
  if (plan().error || state.creating) return;
  const printer = currentPrinter();
  const request = {
    panel: value("panel"),
    printer: value("printer"),
    shortest_s: number("shortest_s"),
    longest_s: number("longest_s"),
    steps: number("steps"),
  };
  // calibration values only when they differ from the profile, like the editor
  if (number("frame_left_mm") !== printer.frame_left_mm) request.frame_left_mm = number("frame_left_mm");
  if (number("frame_bottom_mm") !== printer.frame_bottom_mm) request.frame_bottom_mm = number("frame_bottom_mm");
  if (value("mirror_x") !== printer.mirror_x) request.mirror_x = value("mirror_x");
  state.creating = true;
  state.message = { key: "series.creating", params: {} };
  render();
  try {
    const name = `exposure-series-${request.shortest_s}-${request.longest_s}s-${request.steps}.pm3`;
    save(await exposureSeriesBlob(request), name);
    state.message = { key: "series.created", params: { name }, kind: "ok" };
  } catch (error) {
    state.message = { key: "series.failed", params: { message: error.message }, kind: "error" };
  } finally {
    state.creating = false;
    render();
  }
}

await initI18n();
onLanguageChange(render);
try {
  const [profiles, panels] = await Promise.all([getProfiles(), getPanels()]);
  state.profiles = profiles;
  state.panels = panels.panels;
  fill(field("panel"), state.panels.map((panel) => h("option", { value: panel.id }, panel.name ?? panel.id)));
  fill(field("printer"), Object.entries(profiles.printers).map(([id, printer]) => h("option", { value: id }, printer.name)));
  restoreFields();
  applyPrinter();
  form.addEventListener("input", (event) => {
    if (event.target.name === "printer") applyPrinter();
    state.message = null;
    saveFields();
    render();
  });
  form.addEventListener("submit", createFile);
  document.getElementById("series").hidden = false;
  render();
} catch (error) {
  document.getElementById("load-error").textContent = t("editor.load_failed", { message: error.message });
}
