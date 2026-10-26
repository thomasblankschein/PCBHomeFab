// The editor page: choose Gerber ZIPs, set copies and spacing, see the plate, create the job.

import { ApiError, createJob, getBoardInfo, getProfiles, previewLayout } from "./api.js";
import { fill, h } from "./dom.js";
import { mm } from "./format.js";
import { holeColors, holeSummary, isRectangle, placedBoards, plateUsage, polygonPath, previewId, validCount } from "./geometry.js";

const STORAGE_KEY = "pcbhomefab.settings";
const SAVED_FIELDS = ["printer", "mill", "holes", "gap_mm", "margin_mm", "flip", "thickness_mm", "tabs", "exposure", "mill_gcode"];

const form = document.getElementById("settings");
const rowsBody = document.getElementById("rows");
const emptyHint = document.getElementById("empty");
const fileInput = document.getElementById("files");
const dropZone = document.getElementById("drop");
const plate = document.getElementById("plate");
const summary = document.getElementById("summary");
const layoutError = document.getElementById("layout-error");
const submit = document.getElementById("submit");
const submitError = document.getElementById("submit-error");

const state = { profiles: null, rows: [], nextKey: 1, layout: null, layoutError: "", creating: false };
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
    if (!/\.zip$/i.test(file.name)) {
      Object.assign(row, { status: "error", error: "Only Gerber ZIP files are accepted." });
    } else if (file.size > limits().max_upload_mb * 1024 * 1024) {
      Object.assign(row, { status: "error", error: `The file is larger than ${limits().max_upload_mb} MB.` });
    } else if (state.rows.length >= limits().max_files) {
      Object.assign(row, { status: "error", error: `At most ${limits().max_files} files per job.` });
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
    ? `${info.holes.length} holes (${diameters.map(([d, n]) => `${n}×${d}`).join(", ")} mm)`
    : "no holes";
  const shape = isRectangle(info) ? "rectangle" : info.contour.cutouts.length ? "board contour with cutouts" : "board contour";
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
          h("div", { class: "muted" }, row.status === "reading" ? "Reading ..." : row.status === "error" ? "" : describe(row.info)),
          row.error ? h("div", { class: "error", role: "alert" }, row.error) : null,
        ),
        h(
          "td",
          {},
          row.status === "ok"
            ? [
                h("label", { class: "sr-only", for: countId }, `Copies of ${row.file.name}`),
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
          h("button", { type: "button", class: "icon", title: "Move up", "aria-label": `Move ${row.file.name} up`, disabled: index === 0, onclick: () => move(row, -1) }, "↑"),
          h("button", { type: "button", class: "icon", title: "Move down", "aria-label": `Move ${row.file.name} down`, disabled: index === state.rows.length - 1, onclick: () => move(row, 1) }, "↓"),
          h("button", { type: "button", class: "icon", title: "Remove", "aria-label": `Remove ${row.file.name}`, onclick: () => remove(row) }, "✕"),
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
    state.layoutError = readyRows().length ? "Check the copies, the gap and the margin." : "";
    renderPlate();
    return;
  }
  previewAbort = new AbortController();
  try {
    const layout = await previewLayout(request, previewAbort.signal);
    if (sequence !== previewSequence) return;
    state.layout = layout;
    state.layoutError = "";
  } catch (error) {
    if (error.name === "AbortError" || sequence !== previewSequence) return;
    state.layout = null;
    state.layoutError = error.message;
  }
  renderPlate();
}

function boardsById() {
  return Object.fromEntries(readyRows().map((row, i) => [previewId(i), { ...row.info, name: row.file.name.replace(/\.zip$/i, "") }]));
}

function renderPlate() {
  const layout = state.layout;
  const width = layout?.plate.width_mm ?? 160;
  const height = layout?.plate.height_mm ?? 100;
  plate.setAttribute("viewBox", `-2 -2 ${width + 4} ${height + 4}`);
  const parts = [h("rect", { class: "plate", x: 0, y: 0, width, height })];
  const rows = readyRows().map((row, i) => ({ id: previewId(i), count: row.count }));
  const byId = boardsById();
  const diameters = holeSummary(rows, byId);
  const colors = holeColors(diameters.map(([d]) => d));
  if (layout) {
    const toX = (x) => x;
    const toY = (y) => height - y;
    for (const board of placedBoards(layout, byId)) {
      parts.push(
        h(
          "g",
          {},
          h("title", {}, `${board.name}: ${mm(board.width)} × ${mm(board.height)} at ${mm(board.x)}, ${mm(board.y)}`),
          h("path", { class: "board", "fill-rule": "evenodd", d: polygonPath([board.outer, ...board.cutouts], toX, toY) }),
          board.holes.map((hole) =>
            h("circle", { class: "hole", cx: hole.x, cy: toY(hole.y), r: Math.max(hole.diameter / 2, 0.35), fill: colors.get(hole.diameter) }),
          ),
        ),
      );
    }
  }
  fill(plate, parts);

  layoutError.textContent = state.layoutError;
  layoutError.hidden = !state.layoutError;
  const total = rows.reduce((sum, row) => sum + (validCount(row.count, limits().max_boards) ? row.count : 0), 0);
  fill(
    summary,
    layout
      ? [
          h("p", {}, `${total} board${total === 1 ? "" : "s"} on a ${width} × ${height} mm plate, ${Math.round(plateUsage(layout, byId) * 100)} % of the area used.`),
          diameters.length
            ? h(
                "ul",
                { class: "holes" },
                diameters.map(([d, n]) => h("li", {}, h("span", { class: "chip", "data-color": colors.get(d) }), `${n} × ${d} mm`)),
              )
            : null,
        ]
      : null,
  );
  for (const chip of summary.querySelectorAll(".chip")) chip.style.background = chip.dataset.color;
  renderSubmit();
}

// --- creating the job -------------------------------------------------------------------------------------

function renderSubmit() {
  const rows = readyRows();
  const reading = state.rows.some((row) => row.status === "reading");
  const countsOk = rows.every((row) => validCount(row.count, limits().max_boards));
  const output = value("exposure") || value("mill_gcode");
  submit.disabled = state.creating || reading || !rows.length || !countsOk || !state.layout || !output || !form.checkValidity();
  submit.textContent = state.creating ? "Creating ..." : "Create job";
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
    submitError.textContent = error instanceof ApiError ? error.message : "Could not create the job.";
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
    renderSubmit();
  });
  for (const name of ["gap_mm", "margin_mm"]) field(name).addEventListener("input", onLayoutInputsChanged);
  form.addEventListener("submit", onSubmit);
}

async function start() {
  try {
    state.profiles = await getProfiles();
  } catch (error) {
    document.getElementById("load-error").textContent = `${error.message} Reload the page to try again.`;
    return;
  }
  fillSelect(field("printer"), state.profiles.printers);
  fillSelect(field("mill"), state.profiles.mills);
  applyPrinter();
  applyMill();
  restoreSettings();
  wire();
  document.getElementById("limits").textContent = `Up to ${limits().max_files} files of ${limits().max_upload_mb} MB and ${limits().max_boards} boards per job. Files are kept for ${Math.round(limits().job_ttl_hours / 24)} days.`;
  form.hidden = false;
  document.getElementById("editor").hidden = false;
  render();
}

start();
