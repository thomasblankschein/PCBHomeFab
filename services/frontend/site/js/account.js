// The account in the header: who is logged in and the button to log out. Every page loads this module.

import { getMe } from "./api.js";
import { logout } from "./auth.js";
import { h } from "./dom.js";
import { applyStatic } from "./i18n.js";

const header = document.querySelector(".top");

if (header) {
  try {
    const me = await getMe();
    const account = h(
      "div",
      { class: "account", role: "group", "data-i18n-attr": "aria-label:account.aria" },
      h("span", { class: "who" }, me.name || me.id),
      h("button", { type: "button", class: "link", "data-i18n": "account.logout", onclick: () => logout() }, "Log out"),
    );
    header.append(account);
    applyStatic(account);
  } catch {
    // the page shows its own error when the server cannot be reached
  }
}
