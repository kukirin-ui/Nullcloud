# Nullcloud Monetization & Product Tiers

Nullcloud follows a transparent, developer-respecting open-core model inspired by [Meridian](https://github.com/kukirin-ui/Meridian):

1. **Free Core (MIT License)** — Built for maximum distribution, trust, and everyday utility.
2. **Nullcloud Pro (€19 one-time, Revolut)** — The Premium Productivity Hub and Tailscale Private Cloud for power users.
3. **Remote setup (€30) and Pro + setup (€45)** — Fixed-price Revolut checkouts.
4. **Tailscale private cloud (€60-80) and team consulting (from €250)** — Email Pozun.alen96@gmail.com for a quote.
5. **Community Support** — GitHub Sponsors for people who want to back the open-source core.

---

## Tier Comparison

| Capability | Free Core (MIT) | Nullcloud Pro (One-Time License) | High-Compliance Consulting |
|---|---|---|---|
| **On-Device, No Cloud AI** (Airplane Mode capable) | Included | Included | Included |
| **Unified One-Command Setup (`bash setup.sh`)** | Included | Included | Turn-key managed setup |
| **3 Entry Points** (Android Share Sheet, Web UI, Browser Extension) | Included | Included | Included |
| **Mobile & Desktop Hyper-Optimization** (Auto 1B/3B Llama GGUF + CPU big.LITTLE + GPU `-ngl` offload) | Included | Included | Custom device tuning |
| **Core Modes** (Summary, Facts, Claims, ELI5, Translate, Ask) | Included | Included | Included |
| **Read Aloud (TTS) & Markdown / Obsidian Note Export** | Included | Included | Included |
| **Saved-Page Library with SQLite FTS5 Search** | — | **Included** | **Included** |
| **Offline PDF Input & Document Extraction** | — | **Included** | **Included** |
| **Custom Prompt Presets** (Legal, Journalism, Clinical + Custom) | — | **Included** | **Custom-authored for team** |
| **Private Cloud Mode** (Phone as AI Server for Laptop via Tailscale) | — | **Included** | **Tailnet ACL & fleet setup** |

---

## Prices

| Offer | Price | Checkout |
|---|---|---|
| **Nullcloud Pro license** | €19 one-time | [Get Pro](https://checkout.revolut.com/pay/d25ddfdd-7351-465b-afb6-c6238f65c575) |
| **Remote setup** | €30 | [Remote setup](https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4) |
| **Pro + setup bundle** | €45 | [Pro + setup](https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52) |
| **Tailscale private cloud** | €60-80 | Email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) for a quote |
| **Team consulting** | from €250 | Email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) for a quote |

Pay via the link, then email [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) with the payment confirmation. The license key is sent manually.

## How Offline Pro Licensing Works (Zero Phone-Home)

Nullcloud Pro uses **100% offline ECDSA P-256 cryptographic signatures**:

1. **Purchase:** The buyer pays with one of the Revolut links above.
2. **Confirmation:** The buyer emails [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com) with the payment confirmation.
3. **Key Issuance:** The maintainer runs `node tools/license/sign.mjs --ref ORDER-1234 --sku pro` with the offline private key (`private.pem`, never committed) and emails this key:
   ```text
   NULLCLOUD-<base64url-payload>.<base64url-ecdsa-signature>
   ```
4. **Offline Verification:** The customer pastes the key into the Nullcloud Web UI (`http://127.0.0.1:8080` -> **Private Cloud & Pro**), the Browser Extension, or `~/.nullcloud-pro.key`.
5. `server/server.py` verifies the ECDSA P-256 signature locally using pure Python stdlib math against `DEFAULT_LICENSE_PUBKEY`. No network call is ever made.

### Issuing & Verifying Keys (Maintainer CLI)

Generate the keypair on your own computer. `tools/license/keys/private.pem` is gitignored. Never commit it, never email it, and keep an offline backup (mode `0600`).

The public key shipped in this repository only verifies keys signed by its matching private key. If you do not already hold that private key, run keygen once, then replace `DEFAULT_LICENSE_PUBKEY` in `server/server.py` and `tools/license/keys/public.b64` with the new public key before issuing customer keys.

```bash
# 1. Generate your P-256 signing keypair (keep private.pem secret and offline)
node tools/license/keygen.mjs

# 2. Paste the printed public key into server/server.py as DEFAULT_LICENSE_PUBKEY
#    and into tools/license/keys/public.b64. Commit only those public files.

# 3. After the buyer emails payment confirmation, issue one key for that order
node tools/license/sign.mjs --ref ORDER-1001 --sku pro

# 4. Verify the key offline, then email only the NULLCLOUD-... line to the buyer
node tools/license/verify.mjs 'NULLCLOUD-...'
```

---

## Selling the "Private Cloud" (Phone -> Laptop over Tailscale)

With Nullcloud Pro, a user's Android phone becomes a personal, portable AI server that they can reach from their laptop or iPad anywhere in the world—without paying for cloud tokens or exposing a port on public Wi-Fi:

1. Start Nullcloud on the phone with Tailscale binding enabled:
   ```bash
   TAILSCALE=1 bash ~/nullcloud/termux/start.sh
   ```
2. Nullcloud detects the phone's `100.x.y.z` Tailscale IPv4 address and binds the token-protected API to `http://100.x.y.z:8080` while keeping `llama-server` strictly on `127.0.0.1:8081`.
3. On the laptop, open the Nullcloud Browser Extension -> **CPU / GPU, Private Cloud & Pro Settings** -> enter `http://100.x.y.z:8080` and the token. Every click on the laptop now streams answers from the phone's GPU/NPU/CPU.
