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

echo "== 4. Checking everything is free (no paywall or license gate left) =="
if grep -rn "d25ddfdd\|require_pro\|pro_required\|license_key\|X-License-Key" server/ extension/ termux/ desktop/ docs/ .github/ README.md >/dev/null 2>&1; then
  echo "FAIL: Found leftover Pro paywall / license code"
  exit 1
fi
echo "  [OK] All features free"

echo "== 5. Running pytest suite =="
python3 -m pytest -q
echo "== All Nullcloud QA checks passed! =="
