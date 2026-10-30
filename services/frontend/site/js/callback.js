// The page Keycloak sends the browser back to after the login (redirect address /auth-callback).

import { finishLogin } from "./auth.js";
import { initI18n, t } from "./i18n.js";

await initI18n();
try {
  await finishLogin();
} catch (error) {
  const state = document.getElementById("state");
  state.textContent = t("login.failed", { message: error.message });
  state.className = "state error";
  document.getElementById("again").hidden = false;
}
