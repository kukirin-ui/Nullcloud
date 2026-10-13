#!/data/data/com.termux/files/usr/bin/bash
# Start Nullcloud on Android (Termux): CPU + GPU hyper-optimized llama-server + local API server.
# Set TAILSCALE=1 to bind to your phone's Tailscale IPv4 for Private Cloud laptop access.
# Set GPU_LAYERS=0 for CPU-only, or GPU_LAYERS=99 (default) for Vulkan/OpenCL mobile GPU offload.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOKEN="$(cat "$HOME/.nullcloud-token")"
[ -f "$HOME/.nullcloud-profile.env" ] && . "$HOME/.nullcloud-profile.env"

CTX_SIZE="${CTX_SIZE:-3072}"
MAX_CHARS="${MAX_CHARS:-6000}"
MAX_TOKENS="${MAX_TOKENS:-400}"
MODEL_NAME="${MODEL_NAME:-Llama-3.2-3B-Instruct-Q4_K_M}"
GPU_LAYERS="${GPU_LAYERS:-99}"
GPU_NAME="${GPU_NAME:-Mobile GPU (Vulkan/OpenCL)}"

# CPU tweak: detect big/performance cores, cap at 4 on 1B profile or 6 on 3B profile for optimal tok/s & thermals
CORES="$(nproc 2>/dev/null || echo 4)"
if [ "${MODEL_TIER:-3b}" = "1b" ]; then
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

# Tier 1: GPU offload (-ngl) + quantized KV cache (q8_0/q4_0) + Flash-Attention + CPU big-core threads
ACCEL_ACTIVE="CPU ($THREADS threads) + GPU ($GPU_NAME, -ngl $GPU_LAYERS, KV q8_0/q4_0, Flash-Attn)"
if [ "$GPU_LAYERS" -gt 0 ] 2>/dev/null; then
  nohup llama-server -m "$HOME/nullcloud-models/model.gguf" \
    -c "$CTX_SIZE" -t "$THREADS" -ngl "$GPU_LAYERS" -b 512 -ub 128 \
    --cache-type-k q8_0 --cache-type-v q4_0 --flash-attn \
    --host 127.0.0.1 --port 8081 > "$HOME/nullcloud-llm.log" 2>&1 &
  sleep 1
fi

# Tier 2 fallback: CPU-optimized quantized KV cache + Flash-Attention (if GPU offload not compiled or GPU_LAYERS=0)
if ! pgrep -f "llama-server.*--port 8081" >/dev/null 2>&1; then
  ACCEL_ACTIVE="CPU ($THREADS big-cores, NEON/dotprod, KV q8_0/q4_0, Flash-Attn)"
  nohup llama-server -m "$HOME/nullcloud-models/model.gguf" \
    -c "$CTX_SIZE" -t "$THREADS" -b 512 -ub 128 \
    --cache-type-k q8_0 --cache-type-v q4_0 --flash-attn \
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
