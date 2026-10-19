"""
BoxCheck — page preview + ink-density heatmap + raw CMYK data bitmap
rendering for the interactive canvas, WITHOUT persisting anything to disk
(matches the existing "files are not stored on the server" principle — see
project notes: uploads are read straight into memory). All three return a
base64 data: URI, meant to be embedded directly in the single /check JSON
response rather than served from a separate endpoint (there's no uploaded-
file state to serve from later).

Requires: pymupdf (already a dependency), Pillow + numpy (new — pip install
pillow numpy).

IMPORTANT: call all three with the SAME max_dimension_px (the default,
1400, everywhere) so their pixel grids and `scale` values line up exactly —
the frontend overlays them on top of each other and reads pixels from the
CMYK data bitmap using the same coordinate math it uses for the preview.
"""

from __future__ import annotations
import base64
import io
from collections import deque
from typing import Optional

import numpy as np
import pymupdf
from PIL import Image

DEFAULT_MAX_DIMENSION_PX = 1400


def _page_scale(page: "pymupdf.Page", max_dimension_px: int) -> float:
    longest_pt = max(page.rect.width, page.rect.height)
    return max_dimension_px / longest_pt if longest_pt > 0 else 1.0


def render_page_preview(page: "pymupdf.Page", max_dimension_px: int = DEFAULT_MAX_DIMENSION_PX) -> dict:
    """Rasterize the page for the canvas base layer. Returns a dict matching
    frontend PreviewImage: {url, width_px, height_px, scale} where `scale`
    is px-per-PDF-point, so the frontend can place trim/bleed/safe-zone
    rects (which it has in PDF points) directly on top of this image with
    no unit conversion of its own.
    """
    scale = _page_scale(page, max_dimension_px)
    matrix = pymupdf.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)

    img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "url": data_uri,
        "width_px": pixmap.width,
        "height_px": pixmap.height,
        "scale": round(scale, 6),
    }


def _cmyk_pixmap_array(page: "pymupdf.Page", max_dimension_px: int) -> tuple["np.ndarray", float]:
    """Shared by render_ink_heatmap and render_cmyk_data_bitmap so the CMYK
    pixmap is only rendered once. Returns (arr uint8 (h, w, 4), scale)."""
    scale = _page_scale(page, max_dimension_px)
    matrix = pymupdf.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csCMYK, alpha=False)
    arr = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 4)
    return arr, scale


# Simple blue -> yellow -> red gradient, keyed by ink coverage 0.0-1.0.
# Approximates a standard "cold to hot" heatmap without pulling in a plotting
# dependency (matplotlib) just for a 3-stop gradient.
_GRADIENT_STOPS = [
    (0.0, (30, 64, 175)),   # low coverage — blue
    (0.5, (245, 158, 11)),  # mid — amber (matches the warning token)
    (1.0, (217, 70, 239)),  # high coverage — magenta (matches --overlay-ink-high)
]


def _gradient_color(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(_GRADIENT_STOPS, _GRADIENT_STOPS[1:]):
        if t0 <= t <= t1:
            local = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(int(c0[i] + (c1[i] - c0[i]) * local) for i in range(3))
    return _GRADIENT_STOPS[-1][1]


_GRADIENT_LUT = np.array([_gradient_color(i / 255) for i in range(256)], dtype=np.uint8)

# Local-cluster search parameters for max_coverage_cluster_rect_pt (TAC
# audit, read-only pass): measured empirically against the real QA PDF
# (57384_..._98.94%.pdf) before picking these. A NAIVE global threshold
# mask ("every pixel >= 90% of the page max") already spans x[3,1396] out
# of a 1400px-wide raster at this exact threshold — i.e. it silently
# unions the true hot spot with an unrelated, distant one elsewhere on the
# sheet (this file repeats a similar registration mark at several
# positions). A LOCAL, adjacency-only flood-fill from the argmax pixel,
# by contrast, measured a stable 2-4 pixel cluster across every threshold
# from 80%-98% and every radius cap from 20-100px tried — the radius cap
# was never even reached. 90% / 50px is the chosen pair: comfortably
# inside the stable range, with headroom before the cap could matter.
CLUSTER_THRESHOLD_FRAC = 0.90
CLUSTER_RADIUS_CAP_PX = 50


def _local_coverage_cluster(coverage: "np.ndarray", y0: int, x0: int, max_coverage: float):
    """Bounded 4-connected flood-fill from the max-coverage pixel (y0, x0):
    only follows PHYSICALLY ADJACENT pixels at/above
    CLUSTER_THRESHOLD_FRAC * max_coverage, and never steps more than
    CLUSTER_RADIUS_CAP_PX away from the starting pixel in either axis — so
    a second, unrelated hot spot elsewhere on the page can never be pulled
    into the same cluster (see the module-level comment above for the
    measurement that ruled out a page-wide threshold mask). Returns
    (pixel_count, (x0,y0,x1,y1)) — the bbox is pixel-inclusive (x1/y1 are
    one past the last included pixel, matching the +1 convention
    max_coverage_rect_pt already uses below).
    """
    height, width = coverage.shape
    threshold = max_coverage * CLUSTER_THRESHOLD_FRAC
    visited = {(y0, x0)}
    queue = deque([(y0, x0)])
    while queue:
        cy, cx = queue.popleft()
        if abs(cy - y0) >= CLUSTER_RADIUS_CAP_PX or abs(cx - x0) >= CLUSTER_RADIUS_CAP_PX:
            continue
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = cy + dy, cx + dx
            if (
                0 <= ny < height and 0 <= nx < width
                and (ny, nx) not in visited
                and coverage[ny, nx] >= threshold
            ):
                visited.add((ny, nx))
                queue.append((ny, nx))
    ys = [p[0] for p in visited]
    xs = [p[1] for p in visited]
    bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
    return len(visited), bbox


def render_ink_heatmap(
    page: "pymupdf.Page",
    max_dimension_px: int = DEFAULT_MAX_DIMENSION_PX,
    max_alpha: int = 170,
    cmyk_arr: Optional["np.ndarray"] = None,
) -> Optional[dict]:
    """Renders a CMYK total-area-coverage heatmap overlay for the page.

    NOTE — this is a rasterized approximation (rendered pixel CMYK sum, not
    a true object-level ink-build calculation): good enough to visually flag
    hot spots for a designer, but should be labeled as informational/
    approximate in the UI. Returns None if the page has no visible CMYK
    content (e.g. it renders as effectively blank), so the frontend can skip
    offering the heatmap toggle rather than showing an empty overlay.

    Pass `cmyk_arr` (from _cmyk_pixmap_array) to reuse an already-rendered
    array instead of rendering the page a second time — render_cmyk_data_bitmap
    needs the same array, so compute it once and pass it to both.

    Returns {url, max_coverage_pct, page, max_coverage_pixel,
    max_coverage_rect_pt, max_coverage_cluster_rect_pt,
    max_coverage_cluster_pixels, max_coverage_cluster_area_pct} matching
    frontend InkHeatmap. Every field past `max_coverage_pct` is additive
    (TAC location audit, read-only investigation first) — `url` and
    `max_coverage_pct` are computed exactly as before, unchanged.
    """
    if cmyk_arr is None:
        cmyk_arr, _ = _cmyk_pixmap_array(page, max_dimension_px)
    arr = cmyk_arr.astype(np.float32)

    coverage = arr.sum(axis=2) / (4 * 255.0)  # 0.0 - 1.0 per pixel
    max_coverage = float(coverage.max()) if coverage.size else 0.0

    if max_coverage < 0.02:  # effectively blank page — nothing worth overlaying
        return None

    idx = np.clip((coverage * 255).astype(np.uint8), 0, 255)
    rgb = _GRADIENT_LUT[idx]  # (h, w, 3)
    alpha = np.clip((coverage * max_alpha), 0, max_alpha).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])

    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    # Where the reported max actually came from. Same PDF-point coordinate
    # system as main.py's hairline_locations (page.mediabox / get_drawings
    # rect / raster pixel all share one top-left-origin, Y-down space —
    # verified empirically, see the TAC audit): pixel -> pt is a plain
    # divide by `scale`, no vertical flip. `_page_scale` is pure arithmetic
    # (no render), so it's safe to (re)compute here even when `cmyk_arr`
    # was passed in and its own scale wasn't kept.
    scale = _page_scale(page, max_dimension_px)
    y_max, x_max = np.unravel_index(np.argmax(coverage), coverage.shape)
    x_max, y_max = int(x_max), int(y_max)
    inv_scale = 1.0 / scale if scale > 0 else 1.0
    max_coverage_rect_pt = [
        round(x_max * inv_scale, 3), round(y_max * inv_scale, 3),
        round((x_max + 1) * inv_scale, 3), round((y_max + 1) * inv_scale, 3),
    ]

    cluster_pixels, (cx0, cy0, cx1, cy1) = _local_coverage_cluster(coverage, y_max, x_max, max_coverage)
    max_coverage_cluster_rect_pt = [
        round(cx0 * inv_scale, 3), round(cy0 * inv_scale, 3),
        round(cx1 * inv_scale, 3), round(cy1 * inv_scale, 3),
    ]
    total_pixels = coverage.shape[0] * coverage.shape[1]

    return {
        "url": data_uri,
        "max_coverage_pct": round(max_coverage * 400, 1),  # 0-400% TAC scale — UNCHANGED
        "page": page.number + 1,  # 1-indexed, same convention as hairline_locations
        "max_coverage_pixel": {"x": x_max, "y": y_max},
        "max_coverage_rect_pt": max_coverage_rect_pt,
        "max_coverage_cluster_rect_pt": max_coverage_cluster_rect_pt,
        "max_coverage_cluster_pixels": cluster_pixels,
        "max_coverage_cluster_area_pct": round(100.0 * cluster_pixels / total_pixels, 4) if total_pixels else 0.0,
    }


def render_cmyk_data_bitmap(
    page: "pymupdf.Page",
    max_dimension_px: int = DEFAULT_MAX_DIMENSION_PX,
    cmyk_arr: Optional["np.ndarray"] = None,
) -> dict:
    """Encodes the RAW per-pixel CMYK bytes as an OPAQUE RGBA PNG (R=Cyan,
    G=Magenta, B=Yellow, alpha=255) plus a separate grayscale ``k_data`` PNG
    carrying the Key/black plane (each 0-255 representing 0-100% ink on that
    channel). PNG is lossless, so this round-trips exact byte values.

    ★ The Key channel deliberately does NOT travel in the RGBA alpha slot
    anymore. The frontend reads this PNG through canvas drawImage +
    getImageData, and a canvas stores pixels PREMULTIPLIED: any pixel with
    alpha=0 (i.e. K=0% — exactly the flat colored artwork the hover readout
    exists for) reads back as (0,0,0,0), destroying C/M/Y regardless of the
    bytes in the file. Splitting K into its own opaque plane keeps every
    channel readable; the K plane uses the same "higher byte = more ink"
    polarity as the C/M/Y bytes (NOT the spot plates' inverted TIFF polarity).

    This is what powers three things in the new Checker spec: the
    cursor-follow "C:75% M:68% Y:67% K:90% (Total: 300%)" readout, the
    bottom CMYK-separations channel toggles (recompose by zeroing out a
    channel client-side), and precise rich-black detection (K-only text
    with C=M=Y=0). The frontend loads these into an offscreen canvas and
    reads pixels with getImageData — no need to ship raw per-pixel arrays
    over JSON.

    Pass `cmyk_arr` to reuse an already-rendered array (see render_ink_heatmap).
    Must be rendered at the SAME max_dimension_px as render_page_preview so
    the two align pixel-for-pixel (both use the shared `_page_scale`, so this
    is automatic as long as callers don't pass mismatched values).
    """
    if cmyk_arr is None:
        cmyk_arr, scale = _cmyk_pixmap_array(page, max_dimension_px)
    else:
        scale = _page_scale(page, max_dimension_px)

    # Opaque CMY plane: constant alpha, so canvas readback can never clobber
    # the color bytes.
    opaque = np.full((*cmyk_arr.shape[:2], 4), 255, dtype=np.uint8)
    opaque[:, :, :3] = cmyk_arr[:, :, :3]
    img = Image.fromarray(opaque, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)  # lossless regardless of optimize
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

    # Key plane: single-channel grayscale, direct polarity (byte = 0-100% ink).
    k_img = Image.fromarray(cmyk_arr[:, :, 3], mode="L")
    k_buf = io.BytesIO()
    k_img.save(k_buf, format="PNG", optimize=True)
    k_data_uri = "data:image/png;base64," + base64.b64encode(k_buf.getvalue()).decode("ascii")

    return {
        "url": data_uri,
        "width_px": cmyk_arr.shape[1],
        "height_px": cmyk_arr.shape[0],
        "scale": round(scale, 6),
        "k_data": {
            "url": k_data_uri,
            "width_px": cmyk_arr.shape[1],
            "height_px": cmyk_arr.shape[0],
        },
    }
