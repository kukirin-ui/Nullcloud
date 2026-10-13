# Security Policy

## Supported Versions

Only the latest version on `main` receives security updates.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities. Report vulnerabilities privately via GitHub Security Advisories (**Security -> Report a vulnerability**) or email the maintainer at [Pozun.alen96@gmail.com](mailto:Pozun.alen96@gmail.com).

Include steps to reproduce and the security impact. You will receive a response within 7 days.

## Security Architecture

- **On-Device Processing:** Page text, pasted notes, and PDFs are sent only to your local model server (`127.0.0.1` or your explicit Tailscale IP).
- **Token Authentication:** Every API endpoint (except `/health` and static `/`) requires a constant-time verified `X-Token` header (`~/.nullcloud-token`, mode `0600`).
- **SSRF Protection:** URL fetching blocks private, loopback, link-local, reserved, and `.local`/`.internal` addresses on both the initial request and every redirect hop.
- **Offline Licensing:** Pro license keys use offline ECDSA P-256 signature verification with zero network calls.
