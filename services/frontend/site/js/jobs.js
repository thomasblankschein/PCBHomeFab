// The list of the jobs of the logged-in account: open or delete them.

import { ApiError, deleteJob, listJobs } from "./api.js";
import { fill, h } from "./dom.js";
import { mm } from "./format.js";
import { currentLanguage, initI18n, onLanguageChange, t } from "./i18n.js";

const PAGE = 25;
const REFRESH_MS = 4000;

const body = document.getElementById("rows");
const table = document.getElementById("jobs");
const empty = document.getElementById("empty");
const range = document.getElementById("range");
const previous = document.getElementById("previous");
const next = document.getElementById("next");
const error = document.getElementById("load-error");

let offset = 0;
let page = null;
let timer = null;

const STATES = { queued: "jobs.state_queued", running: "jobs.state_running", done: "jobs.state_done", failed: "jobs.state_failed" };

const created = (job) => new Date(job.created * 1000).toLocaleString(currentLanguage());

function outputs(job) {
  return [job.exposure ? t("jobs.output_exposure") : null, job.mill_gcode ? t("jobs.output_mill") : null].filter(Boolean).join(", ");
}

function row(job) {
  return h(
    "tr",
    {},
    h("td", {}, created(job)),
    h("td", {}, job.boards.map((b) => `${b.count} × ${b.name}`).join(", ")),
    h("td", {}, job.panel ? `${mm(job.panel.width_mm)} × ${mm(job.panel.height_mm)}` : ""),
    h("td", {}, outputs(job)),
    h("td", { class: job.status === "failed" ? "error" : "" }, t(STATES[job.status] ?? "jobs.state_failed")),
    h(
      "td",
      { class: "actions" },
      h("a", { class: "button", href: `/jobs/${encodeURIComponent(job.id)}` }, t("jobs.open")),
      " ",
      h("button", { type: "button", "aria-label": t("jobs.delete_label", { created: created(job) }), onclick: () => remove(job) }, t("jobs.delete")),
    ),
  );
}

function render() {
  if (!page) return;
  const jobs = page.jobs;
  fill(body, jobs.map(row));
  table.hidden = page.total === 0;
  empty.hidden = page.total !== 0;
  range.textContent = page.total ? t("jobs.range", { from: page.offset + 1, to: page.offset + jobs.length, total: page.total }) : "";
  previous.disabled = page.offset === 0;
  next.disabled = page.offset + jobs.length >= page.total;
}

function show(message) {
  error.textContent = message;
  error.hidden = !message;
}

async function load() {
  clearTimeout(timer);
  try {
    page = await listJobs(PAGE, offset);
    if (page.jobs.length === 0 && offset > 0) {
      offset = Math.max(0, offset - PAGE);
      return load();
    }
    show("");
    render();
    // jobs that are still working change by themselves
    if (page.jobs.some((job) => job.status === "queued" || job.status === "running")) timer = setTimeout(load, REFRESH_MS);
  } catch (caught) {
    show(t("jobs.load_failed", { message: caught.message }));
    if (!(caught instanceof ApiError)) throw caught;
  }
  return undefined;
}

async function remove(job) {
  if (!window.confirm(t("jobs.confirm_delete"))) return;
  try {
    await deleteJob(job.id);
  } catch (caught) {
    show(t("jobs.delete_failed", { message: caught.message }));
    return;
  }
  await load();
}

previous.addEventListener("click", () => {
  offset = Math.max(0, offset - PAGE);
  load();
});
next.addEventListener("click", () => {
  offset += PAGE;
  load();
});

await initI18n();
onLanguageChange(render);
load();
