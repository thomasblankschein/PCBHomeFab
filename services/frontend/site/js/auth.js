// Login with OpenID Connect against Keycloak, which the gateway publishes under /auth: authorization code flow with PKCE,
// no library. The access token goes with every API call (api.js). The password is typed on the page of Keycloak only.

import { sha256 } from "./sha256.js";

const REALM ="/auth/realms/pcbhomefab";
const CLIENT_ID = "pcbhomefab-web";
const TOKENS_KEY = "pcbhomefab.tokens";
const PENDING_KEY = "pcbhomefab.login";
// A token that runs out within this time is renewed before it is used.
const SKEW_MS = 30_000;

export const callbackUri = () => `${window.location.origin}/auth-callback`;

export function base64Url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

export function randomString(length = 32) {
  return base64Url(crypto.getRandomValues(new Uint8Array(length)));
}

/** The PKCE code challenge (S256) of a verifier, RFC 7636. */
export async function pkceChallenge(verifier) {
  const bytes = new TextEncoder().encode(verifier);
  // crypto.subtle exists only on https and localhost; over plain http the hash is calculated here.
  return base64Url(globalThis.crypto?.subtle ? await crypto.subtle.digest("SHA-256", bytes) : sha256(bytes));
}

export function authorizeUrl(endpoint, { redirectUri, state, challenge }) {
  const url = new URL(endpoint);
  url.search = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    scope: "openid",
    redirect_uri: redirectUri,
    state,
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();
  return url.toString();
}

/** What is stored of a token response: the tokens and when the access token runs out (ms since 1970). */
export function tokensFrom(response, now = Date.now()) {
  return {
    access: response.access_token,
    refresh: response.refresh_token ?? null,
    id: response.id_token ?? null,
    expiresAt: now + Number(response.expires_in ?? 0) * 1000,
  };
}

/** A path inside this site to go back to after the login; anything else becomes the start page. */
export function safeReturnPath(path) {
  return typeof path === "string" && /^\/(?![/\\])/.test(path) ? path : "/";
}

function read(storage, key) {
  try {
    return JSON.parse(storage.getItem(key));
  } catch {
    return null;
  }
}

function write(storage, key, value) {
  try {
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(value));
  } catch {
    // storage is blocked: the login then lasts until the page is left
  }
}

let memoryTokens = null;
const loadTokens = () => memoryTokens ?? read(window.localStorage, TOKENS_KEY);

function saveTokens(tokens) {
  memoryTokens = tokens;
  write(window.localStorage, TOKENS_KEY, tokens);
}

let discovered = null;

async function endpoints() {
  discovered ??= fetch(`${REALM}/.well-known/openid-configuration`).then((response) => {
    if (!response.ok) throw new Error(`login service answered ${response.status}`);
    return response.json();
  });
  try {
    return await discovered;
  } catch (error) {
    discovered = null;
    throw error;
  }
}

let loginStarted = null;

/** Go to the login page of Keycloak. The promise never ends, the page is left. */
export function startLogin(returnTo = window.location.pathname + window.location.search) {
  loginStarted ??= (async () => {
    const config = await endpoints();
    const verifier = randomString(48);
    const state = randomString(16);
    write(window.sessionStorage, PENDING_KEY, { state, verifier, returnTo: safeReturnPath(returnTo) });
    window.location.assign(authorizeUrl(config.authorization_endpoint, { redirectUri: callbackUri(), state, challenge: await pkceChallenge(verifier) }));
    await new Promise(() => {});
  })();
  return loginStarted;
}

async function tokenRequest(parameters) {
  const config = await endpoints();
  const response = await fetch(config.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: CLIENT_ID, ...parameters }),
  });
  if (!response.ok) throw new Error(`token request failed (${response.status})`);
  return tokensFrom(await response.json());
}

/** The callback page: trade the code in the address for tokens, then go back to where the user came from. */
export async function finishLogin() {
  const query = new URLSearchParams(window.location.search);
  const pending = read(window.sessionStorage, PENDING_KEY);
  write(window.sessionStorage, PENDING_KEY, null);
  if (query.get("error")) throw new Error(query.get("error_description") || query.get("error"));
  if (!pending || !query.get("code") || query.get("state") !== pending.state) throw new Error("The login was not started here.");
  saveTokens(
    await tokenRequest({ grant_type: "authorization_code", code: query.get("code"), redirect_uri: callbackUri(), code_verifier: pending.verifier }),
  );
  window.location.replace(safeReturnPath(pending.returnTo));
}

let refreshing = null;

/** A valid access token. Renews it when it runs out, goes to the login page when there is none or it cannot be renewed. */
export async function accessToken() {
  const tokens = loadTokens();
  if (!tokens) return startLogin();
  if (tokens.expiresAt - Date.now() > SKEW_MS) return tokens.access;
  if (!tokens.refresh) return startLogin();
  refreshing ??= tokenRequest({ grant_type: "refresh_token", refresh_token: tokens.refresh })
    .then((fresh) => {
      saveTokens({ ...fresh, refresh: fresh.refresh ?? tokens.refresh, id: fresh.id ?? tokens.id });
      return fresh.access;
    })
    .finally(() => {
      refreshing = null;
    });
  try {
    return await refreshing;
  } catch {
    saveTokens(null);
    return startLogin();
  }
}

/** The server refused the token: forget it and log in again. */
export function loginAgain() {
  saveTokens(null);
  return startLogin();
}

/** End the session at Keycloak too, then come back to the start page (which asks for the login again). */
export async function logout() {
  const tokens = loadTokens();
  saveTokens(null);
  const config = await endpoints();
  const url = new URL(config.end_session_endpoint);
  url.search = new URLSearchParams({
    client_id: CLIENT_ID,
    post_logout_redirect_uri: `${window.location.origin}/`,
    ...(tokens?.id ? { id_token_hint: tokens.id } : {}),
  }).toString();
  window.location.assign(url.toString());
}
