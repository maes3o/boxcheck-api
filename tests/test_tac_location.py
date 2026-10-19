"""
TAC (total ink coverage) location — regression tests for the additive
fields render_ink_heatmap() now returns (TAC audit, read-only investigation
first — see the audit's empirical measurements for why 90% / 50px was
chosen for the local cluster search).

`url` and `max_coverage_pct` are UNCHANGED — same formula, same value —
everything else (`page`, `max_coverage_pixel`, `max_coverage_rect_pt`,
`max_coverage_cluster_rect_pt`, `max_coverage_cluster_pixels`,
`max_coverage_cluster_area_pct`) is new and additive.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf
import pytest

from render_preview import DEFAULT_MAX_DIMENSION_PX, _page_scale, render_ink_heatmap

REAL_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "test-files",
    "57384_07.05.2025_КМВ_Кукурудзяні_кільця_зі_смаком_кальмару_75г_98.94%.pdf",
)
require_real = pytest.mark.skipif(not os.path.exists(REAL_PDF_PATH), reason="real QA PDF not present")


def _content_pdf_bytes(width: float, height: float, content: bytes) -> bytes:
    """A page with a raw CMYK (`k`) content stream — pymupdf's high-level
    draw_rect only takes RGB fill, and CMYK sum is exactly what
    render_ink_heatmap measures, so the fixture needs the real operator."""
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, content)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")
    data = doc.tobytes()
    doc.close()
    return data


# --- A. Real QA PDF ---------------------------------------------------------


@require_real
def test_real_pdf_tac_location_matches_known_hotspot():
    doc = pymupdf.open(REAL_PDF_PATH)
    page = doc[0]
    result = render_ink_heatmap(page)
    assert result is not None

    # Unchanged fields — same formula, same value as before this change.
    assert result["max_coverage_pct"] == 396.9
    assert result["url"].startswith("data:image/png;base64,")

    # New fields.
    assert result["page"] == 1
    assert result["max_coverage_pixel"] == {"x": 3, "y": 302}

    scale = _page_scale(page, DEFAULT_MAX_DIMENSION_PX)
    rect = result["max_coverage_rect_pt"]
    # The rect must exactly enclose pixel (3,302) in PDF points (same
    # top-left-origin, Y-down convention as hairline_locations' rect —
    # verified empirically in the TAC audit against page.mediabox /
    # get_drawings()).
    assert rect[0] == pytest.approx(3 / scale, abs=1e-2)
    assert rect[1] == pytest.approx(302 / scale, abs=1e-2)
    assert rect[2] == pytest.approx(4 / scale, abs=1e-2)
    assert rect[3] == pytest.approx(303 / scale, abs=1e-2)

    # Cluster must contain the argmax pixel's rect and stay tiny (measured:
    # 3 pixels on this file, comfortably inside the 50px radius cap).
    cluster_rect = result["max_coverage_cluster_rect_pt"]
    assert cluster_rect[0] <= rect[0] and cluster_rect[1] <= rect[1]
    assert cluster_rect[2] >= rect[2] and cluster_rect[3] >= rect[3]
    assert result["max_coverage_cluster_pixels"] == 3
    assert result["max_coverage_cluster_area_pct"] < 0.01


@require_real
def test_real_pdf_page_check_still_returns_same_ink_heatmap_shape():
    """_render_page_sync (/check/page) computes ink_heatmap independently
    of _check_pdf_sync (/check) — both call render_ink_heatmap directly, so
    a fix in one function covers both call sites without touching either
    (main.py:998, main.py:1157)."""
    import main
    pdf_bytes = open(REAL_PDF_PATH, "rb").read()
    result = main._render_page_sync(pdf_bytes, 0, "unknown", None, None, None)
    heatmap = result.get("ink_heatmap")
    assert heatmap is not None
    assert heatmap["max_coverage_pct"] == 396.9
    assert heatmap["page"] == 1
    assert "max_coverage_cluster_rect_pt" in heatmap


# --- B. Synthetic PDF: two distant hot spots, cluster must not merge them --


def test_cluster_does_not_merge_distant_hot_spots():
    # Wide page: spot A is a 40x40pt pure-K block near the left edge
    # (coverage 0.25 -> 100%, big — like ordinary rich artwork). Spot B is
    # a TINY 3x3pt rich-black mark near the right edge (coverage 1.0 ->
    # 400%, like the real QA PDF's registration-mark hot spot) — ~850pt
    # from spot A, i.e. ~1190 raster px apart at the default scale, far
    # beyond the 50px radius cap. Global max must land in the small spot
    # B, and the cluster must stay local to it, not reach toward the big
    # (but lower-coverage) spot A.
    content = (
        b"0 0 0 1 k 10 10 40 40 re f "       # spot A: K only -> coverage 0.25 -> 100%
        b"1 1 1 1 k 900 100 3 3 re f"         # spot B: full CMYK, tiny -> coverage 1.0 -> 400%
    )
    data = _content_pdf_bytes(1000, 200, content)
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc[0]
    result = render_ink_heatmap(page)
    assert result is not None
    assert result["max_coverage_pct"] == pytest.approx(400.0, abs=0.5)

    scale = _page_scale(page, DEFAULT_MAX_DIMENSION_PX)
    # argmax must be inside spot B's area (x in [900,903] pt), not spot A's.
    x_pt = result["max_coverage_pixel"]["x"] / scale
    assert 895 <= x_pt <= 910, f"argmax should be inside spot B, got x_pt={x_pt}"

    cluster_rect = result["max_coverage_cluster_rect_pt"]
    # The cluster bbox must stay local to spot B — must NOT reach anywhere
    # near spot A (x < 100pt). This is the exact failure mode a naive
    # page-wide threshold mask would produce (see the audit's measurement).
    assert cluster_rect[0] > 500, (
        f"cluster must not extend toward the distant spot A, got rect={cluster_rect}"
    )
    assert result["max_coverage_cluster_pixels"] < 50, (
        "cluster should be a small local region matching spot B's own tiny size, "
        f"not spot A's — got {result['max_coverage_cluster_pixels']} pixels"
    )


# --- C. Backward compatibility ----------------------------------------------


@require_real
def test_url_and_max_coverage_pct_unchanged_shape():
    """The two pre-existing fields keep their exact pre-fix type/shape —
    same string prefix, same float, nothing repurposed."""
    doc = pymupdf.open(REAL_PDF_PATH)
    result = render_ink_heatmap(doc[0])
    assert isinstance(result["url"], str) and result["url"].startswith("data:image/png;base64,")
    assert isinstance(result["max_coverage_pct"], float)
    assert result["max_coverage_pct"] == 396.9


def test_blank_page_still_returns_none():
    """The existing max_coverage < 0.02 -> None short-circuit must still
    apply before any of the new fields are computed."""
    doc = pymupdf.open()
    doc.new_page(width=200, height=200)
    result = render_ink_heatmap(doc[0])
    assert result is None
