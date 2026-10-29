// Calls to the REST API of the jobs service (the gateway publishes it under /api).

import { t } from "./i18n.js";

const API = "/api/v1";

export class ApiError extends Error {
  constructor(message, { code = "client.error", status = 0 } = {}) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API}${path}`, options);
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(t("error.network"), { code: "client.network" });
  }
  if (response.ok) return response;
  let problem = {};
  try {
    problem = await response.json();
  } catch {
    // not a JSON problem, for example an error page of a proxy
  }
  const message = problem.detail || (response.status === 413 ? t("error.too_large") : t("error.status", { status: response.status }));
  throw new ApiError(message, { code: problem.code ?? "http.error", status: response.status });
}

const json = async (path, options) => (await request(path, options)).json();

export const getProfiles = () => json("/profiles");
export const getTools = () => json("/tools");
export const getPanels = () => json("/panels");
export const getJob = (id) => json(`/jobs/${encodeURIComponent(id)}`);

export function getBoardInfo(file) {
  const body = new FormData();
  body.append("file", file);
  return json("/boards", { method: "POST", body });
}

export function previewLayout(request_, signal) {
  return json("/layouts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request_),
    signal,
  });
}

export function createJob(formData) {
  return json("/jobs", { method: "POST", body: formData });
}

export function archiveUrl(jobId) {
  return `${API}/jobs/${encodeURIComponent(jobId)}/archive`;
}

/** The job description as a PDF; the report is written in German or English (`lang`). */
export function reportUrl(jobId, lang) {
  return `${API}/jobs/${encodeURIComponent(jobId)}/report.pdf?lang=${lang === "de" ? "de" : "en"}`;
}

export function fileUrl(jobId, name) {
  return `${API}/jobs/${encodeURIComponent(jobId)}/files/${name.split("/").map(encodeURIComponent).join("/")}`;
}
