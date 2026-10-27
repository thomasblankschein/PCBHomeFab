// Translations. One flat JSON file per language in /locales (key -> text), the languages are listed in
// /locales/index.json. To add a language: copy en.json, translate it, add an entry to index.json.
//
//   - Static text:   data-i18n="key" sets the text, data-i18n-attr="aria-label:key,title:key2" sets attributes.
//   - Script text:   t(key, { name: value }). "{name}" in a text is replaced by the value.
//   - Plurals:       pass a numeric `count`; the texts are "key_one", "key_other" (CLDR categories of the language).
//   - Missing keys:  the text of the default language is used, then the key itself.

import { h } from "./dom.js";

const STORAGE_KEY = "pcbhomefab.language";
const LOCALES = "/locales";
const BUILT_IN = { default: "en", languages: [{ code: "en", name: "English" }] };

let index = BUILT_IN;
let language = BUILT_IN.default;
let messages = {};
let fallback = {};
const listeners = [];

// --- pure parts (tested without a browser) -----------------------------------------------------------------

export function interpolate(text, params = {}) {
  return text.replace(/\{(\w+)\}/g, (placeholder, name) => (name in params ? String(params[name]) : placeholder));
}

export function lookup(table, fallbackTable, locale, key, params = {}) {
  let text;
  if (typeof params.count === "number") {
    const category = new Intl.PluralRules(locale).select(params.count);
    for (const source of [table, fallbackTable]) {
      text = source[`${key}_${category}`] ?? source[`${key}_other`];
      if (text !== undefined) break;
    }
  }
  text ??= table[key] ?? fallbackTable[key];
  return text === undefined ? key : interpolate(text, params);
}

/** The language to start with: the stored choice, then the browser languages, then the default. */
export function pickLanguage(codes, stored, preferred, defaultCode) {
  const find = (wanted) => codes.find((code) => code.toLowerCase() === wanted.toLowerCase());
  if (stored && find(stored)) return find(stored);
  for (const tag of preferred) {
    const match = find(tag) ?? find(tag.split("-")[0]);
    if (match) return match;
  }
  return defaultCode;
}

// --- browser parts ------------------------------------------------------------------------------------------

export function t(key, params) {
  return lookup(messages, fallback, language, key, params);
}

export const currentLanguage = () => language;

/** Call `callback` after the language was changed, to render texts that were made by script. */
export function onLanguageChange(callback) {
  listeners.push(callback);
}

async function loadTable(code) {
  const response = await fetch(`${LOCALES}/${encodeURIComponent(code)}.json`);
  if (!response.ok) throw new Error(`language file ${code} not found`);
  return response.json();
}

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function store(code) {
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // storage may be blocked, the choice then lasts until the page is closed
  }
}

export function applyStatic(root = document) {
  // a key without a text keeps the English text of the markup
  for (const element of root.querySelectorAll("[data-i18n]")) {
    const text = t(element.dataset.i18n);
    if (text !== element.dataset.i18n) element.textContent = text;
  }
  for (const element of root.querySelectorAll("[data-i18n-attr]")) {
    for (const pair of element.dataset.i18nAttr.split(",")) {
      const [attribute, key] = pair.split(":").map((part) => part.trim());
      const text = t(key);
      if (text !== key) element.setAttribute(attribute, text);
    }
  }
}

async function use(code) {
  if (code === index.default) {
    messages = fallback;
  } else {
    try {
      messages = await loadTable(code);
    } catch {
      code = index.default;
      messages = fallback;
    }
  }
  language = code;
  document.documentElement.lang = code;
}

function switcher() {
  const select = h(
    "select",
    { id: "language", "data-i18n-attr": "aria-label:language.label", onchange: (event) => setLanguage(event.target.value) },
    index.languages.map((entry) => h("option", { value: entry.code, lang: entry.code }, entry.name)),
  );
  select.value = language;
  return select;
}

export async function setLanguage(code) {
  await use(code);
  store(language);
  document.getElementById("language").value = language;
  applyStatic();
  for (const callback of listeners) callback();
}

/** Load the language files, pick the language and translate the static text. Call it once at the start of a page. */
export async function initI18n() {
  try {
    const response = await fetch(`${LOCALES}/index.json`);
    if (response.ok) index = await response.json();
    fallback = await loadTable(index.default);
  } catch {
    // without language files the pages keep the English text of the markup
  }
  try {
    const codes = index.languages.map((entry) => entry.code);
    await use(pickLanguage(codes, readStored(), navigator.languages ?? [], index.default));
    const header = document.querySelector(".top");
    if (header && codes.length > 1 && !document.getElementById("language")) header.append(h("div", { class: "language" }, switcher()));
    applyStatic();
  } finally {
    document.documentElement.dataset.ready = "";
  }
}
