#!/usr/bin/env bash
# Unified Nullcloud Setup Script — Automatically detects Termux (Android) vs Desktop (macOS/Linux)
# and deploys all entry points (Browser Extension backend, Web UI, and Android Share Sheet).
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -n "${TERMUX_VERSION:-}" ] || [ -d "/data/data/com.termux/files/usr" ]; then
  echo "Detected Android Termux environment -> Running mobile hyper-optimized setup..."
  exec bash "$ROOT/termux/setup.sh" "$@"
else
  echo "Detected Desktop environment ($(uname -s)) -> Running desktop setup & server..."
  exec bash "$ROOT/desktop/start.sh" "$@"
fi
