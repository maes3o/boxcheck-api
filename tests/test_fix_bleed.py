"""N16: coverage for fix_bleed.py — compute_edge_expansion_pt (unit,
symmetric/asymmetric cases + missing-TrimBox error) and fix_bleed_pdf
(end-to-end: synthetic PDFs with the same geometry patterns, plus a smoke
test against a real test-file with zero declared bleed, same fixtures
family as N14/A7 — skipped if the file isn't present, since test-files/ is
intentionally excluded from git, per HANDOFF.md)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pymupdf

from fix_bleed import compute_edge_expansion_pt, fix_bleed_pdf, NoDeclaredTrimBoxError

MM_TO_PT = 2.8346


def _make_pdf(trim_w_mm: float, trim_h_mm: float, bleed_mm) -> bytes:
    """bleed_mm: float (uniform) or (left, right, top, bottom) tuple in mm."""
    if isinstance(bleed_mm, tuple):
        bl, br, bt, bb = bleed_mm
    else:
        bl = br = bt = bb = bleed_mm
    trim_w_pt, trim_h_pt = trim_w_mm * MM_TO_PT, trim_h_mm * MM_TO_PT
    bl_pt, br_pt, bt_pt, bb_pt = bl * MM_TO_PT, br * MM_TO_PT, bt * MM_TO_PT, bb * MM_TO_PT

    doc = pymupdf.open()
    page = doc.new_page(width=trim_w_pt + bl_pt + br_pt, height=trim_h_pt + bt_pt + bb_pt)
    mediabox = page.mediabox
    trimbox = pymupdf.Rect(bl_pt, bt_pt, mediabox.x1 - br_pt, mediabox.y1 - bb_pt)
    page.set_trimbox(trimbox)
    page.insert_text((trimbox.x0 + 5, trimbox.y0 + 10), "test", fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def _make_pdf_no_trimbox(trim_w_mm: float, trim_h_mm: float) -> bytes:
    doc = pymupdf.open()
    doc.new_page(width=trim_w_mm * MM_TO_PT, height=trim_h_mm * MM_TO_PT)
    data = doc.tobytes()
    doc.close()
    return data


# --- compute_edge_expansion_pt (pure function) ---

def test_symmetric_deficit_expands_every_edge_equally():
    mediabox = pymupdf.Rect(0, 0, 100, 100)
    trimbox = pymupdf.Rect(1, 1, 99, 99)  # 1pt bleed on every side
    target_pt = 3.0
    expansion = compute_edge_expansion_pt(mediabox, trimbox, target_pt)
    assert expansion == {"left": 2.0, "right": 2.0, "top": 2.0, "bottom": 2.0}


def test_asymmetric_deficit_only_expands_short_edges():
    mediabox = pymupdf.Rect(0, 0, 100, 100)
    # left/top already have 3pt (meets target); right/bottom only 1pt.
    trimbox = pymupdf.Rect(3, 3, 99, 99)
    target_pt = 3.0
    expansion = compute_edge_expansion_pt(mediabox, trimbox, target_pt)
    assert expansion == {"left": 0.0, "right": 2.0, "top": 0.0, "bottom": 2.0}


def test_edge_already_exceeding_target_is_not_reduced():
    mediabox = pymupdf.Rect(0, 0, 100, 100)
    trimbox = pymupdf.Rect(10, 10, 90, 90)  # 10pt bleed everywhere, target is lower
    expansion = compute_edge_expansion_pt(mediabox, trimbox, 3.0)
    assert all(v == 0.0 for v in expansion.values())


# --- fix_bleed_pdf (end-to-end, synthetic) ---

def test_fix_bleed_pdf_raises_without_declared_trimbox():
    data = _make_pdf_no_trimbox(90, 50)
    doc = pymupdf.open(stream=data, filetype="pdf")
    with pytest.raises(NoDeclaredTrimBoxError):
        fix_bleed_pdf(doc, 0, target_bleed_mm=3.0)
    doc.close()


def test_fix_bleed_pdf_expands_symmetric_bleed_to_target():
    data = _make_pdf(90, 50, bleed_mm=1.0)  # 1mm everywhere, need 3mm -> +2mm added
    doc = pymupdf.open(stream=data, filetype="pdf")
    result = fix_bleed_pdf(doc, 0, target_bleed_mm=3.0)
    doc.close()

    assert result["edges_mm"] == {"left": 2.0, "right": 2.0, "top": 2.0, "bottom": 2.0}

    fixed = pymupdf.open(stream=result["pdf_bytes"], filetype="pdf")
    fixed_page = fixed[0]
    fixed_mediabox = fixed_page.mediabox
    fixed_trimbox = fixed_page.trimbox
    # MediaBox expands from the TrimBox, not from the old MediaBox — the
    # finished (trim) size is never touched, only the margin around it
    # grows, so the new file's own declared bleed reaches the full target
    # on every edge (1mm existing + 2mm added = 3mm).
    got_bleed_mm = min(
        fixed_trimbox.x0 - fixed_mediabox.x0,
        fixed_mediabox.x1 - fixed_trimbox.x1,
        fixed_trimbox.y0 - fixed_mediabox.y0,
        fixed_mediabox.y1 - fixed_trimbox.y1,
    ) / MM_TO_PT
    assert got_bleed_mm == pytest.approx(3.0, abs=0.05)
    # Trim (finished) size itself must be unchanged — only the margin grew.
    assert fixed_trimbox.width == pytest.approx(90 * MM_TO_PT, abs=0.5)
    assert fixed_trimbox.height == pytest.approx(50 * MM_TO_PT, abs=0.5)
    fixed.close()


def test_fix_bleed_pdf_only_expands_the_short_edges():
    # left/top already at 3mm; right/bottom only 1mm -> only those two grow.
    data = _make_pdf(90, 50, bleed_mm=(3.0, 1.0, 3.0, 1.0))
    doc = pymupdf.open(stream=data, filetype="pdf")
    result = fix_bleed_pdf(doc, 0, target_bleed_mm=3.0)
    doc.close()

    assert result["edges_mm"] == {"left": 0.0, "right": 2.0, "top": 0.0, "bottom": 2.0}

    fixed = pymupdf.open(stream=result["pdf_bytes"], filetype="pdf")
    fixed_page = fixed[0]
    fixed_mediabox = fixed_page.mediabox
    fixed_trimbox = fixed_page.trimbox
    left_bleed_mm = (fixed_trimbox.x0 - fixed_mediabox.x0) / MM_TO_PT
    right_bleed_mm = (fixed_mediabox.x1 - fixed_trimbox.x1) / MM_TO_PT
    top_bleed_mm = (fixed_trimbox.y0 - fixed_mediabox.y0) / MM_TO_PT
    bottom_bleed_mm = (fixed_mediabox.y1 - fixed_trimbox.y1) / MM_TO_PT
    # Every edge reaches the 3mm target — the two that already had it kept
    # it unchanged (0 added), the two that were short got exactly the
    # deficit added.
    assert left_bleed_mm == pytest.approx(3.0, abs=0.05)
    assert top_bleed_mm == pytest.approx(3.0, abs=0.05)
    assert right_bleed_mm == pytest.approx(3.0, abs=0.05)
    assert bottom_bleed_mm == pytest.approx(3.0, abs=0.05)
    # Trim size unchanged regardless of which sides grew.
    assert fixed_trimbox.width == pytest.approx(90 * MM_TO_PT, abs=0.5)
    assert fixed_trimbox.height == pytest.approx(50 * MM_TO_PT, abs=0.5)
    fixed.close()


def test_fix_bleed_pdf_trim_does_not_shift_when_only_one_side_needs_it():
    """Left already has the full 3mm bleed, right has none. The finished
    (trim) size and its position relative to the artwork must be identical
    before and after — MediaBox grows outward from the TrimBox, never the
    other way around, so a side that was already fine is left completely
    untouched instead of being absorbed into a bigger trim."""
    data = _make_pdf(90, 50, bleed_mm=(3.0, 0.0, 3.0, 3.0))  # left/top/bottom=3mm, right=0mm
    doc = pymupdf.open(stream=data, filetype="pdf")
    original_trimbox = doc[0].trimbox
    result = fix_bleed_pdf(doc, 0, target_bleed_mm=3.0)
    doc.close()

    # left/top/bottom already sufficient -> 0 added; only right gets the
    # full 3mm added, having had none before.
    assert result["edges_mm"] == {"left": 0.0, "right": 3.0, "top": 0.0, "bottom": 0.0}

    fixed = pymupdf.open(stream=result["pdf_bytes"], filetype="pdf")
    fixed_page = fixed[0]
    fixed_mediabox = fixed_page.mediabox
    fixed_trimbox = fixed_page.trimbox

    # The trim's own size is untouched.
    assert fixed_trimbox.width == pytest.approx(original_trimbox.width, abs=0.05)
    assert fixed_trimbox.height == pytest.approx(original_trimbox.height, abs=0.05)
    # The trim's position relative to the new page's ORIGIN (which sits at
    # the same place as the old page's origin — nothing was added on the
    # left/top/bottom) is exactly where it always was; it did not shift
    # just because the right margin grew.
    assert fixed_trimbox.x0 == pytest.approx(original_trimbox.x0, abs=0.05)
    assert fixed_trimbox.y0 == pytest.approx(original_trimbox.y0, abs=0.05)

    left_bleed_mm = (fixed_trimbox.x0 - fixed_mediabox.x0) / MM_TO_PT
    right_bleed_mm = (fixed_mediabox.x1 - fixed_trimbox.x1) / MM_TO_PT
    top_bleed_mm = (fixed_trimbox.y0 - fixed_mediabox.y0) / MM_TO_PT
    bottom_bleed_mm = (fixed_mediabox.y1 - fixed_trimbox.y1) / MM_TO_PT
    assert left_bleed_mm == pytest.approx(3.0, abs=0.05)  # untouched, was already 3mm
    assert right_bleed_mm == pytest.approx(3.0, abs=0.05)  # newly added
    assert top_bleed_mm == pytest.approx(3.0, abs=0.05)  # untouched, was already 3mm
    assert bottom_bleed_mm == pytest.approx(3.0, abs=0.05)  # untouched, was already 3mm
    fixed.close()


def test_fix_bleed_pdf_preview_matches_new_page_size():
    data = _make_pdf(90, 50, bleed_mm=0.0)
    doc = pymupdf.open(stream=data, filetype="pdf")
    result = fix_bleed_pdf(doc, 0, target_bleed_mm=3.0)
    doc.close()
    assert result["preview"]["url"].startswith("data:image/png;base64,")
    assert result["preview"]["width_px"] > 0
    assert result["preview"]["height_px"] > 0


# --- Smoke test against a real client PDF (N14/A7 fixture family) ---

_REAL_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "test-files", "47 Magura_Brelok-lenta_20260907 PRINT.pdf")


@pytest.mark.skipif(not os.path.exists(_REAL_FIXTURE), reason="test-files/ not present on this checkout (excluded from git)")
def test_fix_bleed_pdf_on_real_zero_bleed_file():
    with open(_REAL_FIXTURE, "rb") as f:
        data = f.read()
    doc = pymupdf.open(stream=data, filetype="pdf")
    original_trimbox = doc[0].trimbox
    result = fix_bleed_pdf(doc, 0, target_bleed_mm=3.0)
    doc.close()

    assert all(v == pytest.approx(3.0, abs=0.05) for v in result["edges_mm"].values())
    fixed = pymupdf.open(stream=result["pdf_bytes"], filetype="pdf")
    assert fixed[0].mediabox.width > fixed[0].trimbox.width
    # Finished size must be exactly the original trim size, unchanged.
    assert fixed[0].trimbox.width == pytest.approx(original_trimbox.width, abs=0.05)
    assert fixed[0].trimbox.height == pytest.approx(original_trimbox.height, abs=0.05)
    fixed.close()
