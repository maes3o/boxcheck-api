"""
BoxCheck — per-image region analysis: bbox + colorspace + effective DPI for
every raster image on a page. This is what powers the new location-aware
frontend features from Gemini's detailed Checker spec (09.09.2026):
"Highlight RGB Elements", low-DPI image pins, and the RGB Detector canvas
mode — all of which need to know WHERE on the page a flagged image sits,
not just that "an RGB image exists somewhere" (the granularity the
project's existing colorspace/DPI checks likely have today, per project
notes — this is additive, not a replacement: merge these regions into
whatever `details` the existing checks already carry).

Effective DPI, not declared/embedded DPI: computed from the image's actual
placed size on the page (from get_image_info's bbox, in PDF points) versus
its pixel dimensions — this is what determines print quality, and is
unaffected by a meaningless 72/96 dpi tag some export tools leave in the
image's own metadata.
"""

from __future__ import annotations
from typing import TypedDict

import pymupdf


class ImageRegion(TypedDict):
    bbox_pt: tuple[float, float, float, float]
    xref: int
    cs_name: str
    is_rgb: bool
    is_cmyk: bool
    is_gray: bool
    effective_dpi: float
    low_dpi: bool


PT_PER_IN = 72.0


def get_image_regions(page: "pymupdf.Page", dpi_threshold: float = 300.0) -> list[ImageRegion]:
    regions: list[ImageRegion] = []
    # xrefs=True: each region needs to know which underlying image resource
    # it's a placement of — the same embedded image is often drawn more than
    # once on a page (e.g. a repeated logo), and callers that summarize "N
    # images have issue X" need to count distinct resources, not placements.
    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox")
        if not bbox:
            continue
        x0, y0, x1, y1 = bbox
        width_pt, height_pt = abs(x1 - x0), abs(y1 - y0)
        if width_pt <= 0 or height_pt <= 0:
            continue

        px_w, px_h = info.get("width", 0), info.get("height", 0)
        width_in = width_pt / PT_PER_IN
        height_in = height_pt / PT_PER_IN
        dpi_x = px_w / width_in if width_in > 0 else 0
        dpi_y = px_h / height_in if height_in > 0 else 0
        effective_dpi = round(min(dpi_x, dpi_y), 1) if dpi_x and dpi_y else 0.0

        cs_name = str(info.get("cs-name", ""))
        cs_lower = cs_name.lower()
        is_gray = "gray" in cs_lower
        is_cmyk = "cmyk" in cs_lower
        # Separation/DeviceN (spot-color) images are print-safe on their own
        # plate — they must NOT fall into the "RGB, needs CMYK conversion"
        # bucket just because they're not literally Gray/CMYK/Indexed.
        # Confirmed against two real files: die-line/dimension markup
        # rendered via Separation(Lab, PANTONE ...) and a business card's
        # gradient stars — both were 100% misflagged as RGB before this.
        is_spot = cs_lower.startswith("separation") or cs_lower.startswith("devicen")
        # Treat anything not explicitly Gray/CMYK/Indexed/spot as RGB —
        # matches how printers actually care (RGB/Lab/anything not
        # separated is a problem; only true CMYK, spot, or Gray is safe).
        is_rgb = not is_gray and not is_cmyk and not is_spot and "indexed" not in cs_lower

        regions.append(
            {
                "bbox_pt": (x0, y0, x1, y1),
                "xref": info.get("xref", 0),
                "cs_name": cs_name,
                "is_rgb": is_rgb,
                "is_cmyk": is_cmyk,
                "is_gray": is_gray,
                "effective_dpi": effective_dpi,
                "low_dpi": effective_dpi > 0 and effective_dpi < dpi_threshold,
            }
        )
    return regions
