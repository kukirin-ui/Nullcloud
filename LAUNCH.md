# Worldwide Launch & Monetization Playbook

## Positioning & Core Rules

1. **Own the "Airplane Mode" Niche:**
   - Emphasize that the AI runs **100% offline on a phone**—a capability very few projects demonstrate live.
   - **Strict Branding Rule:** Never call it "air-gapped" (because a phone connects to the internet). Brand it strictly and consistently as **"on-device, no cloud AI"**.
2. **Double Down on the Android Share Sheet:**
   - The Android Share Sheet integration (`Share -> Termux -> summary notification`) that works in any app without needing a mobile browser extension is our primary unique wedge.
3. **Unified Simplicity:**
   - Maintain the single `bash setup.sh` command that deploys all three entry points at once (Browser Extension backend, Web UI, and Android Share Sheet).
4. **Optimize the Mobile Experience (GPU offload):**
   - Pre-configure `Llama-3.2-1B-Instruct Q4_K_M` (under ~5.5 GB RAM) and `Llama-3.2-3B-Instruct Q4_K_M` (6 GB+ RAM) with GPU layer offload (`-ngl`, Vulkan). Tested on Exynos with GPU (Vulkan).

---

## Monetization Execution Plan

### 1. Target High-Compliance Consulting First (Fastest Path to Early Revenue)
- **Who:** Law firms, investigative journalists/newsrooms, and medical clinics (`docs/CONSULTING.md`).
- **Why they pay:** Strict data-handling, attorney-client privilege, confidential source protection, and clinical privacy rules forbid pasting sensitive documents into cloud LLMs.
- **Offer:** Fixed-scope turn-key onboarding, hardware-tuned mobile + workstation installation, Tailscale Private Cloud fleet setup, and bespoke domain prompt presets.

### 2. Sell Services, Not Features
Nullcloud is 100% free (library, PDF, presets and Private Cloud included). Income comes only from optional services:
  - Remote setup, €30: https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4
  - Setup + priority support, €45: https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52
  - Private Cloud (Tailscale) setup €60-80 and team setup from €250: email Pozun.alen96@gmail.com for a quote.
- **Flow:** The buyer pays via the link, then emails Pozun.alen96@gmail.com with the payment confirmation to book a time.

### 3. Free Core for Distribution
- Everything stays MIT-licensed and free, so it spreads on Hacker News, `r/LocalLLaMA`, `r/termux`, `r/privacy`, and `r/selfhosted`.
- Optional donations via Revolut (link in the README).

---

## Hero Assets Before Posting

1. **20-Second "Airplane Mode" Video:**
   - Show phone -> swipe down Quick Settings -> **Airplane Mode ON** -> tap Share -> Termux (or click Run in Web UI) -> summary streams in -> notification pops up.
2. **Real Device Benchmarks (`bash termux/bench.sh 20`):**
   - Run 20 iterations in Airplane Mode with charger unplugged and record tok/s, seconds/article, battery drop, and temperature delta.

---

## Launch Schedule

| Day | Channel | Angle |
|---|---|---|
| **Day 1** (Tue–Thu, 14:00–16:00 UTC) | **Hacker News (`Show HN`)** | *"Show HN: Nullcloud – Summarize any page with an LLM running on your phone (on-device, no cloud AI)"* |
| **Day 1** | **`r/LocalLLaMA`** | Real `bench.sh` numbers from an Exynos phone with GPU (Vulkan) offload, battery/thermal numbers |
| **Day 2** | **`r/termux`, `r/selfhosted`, `r/privacy`** | Tailored posts: `termux-url-opener` share sheet, Tailscale Private Cloud, zero telemetry |
| **Day 2** | **`r/androidapps`, XDA Forums** | Android Share Sheet -> private summary notification in any browser without extensions |
| **Day 3** | **X, Mastodon, Bluesky** | 20-second Airplane Mode video + benchmark table + repo link |
| **Days 4–7** | **Product Hunt, Dev.to** | *"How I turned my Android phone into a private Tailscale AI server running Llama 3.2"* |
