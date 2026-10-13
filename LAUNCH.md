# Worldwide Launch & Monetization Playbook

## Positioning & Core Rules

1. **Own the "Airplane Mode" Niche:**
   - Emphasize that the AI runs **100% offline on a phone**—a capability very few projects demonstrate live.
   - **Strict Branding Rule:** Never call it "air-gapped" (because a phone connects to the internet). Brand it strictly and consistently as **"on-device, no cloud AI"**.
2. **Double Down on the Android Share Sheet:**
   - The Android Share Sheet integration (`Share -> Termux -> summary notification`) that works in any app without needing a mobile browser extension is our primary unique wedge.
3. **Unified Simplicity:**
   - Maintain the single `bash setup.sh` command that deploys all three entry points at once (Browser Extension backend, Web UI, and Android Share Sheet).
4. **Hyper-Optimize the Mobile Experience (CPU + GPU):**
   - Pre-configure `Llama-3.2-1B-Instruct Q4_K_M` (4 GB RAM) and `Llama-3.2-3B-Instruct Q4_K_M` (6 GB+ RAM) with both **GPU layer offload (`-ngl`, Vulkan / OpenCL on Adreno & Mali)** and **CPU big.LITTLE thread capping + quantized KV cache (`q8_0`/`q4_0`) + Flash-Attention** so phones hit **5–15+ tokens/second** out of the box.

---

## Monetization Execution Plan

### 1. Target High-Compliance Consulting First (Fastest Path to Early Revenue)
- **Who:** Law firms, investigative journalists/newsrooms, and medical clinics (`docs/CONSULTING.md`).
- **Why they pay:** Strict data-handling, attorney-client privilege, confidential source protection, and clinical privacy rules forbid pasting sensitive documents into cloud LLMs.
- **Offer:** Fixed-scope turn-key onboarding, hardware-tuned mobile + workstation installation, Tailscale Private Cloud fleet setup, and bespoke domain prompt presets.

### 2. Ship the Premium Productivity Hub ("Nullcloud Pro")
- **Checkout (Revolut only):**
  - Nullcloud Pro license, €19 one-time: https://checkout.revolut.com/pay/d25ddfdd-7351-465b-afb6-c6238f65c575
  - Remote setup, €30: https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4
  - Pro + setup bundle, €45: https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52
  - Tailscale private cloud (€60-80) and team consulting (from €250): email Pozun.alen96@gmail.com for a quote.
- **Flow:** The buyer pays via the link, then emails Pozun.alen96@gmail.com with the payment confirmation. The license key is sent manually.
- **Offline Cryptographic Key:** Issued with `node tools/license/sign.mjs --ref ORDER-ID --sku pro` and verified 100% offline in `server/server.py` (ECDSA P-256, zero phone-home).
- **Pro Features Locked Behind License:**
  1. **Saved-Page Library with Search:** Local SQLite FTS5 index (`~/.nullcloud-library.db`) searching across titles, URLs, page text, and summaries offline.
  2. **PDF Input Capabilities:** Upload or share any PDF for on-device extraction and summarization.
  3. **Custom Prompt Presets:** Built-in Legal, Journalism, Clinical, and Executive templates plus user-defined presets.
  4. **Private Cloud Server (`TAILSCALE=1`):** Turns the user's phone into an encrypted private AI server accessible from their laptop via Tailscale.

### 3. Leverage the Free MIT Core for Distribution
- Keep the core MIT-licensed with zero crippleware on standard single-page summarization so it spreads organically on Hacker News, `r/LocalLLaMA`, `r/termux`, `r/privacy`, and `r/selfhosted`.
- Enable community support via **GitHub Sponsors** (`.github/FUNDING.yml`). The custom funding link is the €19 Pro checkout.

---

## Hero Assets Before Posting

1. **20-Second "Airplane Mode" Video:**
   - Show phone -> swipe down Quick Settings -> **Airplane Mode ON** -> tap Share -> Termux (or click Run in Web UI) -> summary streams in at 10+ tok/s -> notification pops up.
2. **Real Device Benchmarks (`bash termux/bench.sh 20`):**
   - Run 20 iterations in Airplane Mode with charger unplugged and record tok/s, seconds/article, battery drop, and temperature delta.

---

## Launch Schedule

| Day | Channel | Angle |
|---|---|---|
| **Day 1** (Tue–Thu, 14:00–16:00 UTC) | **Hacker News (`Show HN`)** | *"Show HN: Nullcloud – Summarize any page with an LLM running on your phone (on-device, no cloud AI)"* |
| **Day 1** | **`r/LocalLLaMA`** | Benchmarks: Llama 3.2 1B & 3B tok/s on 4GB–6GB RAM phones (CPU big.LITTLE + Vulkan/OpenCL GPU `-ngl`), KV cache tuning, battery/thermal numbers |
| **Day 2** | **`r/termux`, `r/selfhosted`, `r/privacy`** | Tailored posts: `termux-url-opener` share sheet, Tailscale Private Cloud, zero telemetry |
| **Day 2** | **`r/androidapps`, XDA Forums** | Android Share Sheet -> private summary notification in any browser without extensions |
| **Day 3** | **X, Mastodon, Bluesky** | 20-second Airplane Mode video + benchmark table + repo link |
| **Days 4–7** | **Product Hunt, Dev.to** | *"How I turned my Android phone into a private Tailscale AI server running Llama 3.2"* |
