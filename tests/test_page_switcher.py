"""Round 12 phase C: coverage for /check/page and _render_page_sync — the
lazy per-page render the page-switcher UI calls on Next/Previous. Confirmed
via "Крок 1" investigation (see PROGRESS.md) that main.py's canvas render
pipeline (preview/ink_heatmap/cmyk_data/spot_separations) was page-1-only
even after round 10 phase D's real multi-page CHECKING — this is the fix
for the render side specifically, not a re-test of the check-aggregation
logic (already covered by test_checks.py/test_document_geometry.py).
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf
from fastapi.testclient import TestClient

import main

MM_TO_PT = 72 / 25.4


def _make_two_page_pdf() -> bytes:
    doc = pymupdf.open()
    p1 = doc.new_page(width=90 * MM_TO_PT, height=50 * MM_TO_PT)
    p1.set_trimbox(p1.mediabox)
    p1.insert_text((10 * MM_TO_PT, 25 * MM_TO_PT), "Clean page 1", fontsize=8)

    p2 = doc.new_page(width=90 * MM_TO_PT, height=50 * MM_TO_PT)
    p2.set_trimbox(p2.mediabox)
    p2.insert_text((1, 25 * MM_TO_PT), "Edge text page 2", fontsize=14)  # crosses the trim line

    data = doc.tobytes()
    doc.close()
    return data


def test_render_page_sync_produces_different_previews_per_page():
    data = _make_two_page_pdf()
    r0 = main._render_page_sync(data, 0, "unknown", "business_card", None, None)
    r1 = main._render_page_sync(data, 1, "unknown", "business_card", None, None)
    assert r0["preview"]["url"] != r1["preview"]["url"]
    assert r0["page_count"] == r1["page_count"] == 2


def test_render_page_sync_page_severity_is_per_page_not_aggregated():
    data = _make_two_page_pdf()
    r0 = main._render_page_sync(data, 0, "unknown", "business_card", None, None)
    r1 = main._render_page_sync(data, 1, "unknown", "business_card", None, None)
    assert r0["page_severity"] == "ok"
    assert r1["page_severity"] == "warning"
    assert r0["annotations"] == []
    assert len(r1["annotations"]) == 1
    assert r1["annotations"][0]["kind"] == "safe_zone_violation"


def test_render_page_sync_out_of_range_raises_index_error():
    data = _make_two_page_pdf()
    try:
        main._render_page_sync(data, 5, "unknown", None, None, None)
        assert False, "expected IndexError"
    except IndexError:
        pass


def test_check_page_endpoint_returns_page_specific_result():
    client = TestClient(main.app)
    data = _make_two_page_pdf()
    res = client.post(
        "/check/page?page_index=1&product_id=business_card",
        files={"file": ("test.pdf", data, "application/pdf")},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["page_severity"] == "warning"
    assert body["page_count"] == 2


def test_render_page_sync_includes_page_geometry_for_overlays():
    # The page-switcher UI needs bleed/trim/safe-zone rects for whichever
    # page is on screen, not just page 1 — added alongside the frontend
    # work since _render_page_sync's first cut only returned the render
    # images/annotations, not the geometry the canvas overlays need.
    data = _make_two_page_pdf()
    r1 = main._render_page_sync(data, 1, "unknown", "business_card", None, None)
    geo = r1["page_geometry"]
    assert geo["trim_box_pt"] is not None
    assert geo["media_box_pt"] is not None
    assert geo["safe_zone_margin_mm"] is not None
    assert len(geo["safe_zone_violations"]) == 1
    assert geo["has_declared_trimbox"] is True


def test_check_page_endpoint_out_of_range_is_400():
    client = TestClient(main.app)
    data = _make_two_page_pdf()
    res = client.post(
        "/check/page?page_index=5",
        files={"file": ("test.pdf", data, "application/pdf")},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_page_index"
