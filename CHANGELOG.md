# Changelog

All notable changes to this project are documented here.

## [2.0.0] - 2026-10-13

### Changed
- **Nullcloud is now completely free.** Library, PDF input, custom presets and Private Cloud work for everyone. No license key, no paywall.
- Removed the Pro license (ECDSA key check, `/pro/status`, `/pro/activate`, `tools/license/`). Added `GET /features`.
- Income is from optional services only: remote setup €30, setup + priority support €45, Private Cloud (Tailscale) setup €60-80 and team setup from €250 (quote by email).
- README: honest hardware notes (tested on Exynos with GPU/Vulkan), removed unmeasured speed tables, added Termux troubleshooting, replaced the broken Sponsor badge with an optional Revolut donation link.

## [1.2.0] - 2026-10-13

### Changed
- Product name is **Nullcloud** everywhere (UI, extension, scripts, docs, license prefix `NULLCLOUD-`, and local paths such as `~/.nullcloud-pro.key` and `~/nullcloud-models`).
- Pro, remote setup, and the Pro + setup bundle are sold only through fixed Revolut checkout links (€19, €30, and €45). Tailscale private cloud (€60-80) and team consulting (from €250) are quoted by email. The buyer pays, then emails the payment confirmation; the license key is sent manually.

## [1.1.0] - 2026-10-13

### Added
- **Unified One-Command Setup (`setup.sh`):** Auto-detects Android Termux vs Desktop (macOS/Linux) and deploys all three entry points (Android Share Sheet, Web UI, and Browser Extension).
- **Mobile & Desktop CPU + GPU Hyper-Optimization (`termux/setup.sh`, `termux/start.sh`, `desktop/start.sh`):** Automatically detects 4GB RAM (`Llama-3.2-1B-Instruct Q4_K_M`) vs 6GB+ RAM (`Llama-3.2-3B-Instruct Q4_K_M`), detects mobile/desktop GPUs (Snapdragon Adreno, Arm Mali/Immortalis, Apple Metal, NVIDIA CUDA, AMD ROCm, Vulkan/OpenCL), enables GPU layer offload (`-ngl`), Flash-Attention (`--flash-attn`), quantized KV cache (`q8_0`/`q4_0`), and caps CPU big.LITTLE performance threads for sustained 5–15+ tok/s on-device.
- **In-App CPU + GPU Tuning Controls (`server/server.py`, `server/ui.html`, `extension/`):** Added `/hardware` endpoint and live UI controls to switch between Full GPU Offload (`-ngl 99`), Balanced Hybrid CPU+GPU (`-ngl 16`), Light Mobile GPU Assist (`-ngl 8`), and CPU-Only (`-ngl 0`), plus CPU thread count tuning.
- **Airplane Mode & Offline Enhancements:** Cached/saved page lookup when offline in URL mode, direct text/PDF analysis in Airplane Mode, and full-page offline extraction from open browser tabs.
- **Enhanced Android Share Sheet (`termux/termux-url-opener`):** Supports shared links, selected text, and local PDF files; adds thermal safety guard (45°C pause) and interactive notification action buttons (**Copy** and **Open UI**).
- **Nullcloud Pro Productivity Hub & Private Cloud (`server/server.py`, `server/ui.html`, `extension/`):**
  - Offline ECDSA P-256 license verification (`tools/license/keygen.mjs`, `sign.mjs`, `verify.mjs`).
  - Saved-page library with SQLite FTS5 full-text search (`/library`).
  - On-device PDF input extraction (`/analyze` with `pdf_base64`).
  - Custom prompt presets (`/presets`) plus pre-built high-compliance templates for Law Firms, Journalists, and Medical Clinics.
  - Tailscale Private Cloud mode (`TAILSCALE=1`) turning the phone into a private AI server accessible from a laptop.
- **Monetization & Compliance Docs:** Added `docs/CONSULTING.md`, `docs/MONETIZATION.md`, `.github/FUNDING.yml`, CI test suite, and QA gates.
