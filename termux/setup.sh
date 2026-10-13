#!/data/data/com.termux/files/usr/bin/bash
# Nullcloud Termux Setup — Unified One-Command Installer (Share Sheet + Web UI + Extension Backend)
# Pre-configures Llama 3.2 1B (under ~5.5 GB RAM) or 3B (6 GB+ RAM) with GPU offload. Tested on Exynos with Vulkan.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$HOME/nullcloud-models"; mkdir -p "$MODELS"

URL_3B="https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf"
URL_1B="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"

# Auto-detect device RAM from /proc/meminfo (in kB)
MEM_KB="$(awk '/MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 6000000)"
MEM_GB="$(awk "BEGIN{printf \"%.1f\", $MEM_KB / 1048576}")"

# Rough GPU guess from sysfs; replaced by llama.cpp's real Vulkan device name after install
GPU_NAME="Mobile GPU (Vulkan)"
if [ -r /sys/class/kgsl/kgsl-3d0/gpu_model ]; then
  GPU_NAME="Adreno $(tr -d '\0\r\n' < /sys/class/kgsl/kgsl-3d0/gpu_model)"
elif [ -d /sys/class/misc/mali0 ] || [ -e /dev/mali0 ]; then
  GPU_NAME="Arm Mali / Immortalis GPU"
elif [ -d /vendor/etc/vulkan/icd.d ] || [ -d /system/vendor/etc/vulkan/icd.d ]; then
  ICD="$(ls /vendor/etc/vulkan/icd.d /system/vendor/etc/vulkan/icd.d 2>/dev/null | head -n 1 | tr -d '\r\n')"
  [ -n "$ICD" ] && GPU_NAME="Vulkan ($ICD)"
fi
GPU_LAYERS="${GPU_LAYERS:-99}"

if [ -n "$MODEL_TIER" ]; then
  TIER="$MODEL_TIER"
elif [ "$MEM_KB" -lt 5500000 ]; then
  TIER="1b"
else
  TIER="3b"
fi

if [ "$TIER" = "1b" ]; then
  DEFAULT_URL="$URL_1B"
  CTX_SIZE=2048
  MAX_CHARS=4500
  MAX_TOKENS=300
  MODEL_NAME="Llama-3.2-1B-Instruct-Q4_K_M"
else
  DEFAULT_URL="$URL_3B"
  CTX_SIZE=3072
  MAX_CHARS=6000
  MAX_TOKENS=400
  MODEL_NAME="Llama-3.2-3B-Instruct-Q4_K_M"
fi

MODEL_URL="${MODEL_URL:-$DEFAULT_URL}"

echo "== Nullcloud On-Device AI Setup (GPU-first, Vulkan) =="
echo "Detected RAM: ${MEM_GB} GB | GPU: ${GPU_NAME}"
echo "Selecting ${MODEL_NAME} profile (run termux/bench.sh to measure speed)"

pkg update -y && pkg upgrade -y
pkg install -y python curl wget jq termux-api unzip poppler

# Prefer the packaged llama.cpp with the Vulkan backend (no compiling needed).
# vulkan-loader-android uses the phone's real GPU driver; vulkan-loader-generic does not.
pkg uninstall -y vulkan-loader-generic 2>/dev/null || true
pkg install -y vulkan-loader-android 2>/dev/null || true
pkg install -y llama-cpp llama-cpp-backend-vulkan 2>/dev/null || pkg install -y llama-cpp 2>/dev/null || true

if [ "${BUILD_VULKAN:-0}" = "1" ] || ! command -v llama-server >/dev/null; then
  echo "Building llama.cpp from source with Vulkan GPU acceleration (-DGGML_VULKAN=ON)..."
  pkg install -y git cmake clang vulkan-headers vulkan-loader-android shaderc
  SRC_DIR="$HOME/.cache/llama.cpp-vulkan"
  rm -rf "$SRC_DIR"
  git clone --depth 1 https://github.com/ggerganov/llama.cpp "$SRC_DIR"
  cmake -S "$SRC_DIR" -B "$SRC_DIR/build" -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build "$SRC_DIR/build" --target llama-server -j"$(nproc 2>/dev/null || echo 4)"
  cp "$SRC_DIR/build/bin/llama-server" "$PREFIX/bin/llama-server"
fi

# Ask llama.cpp for the real GPU name (e.g. "Vulkan0: Samsung Xclipse 960 (...)" -> "Samsung Xclipse 960")
detect_llama_gpu() {
  command -v llama-server >/dev/null 2>&1 || return 0
  llama-server --list-devices 2>/dev/null | sed -n 's/^[[:space:]]*Vulkan0:[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*(.*/\1/p' | head -n 1
}
DETECTED_GPU="$(detect_llama_gpu)"
if [ -n "$DETECTED_GPU" ]; then
  GPU_NAME="$DETECTED_GPU"
  echo "llama.cpp Vulkan device: $GPU_NAME"
else
  echo "!! llama.cpp sees no Vulkan GPU. Check with: llama-server --list-devices (see README Troubleshooting)"
fi
pip install -r "$ROOT/server/requirements.txt"

if [ ! -f "$MODELS/model.gguf" ]; then
  echo "Downloading $MODEL_NAME (~1-2 GB one-time download)..."
  wget -c -O "$MODELS/model.gguf.part" "$MODEL_URL" && mv "$MODELS/model.gguf.part" "$MODELS/model.gguf"
fi

if [ ! -f "$HOME/.nullcloud-token" ]; then
  head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$HOME/.nullcloud-token"
  chmod 600 "$HOME/.nullcloud-token"
fi

cat > "$HOME/.nullcloud-profile.env" <<EOF
MODEL_TIER=$TIER
MODEL_NAME=$MODEL_NAME
CTX_SIZE=$CTX_SIZE
MAX_CHARS=$MAX_CHARS
MAX_TOKENS=$MAX_TOKENS
GPU_NAME="$GPU_NAME"
GPU_LAYERS=$GPU_LAYERS
EOF
chmod 600 "$HOME/.nullcloud-profile.env"

# Deploy Android Share Sheet integration ("Share -> Termux" -> summary notification)
mkdir -p "$HOME/bin"
cp "$ROOT/termux/termux-url-opener" "$HOME/bin/termux-url-opener"
chmod +x "$HOME/bin/termux-url-opener" "$ROOT/termux/start.sh" "$ROOT/termux/stop.sh" "$ROOT/termux/bench.sh"
echo "$ROOT" > "$HOME/.nullcloud-root"

echo
echo "== Setup complete (On-Device, No Cloud AI) =="
echo "Profile:     $MODEL_NAME (CTX=$CTX_SIZE, MAX_CHARS=$MAX_CHARS)"
echo "Compute:     GPU offload ($GPU_NAME, -ngl $GPU_LAYERS, Vulkan), THREADS=2 recommended"
echo "Your token:  $(cat "$HOME/.nullcloud-token")"
echo "Start:       bash $ROOT/termux/start.sh"
echo "Entry points ready:"
echo "  1. Android Share Sheet: Share any link or text -> Termux -> instant summary notification"
echo "  2. Web UI:              http://127.0.0.1:8080 (works in any browser, even in Airplane Mode)"
echo "  3. Browser Extension:   Load extension/ or connect laptop via Tailscale Private Cloud"
