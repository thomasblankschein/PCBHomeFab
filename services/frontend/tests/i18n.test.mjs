import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

import { interpolate, lookup, pickLanguage } from "../site/js/i18n.js";

const site = new URL("../site/", import.meta.url);
const read = (path) => readFileSync(new URL(path, site), "utf8");
const readJson = (path) => JSON.parse(read(path));

const index = readJson("locales/index.json");
const tables = Object.fromEntries(index.languages.map(({ code }) => [code, readJson(`locales/${code}.json`)]));
const english = tables[index.default];

const PLURAL = /_(zero|one|two|few|many|other)$/;
const baseKey = (key) => key.replace(PLURAL, "");
const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test("the language list names existing files and the default language", () => {
  assert.ok(index.languages.some(({ code }) => code === index.default));
  const files = readdirSync(new URL("locales/", site)).filter((f) => f !== "index.json");
  assert.deepEqual(files.map((f) => f.replace(/\.json$/, "")).sort(), index.languages.map((l) => l.code).sort());
  for (const { code, name } of index.languages) assert.ok(name, `language ${code} has a name`);
});

for (const [code, table] of Object.entries(tables)) {
  if (code === index.default) continue;

  test(`${code}: same texts as the default language`, () => {
    const wanted = new Set(Object.keys(english).map(baseKey));
    const have = new Set(Object.keys(table).map(baseKey));
    assert.deepEqual([...wanted].filter((k) => !have.has(k)), [], "missing keys");
    assert.deepEqual([...have].filter((k) => !wanted.has(k)), [], "keys the default language does not have");
  });

  test(`${code}: same placeholders`, () => {
    for (const [key, text] of Object.entries(table)) {
      const reference = english[key] ?? english[`${baseKey(key)}_other`];
      assert.deepEqual(placeholders(text), placeholders(reference), key);
    }
  });
}

test("every plural text has the form other", () => {
  for (const [code, table] of Object.entries(tables)) {
    for (const key of Object.keys(table).filter((k) => PLURAL.test(k))) {
      assert.ok(`${baseKey(key)}_other` in table, `${code}: ${key}`);
    }
  }
});

test("every key used in the pages and scripts exists", () => {
  const known = new Set(Object.keys(english).flatMap((key) => [key, baseKey(key)]));
  const used = [];
  for (const file of readdirSync(site).filter((f) => f.endsWith(".html"))) {
    const html = read(file);
    for (const m of html.matchAll(/data-i18n="([^"]+)"/g)) used.push([file, m[1]]);
    for (const m of html.matchAll(/data-i18n-attr="([^"]+)"/g)) {
      for (const pair of m[1].split(",")) used.push([file, pair.split(":")[1].trim()]);
    }
  }
  for (const file of readdirSync(new URL("js/", site)).filter((f) => f.endsWith(".js"))) {
    const code = read(`js/${file}`);
    for (const m of code.matchAll(/\bt\(\s*"([^"]+)"/g)) used.push([file, m[1]]);
    for (const m of code.matchAll(/\b(?:key|setState\()\s*:?\s*"([a-z_]+\.[a-z_]+)"/g)) used.push([file, m[1]]);
    assert.ok(!/\bt\(\s*`/.test(code), `${file}: build keys from literals so that they can be checked`);
  }
  assert.deepEqual(used.filter(([, key]) => !known.has(key)), []);
});

test("every key of the default language is used", () => {
  const sources = [
    ...readdirSync(site).filter((f) => f.endsWith(".html")).map((f) => read(f)),
    ...readdirSync(new URL("js/", site)).filter((f) => f.endsWith(".js")).map((f) => read(`js/${f}`)),
  ].join("\n");
  const unused = [...new Set(Object.keys(english).map(baseKey))].filter((key) => !sources.includes(`"${key}"`) && !sources.includes(`:${key}"`));
  assert.deepEqual(unused, []);
});

test("interpolate replaces known placeholders only", () => {
  assert.equal(interpolate("{a} and {b} and {c}", { a: 1, b: "x" }), "1 and x and {c}");
});

test("lookup: plural forms, fallback and missing keys", () => {
  const table = { "n_one": "{count} thing", "n_other": "{count} things", "only_here": "here" };
  const fallback = { "only_default": "default", "m_other": "{count} of m", "only_here": "default here" };
  assert.equal(lookup(table, fallback, "en", "n", { count: 1 }), "1 thing");
  assert.equal(lookup(table, fallback, "en", "n", { count: 5 }), "5 things");
  assert.equal(lookup(table, fallback, "en", "m", { count: 2 }), "2 of m");
  assert.equal(lookup(table, fallback, "en", "only_here"), "here");
  assert.equal(lookup(table, fallback, "en", "only_default"), "default");
  assert.equal(lookup(table, fallback, "en", "nothing"), "nothing");
});

test("lookup uses the plural rules of the language", () => {
  const table = { "d_one": "one", "d_few": "few", "d_other": "other" };
  assert.equal(lookup(table, {}, "pl", "d", { count: 3 }), "few");
  assert.equal(lookup(table, {}, "en", "d", { count: 3 }), "other");
});

test("pickLanguage: stored choice, browser languages, default", () => {
  const codes = ["en", "de"];
  assert.equal(pickLanguage(codes, "de", ["en-US"], "en"), "de");
  assert.equal(pickLanguage(codes, "xx", ["fr-FR", "de-AT", "en"], "en"), "de");
  assert.equal(pickLanguage(codes, null, ["fr"], "en"), "en");
  assert.equal(pickLanguage(codes, null, [], "en"), "en");
});
