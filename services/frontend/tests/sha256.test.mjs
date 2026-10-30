import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import test from "node:test";

import { sha256 } from "../site/js/sha256.js";

const hex = (bytes) => Buffer.from(bytes).toString("hex");

test("SHA-256 gives the known values of the standard", () => {
  assert.equal(hex(sha256(new Uint8Array())), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
  assert.equal(hex(sha256(new TextEncoder().encode("abc"))), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("SHA-256 equals the one of node for lengths around the block size", () => {
  for (const length of [1, 54, 55, 56, 57, 63, 64, 65, 119, 120, 128, 1000]) {
    const data = randomBytes(length);
    assert.equal(hex(sha256(new Uint8Array(data))), createHash("sha256").update(data).digest("hex"), `length ${length}`);
  }
});
