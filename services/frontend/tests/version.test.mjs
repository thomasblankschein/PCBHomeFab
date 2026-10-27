import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("the version shown in the footer is the newest one of the changelog", () => {
  const shown = JSON.parse(readFileSync(new URL("../site/version.json", import.meta.url), "utf8")).version;
  const changelog = readFileSync(new URL("../../../CHANGELOG.md", import.meta.url), "utf8");
  assert.equal(/^## (\d+\.\d+\.\d+)/m.exec(changelog)[1], shown);
});
