// Calls to the REST API of the jobs service (the gateway publishes it under /api). Every call carries the access token of
// the login (auth.js); without a valid login the page goes to the login page.

import { accessToken, loginAgain } from "./auth.js";
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
  const token = await accessToken();
  let response;
  try {
    response = await fetch(`${API}${path}`, { ...options, headers: { ...options.headers, Authorization: `Bearer ${token}` } });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(t("error.network"), { code: "client.network" });
  }
  if (response.ok) return response;
  if (response.status === 401) return loginAgain();
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
export const getMe = () => json("/me");
export const listJobs = (limit, offset) => json(`/jobs?limit=${limit}&offset=${offset}`);

export async function deleteJob(id) {
  await request(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

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

// Files are fetched with the token and handed on as blobs: a plain link or picture of the page cannot send it.
const jobPath = (jobId) => `/jobs/${encodeURIComponent(jobId)}`;
const filePath = (jobId, name) => `${jobPath(jobId)}/files/${name.split("/").map(encodeURIComponent).join("/")}`;
const languageOf = (lang) => (lang === "de" ? "de" : "en");

export const fileBlob = async (jobId, name) => (await request(filePath(jobId, name))).blob();
export const fileText = async (jobId, name) => (await request(filePath(jobId, name))).text();

/** All result files in one ZIP; it holds the job description in German or English (`lang`). */
export const archiveBlob = async (jobId, lang) => (await request(`${jobPath(jobId)}/archive?lang=${languageOf(lang)}`)).blob();

/** The job description as a PDF, written in German or English (`lang`). */
export const reportBlob = async (jobId, lang) => (await request(`${jobPath(jobId)}/report.pdf?lang=${languageOf(lang)}`)).blob();
