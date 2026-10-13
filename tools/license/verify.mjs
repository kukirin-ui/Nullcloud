#!/usr/bin/env node
// Verifies a Nullcloud Pro / Team license key offline using the same P-256 SPKI check as server/server.py.
//
//   node tools/license/verify.mjs NULLCLOUD-xxxx.yyyy [--pub tools/license/keys/public.b64]
import { createVerify, createPublicKey } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const argv = process.argv.slice(2);
const key = argv.find((a) => !a.startsWith("--"));
const pubIx = argv.indexOf("--pub");
const pubPath = pubIx >= 0 ? argv[pubIx + 1] : join(import.meta.dirname, "keys", "public.b64");
if (!key) {
  console.error("Usage: node tools/license/verify.mjs NULLCLOUD-... [--pub tools/license/keys/public.b64]");
  process.exit(1);
}

let k = key.trim();
if (k.startsWith("NULLCLOUD-")) k = k.slice("NULLCLOUD-".length);
else if (k.startsWith("MERIDIAN-")) k = k.slice(9);
const dot = k.indexOf(".");
if (dot <= 0) {
  console.error("Not a valid Nullcloud license key.");
  process.exit(2);
}
const payload = Buffer.from(k.slice(0, dot), "base64url");
const sig = Buffer.from(k.slice(dot + 1), "base64url");
const pub = createPublicKey({
  key: Buffer.from(readFileSync(pubPath, "utf8").trim(), "base64"),
  format: "der",
  type: "spki",
});

const verifier = createVerify("SHA256");
verifier.update(payload);
const ok = verifier.verify({ key: pub, dsaEncoding: "der" }, sig);
const claims = JSON.parse(payload.toString("utf8"));
console.log(JSON.stringify({ ok, claims }, null, 2));
process.exit(ok && ["pro", "team", "premium"].includes(claims.sku) ? 0 : 3);
