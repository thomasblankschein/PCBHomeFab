import { t } from "./i18n.js";

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function mm(value) {
  return `${Number(value.toFixed(2))} mm`;
}

/** Human title of a G-code file name such as `mill/2_drill_1.0mm.nc`. */
export function programTitle(name) {
  const match = /(\d+)_(drill|mill)_([\d.]+)mm\.nc$/.exec(name);
  if (!match) return name;
  const [, step, kind, diameter] = match;
  return t(kind === "drill" ? "job.program_drill" : "job.program_mill", { step, diameter });
}

export function daysLeft(expires) {
  return Math.max(1, Math.round((expires - Date.now() / 1000) / 86400));
}
