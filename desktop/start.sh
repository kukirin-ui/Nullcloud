#!/usr/bin/env bash
# macOS / Linux. Needs Ollama (https://ollama.com/download) and Python 3.
# Enables CPU + GPU acceleration (Apple Metal, NVIDIA CUDA, AMD ROCm, or Vulkan) + Flash-Attention & KV-cache quantization.
# Set TAILSCALE=1 or HOST=<tailscale-ip> to expose over your private Tailscale network.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${MODEL:-llama3.2:3b}"
GPU_LAYERS="${GPU_LAYERS:-99}"

# Detect Desktop GPU Backend
GPU_NAME="Auto GPU (Metal/CUDA/ROCm/Vulkan)"
if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  GPU_NAME="Apple Silicon Metal GPU"
elif command -v nvidia-smi >/dev/null 2>&1; then
  NV_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 | tr -d '\r\n')"
  [ -n "$NV_NAME" ] && GPU_NAME="NVIDIA CUDA ($NV_NAME)"
elif command -v rocminfo >/dev/null 2>&1; then
  GPU_NAME="AMD ROCm GPU"
fi

export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
export OLLAMA_KV_CACHE_TYPE="${OLLAMA_KV_CACHE_TYPE:-q8_0}"

command -v ollama >/dev/null || { echo "Install Ollama first: https://ollama.com/download"; exit 1; }
ollama list >/dev/null 2>&1 || { (ollama serve >/dev/null 2>&1 &); sleep 3; }
ollama pull "$MODEL"
python3 -m pip install -q -r "$ROOT/server/requirements.txt"
if [ ! -f "$HOME/.nullcloud-token" ]; then
  head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$HOME/.nullcloud-token"
  chmod 600 "$HOME/.nullcloud-token"
fi

BIND_HOST="${HOST:-127.0.0.1}"
if [ "${TAILSCALE:-0}" = "1" ] && command -v tailscale >/dev/null 2>&1; then
  TS_IP="$(tailscale ip -4 2>/dev/null | head -n 1 | tr -d ' \r\n')"
  [ -n "$TS_IP" ] && BIND_HOST="$TS_IP"
fi

ACCEL_ACTIVE="CPU + GPU ($GPU_NAME, -ngl $GPU_LAYERS, Flash-Attn, KV $OLLAMA_KV_CACHE_TYPE)"
echo "Nullcloud (on-device, no cloud AI)"
echo "Compute: $ACCEL_ACTIVE"
echo "Web UI:  http://${BIND_HOST}:8080"
echo "Token:   $(cat "$HOME/.nullcloud-token")"
HOST="$BIND_HOST" LLM_URL=http://127.0.0.1:11434/v1/chat/completions MODEL="$MODEL" TOKEN="$(cat "$HOME/.nullcloud-token")" \
  GPU_LAYERS="$GPU_LAYERS" GPU_NAME="$GPU_NAME" ACCEL_MODE="$ACCEL_ACTIVE" \
  python3 "$ROOT/server/server.py"
