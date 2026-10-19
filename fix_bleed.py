"""
BoxCheck — N16: opt-in bleed auto-fix ("Спробувати виправити автоматично").

Given a page whose declared TrimBox has insufficient bleed on one or more
edges (vs. the same profile/threshold the bleed check itself uses), builds
a new PDF page whose MediaBox is expanded — outward from the *existing*
TrimBox, not from the old MediaBox — just enough on each short edge to
reach the target bleed. The finished/trim size and its position relative
to the artwork never change: the new TrimBox is the old TrimBox, carried
over unmoved (only translated by whatever the content itself was shifted
by, so it stays fixed relative to the artwork once that's placed on the
bigger new page) — a side that already had enough bleed keeps exactly what
it had, it is never absorbed into a bigger "trim". The original content is
placed unscaled and unmoved via show_pdf_page() (an XObject reference to
the source page — no rasterization, so existing text/vector inside the
original area stays crisp). Only the new margin is filled: a ~5mm raster
strip of the original page's own edge, mirrored outward and stretched (not
tiled — see below) to cover whatever margin width is needed; corners are
mirrored on both axes.

One call produces both the preview PNG and the final PDF bytes in the same
pass (deterministic geometry — no reason to compute it twice), matching
main.py's single POST /fix/bleed endpoint.

Not in MVP (called out in the spec as separate follow-up tasks): tiling a
repeated pattern into a large margin (a mirrored strip is stretched
instead) and booklet imposition.
"""
from __future__ import annotations
import io

import numpy as np
import pymupdf
from PIL import Image

from render_preview import render_page_preview

STRIP_MM = 5.0
STRIP_DPI = 300
MM_TO_PT = 2.8346


class NoDeclaredTrimBoxError(Exception):
    """The page has no declared TrimBox, so there's nothing honest to
    measure the existing bleed against — refuse rather than guess (same
    "page1_has_declared_trimbox" rule main.py's Document Geometry card
    already follows)."""


def compute_edge_expansion_pt(
    mediabox: "pymupdf.Rect", trimbox: "pymupdf.Rect", target_bleed_pt: float,
) -> dict[str, float]:
    """Per-edge expansion (pt, >=0) needed so that edge alone reaches
    target_bleed_pt. Mirrors the 4-term min() main.py's own bleed check
    uses (x0=left, x1=right, y0=top, y1=bottom), but per-edge instead of
    a single worst-case min — an edge that already meets the target gets
    0 and is left untouched, never trimmed back."""
    return {
        "left": max(0.0, target_bleed_pt - (trimbox.x0 - mediabox.x0)),
        "right": max(0.0, target_bleed_pt - (mediabox.x1 - trimbox.x1)),
        "top": max(0.0, target_bleed_pt - (trimbox.y0 - mediabox.y0)),
        "bottom": max(0.0, target_bleed_pt - (mediabox.y1 - trimbox.y1)),
    }


def _mirrored_png(strip: np.ndarray, flip_axis0: bool, flip_axis1: bool) -> bytes:
    """Flip `strip` (a raster sample taken from the original page's own
    edge) so the row/column nearest the original content lands at the
    mirror boundary. No resize here — the caller places this image into a
    PDF rect via insert_image(..., keep_proportion=False), which stretches
    it to the exact margin size, giving the "stretch, don't tile" behavior
    the spec asks for."""
    if flip_axis0:
        strip = strip[::-1, :, :]
    if flip_axis1:
        strip = strip[:, ::-1, :]
    buf = io.BytesIO()
    Image.fromarray(strip, mode="RGB").save(buf, format="PNG")
    return buf.getvalue()


def fix_bleed_pdf(doc: "pymupdf.Document", page_index: int, target_bleed_mm: float) -> dict:
    """Build a new 1-page PDF with page `page_index`'s bleed extended to
    target_bleed_mm on every edge that falls short. Returns
    {pdf_bytes, preview, edges_mm} where `preview` is a render_preview.py
    -shaped {url, width_px, height_px, scale} dict and `edges_mm` is the
    per-edge expansion actually applied (0 for edges that already met the
    target). Raises NoDeclaredTrimBoxError if the page has no declared
    TrimBox."""
    page = doc[page_index]
    if doc.xref_get_key(page.xref, "TrimBox")[0] == "null":
        raise NoDeclaredTrimBoxError("Page has no declared TrimBox")

    mediabox = page.mediabox
    trimbox = page.trimbox
    target_bleed_pt = target_bleed_mm * MM_TO_PT
    expansion_pt = compute_edge_expansion_pt(mediabox, trimbox, target_bleed_pt)

    px_per_pt = STRIP_DPI / 72.0
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(px_per_pt, px_per_pt), colorspace=pymupdf.csRGB, alpha=False)
    arr = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    orig_h_px, orig_w_px = arr.shape[:2]

    strip_px = max(1, round(STRIP_MM / 25.4 * STRIP_DPI))
    strip_px = min(strip_px, orig_h_px, orig_w_px)

    new_w_pt = mediabox.width + expansion_pt["left"] + expansion_pt["right"]
    new_h_pt = mediabox.height + expansion_pt["top"] + expansion_pt["bottom"]

    new_doc = pymupdf.open()
    new_page = new_doc.new_page(width=new_w_pt, height=new_h_pt)
    # Re-read: pymupdf stores page boxes as float32, so the mediabox that
    # comes back can differ in the last decimal from the double we asked
    # for — any rect built from the original new_w_pt/new_h_pt can then
    # fall a hair outside it and fail the "not in MediaBox" check below
    # (same float32-rounding gotcha test_bleed_thresholds.py's own fixture
    # comment calls out).
    new_mediabox = new_page.mediabox
    new_w_pt, new_h_pt = new_mediabox.x1, new_mediabox.y1

    def place(rect: "pymupdf.Rect", flip0: bool, flip1: bool, sample: np.ndarray) -> None:
        if rect.width <= 0 or rect.height <= 0:
            return
        new_page.insert_image(rect, stream=_mirrored_png(sample, flip0, flip1), keep_proportion=False)

    left, right = expansion_pt["left"], expansion_pt["right"]
    top, bottom = expansion_pt["top"], expansion_pt["bottom"]

    # Edges — span only the original content's extent along the parallel axis.
    if top > 0:
        place(pymupdf.Rect(left, 0, left + mediabox.width, top), True, False, arr[0:strip_px, :, :])
    if bottom > 0:
        place(pymupdf.Rect(left, top + mediabox.height, left + mediabox.width, new_h_pt), True, False,
              arr[orig_h_px - strip_px:orig_h_px, :, :])
    if left > 0:
        place(pymupdf.Rect(0, top, left, top + mediabox.height), False, True, arr[:, 0:strip_px, :])
    if right > 0:
        place(pymupdf.Rect(left + mediabox.width, top, new_w_pt, top + mediabox.height), False, True,
              arr[:, orig_w_px - strip_px:orig_w_px, :])

    # Corners — mirrored on both axes.
    if top > 0 and left > 0:
        place(pymupdf.Rect(0, 0, left, top), True, True, arr[0:strip_px, 0:strip_px, :])
    if top > 0 and right > 0:
        place(pymupdf.Rect(left + mediabox.width, 0, new_w_pt, top), True, True,
              arr[0:strip_px, orig_w_px - strip_px:orig_w_px, :])
    if bottom > 0 and left > 0:
        place(pymupdf.Rect(0, top + mediabox.height, left, new_h_pt), True, True,
              arr[orig_h_px - strip_px:orig_h_px, 0:strip_px, :])
    if bottom > 0 and right > 0:
        place(pymupdf.Rect(left + mediabox.width, top + mediabox.height, new_w_pt, new_h_pt), True, True,
              arr[orig_h_px - strip_px:orig_h_px, orig_w_px - strip_px:orig_w_px, :])

    # Original content, unscaled and unmoved, on top of the mirrored margin.
    # `& new_mediabox`: guards against the same float32 rounding as above
    # pushing this a hair outside the page (set_trimbox below requires
    # strict containment).
    content_rect = pymupdf.Rect(left, top, left + mediabox.width, top + mediabox.height) & new_mediabox
    new_page.show_pdf_page(content_rect, doc, page_index)

    # TrimBox = the OLD TrimBox, translated by the exact same (left, top)
    # offset the content itself was placed at — so it stays fixed relative
    # to the artwork (finished size and position never change), instead of
    # snapping to wherever the old MediaBox now sits. A side with 0
    # expansion keeps its old margin exactly: e.g. left=0 here means the
    # trim's left edge lands at the same distance from the new page's left
    # edge as it always was from the old one.
    new_trimbox = pymupdf.Rect(
        trimbox.x0 + left, trimbox.y0 + top, trimbox.x1 + left, trimbox.y1 + top,
    ) & new_mediabox
    new_page.set_trimbox(new_trimbox)
    new_page.set_bleedbox(new_mediabox)

    pdf_bytes = new_doc.tobytes()
    preview = render_page_preview(new_page)
    new_doc.close()

    return {
        "pdf_bytes": pdf_bytes,
        "preview": preview,
        "edges_mm": {k: round(v / MM_TO_PT, 2) for k, v in expansion_pt.items()},
    }
