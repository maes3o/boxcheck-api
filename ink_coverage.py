"""
BoxCheck Ink Coverage — analysis driver (response schema v1).

    analyze_ink_coverage(pdf_bytes, opts) -> dict

Pipeline per page: geometry -> native colorant detection (ink_content_scan)
-> converted colour-space detection -> Ghostscript tiffsep measurement
(ink_gs_measure) -> reconciliation -> assembly.

Native detection and raster measurement stay separate until reconcile():
declared-but-unused colorants never count as ink, Ghostscript's always-present
empty C/M/Y/K plates never count as usage, and converted RGB/Gray/ICC/Lab ink
is reported apart from native plates. Ink amounts are raw — no thin-stroke
correction factor exists anywhere in this code.

Runs inside the isolated worker process (ink_worker.py); nothing imports main.py.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

import pymupdf

import ink_gs_measure as gm
from ink_content_scan import PROCESS_NAMES, ScanBudgetExceeded, scan_page

logger = logging.getLogger("boxcheck.ink_coverage")

SCHEMA_VERSION = 1
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGES = 10
TOTAL_DEADLINE_S = 55.0
METHOD = "gs-tiffsep-raster+content-scan"
MM_PER_PT = 25.4 / 72.0


class InkError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Reconciliation (pure; unit-tested without Ghostscript)
# --------------------------------------------------------------------------

def _level(flags: set[str], thin: int) -> str:
    if any(f.startswith("unvalidated") or f in ("transparency_used", "detected_from_plate_only",
                                                 "no_plate_gs_component_limit")
           for f in flags):
        return "unvalidated"
    if thin > 0:
        return "approximate"
    return "exact"


def _accuracy(flags: set[str], thin: int, minw) -> dict:
    flags = set(flags)
    if thin > 0:
        flags.add("thin_strokes")
    return {
        "level": _level(flags, thin),
        "flags": sorted(flags),
        "thin_stroke_paints": thin,
        "min_stroke_width_pt": minw,
    }


def _plate_index(plates: dict) -> tuple[dict, dict]:
    by_norm: dict[str, list[str]] = {}
    by_loose: dict[str, list[str]] = {}
    for raw in plates:
        by_norm.setdefault(gm.norm_name(raw), []).append(raw)
        by_loose.setdefault(gm.loose_name(raw), []).append(raw)
    return by_norm, by_loose


def reconcile(scan: dict | None, plates: dict | None, spot_ceiling: int = gm.GS_MAX_SPOT_PLATES) -> dict:
    """Matches detected colorants with measured plates.

    scan   output of scan_page, or None for plates-only detection
    plates {plate name: stats} from Ghostscript, or None when not measured
    spot_ceiling  number of spot planes Ghostscript was asked for (-dMaxSpots)

    Returns {colorants, zero_tint_only, derived_process_plates, diagnostics}.
    """
    diags: list[dict] = []
    out_colorants: list[dict] = []
    out_zero: list[dict] = []
    derived: list[dict] = []

    plates_only = scan is None
    detected_used = scan["colorants"] if scan else {}
    detected_zero = scan["zero_tint_only"] if scan else {}
    converted = scan["converted"] if scan else {}
    flags = scan["flags"] if scan else set()

    measured_run = plates is not None
    plates = plates or {}
    by_norm, by_loose = _plate_index(plates)

    # names that collide after normalisation (detected side)
    all_detected = list(detected_used) + list(detected_zero)
    det_count: dict[str, int] = {}
    for n in all_detected:
        det_count[gm.norm_name(n)] = det_count.get(gm.norm_name(n), 0) + 1

    matched_plates: set[str] = set()

    def find_plate(name: str):
        """-> (plate_raw | None, ambiguous)"""
        nk = gm.norm_name(name)
        if det_count.get(nk, 0) > 1:
            return None, True
        cands = by_norm.get(nk)
        if cands is None:
            cands = by_loose.get(gm.loose_name(name))
        if not cands:
            return None, False
        if len(cands) > 1:
            return None, True
        return cands[0], False

    # Ghostscript is asked for as many spot planes as spots were detected
    # (-dMaxSpots). If it still ran out (it emitted `spot_ceiling` spot
    # plates and a painted spot has none), the extras were folded into CMYK:
    # they must not be reported as measured zeros.
    spot_plates = sum(1 for r in plates if gm.norm_name(r) not in gm.PROCESS_PLATES)
    spots_painted = sum(1 for n in detected_used if n not in PROCESS_NAMES)
    spots_without_plate = sum(
        1 for n in detected_used if n not in PROCESS_NAMES and find_plate(n) == (None, False))
    gs_limit = measured_run and spot_plates >= spot_ceiling and spots_without_plate > 0
    if gs_limit:
        diags.append({
            "code": "gs_component_limit_exceeded", "severity": "warning",
            "spots_painted": spots_painted, "spot_plates_emitted": spot_plates,
        })
    has_conv = bool(converted) or "all_used" in flags or "image" in flags or gs_limit

    def stats_of(raw):
        s = dict(plates[raw])
        s.pop("duplicate", None)
        return s

    for name, info in detected_used.items():
        raw, ambiguous = find_plate(name)
        measured = None
        if ambiguous:
            diags.append({"code": "ambiguous_plate_name", "colorant": name, "severity": "warning"})
            for cand in by_norm.get(gm.norm_name(name), []):
                matched_plates.add(cand)
        elif measured_run:
            if raw is not None:
                matched_plates.add(raw)
                measured = stats_of(raw)
            elif gs_limit and name not in PROCESS_NAMES:
                measured = None
            else:
                measured = gm.empty_stats()
            if measured is not None and measured["area_any_ink_pct"] == 0:
                diags.append({"code": "painted_but_no_ink_measured", "colorant": name, "severity": "info"})
        f = set(info["flags"])
        if gs_limit and measured is None and not ambiguous:
            f.add("no_plate_gs_component_limit")
        if measured_run and has_conv and name in PROCESS_NAMES:
            f.add("includes_converted_ink")
        out_colorants.append({
            "name": name,
            "used_via": info["used_via"],
            "tint": info["tint"],
            "paint": info["paint"],
            "measured": measured,
            "accuracy": _accuracy(f, info["thin_stroke_paints"], info["min_stroke_width_pt"]),
        })

    for name, info in detected_zero.items():
        raw, ambiguous = find_plate(name)
        measured = None
        if ambiguous:
            diags.append({"code": "ambiguous_plate_name", "colorant": name, "severity": "warning"})
        elif measured_run:
            if raw is not None:
                matched_plates.add(raw)
                measured = stats_of(raw)
            else:
                measured = gm.empty_stats()
        out_zero.append({"name": name, "measured": measured})

    # plates with ink that detection did not account for
    for raw, st in plates.items():
        if raw in matched_plates or st["area_any_ink_pct"] <= 0:
            continue   # an empty plate (incl. GS's default C/M/Y/K) is not usage
        is_process = gm.norm_name(raw) in gm.PROCESS_PLATES
        measured = stats_of(raw)
        if is_process and has_conv and not plates_only:
            origin = ("separation_all" if "all_used" in flags else
                      "conversion" if converted else
                      "image" if "image" in flags else "gs_component_limit")
            derived.append({"plate": raw, "origin": origin, "measured": measured})
            continue
        if not plates_only:
            diags.append({"code": "ink_on_plate_without_detected_use", "colorant": raw, "severity": "warning"})
        out_colorants.append({
            "name": raw,
            "used_via": [],
            "tint": None,
            "paint": None,
            "measured": measured,
            "accuracy": _accuracy({"detected_from_plate_only"}, 0, None),
        })

    return {
        "colorants": out_colorants,
        "zero_tint_only": out_zero,
        "derived_process_plates": derived,
        "diagnostics": diags,
    }


def _page_diagnostics(scan: dict | None) -> list[dict]:
    if scan is None:
        return []
    d: list[dict] = []
    flags = scan["flags"]
    if scan["thin_stroke_paints"] > 0:
        d.append({
            "code": "thin_strokes", "severity": "warning",
            "paints": scan["thin_stroke_paints"], "min_stroke_width_pt": scan["min_stroke_width_pt"],
        })
    if "transparency" in flags:
        d.append({"code": "transparency_used", "severity": "info"})
    for kind in ("image", "pattern", "icc", "lab", "indexed"):
        if kind in flags:
            d.append({"code": f"unvalidated_feature:{kind}", "severity": "info"})
    if "all_used" in flags:
        d.append({"code": "separation_all_used", "severity": "info"})
    if "colorant_limit" in flags:
        d.append({"code": "colorant_limit_exceeded", "severity": "warning"})
    return d


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

def page_geometry(doc, page) -> dict:
    r = page.rect
    try:
        uu_raw = doc.xref_get_key(page.xref, "UserUnit")
        user_unit = float(uu_raw[1]) if uu_raw[0] in ("int", "real") else 1.0
    except Exception:
        user_unit = 1.0
    if not (user_unit > 0):
        user_unit = 1.0
    w, h = float(r.width), float(r.height)
    box = "CropBox" if tuple(page.cropbox) != tuple(page.mediabox) else "MediaBox"
    return {
        "box": box,
        "width_pt": round(w, 3),
        "height_pt": round(h, 3),
        "area_mm2": round(w * h * user_unit * user_unit * MM_PER_PT * MM_PER_PT, 3),
        "rotation": int(page.rotation),
        "user_unit": user_unit,
    }


# --------------------------------------------------------------------------
# Page analysis
# --------------------------------------------------------------------------

def _analyze_page(doc, index: int, pdf_path: Path, workdir: Path, deadline: float) -> dict:
    page = doc[index]
    page_no = index + 1
    geo = page_geometry(doc, page)
    area_mm2 = geo["area_mm2"]
    eff_w = geo["width_pt"] * geo["user_unit"]
    eff_h = geo["height_pt"] * geo["user_unit"]
    result: dict = {"page": page_no, "status": "ok", "geometry": geo}

    too_large = False
    try:
        base = gm.plan_base_dpi(eff_w, eff_h)
    except gm.PageTooLarge:
        too_large = True
        base = {"dpi": gm.MIN_DPI, "pixel_budget_limited": True}

    # --- native + converted detection ------------------------------------
    scan = None
    diags: list[dict] = []
    try:
        scan = scan_page(doc, page, base_dpi=base["dpi"], user_unit=geo["user_unit"])
    except ScanBudgetExceeded:
        diags.append({"code": "detection_budget_exceeded", "severity": "warning"})
    except Exception:
        logger.exception("ink content scan failed on page %d", page_no)
        diags.append({"code": "detection_budget_exceeded", "severity": "warning"})
    detection = "full" if scan is not None else "plates_only"

    measurement = {
        "passes": [], "dpi_effective": None, "plate_px": None,
        "pixel_budget_limited": bool(base["pixel_budget_limited"]),
        "gs_returncode": None, "detection": detection, "peak_total_pct": None,
    }

    # --- Ghostscript measurement ------------------------------------------
    # Ghostscript defaults to 10 spot planes; ask for as many as the page's
    # detected spot colorants need (<= 32) so none is folded into CMYK.
    n_spots = None if scan is None else sum(
        1 for n in list(scan["colorants"]) + list(scan["zero_tint_only"]) if n not in PROCESS_NAMES)
    max_spots = gm.spot_plane_request(n_spots)
    plates = None
    if too_large:
        result["status"] = "failed"
        result["error"] = "page_too_large_for_pixel_budget"
    else:
        try:
            m = gm.measure_page(pdf_path, page_no, base["dpi"], workdir, area_mm2, deadline, max_spots)
            measurement["gs_returncode"] = m["gs_returncode"]
            if m["gs_returncode"] != 0:
                result["status"] = "failed"
                result["error"] = "gs_failed"
            else:
                measurement["passes"].append({"dpi": base["dpi"], "reason": "base"})
                plates, px, peak, eff_dpi = m["plates"], m["px"], m["peak_total_pct"], base["dpi"]
                if scan is not None and scan["thin_stroke_paints"] > 0:
                    second = gm.plan_thin_stroke_dpi(eff_w, eff_h, base["dpi"])
                    if second is None:
                        measurement["pixel_budget_limited"] = True
                    else:
                        if second["pixel_budget_limited"]:
                            measurement["pixel_budget_limited"] = True
                        try:
                            m2 = gm.measure_page(pdf_path, page_no, second["dpi"], workdir, area_mm2, deadline, max_spots)
                            if m2["gs_returncode"] == 0:
                                measurement["passes"].append({"dpi": second["dpi"], "reason": "thin_strokes"})
                                plates, px, peak, eff_dpi = m2["plates"], m2["px"], m2["peak_total_pct"], second["dpi"]
                        except gm.GsTimeout:
                            pass   # keep the base pass
                measurement["dpi_effective"] = eff_dpi
                measurement["plate_px"] = px
                measurement["peak_total_pct"] = peak
        except gm.GsTimeout:
            result["status"] = "skipped_timeout"

    # --- reconcile ---------------------------------------------------------
    rec = reconcile(scan, plates, max_spots or gm.GS_MAX_SPOT_PLATES)
    result["measurement"] = measurement
    result["colorants"] = rec["colorants"]
    result["painted_zero_tint_only"] = rec["zero_tint_only"]
    result["declared_but_unused"] = scan["declared_unused"] if scan else []
    result["converted_color_spaces"] = (
        [{"family": f, "paints": n} for f, n in scan["converted"].items()] if scan else []
    )
    result["derived_process_plates"] = rec["derived_process_plates"]
    result["diagnostics"] = diags + _page_diagnostics(scan) + rec["diagnostics"]
    return result


def _placeholder(page_no: int) -> dict:
    return {"page": page_no, "status": "skipped_timeout"}


# --------------------------------------------------------------------------
# Document assembly
# --------------------------------------------------------------------------

def _doc_colorants(pages: list[dict]) -> list[dict]:
    """Union of colorants across pages, ids assigned, page entries patched
    with their ids. Order: Cyan, Magenta, Yellow, Black first, then first
    paint order — ordering only, no classification."""
    order: list[str] = []          # normalised keys, first-seen
    info: dict[str, dict] = {}

    def touch(name, page_no, families):
        k = gm.norm_name(name)
        e = info.get(k)
        if e is None:
            e = {"name": name, "families": [], "pages": []}
            info[k] = e
            order.append(k)
        for f in families:
            if f not in e["families"]:
                e["families"].append(f)
        if page_no not in e["pages"]:
            e["pages"].append(page_no)

    for p in pages:
        for c in p.get("colorants", []):
            touch(c["name"], p["page"], [v["family"] for v in c["used_via"]])
        for c in p.get("painted_zero_tint_only", []):
            touch(c["name"], p["page"], [])

    proc = [k for k in order if info[k]["name"] in PROCESS_NAMES]
    proc.sort(key=lambda k: PROCESS_NAMES.index(info[k]["name"]))
    rest = [k for k in order if k not in proc]
    final = proc + rest
    ids = {k: f"c{i}" for i, k in enumerate(final)}
    for p in pages:
        for c in p.get("colorants", []):
            c["id"] = ids[gm.norm_name(c["name"])]
        for c in p.get("painted_zero_tint_only", []):
            c["id"] = ids[gm.norm_name(c["name"])]
    out = []
    for k in final:
        e = info[k]
        out.append({"id": ids[k], "name": e["name"], "families": e["families"], "pages": e["pages"]})
    return out


def _assemble(page_count: int, selected: list[int], truncated: bool, pages: list[dict],
              gs_ver: str, t0: float) -> dict:
    ok = sum(1 for p in pages if p["status"] == "ok")
    return {
        "schema_version": SCHEMA_VERSION,
        "document": {
            "page_count": page_count,
            "pages_analyzed": ok,
            "truncated": truncated,
            "complete": ok == len(selected) and len(pages) == len(selected),
            "engine": {
                "method": METHOD,
                "gs_version": gs_ver,
                "pymupdf": pymupdf.version[0],
                "analysis_ms": int((time.monotonic() - t0) * 1000),
            },
            "colorants": _doc_colorants(pages),
        },
        "pages": pages,
    }


def select_pages(page_count: int, requested: list[int] | None) -> tuple[list[int], bool]:
    """-> (1-based page numbers to analyse, truncated)."""
    if requested:
        seen, sel = set(), []
        for p in requested:
            if 1 <= p <= page_count and p not in seen:
                seen.add(p)
                sel.append(p)
        if not sel:
            raise InkError("invalid_pages", "No requested page exists in this document.")
    else:
        sel = list(range(1, page_count + 1))
    truncated = len(sel) > MAX_PAGES
    return sel[:MAX_PAGES], truncated


def analyze_ink_coverage(pdf_bytes: bytes, opts: dict | None = None, progress=None) -> dict:
    """opts: pages (list[int] | None), deadline_s (default 55),
    workdir (Path | None). progress(result_dict) is called after every page
    with a complete, valid response (unfinished pages as skipped_timeout)."""
    opts = opts or {}
    t0 = time.monotonic()
    deadline = t0 + float(opts.get("deadline_s", TOTAL_DEADLINE_S))

    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise InkError("file_too_large", "File too large.")
    if b"%PDF" not in pdf_bytes[:1024]:
        raise InkError("invalid_pdf", "File is not a valid or readable PDF.")
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        raise InkError("invalid_pdf", "File is not a valid or readable PDF.")
    try:
        if doc.needs_pass or doc.is_encrypted:
            raise InkError("encrypted_pdf", "PDF is password-protected.")
        page_count = doc.page_count
        if page_count < 1:
            raise InkError("invalid_pdf", "File is not a valid or readable PDF.")
        selected, truncated = select_pages(page_count, opts.get("pages"))
        gs_ver = gm.gs_version()

        own_tmp = None
        workdir = opts.get("workdir")
        if workdir is None:
            own_tmp = tempfile.TemporaryDirectory(prefix="boxcheck-ink-")
            workdir = own_tmp.name
        workdir = Path(workdir)
        try:
            # GS 9.55 mishandles Optional Content; force every OCG on
            # (also what detection assumes: all layers visible).
            from spot_separations import _maybe_flatten_ocgs
            try:
                flat = _maybe_flatten_ocgs(pdf_bytes, doc[0])
            except Exception:
                flat = pdf_bytes
            pdf_path = workdir / "input.pdf"
            pdf_path.write_bytes(flat)

            pages: list[dict] = []

            def snapshot():
                done = {p["page"] for p in pages}
                full = pages + [_placeholder(n) for n in selected if n not in done]
                full.sort(key=lambda p: selected.index(p["page"]))
                return _assemble(page_count, selected, truncated, full, gs_ver, t0)

            for n in selected:
                if time.monotonic() >= deadline - 1.0:
                    break
                pages.append(_analyze_page(doc, n - 1, pdf_path, workdir, deadline))
                if progress is not None:
                    progress(snapshot())
            return snapshot()
        finally:
            if own_tmp is not None:
                own_tmp.cleanup()
    finally:
        doc.close()
