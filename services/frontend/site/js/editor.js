// The editor page: choose Gerber ZIPs, set copies and spacing, see the plate, create the job.

import { ApiError, createJob, getBoardInfo, getPlates, getProfiles, getTools, previewLayout } from "./api.js";
import { fill, h } from "./dom.js";
import { attachPanZoom } from "./panzoom.js";
import { mm } from "./format.js";
import { initI18n, onLanguageChange, t } from "./i18n.js";
import { copperPaths, holeColors, holeSummary, isRectangle, missingDrills, placedBoards, plateUsage, polygonPath, previewId, suggestDrill, validCount } from "./geometry.js";

const STORAGE_KEY = "pcbhomefab.settings";
const SAVED_FIELDS = ["plate", "marks", "mark_labels", "printer", "mill", "holes", "gap_mm", "margin_mm", "flip", "thickness_mm", "tabs", "exposure", "mill_gcode"];

const form = document.getElementById("settings");
const rowsBody = document.getElementById("rows");
const emptyHint = document.getElementById("empty");
const fileInput = document.getElementById("files");
const dropZone = document.getElementById("drop");
const plate = document.getElementById("plate");
const plateHint = document.getElementById("plate-hint");
const plateZoom = attachPanZoom(plate);
const summary = document.getElementById("summary");
const layoutError = document.getElementById("layout-error");
const submit = document.getElementById("submit");
const submitError = document.getElementById("submit-error");

const state = { profiles: null, plates: [], drills: [], missing: [], drillMap: {}, rows: [], nextKey: 1, layout: null, layoutError: "", creating: false, view: "top" };
// A row error or the layout error is a message of the server (text) or one of ours ({ key, params }).
const messageText = (message) => (typeof message === "string" ? message : message ? t(message.key, message.params) : "");
let previewTimer = 0;
let previewSequence = 0;
let previewAbort = null;

// --- settings ---------------------------------------------------------------------------------------------

function field(name) {
  return form.elements.namedItem(name);
}

function value(name) {
  const element = field(name);
  return element.type === "checkbox" ? element.checked : element.value;
}

function number(name) {
  return Number.parseFloat(value(name));
}

function saveSettings() {
  try {
    const saved = Object.fromEntries(SAVED_FIELDS.map((name) => [name, value(name)]));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
  } catch {
    // storage may be blocked, the page works without it
  }
}

function restoreSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    for (const name of SAVED_FIELDS) {
      if (!(name in saved)) continue;
      const element = field(name);
      if (element.type === "checkbox") element.checked = Boolean(saved[name]);
      else if (element.tagName !== "SELECT" || [...element.options].some((o) => o.value === saved[name])) {
        element.value = saved[name];
      }
    }
  } catch {
    // ignore broken stored values
  }
}

/** The plate size chosen in the settings (the first one while the list is still empty). */
function currentPlate() {
  return state.plates.find((plate) => plate.id === value("plate")) ?? state.plates[0] ?? { width_mm: 160, height_mm: 100 };
}

// Positioning marks sit in the margin of the plate; the jobs service refuses a smaller margin.
const MARKS_MIN_MARGIN_MM = 4.5;

function marksNeedMargin() {
  return value("marks") && !(number("margin_mm") >= MARKS_MIN_MARGIN_MM);
}

function applyPrinter() {
  const printer = state.profiles.printers[value("printer")];
  field("exposure_s").value = printer.default_exposure_s;
  field("frame_left_mm").value = printer.frame_left_mm;
  field("frame_bottom_mm").value = printer.frame_bottom_mm;
  field("mirror_x").checked = printer.mirror_x;
}

function applyMill() {
  const mill = state.profiles.mills[value("mill")];
  field("flip").value = mill.flip;
  field("tabs").checked = mill.tabs;
}

function fillSelect(select, entries) {
  fill(select, Object.entries(entries).map(([id, entry]) => h("option", { value: id }, entry.name)));
}

// --- boards -----------------------------------------------------------------------------------------------

function limits() {
  return state.profiles.limits;
}

function readyRows() {
  return state.rows.filter((row) => row.status === "ok");
}

function addFiles(files) {
  submitError.textContent = "";
  for (const file of files) {
    const row = { key: state.nextKey++, file, status: "reading", info: null, error: "", count: 1 };
    if (!/\.(zip|kicad_pcb)$/i.test(file.name)) {
      Object.assign(row, { status: "error", error: { key: "boards.only_zip" } });
    } else if (file.size > limits().max_upload_mb * 1024 * 1024) {
      Object.assign(row, { status: "error", error: { key: "boards.too_large", params: { mb: limits().max_upload_mb } } });
    } else if (state.rows.length >= limits().max_files) {
      Object.assign(row, { status: "error", error: { key: "boards.files_limit", params: { max: limits().max_files } } });
    }
    state.rows.push(row);
    if (row.status === "reading") readBoard(row);
  }
  render();
}

async function readBoard(row) {
  try {
    row.info = await getBoardInfo(row.file);
    row.status = "ok";
  } catch (error) {
    row.status = "error";
    row.error = error.message;
  }
  render();
}

function move(row, delta) {
  const index = state.rows.indexOf(row);
  const target = index + delta;
  if (target < 0 || target >= state.rows.length) return;
  state.rows.splice(index, 1);
  state.rows.splice(target, 0, row);
  render();
}

function remove(row) {
  state.rows = state.rows.filter((r) => r !== row);
  render();
}

function describe(info) {
  const diameters = holeSummary([{ id: "x", count: 1 }], { x: info });
  const holes = diameters.length
    ? t("boards.holes", { count: info.holes.length, detail: diameters.map(([d, n]) => `${n}×${d}`).join(", ") })
    : t("boards.holes_none");
  const shape = t(isRectangle(info) ? "boards.shape_rectangle" : info.contour.cutouts.length ? "boards.shape_contour_cutouts" : "boards.shape_contour");
  return `${mm(info.width_mm)} × ${mm(info.height_mm)}, ${holes}, ${shape}`;
}

function renderRows() {
  emptyHint.hidden = state.rows.length > 0;
  fill(
    rowsBody,
    state.rows.map((row, index) => {
      const countId = `count-${row.key}`;
      return h(
        "tr",
        { class: row.status === "error" ? "row-error" : "" },
        h("td", { class: "num" }, index + 1),
        h(
          "td",
          {},
          h("strong", {}, row.file.name),
          h("div", { class: "muted" }, row.status === "reading" ? t("boards.reading") : row.status === "error" ? "" : describe(row.info)),
          row.error ? h("div", { class: "error", role: "alert" }, messageText(row.error)) : null,
        ),
        h(
          "td",
          {},
          row.status === "ok"
            ? [
                h("label", { class: "sr-only", for: countId }, t("boards.copies_of", { name: row.file.name })),
                h("input", {
                  id: countId,
                  type: "number",
                  min: 1,
                  max: limits().max_boards,
                  value: row.count,
                  class: "count",
                  oninput: (event) => {
                    row.count = Number.parseInt(event.target.value, 10);
                    event.target.setAttribute("aria-invalid", String(!validCount(row.count, limits().max_boards)));
                    onLayoutInputsChanged();
                  },
                }),
              ]
            : null,
        ),
        h(
          "td",
          { class: "actions" },
          h("button", { type: "button", class: "icon", title: t("boards.move_up"), "aria-label": t("boards.move_up_label", { name: row.file.name }), disabled: index === 0, onclick: () => move(row, -1) }, "↑"),
          h("button", { type: "button", class: "icon", title: t("boards.move_down"), "aria-label": t("boards.move_down_label", { name: row.file.name }), disabled: index === state.rows.length - 1, onclick: () => move(row, 1) }, "↓"),
          h("button", { type: "button", class: "icon", title: t("boards.remove"), "aria-label": t("boards.remove_label", { name: row.file.name }), onclick: () => remove(row) }, "✕"),
        ),
      );
    }),
  );
}

// --- plate preview ----------------------------------------------------------------------------------------

function previewRequest() {
  const rows = readyRows();
  if (!rows.length || rows.some((row) => !validCount(row.count, limits().max_boards))) return null;
  const gap = number("gap_mm");
  const margin = number("margin_mm");
  if (!(gap >= 0.5 && gap <= 20) || !(margin >= 0 && margin <= 20)) return null;
  return {
    plate: value("plate"),
    gap_mm: gap,
    margin_mm: margin,
    boards: rows.map((row, i) => ({ id: previewId(i), width_mm: row.info.width_mm, height_mm: row.info.height_mm, count: row.count })),
  };
}

function onLayoutInputsChanged() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshLayout, 250);
  renderSubmit();
}

async function refreshLayout() {
  const request = previewRequest();
  previewAbort?.abort();
  const sequence = ++previewSequence;
  if (!request) {
    state.layout = null;
    state.layoutError = readyRows().length ? { key: "plate.check_inputs" } : "";
    renderPlate();
    return;
  }
  previewAbort = new AbortController();
  try {
    const layout = await previewLayout(request, previewAbort.signal);
    if (sequence !== previewSequence) return;
    state.layout = layout;
    state.layoutError = marksNeedMargin() ? { key: "plate.marks_margin", params: { min: MARKS_MIN_MARGIN_MM } } : "";
  } catch (error) {
    if (error.name === "AbortError" || sequence !== previewSequence) return;
    state.layout = null;
    state.layoutError = error.message;
  }
  renderPlate();
}

function boardsById() {
  return Object.fromEntries(readyRows().map((row, i) => [previewId(i), { ...row.info, name: row.file.name.replace(/\.(zip|kicad_pcb)$/i, "") }]));
}

/** The tracks, pads and copper pours of a placed board, for the underside view. */
function copperShapes(board, toX, toY) {
  const { tracks, fills } = copperPaths(board.copper, board.x, board.y, toX, toY);
  return h(
    "g",
    { class: "copper" },
    h("path", { class: "fill", d: fills }),
    tracks.map((track) => h("path", { class: "track", d: track.d, "stroke-width": track.width })),
  );
}

function renderPlate() {
  const layout = state.layout;
  const width = layout?.plate.width_mm ?? currentPlate().width_mm;
  const height = layout?.plate.height_mm ?? currentPlate().height_mm;
  const underside = state.view === "bottom";
  plateZoom.setBase({ x: -2, y: -2, w: width + 4, h: height + 4 });
  plateHint.textContent = t(underside ? "plate.hint_bottom" : "plate.hint_top");
  for (const [view, id] of [["top", "view-top"], ["bottom", "view-bottom"]]) {
    document.getElementById(id).setAttribute("aria-pressed", String(state.view === view));
  }
  const parts = [h("rect", { class: "plate", x: 0, y: 0, width, height })];
  const rows = readyRows().map((row, i) => ({ id: previewId(i), count: row.count }));
  const byId = boardsById();
  const diameters = holeSummary(rows, byId);
  const colors = holeColors(diameters.map(([d]) => d));
  if (layout) {
    // the underside is the design view seen from the copper side: mirrored left to right
    const toX = underside ? (x) => width - x : (x) => x;
    const toY = (y) => height - y;
    for (const board of placedBoards(layout, byId)) {
      parts.push(
        h(
          "g",
          {},
          h("title", {}, t("plate.board_title", { name: board.name, width: mm(board.width), height: mm(board.height), x: mm(board.x), y: mm(board.y) })),
          h("path", { class: "board", "fill-rule": "evenodd", d: polygonPath([board.outer, ...board.cutouts, ...board.extra], toX, toY) }),
          underside && board.copper ? copperShapes(board, toX, toY) : null,
          board.holes.map((hole) =>
            h("circle", { class: "hole", cx: toX(hole.x), cy: toY(hole.y), r: Math.max(hole.diameter / 2, 0.35), fill: colors.get(hole.diameter) }),
          ),
        ),
      );
    }
  }
  fill(plate, parts);

  layoutError.textContent = messageText(state.layoutError);
  layoutError.hidden = !state.layoutError;
  const total = rows.reduce((sum, row) => sum + (validCount(row.count, limits().max_boards) ? row.count : 0), 0);
  fill(
    summary,
    layout
      ? [
          h("p", {}, t("plate.summary", { count: total, width, height, usage: Math.round(plateUsage(layout, byId) * 100) })),
          diameters.length
            ? h(
                "ul",
                { class: "holes" },
                diameters.map(([d, n]) => h("li", {}, h("span", { class: "chip", "data-color": colors.get(d) }), t("plate.hole_line", { count: n, diameter: d }))),
              )
            : null,
        ]
      : null,
  );
  for (const chip of summary.querySelectorAll(".chip")) chip.style.background = chip.dataset.color;
  state.missing = state.drills.length ? missingDrills(diameters, state.drills) : [];
  renderDrillMap();
  renderSubmit();
}

// --- drills for hole sizes the tool library does not have -------------------------------------------------

/** The hole sizes that need a drill chosen, while the mill output is on. */
function drillsToChoose() {
  return value("mill_gcode") ? state.missing : [];
}

function renderDrillMap() {
  const wanted = drillsToChoose();
  document.getElementById("drill-map").hidden = wanted.length === 0;
  fill(
    document.getElementById("drill-rows"),
    wanted.map(([diameter, count]) => {
      state.drillMap[diameter] ??= suggestDrill(diameter, state.drills);
      const select = h(
        "select",
        // "input" (not "change"): it fires first, so the form's own input handler redraws the rows with the new choice
        { oninput: () => (state.drillMap[diameter] = Number(select.value)) },
        state.drills.map((drill) => h("option", { value: drill, selected: drill === state.drillMap[diameter] }, `${drill} mm`)),
      );
      return h("label", {}, h("span", {}, t("drills.row", { diameter, count })), select);
    }),
  );
}

// --- creating the job -------------------------------------------------------------------------------------

function renderSubmit() {
  const rows = readyRows();
  const reading = state.rows.some((row) => row.status === "reading");
  const countsOk = rows.every((row) => validCount(row.count, limits().max_boards));
  const output = value("exposure") || value("mill_gcode");
  submit.disabled = marksNeedMargin() || state.creating || reading || !rows.length || !countsOk || !state.layout || !output || !form.checkValidity();
  submit.textContent = t(state.creating ? "settings.creating" : "settings.submit");
}

function jobFormData() {
  const data = new FormData();
  const rows = readyRows();
  for (const row of rows) {
    data.append("boards", row.file, row.file.name);
    data.append("counts", String(row.count));
  }
  const printer = state.profiles.printers[value("printer")];
  const entries = {
    plate: value("plate"),
    marks: value("marks"),
    mark_labels: value("mark_labels"),
    printer: value("printer"),
    mill: value("mill"),
    exposure: value("exposure"),
    mill_gcode: value("mill_gcode"),
    exposure_s: value("exposure_s"),
    holes: value("holes"),
    gap_mm: value("gap_mm"),
    margin_mm: value("margin_mm"),
    flip: value("flip"),
    thickness_mm: value("thickness_mm"),
    tabs: value("tabs"),
  };
  for (const [name, entry] of Object.entries(entries)) data.append(name, String(entry));
  // calibration values are only sent when they differ from the profile
  if (number("frame_left_mm") !== printer.frame_left_mm) data.append("frame_left_mm", value("frame_left_mm"));
  if (number("frame_bottom_mm") !== printer.frame_bottom_mm) data.append("frame_bottom_mm", value("frame_bottom_mm"));
  if (value("mirror_x") !== printer.mirror_x) data.append("mirror_x", String(value("mirror_x")));
  const chosen = Object.fromEntries(drillsToChoose().map(([diameter]) => [String(diameter), state.drillMap[diameter]]));
  if (Object.keys(chosen).length) data.append("drill_map", JSON.stringify(chosen));
  return data;
}

async function onSubmit(event) {
  event.preventDefault();
  submitError.textContent = "";
  state.creating = true;
  renderSubmit();
  try {
    const job = await createJob(jobFormData());
    window.location.assign(`/jobs/${encodeURIComponent(job.id)}`);
  } catch (error) {
    submitError.textContent = error instanceof ApiError ? error.message : t("settings.create_failed");
    state.creating = false;
    renderSubmit();
  }
}

// --- start ------------------------------------------------------------------------------------------------

function render() {
  renderRows();
  onLayoutInputsChanged();
  renderPlate();
}

function renderLimits() {
  const l = limits();
  document.getElementById("limits").textContent = t("boards.limits", {
    files: l.max_files,
    mb: l.max_upload_mb,
    boards: l.max_boards,
    count: Math.round(l.job_ttl_hours / 24),
  });
}

function wire() {
  fileInput.addEventListener("change", () => {
    addFiles([...fileInput.files]);
    fileInput.value = "";
  });
  for (const type of ["dragenter", "dragover"]) {
    dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      dropZone.classList.add("over");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      dropZone.classList.remove("over");
    });
  }
  dropZone.addEventListener("drop", (event) => addFiles([...event.dataTransfer.files]));
  field("printer").addEventListener("change", () => {
    applyPrinter();
    saveSettings();
  });
  field("mill").addEventListener("change", () => {
    applyMill();
    saveSettings();
  });
  form.addEventListener("input", () => {
    saveSettings();
    renderDrillMap();
    renderSubmit();
  });
  for (const name of ["plate", "marks", "gap_mm", "margin_mm"]) field(name).addEventListener("input", onLayoutInputsChanged);
  for (const view of ["top", "bottom"]) {
    document.getElementById(`view-${view}`).addEventListener("click", () => {
      state.view = view;
      plateZoom.reset(); // the underside is mirrored, the zoomed part would not match
      renderPlate();
    });
  }
  form.addEventListener("submit", onSubmit);
}

async function start() {
  await initI18n();
  try {
    let library;
    [state.profiles, { plates: state.plates }, library] = await Promise.all([getProfiles(), getPlates(), getTools()]);
    state.drills = library.tools.filter((tool) => tool.kind === "drill" && tool.enabled).map((tool) => tool.diameter_mm).sort((a, b) => a - b);
  } catch (error) {
    document.getElementById("load-error").textContent = t("editor.load_failed", { message: error.message });
    return;
  }
  fillSelect(field("plate"), Object.fromEntries(state.plates.map((plate) => [plate.id, plate])));
  fillSelect(field("printer"), state.profiles.printers);
  fillSelect(field("mill"), state.profiles.mills);
  applyPrinter();
  applyMill();
  restoreSettings();
  wire();
  renderLimits();
  onLanguageChange(() => {
    renderLimits();
    renderRows();
    renderPlate();
  });
  form.hidden = false;
  document.getElementById("editor").hidden = false;
  render();
}

start();
