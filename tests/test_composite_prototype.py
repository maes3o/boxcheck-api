"""
STEP 1 prototype tests — composite_prototype.py, the isolated Ghostscript
composite renderer built to evaluate whether GS's real overprint/knockout
modeling is a viable replacement for InteractiveCanvas.tsx's current
client-side subtractive spot overlay (Audit #2).

This module is NOT wired into main.py/checks.py or any HTTP endpoint —
these tests only exercise composite_prototype.py itself, and don't touch
(or need) anything in the existing production request path.
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pymupdf
import pytest
from PIL import Image

import composite_prototype as cp
import main  # only for collect_spot_colors, used as an independent cross-check

REAL_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "test-files",
    "57384_07.05.2025_КМВ_Кукурудзяні_кільця_зі_смаком_кальмару_75г_98.94%.pdf",
)


def _cmyk_only_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 20), "test", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _spot_colorspace_pdf_bytes(spot_name: str = "Spot1") -> bytes:
    """Same technique tests/test_image_analysis.py already uses (see its
    test_separation_colorspace_not_flagged_rgb): insert a normal image,
    then override its /ColorSpace to a real Separation array — a genuine
    Separation colorspace Ghostscript's tiffsep will detect and give its
    own plate, without needing to hand-author a raw content stream."""
    img = Image.new("RGB", (100, 100), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=buf.getvalue())
    img_xref = page.get_images(full=True)[0][0]
    doc.xref_set_key(
        img_xref, "ColorSpace",
        f"[/Separation/{spot_name}/DeviceGray<</FunctionType 2/Domain[0 1]/C0[1]/C1[0]/N 1>>]",
    )
    data = doc.tobytes()
    doc.close()
    return data


def test_renders_composite_with_correct_dimensions_for_cmyk_only_pdf():
    data = _cmyk_only_pdf_bytes()
    result = cp.render_ghostscript_composite(data, dpi=72.0)
    # 200pt page at 72dpi -> 200px, +/- 1px rounding (same tolerance
    # spot_separations.py's own comment already documents for GS vs
    # pymupdf independent rounding).
    assert abs(result["width_px"] - 200) <= 1
    assert abs(result["height_px"] - 200) <= 1
    assert len(result["composite_tiff"]) > 0


def test_cmyk_only_pdf_produces_no_named_spot_plates():
    # tiffsep always emits the 4 process plates too (Cyan/Magenta/Yellow/
    # Black, whichever are actually used) alongside any real spot — a
    # plain CMYK-only PDF should show none of those PLUS no spot name.
    data = _cmyk_only_pdf_bytes()
    result = cp.render_ghostscript_composite(data, dpi=72.0)
    process_names = {"cyan", "magenta", "yellow", "black"}
    spot_names = {n for n in result["separations"] if n.lower() not in process_names}
    assert spot_names == set()


def test_real_separation_colorspace_produces_its_own_named_plate():
    data = _spot_colorspace_pdf_bytes("MySpot")
    result = cp.render_ghostscript_composite(data, dpi=72.0)
    assert "MySpot" in result["separations"]
    assert len(result["separations"]["MySpot"]) > 0


def test_invalid_pdf_bytes_raises_composite_render_error():
    with pytest.raises(cp.CompositeRenderError):
        cp.render_ghostscript_composite(b"not a real pdf", dpi=72.0)


def test_compare_under_mask_reports_larger_diff_inside_a_fully_inked_mask():
    # Pure-function test, no Ghostscript involved: construct a composite
    # pair that's identical everywhere EXCEPT a masked region, confirm
    # compare_under_mask actually isolates the difference to that region.
    h, w = 10, 10
    gs = np.zeros((h, w, 4), dtype=np.uint8)
    naive = np.zeros((h, w, 4), dtype=np.uint8)
    naive[5:, :, :] = 200  # bottom half differs

    mask = np.full((h, w), 255, dtype=np.uint8)  # tiffsep polarity: 255=no ink
    mask[5:, :] = 0  # bottom half = fully inked

    buf = io.BytesIO()
    Image.fromarray(mask, mode="L").save(buf, format="TIFF")

    result = cp.compare_under_mask(gs, naive, buf.getvalue())
    assert result["mean_abs_diff_inside_mask"] == pytest.approx(800.0)  # 4 channels * 200
    assert result["mean_abs_diff_outside_mask"] == pytest.approx(0.0)


@pytest.mark.skipif(not os.path.exists(REAL_PDF_PATH), reason="real production test PDF not present")
def test_real_production_pdf_separations_match_collect_spot_colors():
    """Cross-checks this prototype's Ghostscript-detected plates against
    the EXISTING, already-shipped main.collect_spot_colors (PDF-object-
    level detection, unrelated code path) — they should agree on which
    named spot colorants exist in this real file."""
    doc = pymupdf.open(REAL_PDF_PATH)
    page = doc[0]
    expected_spots = {s["name"] for s in main.collect_spot_colors(doc, page)}
    doc.close()

    pdf_bytes = cp.get_page_pdf_bytes(REAL_PDF_PATH, 0)
    result = cp.render_ghostscript_composite(pdf_bytes, dpi=100.0)

    # collect_spot_colors also reports Cyan/Magenta/Yellow/Black as named
    # Separations in this real file (see Audit #3's findings) — tiffsep's
    # own plate set is a superset check here (>=), not exact equality,
    # since tiffsep always emits process plates as C/M/Y/K regardless of
    # whether they're ALSO separately named Separations in the PDF.
    assert expected_spots.issubset(set(result["separations"].keys()) | {"Cyan", "Magenta", "Yellow", "Black"})
    assert "White-1" in result["separations"]


@pytest.mark.skipif(not os.path.exists(REAL_PDF_PATH), reason="real production test PDF not present")
def test_real_production_pdf_white1_overprint_measurably_changes_composite():
    """Regression marker for STEP 1's central empirical finding: Ghostscript's
    real composite differs from pymupdf's naive (no-overprint-model) composite
    MUCH more inside White-1's own ink mask than outside it — evidence that
    GS's overprint modeling is doing something real specifically where
    White-1 paints. See diagnostics/composite_prototype/report.json for the
    full numbers this was derived from."""
    doc = pymupdf.open(REAL_PDF_PATH)
    page = doc[0]
    DPI = 100.0

    pdf_bytes = cp.get_page_pdf_bytes(REAL_PDF_PATH, 0)
    gs_result = cp.render_ghostscript_composite(pdf_bytes, dpi=DPI)
    naive = cp.render_naive_pymupdf_cmyk(page, dpi=DPI)
    doc.close()

    gs_arr = cp.tiff_bytes_to_array(gs_result["composite_tiff"])
    comparison = cp.compare_under_mask(gs_arr, naive, gs_result["separations"]["White-1"])

    assert comparison["mean_abs_diff_inside_mask"] is not None
    assert comparison["mean_abs_diff_outside_mask"] is not None
    # The real finding was ~337 vs ~2 (at 150dpi) — assert the qualitative
    # shape (order-of-magnitude gap), not the exact number, so this isn't
    # brittle against a different DPI/GS patch version.
    assert comparison["mean_abs_diff_inside_mask"] > comparison["mean_abs_diff_outside_mask"] * 10
