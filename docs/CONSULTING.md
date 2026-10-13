# High-Compliance Consulting & Private AI Deployment

**On-Device, No Cloud AI for Law Firms, Investigative Newsrooms, and Medical Clinics**

Nullcloud provides turn-key deployment and customization for privacy-sensitive teams that have strict data-handling, privilege, or source-protection requirements and cannot send sensitive pages, PDFs, or notes to third-party cloud AI APIs.

---

## Why Privacy-Sensitive Teams Choose On-Device AI

1. **Zero Third-Party AI Cloud Exposure:** Every prompt, document, web page, and PDF is processed strictly on the user's own phone or workstation (`127.0.0.1` or an encrypted Tailscale tailnet they control). No data is sent to external AI vendors, retained in cloud logs, or used for model training.
2. **Works Completely Offline (Airplane Mode):** Attorneys on flights, investigative journalists in the field, and clinicians in restricted-connectivity wards can summarize open pages, case files, and PDFs with cellular and Wi-Fi radios turned off.
3. **Instant Android Share Sheet Workflow:** Team members share any link, text selection, or PDF directly from their mobile browser or document viewer to Termux and receive a summary notification in seconds—no desktop browser extension required.
4. **Phone as a Private Cloud Server:** With Tailscale, a team member's phone or a dedicated local mini-PC acts as an encrypted private AI server accessible from their laptop or iPad using token authentication.

---

## Vertical Solutions & Pre-Built Presets (free)

### 1. Law Firms & Legal Counsel (`legal-privilege`)
- **Use Case:** Reviewing contracts, opposing filings, discovery PDFs, and case law without waiving privilege or violating client confidentiality policies.
- **Included Workflow:** Pre-configured *Privilege & Risk Scan* preset extracts parties, governing obligations, liability/indemnity clauses, and missing deadlines with exact text citations.
- **Vault Integration:** Automatic Markdown export with YAML frontmatter directly into local Obsidian or Logseq case folders.

### 2. Investigative Journalists & Newsrooms (`journalism-source`)
- **Use Case:** Analyzing leaked documents, court dockets, foreign-language articles, and whistleblower materials on a phone in Airplane Mode.
- **Included Workflow:** *Source Verification & Chronology* preset builds a strict timeline of events, named sources, direct quotes, and unattributed claims.
- **Offline Library:** Local SQLite FTS5 full-text search across thousands of archived articles and summaries (`~/.nullcloud-library.db`).

### 3. Medical Clinics & Independent Practitioners (`clinical-intake`)
- **Use Case:** Summarizing clinical literature, intake notes, and referral PDFs locally on clinic hardware without transmitting patient-adjacent text to external LLM APIs.
- **Included Workflow:** *De-Identified Summary & Key Findings* preset structures notes into Chief Complaint, Key Findings, Interventions, and Follow-up items.
- *Compliance Note:* Nullcloud is a local software tool running on hardware you control; your organization remains responsible for device encryption, physical access controls, and regulatory compliance (e.g., HIPAA / GDPR).

---

## Consulting Packages

| Package | Scope | Ideal For |
|---|---|---|
| **1. Rapid Team Audit & Setup** | Provisioning on up to 5 phones/laptops, hardware-tuned Llama 1B/3B GGUF selection with GPU offload where supported, offline Pro license keys, and staff onboarding. | Solo practitioners, boutique law practices, independent reporters |
| **2. Private Cloud & Tailscale Fleet** | Dedicated Private Cloud setup connecting team phones and laptops via Tailscale ACLs, shared Obsidian/Markdown vault sync, and 5 custom domain-specific prompt presets. | Small law firms, investigative desks, specialist clinics |
| **3. Custom Compliance Integration** | Custom document pipelines (local PDF/OCR ingestion), bespoke model quantization/benchmarking on your target devices, and priority support SLA. | Enterprise compliance teams & regulated organizations |

---

## Prices

Nullcloud itself is free. Services:

- Remote setup: €30 ([Revolut](https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4))
- Setup + priority support: €45 ([Revolut](https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52))
- Private Cloud (Tailscale) setup: €60-80, quote by email
- Team setup & consulting: from €250, quote by email to [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com)

## Book a Consultation

- **Email:** [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com?subject=Nullcloud%20High-Compliance%20Consulting)
- **GitHub Issues / Discussions:** [kukirin-ui/Nullcloud](https://github.com/kukirin-ui/Nullcloud/issues)
