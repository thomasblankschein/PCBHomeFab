import { getPlates, getProfiles } from "./api.js";
import { fill, h } from "./dom.js";
import { initI18n, onLanguageChange, t } from "./i18n.js";

const container = document.getElementById("machines");
let profiles = null;
let plates = null;
const plateTable = document.getElementById("plates");

const number = (value, unit) => `${Number(value.toFixed(3))} ${unit}`;
const yesNo = (value) => t(value ? "machines.yes" : "machines.no");
const flipKeys = { x: "settings.flip_x", y: "settings.flip_y", none: "settings.flip_none" };

// label key, value
const printerRows = (p) => [
  ["machines.p_machine_name", p.machine_name],
  ["machines.p_display", `${p.display_mm[0]} × ${p.display_mm[1]} mm`],
  ["machines.p_resolution", `${p.resolution[0]} × ${p.resolution[1]} px`],
  ["machines.p_pixel", number(p.pixel_mm * 1000, "µm")],
  ["machines.p_frame_left", number(p.frame_left_mm, "mm")],
  ["machines.p_frame_bottom", number(p.frame_bottom_mm, "mm")],
  ["machines.p_mirror", yesNo(p.mirror_x)],
  ["machines.p_exposure", number(p.default_exposure_s, "s")],
  ["machines.p_lift", number(p.lift_height_mm, "mm")],
  ["machines.p_lift_speed", number(p.lift_speed_mms, "mm/s")],
  ["machines.p_retract_speed", number(p.retract_speed_mms, "mm/s")],
];

const millRows = (m) => [
  ["machines.m_spindle", number(m.max_spindle_rpm, "rpm")],
  ["machines.m_endmill", number(m.outline_endmill_mm, "mm")],
  ["machines.m_safe_z", number(m.safe_z_mm, "mm")],
  ["machines.m_spinup", number(m.spindle_spinup_s, "s")],
  ["machines.m_drill_overshoot", number(m.drill_overshoot_mm, "mm")],
  ["machines.m_mill_overshoot", number(m.mill_overshoot_mm, "mm")],
  ["machines.m_tabs", yesNo(m.tabs)],
  ["machines.m_tab_width", number(m.tab_width_mm, "mm")],
  ["machines.m_tab_height", number(m.tab_height_mm, "mm")],
  ["machines.m_flip", t(flipKeys[m.flip] ?? "settings.flip_none")],
  ["machines.m_offset", `${number(m.offset_x_mm, "mm")}, ${number(m.offset_y_mm, "mm")}`],
  ["machines.m_thickness", number(m.default_thickness_mm, "mm")],
];

function card(name, rows) {
  return h(
    "section",
    { class: "panel" },
    h("h3", {}, name),
    h("dl", { class: "facts" }, rows.map(([key, value]) => [h("dt", {}, t(key)), h("dd", {}, value)])),
  );
}

function render() {
  fill(
    container,
    h("h2", {}, t("machines.printers")),
    Object.values(profiles.printers).map((printer) => card(printer.name, printerRows(printer))),
    h("h2", {}, t("machines.mills")),
    Object.values(profiles.mills).map((mill) => card(mill.name, millRows(mill))),
  );
}

function renderPlates() {
  document.getElementById("plates-source").textContent = t("tools.source", { source: plates.source });
  fill(
    plateTable.tBodies[0],
    plates.plates.map((plate) =>
      h("tr", {}, h("td", {}, plate.name), h("td", { class: "num" }, number(plate.width_mm, "mm")), h("td", { class: "num" }, number(plate.height_mm, "mm")), h("td", {}, h("code", {}, plate.id))),
    ),
  );
  plateTable.hidden = false;
}

await initI18n();
onLanguageChange(() => {
  if (profiles) render();
  if (plates) renderPlates();
});
try {
  [profiles, plates] = await Promise.all([getProfiles(), getPlates()]);
  render();
  renderPlates();
} catch (error) {
  document.getElementById("load-error").textContent = error.message;
}
