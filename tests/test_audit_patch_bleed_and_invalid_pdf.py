"""Production-readiness audit patch: B1 (bleed float tolerance) and B2
(damaged/truncated PDF -> 422 invalid_pdf with CORS headers, not a 500)."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main

MM = 72 / 25.4


def _pdf_with_bleed(bleed_mm: float, trim_w_mm: float = 100.0, trim_h_mm: float = 150.0) -> bytes:
    bleed_pt = bleed_mm * MM
    doc = pymupdf.open()
    page = doc.new_page(width=trim_w_mm * MM + 2 * bleed_pt, height=trim_h_mm * MM + 2 * bleed_pt)
    mediabox = page.mediabox
    page.set_trimbox(pymupdf.Rect(bleed_pt, bleed_pt, mediabox.x1 - bleed_pt, mediabox.y1 - bleed_pt))
    page.insert_text((40, 60), "bleed test", fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def _check(data: bytes) -> dict:
    # carton profile: bleed threshold 3.0 mm
    return main._check_pdf_sync(data, "bleed.pdf", "carton", None, "mm")


# ---- B1: bleed tolerance ----

def test_exact_3mm_bleed_passes_the_3mm_threshold():
    r = _check(_pdf_with_bleed(3.0))
    assert r["thresholds_used"]["bleed_mm"] == 3.0
    assert r["bleed_mm"] == 3.0
    assert r["bleed_warning"] is False


def test_float32_truncated_3mm_bleed_passes():
    # Exactly the case from the audit: 8.503937 pt is 2.9999999 mm.
    data = _pdf_with_bleed(3.0)
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc[0]
    t = page.trimbox
    page.set_trimbox(pymupdf.Rect(8.503937, 8.503937, t.x1, t.y1))
    raw_mm = min(page.trimbox.x0 - page.mediabox.x0, page.trimbox.y0 - page.mediabox.y0) * 25.4 / 72
    assert raw_mm < 3.0  # the precondition: strictly below 3 by float noise
    r = _check(doc.tobytes())
    assert r["bleed_warning"] is False


def test_slightly_below_threshold_within_tolerance_passes():
    assert _check(_pdf_with_bleed(2.96))["bleed_warning"] is False


def test_clearly_insufficient_bleed_still_fails():
    for bleed in (2.9, 2.5, 1.0):
        r = _check(_pdf_with_bleed(bleed))
        assert r["bleed_warning"] is True, bleed


def test_no_bleed_still_reports_warning_state():
    r = _check(_pdf_with_bleed(0.0))
    assert r["bleed_mm"] == 0.0
    assert r["bleed_warning"] is True


def test_tolerance_is_applied_to_overridden_thresholds_too():
    # 5 mm demanded, 3 mm present: still a real failure.
    r = main._check_pdf_sync(_pdf_with_bleed(3.0), "bleed.pdf", "carton", None, "mm", bleed_threshold=5.0)
    assert r["bleed_warning"] is True


# ---- B2: damaged PDFs ----

@pytest.fixture()
def client():
    main.limiter.reset()
    return TestClient(main.app, raise_server_exceptions=False)


def _truncated_pdf() -> bytes:
    img = io.BytesIO()
    Image.new("RGB", (590, 590), (200, 30, 30)).save(img, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=440)
    page.insert_image(pymupdf.Rect(20, 20, 200, 200), stream=img.getvalue())
    page.insert_text((20, 300), "Hello", fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data[: len(data) // 2]


def _post(client, data: bytes, path="/check"):
    return client.post(path, files={"file": ("broken.pdf", data, "application/pdf")}, headers={"Origin": "https://boxcheck.org"})


def test_truncated_pdf_is_422_invalid_pdf_not_500(client):
    resp = _post(client, _truncated_pdf())
    assert resp.status_code == 422
    assert resp.json() == {"detail": {"code": "invalid_pdf", "message": "File is not a valid or readable PDF."}}


def test_invalid_pdf_error_path_carries_cors_headers(client):
    resp = _post(client, _truncated_pdf())
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_invalid_pdf_response_exposes_no_internals(client):
    body = _post(client, _truncated_pdf()).text
    for leak in ("Traceback", "FzError", "mupdf", "color space", ".py"):
        assert leak not in body


def test_garbage_and_empty_files_keep_their_422(client):
    for data in (b"", b"not a pdf at all" * 50, b"%PDF-1.7\n" + os.urandom(2000)):
        resp = _post(client, data)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "invalid_pdf"


def test_valid_pdf_is_unchanged(client):
    resp = _post(client, _pdf_with_bleed(3.0))
    assert resp.status_code == 200
    body = resp.json()
    assert body["page_count"] == 1
    assert body["bleed_warning"] in (True, False)
