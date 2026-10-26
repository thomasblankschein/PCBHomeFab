import { ApiError, fileUrl, getJob } from "./api.js";
import { fill, h } from "./dom.js";
import { daysLeft, formatSize, mm, programTitle } from "./format.js";

const jobId = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() ?? "");
const state = document.getElementById("state");
const result = document.getElementById("result");

function setState(text, kind = "") {
  state.textContent = text;
  state.className = `state ${kind}`.trim();
}

function download(job, file, label, note) {
  return h(
    "li",
    {},
    h("a", { href: fileUrl(job.id, file.name), download: file.name.split("/").pop() }, label ?? file.name),
    h("span", { class: "muted" }, ` ${formatSize(file.size)}`),
    note ? h("div", { class: "muted" }, note) : null,
  );
}

function summaryOf(job) {
  const p = job.params;
  const boards = p.boards.map((b) => `${b.count} × ${b.name} (${mm(b.width_mm)} × ${mm(b.height_mm)})`).join(", ");
  const outputs = [p.exposure ? `exposure ${p.exposure_s} s` : null, p.mill_gcode ? "drill and mill G-code" : null].filter(Boolean);
  return h("dl", { class: "facts" }, [
    h("dt", {}, "Boards"),
    h("dd", {}, boards),
    h("dt", {}, "Outputs"),
    h("dd", {}, outputs.join(", ")),
    h("dt", {}, "Plate"),
    h("dd", {}, `gap ${mm(p.gap_mm)}, margin ${mm(p.margin_mm)}, ${mm(p.thickness_mm)} thick`),
  ]);
}

function showDone(job) {
  setState(`Done. The files are kept for about ${daysLeft(job.expires)} more day(s). Keep this link, it is the only way to get them back.`, "ok");
  const files = new Map(job.files.map((f) => [f.name, f]));
  const programs = job.files.filter((f) => /^mill\/.+\.nc$/.test(f.name)).sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));
  const sections = [summaryOf(job)];

  if (files.has("exposure.pm3")) {
    sections.push(
      h(
        "section",
        { class: "panel" },
        h("h2", {}, "Exposure"),
        h(
          "div",
          { class: "previews" },
          files.has("mask_preview.png")
            ? h("figure", {}, h("img", { src: fileUrl(job.id, "mask_preview.png"), alt: "Exposure mask: white exposes, black stays copper", width: 1024, height: 640 }), h("figcaption", {}, "Mask as sent to the printer (mirrored, white = exposed)."))
            : null,
        ),
        h(
          "ul",
          { class: "files" },
          download(job, files.get("exposure.pm3"), "exposure.pm3", "Open in Photon Workshop and print."),
          files.has("mask.png") ? download(job, files.get("mask.png"), "mask.png", "The mask as image (4096 × 2560 px).") : null,
        ),
      ),
    );
  }

  if (programs.length) {
    sections.push(
      h(
        "section",
        { class: "panel" },
        h("h2", {}, "Drill and mill"),
        files.has("mill_preview.svg")
          ? h("figure", {}, h("img", { src: fileUrl(job.id, "mill_preview.svg"), alt: "Plate with board outlines and holes", class: "mill-preview" }), h("figcaption", {}, "Plate on the mill bed with board outlines and holes (colour = diameter)."))
          : null,
        h("p", { class: "muted" }, "One program per tool, run them in this order and change the tool in between. Set Z0 to the plate surface."),
        h(
          "ul",
          { class: "files" },
          programs.map((file) => download(job, file, programTitle(file.name), file.name.split("/").pop())),
          files.has("mill_gcode.zip") ? download(job, files.get("mill_gcode.zip"), "All programs (ZIP)") : null,
        ),
      ),
    );
  }

  sections.push(
    h(
      "p",
      { class: "actions-row" },
      h("button", { type: "button", id: "copy" }, "Copy link"),
      " ",
      h("a", { class: "button", href: "/" }, "New job"),
    ),
  );
  fill(result, sections);
  result.hidden = false;
  document.getElementById("copy").addEventListener("click", async (event) => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      event.target.textContent = "Link copied";
    } catch {
      event.target.textContent = "Copy the address from the address bar";
    }
  });
}

async function poll() {
  let job;
  try {
    job = await getJob(jobId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      setState("This job does not exist or has expired.", "error");
      return;
    }
    setState("Cannot reach the server, trying again ...");
    setTimeout(poll, 5000);
    return;
  }
  document.title = `Job - PCBHomeFab`;
  if (job.status === "done") {
    showDone(job);
  } else if (job.status === "failed") {
    setState(`The job failed: ${job.error ?? "unknown error"}`, "error");
    result.hidden = false;
    fill(result, summaryOf(job), h("p", {}, h("a", { class: "button", href: "/" }, "Start again")));
  } else {
    setState(job.status === "queued" ? "Waiting in the queue. This page updates itself." : "Creating the files. This page updates itself.");
    setTimeout(poll, 2000);
  }
}

poll();
