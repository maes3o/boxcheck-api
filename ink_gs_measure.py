"""
BoxCheck Ink Coverage — Ghostscript tiffsep measurement.

One Ghostscript call per page. Each colorant gets an 8-bit plate
(255 = no ink); ink = 255 - v. DPI and pixel budgets follow the v1 spec:
150 dpi default, 72 floor, 20 Mpx base budget; an optional second pass up to
600 dpi / 40 Mpx for pages with thin strokes.

Raster thin-stroke error is a documented limitation: NO correction factor is
applied anywhere — values are reported as measured.

Nothing here imports main.py. -dSAFER always; -dNOSAFER is never used.
"""

from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import time
import unicodedata
from pathlib import Path

import numpy as np
from PIL import Image

BASE_DPI = 150.0
MIN_DPI = 72.0
THIN_STROKE_MAX_DPI = 600.0
BASE_PIXEL_BUDGET = 20_000_000
THIN_PIXEL_BUDGET = 40_000_000
GS_PAGE_TIMEOUT_S = 20.0
STDERR_CAP = 64 * 1024

PROCESS_PLATES = ("cyan", "magenta", "yellow", "black")
# Ghostscript 9.55 tiffsep writes at most 14 plates: C, M, Y, K + 10 spots.
# Further spot colorants are silently folded into CMYK via their alternate
# space (verified experimentally on 9.55.0).
GS_MAX_SPOT_PLATES = 10     # Ghostscript's built-in default; raised per call with -dMaxSpots=N
MAX_SPOTS_CAP = 32          # = the v1 colorants-per-page limit (GS 9.55 accepts 0..60)


class GsTimeout(Exception):
    pass


class PageTooLarge(Exception):
    """Even the 72 dpi floor exceeds the base pixel budget."""


def gs_binary() -> str:
    return os.environ.get("INK_GS_BIN", "gs")


def gs_version(binary: str | None = None) -> str:
    try:
        r = subprocess.run([binary or gs_binary(), "--version"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------
# DPI / pixel-budget planning (pure)
# --------------------------------------------------------------------------

def _fit_dpi(width_pt: float, height_pt: float, cap_dpi: float, budget_px: int) -> float:
    area_in2 = (width_pt / 72.0) * (height_pt / 72.0)
    if area_in2 <= 0:
        return cap_dpi
    dpi = min(cap_dpi, math.sqrt(budget_px / area_in2))
    dpi = math.floor(dpi * 100) / 100.0
    # raster dimensions are rounded up; shave the DPI until the budget holds
    while dpi > 0 and math.ceil(width_pt * dpi / 72.0) * math.ceil(height_pt * dpi / 72.0) > budget_px:
        dpi = math.floor((dpi - 0.01) * 100) / 100.0
    return dpi


def plan_base_dpi(width_pt: float, height_pt: float) -> dict:
    """Base pass: 150 dpi, reduced (never below 72) to stay within 20 Mpx.
    Raises PageTooLarge when 72 dpi would still exceed the budget."""
    dpi = _fit_dpi(width_pt, height_pt, BASE_DPI, BASE_PIXEL_BUDGET)
    if dpi < MIN_DPI:
        raise PageTooLarge()
    return {"dpi": dpi, "pixel_budget_limited": dpi < BASE_DPI}


def plan_thin_stroke_dpi(width_pt: float, height_pt: float, base_dpi: float) -> dict | None:
    """Second pass for pages with thin strokes: up to 600 dpi within 40 Mpx.
    None when the budget leaves no higher DPI than the base pass."""
    dpi = _fit_dpi(width_pt, height_pt, THIN_STROKE_MAX_DPI, THIN_PIXEL_BUDGET)
    if dpi <= base_dpi + 1.0:
        return None
    return {"dpi": dpi, "pixel_budget_limited": dpi < THIN_STROKE_MAX_DPI}


# --------------------------------------------------------------------------
# Name normalisation (plate filenames <-> colorant names)
# --------------------------------------------------------------------------

_PCT_RE = re.compile(r"(?:%[0-9A-Fa-f]{2})+")


def fix_plate_name(name: str) -> str:
    """Plate names come from file names: repair surrogate-escaped bytes and
    expand the %XX escapes Ghostscript uses for non-ASCII colorant names."""
    try:
        raw = name.encode("utf-8", "surrogateescape")
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError:
            name = raw.decode("latin-1")
    except UnicodeError:
        pass

    def unescape(m):
        try:
            return bytes(int(h, 16) for h in m.group().split("%")[1:]).decode("utf-8")
        except UnicodeDecodeError:
            return m.group()
    return _PCT_RE.sub(unescape, name)


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFC", name)
    try:  # UTF-8 mis-decoded as latin-1
        fixed = n.encode("latin-1").decode("utf-8")
        n = unicodedata.normalize("NFC", fixed)
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return " ".join(n.casefold().split())


def loose_name(name: str) -> str:
    return re.sub(r"[^0-9a-z\u0080-￿]", "", norm_name(name))


# --------------------------------------------------------------------------
# Ghostscript runner
# --------------------------------------------------------------------------

def spot_plane_request(n_spots: int | None) -> int | None:
    """-dMaxSpots value for `n_spots` detected spot colorants, or None to keep
    Ghostscript's default of 10. `None`/unknown count (plates-only detection)
    asks for the full 32."""
    if n_spots is None:
        return MAX_SPOTS_CAP
    if n_spots <= GS_MAX_SPOT_PLATES:
        return None
    return min(n_spots, MAX_SPOTS_CAP)


def gs_args(binary: str, pdf: Path, page_no: int, dpi: float, out_pattern: Path,
            max_spots: int | None = None) -> list[str]:
    extra = [f"-dMaxSpots={max_spots}"] if max_spots else []
    return [
        binary, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dQUIET",
        "-dNumRenderingThreads=1", "-dUseCropBox",
        "-dGraphicsAlphaBits=4", "-dTextAlphaBits=4", *extra,
        "-sDEVICE=tiffsep", f"-r{dpi:.2f}",
        f"-dFirstPage={page_no}", f"-dLastPage={page_no}",
        f"-sOutputFile={out_pattern}", str(pdf),
    ]


def run_gs(pdf: Path, page_no: int, dpi: float, outdir: Path, timeout_s: float,
           max_spots: int | None = None) -> tuple[int, str]:
    """Runs Ghostscript for one page in its own session; kills the whole
    process group on timeout. Returns (returncode, stderr[:64KB])."""
    out_pattern = outdir / "p.tif"
    proc = subprocess.Popen(
        gs_args(gs_binary(), pdf, page_no, dpi, out_pattern, max_spots),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        _out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        raise GsTimeout()
    return proc.returncode, (err or b"")[:STDERR_CAP].decode("latin-1", "replace")


# --------------------------------------------------------------------------
# Plate loading / statistics
# --------------------------------------------------------------------------

_PLATE_RE = re.compile(r"^p\((.*)\)\.tif$", re.S)


def plate_stats(ink: np.ndarray, area_mm2: float) -> dict:
    """`ink` is a uint8 array (0 = no ink, 255 = full)."""
    total = ink.size
    nz = ink > 0
    n_nz = int(nz.sum())
    mean = float(ink.sum(dtype=np.uint64)) / (255.0 * total) if total else 0.0
    return {
        "ink_mean_pct": round(mean * 100, 4),
        "area_any_ink_pct": round(n_nz / total * 100, 4) if total else 0.0,
        "max_ink_pct": round(float(ink.max()) / 255.0 * 100, 2) if total else 0.0,
        "mean_ink_on_inked_area_pct": round(float(ink[nz].mean()) / 255.0 * 100, 4) if n_nz else 0.0,
        "full_ink_equivalent_mm2": round(mean * area_mm2, 3),
    }


def empty_stats() -> dict:
    return {
        "ink_mean_pct": 0.0, "area_any_ink_pct": 0.0, "max_ink_pct": 0.0,
        "mean_ink_on_inked_area_pct": 0.0, "full_ink_equivalent_mm2": 0.0,
    }


def load_plates(outdir: Path, area_mm2: float) -> dict:
    """Reads every separation plate GS wrote. Returns
    {"plates": {name: stats}, "px": [w, h], "peak_total_pct": float}.
    Peak total = max per-pixel sum over ALL plates (int16 accumulator)."""
    plates: dict[str, dict] = {}
    acc = None
    shape = None
    for entry in sorted(os.listdir(outdir)):
        m = _PLATE_RE.match(entry)
        if not m:
            continue
        name = fix_plate_name(m.group(1))
        with Image.open(outdir / entry) as im:
            arr = np.asarray(im.convert("L") if im.mode != "L" else im, dtype=np.uint8)
        if arr.ndim != 2:
            continue
        if shape is None:
            shape = arr.shape
        elif arr.shape != shape:
            continue
        ink = np.subtract(255, arr, dtype=np.uint8)
        del arr
        if acc is None:
            acc = np.zeros(shape, dtype=np.int16)
        acc += ink
        key = name
        if key in plates:   # identical raw names cannot be told apart
            plates[key]["duplicate"] = True
            continue
        s = plate_stats(ink, area_mm2)
        s["duplicate"] = False
        plates[key] = s
    peak = float(acc.max()) / 255.0 * 100 if acc is not None else 0.0
    return {
        "plates": plates,
        "px": [int(shape[1]), int(shape[0])] if shape else [0, 0],
        "peak_total_pct": round(peak, 2),
    }


def measure_page(pdf: Path, page_no: int, dpi: float, workdir: Path, area_mm2: float,
                 deadline: float, max_spots: int | None = None) -> dict:
    """One tiffsep pass. `deadline` is a time.monotonic() value; the per-page
    timeout is min(20 s, time left). Raises GsTimeout."""
    left = deadline - time.monotonic()
    if left <= 1.0:
        raise GsTimeout()
    outdir = Path(workdir) / f"pass_{page_no}_{int(dpi)}"
    outdir.mkdir(parents=True, exist_ok=True)
    rc, err = run_gs(pdf, page_no, dpi, outdir, min(GS_PAGE_TIMEOUT_S, left), max_spots)
    result = {"gs_returncode": rc, "stderr": err, "dpi": dpi, "plates": {}, "px": [0, 0], "peak_total_pct": 0.0}
    if rc == 0:
        result.update(load_plates(outdir, area_mm2))
        result["gs_returncode"] = rc
    return result
