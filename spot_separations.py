"""
BoxCheck — spot-color separation preview via Ghostscript's tiffsep device.

Runs `gs -sDEVICE=tiffsep` against the uploaded PDF and extracts ONLY the
spot-color plates (Cyan/Magenta/Yellow/Black are dropped — those are already
covered by render_preview.py's CMYK data bitmap). Only meant to be called
when the page's own spot-color check (main.py's collect_spot_colors) has
already found at least one named spot — Ghostscript is real work, no reason
to pay for it on a file with process inks only.

PDF bytes and Ghostscript's TIFF outputs live entirely in a
tempfile.TemporaryDirectory() and are gone the moment this function returns,
matching the project's "nothing is persisted" principle used throughout
render_preview.py.
"""

from __future__ import annotations

import base64
import io
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

from render_preview import _page_scale, DEFAULT_MAX_DIMENSION_PX

logger = logging.getLogger("boxcheck.spot_separations")

GS_TIMEOUT_SECONDS = 25
_PROCESS_PLATE_NAMES = {"cyan", "magenta", "yellow", "black"}


def _decode_preview_rgb(preview_data_uri: str) -> "np.ndarray | None":
    try:
        _, b64 = preview_data_uri.split(",", 1)
        img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
        return np.array(img, dtype=np.uint8)
    except Exception:
        return None


def _average_color_at_high_coverage(coverage: "np.ndarray", preview_rgb: "np.ndarray", threshold: int = 127) -> str:
    """Approximates the spot ink's visible color WITHOUT parsing the PDF's
    own Separation/DeviceN tint-transform function: mask pixels where this
    plate has significant ink, then average the RGB the page already
    rendered to (render_page_preview's output, already computed for the
    response) at those same pixels. Falls back to mid-gray if the plate is
    essentially empty (no ink found anywhere) or there's no preview to
    sample from.

    tiffsep plates use standard TIFF grayscale polarity: 0 = full ink,
    255 = no ink/paper (verified against a real file's process plates,
    which read ~96-97% at 255 — matching a mostly-blank page background,
    not "255 = full ink" as first assumed).
    """
    if preview_rgb is None:
        return "#808080"
    # Ghostscript's raster and pymupdf's preview pixmap round page
    # dimensions independently and can differ by a pixel or two — crop both
    # to their common region rather than refusing to sample at all.
    h = min(coverage.shape[0], preview_rgb.shape[0])
    w = min(coverage.shape[1], preview_rgb.shape[1])
    coverage = coverage[:h, :w]
    preview_rgb = preview_rgb[:h, :w]

    mask = coverage <= threshold
    if not mask.any():
        return "#808080"
    r = int(preview_rgb[..., 0][mask].mean())
    g = int(preview_rgb[..., 1][mask].mean())
    b = int(preview_rgb[..., 2][mask].mean())
    return f"#{r:02x}{g:02x}{b:02x}"


def _maybe_flatten_ocgs(pdf_bytes: bytes, page: "pymupdf.Page") -> bytes:
    """Ghostscript 9.55.0's PDF interpreter (predates the "pdfi" C rewrite
    that only became default in the 10.x series) doesn't reliably honor a
    plain Optional Content /D /ON layer state the way pymupdf's own MuPDF
    engine does — verified against a real file where a genuinely
    on-by-default "die" layer (no /AS override, plainly in /D /ON) rendered
    as 0% ink under tiffsep until flattened this way, then rendered
    correctly (12.6% ink coverage), with no change to the process plates.

    Forces every OCG to /ON and drops /OFF entirely, then re-serializes —
    all on an INDEPENDENT copy opened fresh from `pdf_bytes`, never
    mutating the live `page`/its Document, which the rest of /check's
    render pipeline is still using. Only pays for the re-open + reserialize
    when the page's document actually has OCGs at all (checked cheaply via
    the already-open `page`, no extra parse) — the common case (no layers)
    returns `pdf_bytes` unchanged.
    """
    if not page.parent.get_ocgs():
        return pdf_bytes
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        ocgs = doc.get_ocgs()
        doc.set_layer(-1, on=list(ocgs.keys()), off=[])
        return doc.tobytes()
    finally:
        doc.close()


def render_spot_separations(
    pdf_bytes: bytes,
    page: "object",
    spot_names: list[str],
    preview_data_uri: str,
    max_dimension_px: int = DEFAULT_MAX_DIMENSION_PX,
    page_index: int = 0,
) -> list[dict]:
    """Returns [{name, url, width_px, height_px, scale, display_color_hex}],
    one per spot-color plate Ghostscript actually produced, matched
    case-insensitively against `spot_names` from the existing spot-color
    check (so a plate Ghostscript reports that the page's own scan didn't
    name is skipped rather than surfaced unverified). `url` is a lossless
    grayscale PNG data URI, 0=no ink/255=full ink on that plate, at the same
    scale as preview/cmyk_data (render_preview._page_scale, so all three
    line up pixel-for-pixel).

    Round 12 phase C: `page_index` (0-based) restricts Ghostscript to that
    ONE page via -dFirstPage/-dLastPage — previously always omitted, which
    meant GS silently rasterized every page of a multi-page PDF and this
    function only ever read back the results for whichever page tiffsep
    numbered "1" (its own output numbering, always restarting at 1
    regardless of which source page(s) it was given — confirmed
    experimentally: `-dFirstPage=2 -dLastPage=2` on a 3-page file still
    produces `sep_1(Plate).tif`, not `sep_2(...)`). That's why the glob
    below doesn't need to change for a different page_index — only the
    -dFirstPage/-dLastPage args do. This was both wasted work (GS was
    already paying for every page's separations, previously) and a
    correctness prerequisite for the page-switcher (item this phase adds):
    without restricting the page, this function could never honestly
    render page 2+'s own separations, only ever page 1's.

    Never raises: any Ghostscript failure, timeout, or parsing problem is
    logged and swallowed, returning [] so one bad file can't take down
    /check.
    """
    if not spot_names:
        return []

    wanted = {n.lower() for n in spot_names}
    scale = _page_scale(page, max_dimension_px)
    dpi = scale * 72.0
    preview_rgb = _decode_preview_rgb(preview_data_uri)
    gs_page_number = page_index + 1  # Ghostscript page numbers are 1-based

    try:
        with tempfile.TemporaryDirectory(prefix="boxcheck-tiffsep-") as tmpdir:
            tmp = Path(tmpdir)
            input_pdf = tmp / "input.pdf"
            input_pdf.write_bytes(_maybe_flatten_ocgs(pdf_bytes, page))
            output_pattern = tmp / "sep_%d.tif"

            proc = subprocess.run(
                [
                    "gs", "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dQUIET",
                    "-sDEVICE=tiffsep", f"-r{dpi:.2f}",
                    f"-dFirstPage={gs_page_number}", f"-dLastPage={gs_page_number}",
                    f"-sOutputFile={output_pattern}", str(input_pdf),
                ],
                capture_output=True,
                timeout=GS_TIMEOUT_SECONDS,
            )
            if proc.returncode != 0:
                logger.warning(
                    "tiffsep failed (rc=%s): %s",
                    proc.returncode,
                    proc.stderr.decode("latin-1", "ignore")[:500],
                )
                return []

            results: list[dict] = []
            for tif_path in sorted(tmp.glob("sep_1(*).tif")):
                plate_name = tif_path.stem.split("(", 1)[1].rstrip(")")
                if plate_name.lower() in _PROCESS_PLATE_NAMES:
                    continue
                if plate_name.lower() not in wanted:
                    continue

                with Image.open(tif_path) as im:
                    coverage = np.array(im.convert("L"), dtype=np.uint8)

                height_px, width_px = coverage.shape
                display_color_hex = _average_color_at_high_coverage(coverage, preview_rgb)

                buf = io.BytesIO()
                Image.fromarray(coverage, mode="L").save(buf, format="PNG", optimize=True)
                data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

                results.append(
                    {
                        "name": plate_name,
                        "url": data_uri,
                        "width_px": width_px,
                        "height_px": height_px,
                        "scale": round(scale, 6),
                        "display_color_hex": display_color_hex,
                    }
                )
            return results
    except Exception:
        logger.exception("Spot separation rendering failed")
        return []
