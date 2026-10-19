"""
BoxCheck — pymupdf-facing extraction glue for the Tier 1 product checks.

Thin wrappers only: pull raw numbers/text out of a pymupdf Page and hand them
to the pure functions in geometry.py. Written against `import pymupdf`
(current pymupdf API name; the project's own code already uses
`pymupdf.open(...)` per project notes — swap to `import fitz as pymupdf` here
if the actual codebase still uses the old alias).
"""

from __future__ import annotations
from typing import Optional

import pymupdf


def get_trimbox_pt(page: "pymupdf.Page") -> tuple[float, float, float, float]:
    """Same source the existing bleed check already trusts (page.trimbox),
    falling back to mediabox if no TrimBox is defined — mirror whatever
    fallback the existing bleed check uses so the two checks agree; adjust
    this if main.py's fallback differs."""
    box = page.trimbox if page.trimbox else page.mediabox
    return (box.x0, box.y0, box.x1, box.y1)


def get_text_items_pt(page: "pymupdf.Page") -> list[tuple[str, tuple[float, float, float, float]]]:
    """One (text, bbox_pt) tuple per line (not per span) — lines give a more
    representative bbox for a heading/paragraph than individual spans, and
    keep the violation list short and readable."""
    items: list[tuple[str, tuple[float, float, float, float]]] = []
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in spans)
            bbox = line.get("bbox")
            if bbox is None:
                continue
            items.append((text, tuple(bbox)))
    return items
