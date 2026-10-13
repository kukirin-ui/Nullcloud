const $ = (id) => document.getElementById(id);
const DEFAULT_API = "http://127.0.0.1:8080";
const store = chrome.storage.local;

function toggleAsk() {
  $("q").style.display = $("mode").value === "ask" ? "block" : "none";
}

function getApiUrl() {
  return ($("api").value.trim() || DEFAULT_API).replace(/\/+$/, "");
}

async function loadPresets(api, token) {
  if (!token) return;
  try {
    const headers = { "X-Token": token };
    const r = await fetch(api + "/presets", { headers });
    if (!r.ok) return;
    const d = await r.json();
    const existing = new Set(Array.from($("mode").options).map((o) => o.value));
    (d.presets || []).forEach((p) => {
      const val = "preset:" + p.id;
      if (!existing.has(val)) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = p.name;
        $("mode").appendChild(opt);
      }
    });
  } catch (_) {}
}

(async () => {
  const s = await store.get(["token", "lang", "mode", "api", "gpu"]);
  $("token").value = s.token || "";
  $("lang").value = s.lang || "";
  $("mode").value = s.mode || "summary";
  $("api").value = s.api || DEFAULT_API;
  $("gpu").value = s.gpu || "99";
  toggleAsk();
  loadPresets(getApiUrl(), $("token").value.trim());
})();

$("mode").addEventListener("change", toggleAsk);
$("copy").addEventListener("click", () => navigator.clipboard.writeText($("out").textContent));
$("open-ui").addEventListener("click", () => chrome.tabs.create({ url: getApiUrl() }));

$("go").addEventListener("click", async () => {
  const out = $("out");
  const token = $("token").value.trim();
  const lang = $("lang").value.trim();
  const mode = $("mode").value;
  const api = getApiUrl();
  const gpu = $("gpu").value || "99";
  await store.set({ token, lang, mode, api, gpu });
  if (!token) {
    out.textContent = "Paste your token first (printed by setup.sh / start.sh).";
    return;
  }
  out.textContent = "Reading open page (offline-capable)...";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        sel: String(getSelection()).trim(),
        body: document.body ? document.body.innerText : "",
        title: document.title,
      }),
    });
    const page = res.result;
    const text = "Title: " + page.title + "\n\n" + (page.sel.length > 40 ? page.sel : page.body);
    out.textContent = "Thinking (on-device CPU + GPU, no cloud AI)...";
    const headers = { "Content-Type": "application/json", "X-Token": token };
    const r = await fetch(api + "/analyze", {
      method: "POST",
      headers,
      body: JSON.stringify({
        text,
        title: page.title,
        mode,
        q: $("q").value,
        lang,
        url: tab.url,
        gpu_layers: Number(gpu),
      }),
    });
    if (r.status === 401) {
      out.textContent = "Wrong token.";
      return;
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      out.textContent = err.error || "Error " + r.status;
      return;
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    out.textContent = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      out.textContent += dec.decode(value, { stream: true });
    }
  } catch (e) {
    out.textContent =
      "Cannot reach the local/Tailscale server (" +
      e.message +
      "). Is it running? See README > Troubleshooting.";
  }
});

$("speak").addEventListener("click", () => {
  if (speechSynthesis.speaking) {
    speechSynthesis.cancel();
    return;
  }
  speechSynthesis.speak(new SpeechSynthesisUtterance($("out").textContent));
});
