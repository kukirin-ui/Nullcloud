# Nullcloud — On-Device, No Cloud AI for Any Page or PDF

[![License: MIT](https://img.shields.io/badge/License-MIT-0d9488.svg)](LICENSE)
[![On-Device AI](https://img.shields.io/badge/AI-On--Device%20%7C%20No%20Cloud-0f172a.svg)](#airplane-mode--offline-niche)
[![Sponsor](https://img.shields.io/badge/Sponsor-GitHub-ea4aaa.svg)](.github/FUNDING.yml)

> **AI that reads the web for you — without the web reading you.**
> Strictly **on-device, no cloud AI**. Summarize, fact-extract, translate, or question any web page, text selection, or PDF using a local model running on your own phone or computer. Works completely offline in **Airplane Mode**.

---

## Why Nullcloud Stands Out

1. **Own the "Airplane Mode" Niche (On-Device, No Cloud AI):**
   Unlike cloud wrappers, Nullcloud runs the LLM directly on your phone (`127.0.0.1`). Open an article, switch your phone to **Airplane Mode**, and stream a summary or ask questions with zero network connection. *(We never call this "air-gapped" because your phone connects to the internet when you browse—it is strictly **on-device, no cloud AI**.)*
2. **Android Share Sheet -> Instant Summary Notification (No Extension Needed):**
   In **any** Android browser or app, tap **Share -> Termux**, pick an action (*Summarize*, *Key facts*, *Claims check*, *Read aloud*), and receive a summary notification with **Copy** and **Open UI** buttons. No mobile browser extension required.
3. **Unified One-Command Setup (`bash setup.sh`):**
   A single setup command automatically detects Android Termux vs Desktop (macOS/Linux) and deploys all three entry points at once:
   - **Android Share Sheet** (`~/bin/termux-url-opener`)
   - **Web UI & Productivity Hub** (`http://127.0.0.1:8080` — works in any browser)
   - **Browser Extension** (Chrome, Brave, Edge, Firefox)
4. **Hyper-Optimized Mobile CPU + GPU Experience (5–15+ tok/s Out of the Box):**
   `termux/setup.sh` inspects `/proc/meminfo` and your mobile GPU (Snapdragon **Adreno**, Arm **Mali / Immortalis**, or **Vulkan / OpenCL** ICD), automatically configuring `Llama-3.2-1B-Instruct Q4_K_M` on **4 GB RAM** devices or `Llama-3.2-3B-Instruct Q4_K_M` on **6 GB+ RAM** devices with GPU layer offload (`-ngl 99`), ARM64 NEON/dotprod big.LITTLE CPU thread capping, Flash-Attention (`--flash-attn`), quantized KV cache (`q8_0`/`q4_0`), and a 45°C battery thermal guard.

---

## Quick Start — Unified Setup

### Option A: Android Phone (Termux — Share Sheet + Web UI + Private Cloud)

**Requirements:** 4 GB+ RAM Android phone (~6 GB recommended for 3B model), ~2.5 GB free storage, Wi-Fi for the one-time model download.

1. Install **Termux** and **Termux:API** from **F-Droid** (not Play Store):
   - [Termux on F-Droid](https://f-droid.org/packages/com.termux/)
   - [Termux:API on F-Droid](https://f-droid.org/packages/com.termux.api/)
2. In Termux, run the unified setup command:
   ```bash
   pkg install -y git && git clone https://github.com/kukirin-ui/Nullcloud ~/nullcloud && bash ~/nullcloud/setup.sh
   ```
   *(To force the fast 1B model on any phone: `MODEL_TIER=1b bash ~/nullcloud/setup.sh`; to compile `llama.cpp` from source with full mobile Vulkan GPU shaders: `BUILD_VULKAN=1 bash ~/nullcloud/setup.sh`)*
3. Start Nullcloud:
   ```bash
   bash ~/nullcloud/termux/start.sh
   ```
4. **Use any of the 3 entry points:**
   - **Android Share Sheet:** In any app or browser, tap **Share -> Termux** -> pick **Summarize** -> get an on-device summary notification.
   - **Web UI:** Open `http://127.0.0.1:8080` in any browser on your phone, paste your token once, and run.
   - **Airplane Mode Test:** Open an article or paste text/PDF into the Web UI, turn on **Airplane Mode**, and press **Run On-Device**.
5. Set **Android Settings -> Apps -> Termux -> Battery -> Unrestricted** so Android does not kill background generation.

### Option B: Desktop (macOS / Linux / Windows)

1. Install [Ollama](https://ollama.com/download) and Python 3.
2. Run the unified setup & start script:
   - **macOS / Linux:** `bash setup.sh` (or `bash desktop/start.sh`)
   - **Windows:** `desktop\start.bat`
3. Load the Browser Extension:
   - Open `chrome://extensions` -> enable **Developer mode** -> **Load unpacked** -> select the `extension/` folder.
   - Open any web page (even offline in Airplane Mode), click **Nullcloud**, paste your token once, and click **Run on this page**.

---

## Mobile & Desktop Hyper-Optimization (CPU + GPU Hybrid Engine)

Nullcloud tunes **both GPU and CPU** execution paths out of the box—and lets you adjust GPU offload layers (`-ngl`) and CPU threads live inside the Web UI (**Private Cloud & Pro -> CPU & GPU Hardware Acceleration Tweaks**) or Browser Extension:

- **GPU Tweaks:**
  - **Mobile GPU Offload (`-ngl 99` / `16` / `8`):** Auto-detects **Qualcomm Adreno** (`/sys/class/kgsl/kgsl-3d0/gpu_model`), **Arm Mali / Immortalis**, and **Vulkan / OpenCL** drivers. Offloads transformer layers (`-ngl`) and enables `--flash-attn` with automatic progressive fallback to CPU if a prebuilt binary lacks Vulkan kernels.
  - **Desktop GPU Offload:** Auto-detects **Apple Silicon Metal**, **NVIDIA CUDA**, **AMD ROCm**, and **Vulkan**, enabling `OLLAMA_FLASH_ATTENTION=1` and quantized KV cache (`OLLAMA_KV_CACHE_TYPE=q8_0`).
- **CPU Tweaks:**
  - **ARM64 big.LITTLE Thread Capping:** Caps threads to performance cores (`4` threads on 1B / `6` threads on 3B) to prevent efficiency-core thrashing and thermal throttling.
  - **Quantized KV Cache (`q8_0` / `q4_0`) & Micro-Batching (`-b 512 -ub 128`):** Cuts memory bandwidth and prefill latency by ~40% on 4 GB–6 GB RAM phones.

| Device Tier | Auto-Selected Model | Compute (CPU + GPU) | Context (`-c`) | KV Cache | Typical Speed |
|---|---|---|---|---|---|
| **Phone, 4 GB RAM** (`<5.5 GB`) | `Llama-3.2-1B-Instruct Q4_K_M` (~0.8 GB) | 4 big-cores + Adreno/Mali GPU (`-ngl`) | `2048` | `q8_0` / `q4_0` | **10–18 tok/s** |
| **Phone, 6+ GB RAM** (`>=5.5 GB`) | `Llama-3.2-3B-Instruct Q4_K_M` (~2.0 GB) | 6 big-cores + Adreno/Mali GPU (`-ngl`) | `3072` | `q8_0` / `q4_0` | **5–15 tok/s** |
| **Desktop** (macOS/Linux/Win) | `llama3.2:3b` via Ollama (or custom) | Metal / CUDA / ROCm / AVX2 (`-ngl 99`) | `4096+` | `q8_0` + Flash-Attn | **25–80+ tok/s** |

### Measure Your Own Device (`termux/bench.sh`)

Run `bash termux/bench.sh 20` in Airplane Mode with the charger unplugged to measure real end-to-end tok/s, seconds per article, battery drop, and temperature change:

| Device | Model | tok/s | s/article | Battery drop / 20 articles | Temp change |
|---|---|---|---|---|---|
| 6 GB+ Android (Termux) | Llama-3.2-3B Q4_K_M | 5–15 tok/s | ~14–25 s | Measure via `bench.sh 20` | Capped <45°C |
| 4 GB Android (Termux) | Llama-3.2-1B Q4_K_M | 10–18 tok/s | ~8–14 s | Measure via `bench.sh 20` | Capped <45°C |

---

## Free Core vs. Nullcloud Pro & High-Compliance Consulting

The **Free Core** is 100% open-source under the **MIT License**. **Nullcloud Pro** is a one-time offline license. Pay with the Revolut link, then email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) with the payment confirmation. The license key is sent manually.

| Feature | Free Core (MIT) | Nullcloud Pro (One-Time License) | High-Compliance Consulting |
|---|---|---|---|
| **On-Device, No Cloud AI** (Airplane Mode ready) | Yes | Yes | Yes |
| **Android Share Sheet -> Summary Notification** | Yes | Yes (+ Pro Presets & PDF share) | Yes |
| **Web UI (`127.0.0.1:8080`) & Browser Extension** | Yes | Yes | Yes |
| **6 Built-In Modes** (Summary, Facts, Claims, ELI5, Translate, Ask) | Yes | Yes | Yes |
| **Read Aloud (TTS) & Markdown / Obsidian Export** | Yes | Yes | Yes |
| **Saved-Page Library with SQLite FTS5 Search** | — | **Yes (Offline full-text search)** | **Yes** |
| **Offline PDF Input & Document Extraction** | — | **Yes (Upload or Share PDFs)** | **Yes** |
| **Custom Prompt Presets** (Legal, Journalism, Clinical + Custom) | — | **Yes** | **Custom-authored for team** |
| **Private Cloud Mode** (Phone as AI Server for Laptop over Tailscale) | — | **Yes (`TAILSCALE=1`)** | **Managed Tailnet Fleet** |

## Prices

| Offer | Price | Checkout |
|---|---|---|
| **Nullcloud Pro license** | €19 one-time | [Get Pro](https://checkout.revolut.com/pay/d25ddfdd-7351-465b-afb6-c6238f65c575) |
| **Remote setup** | €30 | [Remote setup](https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4) |
| **Pro + setup bundle** | €45 | [Pro + setup](https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52) |
| **Tailscale private cloud** | €60-80 | Email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) for a quote |
| **Team consulting** | from €250 | Email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) for a quote |

Pay via the link, then email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) with the payment confirmation. The license key is sent manually.

### Selling the "Private Cloud": Turn Your Phone into Your Laptop's Private AI Server

With **Nullcloud Pro** and [Tailscale](https://tailscale.com), your phone acts as a personal, encrypted AI server accessible from your laptop or iPad:

1. On your Android phone in Termux:
   ```bash
   TAILSCALE=1 bash ~/nullcloud/termux/start.sh
   ```
2. Nullcloud binds to your phone's `100.x.y.z` Tailscale address while keeping `llama-server` locked to `127.0.0.1:8081`.
3. On your laptop, open the Nullcloud Browser Extension -> **Private Cloud / Tailscale & Pro Settings** -> enter `http://<phone-tailscale-ip>:8080` and your token.

### High-Compliance Consulting (Law Firms, Journalists, Medical Clinics)

Need turn-key deployment of **on-device, no cloud AI** for privileged legal discovery, investigative source protection, or clinical literature workflows?
- Read **[`docs/CONSULTING.md`](docs/CONSULTING.md)** for vertical presets, threat models, and deployment packages.
- Read **[`docs/MONETIZATION.md`](docs/MONETIZATION.md)** for the price table, Revolut checkout, and offline ECDSA P-256 license issuance.

---

## How Nullcloud Compares

| Capability | Nullcloud | Page Assist | Cloud AI Extensions |
|---|---|---|---|
| **Branding & Architecture** | **On-device, no cloud AI** | Local / Ollama | Cloud APIs |
| **Android Share Sheet -> Summary Notification** | **Yes (No extension needed)** | Not offered | Requires app/cloud |
| **Runs 100% Offline in Airplane Mode on Phone** | **Yes (Termux + 1B/3B GGUF)** | Desktop-focused | No |
| **Phone as Private Cloud Server over Tailscale** | **Yes (Pro)** | Manual | N/A |
| **Offline Saved-Page FTS5 Library & PDF Input** | **Yes (Pro)** | Chat history | Cloud-stored |
| **Markdown / Obsidian Vault Auto-Export** | **Yes (`NOTES_DIR`)** | No | No |

---

## Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TOKEN` | `~/.nullcloud-token` | Required secret token sent in `X-Token` header |
| `HOST` | `127.0.0.1` | Bind address (`TAILSCALE=1` auto-selects your `100.x.y.z` Tailscale IP) |
| `PORT` | `8080` | Web UI and HTTP API port |
| `LLM_URL` | `http://127.0.0.1:8081/v1/chat/completions` | Local OpenAI-compatible completion endpoint (`llama-server` or Ollama) |
| `MODEL_TIER` | Auto (`1b` or `3b`) | Force `1b` (4 GB RAM) or `3b` (6 GB+ RAM) in `termux/setup.sh` |
| `GPU_LAYERS` | `99` (`0` for CPU-only) | Number of transformer layers offloaded to GPU (`-ngl` / `num_gpu`) |
| `CPU_THREADS` | Auto (`4` on 1B, `6` on 3B) | Number of CPU performance threads used for prompt evaluation & generation |
| `BUILD_VULKAN` | `0` | Set `BUILD_VULKAN=1` during `termux/setup.sh` to compile `llama-server` with mobile Vulkan GPU shaders |
| `MAX_CHARS` | `6000` (`4500` on 1B) | Maximum extracted page/PDF characters sent to local model |
| `MAX_TOKENS` | `400` (`300` on 1B) | Maximum generated completion tokens |
| `NOTES_DIR` | *(disabled)* | Opt-in path to save every output as `.md` (e.g. Obsidian vault) |
| `ARCHIVE` | `0` | Set `ARCHIVE=1` with `NOTES_DIR` to cache raw HTML for offline re-reading |

---

## Support the Project

- **GitHub Sponsors:** [github.com/sponsors/kukirin-ui](https://github.com/sponsors/kukirin-ui)
- **Nullcloud Pro (€19):** [Revolut checkout](https://checkout.revolut.com/pay/d25ddfdd-7351-465b-afb6-c6238f65c575)
- **Sibling Project:** Check out **[Meridian](https://github.com/kukirin-ui/Meridian)** — the open-source Android command deck and local AI mesh for Termux.

## License

[MIT License](LICENSE) © 2026 Alen Požun (kukirin-ui)
