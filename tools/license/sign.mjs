#!/usr/bin/env node
// Issues a signed offline Nullcloud license key after a Revolut payment is confirmed by email.
//
//   node tools/license/sign.mjs --ref ORDER-1234 [--key tools/license/keys/private.pem] [--sku pro|team] [--copies 2]
//
// Output format (what the customer pastes into the Web UI, Extension, or ~/.nullcloud-pro.key):
//   NULLCLOUD-<base64url payload>.<base64url signature>
// payload = {"sku":"pro"|"team","iat":<unix seconds>,"ref":"ORDER-1234"}
// signature = SHA256withECDSA over the raw payload bytes, DER encoded.
// Verified 100% offline in server/server.py with zero phone-home or cloud dependency.
import { createSign, createPrivateKey } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, arr) => {
    if (a.startsWith("--")) {
      acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : "true"]);
    }
    return acc;
  }, [])
);

const ref = args.ref;
if (!ref) {
  console.error("Usage: node tools/license/sign.mjs --ref <order-id> [--key tools/license/keys/private.pem] [--sku pro|team] [--copies 1]");
  process.exit(1);
}
const keyPath = args.key || join(import.meta.dirname, "keys", "private.pem");
const sku = args.sku || "pro";
if (sku !== "pro" && sku !== "team" && sku !== "premium") {
  console.error("sku must be pro, team, or premium");
  process.exit(1);
}

const copies = args.copies == null ? 1 : Number(args.copies);
if (!Number.isInteger(copies) || copies < 1 || copies > 50) {
  console.error("copies must be a whole number from 1 to 50");
  process.exit(1);
}

const key = createPrivateKey(readFileSync(keyPath));
const b64url = (b) => b.toString("base64url");
const iat = Math.floor(Date.now() / 1000);
for (let n = 1; n <= copies; n++) {
  const copyRef = copies === 1 ? ref : `${ref}-${n}`;
  const payload = Buffer.from(JSON.stringify({ sku, iat, ref: copyRef }), "utf8");
  const signer = createSign("SHA256");
  signer.update(payload);
  const sig = signer.sign({ key, dsaEncoding: "der" });
  console.log(`NULLCLOUD-${b64url(payload)}.${b64url(sig)}`);
}
