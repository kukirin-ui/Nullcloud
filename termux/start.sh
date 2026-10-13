#!/data/data/com.termux/files/usr/bin/bash
# Start Nullcloud on Android (Termux): GPU-first (Vulkan) llama-server + local API server.
# Set TAILSCALE=1 to bind to your phone's Tailscale IPv4 for Private Cloud laptop access.
# GPU_LAYERS=99 (default) offloads all layers to the Vulkan GPU. THREADS=2 is recommended with full GPU offload.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOKEN="$(cat "$HOME/.nullcloud-token")"
[ -f "$HOME/.nullcloud-profile.env" ] && . "$HOME/.nullcloud-profile.env"

CTX_SIZE="${CTX_SIZE:-3072}"
MAX_CHARS="${MAX_CHARS:-6000}"
MAX_TOKENS="${MAX_TOKENS:-400}"
MODEL_NAME="${MODEL_NAME:-Llama-3.2-3B-Instruct-Q4_K_M}"
GPU_LAYERS="${GPU_LAYERS:-99}"

# Ask llama.cpp for the real GPU name (e.g. "Vulkan0: Samsung Xclipse 960 (...)" -> "Samsung Xclipse 960")
detect_llama_gpu() {
  command -v llama-server >/dev/null 2>&1 || return 0
  llama-server --list-devices 2>/dev/null | sed -n 's/^[[:space:]]*Vulkan0:[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*(.*/\1/p' | head -n 1
}
case "${GPU_NAME:-}" in
  ""|"Mobile GPU"*|"Vulkan ("*|"Arm Mali / Immortalis GPU")
    DETECTED="$(detect_llama_gpu)"
    if [ -n "$DETECTED" ]; then
      GPU_NAME="$DETECTED"
      PROFILE="$HOME/.nullcloud-profile.env"
      if [ -f "$PROFILE" ] && grep -q '^GPU_NAME=' "$PROFILE"; then
        sed -i "s|^GPU_NAME=.*|GPU_NAME=\"$GPU_NAME\"|" "$PROFILE"
      else
        echo "GPU_NAME=\"$GPU_NAME\"" >> "$PROFILE"
      fi
    fi
    ;;
esac
GPU_NAME="${GPU_NAME:-Mobile GPU (Vulkan)}"

# Threads: with full GPU offload, 2 threads gave the best prompt speed in real tests
# (Samsung Xclipse 960, Qwen3 4B Q4_K_M: 2 threads pp512 232.3 / tg32 23.2 t/s, 4 threads 228.1 / 21.9, 8 threads 167.8 / 13.8).
CORES="$(nproc 2>/dev/null || echo 4)"
if [ "$GPU_LAYERS" -gt 0 ] 2>/dev/null; then
  DEFAULT_THREADS=2
elif [ "${MODEL_TIER:-3b}" = "1b" ]; then
  DEFAULT_THREADS=$(( CORES > 4 ? 4 : CORES ))
else
  DEFAULT_THREADS=$(( CORES > 6 ? 6 : CORES ))
fi
THREADS="${THREADS:-$DEFAULT_THREADS}"

BIND_HOST="${HOST:-127.0.0.1}"
if [ "${TAILSCALE:-0}" = "1" ] && command -v tailscale >/dev/null 2>&1; then
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 | tr -d ' \r\n')"
  if [ -n "$TS_IP" ]; then
    BIND_HOST="$TS_IP"
  fi
fi

termux-wake-lock 2>/dev/null
pkill -f "llama-server.*--port 8081" 2>/dev/null
pkill -f "server/server.py" 2>/dev/null

# Tier 1: GPU offload (-ngl) + quantized KV cache (q8_0/q4_0) + Flash-Attention
ACCEL_ACTIVE="GPU ($GPU_NAME, -ngl $GPU_LAYERS, KV q8_0/q4_0, Flash-Attn, $THREADS threads)"
if [ "$GPU_LAYERS" -gt 0 ] 2>/dev/null; then
  nohup llama-server -m "$HOME/nullcloud-models/model.gguf" \
    -c "$CTX_SIZE" -t "$THREADS" -ngl "$GPU_LAYERS" -b 512 -ub 128 \
    --cache-type-k q8_0 --cache-type-v q4_0 --flash-attn on \
    --host 127.0.0.1 --port 8081 > "$HOME/nullcloud-llm.log" 2>&1 &
  sleep 1
fi

# Tier 1b: GPU offload without Flash-Attention / quantized KV (older or stricter llama.cpp builds)
if [ "$GPU_LAYERS" -gt 0 ] 2>/dev/null && ! pgrep -f "llama-server.*--port 8081" >/dev/null 2>&1; then
  ACCEL_ACTIVE="GPU ($GPU_NAME, -ngl $GPU_LAYERS, $THREADS threads)"
  nohup llama-server -m "$HOME/nullcloud-models/model.gguf" \
    -c "$CTX_SIZE" -t "$THREADS" -ngl "$GPU_LAYERS" \
    --host 127.0.0.1 --port 8081 > "$HOME/nullcloud-llm.log" 2>&1 &
  sleep 1
fi

# Tier 2 fallback: CPU-optimized quantized KV cache + Flash-Attention (if GPU offload not compiled or GPU_LAYERS=0)
if ! pgrep -f "llama-server.*--port 8081" >/dev/null 2>&1; then
  ACCEL_ACTIVE="CPU fallback ($THREADS threads, KV q8_0/q4_0, Flash-Attn) - GPU did not start, see Troubleshooting"
  nohup llama-server -m "$HOME/nullcloud-models/model.gguf" \
    -c "$CTX_SIZE" -t "$THREADS" -b 512 -ub 128 \
    --cache-type-k q8_0 --cache-type-v q4_0 --flash-attn on \
    --host 127.0.0.1 --port 8081 > "$HOME/nullcloud-llm.log" 2>&1 &
  sleep 1
fi

# Tier 3 fallback: Legacy llama-server compatibility
if ! pgrep -f "llama-server.*--port 8081" >/dev/null 2>&1; then
  ACCEL_ACTIVE="CPU ($THREADS threads, standard KV)"
  nohup llama-server -m "$HOME/nullcloud-models/model.gguf" \
    -c "$CTX_SIZE" -t "$THREADS" \
    --host 127.0.0.1 --port 8081 > "$HOME/nullcloud-llm.log" 2>&1 &
fi

echo -n "Loading $MODEL_NAME [$ACCEL_ACTIVE, ctx $CTX_SIZE]"
for i in $(seq 1 90); do
  curl -s http://127.0.0.1:8081/health 2>/dev/null | grep -q ok && break
  echo -n "."; sleep 2
done
echo

HOST="$BIND_HOST" MAX_CHARS="$MAX_CHARS" MAX_TOKENS="$MAX_TOKENS" MODEL="$MODEL_NAME" TOKEN="$TOKEN" \
  CPU_THREADS="$THREADS" GPU_LAYERS="$GPU_LAYERS" GPU_NAME="$GPU_NAME" ACCEL_MODE="$ACCEL_ACTIVE" CTX_SIZE="$CTX_SIZE" \
  nohup python "$ROOT/server/server.py" > "$HOME/nullcloud-api.log" 2>&1 &
sleep 2
echo "Nullcloud is running (on-device, no cloud AI)."
echo "Compute: $ACCEL_ACTIVE"
echo "Web UI:  http://${BIND_HOST}:8080  (works in any browser, even in Airplane Mode)"
echo "Token:   $TOKEN"
