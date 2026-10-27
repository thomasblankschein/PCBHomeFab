// 3D simulation of the drill and mill programs of a job: the plate, the tool paths and a tool that moves along them.
// Drawn on a 2D canvas with the small camera of camera.js, so there is no library and no build step.

import { fileUrl } from "./api.js";
import { basisOf, isoView, makeCamera, orbit, pan, project, topView, zoom } from "./camera.js";
import { fill, h } from "./dom.js";
import { programInfo, programTitle } from "./format.js";
import { buildTimeline, parseGcode, positionAt } from "./gcode.js";
import { onLanguageChange, t } from "./i18n.js";

const RAPID_FEED = 1500;
const SPEEDS = [1, 10, 50, 200, 1000];
const COLORS = ["#2b7de9", "#e0742b", "#9b59b6", "#16a085", "#c0392b", "#7f8c8d"];
const TOOL_HEIGHT = 14;

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function clock(seconds) {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export async function loadPrograms(jobId, files) {
  return Promise.all(
    files.map(async (file, index) => {
      const response = await fetch(fileUrl(jobId, file.name));
      if (!response.ok) throw new Error(`${file.name}: ${response.status}`);
      const moves = parseGcode(await response.text());
      for (const m of moves) m.p = index;
      return { name: file.name, diameter: Number(programInfo(file.name)?.diameter ?? 1), color: COLORS[index % COLORS.length], moves };
    }),
  );
}

/** Builds the simulation inside `container` for programs from `loadPrograms`. */
export function createSimulation(container, programs, thickness, plateSize) {
  const PLATE = { width: plateSize.width_mm, height: plateSize.height_mm };
  const all = programs.flatMap((program) => program.moves);
  const state = {
    camera: makeCamera({ target: [PLATE.width / 2, PLATE.height / 2, 0], distance: 330 }),
    zScale: 3,
    rapids: true,
    selected: -1,
    playing: false,
    speed: 50,
    time: 0,
    moves: all,
    timeline: buildTimeline(all, RAPID_FEED),
    screen: new Float32Array(0),
    projected: false,
    last: 0,
  };
  state.time = state.timeline.total;

  const canvas = h("canvas", {
    tabindex: 0,
    role: "img",
    class: "sim-canvas",
    "data-i18n-attr": "aria-label:sim.aria",
    "aria-label": t("sim.aria"),
  });
  const status = h("p", { class: "sim-status muted" });
  const scrub = h("input", { type: "range", min: 0, max: 1000, value: 1000, "data-i18n-attr": "aria-label:sim.scrub", "aria-label": t("sim.scrub") });
  const clockText = h("span", { class: "sim-clock muted" });
  const playButton = h("button", { type: "button", class: "primary" });
  const programSelect = h("select", {}, [
    h("option", { value: -1, "data-i18n": "sim.all_programs" }, t("sim.all_programs")),
    programs.map((program, index) => h("option", { value: index }, programTitle(program.name))),
  ]);
  const speedSelect = h("select", {}, SPEEDS.map((s) => h("option", { value: s, selected: s === state.speed }, `${s}×`)));
  const zScale = h("input", { type: "range", min: 1, max: 10, step: 1, value: state.zScale });
  const rapids = h("input", { type: "checkbox", checked: true });
  const legend = h("ul", { class: "legend sim-legend" });
  const note = h("p", { class: "muted" });
  const button = (key, onclick) => h("button", { type: "button", "data-i18n": key, onclick }, t(key));
  const label = (key, control) => h("label", {}, h("span", { "data-i18n": key }, t(key)), control);

  fill(
    container,
    h("p", { class: "muted", "data-i18n": "sim.hint" }, t("sim.hint")),
    h("div", { class: "sim-stage" }, canvas),
    h("div", { class: "sim-transport" }, playButton, button("sim.restart", () => restart()), scrub, clockText),
    status,
    h(
      "div",
      { class: "grid sim-options" },
      label("sim.program", programSelect),
      label("sim.speed", speedSelect),
      label("sim.zscale", zScale),
      h("label", { class: "inline" }, rapids, " ", h("span", { "data-i18n": "sim.rapids" }, t("sim.rapids"))),
    ),
    h(
      "p",
      { class: "sim-views" },
      button("sim.view_iso", () => setCamera(isoView(state.camera))),
      " ",
      button("sim.view_top", () => setCamera(topView(state.camera))),
      " ",
      button("sim.zoom_in", () => setCamera(zoom(state.camera, 0.8))),
      " ",
      button("sim.zoom_out", () => setCamera(zoom(state.camera, 1.25))),
    ),
    legend,
    note,
  );

  // --- scene ------------------------------------------------------------------------------------------------

  function setCamera(camera) {
    state.camera = camera;
    state.projected = false;
    draw();
  }

  function select(index) {
    state.selected = index;
    state.moves = index < 0 ? all : all.filter((m) => m.p === index);
    state.timeline = buildTimeline(state.moves, RAPID_FEED);
    state.time = state.timeline.total;
    state.playing = false;
    state.projected = false;
    draw();
  }

  function restart() {
    state.time = 0;
    state.playing = true;
    state.last = performance.now();
    requestAnimationFrame(tick);
    draw();
  }

  function togglePlay() {
    if (state.playing) {
      state.playing = false;
    } else {
      if (state.time >= state.timeline.total) state.time = 0;
      state.playing = true;
      state.last = performance.now();
      requestAnimationFrame(tick);
    }
    draw();
  }

  function tick(now) {
    if (!state.playing) return;
    state.time = Math.min(state.timeline.total, state.time + ((now - state.last) / 1000) * state.speed);
    state.last = now;
    if (state.time >= state.timeline.total) state.playing = false;
    draw();
    if (state.playing) requestAnimationFrame(tick);
  }

  function size() {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(200, Math.round(canvas.clientWidth * ratio));
    const height = Math.round(width * 0.62);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
      state.projected = false;
    }
    return { width, height, ratio };
  }

  function projectMoves(basis, width, height) {
    const z = state.zScale;
    const screen = new Float32Array(state.moves.length * 4);
    state.moves.forEach((m, i) => {
      const a = project([m.x0, m.y0, m.z0 * z], basis, width, height);
      const b = project([m.x1, m.y1, m.z1 * z], basis, width, height);
      screen.set([a?.x ?? NaN, a?.y ?? NaN, b?.x ?? NaN, b?.y ?? NaN], i * 4);
    });
    state.screen = screen;
    state.projected = true;
  }

  function strokeMoves(ctx, from, to, test) {
    const { screen, moves } = state;
    ctx.beginPath();
    for (let i = from; i < to; i++) {
      if (!test(moves[i]) || Number.isNaN(screen[i * 4])) continue;
      ctx.moveTo(screen[i * 4], screen[i * 4 + 1]);
      ctx.lineTo(screen[i * 4 + 2], screen[i * 4 + 3]);
    }
    ctx.stroke();
  }

  function drawPlate(ctx, basis, width, height) {
    const depth = thickness * state.zScale;
    const corner = (x, y, z) => project([x * PLATE.width, y * PLATE.height, z], basis, width, height);
    const faces = [
      { points: [[0, 0, -depth], [1, 0, -depth], [1, 1, -depth], [0, 1, -depth]], shade: 0.35 },
      { points: [[0, 0, -depth], [1, 0, -depth], [1, 0, 0], [0, 0, 0]], shade: 0.2 },
      { points: [[1, 0, -depth], [1, 1, -depth], [1, 1, 0], [1, 0, 0]], shade: 0.25 },
      { points: [[1, 1, -depth], [0, 1, -depth], [0, 1, 0], [1, 1, 0]], shade: 0.2 },
      { points: [[0, 1, -depth], [0, 0, -depth], [0, 0, 0], [0, 1, 0]], shade: 0.25 },
      { points: [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], shade: 0 },
    ]
      .map((face) => ({ ...face, projected: face.points.map(([x, y, z]) => corner(x, y, z)) }))
      .filter((face) => face.projected.every(Boolean));
    for (const face of faces) face.depth = face.projected.reduce((sum, p) => sum + p.depth, 0) / 4;
    faces.sort((a, b) => b.depth - a.depth);
    ctx.lineWidth = 1;
    for (const face of faces) {
      ctx.beginPath();
      face.projected.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.closePath();
      ctx.fillStyle = css("--plate");
      ctx.fill();
      if (face.shade) {
        ctx.fillStyle = `rgba(0, 0, 0, ${face.shade})`;
        ctx.fill();
      }
      ctx.strokeStyle = css("--border");
      ctx.stroke();
    }
  }

  function drawAxes(ctx, basis, width, height) {
    const origin = project([0, 0, 0], basis, width, height);
    if (!origin) return;
    ctx.lineWidth = 2;
    ctx.font = `${Math.round(width / 55)}px system-ui, sans-serif`;
    for (const [name, vector, color] of [["X", [20, 0, 0], "#d33"], ["Y", [0, 20, 0], "#2a2"], ["Z", [0, 0, 20], "#25d"]]) {
      const end = project(vector, basis, width, height);
      if (!end) continue;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(origin.x, origin.y);
      ctx.lineTo(end.x, end.y);
      ctx.stroke();
      ctx.fillText(name, end.x + 3, end.y - 3);
    }
  }

  function draw() {
    const { width, height, ratio } = size();
    const ctx = canvas.getContext("2d");
    const basis = basisOf(state.camera);
    if (!state.projected) projectMoves(basis, width, height);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = css("--surface");
    ctx.fillRect(0, 0, width, height);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";

    drawPlate(ctx, basis, width, height);
    drawAxes(ctx, basis, width, height);

    const { done, point } = positionAt(state.moves, state.timeline, state.time);
    const total = state.moves.length;
    const reference = project(state.camera.target, basis, width, height);
    const mmToPx = reference ? reference.scale : 1;

    // material that is cut away: the width of the tool along every finished cut below the surface
    for (const [index, program] of programs.entries()) {
      ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
      ctx.lineWidth = Math.max(1.5 * ratio, program.diameter * mmToPx);
      strokeMoves(ctx, 0, done, (m) => m.p === index && m.kind === "cut" && m.z0 <= 0 && m.z1 <= 0);
    }
    // the cuts still to come, faint, and the finished ones
    ctx.lineWidth = Math.max(1, ratio);
    for (const [index, program] of programs.entries()) {
      ctx.strokeStyle = `${program.color}55`;
      strokeMoves(ctx, done, total, (m) => m.p === index && m.kind === "cut");
      ctx.strokeStyle = program.color;
      ctx.lineWidth = Math.max(1.5, 1.5 * ratio);
      strokeMoves(ctx, 0, done, (m) => m.p === index && m.kind === "cut");
      ctx.lineWidth = Math.max(1, ratio);
    }
    if (state.rapids) {
      ctx.strokeStyle = css("--muted");
      ctx.setLineDash([4 * ratio, 4 * ratio]);
      ctx.lineWidth = Math.max(1, ratio);
      strokeMoves(ctx, 0, done, (m) => m.kind === "rapid");
      ctx.setLineDash([]);
    }

    // the tool
    const index = done < total ? state.moves[done].p : (state.moves[total - 1]?.p ?? 0);
    const tool = programs[index];
    const tip = project([point[0], point[1], point[2] * state.zScale], basis, width, height);
    const top = project([point[0], point[1], point[2] * state.zScale + TOOL_HEIGHT], basis, width, height);
    if (tool && tip && top) {
      ctx.strokeStyle = css("--text");
      ctx.globalAlpha = 0.75;
      ctx.lineWidth = Math.max(2 * ratio, tool.diameter * tip.scale);
      ctx.lineCap = "butt";
      ctx.beginPath();
      ctx.moveTo(tip.x, tip.y);
      ctx.lineTo(top.x, top.y);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillStyle = tool.color;
      ctx.beginPath();
      ctx.arc(tip.x, tip.y, Math.max(3 * ratio, (tool.diameter * tip.scale) / 2), 0, 2 * Math.PI);
      ctx.fill();
    }

    renderTexts(point, tool);
  }

  function renderTexts(point, tool) {
    const total = state.timeline.total;
    scrub.value = total > 0 ? Math.round((state.time / total) * 1000) : 1000;
    clockText.textContent = `${clock(state.time)} / ${clock(total)}`;
    status.textContent = `${tool ? programTitle(tool.name) : ""} - ${t("sim.position", { x: point[0].toFixed(1), y: point[1].toFixed(1), z: point[2].toFixed(2) })}`;
    note.textContent = t("sim.note", { rapid: RAPID_FEED });
    const key = state.playing ? "sim.pause" : "sim.play";
    playButton.dataset.i18n = key;
    playButton.textContent = t(key);
  }

  function renderLegend() {
    fill(
      legend,
      programs.map((program) =>
        h("li", {}, h("span", { class: "chip", "data-color": program.color }), programTitle(program.name)),
      ),
    );
    for (const chip of legend.querySelectorAll(".chip")) chip.style.background = chip.dataset.color;
    [...programSelect.options].slice(1).forEach((option, index) => (option.textContent = programTitle(programs[index].name)));
  }

  // --- input ------------------------------------------------------------------------------------------------

  let drag = null;
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 && event.button !== 1) return;
    event.preventDefault();
    canvas.focus();
    drag = { x: event.clientX, y: event.clientY, pan: event.button === 1 };
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    state.camera = drag.pan
      ? pan(state.camera, dx * (canvas.height / canvas.clientHeight), dy * (canvas.height / canvas.clientHeight), canvas.height)
      : orbit(state.camera, -dx * 0.008, dy * 0.008);
    drag = { ...drag, x: event.clientX, y: event.clientY };
    state.projected = false;
    draw();
  });
  for (const type of ["pointerup", "pointercancel"]) canvas.addEventListener(type, () => (drag = null));
  canvas.addEventListener("auxclick", (event) => event.preventDefault());
  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      setCamera(zoom(state.camera, Math.exp(event.deltaY * 0.001)));
    },
    { passive: false },
  );
  canvas.addEventListener("keydown", (event) => {
    const turn = { ArrowLeft: [0.1, 0], ArrowRight: [-0.1, 0], ArrowUp: [0, -0.1], ArrowDown: [0, 0.1] }[event.key];
    if (turn) setCamera(orbit(state.camera, ...turn));
    else if (event.key === "+") setCamera(zoom(state.camera, 0.85));
    else if (event.key === "-") setCamera(zoom(state.camera, 1.18));
    else if (event.key === " ") togglePlay();
    else return;
    event.preventDefault();
  });

  playButton.addEventListener("click", togglePlay);
  scrub.addEventListener("input", () => {
    state.playing = false;
    state.time = (Number(scrub.value) / 1000) * state.timeline.total;
    draw();
  });
  programSelect.addEventListener("change", () => select(Number(programSelect.value)));
  speedSelect.addEventListener("change", () => (state.speed = Number(speedSelect.value)));
  zScale.addEventListener("input", () => {
    state.zScale = Number(zScale.value);
    state.projected = false;
    draw();
  });
  rapids.addEventListener("change", () => {
    state.rapids = rapids.checked;
    draw();
  });
  new ResizeObserver(() => draw()).observe(canvas);
  onLanguageChange(() => {
    renderLegend();
    draw();
  });

  renderLegend();
  draw();
}
