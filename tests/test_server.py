import base64
import json
import os
import subprocess
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
    monkeypatch.setattr(server, "LICENSE_FILE", tmp_path / ".nullcloud-pro.key")
    monkeypatch.setattr(server, "LIBRARY_DB", tmp_path / ".nullcloud-library.db")
    monkeypatch.setattr(server, "PRESETS_FILE", tmp_path / ".nullcloud-presets.json")
    monkeypatch.setattr(server, "LAST_RESULT_FILE", tmp_path / ".nullcloud-last.json")
    monkeypatch.setattr(server, "COMPUTE_FILE", tmp_path / ".nullcloud-compute.json")
    monkeypatch.setattr(server, "NOTES_DIR", str(tmp_path / "vault"))
    monkeypatch.setattr(server, "ARCHIVE", True)
    return server.app.test_client()


@pytest.fixture()
def pro_key(tmp_path):
    """Generate a fresh ECDSA P-256 keypair and signed Pro token via tools/license/."""
    key_dir = tmp_path / "keys"
    subprocess.run(["node", str(ROOT / "tools/license/keygen.mjs"), str(key_dir)], check=True, capture_output=True)
    pub_b64 = (key_dir / "public.b64").read_text(encoding="utf-8").strip()
    res = subprocess.run(
        ["node", str(ROOT / "tools/license/sign.mjs"), "--ref", "ORDER-999", "--key", str(key_dir / "private.pem"), "--sku", "pro"],
        check=True,
        capture_output=True,
        text=True,
    )
    signed_key = res.stdout.strip()
    return pub_b64, signed_key


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
    assert d["pro"] is False
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


def test_pro_features_gated_on_free_tier(app_client):
    headers = {"X-Token": "test-secret-token-12345"}
    # 1. Library is gated
    r_lib = app_client.get("/library", headers=headers)
    assert r_lib.status_code == 402
    locked = r_lib.get_json()
    assert locked["pro_required"] is True
    assert locked["offers"][0]["price"] == "€19 one-time"
    assert locked["offers"][0]["url"] == "https://checkout.revolut.com/pay/d25ddfdd-7351-465b-afb6-c6238f65c575"
    assert locked["offers"][1]["price"] == "€30"
    assert locked["offers"][2]["price"] == "€45"
    assert "Pozun.alen96@gmail.com" in locked["payment_flow"]
    assert "€60-80" in locked["quote"]
    assert all(item["url"].startswith("https://checkout.revolut.com/pay/") for item in locked["offers"])

    # 2. Custom presets are gated
    r_pre = app_client.post("/presets", headers=headers, json={"name": "Test", "prompt": "Do X"})
    assert r_pre.status_code == 402

    # 3. PDF input is gated
    fake_pdf = base64.b64encode(b"%PDF-1.4\n(Hello PDF) Tj\n").decode("ascii")
    r_pdf = app_client.post("/analyze", headers=headers, json={"pdf_base64": fake_pdf, "mode": "summary"})
    assert r_pdf.status_code == 402

    # 4. Preset mode in /analyze is gated
    r_pm = app_client.post(
        "/analyze",
        headers=headers,
        json={"text": "Enough characters to analyze with a preset mode.", "mode": "preset:legal-privilege"},
    )
    assert r_pm.status_code == 402


def test_offline_ecdsa_pro_activation_and_features(app_client, pro_key, monkeypatch):
    pub_b64, signed_key = pro_key
    monkeypatch.setattr(server, "LICENSE_PUBKEY", pub_b64)
    headers = {"X-Token": "test-secret-token-12345"}

    # Reject tampered or fake keys
    bad = app_client.post("/pro/activate", headers=headers, json={"key": "paid"})
    assert bad.status_code == 400
    tampered = signed_key[:-4] + "AAAA"
    bad2 = app_client.post("/pro/activate", headers=headers, json={"key": tampered})
    assert bad2.status_code == 400

    # Activate valid signed Pro key offline
    act = app_client.post("/pro/activate", headers=headers, json={"key": signed_key})
    assert act.status_code == 200
    act_data = act.get_json()
    assert act_data["pro"] is True
    assert act_data["claims"]["sku"] == "pro"
    assert "tailscale" in act_data

    # Verify Pro presets (Legal, Journalism, Clinical, Executive) + custom preset creation
    pre_res = app_client.get("/presets", headers=headers).get_json()
    assert pre_res["pro"] is True
    preset_ids = {p["id"] for p in pre_res["presets"]}
    assert {"legal-privilege", "journalism-source", "clinical-intake", "exec-brief"}.issubset(preset_ids)

    add_pre = app_client.post(
        "/presets",
        headers=headers,
        json={"name": "M&A Term Sheet Check", "category": "Legal", "prompt": "Extract valuation and liquidation preferences."},
    )
    assert add_pre.status_code == 200

    # Verify Pro PDF extraction (FlateDecode compressed stream)
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
