import assert from "node:assert/strict";
import test from "node:test";

import { authorizeUrl, base64Url, pkceChallenge, randomString, safeReturnPath, tokensFrom } from "../site/js/auth.js";

test("the PKCE challenge is the one of the example in RFC 7636", async () => {
  assert.equal(await pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});

test("base64url has no padding and no + or /", () => {
  assert.equal(base64Url(new Uint8Array([251, 255, 254])), "-__-");
  assert.equal(base64Url(new Uint8Array([1])), "AQ");
  assert.match(randomString(48), /^[A-Za-z0-9_-]{64}$/);
});

test("the login address asks for the code flow with PKCE and the redirect address of the page", () => {
  const url = new URL(
    authorizeUrl("https://pcb.example/auth/realms/pcbhomefab/protocol/openid-connect/auth", {
      redirectUri: "https://pcb.example/auth-callback",
      state: "abc",
      challenge: "xyz",
    }),
  );
  assert.equal(url.origin + url.pathname, "https://pcb.example/auth/realms/pcbhomefab/protocol/openid-connect/auth");
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    client_id: "pcbhomefab-web",
    response_type: "code",
    scope: "openid",
    redirect_uri: "https://pcb.example/auth-callback",
    state: "abc",
    code_challenge: "xyz",
    code_challenge_method: "S256",
  });
});

test("the stored tokens know when the access token runs out", () => {
  const tokens = tokensFrom({ access_token: "a", refresh_token: "r", id_token: "i", expires_in: 900 }, 1_000);
  assert.deepEqual(tokens, { access: "a", refresh: "r", id: "i", expiresAt: 901_000 });
  assert.equal(tokensFrom({ access_token: "a", expires_in: 60 }, 0).refresh, null);
});

test("after the login only a path of this site is gone back to", () => {
  assert.equal(safeReturnPath("/jobs/abc?x=1"), "/jobs/abc?x=1");
  assert.equal(safeReturnPath("/"), "/");
  for (const bad of ["https://evil.example/", "//evil.example/", "/\\evil.example", "jobs", "", null, undefined]) {
    assert.equal(safeReturnPath(bad), "/");
  }
});
