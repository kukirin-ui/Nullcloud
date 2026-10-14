import base64
import json
import os
import sys
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

os.environ["NULLCLOUD_TESTING"] = "1"
os.environ["TOKEN"] = "test-secret-token-12345"

import server  # noqa: E402


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "TOKEN", "test-secret-token-12345")
    monkeypatch.setattr(server, "LIBRARY_DB", tmp_path / ".nullcloud-library.db")
    monkeypatch.setattr(server, "PRESETS_FILE", tmp_path / ".nullcloud-presets.json")
    monkeypatch.setattr(server, "LAST_RESULT_FILE", tmp_path / ".nullcloud-last.json")
    monkeypatch.setattr(server, "COMPUTE_FILE", tmp_path / ".nullcloud-compute.json")
    monkeypatch.setattr(server, "NOTES_DIR", str(tmp_path / "vault"))
    monkeypatch.setattr(server, "ARCHIVE", True)
    return server.app.test_client()


def _mock_llm_stream(chunks=("Bullet 1\n", "Bullet 2\n", "Why it matters.")):
    lines = [f'data: {{"choices":[{{"delta":{{"content":{json.dumps(c)}}}}}]}}'.encode("utf-8") for c in chunks]
    lines.append(b"data: [DONE]")
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.raise_for_status.return_value = None
    mock_resp.iter_lines.return_value = lines
    return mock_resp


def test_health_and_branding(app_client):
    r = app_client.get("/health")
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["mode"] == "on-device, no cloud AI"
    assert d["offline_ready"] is True
    assert d["free"] is True
    assert "compute" in d
    assert d["compute"]["gpu_layers"] == 99
    assert d["compute"]["cpu_threads"] >= 1


def test_cpu_and_gpu_hardware_tweaks(app_client):
    headers = {"X-Token": "test-secret-token-12345"}
    r0 = app_client.get("/hardware", headers=headers)
    assert r0.status_code == 200
    assert r0.get_json()["compute"]["gpu_layers"] == 99

    r1 = app_client.post(
        "/hardware",
        headers=headers,
        json={"gpu_layers": 16, "cpu_threads": 4, "flash_attn": True, "kv_cache": "q8_0/q4_0"},
    )
    assert r1.status_code == 200
    c = r1.get_json()["compute"]
    assert c["gpu_layers"] == 16
    assert c["cpu_threads"] == 4
    assert "GPU" in c["accel_summary"] and "CPU" in c["accel_summary"]


def test_auth_required(app_client):
    r = app_client.post("/analyze", json={"text": "Some long text that should require authentication."})
    assert r.status_code == 401
    r2 = app_client.post(
        "/analyze",
        headers={"X-Token": "wrong-token"},
        json={"text": "Some long text that should require authentication."},
    )
    assert r2.status_code == 401


def test_ssrf_blocks_private_and_loopback():
    for bad_url in [
        "http://127.0.0.1:8080/health",
        "http://localhost/admin",
        "http://0.0.0.0/",
        "http://printer.local/status",
        "ftp://example.com/file",
    ]:
        with pytest.raises(ValueError):
            server.validate_public_url(bad_url)


def test_free_core_airplane_mode_text_analysis(app_client):
    with patch("server.requests.post", return_value=_mock_llm_stream()):
        r = app_client.post(
            "/analyze",
            headers={"X-Token": "test-secret-token-12345"},
            json={
                "text": "This is an open article analyzed completely offline in Airplane Mode on the phone.",
                "mode": "summary",
                "url": "https://example.com/article",
            },
        )
        assert r.status_code == 200
        assert "Bullet 1" in r.get_data(as_text=True)

    last = app_client.get("/last", headers={"X-Token": "test-secret-token-12345"})
    assert last.status_code == 200
    assert "Bullet 1" in last.get_json()["output"]


def test_all_features_free_and_services_listed(app_client):
    headers = {"X-Token": "test-secret-token-12345"}
    f = app_client.get("/features", headers=headers)
    assert f.status_code == 200
    d = f.get_json()
    assert d["free"] is True
    assert set(d["features"]) == {"library", "pdf", "presets", "private_cloud"}
    prices = {s["id"]: s["price"] for s in d["services"]}
    assert prices == {"setup": "€30", "priority": "€45", "tailscale": "€60-80", "team": "from €250"}
    assert all("d25ddfdd" not in s["url"] for s in d["services"])
    assert app_client.get("/pro/status", headers=headers).status_code == 404


def test_library_presets_and_pdf_work_without_license(app_client):
    headers = {"X-Token": "test-secret-token-12345"}
    assert app_client.get("/library", headers=headers).status_code == 200

    # Verify presets (Legal, Journalism, Clinical, Executive) + custom preset creation
    pre_res = app_client.get("/presets", headers=headers).get_json()
    preset_ids = {p["id"] for p in pre_res["presets"]}
    assert {"legal-privilege", "journalism-source", "clinical-intake", "exec-brief"}.issubset(preset_ids)

    add_pre = app_client.post(
        "/presets",
        headers=headers,
        json={"name": "M&A Term Sheet Check", "category": "Legal", "prompt": "Extract valuation and liquidation preferences."},
    )
    assert add_pre.status_code == 200

    # Verify PDF extraction (FlateDecode compressed stream)
    stream_body = zlib.compress(b"BT /F1 12 Tf 72 712 Td (Confidential Legal Contract Clause 42: Governing Law and Arbitration) Tj ET")
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<< /Length " + str(len(stream_body)).encode() + b" /Filter /FlateDecode >>\nstream\n" + stream_body + b"\nendstream\nendobj\n%%EOF"
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    with patch("server.requests.post", return_value=_mock_llm_stream(("Clause 42 summary.",))):
        r_pdf = app_client.post(
            "/analyze",
            headers=headers,
            json={"pdf_base64": pdf_b64, "filename": "contract.pdf", "mode": "preset:legal-privilege"},
        )
        assert r_pdf.status_code == 200
        assert "Clause 42 summary." in r_pdf.get_data(as_text=True)

    # Verify Saved-Page Library & SQLite FTS5 Search
    lib_all = app_client.get("/library", headers=headers).get_json()
    assert lib_all["count"] == 1
    assert lib_all["items"][0]["title"] == "contract.pdf"

    lib_hit = app_client.get("/library?q=Arbitration", headers=headers).get_json()
    assert lib_hit["count"] == 1

    lib_miss = app_client.get("/library?q=nonexistentwordxyz", headers=headers).get_json()
    assert lib_miss["count"] == 0


def test_rank_links_skips_nav_social_media_and_dupes():
    html = ('<nav><a href="/vulkan-nav">Vulkan nav</a></nav><a href="/login">Login</a>'
            '<a href="/vulkan-build">Vulkan build guide</a><a href="/vulkan-build">again</a>'
            '<a href="/x.png">Vulkan image</a><a href="https://facebook.com/s">Share</a>')
    links = server.rank_links("https://ex.com/a", html, "vulkan build", {"https://ex.com/a"}, 5)
    assert links == ["https://ex.com/vulkan-build"]


def test_recipe_mode_follows_links_and_saves(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RECIPES_DIR", tmp_path / "recipes")
    main = ("Vulkan build guide " * 20, '<a href="/child">Vulkan build steps</a>', "Vulkan build")
    child = ("cmake -B build -DGGML_VULKAN=ON " * 20, "", "Child")
    monkeypatch.setattr(server, "fetch_text_with_meta", lambda u, timeout=20: child if u.endswith("/child") else main)
    monkeypatch.setattr(server, "llm_complete", lambda s, u, m, timeout=300: "- fact" if u.startswith("PAGE") else "# Vulkan Build\n## Problem\nx")
    h = {"X-Token": "test-secret-token-12345"}
    for _ in range(2):
        out = app_client.post("/analyze", headers=h, json={"url": "https://ex.com/", "mode": "recipe"}).get_data(as_text=True)
        assert "Reading 1/1: https://ex.com/child" in out and "Recipe saved" in out
    names = [i["name"] for i in app_client.get("/recipes", headers=h).get_json()["items"]]
    assert sorted(names) == ["vulkan-build-2.md", "vulkan-build.md"]
    md = app_client.get("/recipes/vulkan-build.md", headers=h).get_data(as_text=True)
    assert "- https://ex.com/child" in md and "## Date" in md
