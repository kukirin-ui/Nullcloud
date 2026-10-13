#!/data/data/com.termux/files/usr/bin/bash
# Battery + CPU/GPU speed benchmark. Usage: bash termux/bench.sh [RUNS] ; env: CAP_MAH=5000
# For comparable numbers: airplane mode, charger unplugged, same screen brightness, battery >= 80%, model server running.
RUNS="${1:-10}"; CAP="${CAP_MAH:-5000}"
[ -f "$HOME/.nullcloud-profile.env" ] && . "$HOME/.nullcloud-profile.env"
LLM=http://127.0.0.1:8081/v1/chat/completions
SAMPLE="$(python - <<'PY'
print("The quick brown fox jumps over the lazy dog near the river bank. " * 85)
PY
)"
PROMPT="$(printf 'PAGE:\n%s\n\nTASK: Summarize the page in 5 bullet points.' "$SAMPLE")"
bat() { termux-battery-status | jq -r '"\(.percentage) \(.temperature)"'; }
read B0 T0 < <(bat)
TOK=0; SEC=0
for i in $(seq 1 "$RUNS"); do
  S=$(date +%s.%N)
  R=$(jq -n --arg p "$PROMPT" '{messages:[{role:"user",content:$p}],max_tokens:200,temperature:0.2}' | \
      curl -s "$LLM" -H 'Content-Type: application/json' -d @-)
  E=$(date +%s.%N)
  C=$(jq -r '.usage.completion_tokens // 0' <<<"$R")
  TOK=$((TOK + C)); SEC=$(awk "BEGIN{print $SEC + $E - $S}")
  echo "run $i: $C tokens"
done
read B1 T1 < <(bat)
echo
echo "== Nullcloud CPU + GPU benchmark =="
echo "model: ${MODEL_NAME:-local} | gpu: ${GPU_NAME:-Mobile GPU} (-ngl ${GPU_LAYERS:-99})"
echo "runs: $RUNS  (each ~1,300-token page in, <=200 tokens out)"
awk "BEGIN{printf \"end-to-end speed: %.1f tok/s (includes page reading)\n\", $TOK/$SEC}"
awk "BEGIN{printf \"avg time per article: %.1f s\n\", $SEC/$RUNS}"
echo "battery: ${B0}% -> ${B1}%  (temp ${T0}C -> ${T1}C)"
awk "BEGIN{d=$B0-$B1; printf \"drop: %d%% over %d articles = ~%.1f mAh/article at %d mAh (battery %% is coarse; use RUNS>=20)\n\", d, $RUNS, d/100*$CAP/$RUNS, $CAP}"
