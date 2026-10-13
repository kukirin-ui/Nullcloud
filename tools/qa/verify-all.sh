#!/usr/bin/env bash
# Quality & Architecture Gate for Nullcloud
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "== 1. Checking syntax of all shell scripts =="
for sh_file in setup.sh desktop/start.sh termux/setup.sh termux/start.sh termux/stop.sh termux/bench.sh termux/termux-url-opener; do
  bash -n "$sh_file"
  echo "  [OK] $sh_file"
done

echo "== 2. Checking strict branding ('on-device, no cloud AI', never claiming to be 'air-gapped') =="
if grep -rn "air-gapped" server/ extension/ termux/ desktop/ docs/ >/dev/null 2>&1; then
  echo "FAIL: Found forbidden 'air-gapped' claim in code/docs"
  exit 1
fi
grep -q "on-device, no cloud AI" README.md
grep -q "on-device, no cloud AI" server/server.py
echo "  [OK] Branding verified"

echo "== 3. Checking Extension MV3 manifest & files =="
python3 -c '
import json, pathlib
m = json.loads(pathlib.Path("extension/manifest.json").read_text())
assert m["manifest_version"] == 3
assert "CHANGE-ME" not in json.dumps(m), "Placeholder gecko ID still present"
for icon in ("16.png", "48.png", "128.png"):
    assert pathlib.Path("extension/icons/" + icon).is_file()
'
echo "  [OK] Extension manifest valid"

echo "== 4. Testing offline ECDSA P-256 license tools (keygen, sign, verify) =="
TMP_KEYS="$(mktemp -d)"
trap 'rm -rf "$TMP_KEYS"' EXIT
node tools/license/keygen.mjs "$TMP_KEYS" >/dev/null
KEY_PRO="$(node tools/license/sign.mjs --ref QA-100 --key "$TMP_KEYS/private.pem" --sku pro)"
node tools/license/verify.mjs "$KEY_PRO" --pub "$TMP_KEYS/public.b64" >/dev/null
KEYS_2="$(node tools/license/sign.mjs --ref QA-200 --key "$TMP_KEYS/private.pem" --sku pro --copies 2)"
[ "$(printf '%s\n' "$KEYS_2" | wc -l)" -eq 2 ]
echo "  [OK] Offline P-256 license tools verified"

echo "== 5. Running pytest suite =="
python3 -m pytest -q
echo "== All Nullcloud QA checks passed! =="
