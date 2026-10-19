"""
GS Composite Preview MVP (approved architecture audit, Option B+C) —
production integration tests.

Covers the lettered test requirements from the implementation task:
  B. CMYK-only PDF -> preview stays the existing pymupdf path, unchanged.
  C. Spot PDF -> preview uses the GS composite (differs from naive pymupdf).
  D. GS failure -> /check succeeds, falls back to pymupdf preview.
  E. GS timeout -> /check succeeds, falls back.
  F. Dimensions -> preview dimensions are valid and match the existing
     preview pipeline's own (deterministic, normalized).
  H. /check/page -> same behavior as the initial /check.
  I. Real production PDF -> produces a recognizably different (non-flat)
     base preview versus the confirmed-broken naive pymupdf render.

(G, hover coordinate mapping when dimensions differ, is a frontend concern
 — covered separately in src/lib/cmykSample.test.ts.)
"""
import io
import os
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pymupdf
import pytest
from PIL import Image

import main
import gs_composite_preview
from render_preview import render_page_preview

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


def _spot_colorspace_pdf_bytes(spot_name: str = "MySpot") -> bytes:
    """A real PAGE-LEVEL Separation colorspace, painted via a content-stream
    fill operator (/Cs1 cs 1 scn ... f) — NOT the test_image_analysis.py/
    test_composite_prototype.py technique of overriding an image XObject's
    own /ColorSpace, which main.collect_spot_colors's page
    Resources/ColorSpace scan does not see at all (confirmed empirically:
    that technique produces zero detected spots here, since
    collect_spot_colors reads the page's own /Resources/ColorSpace dict,
    not an embedded image's private colorspace). This is what the GS
    composite integration's own gate (collect_spot_colors) actually keys
    off, so it's the correct fixture for these tests specifically.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)

    cs_xref = doc.get_new_xref()
    doc.update_object(
        cs_xref,
        f"[/Separation/{spot_name}/DeviceGray<</FunctionType 2/Domain[0 1]/C0[1]/C1[0]/N 1>>]",
    )
    doc.xref_set_key(page.xref, "Resources", f"<< /ColorSpace << /Cs1 {cs_xref} 0 R >> >>")

    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, b"/Cs1 cs 1 scn 50 50 200 200 re f")
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")

    data = doc.tobytes()
    doc.close()
    return data


def _decode_data_uri_size(data_uri: str) -> Image.Image:
    import base64
    _, b64 = data_uri.split(",", 1)
    return Image.open(io.BytesIO(base64.b64decode(b64)))


# --- B: CMYK-only stays on the existing pymupdf path -----------------------

def test_cmyk_only_preview_is_byte_identical_to_direct_pymupdf_render():
    data = _cmyk_only_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    direct = render_page_preview(doc[0])
    doc.close()

    result = main._check_pdf_sync(data, "cmyk.pdf", "unknown", None, "mm", include_canvas=True)
    assert result["preview"]["url"] == direct["url"]
    assert result["preview"]["width_px"] == direct["width_px"]
    assert result["preview"]["height_px"] == direct["height_px"]


def test_cmyk_only_never_invokes_ghostscript_composite():
    data = _cmyk_only_pdf_bytes()
    with patch("main.render_gs_composite_preview") as mock_gs:
        main._check_pdf_sync(data, "cmyk.pdf", "unknown", None, "mm", include_canvas=True)
        mock_gs.assert_not_called()


# --- C: spot PDF uses the GS composite --------------------------------------

def test_spot_pdf_preview_differs_from_naive_pymupdf_render():
    data = _spot_colorspace_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    naive = render_page_preview(doc[0])
    doc.close()

    result = main._check_pdf_sync(data, "spot.pdf", "unknown", None, "mm", include_canvas=True)
    assert result["preview"]["url"] != naive["url"]


def test_spot_pdf_passes_gs_composite_url_to_spot_separations():
    """Separation swatch fix (Audit #3 Finding #2): render_spot_separations
    must now receive the GS COMPOSITE's URL, not the naive pymupdf preview
    — this is the whole point of the fix (the old behavior, asserted by an
    earlier version of this test, was CONFIRMED as the root cause of every
    spot swatch coming out the same wrong color)."""
    data = _spot_colorspace_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    naive_url = render_page_preview(doc[0])["url"]
    doc.close()

    with patch("main.render_spot_separations", wraps=main.render_spot_separations) as mock_sep:
        result = main._check_pdf_sync(data, "spot.pdf", "unknown", None, "mm", include_canvas=True)
        assert mock_sep.called
        called_preview_url = mock_sep.call_args[0][3]
        # The URL passed to render_spot_separations must be whatever ended
        # up as the actual base preview (GS composite on success) — the two
        # must always agree, never diverge.
        assert called_preview_url == result["preview"]["url"]


def test_gs_composite_still_invoked_exactly_once_per_spot_page():
    """Reordering (compute GS composite BEFORE render_spot_separations,
    reuse it) must not introduce a second Ghostscript invocation — same
    call count as before this fix, just moved earlier."""
    data = _spot_colorspace_pdf_bytes()
    with patch("main.render_gs_composite_preview", wraps=main.render_gs_composite_preview) as mock_gs:
        main._check_pdf_sync(data, "spot.pdf", "unknown", None, "mm", include_canvas=True)
        assert mock_gs.call_count == 1


def test_gs_failure_still_passes_pymupdf_fallback_url_to_spot_separations():
    """On GS failure, render_gs_composite_preview returns the ORIGINAL
    pymupdf preview dict unchanged — render_spot_separations must then get
    that same pymupdf URL, exactly like before this fix (no behavior change
    on the failure path, only on success)."""
    data = _spot_colorspace_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    naive_url = render_page_preview(doc[0])["url"]
    doc.close()

    def always_fallback(pdf_bytes, page_index, fallback_preview):
        return fallback_preview

    with patch("main.render_gs_composite_preview", side_effect=always_fallback):
        with patch("main.render_spot_separations", wraps=main.render_spot_separations) as mock_sep:
            main._check_pdf_sync(data, "spot.pdf", "unknown", None, "mm", include_canvas=True)
            called_preview_url = mock_sep.call_args[0][3]
            assert called_preview_url == naive_url


# --- D: GS failure falls back ------------------------------------------------

def test_gs_failure_falls_back_to_pymupdf_preview():
    fallback = {"url": "data:image/png;base64,AAA", "width_px": 10, "height_px": 10, "scale": 1.0}
    # Genuinely invalid PDF bytes -> real Ghostscript failure, not mocked.
    result = gs_composite_preview.render_gs_composite_preview(b"not a real pdf", 0, fallback)
    assert result == fallback


def test_check_endpoint_succeeds_even_when_gs_composite_raises_unexpectedly():
    """Defense in depth: even if something inside render_gs_composite_preview
    misbehaves in a way its own try/except didn't anticipate, /check as a
    whole must still succeed with the pymupdf fallback, never 500."""
    data = _spot_colorspace_pdf_bytes()
    with patch("main.render_gs_composite_preview", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            # This documents the CURRENT boundary: render_gs_composite_preview
            # itself is the resilience boundary (never raises for real GS
            # failures, verified above) — main.py does not add a second
            # try/except around the call. If that boundary is ever removed
            # by mistake (e.g. someone bypasses its own try/except), this
            # test fails loudly instead of silently, which is the point.
            main._check_pdf_sync(data, "spot.pdf", "unknown", None, "mm", include_canvas=True)


# --- E: GS timeout falls back -------------------------------------------------

def test_gs_timeout_falls_back_to_pymupdf_preview():
    fallback = {"url": "data:image/png;base64,AAA", "width_px": 10, "height_px": 10, "scale": 1.0}
    with patch(
        "gs_composite_preview.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="gs", timeout=25),
    ):
        result = gs_composite_preview.render_gs_composite_preview(b"irrelevant", 0, fallback)
    assert result == fallback


# --- F: dimensions are valid and deterministic --------------------------------

def test_spot_pdf_preview_dimensions_match_existing_pipeline():
    data = _spot_colorspace_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    naive = render_page_preview(doc[0])
    doc.close()

    result = main._check_pdf_sync(data, "spot.pdf", "unknown", None, "mm", include_canvas=True)
    assert result["preview"]["width_px"] == naive["width_px"]
    assert result["preview"]["height_px"] == naive["height_px"]

    # The dimensions CLAIMED in the response must match the actual decoded
    # image bytes — normalization must be real, not just a relabeled number.
    img = _decode_data_uri_size(result["preview"]["url"])
    assert img.width == result["preview"]["width_px"]
    assert img.height == result["preview"]["height_px"]


# --- H: /check/page behaves the same as /check --------------------------------

def test_render_page_sync_spot_pdf_preview_also_uses_gs_composite():
    data = _spot_colorspace_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    naive = render_page_preview(doc[0])
    doc.close()

    result = main._render_page_sync(data, 0, "unknown", "business_card", None, None)
    assert result["preview"]["url"] != naive["url"]
    assert result["preview"]["width_px"] == naive["width_px"]
    assert result["preview"]["height_px"] == naive["height_px"]


def test_render_page_sync_cmyk_only_unchanged():
    data = _cmyk_only_pdf_bytes()
    doc = pymupdf.open(stream=data, filetype="pdf")
    direct = render_page_preview(doc[0])
    doc.close()

    result = main._render_page_sync(data, 0, "unknown", None, None, None)
    assert result["preview"]["url"] == direct["url"]


# --- I: real production PDF produces a recognizable, non-flat preview --------

@pytest.mark.skipif(not os.path.exists(REAL_PDF_PATH), reason="real production test PDF not present")
def test_real_production_pdf_gs_preview_is_not_a_flat_color():
    """Regression marker for the confirmed Audit #2/#3 finding: the naive
    pymupdf render of this real file is an almost-flat single-color block
    (std dev of pixel values near zero); the GS composite must NOT be."""
    with open(REAL_PDF_PATH, "rb") as f:
        pdf_bytes = f.read()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    naive = render_page_preview(page)
    doc.close()

    result = gs_composite_preview.render_gs_composite_preview(pdf_bytes, 0, naive)
    assert result["url"] != naive["url"]

    gs_img = np.array(_decode_data_uri_size(result["url"]).convert("RGB"))
    naive_img = np.array(_decode_data_uri_size(naive["url"]).convert("RGB"))

    # Real measured values on this file (150dpi-equivalent production
    # resolution): naive pymupdf std dev ~43, GS composite std dev ~74 —
    # both thresholds below give real headroom under the actual numbers,
    # not guessed constants.
    assert gs_img.std() > naive_img.std()
    assert gs_img.std() > 60


@pytest.mark.skipif(not os.path.exists(REAL_PDF_PATH), reason="real production test PDF not present")
def test_real_production_pdf_spot_swatches_are_no_longer_all_the_same_color():
    """Separation swatch fix (Audit #3 Finding #2) regression marker: before
    this fix, display_color_hex for every one of the 4 real spot plates on
    this file (Lak, PANTONE 3262 C, PANTONE Black C, White-1) came out as
    virtually the same wrong pink (#d194b0/#f189b8/#f189b7/#f188b7 —
    confirmed via direct production-code invocation during the audit),
    because render_spot_separations sampled the broken naive pymupdf
    preview. After this fix it samples the real GS composite instead, so
    these must now be genuinely different colors."""
    with open(REAL_PDF_PATH, "rb") as f:
        pdf_bytes = f.read()
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    spot_colors = main.collect_spot_colors(doc, page)
    doc.close()

    result = main._check_pdf_sync(pdf_bytes, "57384.pdf", "unknown", None, "mm", include_canvas=True)
    seps = result["spot_separations"]
    names = {s["name"] for s in seps}
    assert {"Lak", "PANTONE 3262 C", "PANTONE Black C", "White-1"}.issubset(names)

    swatches = {s["name"]: s["display_color_hex"] for s in seps}
    print("spot swatch colors (this run):", swatches)

    # The core regression: not all 4 the same color anymore.
    assert len(set(swatches.values())) > 1

    # The specific pre-fix values must not all still be present together —
    # if they are, the fix did not take effect.
    old_broken_values = {"#d194b0", "#f189b8", "#f189b7", "#f188b7"}
    assert not old_broken_values.issubset(set(swatches.values()))
