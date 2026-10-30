import { ApiError, archiveBlob, fileBlob, getJob, reportBlob } from "./api.js";
import { fill, h } from "./dom.js";
import { formatSize, mm, programTitle } from "./format.js";
import { currentLanguage, initI18n, onLanguageChange, t } from "./i18n.js";
import { distanceDeviation, rotationDegrees } from "./rotation.js";

const jobId = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() ?? "");
const state = document.getElementById("state");
const result = document.getElementById("result");

// What the page shows now, kept so that it can be drawn again when the language changes.
let shownState = { key: "job.loading", params: {}, kind: "" };
let shownJob = null;

function setState(key, params = {}, kind = "") {
  shownState = { key, params, kind };
  state.textContent = t(key, params);
  state.className = `state ${kind}`.trim();
}

// The files need the access token of the login, so a plain link or picture cannot reach them: they are fetched with the
// token and then shown or saved from a blob.
const blobUrls = new Map();

function blobUrl(job, name) {
  const key = `${job.id}/${name}`;
  if (!blobUrls.has(key)) blobUrls.set(key, fileBlob(job.id, name).then((blob) => URL.createObjectURL(blob)));
  return blobUrls.get(key);
}

function picture(job, name, attributes) {
  const image = h("img", attributes);
  blobUrl(job, name).then(
    (url) => {
      image.src = url;
    },
    () => blobUrls.delete(`${job.id}/${name}`),
  );
  return image;
}

function save(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** A link that fetches `getBlob()` with the login and runs `then(blob)`; a failure is shown at the top of the page. */
function fileLink(label, getBlob, then, attributes = {}) {
  return h(
    "a",
    {
      href: "#",
      ...attributes,
      onclick: async (event) => {
        event.preventDefault();
        try {
          then(await getBlob());
        } catch (error) {
          setState("job.download_failed", {}, "error");
          if (!(error instanceof ApiError)) throw error;
        }
      },
    },
    label,
  );
}

/** The PDF opens in a new tab. The tab is opened first (a popup after a wait would be blocked) and gets the file later. */
function reportLink(job) {
  return h(
    "a",
    {
      href: "#",
      onclick: async (event) => {
        event.preventDefault();
        const tab = window.open("", "_blank");
        try {
          const blob = await reportBlob(job.id, currentLanguage());
          if (tab) tab.location.href = URL.createObjectURL(blob);
          else save(blob, `pcbhomefab-${job.id.slice(0, 8)}.pdf`);
        } catch (error) {
          tab?.close();
          setState("job.download_failed", {}, "error");
          if (!(error instanceof ApiError)) throw error;
        }
      },
    },
    t("job.report_link"),
  );
}

function download(job, file, label, note) {
  const filename = file.name.split("/").pop();
  return h(
    "li",
    {},
    fileLink(label ?? file.name, () => fileBlob(job.id, file.name), (blob) => save(blob, filename)),
    h("span", { class: "muted" }, ` ${formatSize(file.size)}`),
    note ? h("div", { class: "muted" }, note) : null,
  );
}

// The panel is rarely square on the mill: the second mark is approached after X0 Y0 is set, the position the control shows is
// typed in (it starts with the position the mark should have) and the rotation for the control comes out.
function rotationPanel(second) {
  const field = (value, label) => {
    const input = h("input", { type: "number", step: "any", value, inputmode: "decimal", class: "coordinate" });
    return { input, label: h("label", { class: "inline" }, label, " ", input) };
  };
  const x = field(second.x_mm, "X");
  const y = field(second.y_mm, "Y");
  const command = h("code", { class: "rotation-command" });
  const detail = h("p", { class: "muted" });

  const update = () => {
    const nominal = { x: second.x_mm, y: second.y_mm };
    const measured = { x: x.input.valueAsNumber, y: y.input.valueAsNumber };
    const turn = rotationDegrees(nominal, measured);
    if (turn === null) {
      command.textContent = "";
      detail.textContent = t("job.rotation_invalid");
      return;
    }
    const language = currentLanguage();
    command.textContent = t("job.rotation_command", { angle: turn.toLocaleString(language, { maximumFractionDigits: 4 }) });
    const deviation = distanceDeviation(nominal, measured);
    detail.textContent = t("job.rotation_detail", {
      mm: deviation.mm.toLocaleString(language, { maximumFractionDigits: 3 }),
      percent: deviation.percent.toLocaleString(language, { maximumFractionDigits: 3 }),
    });
  };
  x.input.addEventListener("input", update);
  y.input.addEventListener("input", update);
  update();

  return h(
    "section",
    { class: "panel" },
    h("h2", {}, t("job.rotation")),
    h("p", { class: "muted" }, t("job.rotation_hint", { x: second.x_mm, y: second.y_mm })),
    h("p", {}, x.label, " ", y.label),
    h("p", {}, t("job.rotation_result"), " ", command),
    detail,
  );
}

// Jobs made before the panel size became a choice used this panel.
const LEGACY_PANEL = { width_mm: 160, height_mm: 100 };

function summaryOf(job) {
  const p = job.params;
  const panel = p.panel ?? LEGACY_PANEL;
  const boards = p.boards.map((b) => `${b.count} × ${b.name} (${mm(b.width_mm)} × ${mm(b.height_mm)})`).join(", ");
  const outputs = [p.exposure ? t("job.output_exposure", { seconds: p.exposure_s }) : null, p.mill_gcode ? t("job.output_mill") : null].filter(Boolean);
  return h("dl", { class: "facts" }, [
    h("dt", {}, t("job.boards")),
    h("dd", {}, boards),
    h("dt", {}, t("job.outputs")),
    h("dd", {}, outputs.join(", ")),
    Object.keys(p.drill_map ?? {}).length
      ? [h("dt", {}, t("job.drill_map")), h("dd", {}, Object.entries(p.drill_map).map(([hole, drill]) => `${hole} → ${drill} mm`).join(", "))]
      : null,
    h("dt", {}, t("job.marks")),
    h("dd", {}, p.marks ? t("job.marks_on", { x: p.marks.second_mm.x_mm, y: p.marks.second_mm.y_mm }) : t("job.marks_off")),
    h("dt", {}, t("job.panel")),
    h("dd", {}, t("job.panel_summary", { size: `${panel.width_mm} × ${panel.height_mm} mm`, gap: mm(p.gap_mm), margin: mm(p.margin_mm), thickness: mm(p.thickness_mm) })),
  ]);
}

// The simulation section is made once, so that it keeps its state when the page is drawn again after a language change.
let simulationSection = null;

function simulationPanel(job, programs) {
  if (simulationSection) return simulationSection;
  const body = h("div", { class: "sim" });
  const details = h("details", { class: "panel" }, h("summary", { "data-i18n": "sim.title" }, t("sim.title")), body);
  let started = false;
  details.addEventListener("toggle", async () => {
    if (!details.open || started) return;
    started = true;
    fill(body, h("p", { class: "muted", "data-i18n": "sim.loading" }, t("sim.loading")));
    try {
      const simulation = await import("./simulation.js");
      simulation.createSimulation(
        body,
        await simulation.loadPrograms(job.id, programs),
        job.params.thickness_mm,
        job.params.panel ?? LEGACY_PANEL,
        { copperUrl: job.files.some((f) => f.name === "copper.png") ? await blobUrl(job, "copper.png") : null, flip: job.params.flip, panelOrigin: job.params.marks?.panel_origin_mm },
      );
    } catch {
      started = false;
      fill(body, h("p", { class: "error", role: "alert", "data-i18n": "sim.load_failed" }, t("sim.load_failed")));
    }
  });
  simulationSection = details;
  return details;
}

function showDone(job) {
  setState("job.done", {}, "ok");
  const files = new Map(job.files.map((f) => [f.name, f]));
  const programs = job.files.filter((f) => /^mill\/.+\.nc$/.test(f.name)).sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));
  const sections = [summaryOf(job)];

  if (files.has("exposure.pm3")) {
    sections.push(
      h(
        "section",
        { class: "panel" },
        h("h2", {}, t("job.exposure")),
        h(
          "div",
          { class: "previews" },
          files.has("mask_preview.png")
            ? h("figure", {}, picture(job, "mask_preview.png", { alt: t("job.mask_alt"), width: 1024, height: 640 }), h("figcaption", {}, t("job.mask_caption")))
            : null,
        ),
        h(
          "ul",
          { class: "files" },
          download(job, files.get("exposure.pm3"), "exposure.pm3", t("job.pm3_note")),
          files.has("mask.png") ? download(job, files.get("mask.png"), "mask.png", t("job.mask_png_note")) : null,
        ),
      ),
    );
  }

  if (programs.length) {
    sections.push(
      h(
        "section",
        { class: "panel" },
        h("h2", {}, t("job.drill_mill")),
        files.has("mill_preview.svg")
          ? h("figure", {}, picture(job, "mill_preview.svg", { alt: t("job.mill_alt"), class: "mill-preview" }), h("figcaption", {}, t("job.mill_caption")))
          : null,
        h("p", { class: "muted" }, t("job.programs_hint")),
        job.params.marks
          ? h("p", { class: "muted" }, t("job.marks_hint", { x: job.params.marks.second_mm.x_mm, y: job.params.marks.second_mm.y_mm }))
          : null,
        h(
          "ul",
          { class: "files" },
          programs.map((file) => download(job, file, programTitle(file.name), file.name.split("/").pop())),
          files.has("mill_gcode.zip") ? download(job, files.get("mill_gcode.zip"), t("job.all_programs")) : null,
        ),
      ),
    );
  }

  if (programs.length && job.params.marks) sections.push(rotationPanel(job.params.marks.second_mm));
  if (programs.length) sections.push(simulationPanel(job, programs));

  sections.push(
    h(
      "section",
      { class: "panel" },
      h("h2", {}, t("job.report")),
      h("p", { class: "muted" }, t("job.report_hint")),
      h("ul", { class: "files" }, h("li", {}, reportLink(job))),
    ),
  );

  sections.push(
    h(
      "section",
      { class: "panel" },
      h("h2", {}, t("job.archive")),
      h("p", { class: "muted" }, t("job.archive_hint")),
      h("ul", { class: "files" }, h("li", {}, fileLink(t("job.archive_link"), () => archiveBlob(job.id, currentLanguage()), (blob) => save(blob, `pcbhomefab-${job.id.slice(0, 8)}.zip`)))),
    ),
  );

  sections.push(
    h(
      "p",
      { class: "actions-row" },
      h("a", { class: "button", href: "/" }, t("job.new_job")),
      " ",
      h("a", { class: "button", href: "/jobs" }, t("job.all_jobs")),
    ),
  );
  fill(result, sections);
  result.hidden = false;
}

function showFailed(job) {
  setState("job.failed", { error: job.error ?? t("job.unknown_error") }, "error");
  result.hidden = false;
  fill(result, summaryOf(job), h("p", {}, h("a", { class: "button", href: "/" }, t("job.start_again"))));
}

function show(job) {
  if (job.status === "done") showDone(job);
  else showFailed(job);
}

async function poll() {
  let job;
  try {
    job = await getJob(jobId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      setState("job.not_found", {}, "error");
      return;
    }
    setState("job.unreachable");
    setTimeout(poll, 5000);
    return;
  }
  if (job.status === "done" || job.status === "failed") {
    shownJob = job;
    show(job);
  } else {
    setState(job.status === "queued" ? "job.queued" : "job.running");
    setTimeout(poll, 2000);
  }
}

await initI18n();
onLanguageChange(() => {
  setState(shownState.key, shownState.params, shownState.kind);
  if (shownJob) show(shownJob);
});
setState("job.loading");
poll();
