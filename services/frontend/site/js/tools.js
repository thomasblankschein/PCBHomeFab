import { getTools } from "./api.js";
import { fill, h } from "./dom.js";

const table = document.getElementById("tools");

try {
  const library = await getTools();
  document.getElementById("source").textContent = `Source: ${library.source}`;
  const kinds = { drill: "Drill", endmill: "End mill" };
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
        h("td", { class: "num" }, tool.kind === "drill" ? (tool.peck_mm > 0 ? tool.peck_mm : "one go") : tool.step_down_mm),
        h("td", {}, tool.enabled ? "on" : "off"),
      ),
    ),
  );
  table.hidden = false;
} catch (error) {
  document.getElementById("load-error").textContent = error.message;
}
