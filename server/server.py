#!/usr/bin/env python3
"""Nullcloud server: page text, URL, or PDF -> local LLM (OpenAI-compatible API) -> streamed answer.
On-device, no cloud AI. Works in Airplane Mode on open pages, local text, cached pages, and PDFs.
Supports llama.cpp's llama-server (Termux/desktop) and Ollama (desktop).

Free Core (MIT):
- 3 entry points: Android Share Sheet, Web UI, Browser Extension
- Built-in modes: summary, facts, claims, eli5, translate, ask
- Airplane Mode / offline text & cached page analysis
- Read aloud (TTS) & opt-in Markdown / Obsidian vault export

Pro Productivity Hub & Private Cloud (one-time offline ECDSA P-256 license, paid via Revolut):
- Saved-page library with SQLite FTS5 full-text search
- PDF input extraction (offline via pdftotext, pypdf, or built-in stream parser)
- Custom prompt presets (including high-compliance templates for law, journalism, and clinics)
- Private Cloud server over Tailscale (use your phone as a private AI server from your laptop)
"""
import base64
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zlib
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8080"))
LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8081/v1/chat/completions")
MODEL = os.environ.get("MODEL", "local")
TOKEN = os.environ.get("TOKEN", "")
MAX_CHARS = int(os.environ.get("MAX_CHARS", "6000"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "400"))
CTX_SIZE = int(os.environ.get("CTX_SIZE", "3072"))
CPU_THREADS = int(os.environ.get("CPU_THREADS", str(min(os.cpu_count() or 4, 6))))
GPU_LAYERS = int(os.environ.get("GPU_LAYERS", "99"))
GPU_NAME = os.environ.get("GPU_NAME", "")
ACCEL_MODE = os.environ.get("ACCEL_MODE", "")
KV_CACHE = os.environ.get("KV_CACHE", "q8_0/q4_0")
FLASH_ATTN = os.environ.get("FLASH_ATTN", "1") != "0"
NOTES_DIR = os.environ.get("NOTES_DIR", "")  # opt-in: save results as Markdown (e.g. an Obsidian vault folder)
ARCHIVE = os.environ.get("ARCHIVE", "") == "1"  # opt-in: also keep the raw HTML next to each note

HOME_DIR = pathlib.Path(os.environ.get("NULLCLOUD_HOME", str(pathlib.Path.home())))
LICENSE_FILE = pathlib.Path(os.environ.get("NULLCLOUD_LICENSE_FILE", str(HOME_DIR / ".nullcloud-pro.key")))
LIBRARY_DB = pathlib.Path(os.environ.get("NULLCLOUD_LIBRARY_DB", str(HOME_DIR / ".nullcloud-library.db")))
PRESETS_FILE = pathlib.Path(os.environ.get("NULLCLOUD_PRESETS_FILE", str(HOME_DIR / ".nullcloud-presets.json")))
LAST_RESULT_FILE = pathlib.Path(os.environ.get("NULLCLOUD_LAST_FILE", str(HOME_DIR / ".nullcloud-last.json")))
COMPUTE_FILE = pathlib.Path(os.environ.get("NULLCLOUD_COMPUTE_FILE", str(HOME_DIR / ".nullcloud-compute.json")))

# Default P-256 SPKI public key for offline Pro license verification (override via NULLCLOUD_PUBKEY for custom builds)
DEFAULT_LICENSE_PUBKEY = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEuc4zK4+ZGpUSY/Qxb6RoRgim4UeP"
    "W7GlkvdEmZ5rIapjL/7xQh9Ja38fEt2yx1M5t2l+R+6WmiUf0bZuhfkF2A=="
)
LICENSE_PUBKEY = os.environ.get("NULLCLOUD_PUBKEY", DEFAULT_LICENSE_PUBKEY)

if not TOKEN and os.environ.get("NULLCLOUD_TESTING") != "1":
    sys.exit("Set TOKEN first, e.g.: TOKEN=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \\n') python server.py")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_BYTES", str(16 * 1024 * 1024)))
CORS(
    app,
    origins=[
        r"^chrome-extension://.*$",
        r"^moz-extension://.*$",
        r"^http://127\.0\.0\.1(:\d+)?$",
        r"^http://localhost(:\d+)?$",
        r"^https?://100\.\d+\.\d+\.\d+(:\d+)?$",
        r"^https?://[a-zA-Z0-9._-]+\.ts\.net(:\d+)?$",
    ],
)

MODES = {
    "summary": "Summarize the page in 3-5 concise bullet points, then one sentence on why it matters.",
    "facts": "List the key facts, numbers, names and dates in the page as bullets. Add nothing that is not in the page.",
    "claims": "List the main claims the page makes. For each, say whether the page itself gives evidence for it. Stay neutral.",
    "translate": "Translate the main content of the page into {lang}.",
    "eli5": "Explain the page in simple words a 12-year-old would understand, in at most 6 sentences.",
}

DEFAULT_PRO_PRESETS = [
    {
        "id": "legal-privilege",
        "name": "Legal: Privilege & Risk Scan",
        "category": "Legal / Law Firm",
        "prompt": (
            "Review the document strictly on-device. List: (1) Parties, dates, and governing obligations; "
            "(2) Potential liability, indemnity, or confidentiality clauses; (3) Ambiguities or missing deadlines. "
            "Cite exact phrases from the text."
        ),
    },
    {
        "id": "journalism-source",
        "name": "Journalism: Source Verification & Chronology",
        "category": "Journalism / Newsroom",
        "prompt": (
            "Extract a strict chronological timeline of events, named sources, direct quotes, and quantitative claims. "
            "Flag any unattributed assertions or contradictions within the text."
        ),
    },
    {
        "id": "clinical-intake",
        "name": "Clinical: De-Identified Summary & Key Findings",
        "category": "Medical / Clinic",
        "prompt": (
            "Summarize the clinical note or research paper into: Chief Complaint / Objective, Key Findings & Vitals, "
            "Medications / Interventions mentioned, and Follow-up items. Do not invent any clinical details."
        ),
    },
    {
        "id": "exec-brief",
        "name": "Executive: 60-Second Action Brief",
        "category": "Productivity",
        "prompt": (
            "Provide a 3-bullet executive summary, the single most important takeaway, and up to 3 concrete action items."
        ),
    },
]

# --- Pure-Python NIST P-256 ECDSA Verification (Zero extra dependencies, 100% offline) ---
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_A = _P256_P - 3
_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5


def _pt_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and y1 != y2:
        return None
    if x1 == x2:
        if y1 == 0:
            return None
        m = (3 * x1 * x1 + _P256_A) * pow(2 * y1, _P256_P - 2, _P256_P) % _P256_P
    else:
        m = (y2 - y1) * pow(x2 - x1, _P256_P - 2, _P256_P) % _P256_P
    x3 = (m * m - x1 - x2) % _P256_P
    y3 = (m * (x1 - x3) - y1) % _P256_P
    return (x3, y3)


def _pt_mul(k, p):
    r = None
    a = p
    while k > 0:
        if k & 1:
            r = _pt_add(r, a)
        a = _pt_add(a, a)
        k >>= 1
    return r


def _b64u_decode(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _parse_der_sig(der):
    if len(der) < 8 or der[0] != 0x30:
        raise ValueError("Invalid DER sequence")
    idx = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    if der[idx] != 0x02:
        raise ValueError("Invalid DER r integer")
    rlen = der[idx + 1]
    r = int.from_bytes(der[idx + 2 : idx + 2 + rlen], "big")
    idx += 2 + rlen
    if der[idx] != 0x02:
        raise ValueError("Invalid DER s integer")
    slen = der[idx + 1]
    s = int.from_bytes(der[idx + 2 : idx + 2 + slen], "big")
    return r, s


def verify_license_key(key_str, pubkey_b64=None):
    """Verify an offline NULLCLOUD-<payload>.<sig> ECDSA P-256 key. Never makes network calls."""
    if not key_str or not isinstance(key_str, str):
        return False, None
    k = key_str.strip()
    for prefix in ("NULLCLOUD-", "MERIDIAN-"):
        if k.startswith(prefix):
            k = k[len(prefix) :]
            break
    if "." not in k:
        return False, None
    try:
        p_b64, s_b64 = k.split(".", 1)
        payload = _b64u_decode(p_b64)
        sig_der = _b64u_decode(s_b64)
        spki = base64.b64decode((pubkey_b64 or LICENSE_PUBKEY).strip())
        pub_point = spki[-65:]
        if len(pub_point) != 65 or pub_point[0] != 0x04:
            return False, None
        qx = int.from_bytes(pub_point[1:33], "big")
        qy = int.from_bytes(pub_point[33:65], "big")
        r, s = _parse_der_sig(sig_der)
        if not (1 <= r < _P256_N and 1 <= s < _P256_N):
            return False, None
        z = int.from_bytes(hashlib.sha256(payload).digest(), "big")
        w = pow(s, _P256_N - 2, _P256_N)
        u1 = (z * w) % _P256_N
        u2 = (r * w) % _P256_N
        pt = _pt_add(_pt_mul(u1, (_P256_GX, _P256_GY)), _pt_mul(u2, (qx, qy)))
        if pt is None or (pt[0] % _P256_N) != r:
            return False, None
        claims = json.loads(payload.decode("utf-8"))
        if claims.get("sku") not in ("pro", "team", "premium"):
            return False, None
        return True, claims
    except Exception:  # noqa: BLE001
        return False, None


def get_pro_status():
    """Check if Pro tier is unlocked via request header, env var, or saved ~/.nullcloud-pro.key."""
    candidates = [
        request.headers.get("X-License-Key", "") if request else "",
        os.environ.get("NULLCLOUD_LICENSE_KEY", ""),
    ]
    if LICENSE_FILE.is_file():
        try:
            candidates.append(LICENSE_FILE.read_text(encoding="utf-8").strip())
        except Exception:  # noqa: BLE001
            pass
    for c in candidates:
        if c:
            ok, claims = verify_license_key(c)
            if ok:
                return True, claims
    return False, None


# --- HTML Parser & SSRF-Safe Fetcher ---
class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "iframe", "form", "aside"}
    BREAK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article", "blockquote"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0
        self.in_title = False
        self.title_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
        if tag in self.BREAK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag in self.BREAK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.in_title and data.strip():
            self.title_parts.append(data.strip())
        if not self.skip and data.strip():
            self.out.append(data.strip() + " ")

    @property
    def title(self):
        return " ".join(self.title_parts).strip()


def validate_public_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only http/https URLs are supported.")
    host = p.hostname.lower().rstrip(".")
    if host in ("localhost", "0.0.0.0") or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("Private/local addresses are blocked.")
    for info in socket.getaddrinfo(host, None):
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
            or (getattr(ip, "ipv4_mapped", None) is not None and (ip.ipv4_mapped.is_private or ip.ipv4_mapped.is_loopback))
        ):
            raise ValueError("Private/local addresses are blocked.")
    return url


def find_cached_archive(url):
    """Look up previously archived HTML or saved library page for Airplane Mode / offline use."""
    if LIBRARY_DB.is_file():
        try:
            with sqlite3.connect(LIBRARY_DB) as conn:
                row = conn.execute(
                    "SELECT content, title FROM pages WHERE url = ? ORDER BY id DESC LIMIT 1", (url,)
                ).fetchone()
                if row and row[0]:
                    return row[0], "", row[1] or ""
        except Exception:  # noqa: BLE001
            pass
    if NOTES_DIR:
        base = pathlib.Path(NOTES_DIR).expanduser()
        if base.is_dir():
            for md_file in sorted(base.glob("*.md"), reverse=True):
                try:
                    content = md_file.read_text(encoding="utf-8", errors="ignore")
                    if f'source: "{url}"' in content:
                        m = re.search(r"^archive:\s*(.+)$", content, re.M)
                        if m:
                            arch_path = (base / m.group(1).strip()).resolve()
                            if str(arch_path).startswith(str(base.resolve())) and arch_path.is_file():
                                raw_html = arch_path.read_text(encoding="utf-8", errors="ignore")
                                parser = _Text()
                                parser.feed(raw_html[:2_000_000])
                                text = re.sub(r"\n\s*\n+", "\n", "".join(parser.out)).strip()
                                return text, raw_html, parser.title
                except Exception:  # noqa: BLE001
                    continue
    return None


def fetch_text_with_meta(url):
    current = url
    r = None
    try:
        for _ in range(5):
            validate_public_url(current)
            r = requests.get(
                current,
                timeout=20,
                allow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0 (Nullcloud; on-device AI)"},
            )
            if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                if not loc:
                    break
                current = urljoin(current, loc)
                continue
            break
        else:
            raise ValueError("Too many redirects.")
        r.raise_for_status()
        raw_html = r.text[:2_000_000]
        parser = _Text()
        parser.feed(raw_html)
        cleaned = re.sub(r"\n\s*\n+", "\n", "".join(parser.out)).strip()
        return cleaned, raw_html, parser.title
    except requests.RequestException as net_err:
        cached = find_cached_archive(url)
        if cached:
            return cached
        raise ValueError(
            f"{net_err} (If your phone is in Airplane Mode, analyze an already-open tab via the extension, "
            "paste the text directly, or open a page saved in your offline Library.)"
        ) from net_err


def fetch_text(url):
    cleaned, raw_html, _ = fetch_text_with_meta(url)
    return cleaned, raw_html


# --- Offline PDF Extraction (Pro feature) ---
def _extract_pdf_bytes_fallback(pdf_bytes):
    """Lightweight pure-Python PDF text extractor for simple/uncompressed or FlateDecode PDF streams."""
    chunks = []
    # Scan streams (both compressed FlateDecode and raw)
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.S):
        stream_data = m.group(1)
        decoded = None
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                decoded = zlib.decompress(stream_data, wbits)
                break
            except Exception:  # noqa: BLE001
                pass
        data = decoded if decoded is not None else stream_data
        # Extract literal strings inside parentheses (...) or Tj/TJ blocks
        for sm in re.finditer(rb"\(([^()\\]*(?:\\.[^()\\]*)*)\)", data):
            raw_s = sm.group(1)
            raw_s = (
                raw_s.replace(rb"\n", b"\n")
                .replace(rb"\r", b" ")
                .replace(rb"\t", b" ")
                .replace(rb"\(", b"(")
                .replace(rb"\)", b")")
                .replace(rb"\\", b"\\")
            )
            txt = raw_s.decode("latin-1", errors="ignore").strip()
            if txt and any(c.isalpha() for c in txt):
                chunks.append(txt)
    if not chunks:
        # Also check top-level literal strings if streams weren't matched
        for sm in re.finditer(rb"\(([^()\\]*(?:\\.[^()\\]*)*)\)\s*Tj", pdf_bytes):
            txt = sm.group(1).decode("latin-1", errors="ignore").strip()
            if txt:
                chunks.append(txt)
    return " ".join(chunks).strip()


def extract_pdf_text(pdf_bytes, max_pages=30):
    """Extract text from PDF bytes completely on-device (tries pypdf -> pdftotext -> stdlib fallback)."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Invalid PDF file (missing %PDF header).")
    # 1. Try pypdf / PyPDF2 if installed
    for mod_name in ("pypdf", "PyPDF2"):
        try:
            mod = __import__(mod_name)
            import io

            reader = mod.PdfReader(io.BytesIO(pdf_bytes))
            pages = [p.extract_text() or "" for p in reader.pages[:max_pages]]
            text = "\n\n".join(p.strip() for p in pages if p.strip()).strip()
            if text:
                return text
        except Exception:  # noqa: BLE001
            pass
    # 2. Try pdftotext (poppler in Termux / Linux)
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(pdf_bytes)
            tmp.flush()
            res = subprocess.run(
                ["pdftotext", "-l", str(max_pages), tmp.name, "-"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    # 3. Pure-Python fallback
    text = _extract_pdf_bytes_fallback(pdf_bytes)
    if text:
        return text
    raise ValueError("Could not extract readable text from PDF. Install poppler (`pkg install poppler`) or pypdf.")


# --- Markdown Notes & Pro SQLite FTS5 Library ---
def save_note(url, mode, output, raw):
    """Write a Markdown note (+ optional raw HTML archive). Local files only; never raises."""
    if not NOTES_DIR:
        return
    try:
        base = pathlib.Path(NOTES_DIR).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        host = re.sub(r"[^a-z0-9]+", "-", (urlparse(url).hostname or "note").lower()).strip("-") or "note"
        name = f"{now:%Y-%m-%d-%H%M%S}-{host}"
        meta = [
            f'source: "{url}"',
            f"date: {now.isoformat(timespec='seconds')}",
            f"mode: {mode}",
            "tags: [nullcloud]",
        ]
        if ARCHIVE and raw:
            arch_dir = (base / "archive").resolve()
            arch_dir.mkdir(exist_ok=True)
            (arch_dir / f"{name}.html").write_text(raw, encoding="utf-8")
            meta.append(f"archive: archive/{name}.html")
        (base / f"{name}.md").write_text(
            "---\n" + "\n".join(meta) + "\n---\n\n" + output.strip() + "\n", encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        print("save_note failed:", e, file=sys.stderr)


def _init_library_db():
    LIBRARY_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(LIBRARY_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                title TEXT,
                mode TEXT,
                content TEXT,
                summary TEXT,
                created_at TEXT
            )
            """
        )
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                    title, url, mode, content, summary, content='pages', content_rowid='id'
                )
                """
            )
        except sqlite3.OperationalError:
            pass


def save_to_library(url, title, mode, content, summary):
    """Save analyzed page + summary into the local SQLite library."""
    try:
        _init_library_db()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        clean_title = (title or "").strip() or (urlparse(url).hostname if url else "On-device note") or "On-device note"
        with sqlite3.connect(LIBRARY_DB) as conn:
            cur = conn.execute(
                "INSERT INTO pages (url, title, mode, content, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (url or "", clean_title, mode, (content or "")[:MAX_CHARS], (summary or "").strip(), now),
            )
            rowid = cur.lastrowid
            try:
                conn.execute(
                    "INSERT INTO pages_fts(rowid, title, url, mode, content, summary) VALUES (?, ?, ?, ?, ?, ?)",
                    (rowid, clean_title, url or "", mode, (content or "")[:MAX_CHARS], (summary or "").strip()),
                )
            except sqlite3.OperationalError:
                pass
            return rowid
    except Exception as e:  # noqa: BLE001
        print("save_to_library failed:", e, file=sys.stderr)
        return None


def search_library(query_str="", limit=50):
    _init_library_db()
    q = (query_str or "").strip()
    with sqlite3.connect(LIBRARY_DB) as conn:
        conn.row_factory = sqlite3.Row
        if not q:
            rows = conn.execute(
                "SELECT id, url, title, mode, content, summary, created_at FROM pages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        try:
            safe_fts = " ".join(f'"{w}"' for w in re.findall(r"\w+", q))
            if safe_fts:
                rows = conn.execute(
                    """
                    SELECT p.id, p.url, p.title, p.mode, p.content, p.summary, p.created_at
                    FROM pages_fts f JOIN pages p ON p.id = f.rowid
                    WHERE pages_fts MATCH ?
                    ORDER BY rank LIMIT ?
                    """,
                    (safe_fts, limit),
                ).fetchall()
                return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass
        like = f"%{q}%"
        rows = conn.execute(
            """
            SELECT id, url, title, mode, content, summary, created_at FROM pages
            WHERE title LIKE ? OR url LIKE ? OR content LIKE ? OR summary LIKE ?
            ORDER BY id DESC LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def load_presets():
    custom = []
    if PRESETS_FILE.is_file():
        try:
            data = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                custom = data
        except Exception:  # noqa: BLE001
            pass
    return DEFAULT_PRO_PRESETS + custom


def save_custom_presets(custom_list):
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(custom_list, indent=2), encoding="utf-8")


def detect_gpu_name():
    """Detect mobile or desktop GPU hardware (Adreno, Mali, Vulkan, Metal, CUDA, ROCm) without network calls."""
    if GPU_NAME:
        return GPU_NAME
    kgsl = pathlib.Path("/sys/class/kgsl/kgsl-3d0/gpu_model")
    if kgsl.is_file():
        try:
            return "Adreno " + kgsl.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:  # noqa: BLE001
            pass
    if pathlib.Path("/sys/class/misc/mali0").exists() or pathlib.Path("/dev/mali0").exists():
        return "Arm Mali / Immortalis GPU"
    if sys.platform == "darwin":
        return "Apple Silicon Metal GPU"
    if shutil.which("nvidia-smi"):
        return "NVIDIA CUDA GPU"
    if shutil.which("rocminfo"):
        return "AMD ROCm GPU"
    return "Vulkan / OpenCL GPU"


def get_compute_config():
    """Return active CPU + GPU acceleration settings (combining env defaults and user overrides)."""
    cfg = {
        "cpu_cores": os.cpu_count() or 4,
        "cpu_threads": CPU_THREADS,
        "cpu_isa": "ARM64 NEON / dotprod (big.LITTLE)" if os.uname().machine in ("aarch64", "arm64") else f"{os.uname().machine} SIMD/AVX2",
        "gpu_name": detect_gpu_name(),
        "gpu_layers": GPU_LAYERS,
        "gpu_backends": ["Vulkan", "OpenCL", "Metal", "CUDA", "ROCm"],
        "ctx_size": CTX_SIZE,
        "kv_cache": KV_CACHE,
        "flash_attn": FLASH_ATTN,
    }
    if COMPUTE_FILE.is_file():
        try:
            saved = json.loads(COMPUTE_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                if "cpu_threads" in saved:
                    cfg["cpu_threads"] = max(1, min(int(saved["cpu_threads"]), 32))
                if "gpu_layers" in saved:
                    cfg["gpu_layers"] = max(0, min(int(saved["gpu_layers"]), 999))
                if "flash_attn" in saved:
                    cfg["flash_attn"] = bool(saved["flash_attn"])
                if "kv_cache" in saved and saved["kv_cache"] in ("q8_0/q4_0", "q8_0", "q4_0", "f16"):
                    cfg["kv_cache"] = saved["kv_cache"]
        except Exception:  # noqa: BLE001
            pass
    mode_label = (
        f"CPU ({cfg['cpu_threads']} threads) + GPU ({cfg['gpu_name']}, -ngl {cfg['gpu_layers']}, KV {cfg['kv_cache']})"
        if cfg["gpu_layers"] > 0
        else f"CPU-Only ({cfg['cpu_threads']} threads, {cfg['cpu_isa']}, KV {cfg['kv_cache']})"
    )
    cfg["accel_summary"] = ACCEL_MODE or mode_label
    return cfg


def get_tailscale_info():
    """Detect local Tailscale IPv4 (100.x.y.z) for Private Cloud mode."""
    ts_ip = None
    if shutil.which("tailscale"):
        try:
            res = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                ts_ip = res.stdout.strip().splitlines()[0].strip()
        except Exception:  # noqa: BLE001
            pass
    if not ts_ip:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None):
                ip_str = info[4][0]
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.version == 4 and ip_obj in ipaddress.ip_network("100.64.0.0/10"):
                    ts_ip = ip_str
                    break
        except Exception:  # noqa: BLE001
            pass
    return {
        "tailscale_ip": ts_ip,
        "listening_host": HOST,
        "port": PORT,
        "private_cloud_url": f"http://{ts_ip}:{PORT}" if ts_ip else None,
        "bind_command_termux": "TAILSCALE=1 bash ~/nullcloud/termux/start.sh",
        "bind_command_desktop": f"HOST={ts_ip or '<tailscale-ip>'} bash desktop/start.sh",
    }


def authorized():
    provided = request.headers.get("X-Token", "")
    if not TOKEN or not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), TOKEN.encode("utf-8"))


PRO_CHECKOUT_URL = "https://checkout.revolut.com/pay/d25ddfdd-7351-465b-afb6-c6238f65c575"
SETUP_CHECKOUT_URL = "https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4"
BUNDLE_CHECKOUT_URL = "https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52"
QUOTE_EMAIL = "Pozun.alen96@gmail.com"
PAYMENT_FLOW = (
    "Pay via the link, then email Pozun.alen96@gmail.com with the payment confirmation. "
    "The license key is sent manually."
)
PAYMENT_OFFERS = [
    {"id": "pro", "label": "Get Pro", "price": "€19 one-time", "url": PRO_CHECKOUT_URL},
    {"id": "setup", "label": "Remote setup", "price": "€30", "url": SETUP_CHECKOUT_URL},
    {"id": "bundle", "label": "Pro + setup", "price": "€45", "url": BUNDLE_CHECKOUT_URL},
]


def pro_locked_body(message):
    return {
        "error": message,
        "pro_required": True,
        "offers": PAYMENT_OFFERS,
        "payment_flow": PAYMENT_FLOW,
        "quote": (
            "Tailscale private cloud (€60-80) and team consulting (from €250): "
            f"contact {QUOTE_EMAIL} for a quote."
        ),
    }


def require_pro():
    is_pro, _claims = get_pro_status()
    if not is_pro:
        return (
            jsonify(
                **pro_locked_body(
                    "This feature requires Nullcloud Pro (saved-page library with search, PDF input, "
                    "custom prompt presets, and Private Cloud server over Tailscale). "
                    + PAYMENT_FLOW
                )
            ),
            402,
        )
    return None


# --- HTTP Routes ---
@app.get("/")
def ui():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "ui.html")


@app.get("/health")
def health():
    is_pro, claims = get_pro_status()
    compute = get_compute_config()
    return jsonify(
        ok=True,
        mode="on-device, no cloud AI",
        offline_ready=True,
        model=MODEL,
        max_chars=MAX_CHARS,
        max_tokens=MAX_TOKENS,
        pro=is_pro,
        sku=claims.get("sku") if claims else "free",
        compute=compute,
    )


@app.get("/hardware")
def get_hardware():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    return jsonify(ok=True, compute=get_compute_config())


@app.post("/hardware")
def update_hardware():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    d = request.get_json(force=True, silent=True) or {}
    cfg = get_compute_config()
    updated = {
        "cpu_threads": max(1, min(int(d.get("cpu_threads", cfg["cpu_threads"])), 32)),
        "gpu_layers": max(0, min(int(d.get("gpu_layers", cfg["gpu_layers"])), 999)),
        "flash_attn": bool(d.get("flash_attn", cfg["flash_attn"])),
        "kv_cache": str(d.get("kv_cache", cfg["kv_cache"])),
    }
    COMPUTE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMPUTE_FILE.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    return jsonify(ok=True, compute=get_compute_config())


@app.get("/last")
def last_result():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    if not LAST_RESULT_FILE.is_file():
        return jsonify(error="No recent analysis yet."), 404
    try:
        return jsonify(json.loads(LAST_RESULT_FILE.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=str(e)), 500


@app.get("/pro/status")
def pro_status():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    is_pro, claims = get_pro_status()
    return jsonify(
        pro=is_pro,
        sku=claims.get("sku") if claims else "free",
        claims=claims,
        tailscale=get_tailscale_info() if is_pro else None,
    )


@app.post("/pro/activate")
def pro_activate():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    d = request.get_json(force=True, silent=True) or {}
    key_str = (d.get("key") or "").strip()
    ok, claims = verify_license_key(key_str)
    if not ok:
        return jsonify(error="Invalid Nullcloud Pro license key. Check that you copied the full NULLCLOUD-... key."), 400
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(key_str + "\n", encoding="utf-8")
    try:
        os.chmod(LICENSE_FILE, 0o600)
    except OSError:
        pass
    return jsonify(ok=True, pro=True, claims=claims, tailscale=get_tailscale_info())


@app.get("/presets")
def get_presets():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    is_pro, _ = get_pro_status()
    if not is_pro:
        return jsonify(presets=[], pro_required=True)
    return jsonify(presets=load_presets(), pro=True)


@app.post("/presets")
def add_preset():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    gate = require_pro()
    if gate:
        return gate
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get("name") or "").strip()
    prompt = (d.get("prompt") or "").strip()
    category = (d.get("category") or "Custom").strip()
    if not name or not prompt:
        return jsonify(error="Preset name and prompt are required."), 400
    preset_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "custom"
    custom = []
    if PRESETS_FILE.is_file():
        try:
            custom = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            custom = []
    custom = [p for p in custom if p.get("id") != preset_id]
    custom.append({"id": preset_id, "name": name[:80], "category": category[:40], "prompt": prompt[:2000]})
    save_custom_presets(custom)
    return jsonify(ok=True, presets=load_presets())


@app.delete("/presets/<preset_id>")
def delete_preset(preset_id):
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    gate = require_pro()
    if gate:
        return gate
    custom = []
    if PRESETS_FILE.is_file():
        try:
            custom = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            custom = []
    custom = [p for p in custom if p.get("id") != preset_id]
    save_custom_presets(custom)
    return jsonify(ok=True, presets=load_presets())


@app.get("/library")
def list_library():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    gate = require_pro()
    if gate:
        return gate
    q = request.args.get("q", "")
    items = search_library(q)
    return jsonify(items=items, count=len(items))


@app.post("/library")
def create_library_item():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    gate = require_pro()
    if gate:
        return gate
    d = request.get_json(force=True, silent=True) or {}
    rowid = save_to_library(
        url=d.get("url") or "",
        title=d.get("title") or "",
        mode=d.get("mode") or "summary",
        content=d.get("content") or d.get("text") or "",
        summary=d.get("summary") or "",
    )
    return jsonify(ok=True, id=rowid)


@app.delete("/library/<int:item_id>")
def delete_library_item(item_id):
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    gate = require_pro()
    if gate:
        return gate
    _init_library_db()
    with sqlite3.connect(LIBRARY_DB) as conn:
        conn.execute("DELETE FROM pages WHERE id = ?", (item_id,))
        try:
            conn.execute("DELETE FROM pages_fts WHERE rowid = ?", (item_id,))
        except sqlite3.OperationalError:
            pass
    return jsonify(ok=True)


@app.post("/analyze")
def analyze():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    d = request.get_json(force=True, silent=True) or {}
    is_pro, _ = get_pro_status()

    text = (d.get("text") or "").strip()
    raw = ""
    title = (d.get("title") or "").strip()

    # Pro feature: PDF input (base64 encoded PDF bytes)
    if d.get("pdf_base64"):
        if not is_pro:
            return require_pro()
        try:
            pdf_bytes = base64.b64decode(d["pdf_base64"])
            text = extract_pdf_text(pdf_bytes)
            if not title:
                title = d.get("filename") or "PDF Document"
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"Could not read PDF: {e}"), 400

    try:
        if not text and d.get("url"):
            text, raw, fetched_title = fetch_text_with_meta(d["url"])
            if not title and fetched_title:
                title = fetched_title
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not read URL: {e}"), 400
    if len(text) < 20:
        return jsonify(error="No text to analyze."), 400

    mode = d.get("mode", "summary")
    q = (d.get("q") or "").strip()
    lang = (d.get("lang") or "").strip()
    preset_id = (d.get("preset_id") or "").strip()
    custom_prompt = (d.get("custom_prompt") or "").strip()

    # Pro feature: Custom prompt presets
    if preset_id or custom_prompt or mode.startswith("preset:"):
        if not is_pro:
            return require_pro()
        target_id = preset_id or (mode.split(":", 1)[1] if mode.startswith("preset:") else "")
        preset_map = {p["id"]: p["prompt"] for p in load_presets()}
        task = custom_prompt or preset_map.get(target_id)
        if not task:
            return jsonify(error=f"Unknown preset: {target_id}"), 400
        mode = f"preset:{target_id}" if target_id else "preset:custom"
    else:
        task = (
            q
            if (mode == "ask" and q)
            else MODES.get(mode, MODES["summary"]).format(lang=lang or "the language of the page")
        )

    system = (
        "You are a private on-device assistant. Use only the PAGE text. "
        "If the answer is not in the page, say so. "
        + (f"Reply in {lang}." if lang else "Reply in the language of the page unless the task says otherwise.")
    )
    compute = get_compute_config()
    eff_gpu_layers = int(d["gpu_layers"]) if d.get("gpu_layers") is not None and str(d.get("gpu_layers")).isdigit() else compute["gpu_layers"]
    eff_cpu_threads = int(d["cpu_threads"]) if d.get("cpu_threads") is not None and str(d.get("cpu_threads")).isdigit() else compute["cpu_threads"]

    payload = {
        "model": MODEL,
        "stream": True,
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
        "n_gpu_layers": eff_gpu_layers,
        "options": {
            "num_gpu": eff_gpu_layers,
            "num_thread": eff_cpu_threads,
            "num_ctx": compute["ctx_size"],
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"PAGE:\n{text[:MAX_CHARS]}\n\nTASK: {task}"},
        ],
    }

    def gen():
        acc = []
        try:
            with requests.post(LLM_URL, json=payload, stream=True, timeout=(5, 600)) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith(b"data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == b"[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content")
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        acc.append(delta)
                        yield delta
            full_output = "".join(acc).strip()
            if full_output:
                try:
                    LAST_RESULT_FILE.write_text(
                        json.dumps(
                            {
                                "url": d.get("url") or "",
                                "title": title,
                                "mode": mode,
                                "output": full_output,
                                "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                            }
                        ),
                        encoding="utf-8",
                    )
                except Exception:  # noqa: BLE001
                    pass
                if NOTES_DIR:
                    save_note(d.get("url") or "", mode, full_output, raw)
                if is_pro and d.get("save_library", True):
                    save_to_library(d.get("url") or "", title, mode, text, full_output)
        except Exception as e:  # noqa: BLE001
            yield f"\n[Model server not reachable: {e}. Is it running? See README > Troubleshooting.]"

    return Response(
        gen(),
        mimetype="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    if HOST not in ("127.0.0.1", "localhost"):
        print(f"WARNING: listening on {HOST}. Anyone on that network can reach the API (token required).")
    app.run(host=HOST, port=PORT, threaded=True)
