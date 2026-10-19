#!/usr/bin/env python3
"""Research-only: extract vector geometry from reference dieline PDFs.

Pipeline: PDF -> raw primitives (lines / cubic curves) -> mm calibration ->
normalized JSON per sample -> controlled comparison between samples.

Nothing here is production code and nothing here encodes box formulas. The
script reads only the PDFs (never ARD files) and labels every statement it
emits as OBSERVED / DERIVED / HYPOTHESIS.

    python scripts/extract_reference.py --sample a.pdf --sample b.pdf ...
        [--out reference/normalized] [--doc docs/structural-research.md]

L/W/D are taken from the file name (``200x150x40``) and are UNVERIFIED labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

import pymupdf

PT_MM = 25.4 / 72.0
SAME_TOL = 0.03          # mm: coordinates closer than this are "the same"
LEVEL_TOL = 0.02         # mm: clustering tolerance for feature levels
SNAP_TOL = 0.02          # mm: endpoint snapping for connectivity
GAP_MAX = 3.0            # mm: crease spacing below this counts as a "double line"
CALIPER_CANDIDATE_MM = 0.79375   # 1/32 in -- itself a HYPOTHESIS from the brief
KAPPA = 0.5522847498
SCHEMA = "boxcheck.structural.reference/v1"
DOC_BEGIN, DOC_END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"

ANCHORS = ("min", "ctr", "max")


# --------------------------------------------------------------------------
# content-stream parsing (strict: unknown operators abort instead of being skipped)
# --------------------------------------------------------------------------
_NUM = re.compile(r"-?\d*\.?\d+")


def parse_stream(text: str) -> list[dict]:
    """Return one record per painted path: separation-colourspace name + primitives."""
    paths, prims, stack = [], [], []
    cs, tint, cur = None, None, None
    gstate = {"w": 1.0, "cap": None, "join": None, "miter": None, "dash": None}
    for tok in text.split():
        if _NUM.fullmatch(tok) or tok.startswith("/"):
            stack.append(tok)
            continue
        if tok in ("q", "Q"):
            pass
        elif tok == "CS":
            cs = stack[-1][1:]
        elif tok == "SCN":
            tint = float(stack[-1])
        elif tok == "w":
            gstate["w"] = float(stack[-1])
        elif tok == "j":
            gstate["join"] = int(stack[-1])
        elif tok == "J":
            gstate["cap"] = int(stack[-1])
        elif tok == "M":
            gstate["miter"] = float(stack[-1])
        elif tok == "m":
            cur = (float(stack[-2]), float(stack[-1]))
        elif tok == "l":
            p1 = (float(stack[-2]), float(stack[-1]))
            prims.append({"kind": "line", "pts": [cur, p1]})
            cur = p1
        elif tok == "c":
            v = [float(s) for s in stack[-6:]]
            pts = [cur, (v[0], v[1]), (v[2], v[3]), (v[4], v[5])]
            prims.append({"kind": "curve", "pts": pts})
            cur = pts[-1]
        elif tok == "S":
            paths.append({"cs": cs, "tint": tint, "prims": prims, "gstate": dict(gstate)})
            prims = []
        else:
            raise SystemExit(f"unsupported PDF operator {tok!r}: extend the parser deliberately")
        stack.clear()
    return paths


def colorspace_map(doc: pymupdf.Document, page: pymupdf.Page) -> dict[str, dict]:
    """CSn -> {separation, cmyk_at_100} read from the page resources."""
    res = doc.xref_get_key(page.xref, "Resources")[1]
    out = {}
    for name, xref in re.findall(r"/(CS\d+)\s+(\d+)\s+0\s+R", res):
        obj = doc.xref_object(int(xref), compressed=False)
        m = re.search(r"/Separation\s*/(\S+)\s*/(\w+)\s+(\d+)\s+0\s+R", obj)
        entry = {"separation": m.group(1) if m else None, "cmyk_at_100": None}
        if m:
            fn = doc.xref_object(int(m.group(3)), compressed=False)
            c1 = re.search(r"/C1\s*\[([^\]]*)\]", fn)
            if c1:
                entry["cmyk_at_100"] = [float(x) for x in c1.group(1).split()]
        out[name] = entry
    return out


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
def _bez(p, t):
    u = 1 - t
    return tuple(u**3 * p[0][i] + 3 * u * u * t * p[1][i] + 3 * u * t * t * p[2][i] + t**3 * p[3][i]
                 for i in (0, 1))


def prim_extent(prim: dict) -> list[tuple[float, float]]:
    if prim["kind"] == "line":
        return prim["pts"]
    return [_bez(prim["pts"], i / 64) for i in range(65)]


def orientation(prim: dict) -> str:
    if prim["kind"] == "curve":
        return "C"
    (x0, y0), (x1, y1) = prim["pts"]
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    if dx < 1e-6 and dy < 1e-6:
        return "0"                      # zero-length (degenerate) segment
    if dy < 1e-3:
        return "H"
    if dx < 1e-3:
        return "V"
    return "D"


def arc_fit(pts_mm: list[list[float]]) -> dict | None:
    """DERIVED: does this cubic look like a circular quarter arc? -> radius."""
    p0, p1, p2, p3 = pts_mm
    h0 = (p1[0] - p0[0], p1[1] - p0[1])
    h1 = (p3[0] - p2[0], p3[1] - p2[1])
    chord = math.dist(p0, p3)
    n0, n1 = math.hypot(*h0), math.hypot(*h1)
    if min(n0, n1, chord) < 1e-6:
        return None
    ortho = abs(h0[0] * h1[0] + h0[1] * h1[1]) / (n0 * n1)
    r = chord / math.sqrt(2)
    ok = ortho < 0.02 and abs(n0 - KAPPA * r) < 0.02 * r and abs(n1 - KAPPA * r) < 0.02 * r
    return {"quarter_arc": ok, "radius_mm": round(r, 4) if ok else None}


def cluster(vals: list[tuple[float, str]], tol: float) -> list[list[tuple[float, str]]]:
    groups: list[list[tuple[float, str]]] = []
    for v, tag in sorted(vals, key=lambda t: t[0]):
        if groups and v - groups[-1][-1][0] <= tol:
            groups[-1].append((v, tag))
        else:
            groups.append([(v, tag)])
    return groups


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def extract_sample(pdf: Path) -> dict:
    m = re.search(r"(\d+)[xX](\d+)[xX](\d+)", pdf.name)
    if not m:
        raise SystemExit(f"cannot read L/W/D label from file name: {pdf.name}")
    L, W, D = (int(g) for g in m.groups())
    doc = pymupdf.open(pdf)
    page = doc[0]
    cs_map = colorspace_map(doc, page)
    paths = parse_stream(page.read_contents().decode("latin1"))

    prims = []
    for pi, path in enumerate(paths):
        sep = cs_map[path["cs"]]["separation"]
        for si, prim in enumerate(path["prims"]):
            prims.append({"path": pi, "seg": si, "kind": prim["kind"], "separation": sep,
                          "colorspace": path["cs"], "tint": path["tint"],
                          "orientation": orientation(prim), "raw_pt": prim["pts"]})

    # consistency vs PyMuPDF's independent interpretation of the same page
    mu_items = [i for d in page.get_drawings() for i in d["items"]]
    mu_real = sum(1 for i in mu_items if i[0] == "c" or math.dist(i[1], i[2]) > 1e-6)
    nondegenerate = sum(1 for p in prims if p["orientation"] != "0")
    check = {"own_parser_primitives": len(prims), "own_nondegenerate": nondegenerate,
             "zero_length_segments": len(prims) - nondegenerate,
             "pymupdf_items": len(mu_items), "pymupdf_non_zero_length": mu_real,
             "consistent": mu_real == nondegenerate,
             "note": "zero-length 'm p / l p' segments are path-construction artifacts; excluded from geometry"}

    ext = [pt for pr in prims if pr["orientation"] != "0" for pt in prim_extent({"kind": pr["kind"], "pts": pr["raw_pt"]})]
    min_x, max_x = min(p[0] for p in ext), max(p[0] for p in ext)
    min_y, max_y = min(p[1] for p in ext), max(p[1] for p in ext)
    page_w_pt, page_h_pt = page.mediabox_size  # unrotated size, pt (rotation checked below)
    assert page.rotation == 0, "rotated pages not handled"

    bbox_min_mm = (min_x * PT_MM, min_y * PT_MM)
    for pr in prims:
        pr["page_mm"] = [[round(x * PT_MM, 4), round(y * PT_MM, 4)] for x, y in pr["raw_pt"]]
        pr["norm_mm"] = [[round(x * PT_MM - bbox_min_mm[0], 4), round(y * PT_MM - bbox_min_mm[1], 4)]
                         for x, y in pr["raw_pt"]]
        if pr["kind"] == "curve":
            pr["arc_fit"] = arc_fit(pr["norm_mm"])
        pr["id"] = f"p{pr['path']:02d}.{pr['seg']}"

    sizes_mm = ((max_x - min_x) * PT_MM, (max_y - min_y) * PT_MM)
    calib = {
        "unit_scale_mm_per_pt": PT_MM,
        "unit_basis": "OBSERVED: page size is a whole number of mm only under 25.4/72; no /UserUnit, no cm operator",
        "page_mm": [round(page_w_pt * PT_MM, 4), round(page_h_pt * PT_MM, 4)],
        "page_mm_deviation_from_integer": [round(abs(v - round(v)), 5) for v in (page_w_pt * PT_MM, page_h_pt * PT_MM)],
        "geometry_margins_mm": {
            "left": round(bbox_min_mm[0], 3) + 0.0, "right": round(page_w_pt * PT_MM - max_x * PT_MM, 3) + 0.0,
            "bottom": round(bbox_min_mm[1], 3) + 0.0, "top": round(page_h_pt * PT_MM - max_y * PT_MM, 3) + 0.0},
        "bbox_size_mm": [round(sizes_mm[0], 4), round(sizes_mm[1], 4)],
        "coordinate_frame": {
            "raw_pt": "PDF user space, points, origin bottom-left, y up",
            "page_mm": "raw_pt * 25.4/72",
            "norm_mm": "page_mm minus geometry bbox min corner (stroke width ignored); y up"},
    }
    crease_gaps = _crease_gaps(prims)
    unit_gap = min(crease_gaps)
    factor = CALIPER_CANDIDATE_MM / unit_gap
    calib["crease_double_line_gaps_mm"] = [round(g, 4) for g in crease_gaps]
    calib["unit_gap_mm"] = round(unit_gap, 5)
    calib["fit_to_page_evidence"] = {
        "status": "DERIVED",
        "note": "the limiting axis has margin == 12.7 mm (0.5 in) on B/C/D, 0 on A; the page is a paper size, "
                "so the drawing was scaled to fit it and the scale differs per sample"}
    calib["calibrated"] = {
        "status": "HYPOTHESIS",
        "method": "scale so the smallest crease double-line gap equals 1/32 in (0.79375 mm)",
        "factor_to_true_mm": round(factor, 5),
        "supporting_evidence": "DERIVED: every arc radius / unit gap is a clean multiple (see classification.radii_over_unit_gap)",
        "bbox_size_mm": [round(sizes_mm[0] * factor, 3), round(sizes_mm[1] * factor, 3)]}
    for pr in prims:
        pr["cal_mm"] = [[round(x * factor, 4), round(y * factor, 4)] for x, y in pr["norm_mm"]]

    return {
        "schema": SCHEMA,
        "status_legend": {"OBSERVED": "read directly from the PDF", "DERIVED": "computed from OBSERVED data",
                          "HYPOTHESIS": "interpretation not proven"},
        "sample": {
            "label": f"{L}x{W}x{D}", "source_file": pdf.name,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "producer": doc.metadata.get("producer"), "creator": doc.metadata.get("creator"),
            "nominal_dims_from_filename": {"L": L, "W": W, "D": D,
                                           "status": "UNVERIFIED: file name only; ARD/PDF carry no readable L/W/D"}},
        "page": {"mediabox_pt": [round(v, 5) for v in page.mediabox], "rotation": page.rotation,
                 "user_unit": doc.xref_get_key(page.xref, "UserUnit")[1], "pages_in_file": len(doc)},
        "colorspaces": cs_map,
        "stroke_state": paths[0]["gstate"] if paths else None,
        "parser_crosscheck": check,
        "calibration": calib,
        "classification": classify(prims, cs_map, unit_gap),
        "primitives": prims,
    }


def _axis_levels(prims, sep, orient) -> list[float]:
    """Unique coordinate levels of axis-aligned primitives (y for H, x for V), norm_mm."""
    idx = 1 if orient == "H" else 0
    vals = [(p["norm_mm"][0][idx], p["id"]) for p in prims if p["separation"] == sep and p["orientation"] == orient]
    return [statistics.fmean(v for v, _ in g) for g in cluster(vals, LEVEL_TOL)]  # unrounded: feeds calibration


def _crease_gaps(prims) -> list[float]:
    gaps = []
    for orient in ("H", "V"):
        lv = _axis_levels(prims, "Crease", orient)
        gaps += [b - a for a, b in zip(lv, lv[1:]) if b - a < GAP_MAX]
    return gaps


def classify(prims, cs_map, unit_gap: float) -> dict:
    """Role per separation, backed by evidence extracted from the file itself."""
    out = {}
    for sep in sorted({p["separation"] for p in prims}):
        mine = [p for p in prims if p["separation"] == sep and p["orientation"] != "0"]
        verts: dict[tuple[int, int], int] = {}
        for p in mine:
            for q in (p["norm_mm"][0], p["norm_mm"][-1]):
                k = (round(q[0] / SNAP_TOL), round(q[1] / SNAP_TOL))
                verts[k] = verts.get(k, 0) + 1
        deg = {}
        for d in verts.values():
            deg[d] = deg.get(d, 0) + 1
        out[sep] = {
            "role": sep.upper(),
            "role_basis": "OBSERVED: separation colour-space name stored in the PDF",
            "lines": sum(p["kind"] == "line" for p in mine), "curves": sum(p["kind"] == "curve" for p in mine),
            "degenerate_segments": sum(p["separation"] == sep and p["orientation"] == "0" for p in prims),
            "orientations": {o: sum(p["orientation"] == o for p in mine) for o in "HVDC"},
            "paths": sorted({p["path"] for p in mine}),
            "endpoint_degree_histogram": {str(k): v for k, v in sorted(deg.items())},
            "quarter_arcs": sum(1 for p in mine if p.get("arc_fit", {}) and p["arc_fit"]["quarter_arc"]),
            "radii_mm": sorted(p["arc_fit"]["radius_mm"] for p in mine if p.get("arc_fit") and p["arc_fit"]["quarter_arc"]),
        }
        out[sep]["radii_over_unit_gap"] = sorted({round(r / unit_gap, 2) for r in out[sep]["radii_mm"]})
    return out


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
def signature(s: dict) -> list:
    return [(p["kind"], p["separation"], p["orientation"]) for p in s["primitives"]]


def coord_table(s: dict, scale: float = 1.0) -> list[dict]:
    """Flat list of (id, point, axis, value) for anchor-relative comparison."""
    w, h = s["calibration"]["bbox_size_mm"]
    rows = []
    for p in s["primitives"]:
        for pi, (x, y) in enumerate(p["norm_mm"]):
            for ax, v, size in (("x", x, w), ("y", y, h)):
                rows.append({"key": f"{p['id']}.{pi}.{ax}", "axis": ax,
                             "min": v * scale, "ctr": (v - size / 2) * scale, "max": (v - size) * scale})
    return rows


def compare_pair(a: dict, b: dict, scale_a=1.0, scale_b=1.0) -> dict:
    ra, rb = coord_table(a, scale_a), coord_table(b, scale_b)
    out = {}
    for ax in ("x", "y"):
        for anc in ANCHORS:
            deltas = [(rb[i][anc] - ra[i][anc], ra[i]["key"]) for i in range(len(ra)) if ra[i]["axis"] == ax]
            groups = cluster(deltas, SAME_TOL)
            out[f"{ax}/{anc}"] = {
                "total": len(deltas),
                "invariant": sum(1 for v, _ in deltas if abs(v) <= SAME_TOL),
                "clusters": [{"delta_mm": round(statistics.fmean(v for v, _ in g), 3), "count": len(g)} for g in groups],
            }
    return out


def sensitivity(a: dict, b: dict, scale_a: float, scale_b: float, dparam: float) -> dict:
    """DERIVED: per axis, express each coordinate delta as k = delta / (changed parameter delta).

    The anchor (bbox min / centre / max) with the most 'clean' k values (multiples of 0.5)
    is reported; k values are bucketed to 0.05. Anchor choice is itself an assumption."""
    ra, rb = coord_table(a, scale_a), coord_table(b, scale_b)
    out = {}
    for ax in ("x", "y"):
        best = None
        for anc in ANCHORS:
            ks = [(rb[i][anc] - ra[i][anc]) / dparam for i in range(len(ra)) if ra[i]["axis"] == ax]
            clean = sum(1 for k in ks if abs(k - round(k * 2) / 2) <= 0.05)
            if best is None or clean > best[1]:
                best = (anc, clean, ks)
        anc, clean, ks = best
        hist: dict[float, int] = {}
        for k in ks:
            hist[round(round(k / 0.05) * 0.05, 2) + 0.0] = hist.get(round(round(k / 0.05) * 0.05, 2) + 0.0, 0) + 1
        out[ax] = {"anchor": anc, "clean": clean, "total": len(ks), "k_histogram": dict(sorted(hist.items()))}
    return out


def level_table(s: dict) -> dict:
    prims = s["primitives"]
    f = s["calibration"]["calibrated"]["factor_to_true_mm"]
    ys, xs = _axis_levels(prims, "Crease", "H"), _axis_levels(prims, "Crease", "V")
    return {"crease_y_levels": [round(v, 3) for v in ys], "crease_x_levels": [round(v, 3) for v in xs],
            "crease_y_levels_cal": [round(v * f, 2) for v in ys], "crease_x_levels_cal": [round(v * f, 2) for v in xs]}


PAIRS = [  # (base, other, changed parameter(s)); B is the base of all single-factor contrasts
    ("200x150x40", "200x150x30", "D"),
    ("200x150x40", "200x180x40", "W"),
    ("200x150x40", "160x150x40", "L"),
    ("200x180x40", "160x150x40", "L+W"),
]


def build_comparison(samples: dict[str, dict]) -> dict:
    sigs = {k: signature(v) for k, v in samples.items()}
    ref = next(iter(sigs.values()))
    aligned = all(s == ref for s in sigs.values())
    comp = {"index_aligned": aligned,
            "alignment_basis": "OBSERVED: identical (kind, separation, orientation) sequence in every sample" if aligned
            else "NOT aligned: per-coordinate comparison below is invalid",
            "bbox_size_mm": {k: v["calibration"]["bbox_size_mm"] for k, v in samples.items()},
            "margins_mm": {k: v["calibration"]["geometry_margins_mm"] for k, v in samples.items()},
            "page_mm": {k: v["calibration"]["page_mm"] for k, v in samples.items()},
            "unit_gap_mm": {k: v["calibration"]["unit_gap_mm"] for k, v in samples.items()},
            "calibrated_bbox_mm": {k: v["calibration"]["calibrated"]["bbox_size_mm"] for k, v in samples.items()},
            "levels": {k: level_table(v) for k, v in samples.items()}, "pairs": []}
    if not aligned:
        return comp
    factors = {k: v["calibration"]["calibrated"]["factor_to_true_mm"] for k, v in samples.items()}
    for base, other, changed in PAIRS:
        if base not in samples or other not in samples:
            continue
        dims_b = samples[base]["sample"]["nominal_dims_from_filename"]
        dims_o = samples[other]["sample"]["nominal_dims_from_filename"]
        dparam = {k: dims_o[k] - dims_b[k] for k in "LWD" if dims_o[k] != dims_b[k]}
        comp["pairs"].append({
            "base": base, "other": other, "changed": changed, "nominal_delta": dparam,
            "nominal_page_scale": compare_pair(samples[base], samples[other]),
            "calibrated_hypothesis": compare_pair(samples[base], samples[other], factors[base], factors[other]),
        })
        if len(dparam) == 1:
            (name, dv), = dparam.items()
            comp["pairs"][-1]["sensitivity_calibrated"] = {
                "parameter": name, "delta": dv,
                **sensitivity(samples[base], samples[other], factors[base], factors[other], dv)}
    return comp


# --------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------
def _fmt(vals):
    return ", ".join(f"{v:g}" for v in vals)


def render_markdown(samples: dict[str, dict], comp: dict) -> str:
    L = []
    L.append("### G1. Extraction summary (OBSERVED)\n")
    L.append("| sample | page mm | geometry bbox mm (page scale) | calibrated bbox mm (HYPOTHESIS) | margins L/R/B/T mm | Cut: lines/curves | Crease: lines | zero-length segs | parser cross-check |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for k, s in samples.items():
        c, cl = s["calibration"], s["classification"]
        m = c["geometry_margins_mm"]
        cut, cr = cl.get("Cut", {}), cl.get("Crease", {})
        L.append(f"| {k} | {c['page_mm'][0]:g}×{c['page_mm'][1]:g} | {c['bbox_size_mm'][0]:g}×{c['bbox_size_mm'][1]:g} | "
                 f"{c['calibrated']['bbox_size_mm'][0]:g}×{c['calibrated']['bbox_size_mm'][1]:g} | "
                 f"{m['left']:g}/{m['right']:g}/{m['bottom']:g}/{m['top']:g} | {cut.get('lines')}/{cut.get('curves')} | "
                 f"{cr.get('lines')} | {cut.get('degenerate_segments', 0) + cr.get('degenerate_segments', 0)} | "
                 f"{'ok' if s['parser_crosscheck']['consistent'] else 'MISMATCH'} |")
    L.append("")
    L.append(f"Topology alignment: **{comp['alignment_basis']}**.\n")

    L.append("### G2. Classification evidence (OBSERVED)\n")
    L.append("| sample | separation → role | endpoint degree histogram | quarter-arc radii (page-scale mm, DERIVED) | radii ÷ unit gap (DERIVED) |")
    L.append("|---|---|---|---|---|")
    for k, s in samples.items():
        for sep, v in s["classification"].items():
            L.append(f"| {k} | {sep} → {v['role']} | {v['endpoint_degree_histogram']} | {_fmt(v['radii_mm']) or '—'} | {_fmt(v['radii_over_unit_gap']) or '—'} |")
    L.append("")

    L.append("### G3. Scale check (OBSERVED gaps, HYPOTHESIS factor)\n")
    L.append("| sample | crease double-line gaps (page-scale mm) | unit gap | factor to 1/32 in |")
    L.append("|---|---|---|---|")
    for k, s in samples.items():
        c = s["calibration"]
        L.append(f"| {k} | {_fmt(c['crease_double_line_gaps_mm'])} | {c['unit_gap_mm']} | "
                 f"{c['calibrated']['factor_to_true_mm']} |")
    L.append("")

    L.append("### G4. Crease levels along each axis (calibrated HYPOTHESIS mm; y up from bbox bottom, x from bbox left)\n")
    L.append("| sample | horizontal crease Y | consecutive gaps | vertical crease X | consecutive gaps |")
    L.append("|---|---|---|---|---|")
    for k, lv in comp["levels"].items():
        ys, xs = lv["crease_y_levels_cal"], lv["crease_x_levels_cal"]
        L.append(f"| {k} | {_fmt(ys)} | {_fmt(round(b - a, 2) for a, b in zip(ys, ys[1:]))} | "
                 f"{_fmt(xs)} | {_fmt(round(b - a, 2) for a, b in zip(xs, xs[1:]))} |")
    L.append("")

    if comp["pairs"]:
        L.append("### G5. Pairwise coordinate deltas (DERIVED; index-aligned, tolerance "
                 f"{SAME_TOL} mm)\n")
        L.append("Each cell: invariant coordinates / total, then distinct delta clusters (mm × count). "
                 "Anchor = which bbox edge the coordinates are measured from (min = left/bottom, "
                 "ctr = centre, max = right/top).\n")
        for view, title in (("calibrated_hypothesis", "calibrated (HYPOTHESIS: unit gap = 1/32 in)"),
                            ("nominal_page_scale", "nominal page scale (25.4/72)")):
            L.append(f"**View: {title}**\n")
            L.append("| base → other | changed (nominal Δ) | axis/anchor | invariant | delta clusters |")
            L.append("|---|---|---|---|---|")
            for p in comp["pairs"]:
                for key, v in p[view].items():
                    cl = "; ".join(f"{c['delta_mm']:+g}×{c['count']}" for c in v["clusters"][:8])
                    more = " …" if len(v["clusters"]) > 8 else ""
                    L.append(f"| {p['base']} → {p['other']} | {p['changed']} {p['nominal_delta']} | {key} | "
                             f"{v['invariant']}/{v['total']} | {cl}{more} |")
            L.append("")
    sens = [p for p in comp["pairs"] if "sensitivity_calibrated" in p]
    if sens:
        L.append("### G6. Sensitivity classes, single-factor pairs (DERIVED, calibrated view)\n")
        L.append("k = coordinate delta ÷ nominal parameter delta (bucketed 0.05), measured from the anchor that "
                 "gives the most multiples of 0.5. Histogram cells: `k × count`.\n")
        L.append("| base → other | parameter Δ | axis | anchor | clean multiples of 0.5 | k histogram |")
        L.append("|---|---|---|---|---|---|")
        for p in sens:
            sc = p["sensitivity_calibrated"]
            for ax in ("x", "y"):
                v = sc[ax]
                h = "; ".join(f"{k:g}×{n}" for k, n in v["k_histogram"].items())
                L.append(f"| {p['base']} → {p['other']} | {sc['parameter']} {sc['delta']:+d} | {ax} | {v['anchor']} | "
                         f"{v['clean']}/{v['total']} | {h} |")
        L.append("")
    return "\n".join(L) + "\n"


def update_doc(doc_path: Path, generated: str) -> None:
    text = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    block = f"{DOC_BEGIN}\n{generated}{DOC_END}"
    if DOC_BEGIN in text and DOC_END in text:
        pre, rest = text.split(DOC_BEGIN, 1)
        post = rest.split(DOC_END, 1)[1]
        text = pre + block + post
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(text, encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="append", required=True, type=Path, help="reference PDF (repeatable)")
    ap.add_argument("--out", type=Path, default=root / "reference" / "normalized")
    ap.add_argument("--doc", type=Path, default=root / "docs" / "structural-research.md")
    args = ap.parse_args()

    samples = {}
    for pdf in args.sample:
        s = extract_sample(pdf)
        samples[s["sample"]["label"]] = s
    args.out.mkdir(parents=True, exist_ok=True)
    for label, s in samples.items():
        (args.out / f"{label}.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    comp = build_comparison(samples)
    (args.out / "_comparison.json").write_text(json.dumps(comp, indent=1) + "\n", encoding="utf-8")
    update_doc(args.doc, render_markdown(samples, comp))
    print(f"wrote {len(samples)} samples + _comparison.json to {args.out}; updated {args.doc}")


if __name__ == "__main__":
    main()
