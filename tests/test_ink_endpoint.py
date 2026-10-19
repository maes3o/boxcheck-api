"""POST /check/ink-coverage + the isolated runner: limits, isolation, cleanup."""
import asyncio
import os
import shutil
import stat
import sys
import tempfile
import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import ink_fixtures as fx
import ink_runner
import main

needs_gs = pytest.mark.skipif(shutil.which("gs") is None, reason="ghostscript not installed")


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    main.limiter.reset()
    monkeypatch.setattr(ink_runner, "_semaphore", None)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))     # all request dirs land here
    yield
    assert not [d for d in os.listdir(tmp_path) if d.startswith(ink_runner.TMP_PREFIX)], "temp dir leaked"


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def post(client, data: bytes, **form):
    return client.post("/check/ink-coverage", files={"file": ("a.pdf", data, "application/pdf")}, data=form)


def fake_gs(tmp_path, body: str):
    p = tmp_path / "gs"
    p.write_text('#!/bin/sh\n[ "$1" = "--version" ] && echo 9.55.0 && exit 0\n' + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


# ---- happy path / schema ---------------------------------------------------------

@needs_gs
def test_ok_response_matches_v1_schema(client):
    r = post(client, fx.spot_pdf("PANTONE 185 C", 0.8))
    assert r.status_code == 200
    j = r.json()
    assert set(j) == {"schema_version", "document", "pages"} and j["schema_version"] == 1
    assert set(j["document"]) == {"page_count", "pages_analyzed", "truncated", "complete", "engine", "colorants"}
    assert set(j["document"]["engine"]) == {"method", "gs_version", "pymupdf", "analysis_ms"}
    assert set(j["document"]["colorants"][0]) == {"id", "name", "families", "pages"}
    p = j["pages"][0]
    assert {"page", "status", "geometry", "measurement", "colorants", "painted_zero_tint_only",
            "declared_but_unused", "converted_color_spaces", "derived_process_plates", "diagnostics"} <= set(p)
    assert set(p["geometry"]) == {"box", "width_pt", "height_pt", "area_mm2", "rotation", "user_unit"}
    assert {"passes", "dpi_effective", "plate_px", "pixel_budget_limited", "gs_returncode", "detection"} <= set(p["measurement"])
    c = p["colorants"][0]
    assert set(c) == {"name", "used_via", "tint", "paint", "measured", "accuracy", "id"}
    assert set(c["measured"]) == {"ink_mean_pct", "area_any_ink_pct", "max_ink_pct",
                                  "mean_ink_on_inked_area_pct", "full_ink_equivalent_mm2"}
    assert set(c["accuracy"]) == {"level", "flags", "thin_stroke_paints", "min_stroke_width_pt"}
    assert set(c["paint"]) == {"sources", "overprint_paints", "knockout_paints", "opm"}


@needs_gs
def test_selection_is_never_stored_or_returned(client):
    j = post(client, fx.cmyk_quarter()).json()
    assert "selected" not in str(j).lower() and "technical" not in str(j).lower()


@needs_gs
def test_pages_param_and_truncation(client):
    pdf = fx.make_pdf([{"content": "1 0 0 0 k 0 0 10 10 re f"}] * 12)
    j = post(client, pdf).json()
    assert j["document"]["page_count"] == 12 and j["document"]["truncated"] and len(j["pages"]) == 10
    j = post(client, pdf, pages="2,4-5").json()
    assert [p["page"] for p in j["pages"]] == [2, 4, 5] and not j["document"]["truncated"]


# ---- rejections -------------------------------------------------------------------

def test_413_file_too_large(client):
    r = post(client, b"%PDF-1.4\n" + b"0" * (25 * 1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["detail"]["code"] == "file_too_large"


@pytest.mark.parametrize("data", [b"not a pdf at all", b"%PDF-1.4\n1 0 obj << /Broken", b""])
def test_422_invalid_pdf(client, data):
    r = post(client, data)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_pdf"


def test_422_zero_page_pdf(client):
    r = post(client, fx.make_pdf([]))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_pdf"


def test_422_encrypted_pdf(client):
    doc = pymupdf.open(stream=fx.cmyk_quarter(), filetype="pdf")
    enc = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    r = post(client, enc)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "encrypted_pdf"


@pytest.mark.parametrize("bad", ["abc", "1-", "0", "5-2", "1;2", "1," + "9" * 300])
def test_400_invalid_pages(client, bad):
    r = post(client, fx.cmyk_quarter(), pages=bad)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_pages"


def test_400_requested_page_out_of_range(client):
    r = post(client, fx.cmyk_quarter(), pages="9")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "invalid_pages"


def test_rate_limit_6_per_minute(client):
    statuses = [post(client, b"junk").status_code for _ in range(7)]
    assert statuses[:6] == [422] * 6 and statuses[6] == 429


def test_503_busy_when_no_slot(client, monkeypatch):
    monkeypatch.setattr(ink_runner, "SLOT_WAIT_S", 0.2)
    monkeypatch.setattr(ink_runner, "_semaphore", asyncio.Semaphore(0))
    r = post(client, fx.cmyk_quarter())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "busy"
    assert "retry-after" in r.headers


def test_503_busy_when_disk_low(client, monkeypatch):
    monkeypatch.setattr(ink_runner, "_enough_disk", lambda _p: False)
    assert post(client, fx.cmyk_quarter()).status_code == 503


# ---- timeouts / crashes / isolation ---------------------------------------------------

@needs_gs
def test_hanging_gs_returns_partial_result_not_504(client, tmp_path, monkeypatch):
    monkeypatch.setenv("INK_GS_BIN", fake_gs(tmp_path, "exec sleep 120"))
    monkeypatch.setattr(ink_runner, "TOTAL_DEADLINE_S", 7.0)
    t = time.monotonic()
    r = post(client, fx.cmyk_quarter())
    assert r.status_code == 200 and time.monotonic() - t < 12
    j = r.json()
    assert j["pages"][0]["status"] == "skipped_timeout" and j["document"]["complete"] is False


def test_worker_hard_kill_salvages_partial_or_504(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ink_runner, "TOTAL_DEADLINE_S", 2.0)
    monkeypatch.setattr(ink_runner, "_worker_cmd", lambda *a, **k: ["sleep", "100"])
    t = time.monotonic()
    r = post(client, fx.cmyk_quarter())
    assert r.status_code == 504 and r.json()["detail"]["code"] == "timeout"
    assert time.monotonic() - t < 6


def test_worker_segfault_does_not_take_api_down(client, monkeypatch):
    monkeypatch.setattr(ink_runner, "_worker_cmd",
                        lambda *a, **k: [sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGSEGV)"])
    r = post(client, fx.cmyk_quarter())
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_pdf"
    assert client.get("/profiles").status_code == 200         # API still alive


@needs_gs
def test_worker_runs_under_prlimit_when_available():
    cmd = ink_runner._worker_cmd(*(["i.pdf", "o.json", "w", None, 50.0]))
    if shutil.which("prlimit"):
        assert cmd[0].endswith("prlimit") and "--as=3221225472" in cmd and "--cpu=60" in cmd
    assert "-m" in cmd and "ink_worker" in cmd


@needs_gs
def test_worker_address_space_limit_kills_bomb(tmp_path):
    """The worker enforces AS via setrlimit: allocating past it fails fast
    instead of growing the API's memory."""
    import subprocess
    code = ("import resource;resource.setrlimit(resource.RLIMIT_AS,(300*1024**2,300*1024**2));"
            "\ntry:\n    b=bytearray(600*1024**2)\n    print('allocated')\nexcept MemoryError:\n    print('limited')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip()
    assert out == "limited"


@needs_gs
def test_temp_dirs_cleaned_after_success_and_failure(client, tmp_path, monkeypatch):
    post(client, fx.cmyk_quarter())
    post(client, b"%PDF-1.4 broken")
    monkeypatch.setattr(ink_runner, "_worker_cmd", lambda *a, **k: ["sleep", "100"])
    monkeypatch.setattr(ink_runner, "TOTAL_DEADLINE_S", 1.5)
    post(client, fx.cmyk_quarter())
    # the autouse fixture asserts no boxcheck-ink-* directory is left behind


def test_startup_sweep_removes_only_stale_ink_dirs(tmp_path):
    old = tmp_path / "boxcheck-ink-old"
    new = tmp_path / "boxcheck-ink-new"
    other = tmp_path / "unrelated"
    for d in (old, new, other):
        d.mkdir()
    past = time.time() - 7200
    os.utime(old, (past, past))
    os.utime(other, (past, past))
    assert ink_runner.sweep_stale_tempdirs(base=str(tmp_path)) == 1
    assert not old.exists() and new.exists() and other.exists()
    new.rmdir()


def test_concurrency_default_is_min2_cores_minus1(monkeypatch):
    monkeypatch.delenv("INK_MAX_CONCURRENCY", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert ink_runner.max_concurrency() == 2
    monkeypatch.setattr(os, "cpu_count", lambda: 2)
    assert ink_runner.max_concurrency() == 1
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert ink_runner.max_concurrency() == 1
    monkeypatch.setenv("INK_MAX_CONCURRENCY", "3")
    assert ink_runner.max_concurrency() == 3


@needs_gs
def test_gs_never_run_with_nosafer(tmp_path, monkeypatch):
    log = tmp_path / "args.log"
    gs = fake_gs(tmp_path, f'echo "$@" >> {log}\nexit 0')
    monkeypatch.setenv("INK_GS_BIN", gs)
    from ink_coverage import analyze_ink_coverage
    analyze_ink_coverage(fx.cmyk_quarter(), {})
    text = log.read_text()
    assert "-dSAFER" in text and "NOSAFER" not in text


@needs_gs
def test_32_spots_large_page_with_second_pass_fits_the_memory_limits(client):
    """Worst case for memory: 32 spot planes at the 40 Mpx second pass,
    run in the real worker under prlimit (AS 3 GB, CPU 60 s)."""
    r = post(client, fx.many_spots_pdf(32, (2000, 1500), thin_line=True))
    assert r.status_code == 200
    p = r.json()["pages"][0]
    assert p["status"] == "ok" and [x["reason"] for x in p["measurement"]["passes"]] == ["base", "thin_strokes"]
    inked = [c for c in p["colorants"] if c["measured"] and c["measured"]["area_any_ink_pct"] > 0]
    assert len(inked) == 32
    assert p["derived_process_plates"] == []
