"use strict";

const jobId = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");
const api = `/api/v1/jobs/${encodeURIComponent(jobId)}`;
const state = document.getElementById("state");
const list = document.getElementById("files");
document.getElementById("title").textContent = `Job ${jobId}`;

function fileUrl(name) {
  return `${api}/files/${name.split("/").map(encodeURIComponent).join("/")}`;
}

function showFailure(message) {
  state.textContent = message;
  state.className = "error";
}

function showDone(job) {
  const days = Math.max(1, Math.round((job.expires - Date.now() / 1000) / 86400));
  state.textContent = `Done. Files are kept for about ${days} more day(s). Keep this link, it is the only way to get them back.`;
  list.replaceChildren(
    ...job.files.map((file) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = fileUrl(file.name);
      link.textContent = file.name;
      item.append(link, ` (${Math.floor(file.size / 1024) + 1} KB)`);
      return item;
    }),
  );
  if (job.files.some((file) => file.name === "mask_preview.png")) {
    document.getElementById("mask").src = fileUrl("mask_preview.png");
    document.getElementById("preview").hidden = false;
  }
}

async function poll() {
  let job;
  try {
    const response = await fetch(api);
    if (response.status === 404) return showFailure("Job not found or expired.");
    if (!response.ok) throw new Error(String(response.status));
    job = await response.json();
  } catch {
    state.textContent = "Cannot reach the server, trying again ...";
    return setTimeout(poll, 5000);
  }
  if (job.status === "done") return showDone(job);
  if (job.status === "failed") return showFailure(`The job failed: ${job.error || "unknown error"}`);
  state.textContent = `Status: ${job.status}. This page updates itself.`;
  return setTimeout(poll, 2000);
}

poll();
