#!/usr/bin/env python3
"""Nullcloud server: page text, URL, or PDF -> local LLM (OpenAI-compatible API) -> streamed answer.
On-device, no cloud AI. Works in Airplane Mode on open pages, local text, cached pages, and PDFs.
Supports llama.cpp's llama-server (Termux/desktop) and Ollama (desktop).

Free Core (MIT):
- 3 entry points: Android Share Sheet, Web UI, Browser Extension
- Built-in modes: summary, facts, claims, eli5, translate, ask
- Airplane Mode / offline text & cached page analysis
- Read aloud (TTS) & opt-in Markdown / Obsidian vault export

Productivity Hub & Private Cloud (also free, no license needed):
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
import threading
import time
import uuid
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
RECIPES_DIR = pathlib.Path(os.environ.get("NULLCLOUD_RECIPES_DIR", str(pathlib.Path.home() / "nullcloud-recipes")))
NOTES_DIR = os.environ.get("NOTES_DIR", "")  # opt-in: save results as Markdown (e.g. an Obsidian vault folder)
ARCHIVE = os.environ.get("ARCHIVE", "") == "1"  # opt-in: also keep the raw HTML next to each note

HOME_DIR = pathlib.Path(os.environ.get("NULLCLOUD_HOME", str(pathlib.Path.home())))
LIBRARY_DB = pathlib.Path(os.environ.get("NULLCLOUD_LIBRARY_DB", str(HOME_DIR / ".nullcloud-library.db")))
PRESETS_FILE = pathlib.Path(os.environ.get("NULLCLOUD_PRESETS_FILE", str(HOME_DIR / ".nullcloud-presets.json")))
LAST_RESULT_FILE = pathlib.Path(os.environ.get("NULLCLOUD_LAST_FILE", str(HOME_DIR / ".nullcloud-last.json")))
COMPUTE_FILE = pathlib.Path(os.environ.get("NULLCLOUD_COMPUTE_FILE", str(HOME_DIR / ".nullcloud-compute.json")))

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
    "recipe": (
        "Turn the useful knowledge in the page into a short, practical recipe in Markdown. "
        "Use exactly these sections: '# <Title>', '## Problem' (1-3 sentences), "
        "'## Solution' (short numbered steps), '## Commands' (put EACH command in its own "
        "separate ```bash code block; write 'None' if the page has no commands). "
        "Use only what the page says. Do not add a source or date line."
    ),
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


def fetch_text_with_meta(url, timeout=20):
    current = url
    r = None
    try:
        for _ in range(5):
            validate_public_url(current)
            r = requests.get(
                current,
                timeout=timeout,
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


# --- Offline PDF Extraction ---
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


# --- Recipes (saved as Markdown in ~/nullcloud-recipes) ---
def _slugify(s, fallback="recipe"):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60].strip("-")
    return s or fallback


def save_recipe(url, title, output, sources=None, path=None):
    """Save a recipe as <slug>.md (new name, never clobbering) or overwrite `path`. Returns the path."""
    body = output.strip()
    m = re.search(r"^#\s+(.+)$", body, re.M)
    rtitle = (m.group(1).strip() if m else "") or title or (urlparse(url).hostname if url else "") or "Recipe"
    if not m:
        body = f"# {rtitle}\n\n" + body
    now = datetime.datetime.now()
    srcs = sources or [url or "(pasted text)"]
    body += "\n\n## Sources\n" + "\n".join(f"- {u}" for u in srcs) + f"\n\n## Date\n{now:%Y-%m-%d %H:%M}\n"
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)
    if path is not None:
        pathlib.Path(path).write_text(body, encoding="utf-8")
        return pathlib.Path(path)
    slug = _slugify(rtitle)
    path = RECIPES_DIR / f"{slug}.md"
    n = 2
    while path.exists():
        path = RECIPES_DIR / f"{slug}-{n}.md"
        n += 1
    path.write_text(body, encoding="utf-8")
    return path


RECIPE_SPLIT = "===RECIPE==="
SKIP_LINK = re.compile(
    r"(login|log-in|signin|sign-in|signup|register|logout|account|privacy|terms|cookie|contact|"
    r"careers|advertis|subscribe|newsletter|share|facebook\.com|twitter\.com|x\.com/intent|"
    r"instagram\.com|linkedin\.com|tiktok\.com|pinterest|mailto:|javascript:|tel:|#)",
    re.I,
)
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|webp|svg|ico|pdf|zip|gz|tar|apk|exe|mp4|mp3|webm|css|js|woff2?)(\?|$)", re.I)
STOP = set("the a an and or of to in on for with is are be this that it as by at from how what your you".split())


class _Links(HTMLParser):
    """Collect <a href> + anchor text, skipping nav/header/footer/aside."""

    SKIP_TAGS = {"nav", "header", "footer", "aside"}

    def __init__(self):
        super().__init__()
        self.links, self.skip, self.cur = [], 0, None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self.skip += 1
        elif tag == "a" and not self.skip:
            href = dict(attrs).get("href")
            if href:
                self.cur = [href, ""]

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag == "a" and self.cur:
            self.links.append((self.cur[0], self.cur[1].strip()))
            self.cur = None

    def handle_data(self, data):
        if self.cur is not None:
            self.cur[1] += data


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower()) if w not in STOP}


def rank_links(base_url, raw_html, topic, visited, limit):
    """Same-domain + keyword-relevant links first. Deduped, nav/social/media skipped."""
    p = _Links()
    try:
        p.feed(raw_html or "")
    except Exception:  # noqa: BLE001
        pass
    host = (urlparse(base_url).hostname or "").lower()
    tw = _words(topic)
    seen, scored = set(visited), []
    for i, (href, text) in enumerate(p.links):
        u = urljoin(base_url, href.strip()).split("#")[0]
        if not u.startswith(("http://", "https://")) or u in seen:
            continue
        if SKIP_EXT.search(u) or SKIP_LINK.search(href) or len(text) < 3:
            continue
        seen.add(u)
        overlap = len(tw & (_words(text) | _words(urlparse(u).path)))
        same = (urlparse(u).hostname or "").lower() == host
        score = overlap * 3 + (2 if same else 0) - i * 0.001
        if not same and overlap == 0:
            continue  # off-site links only when clearly relevant
        scored.append((score, u))
    scored.sort(reverse=True)
    return [u for _, u in scored[:limit]]


def strip_think(t):
    t = re.sub(r"<think>.*?</think>", "", t or "", flags=re.S)
    return re.sub(r"<think>.*", "", t, flags=re.S).strip()


def llm_complete(system, user, max_tokens, timeout=300):
    payload = {
        "model": MODEL,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user + " /no_think"}],
    }
    r = requests.post(LLM_URL, json=payload, timeout=(5, timeout))
    if r.status_code >= 400:
        try:
            err = r.json().get("error")
            err = err.get("message") if isinstance(err, dict) else err
        except ValueError:
            err = r.text[:300]
        raise RuntimeError(f"Model error ({r.status_code}): {err or 'unknown error'}")
    data = r.json()
    tm = data.get("timings") or {}
    try:
        if tm.get("predicted_per_second"):
            RECIPE_LIVE["gen_tps"] = f"{float(tm['predicted_per_second']):.1f} t/s"
        if tm.get("prompt_per_second"):
            RECIPE_LIVE["prompt_tps"] = f"{float(tm['prompt_per_second']):.1f} t/s"
    except (TypeError, ValueError):
        pass
    return strip_think(data["choices"][0]["message"].get("content") or "")


RECIPE_STOP = {"flag": False}
RECIPE_LIVE = {"speed": "", "size": "", "phase": "", "gen_tps": "", "prompt_tps": ""}  # live status bar (not written into the log)
BATTERY_TEMP_FILE = os.environ.get("BATTERY_TEMP_FILE", "/sys/class/power_supply/battery/temp")
FETCH_LIMIT = 2_000_000


def battery_temp():
    """Battery temperature as text: sysfs (tenths of °C), then termux-battery-status, else 'n/a'."""
    try:
        v = float(pathlib.Path(BATTERY_TEMP_FILE).read_text().strip())
        return f"{v / 10 if abs(v) > 200 else v:.1f}°C"
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("termux-battery-status"):
        try:
            out = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=5).stdout
            t = json.loads(out).get("temperature")
            if t is not None:
                return f"{float(t):.1f}°C"
        except Exception:  # noqa: BLE001
            pass
    return "n/a"


def _h(s):
    return hashlib.sha1((s or "").encode("utf-8", "ignore")).hexdigest()[:16]


class RecipeCache:
    """Per-URL cache: ~/nullcloud-recipes/.cache/<hash>/{pages,facts}/ + state.json."""

    def __init__(self, key):
        self.dir = RECIPES_DIR / ".cache" / _h(key)
        (self.dir / "pages").mkdir(parents=True, exist_ok=True)
        (self.dir / "facts").mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        try:
            self.state = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.state = {}
        self.state.setdefault("url", key)
        self.state.setdefault("recipes", {})

    def save_state(self, **kw):
        self.state.update(kw)
        self.state["updated"] = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception:  # noqa: BLE001
            pass

    def get_page(self, u):
        """Return (text, raw, title) only if the cached copy is valid (not failed/empty/truncated)."""
        try:
            d = json.loads((self.dir / "pages" / f"{_h(u)}.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if d.get("url") != u or d.get("truncated") or len(d.get("text") or "") < 200:
            return None
        return d["text"], d.get("raw") or "", d.get("title") or ""

    def put_page(self, u, text, raw, title, truncated):
        try:
            (self.dir / "pages" / f"{_h(u)}.json").write_text(json.dumps(
                {"url": u, "title": title, "text": text, "raw": raw, "truncated": truncated}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def get_facts(self, u, key):
        f = self.dir / "facts" / f"{_h(u + '|' + key)}.txt"
        return f.read_text(encoding="utf-8") if f.is_file() else None

    def put_facts(self, u, key, facts):
        try:
            (self.dir / "facts" / f"{_h(u + '|' + key)}.txt").write_text(facts, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _fetch_cached(cache, u, timeout):
    """Returns (text, raw, title, cached, info_line)."""
    import time

    c = cache.get_page(u)
    if c:
        RECIPE_LIVE.update(speed="cached", size="")
        return (*c, True, ">   cached\n")
    t0 = time.time()
    t, rw, tt = fetch_text_with_meta(u, timeout=timeout)
    dt = max(time.time() - t0, 0.001)
    size = len((rw or t or "").encode("utf-8", "ignore"))
    truncated = len(rw or "") >= FETCH_LIMIT
    cache.put_page(u, t, rw, tt, truncated)
    RECIPE_LIVE.update(speed=f"{size / 1024 / dt:.1f} KB/s", size=f"{size / 1024:.1f} KB")
    info = ">   truncated, will re-fetch next time\n" if truncated else ""
    return t, rw, tt, False, info


def _llm_with_heartbeat(system, user, max_tokens, every=None):
    """Run llm_complete in a thread; yield heartbeat lines (with battery temp) while it works.
    The final yielded item is ('result', value) or ('error', exc)."""
    import queue as _q
    import threading as _t

    every = every or float(os.environ.get("RECIPE_HEARTBEAT", "30"))
    q = _q.Queue()
    _t.Thread(target=lambda: q.put(_try(lambda: llm_complete(system, user, max_tokens))), daemon=True).start()
    waited = 0
    while True:
        try:
            yield q.get(timeout=every)
            return
        except _q.Empty:
            waited += every
            yield ""  # keeps the job loop alive; temp shown in the live status bar


def _try(fn):
    try:
        return ("result", fn())
    except Exception as e:  # noqa: BLE001
        return ("error", e)


def recipe_gen(url, title, text, raw, max_links=5, depth=1, ctx=2048, crawl="balanced", new_version=False):
    """Sequential (thermal-friendly): main page + ranked child links -> facts -> merged recipe(s).
    Everything is cached per URL so a second run resumes instead of starting over."""
    import time

    start = time.time()
    RECIPE_STOP["flag"] = False
    is_max = crawl == "max"
    if is_max:
        depth, max_links = 2, max(max_links, 50)
    time_budget = int(os.environ.get("RECIPE_TIME_BUDGET", "7200" if is_max else "600"))
    char_budget = int(os.environ.get("RECIPE_CHAR_BUDGET", "1000000" if is_max else "40000"))
    page_chars = max(800, (ctx - 300 - 200) * 3)  # one page per call fits the context
    sys_facts = "You extract practical knowledge. Use only the PAGE text. Be brief."
    yield ""
    cache = RecipeCache(url or ("text:" + _h(text)))
    cached_pages = 0
    if url and not text:
        yield f"> Reading main page: {url}\n"
        try:
            text, raw, ftitle, was_cached, info = _fetch_cached(cache, url, 20)
        except Exception as e:  # noqa: BLE001
            yield f"[Could not read URL: {e}]"
            cache.save_state(step="error")
            return
        yield info
        cached_pages += was_cached
        title = title or ftitle
        if len(text) < 20:
            yield "[No text to analyze.]"
            return
    RECIPE_LIVE.update(phase="fetch", gen_tps="", prompt_tps="")
    cache.save_state(step="crawling", crawl=crawl, title=title)
    pages = [(url or "(pasted text)", title, text, raw)]
    visited = {url} if url else set()
    if url and max_links > 0:
        queue = rank_links(url, raw, f"{title} {text[:300]}", visited, max_links)
        if depth >= 2 and not is_max:
            queue = queue[: max(1, max_links // 2)]
        visited.update(queue)
        queue = [(q, 1) for q in queue]
        total = len(queue)
        yield f"> Found {total} relevant link(s) on the page.\n"
        i = 0
        while queue and len(pages) - 1 < max_links:
            if RECIPE_STOP["flag"]:
                yield "> Stopped. Making a recipe from what was read so far.\n"
                break
            u, lvl = queue.pop(0)
            i += 1
            if time.time() - start > time_budget * 0.5 or sum(len(p[2]) for p in pages) > char_budget:
                yield "> Time/size budget reached, skipping the remaining links.\n"
                break
            yield f"> Reading {i}/{total}: {u}\n"
            try:
                t, rw, tt, was_cached, info = _fetch_cached(cache, u, 10)
            except Exception as e:  # noqa: BLE001
                yield f">   skipped ({str(e)[:80]})\n"
                continue
            yield info
            if len(t) < 200:
                yield ">   skipped (no useful text)\n"
                continue
            cached_pages += was_cached
            pages.append((u, tt, t, rw))
            if lvl < depth and len(pages) - 1 + len(queue) < max_links:
                more = rank_links(u, rw, f"{title} {tt}", visited, max_links - len(pages) + 1 - len(queue))
                visited.update(more)
                queue.extend((m, lvl + 1) for m in more)
                total += len(more)
    fkey = f"{page_chars}"
    cached_facts = sum(1 for p in pages if cache.get_facts(p[0], fkey) is not None)
    if cached_pages or cached_facts:
        yield f"> Resuming: {cached_pages}/{len(pages)} pages cached, {cached_facts}/{len(pages)} facts cached.\n"
    RECIPE_LIVE["phase"] = "model"
    cache.save_state(step="extracting", pages=[p[0] for p in pages])
    facts, used = [], []
    for n, (u, tt, t, _) in enumerate(pages, 1):
        if time.time() - start > time_budget or (RECIPE_STOP["flag"] and facts):
            yield "> Stopped/time budget reached, using what was read so far.\n"
            break
        f = cache.get_facts(u, fkey)
        if f is not None:
            yield f"> Key facts {n}/{len(pages)}: cached\n"
        else:
            yield f"> Extracting key facts {n}/{len(pages)}...\n"
            res = None
            for item in _llm_with_heartbeat(
                sys_facts,
                f"PAGE ({u}):\n{t[:page_chars]}\n\nTASK: List at most 8 key facts, steps and exact commands "
                "from this page as short bullets. Copy commands exactly. If nothing useful, reply NONE.",
                250,
            ):
                if isinstance(item, tuple):
                    res = item
                else:
                    yield item
            if res[0] == "error":
                yield f"[{res[1]}. Try a shorter page or a larger context (CTX_SIZE).]\n"
                if n == 1:
                    cache.save_state(step="error")
                    return
                continue
            f = res[1] or ""
            cache.put_facts(u, fkey, f)
        if f and f.strip().upper() != "NONE":
            facts.append(f"SOURCE {u}:\n{f}")
            used.append(u)
    if not facts:
        yield "[The model returned no useful facts. Try another link or raise MAX_TOKENS.]"
        return
    yield f"> Writing recipe from {len(used)} source(s)...\n\n"
    cache.save_state(step="writing")
    limit = max(800, (ctx - MAX_TOKENS - 400) * 3)
    rnd = 0
    while len("\n\n".join(facts)) > limit and len(facts) > 1 and rnd < 4:
        rnd += 1
        groups, cur = [], ""
        for f in facts:
            if cur and len(cur) + len(f) > limit:
                groups.append(cur)
                cur = ""
            cur += f[:limit] + "\n\n"
        groups.append(cur)
        if len(groups) >= len(facts):
            break
        yield f"> Condensing facts (round {rnd}, {len(groups)} group(s))...\n"
        new = []
        for g in groups:
            try:
                new.append(llm_complete(sys_facts, f"FACTS:\n{g}\n\nTASK: Merge into at most 10 short bullets. Keep exact commands.", 300))
            except Exception as e:  # noqa: BLE001
                yield f"[{e}]\n"
        facts = [x for x in new if x] or facts
    merged = "\n\n".join(facts)[:limit]
    try:
        out = llm_complete(
            "You are a private on-device assistant. Use only the FACTS.",
            f"FACTS:\n{merged}\n\nTASK: {MODES['recipe']} If the facts clearly cover different topics, "
            f"write several recipes separated by a line containing only {RECIPE_SPLIT}.",
            MAX_TOKENS,
        )
    except Exception as e:  # noqa: BLE001
        yield f"[{e}]"
        return
    if not out:
        yield "[The model returned no answer. Try again or raise MAX_TOKENS.]"
        return
    parts = [x.strip() for x in out.split(RECIPE_SPLIT) if x.strip()]
    saved = []
    prev = [] if new_version else list(cache.state["recipes"].get(crawl) or [])
    for idx, part in enumerate(parts):
        yield part + "\n\n"
        try:
            target = RECIPES_DIR / prev[idx] if idx < len(prev) and re.fullmatch(r"[a-z0-9-]+\.md", prev[idx]) else None
            saved.append(save_recipe(url, title, part, sources=used, path=target))
        except Exception as e:  # noqa: BLE001
            yield f"[Could not save recipe: {e}]\n"
    if saved:
        cache.state["recipes"][crawl] = [p.name for p in saved]
    cache.save_state(step="done")
    yield "Sources:\n" + "\n".join(f"- {u}" for u in used) + "\n"
    for sp in saved:
        yield f"\n[Recipe saved: {sp}]"
    try:
        LAST_RESULT_FILE.write_text(json.dumps({"url": url, "title": title, "mode": "recipe", "output": out,
            "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# --- Markdown Notes & SQLite FTS5 Library ---
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


SETUP_CHECKOUT_URL = "https://checkout.revolut.com/pay/ee0aad48-1ff6-452b-9470-01ae6db706a4"
PRIORITY_CHECKOUT_URL = "https://checkout.revolut.com/pay/c60fa94d-e094-4c1f-aac4-ae04c4776c52"
CONTACT_EMAIL = "Pozun.alen96@gmail.com"
SERVICES = [
    {"id": "setup", "label": "Remote setup", "price": "€30", "url": SETUP_CHECKOUT_URL},
    {"id": "priority", "label": "Setup + priority support", "price": "€45", "url": PRIORITY_CHECKOUT_URL},
    {"id": "tailscale", "label": "Private Cloud (Tailscale) setup", "price": "€60-80", "url": f"mailto:{CONTACT_EMAIL}"},
    {"id": "team", "label": "Team setup & consulting", "price": "from €250", "url": f"mailto:{CONTACT_EMAIL}"},
]


# --- HTTP Routes ---
@app.get("/")
def ui():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "ui.html")


@app.get("/health")
def health():
    compute = get_compute_config()
    return jsonify(
        ok=True,
        mode="on-device, no cloud AI",
        offline_ready=True,
        model=MODEL,
        max_chars=MAX_CHARS,
        max_tokens=MAX_TOKENS,
        free=True,
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


@app.get("/features")
def features():
    """Every feature is free. Income comes only from optional setup services."""
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    return jsonify(
        free=True,
        features=["library", "pdf", "presets", "private_cloud"],
        tailscale=get_tailscale_info(),
        services=SERVICES,
    )


@app.get("/presets")
def get_presets():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    return jsonify(presets=load_presets())


@app.post("/presets")
def add_preset():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
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
    q = request.args.get("q", "")
    items = search_library(q)
    return jsonify(items=items, count=len(items))


@app.post("/library")
def create_library_item():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
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
    _init_library_db()
    with sqlite3.connect(LIBRARY_DB) as conn:
        conn.execute("DELETE FROM pages WHERE id = ?", (item_id,))
        try:
            conn.execute("DELETE FROM pages_fts WHERE rowid = ?", (item_id,))
        except sqlite3.OperationalError:
            pass
    return jsonify(ok=True)


@app.get("/recipes")
def list_recipes():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    items = []
    if RECIPES_DIR.is_dir():
        for f in sorted(RECIPES_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            items.append({"name": f.name, "path": str(f), "size": f.stat().st_size,
                          "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")})
    return jsonify(dir=str(RECIPES_DIR), items=items)


@app.get("/recipes/<name>")
def get_recipe(name):
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    if not re.fullmatch(r"[a-z0-9-]+\.md", name):
        return jsonify(error="Bad recipe name."), 400
    f = RECIPES_DIR / name
    if not f.is_file():
        return jsonify(error="Recipe not found."), 404
    return Response(f.read_text(encoding="utf-8"), mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/recipes/stop")
def stop_recipe():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    RECIPE_STOP["flag"] = True
    return jsonify(ok=True)


# --- Recipe background jobs (run in a server thread; the browser only polls) ---
JOBS = {}
JOBS_LOCK = threading.Lock()
CURRENT_JOB = {"id": None}


def _job_file():
    return RECIPES_DIR / ".cache" / "last-job.json"


def _job_public(j):
    live = {"phase": RECIPE_LIVE.get("phase") or "", "gen_tps": RECIPE_LIVE.get("gen_tps") or "",
            "prompt_tps": RECIPE_LIVE.get("prompt_tps") or "", "speed": RECIPE_LIVE.get("speed") or "",
            "size": RECIPE_LIVE.get("size") or "", "temp": battery_temp()}
    return {k: j.get(k) for k in ("id", "url", "crawl", "status", "started", "finished")} | {"text": "".join(j["log"]), "live": live}


def _persist_job(j):
    try:
        _job_file().parent.mkdir(parents=True, exist_ok=True)
        _job_file().write_text(json.dumps(_job_public(j)), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _run_job(j, gen):
    last = 0.0
    try:
        for chunk in gen:
            if chunk:
                j["log"].append(chunk)
            if time.time() - last > 2:
                _persist_job(j)
                last = time.time()
        j["status"] = "stopped" if RECIPE_STOP["flag"] else "done"
    except Exception as e:  # noqa: BLE001
        j["log"].append(f"\n[Job failed: {e}]")
        j["status"] = "error"
    j["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    _persist_job(j)


def start_recipe_job(url, title, text, raw, ml, dp, ctx, crawl, new_version):
    """Start (or attach to) the single recipe job. Returns (job, error)."""
    with JOBS_LOCK:
        cur = JOBS.get(CURRENT_JOB["id"])
        if cur and cur["status"] == "running":
            if cur["url"] == url and cur["crawl"] == crawl:
                return cur, None
            return cur, "Another recipe job is running. Stop it first."
        j = {"id": uuid.uuid4().hex[:12], "url": url, "crawl": crawl, "status": "running", "log": [],
             "started": datetime.datetime.now().isoformat(timespec="seconds"), "finished": None}
        JOBS.clear()
        JOBS[j["id"]] = j
        CURRENT_JOB["id"] = j["id"]
        RECIPE_STOP["flag"] = False
    gen = recipe_gen(url, title, text, raw, ml, dp, ctx, crawl, new_version)
    t = threading.Thread(target=_run_job, args=(j, gen), daemon=True)
    j["thread"] = t
    t.start()
    return j, None


def _recipe_args(d, ctx):
    try:
        ml = max(0, min(8, int(d.get("max_links", 5))))
        dp = 2 if str(d.get("depth", 1)) == "2" else 1
    except (TypeError, ValueError):
        ml, dp = 5, 1
    return ml, dp, "max" if d.get("crawl") == "max" else "balanced", bool(d.get("new_version"))


@app.post("/recipes/jobs")
def create_recipe_job():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    d = request.get_json(force=True, silent=True) or {}
    url, text = (d.get("url") or "").strip(), (d.get("text") or "").strip()
    if not url and len(text) < 20:
        return jsonify(error="No text to analyze."), 400
    ctx = int(get_compute_config().get("ctx_size") or CTX_SIZE)
    ml, dp, crawl, nv = _recipe_args(d, ctx)
    j, err = start_recipe_job(url, (d.get("title") or "").strip(), text, "", ml, dp, ctx, crawl, nv)
    if err:
        return jsonify(error=err, job=_job_public(j)), 409
    return jsonify(_job_public(j))


@app.get("/recipes/jobs/current")
def current_recipe_job():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    j = JOBS.get(CURRENT_JOB["id"])
    if j:
        return jsonify(_job_public(j))
    try:
        d = json.loads(_job_file().read_text(encoding="utf-8"))
        if d.get("status") == "running":
            d["status"] = "interrupted"  # server restarted mid-job; run the same link again to resume
        return jsonify(d)
    except Exception:  # noqa: BLE001
        return jsonify(status="none")


def _tail_job(j):
    """Stream a job's log to an HTTP client. Disconnecting does not stop the job."""
    n = 0
    while True:
        log = j["log"]
        while n < len(log):
            yield log[n]
            n += 1
        if j["status"] != "running" and n >= len(j["log"]):
            return
        time.sleep(0.2)


@app.post("/analyze")
def analyze():
    if not authorized():
        return jsonify(error="Wrong or missing token."), 401
    d = request.get_json(force=True, silent=True) or {}

    text = (d.get("text") or "").strip()
    raw = ""
    title = (d.get("title") or "").strip()

    if d.get("mode") == "recipe" and not d.get("pdf_base64"):
        ctx = int(get_compute_config().get("ctx_size") or CTX_SIZE)
        ml, dp, crawl, nv = _recipe_args(d, ctx)
        url = (d.get("url") or "").strip()
        if not url and len(text) < 20:
            return jsonify(error="No text to analyze."), 400
        j, err = start_recipe_job(url, title, text, "", ml, dp, ctx, crawl, nv)
        if err:
            return jsonify(error=err), 409
        return Response(_tail_job(j), mimetype="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # PDF input (base64 encoded PDF bytes)
    if d.get("pdf_base64"):
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

    # Custom prompt presets
    if preset_id or custom_prompt or mode.startswith("preset:"):
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

    # Fit the page into the model context: ~3 chars/token is a safe estimate for
    # mixed text. Leave room for the system prompt, task and the answer.
    ctx = int(compute.get("ctx_size") or CTX_SIZE)
    budget_tokens = max(256, ctx - MAX_TOKENS - 200 - len(task) // 3)
    page_text = text[: min(MAX_CHARS, budget_tokens * 3)]

    if mode == "recipe":  # PDF input: run as a background job on the extracted text
        ml, dp, crawl, nv = _recipe_args(d, ctx)
        j, err = start_recipe_job(d.get("url") or "", title, text, raw, ml, dp, ctx, crawl, nv)
        if err:
            return jsonify(error=err), 409
        return Response(_tail_job(j), mimetype="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    payload = {
        "model": MODEL,
        "stream": True,
        # Qwen3 and other reasoning models: answer directly instead of spending
        # the whole token budget on hidden "thinking".
        "chat_template_kwargs": {"enable_thinking": False},
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
            {"role": "user", "content": f"PAGE:\n{page_text}\n\nTASK: {task} /no_think"},
        ],
    }

    def gen():
        acc = []
        state = {"in_think": False, "buf": "", "reasoning": False, "finish": None}

        def clean(delta):
            """Drop <think>...</think> blocks that some templates put into content."""
            out = []
            buf = state["buf"] + delta
            state["buf"] = ""
            while buf:
                if state["in_think"]:
                    end = buf.find("</think>")
                    if end < 0:
                        state["buf"] = buf[-8:]
                        return "".join(out)
                    buf = buf[end + 8 :]
                    state["in_think"] = False
                else:
                    start = buf.find("<think>")
                    if start < 0:
                        # keep a possible partial "<think" tag for the next chunk
                        cut = buf.rfind("<")
                        if cut >= 0 and "<think>".startswith(buf[cut:]):
                            state["buf"] = buf[cut:]
                            buf = buf[:cut]
                        out.append(buf)
                        break
                    out.append(buf[:start])
                    buf = buf[start + 7 :]
                    state["in_think"] = True
            return "".join(out)

        try:
            yield ""  # start the response so the UI knows the server is working
            with requests.post(LLM_URL, json=payload, stream=True, timeout=(5, 600)) as r:
                status = r.status_code if isinstance(r.status_code, int) else 200
                if status >= 400:
                    try:
                        err = r.json().get("error")
                        err = err.get("message") if isinstance(err, dict) else err
                    except ValueError:
                        err = r.text[:300]
                    yield f"[Model error ({status}): {err or 'unknown error'}. Try a shorter page or a larger context (CTX_SIZE).]"
                    return
                for line in r.iter_lines():
                    if not line.startswith(b"data:"):
                        if line.startswith(b"error:"):
                            yield f"[Model error: {line[6:].decode('utf-8', 'replace').strip()}]"
                        continue
                    chunk = line[5:].strip()
                    if chunk == b"[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except ValueError:
                        continue
                    if obj.get("error"):
                        e = obj["error"]
                        yield f"[Model error: {e.get('message') if isinstance(e, dict) else e}]"
                        continue
                    try:
                        choice = obj["choices"][0]
                    except (KeyError, IndexError, TypeError):
                        continue
                    state["finish"] = choice.get("finish_reason") or state["finish"]
                    dl = choice.get("delta") or {}
                    if dl.get("reasoning_content"):
                        state["reasoning"] = True
                    delta = clean(dl.get("content") or "")
                    if delta:
                        if not acc:
                            delta = delta.lstrip()
                            if not delta:
                                continue
                        acc.append(delta)
                        yield delta
            if not "".join(acc).strip():
                why = (
                    "the model spent its whole token budget thinking"
                    if state["reasoning"] or state["in_think"]
                    else f"finish reason: {state['finish'] or 'unknown'}"
                )
                yield f"[The model returned no answer ({why}). Try again, pick another preset, or raise MAX_TOKENS.]"
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
                if d.get("save_library", True):
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
