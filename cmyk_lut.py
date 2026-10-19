"""
BoxCheck — round 6 phase G: a real ICC-managed CMYK->sRGB lookup table,
replacing the canvas's naive `255 - min(255, ink+K)` subtractive recompose
formula with an actual color-managed conversion through a genuine Coated
FOGRA39 profile (confirmed against the file's own ICC metadata — CMYK
color space, Lab PCS, "Fogra39" in its description, X-Rite copyright).

Design (agreed with the user before implementation, since this phase was
explicitly flagged as carrying real technical risk):
  - 9 grid points per channel (9**4 = 6561 CMYK entries). CMYK is smooth
    enough that this captures it well, and the client-side interpolation
    *math* cost dominates runtime far more than table size does, so there's
    no performance reason to go bigger.
  - Built once via PIL.ImageCms (relative colorimetric intent, matching the
    report UI's own "відносний колориметричний рендер" disclaimer text),
    cached to disk so a server restart doesn't repeat the ~1-3s build, and
    held in an in-memory cache on top of that so repeated requests within
    one process never touch disk again either.
  - Served as a small standalone binary endpoint (see main.py's
    /lut/cmyk-to-srgb) with long-lived cache headers, NOT embedded in every
    /check response — the table is identical for every file checked, so
    repeating it per-request would waste bandwidth for nothing.
  - Byte layout: flat uint8 RGB triples, nested index order
    ((c*N + m)*N + y)*N + k, i.e. K varies fastest. The frontend's
    quadrilinear interpolation (InteractiveCanvas.tsx) must use the exact
    same order and N (sent via the X-Lut-Grid-N response header) to decode
    it correctly.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageCms

GRID_N = 9

_ICC_PATH = Path(__file__).parent / "icc" / "Coated_Fogra39L_VIGC_300.icc"
_CACHE_PATH = Path(__file__).parent / "lut_cache" / f"cmyk_to_srgb_fogra39_{GRID_N}.bin"

_lut_cache: bytes | None = None


def _grid_values(n: int) -> list[int]:
    """n evenly spaced 0-255 values, inclusive of both ends."""
    if n == 1:
        return [0]
    return [round(i * 255 / (n - 1)) for i in range(n)]


def build_lut(icc_path: Path = _ICC_PATH, grid_n: int = GRID_N) -> bytes:
    """Samples the ICC profile's CMYK->sRGB transform at every grid point
    and returns the flat RGB byte table (see module docstring for layout).
    """
    values = _grid_values(grid_n)
    pixels: list[tuple[int, int, int, int]] = [
        (c, m, y, k) for c in values for m in values for y in values for k in values
    ]

    # One wide (N, 1) CMYK image so the whole grid goes through the ICC
    # transform in a single call rather than one call per grid point.
    img = Image.new("CMYK", (len(pixels), 1))
    img.putdata(pixels)

    cmyk_profile = ImageCms.getOpenProfile(str(icc_path))
    srgb_profile = ImageCms.createProfile("sRGB")
    transform = ImageCms.buildTransform(
        cmyk_profile,
        srgb_profile,
        "CMYK",
        "RGB",
        renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
    )
    out = ImageCms.applyTransform(img, transform)

    flat = bytearray(len(pixels) * 3)
    for i, (r, g, b) in enumerate(out.get_flattened_data()):
        flat[i * 3] = r
        flat[i * 3 + 1] = g
        flat[i * 3 + 2] = b
    return bytes(flat)


def get_lut_bytes() -> bytes:
    """In-memory cache -> disk cache -> build, in that order of preference."""
    global _lut_cache
    if _lut_cache is not None:
        return _lut_cache

    expected_size = GRID_N**4 * 3
    if _CACHE_PATH.exists():
        data = _CACHE_PATH.read_bytes()
        if len(data) == expected_size:
            _lut_cache = data
            return data
        # Stale/corrupt cache (e.g. GRID_N changed) — fall through and rebuild.

    data = build_lut()
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_bytes(data)
    _lut_cache = data
    return data
