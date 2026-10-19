"""
BoxCheck — PROTOTYPE ONLY, native MuPDF separation API investigation.

Not wired into main.py/checks.py/any HTTP endpoint. Does not modify, import,
or replace spot_separations.py, render_preview.py, or gs_composite_preview.py
— this explores a DIFFERENT engine (pymupdf's own bundled low-level MuPDF
C API, via the `pymupdf.mupdf` submodule) as a possible alternative to the
Ghostscript-based pipeline, per explicit request. No production code path
uses anything in this file.

KEY FINDING (see this session's own investigation, not asserted from
memory): pymupdf 1.28.2's HIGH-level API (`import pymupdf`, i.e. the
`fitz`-style wrapper main.py/checks.py/render_preview.py already use)
exposes NO separation-related symbols at all (`dir(pymupdf)` — zero
matches for "separ"). The full native MuPDF separation API — including
every function requested (fz_page_separations, fz_set_separation_behavior,
FZ_SEPARATION_DISABLED, fz_new_pixmap_from_page_with_separations) — IS
present, but only via `pymupdf.mupdf`, a SEPARATE low-level SWIG-generated
submodule bundled inside the same pymupdf package. Reachable, in this
version, via `page.this` (a `pymupdf.mupdf.FzPage`), whose methods are the
real MuPDF C functions with the page as an implicit first argument.
"""

from __future__ import annotations

import numpy as np
import pymupdf
import pymupdf.mupdf as raw
from PIL import Image


def get_page_separations(page: "pymupdf.Page"):
    """Returns (FzSeparations, [names]) for one page — empty list if the
    page has none. fz_page_uses_overprint() is also exposed directly on
    the same object and is a useful cheap pre-check."""
    seps = page.this.fz_page_separations()
    n = seps.fz_count_separations()
    names = [seps.fz_separation_name(i) for i in range(n)]
    return seps, names


def render_with_separations(page: "pymupdf.Page", dpi: float, disabled_names: list[str] | None = None) -> np.ndarray:
    """Renders the page to a raw CMYK numpy array (h, w, 4), honoring
    per-separation on/off state via the native API. `disabled_names`: which
    named separations to set to FZ_SEPARATION_DISABLED before rendering —
    everything else keeps its current/default behavior (typically
    FZ_SEPARATION_SPOT, i.e. on).
    """
    seps, names = get_page_separations(page)
    for name in disabled_names or []:
        if name in names:
            seps.fz_set_separation_behavior(names.index(name), raw.FZ_SEPARATION_DISABLED)

    cs = raw.fz_device_cmyk()
    scale = dpi / 72.0
    ctm = raw.fz_scale(scale, scale)
    pix = page.this.fz_new_pixmap_from_page_with_separations(ctm, cs, seps, 0)

    w, h, stride = pix.fz_pixmap_width(), pix.fz_pixmap_height(), pix.fz_pixmap_stride()
    mv = pix.fz_pixmap_samples_memoryview()
    # SAFETY (found the hard way — this crashed with a segfault without the
    # .copy()): fz_pixmap_samples_memoryview() is a VIEW into the C++
    # FzPixmap's own buffer, not a Python-owned copy. `pix` is a local
    # variable with no other reference — once this function returns, it's
    # garbage-collected, its C++ destructor frees the underlying sample
    # buffer, and any array still aliasing that memory (via np.frombuffer
    # without a copy) reads freed memory on first real use. Copying here,
    # while `pix` is still alive, is required for a safe return value.
    arr = np.frombuffer(mv, dtype=np.uint8).copy()
    n_ch = stride // w
    return arr[: h * stride].reshape(h, stride)[:, : w * n_ch].reshape(h, w, n_ch)


def cmyk_array_to_rgb_png(arr: np.ndarray, path: str) -> None:
    """Naive CMYK->RGB (PIL's built-in conversion, NOT the project's ICC
    LUT) purely for visual prototype inspection — not a claim of accurate
    on-screen color."""
    im = Image.frombytes("CMYK", (arr.shape[1], arr.shape[0]), arr.tobytes())
    im.convert("RGB").save(path)


def dump_alternate_colorspaces(doc: "pymupdf.Document", page: "pymupdf.Page") -> dict[str, str]:
    """Reads each Resources/ColorSpace entry's raw PDF object text — used
    here only to answer "does this file's spots use Lab?" by inspecting
    the real /Separation.../<alternate-space> declarations directly,
    independent of the native separations API above."""
    res = doc.xref_get_key(page.xref, "Resources/ColorSpace")
    if res[0] != "dict":
        return {}
    import re

    refs = dict(re.findall(r"/(\w+)\s+(\d+)\s+0\s+R", res[1]))
    return {name: doc.xref_object(int(xref)) for name, xref in refs.items()}
