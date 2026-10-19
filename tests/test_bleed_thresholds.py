"""Round 11 phase E: regression coverage for the "unknown" print-method bleed
threshold split (main.py's UNKNOWN_METHOD_BLEED_MM_BY_PRODUCT).

Context: Gemini's audit proposed lowering the flat "unknown" bleed default
from 5mm to 2-3mm, arguing that 5mm is packaging/die-cut territory and too
strict for flat sheet-fed products (business cards, flyers, ...). Before
touching the documented-conservative "unknown" profile, we built this
synthetic fixture — a flyer-sized page with a real, industry-normal 3mm
bleed on every side — and confirmed the OLD flat-5mm logic flagged it as a
false "critical" (adaptReport.ts maps bleed_warning=True to "critical", not
just "warning"). That confirmed the problem was real, not just theoretical,
and justified the product-category split below instead of leaving Phase E
unimplemented.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf

import main


def _make_flat_product_pdf(tmp_path, trim_w_mm: float, trim_h_mm: float, bleed_mm: float) -> bytes:
    mm_to_pt = 72 / 25.4
    trim_w_pt, trim_h_pt = trim_w_mm * mm_to_pt, trim_h_mm * mm_to_pt
    bleed_pt = bleed_mm * mm_to_pt

    doc = pymupdf.open()
    page = doc.new_page(width=trim_w_pt + 2 * bleed_pt, height=trim_h_pt + 2 * bleed_pt)
    page.set_mediabox(pymupdf.Rect(0, 0, page.rect.width, page.rect.height))
    mediabox = page.mediabox  # re-read: float32-rounded, avoids "not in MediaBox" from stale doubles

    trimbox = pymupdf.Rect(bleed_pt, bleed_pt, mediabox.x1 - bleed_pt, mediabox.y1 - bleed_pt)
    page.set_cropbox(mediabox)
    page.set_trimbox(trimbox)
    page.insert_text((trimbox.x0 + 5, trimbox.y0 + 10), "test", fontsize=8)

    data = doc.tobytes()
    doc.close()
    return data


def test_unknown_method_5mm_default_false_positives_on_normal_flyer_bleed(tmp_path):
    """The old flat "unknown"=5mm default flags a completely normal 3mm
    flat-sheet bleed as a false critical when no product is selected — this
    is the empirical evidence Phase E's analysis required before touching
    the threshold. Kept as a permanent regression marker for that baseline
    behavior (still correct: with no product, 5mm remains the right
    worst-case default, since the file could turn out to be packaging)."""
    data = _make_flat_product_pdf(tmp_path, trim_w_mm=105.0, trim_h_mm=148.0, bleed_mm=3.0)
    result = main._check_pdf_sync(data, "flyer_3mm_bleed.pdf", "unknown", None, "mm")
    assert result["bleed_mm"] == 3.0
    assert result["thresholds_used"]["bleed_mm"] == 5.0
    assert result["bleed_warning"] is True


def test_unknown_method_flat_product_gets_relaxed_bleed_threshold(tmp_path):
    """Same file, but with a flat sheet-fed product selected (flyer) — the
    product-category override drops the effective threshold to 2.5mm, so
    the same normal 3mm bleed correctly passes."""
    data = _make_flat_product_pdf(tmp_path, trim_w_mm=105.0, trim_h_mm=148.0, bleed_mm=3.0)
    result = main._check_pdf_sync(data, "flyer_3mm_bleed.pdf", "unknown", None, "mm", product_id="flyer")
    assert result["bleed_mm"] == 3.0
    assert result["thresholds_used"]["bleed_mm"] == 2.5
    assert result["bleed_warning"] is False


def test_unknown_method_packaging_product_keeps_conservative_5mm(tmp_path):
    """Packaging/die-cut tier-1 products are deliberately absent from the
    override table — the same 3mm bleed should still fail for them, since
    5mm is a genuine requirement there, not an artifact of not knowing the
    print method."""
    data = _make_flat_product_pdf(tmp_path, trim_w_mm=105.0, trim_h_mm=148.0, bleed_mm=3.0)
    result = main._check_pdf_sync(data, "flyer_3mm_bleed.pdf", "unknown", None, "mm", product_id="packaging_box")
    assert result["thresholds_used"]["bleed_mm"] == 5.0
    assert result["bleed_warning"] is True


def test_explicit_bleed_threshold_overrides_product_category_default(tmp_path):
    """An explicit bleed_threshold query param must still win over both the
    profile default and the product-category override — advanced overrides
    (round 6) must not be silently shadowed by this new table."""
    data = _make_flat_product_pdf(tmp_path, trim_w_mm=105.0, trim_h_mm=148.0, bleed_mm=3.0)
    result = main._check_pdf_sync(data, "flyer_3mm_bleed.pdf", "unknown", None, "mm", bleed_threshold=1.0, product_id="flyer")
    assert result["thresholds_used"]["bleed_mm"] == 1.0
    assert result["bleed_warning"] is False
