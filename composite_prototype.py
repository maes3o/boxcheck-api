"""
BoxCheck — STEP 1 prototype: a real Ghostscript-composited CMYK raster for
ONE PDF page, for evaluating whether GS's own overprint/knockout modeling
(as interpreted from the PDF's real content stream) is a viable replacement
for InteractiveCanvas.tsx's current client-side subtractive spot overlay
(see Audit #2's Root Cause #1/#3 — that overlay cannot represent overprint
or knockout at all, and is structurally a no-op for a white spot ink).

ISOLATED PROTOTYPE — NOT wired into main.py/checks.py/any HTTP endpoint.
Nothing here changes existing production behavior. Deliberately does NOT
import from or modify spot_separations.py — this is a separate function
using the same well-established `gs -sDEVICE=tiffsep` subprocess pattern
(same device, same project already depends on it), so the comparison this
step is meant to produce isn't contaminated by any change to the existing,
already-shipped separations pipeline.

Ghostscript's tiffsep device, when given `-sOutputFile=composite.tif`
(a plain filename, not the `sep_%d(Plate).tif` pattern spot_separations.py
uses for per-separation plates), ALSO always writes a full CMYK COMPOSITE
raster to that exact filename — verified empirically below (see
diagnostics/composite_prototype/NOTES.md): tiffsep writes one composite
file (exact name given) alongside one per-separation plate file per
colorant found in the page's actual resources. That composite is built by
Ghostscript's own PDF content-stream interpreter, which — per Ghostscript's
documented tiffsep behavior — applies overprint/knockout state as declared
in the PDF's ExtGState (/OP, /op, OPM) when compositing plates together,
unlike pymupdf's `get_pixmap(colorspace=csCMYK)`, which has no separation/
overprint model at all (see render_preview.py) and simply asks its own
renderer for a flat CMYK conversion.

CORRECTED CLAIM, post-empirical-test: an earlier version of this module
assumed Ghostscript's `-dSeparationColorNames` device parameter could be
used to EXCLUDE a specific real colorant (e.g. White-1) from getting its
own plate, to produce a "White-1 disabled" composite for comparison.
Tested directly against the real production PDF with
`-c "<< /SeparationColorNames [...] >> setpagedevice"` (the working CLI
form — plain `-dSeparationColorNames=[...]` errors out in this GS 9.55.0
build) explicitly omitting White-1: Ghostscript still auto-detected and
rendered White-1's plate identically to the unrestricted baseline run
(byte-identical file size). So `SeparationColorNames` does NOT suppress a
colorant actually used in the page's content in this GS version/build —
it appears to only pre-declare names for a device parameter that doesn't
override auto-detection from the content stream. No other GS-native,
content-stream-safe mechanism to synthesize a "White-1 off" render was
found within this prototype's scope (see the module-level report this
step produced for what WAS verified instead: a direct pixel-region
comparison between GS's real composite and pymupdf's naive one, under
White-1's own real ink mask, which answers the same underlying question
— "does GS's overprint-aware compositing do something pymupdf's naive
rasterizer doesn't, specifically where White-1 paints" — without needing
a fabricated on/off toggle).
"""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

logger = logging.getLogger("boxcheck.composite_prototype")

GS_TIMEOUT_SECONDS = 60


class CompositeRenderError(Exception):
    """Raised when Ghostscript fails or produces no composite file — never
    silently swallowed here (unlike spot_separations.py's production
    render_spot_separations, which must degrade gracefully for /check).
    This is a diagnostic tool: a silent failure would be actively
    misleading for a proof-of-correctness step."""


def render_ghostscript_composite(pdf_bytes: bytes, page_index: int = 0, dpi: float = 150.0) -> dict:
    """Renders ONE page's real Ghostscript CMYK composite (overprint/
    knockout as interpreted by GS from the PDF's own content stream), plus
    every per-separation plate GS produces alongside it.

    Returns {
      "composite_tiff": bytes,          # full CMYK composite, 4 samples/px
      "width_px": int, "height_px": int,
      "separations": {plate_name: bytes (grayscale TIFF)},
      "gs_command": list[str],          # exact argv used, for the report
    }

    Raises CompositeRenderError on any Ghostscript failure — see module
    docstring for why this doesn't swallow errors the way production code
    does.
    """
    gs_page_number = page_index + 1  # Ghostscript page numbers are 1-based

    with tempfile.TemporaryDirectory(prefix="boxcheck-composite-proto-") as tmpdir:
        tmp = Path(tmpdir)
        input_pdf = tmp / "input.pdf"
        input_pdf.write_bytes(pdf_bytes)
        output_file = tmp / "composite.tif"

        cmd = [
            "gs", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dQUIET",
            "-sDEVICE=tiffsep", f"-r{dpi:.2f}",
            f"-dFirstPage={gs_page_number}", f"-dLastPage={gs_page_number}",
            f"-sOutputFile={output_file}", str(input_pdf),
        ]

        proc = subprocess.run(cmd, capture_output=True, timeout=GS_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise CompositeRenderError(
                f"Ghostscript failed (rc={proc.returncode}): "
                f"{proc.stderr.decode('latin-1', 'ignore')[:2000]}"
            )
        if not output_file.exists():
            raise CompositeRenderError(
                f"Ghostscript exited 0 but wrote no composite file. stderr: "
                f"{proc.stderr.decode('latin-1', 'ignore')[:2000]}"
            )

        composite_bytes = output_file.read_bytes()
        with Image.open(io.BytesIO(composite_bytes)) as im:
            width_px, height_px = im.size

        separations: dict[str, bytes] = {}
        for tif_path in sorted(tmp.glob("composite(*).tif")):
            plate_name = tif_path.stem.split("(", 1)[1].rstrip(")")
            separations[plate_name] = tif_path.read_bytes()

        return {
            "composite_tiff": composite_bytes,
            "width_px": width_px,
            "height_px": height_px,
            "separations": separations,
            "gs_command": cmd,
        }


def render_naive_pymupdf_cmyk(page: "pymupdf.Page", dpi: float = 150.0) -> np.ndarray:
    """The CURRENT production comparison baseline: exactly the same call
    render_preview.py's _cmyk_pixmap_array already makes
    (page.get_pixmap(colorspace=pymupdf.csCMYK)), just parameterized by an
    explicit DPI (matching Ghostscript's -r flag exactly) instead of
    render_preview.py's max-dimension-based scale, so the two rasters are
    comparable pixel-for-pixel at the same nominal resolution. Does NOT
    modify or import render_preview.py — same underlying pymupdf call,
    written independently here to keep this prototype fully isolated.
    """
    matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)
    pixmap = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csCMYK, alpha=False)
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 4)


def tiff_bytes_to_array(tiff_bytes: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(tiff_bytes)) as im:
        return np.array(im)


def compare_under_mask(
    gs_composite: np.ndarray,
    naive_composite: np.ndarray,
    mask_tiff_bytes: bytes,
    ink_threshold: int = 127,
) -> dict:
    """Answers the real underlying question behind "does White-1 change the
    composite as expected" WITHOUT a fabricated on/off toggle (see module
    docstring for why one isn't available): compares Ghostscript's real,
    overprint-aware composite against pymupdf's naive one, split into
    pixels WHERE the given plate (e.g. White-1) actually has ink vs. pixels
    where it doesn't. If GS's overprint modeling is doing something real,
    the mean difference INSIDE the mask should be measurably different
    from the mean difference OUTSIDE it — pymupdf has no per-object
    overprint model at all, so any systematic difference specifically
    correlated with this one plate's own ink coverage is real evidence,
    not noise.

    `mask_tiff_bytes` uses tiffsep's native polarity (0=full ink,
    255=no ink) — same convention already documented in
    spot_separations.py and cmykSample.ts.
    """
    mask = tiff_bytes_to_array(mask_tiff_bytes)
    h = min(gs_composite.shape[0], naive_composite.shape[0], mask.shape[0])
    w = min(gs_composite.shape[1], naive_composite.shape[1], mask.shape[1])
    gs_c = gs_composite[:h, :w].astype(np.int16)
    naive_c = naive_composite[:h, :w].astype(np.int16)
    m = mask[:h, :w]

    inked = m < ink_threshold  # tiffsep polarity: LOW byte = ink present
    diff = np.abs(gs_c - naive_c)  # per-channel, shape (h, w, 4)
    diff_total = diff.sum(axis=2)  # 0-1020 per pixel

    inked_count = int(inked.sum())
    not_inked_count = int((~inked).sum())

    return {
        "compared_width": w,
        "compared_height": h,
        "mask_inked_pixel_count": inked_count,
        "mask_not_inked_pixel_count": not_inked_count,
        "mean_abs_diff_inside_mask": float(diff_total[inked].mean()) if inked_count else None,
        "mean_abs_diff_outside_mask": float(diff_total[~inked].mean()) if not_inked_count else None,
        "max_abs_diff_inside_mask": float(diff_total[inked].max()) if inked_count else None,
    }


def get_page_pdf_bytes(pdf_path: str, page_index: int = 0) -> bytes:
    """Extracts a single page as a standalone one-page PDF — tiffsep's own
    -dFirstPage/-dLastPage already restricts rendering to one page (see
    spot_separations.py's own precedent for this same approach), so this
    is only used here to keep the prototype's own input handling
    independent of the full multi-page source file."""
    doc = pymupdf.open(pdf_path)
    try:
        if len(doc) == 1:
            return doc.tobytes()
        sub = pymupdf.open()
        sub.insert_pdf(doc, from_page=page_index, to_page=page_index)
        data = sub.tobytes()
        sub.close()
        return data
    finally:
        doc.close()


def cmyk_tiff_to_png_bytes(tiff_bytes: bytes) -> bytes:
    """Converts tiffsep's raw CMYK composite TIFF to a viewable PNG (naive
    CMYK->RGB via PIL's own built-in conversion, NOT the project's ICC LUT
    from cmykLut.ts/cmyk_lut.py — this prototype's whole point is to
    inspect Ghostscript's own overprint compositing, not to reproduce
    accurate on-screen color; a diagnostic viewer, not a color-managed
    one)."""
    with Image.open(io.BytesIO(tiff_bytes)) as im:
        rgb = im.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="PNG")
        return buf.getvalue()


def separation_tiff_to_png_bytes(tiff_bytes: bytes) -> bytes:
    """Converts one grayscale separation plate (tiffsep polarity: 0=full
    ink, 255=no ink — same convention spot_separations.py already
    documents) to a viewable PNG, inverted so brighter = more ink (more
    intuitive for a human reviewing the diagnostic output than tiffsep's
    native paper-referenced polarity)."""
    with Image.open(io.BytesIO(tiff_bytes)) as im:
        gray = im.convert("L")
        inverted = Image.eval(gray, lambda px: 255 - px)
        buf = io.BytesIO()
        inverted.save(buf, format="PNG")
        return buf.getvalue()
