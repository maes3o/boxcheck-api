"""
BoxCheck — pure geometry helpers for the Tier 1 product checks.

Deliberately has NO dependency on pymupdf/fitz: everything here takes plain
tuples/floats so it can be unit-tested without a PDF engine, and so it's easy
to drop into the existing backend regardless of exactly how pages are parsed
there. The pymupdf-facing extraction glue lives in pdf_extract.py.

Coordinate convention: all "*_pt" rects are (x0, y0, x1, y1) in PDF points,
in the same normalized space pymupdf's page.rect / page.trimbox already use
(origin top-left, y increases downward, x1>x0, y1>y0). That's what
page.get_text("dict") span "bbox" and page.get_drawings() "rect" already give
you, so no flipping is needed if the existing bleed check already trusts
page.trimbox directly (per the project notes, it does).
"""

from __future__ import annotations
from typing import NamedTuple, Optional

PT_PER_MM = 72.0 / 25.4  # 1 mm = 72/25.4 pt ≈ 2.8346 pt
MM_PER_PT = 25.4 / 72.0


def pt_to_mm(value_pt: float) -> float:
    return value_pt * MM_PER_PT


def mm_to_pt(value_mm: float) -> float:
    return value_mm * PT_PER_MM


class Rect(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return abs(self.x1 - self.x0)

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)


# --------------------------------------------------------------------------- size matching

class SizeMatchResult(NamedTuple):
    matched: bool
    format_id: Optional[str]
    format_label_en: Optional[str]
    format_label_ua: Optional[str]
    trim_width_mm: float
    trim_height_mm: float
    deviation_mm: float  # max(|dw|, |dh|) against the best/matched format
    rotated: bool  # True if the match required swapping width/height


def _dims_deviation(trim_w: float, trim_h: float, fmt_w: float, fmt_h: float) -> tuple[float, bool]:
    """Returns (deviation_mm, rotated) — deviation is the worse of the two
    axis deltas, checked in both orientations (rotation-agnostic, matching
    the existing declared-size check's behavior per project notes)."""
    straight = max(abs(trim_w - fmt_w), abs(trim_h - fmt_h))
    rotated_dev = max(abs(trim_w - fmt_h), abs(trim_h - fmt_w))
    if rotated_dev < straight:
        return rotated_dev, True
    return straight, False


def match_product_size(
    trimbox_pt: tuple[float, float, float, float],
    formats: list[dict],
    tolerance_mm: float,
    format_id: Optional[str] = None,
) -> SizeMatchResult:
    """Compare a TrimBox (in PDF points) against a product's standard formats.

    If format_id is given, checks only against that one format. Otherwise
    finds the closest format among `formats` and reports whether it's within
    tolerance. `formats` is the list[ProductFormat]-shaped dicts from
    products.py (needs id/label_ua/label_en/width_mm/height_mm).
    """
    x0, y0, x1, y1 = trimbox_pt
    trim_w_mm = round(pt_to_mm(abs(x1 - x0)), 2)
    trim_h_mm = round(pt_to_mm(abs(y1 - y0)), 2)

    candidates = formats
    if format_id is not None:
        candidates = [f for f in formats if f["id"] == format_id]
        if not candidates:
            # Unknown format_id requested — treat as no-match, caller decides
            # how to surface that (likely a client bug, not a file defect).
            return SizeMatchResult(False, None, None, None, trim_w_mm, trim_h_mm, 0.0, False)

    best: Optional[tuple[dict, float, bool]] = None
    for fmt in candidates:
        dev, rotated = _dims_deviation(trim_w_mm, trim_h_mm, fmt["width_mm"], fmt["height_mm"])
        if best is None or dev < best[1]:
            best = (fmt, dev, rotated)

    if best is None:
        return SizeMatchResult(False, None, None, None, trim_w_mm, trim_h_mm, 0.0, False)

    fmt, dev, rotated = best
    return SizeMatchResult(
        matched=dev <= tolerance_mm,
        format_id=fmt["id"],
        format_label_en=fmt["label_en"],
        format_label_ua=fmt["label_ua"],
        trim_width_mm=trim_w_mm,
        trim_height_mm=trim_h_mm,
        deviation_mm=round(dev, 2),
        rotated=rotated,
    )


# --------------------------------------------------------------------------- safe zone

class SafeZoneViolation(NamedTuple):
    text: str
    bbox_pt: tuple[float, float, float, float]  # for drawing the violation outline on the canvas
    min_margin_mm: float
    side: str  # "left" | "right" | "top" | "bottom"
    crosses_trim: bool  # True if the element actually extends past the trim line


def _margins_mm(bbox: Rect, trim: Rect) -> dict[str, float]:
    return {
        "left": pt_to_mm(bbox.x0 - trim.x0),
        "right": pt_to_mm(trim.x1 - bbox.x1),
        "top": pt_to_mm(bbox.y0 - trim.y0),
        "bottom": pt_to_mm(trim.y1 - bbox.y1),
    }


def _overlaps(bbox: Rect, trim: Rect) -> bool:
    return bbox.x0 < trim.x1 and bbox.x1 > trim.x0 and bbox.y0 < trim.y1 and bbox.y1 > trim.y0


def check_safe_zone_text(
    trimbox_pt: tuple[float, float, float, float],
    text_items: list[tuple[str, tuple[float, float, float, float]]],
    safe_zone_mm: float,
    max_results: int = 25,
) -> list[SafeZoneViolation]:
    """text_items: list of (text_string, bbox_pt) — one per text span/line.
    Elements that don't overlap the trim area at all are ignored (e.g. bleed
    guides or off-canvas artboard notes). An element that overlaps the trim
    area but whose closest edge margin is below `safe_zone_mm` is reported;
    a negative margin means the element actually crosses the trim line.
    Empty/whitespace-only text is skipped. Results are capped and sorted by
    severity (smallest margin first).
    """
    trim = Rect(*trimbox_pt)
    violations: list[SafeZoneViolation] = []

    for text, bbox in text_items:
        if not text or not text.strip():
            continue
        rect = Rect(*bbox)
        if not _overlaps(rect, trim):
            continue
        margins = _margins_mm(rect, trim)
        side, min_margin = min(margins.items(), key=lambda kv: kv[1])
        if min_margin < safe_zone_mm:
            violations.append(
                SafeZoneViolation(
                    text=text.strip()[:60],
                    bbox_pt=(rect.x0, rect.y0, rect.x1, rect.y1),
                    min_margin_mm=round(min_margin, 2),
                    side=side,
                    crosses_trim=min_margin < 0,
                )
            )

    violations.sort(key=lambda v: v.min_margin_mm)
    return violations[:max_results]
