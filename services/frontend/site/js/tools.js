import { getTools } from "./api.js";
import { fill, h } from "./dom.js";
import { initI18n, onLanguageChange, t } from "./i18n.js";

const table = document.getElementById("tools");
let library = null;

function render() {
  document.getElementById("source").textContent = t("tools.source", { source: library.source });
  const kinds = { drill: t("tools.kind_drill"), endmill: t("tools.kind_endmill") };
  fill(
    table.tBodies[0],
    library.tools.map((tool) =>
      h(
        "tr",
        { class: tool.enabled ? "" : "muted" },
        h("td", {}, tool.name || tool.id),
        h("td", {}, kinds[tool.kind] ?? tool.kind),
        h("td", { class: "num" }, `${tool.diameter_mm} mm`),
        h("td", { class: "num" }, tool.spindle_rpm),
        h("td", { class: "num" }, tool.kind === "endmill" ? tool.feed : "-"),
        h("td", { class: "num" }, tool.plunge_feed),
        h("td", { class: "num" }, tool.kind === "drill" ? (tool.peck_mm > 0 ? tool.peck_mm : t("tools.one_go")) : tool.step_down_mm),
        h("td", {}, tool.enabled ? t("tools.on") : t("tools.off")),
      ),
    ),
  );
  table.hidden = false;
}

await initI18n();
onLanguageChange(() => library && render());
try {
  library = await getTools();
  render();
} catch (error) {
  document.getElementById("load-error").textContent = error.message;
}
