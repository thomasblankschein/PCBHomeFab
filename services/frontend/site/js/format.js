import { t } from "./i18n.js";

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function mm(value) {
  return `${Number(value.toFixed(2))} mm`;
}

/** Step, kind and tool diameter of a G-code file name such as `mill/2_drill_1.0mm.nc`, or null. */
export function programInfo(name) {
  const match = /(\d+)_(drill|mill)_([\d.]+)mm\.nc$/.exec(name);
  return match ? { step: match[1], kind: match[2], diameter: match[3] } : null;
}

/** Human title of a G-code file name. */
export function programTitle(name) {
  const info = programInfo(name);
  if (!info) return name;
  return t(info.kind === "drill" ? "job.program_drill" : "job.program_mill", { step: info.step, diameter: info.diameter });
}

export function daysLeft(expires) {
  return Math.max(1, Math.round((expires - Date.now() / 1000) / 86400));
}
