# Contributing to Nullcloud

Thanks for your interest in Nullcloud!

## Core Principles

1. **On-Device, No Cloud AI:** Every analysis runs on the user's own phone or computer. Never describe the project as "air-gapped" (phones connect to the internet); always describe it accurately as **"on-device, no cloud AI"** with **Airplane Mode** support.
2. **Android Share Sheet First:** The Android Share Sheet -> Termux -> summary notification workflow is our primary unique wedge. Keep it fast, reliable, and extension-free.
3. **Unified Simplicity:** `bash setup.sh` must deploy all three entry points (Browser Extension backend, Web UI, and Android Share Sheet) cleanly.
4. **Mobile CPU + GPU Speed (5–15+ tok/s):** Keep default prompts, GPU layer offload (`-ngl`), and CPU thread/context budgets lean so Llama 3.2 1B (4GB RAM) and 3B (6GB+ RAM) run smoothly on real phones.

## Development & Testing

1. Install Python 3 and dependencies:
   ```bash
   pip install -r server/requirements.txt pytest
   ```
2. Run the automated test suite and QA gate:
   ```bash
   pytest
   bash tools/qa/verify-all.sh
   ```
3. Do not commit secrets, private signing keys (`private.pem`), tokens, or model weights (`.gguf`).
4. By contributing, you agree that your work is released under the [MIT License](LICENSE).
