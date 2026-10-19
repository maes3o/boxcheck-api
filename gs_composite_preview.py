"""
BoxCheck — production GS composite base-visual-preview for pages with real
spot colors (Option B+C from the approved architecture audit).

pymupdf's naive CMYK/RGB rasterization (render_preview.py) has no
overprint/knockout model and was confirmed (Audit #2, Audit #3) to render
some real spot/overprint-heavy files as an unrecognizable flat color.
Ghostscript's tiffsep composite (already used in production by
spot_separations.py for per-plate masks) applies real overprint/knockout
semantics from the PDF's own content stream and was human-verified against
Adobe Acrobat Output Preview for the real reference file.

Deliberately a SEPARATE module from spot_separations.py, not a
consolidation — this MVP explicitly does not redesign spot_separations.py
per the approved architecture decision. That means a page with spot colors
pays for TWO Ghostscript invocations per /check (this one, plus
spot_separations.py's own) rather than one — a known, accepted tradeoff,
left for a later optimization pass, not addressed here.

`render_gs_composite_preview` is designed to NEVER raise past its own
boundary and to NEVER be called at all for CMYK-only pages — callers only
reach it after already confirming page1/this-page has real spot colors via
the EXISTING, unchanged collect_spot_colors gate (same variable
main.py already computes for spot_separations.py's own call).
"""

from __future__ import annotations

import base64
import io
import logging
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

logger = logging.getLogger("boxcheck.gs_composite_preview")

# Same convention/value as spot_separations.py's own GS_TIMEOUT_SECONDS —
# this function makes the same kind of synchronous GS subprocess call,
# deliberately kept at the same budget rather than inventing a new number.
GS_TIMEOUT_SECONDS = 25


def render_gs_composite_preview(pdf_bytes: bytes, page_index: int, fallback_preview: dict) -> dict:
    """Returns a dict matching render_page_preview()'s own shape
    ({url, width_px, height_px, scale}), sourced from Ghostscript's tiffsep
    composite when possible, resized to EXACTLY fallback_preview's own
    width_px/height_px — this is the "normalize dimensions" step the
    architecture review called for, so the returned preview's dimensions
    always match what the caller's already-computed pymupdf preview (and
    therefore cmyk_data/spot_separations, which share the same
    _page_scale) already reports.

    On ANY failure (GS missing, non-zero exit, timeout, missing/empty/
    corrupt output, unexpected dimensions, any other exception) — logs a
    warning with enough detail to debug and returns `fallback_preview`
    UNCHANGED. Callers can therefore always use this function's return
    value directly as the canvas preview, with no separate error handling
    needed at the call site — same resilience contract
    spot_separations.py::render_spot_separations already established for
    the existing separations pipeline.
    """
    dpi = fallback_preview["scale"] * 72.0
    gs_page_number = page_index + 1  # Ghostscript page numbers are 1-based

    try:
        with tempfile.TemporaryDirectory(prefix="boxcheck-gs-preview-") as tmpdir:
            tmp = Path(tmpdir)
            input_pdf = tmp / "input.pdf"
            input_pdf.write_bytes(pdf_bytes)
            output_file = tmp / "composite.tif"

            proc = subprocess.run(
                [
                    "gs", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dQUIET",
                    "-sDEVICE=tiffsep", f"-r{dpi:.2f}",
                    f"-dFirstPage={gs_page_number}", f"-dLastPage={gs_page_number}",
                    f"-sOutputFile={output_file}", str(input_pdf),
                ],
                capture_output=True,
                timeout=GS_TIMEOUT_SECONDS,
            )
            if proc.returncode != 0:
                logger.warning(
                    "gs composite preview: non-zero exit (rc=%s) for page_index=%d: %s",
                    proc.returncode, page_index, proc.stderr.decode("latin-1", "ignore")[:500],
                )
                return fallback_preview

            if not output_file.exists() or output_file.stat().st_size == 0:
                logger.warning(
                    "gs composite preview: no/empty output file for page_index=%d. stderr: %s",
                    page_index, proc.stderr.decode("latin-1", "ignore")[:500],
                )
                return fallback_preview

            try:
                with Image.open(output_file) as im:
                    if im.width <= 0 or im.height <= 0:
                        logger.warning(
                            "gs composite preview: unexpected dimensions %sx%s for page_index=%d",
                            im.width, im.height, page_index,
                        )
                        return fallback_preview
                    rgb = im.convert("RGB")
            except Exception:
                logger.warning(
                    "gs composite preview: output file for page_index=%d is not a readable image",
                    page_index, exc_info=True,
                )
                return fallback_preview

            target_size = (fallback_preview["width_px"], fallback_preview["height_px"])
            if rgb.size != target_size:
                rgb = rgb.resize(target_size, Image.LANCZOS)
            buf = io.BytesIO()
            rgb.save(buf, format="PNG", optimize=True)
            data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

            return {
                "url": data_uri,
                "width_px": fallback_preview["width_px"],
                "height_px": fallback_preview["height_px"],
                "scale": fallback_preview["scale"],
            }
    except subprocess.TimeoutExpired:
        logger.warning("gs composite preview: timed out after %ss for page_index=%d", GS_TIMEOUT_SECONDS, page_index)
        return fallback_preview
    except Exception:
        logger.exception("gs composite preview: unexpected failure for page_index=%d", page_index)
        return fallback_preview
