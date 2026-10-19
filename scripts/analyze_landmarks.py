#!/usr/bin/env python3
"""Research-only: landmark / dependency / slot / arc / unit / topology analysis.

Input : reference/normalized/*.json (produced by extract_reference.py)
Output: reference/analysis/*.json and generated blocks in docs/structural-spec.md

Rules: no ARD data, no formulas from any proprietary source. Every coefficient
produced here is PROVISIONAL / SAMPLE-DERIVED: four samples give each of L, W, D
only two distinct values, so linearity is *not testable*, only "clean multiple
of 0.5" is.  Calibrated millimetres rest on the HYPOTHESIS recorded in
extract_reference.py (unit crease gap == 1/32 in); section C below tests it.
"""
from __future__ import annotations

import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NORM = ROOT / "reference" / "normalized"
OUT = ROOT / "reference" / "analysis"
DOC = ROOT / "docs" / "structural-spec.md"

NAMES = ("200x150x40", "200x150x30", "200x180x40", "160x150x40")   # base first
BASE = "200x150x40"
PAIR_PARAM = {"200x150x30": "D", "200x180x40": "W", "160x150x40": "L"}  # single-factor vs BASE
U_HYP = 0.79375            # 1/32 in, HYPOTHESIS
GRID = 0.25               # coefficients are tested against multiples of this
CLEAN_MM = 0.10            # |delta - snap(k)*delta_param| allowed (mm) for a "clean" coefficient
INVARIANT_TOL = 0.40       # mm: below this a coordinate is "unchanged" (calibration error ~0.1-0.3 mm)
RESID_TOL = 0.05           # mm: max residual for a PROVISIONAL model (clean fits reach ~0.01)


# --------------------------------------------------------------------------
# loading / frames
# --------------------------------------------------------------------------
def load() -> dict[str, dict]:
    out = {}
    for n in NAMES:
        d = json.loads((NORM / f"{n}.json").read_text())
        d["_prim"] = {p["id"]: p for p in d["primitives"] if p["orientation"] != "0"}
        d["_dims"] = d["sample"]["nominal_dims_from_filename"]
        d["_W"], d["_H"] = d["calibration"]["calibrated"]["bbox_size_mm"]
        out[n] = d
    return out


def xy(s: dict, pid: str, idx: int) -> tuple[float, float]:
    """(x_c, y_b): x from the symmetry axis (bbox centre), y from the bottom edge; calibrated mm."""
    x, y = s["_prim"][pid]["cal_mm"][idx]
    return x - s["_W"] / 2, y


def unit(s: dict) -> float:
    return s["calibration"]["calibrated"]["factor_to_true_mm"] * s["calibration"]["unit_gap_mm"]


# --------------------------------------------------------------------------
# coefficient fitting
# --------------------------------------------------------------------------
def snap(k: float) -> float:
    return round(k / GRID) * GRID


def fit_series(v: dict[str, float], samples: dict[str, dict]) -> dict:
    """v: sample -> value (mm).  Pair-wise coefficients vs BASE, snapped when 'clean'."""
    dims = {n: samples[n]["_dims"] for n in v}
    coef, clean = {}, True
    for other, par in PAIR_PARAM.items():
        dp = dims[other][par] - dims[BASE][par]
        k = (v[other] - v[BASE]) / dp
        coef[par] = {"raw": round(k, 3), "snapped": snap(k), "clean": abs((k - snap(k)) * dp) <= CLEAN_MM}
        clean &= coef[par]["clean"]
    res = {"coef_raw": {p: c["raw"] for p, c in coef.items()},
           "values": {n: round(v[n], 3) for n in v}}
    if not clean:
        res.update(status="UNCLEAN", note="a coefficient is off a multiple of 0.25 by more than 0.1 mm, or the fit residual exceeds 0.05 mm; linearity untestable (2 values per parameter)")
        return res
    ks = {p: c["snapped"] for p, c in coef.items()}
    off = [v[n] - sum(ks[p] * dims[n][p] for p in ks) for n in v]
    x0 = st.fmean(off)
    resid = [o - x0 for o in off]
    res.update(coef={p: ks[p] for p in ("L", "W", "D")}, intercept_mm=round(x0, 3),
               intercept_in_u=round(x0 / U_HYP, 2), max_residual_mm=round(max(abs(r) for r in resid), 3))
    res["status"] = "PROVISIONAL / SAMPLE-DERIVED" if max(abs(r) for r in resid) <= RESID_TOL else "UNCLEAN"
    return res


def dependency_label(res: dict) -> str:
    if res["status"] == "UNCLEAN":
        return "unclean"
    c = res["coef"]
    dep = [p for p in "LWD" if abs(c[p]) > 0]
    return "+".join(dep) if dep else "none"


# --------------------------------------------------------------------------
# A/B: landmarks
# --------------------------------------------------------------------------
# id: (meaning, group, primitive id, point index, axis)
LANDMARKS = {
    # --- y levels (from bottom edge)
    "Y_BOTTOM":        ("bottom edge of front flap / lower end flaps", "Y", "p09.1", 0, "y"),
    "Y_FLAP_FOLD_LO":  ("front flap fold, lower line of double crease", "Y", "p11.0", 0, "y"),
    "Y_FLAP_FOLD_HI":  ("front flap fold, upper line of double crease", "Y", "p10.0", 0, "y"),
    "Y_FRONT_FOLD":    ("front wall / floor fold (also lower side of slot)", "Y", "p08.0", 0, "y"),
    "Y_SLOT_TOP":      ("upper side of slot", "Y", "p16.4", 0, "y"),
    "Y_BACK_FOLD":     ("floor / back wall fold", "Y", "p00.0", 0, "y"),
    "Y_COVER_FOLD":    ("back wall / cover fold", "Y", "p03.0", 0, "y"),
    "Y_COVER_FLAP_BASE": ("lower cut edge of cover side flaps", "Y", "p23.0", 0, "y"),
    "Y_COVER_SIDE_STRAIGHT_END": ("end of straight outer edge of cover side flap", "Y", "p23.2", 1, "y"),
    "Y_COVER_SIDE_TIP": ("end of rounded tip of cover side flap", "Y", "p23.3", 3, "y"),
    "Y_COVER_TUCK_FOLD": ("cover / tuck flap fold", "Y", "p26.0", 0, "y"),
    "Y_TUCK_ARC_START": ("start of tuck-flap corner arc (straight side ends)", "Y", "p25.0", 1, "y"),
    "Y_TOP":           ("top edge of tuck flap", "Y", "p25.2", 0, "y"),
    # --- x levels (from symmetry axis)
    "X_LEFT_EDGE":     ("left outer edge", "X", "p09.0", 0, "x"),
    "X_FOLD_L1":       ("left end-wall fold, outer line of double crease", "X", "p06.0", 0, "x"),
    "X_FOLD_L2":       ("left end-wall fold, inner line of double crease", "X", "p14.3", 0, "x"),
    "X_FOLD_R1":       ("right end-wall fold, inner line of double crease", "X", "p15.1", 0, "x"),
    "X_FOLD_R2":       ("right end-wall fold, outer line of double crease", "X", "p15.3", 0, "x"),
    "X_RIGHT_EDGE":    ("right outer edge", "X", "p18.0", 0, "x"),
    "X_COVER_SIDE_OUT_L": ("outer edge of left cover side flap", "X", "p27.2", 0, "x"),
    "X_COVER_SIDE_OUT_R": ("outer edge of right cover side flap", "X", "p23.2", 0, "x"),
    "X_COVER_TIP_L":   ("tip of left cover side flap (end of rounded corner)", "X", "p27.3", 3, "x"),
    "X_COVER_TIP_R":   ("tip of right cover side flap (end of rounded corner)", "X", "p23.3", 3, "x"),
    "X_TUCK_ARC_END_L": ("left end of tuck-flap straight top edge", "X", "p25.3", 0, "x"),
    "X_TUCK_ARC_END_R": ("right end of tuck-flap straight top edge", "X", "p25.1", 3, "x"),
    "X_RELIEF_BOT_L":  ("left lower flap relief notch, at bottom edge", "X", "p09.2", 0, "x"),
    "X_RELIEF_TOP_L":  ("left lower flap relief notch, at fold", "X", "p09.2", 1, "x"),
    "X_SLOT_OUT_L":    ("slot outer left (arc extreme)", "S", "p16.1", 3, "x"),
    "X_SLOT_IN_L":     ("slot flat part, left end", "S", "p16.0", 1, "x"),
    "X_SLOT_IN_R":     ("slot flat part, right end", "S", "p16.0", 0, "x"),
    "X_SLOT_OUT_R":    ("slot outer right (arc extreme)", "S", "p16.5", 3, "x"),
    "X_TAB_L":         ("tab edge on bottom edge, left", "S", "p17.1", 1, "x"),
    "X_TAB_R":         ("tab edge on bottom edge, right", "S", "p17.1", 0, "x"),
}

# derived distances: id: (meaning, from, to)
DISTANCES = {
    "H_FRONT_FLAP":   ("front flap height", "Y_BOTTOM", "Y_FLAP_FOLD_LO"),
    "H_FLAP_HINGE":   ("double-crease strip above front flap", "Y_FLAP_FOLD_LO", "Y_FLAP_FOLD_HI"),
    "H_FRONT_WALL":   ("front wall height", "Y_FLAP_FOLD_HI", "Y_FRONT_FOLD"),
    "H_FLOOR":        ("floor height (Y)", "Y_FRONT_FOLD", "Y_BACK_FOLD"),
    "H_BACK_WALL":    ("back wall height", "Y_BACK_FOLD", "Y_COVER_FOLD"),
    "H_COVER":        ("cover panel height (fold to fold)", "Y_COVER_FOLD", "Y_COVER_TUCK_FOLD"),
    "H_COVER_CUT":    ("cover side-flap height (cut base to fold)", "Y_COVER_FLAP_BASE", "Y_COVER_TUCK_FOLD"),
    "H_TUCK":         ("tuck flap height", "Y_COVER_TUCK_FOLD", "Y_TOP"),
    "H_TOTAL":        ("overall height", "Y_BOTTOM", "Y_TOP"),
    "W_END_WALL_L":   ("left end wall width (edge to outer fold line)", "X_LEFT_EDGE", "X_FOLD_L1"),
    "W_END_WALL_R":   ("right end wall width", "X_FOLD_R2", "X_RIGHT_EDGE"),
    "W_FLOOR_OUT":    ("floor width between outer fold lines", "X_FOLD_L1", "X_FOLD_R2"),
    "W_FLOOR_IN":     ("floor width between inner fold lines", "X_FOLD_L2", "X_FOLD_R1"),
    "W_TOTAL":        ("overall width", "X_LEFT_EDGE", "X_RIGHT_EDGE"),
    "W_COVER_SIDE":   ("cover side flap width (fold to outer edge)", "X_FOLD_R1", "X_COVER_SIDE_OUT_R"),
    "W_TUCK_FLAT":    ("tuck flap straight top edge length", "X_TUCK_ARC_END_L", "X_TUCK_ARC_END_R"),
    "W_SLOT_OUT":     ("slot overall width", "X_SLOT_OUT_L", "X_SLOT_OUT_R"),
    "W_SLOT_IN":      ("slot flat-part width", "X_SLOT_IN_L", "X_SLOT_IN_R"),
    "W_TAB":          ("tab width on bottom edge", "X_TAB_L", "X_TAB_R"),
    "D_SLOT_HEIGHT":  ("slot height", "Y_FRONT_FOLD", "Y_SLOT_TOP"),
    "D_COVER_TIP_RISE": ("cover side flap: straight end to tip (rounded corner rise)", "Y_COVER_SIDE_STRAIGHT_END", "Y_COVER_SIDE_TIP"),
    "D_COVER_TIP_DROP": ("cover side flap: tip to fold (taper)", "Y_COVER_SIDE_TIP", "Y_COVER_TUCK_FOLD"),
    "D_TUCK_ARC_RISE": ("tuck flap: straight side end to top edge", "Y_TUCK_ARC_START", "Y_TOP"),
}


def landmark_table(samples: dict[str, dict]) -> dict:
    vals = {}
    for lid, (_, _, pid, idx, ax) in LANDMARKS.items():
        vals[lid] = {n: xy(s, pid, idx)[0 if ax == "x" else 1] for n, s in samples.items()}
    out = {"landmarks": {}, "distances": {}}
    for lid, (meaning, grp, pid, idx, ax) in LANDMARKS.items():
        fit = fit_series(vals[lid], samples)
        out["landmarks"][lid] = {"meaning": meaning, "primitive": pid, "point_index": idx,
                                 "frame": "x_c (from symmetry axis)" if ax == "x" else "y_b (from bottom edge)",
                                 "depends_on": dependency_label(fit), **fit}
    for did, (meaning, a, b) in DISTANCES.items():
        v = {n: abs(vals[b][n] - vals[a][n]) for n in samples}
        fit = fit_series(v, samples)
        out["distances"][did] = {"meaning": meaning, "between": [a, b], "depends_on": dependency_label(fit), **fit}
    return out


# --------------------------------------------------------------------------
# C: directional behaviour over *all* coordinates
# --------------------------------------------------------------------------
def directional(samples: dict[str, dict]) -> dict:
    base = samples[BASE]
    out = {}
    for other, par in PAIR_PARAM.items():
        s = samples[other]
        dp = s["_dims"][par] - base["_dims"][par]
        res = {"parameter": par, "delta": dp, "x": {}, "y": {}}
        for axn, ai in (("x", 0), ("y", 1)):
            inv, clean, unclean, small, ctrl = [], [], [], [], []
            for pid, pb in base["_prim"].items():
                po = s["_prim"][pid]
                for i, (qb, qo) in enumerate(zip(pb["cal_mm"], po["cal_mm"])):
                    vb = qb[ai] - (base["_W"] / 2 if ai == 0 else 0)
                    vo = qo[ai] - (s["_W"] / 2 if ai == 0 else 0)
                    d = vo - vb
                    rec = {"id": f"{pid}.{i}", "kind": pb["kind"], "sep": pb["separation"], "delta_mm": round(d, 3)}
                    if pb["kind"] == "curve" and i in (1, 2):      # Bézier handles: reported separately, never "clean"
                        ctrl.append(rec)
                        continue
                    if abs(d) <= INVARIANT_TOL:
                        inv.append(rec)
                        if abs(d) > 0.05:
                            small.append(rec)
                    else:
                        k = d / dp
                        rec["k"] = round(k, 3)
                        (clean if abs(d - snap(k) * dp) <= CLEAN_MM else unclean).append(rec)
            kh: dict[float, int] = {}
            for r in clean:
                kh[snap(r["k"])] = kh.get(snap(r["k"]), 0) + 1
            res[axn] = {
                "total": len(inv) + len(clean) + len(unclean), "invariant": len(inv),
                "max_abs_delta_among_invariant_mm": max((abs(r["delta_mm"]) for r in inv), default=0),
                "clean_moving": len(clean), "clean_k_histogram": dict(sorted(kh.items())),
                "bezier_handles": {"total": len(ctrl), "unchanged": sum(abs(r["delta_mm"]) <= INVARIANT_TOL for r in ctrl),
                                   "max_abs_delta_mm": max((abs(r["delta_mm"]) for r in ctrl), default=0)},
                "small_movers_0p05_to_0p4_mm": small,
                "unclean": len(unclean),
                "unclean_paths": sorted({r["id"].split(".")[0] for r in unclean}),
                "unclean_points": [r for r in unclean],
            }
        out[f"{BASE}->{other}"] = res
    return out


# --------------------------------------------------------------------------
# F: unit / crease analysis
# --------------------------------------------------------------------------
def unit_analysis(samples: dict[str, dict]) -> dict:
    g = {n: s["calibration"]["unit_gap_mm"] for n, s in samples.items()}
    out = {"unit_gap_page_mm": g, "estimates": {}, "candidates": {}, "checks": {}}
    # independent estimate of the true unit per single-factor pair (uses file-name deltas as truth)
    base = samples[BASE]
    pair_est = {}
    for other, par in PAIR_PARAM.items():
        s = samples[other]
        dp = s["_dims"][par] - base["_dims"][par]
        est = []
        for pid, pb in base["_prim"].items():
            po = s["_prim"][pid]
            for qb, qo in zip(pb["norm_mm"], po["norm_mm"]):
                for ai in (0, 1):
                    d_units = qo[ai] / g[other] - qb[ai] / g[BASE]     # coordinate difference in "page unit gaps"
                    if abs(d_units) < 1:
                        continue
                    k = d_units * U_HYP / dp
                    if abs(k - snap(k)) > 0.08 or snap(k) == 0:
                        continue
                    est.append((snap(k) * dp / d_units, snap(k)))
        vals = [e for e, _ in est]
        pair_est[par] = {"n": len(vals), "median_mm": round(st.median(vals), 5),
                         "q1_q3_mm": [round(q, 5) for q in (st.quantiles(vals, n=4)[0], st.quantiles(vals, n=4)[2])]}
    out["estimates"] = {"method": "unit u such that k*Δparam = u*(coord diff in page unit gaps); Δparam from file names (UNVERIFIED)",
                        "per_pair": pair_est}
    allv = [pair_est[p]["median_mm"] for p in pair_est]
    out["estimates"]["spread_of_pair_medians_mm"] = round(max(allv) - min(allv), 5)
    for cand in (0.79, 0.79375, 0.794, 0.8):
        out["candidates"][str(cand)] = {p: round(pair_est[p]["median_mm"] / cand - 1, 5) for p in pair_est}
    # internal consistency of the unit in every sample
    for n, s in samples.items():
        arcs = [p["arc_fit"]["radius_mm"] for p in s["_prim"].values() if p["kind"] == "curve" and p.get("arc_fit") and p["arc_fit"]["quarter_arc"]]
        slot_h = abs(xy(s, "p16.4", 0)[1] - xy(s, "p08.0", 0)[1])
        out["checks"][n] = {"unit_gap_mm_page": g[n],
                            "smallest_arc_radius_over_unit": round(min(arcs) / g[n], 4),
                            "slot_height_over_unit": round(slot_h / unit(s), 3),
                            "double_crease_strip_over_unit": round(abs(xy(s, "p10.0", 0)[1] - xy(s, "p11.0", 0)[1]) / unit(s), 3)}
    return out


# --------------------------------------------------------------------------
# D: slot
# --------------------------------------------------------------------------
def slot_analysis(samples: dict[str, dict]) -> dict:
    rows = {}
    for n, s in samples.items():
        ol, il = xy(s, "p16.1", 3)[0], xy(s, "p16.0", 1)[0]
        ir, orr = xy(s, "p16.0", 0)[0], xy(s, "p16.5", 3)[0]
        tl, tr = xy(s, "p17.1", 1)[0], xy(s, "p17.1", 0)[0]
        yb = xy(s, "p16.0", 0)[1]
        rows[n] = {"L": s["_dims"]["L"], "W": s["_dims"]["W"], "D": s["_dims"]["D"],
                   "outer_left_xc": round(ol, 3), "outer_right_xc": round(orr, 3),
                   "center_xc": round((ol + orr) / 2, 3), "outer_width": round(orr - ol, 3),
                   "flat_width": round(ir - il, 3), "tab_width": round(tr - tl, 3),
                   "height": round(xy(s, "p16.4", 0)[1] - yb, 3),
                   "y_bottom_minus_front_fold": round(yb - xy(s, "p08.0", 0)[1], 3),
                   "floor_width_out": round(abs(xy(s, "p15.3", 0)[0] - xy(s, "p06.0", 0)[0]), 3),
                   "unit_mm": round(unit(s), 4)}
    ow = {n: rows[n]["outer_width"] for n in rows}
    return {"per_sample": rows,
            "outer_width_by_L": {str(L): sorted({round(r["outer_width"], 2) for r in rows.values() if r["L"] == L}) for L in (160, 200)},
            "fit_outer_edge_left": fit_series({n: rows[n]["outer_left_xc"] for n in rows}, samples),
            "fit_outer_edge_right": fit_series({n: rows[n]["outer_right_xc"] for n in rows}, samples),
            "fit_outer_width": fit_series(ow, samples),
            "fit_flat_width": fit_series({n: rows[n]["flat_width"] for n in rows}, samples)}


# --------------------------------------------------------------------------
# E: rounded geometry (every cubic)
# --------------------------------------------------------------------------
ARC_ROLE = {"p16.1": "slot end (lower-left)", "p16.3": "slot end (upper-left)", "p16.5": "slot end (upper-right)",
            "p16.7": "slot end (lower-right)", "p23.1": "cover side flap base corner (R)", "p27.1": "cover side flap base corner (L)",
            "p23.3": "cover side flap rounded tip (R)", "p27.3": "cover side flap rounded tip (L)",
            "p25.1": "tuck flap corner (R)", "p25.3": "tuck flap corner (L)"}


def circle_fit(c: list[list[float]]) -> dict:
    p0, p1, p2, p3 = c
    d0 = (p1[0] - p0[0], p1[1] - p0[1]); d1 = (p3[0] - p2[0], p3[1] - p2[1])
    n0, n1 = math.hypot(*d0), math.hypot(*d1)
    chord = math.dist(p0, p3)
    cosang = max(-1, min(1, (d0[0] * d1[0] + d0[1] * d1[1]) / (n0 * n1)))
    sweep = math.acos(cosang)
    r = chord / (2 * math.sin(sweep / 2))
    h = 4 / 3 * math.tan(sweep / 4) * r
    return {"radius_mm": round(r, 3), "sweep_deg": round(math.degrees(sweep), 2),
            "handle_ratio": [round(n0 / h, 3), round(n1 / h, 3)],
            "circular": abs(n0 / h - 1) < 0.03 and abs(n1 / h - 1) < 0.03}


def arc_analysis(samples: dict[str, dict]) -> dict:
    out = {}
    for pid, role in ARC_ROLE.items():
        per = {}
        for n, s in samples.items():
            c = s["_prim"][pid]["cal_mm"]
            f = circle_fit(c)
            dx, dy = abs(c[3][0] - c[0][0]), abs(c[3][1] - c[0][1])
            f["extent_radius_mm"] = round((dx + dy) / 2, 3) if abs(dx - dy) < 0.05 else None
            f.update(start_xc_yb=[round(c[0][0] - s["_W"] / 2, 3), round(c[0][1], 3)],
                     end_xc_yb=[round(c[3][0] - s["_W"] / 2, 3), round(c[3][1], 3)],
                     radius_over_unit=round(f["radius_mm"] / unit(s), 3),
                     radius_over_half_D=round(f["radius_mm"] / (s["_dims"]["D"] / 2), 4),
                     floor_candidate_u=None)
            per[n] = f
        rs = {n: per[n]["radius_mm"] for n in per}
        out[pid] = {"role": role, "per_sample": per, "radius_fit": fit_series(rs, samples)}
    # test of a *hypothesis* (not a formula): tuck corner radius == floor((D/2)/u)*u ?
    test = {}
    for n, s in samples.items():
        u = unit(s)
        r = out["p25.1"]["per_sample"][n]["extent_radius_mm"]
        half = s["_dims"]["D"] / 2
        test[n] = {"D_half_over_u": round(half / u, 3), "radius_over_u": round(r / u, 3),
                   "floor_matches": round(r / u, 1) == math.floor(half / u), "round_matches": round(r / u, 1) == round(half / u)}
    out["_tuck_radius_floor_test"] = test
    out["_cover_tip_table"] = {}
    for n, s in samples.items():
        fx, fy = xy(s, "p24.0", 0)[0], xy(s, "p26.0", 0)[1]        # fold corner of the right cover side flap
        tx, ty = xy(s, "p23.3", 3)
        sx, sy = xy(s, "p23.2", 1)
        f = out["p23.3"]["per_sample"][n]
        r_t = out["p25.1"]["per_sample"][n]["extent_radius_mm"]        # tuck corner radius (tangent-length)
        al = math.atan2(fy - ty, tx - fx)
        out["_cover_tip_table"][n] = {"tuck_radius_mm": r_t,
                                      "pred_run_mm": round(s["_dims"]["D"] + unit(s) * 0.0 - r_t * (1 - math.sin(al)), 3),
                                      "pred_rise_mm": round(r_t * math.cos(al), 3),
                                      "tan_taper_times_W": round(math.tan(al) * s["_dims"]["W"], 3),
                                      "tan_taper_times_W_over_Dminus10": round(math.tan(al) * s["_dims"]["W"] / (s["_dims"]["D"] - 10), 4),"W": s["_dims"]["W"], "D": s["_dims"]["D"], "L": s["_dims"]["L"],
                                      "run_mm": round(tx - fx, 3), "drop_mm": round(fy - ty, 3),
                                      "taper_deg": round(math.degrees(math.atan2(fy - ty, tx - fx)), 3),
                                      "rise_mm": round(ty - sy, 3), "arc_radius_mm": f["radius_mm"], "arc_sweep_deg": f["sweep_deg"]}
    return out


# --------------------------------------------------------------------------
# G: topology
# --------------------------------------------------------------------------
PANEL_DEFS = {   # (x_lo, x_hi, y_lo, y_hi) landmark ids (x_c / y_b frames)
    "FRONT_FLAP":      ("X_FOLD_L2", "X_FOLD_R1", "Y_BOTTOM", "Y_FLAP_FOLD_LO"),
    "FLAP_HINGE_STRIP": ("X_FOLD_L1", "X_FOLD_R2", "Y_FLAP_FOLD_LO", "Y_FLAP_FOLD_HI"),
    "FRONT_WALL":      ("X_FOLD_L1", "X_FOLD_R2", "Y_FLAP_FOLD_HI", "Y_FRONT_FOLD"),
    "FLOOR":           ("X_FOLD_L1", "X_FOLD_R2", "Y_FRONT_FOLD", "Y_BACK_FOLD"),
    "BACK_WALL":       ("X_FOLD_L1", "X_FOLD_R2", "Y_BACK_FOLD", "Y_COVER_FOLD"),
    "COVER":           ("X_FOLD_L1", "X_FOLD_R2", "Y_COVER_FOLD", "Y_COVER_TUCK_FOLD"),
    "COVER_TUCK":      ("X_FOLD_L2", "X_FOLD_R1", "Y_COVER_TUCK_FOLD", "Y_TOP"),
    "END_WALL_L":      ("X_LEFT_EDGE", "X_FOLD_L1", "Y_FRONT_FOLD", "Y_BACK_FOLD"),
    "END_WALL_R":      ("X_FOLD_R2", "X_RIGHT_EDGE", "Y_FRONT_FOLD", "Y_BACK_FOLD"),
    "END_LOWER_L":     ("X_LEFT_EDGE", "X_FOLD_L1", "Y_BOTTOM", "Y_FRONT_FOLD"),
    "END_LOWER_R":     ("X_FOLD_R2", "X_RIGHT_EDGE", "Y_BOTTOM", "Y_FRONT_FOLD"),
    "END_UPPER_L":     ("X_LEFT_EDGE", "X_FOLD_L1", "Y_BACK_FOLD", "Y_COVER_FOLD"),
    "END_UPPER_R":     ("X_FOLD_R2", "X_RIGHT_EDGE", "Y_BACK_FOLD", "Y_COVER_FOLD"),
    "COVER_SIDE_L":    ("X_COVER_SIDE_OUT_L", "X_FOLD_L2", "Y_COVER_FLAP_BASE", "Y_COVER_TUCK_FOLD"),
    "COVER_SIDE_R":    ("X_FOLD_R1", "X_COVER_SIDE_OUT_R", "Y_COVER_FLAP_BASE", "Y_COVER_TUCK_FOLD"),
}
PATH_ROLE = {  # semantic names for paths (checked against separation by assert)
    "p00": "floor/back-wall fold", "p01": "left slit back wall / end-upper", "p02": "left chamfer at cover base",
    "p03": "back-wall/cover fold", "p04": "right slit + chamfer back wall / end-upper", "p05": "left end-upper outline",
    "p06": "left end-wall fold (V) + end-wall/end-upper fold (H)", "p07": "left outer edge of end wall",
    "p08": "left end-wall/end-lower fold", "p09": "left end-lower flap outline", "p10": "front flap hinge, upper line",
    "p11": "front flap hinge, lower line", "p12": "front fold, right of slot", "p13": "front fold, left of slot",
    "p14": "front flap left outline + notch", "p15": "front flap right outline + notch", "p16": "slot outline",
    "p17": "tab edge on bottom", "p18": "right end-lower flap outline", "p19": "right end-wall fold (V) + end-wall/end-upper fold (H)",
    "p20": "right outer edge of end wall", "p21": "right end-wall/end-lower fold", "p22": "right end-upper outline",
    "p23": "right cover side flap outline", "p24": "right cover/cover-side fold", "p25": "tuck flap outline",
    "p26": "cover/tuck fold", "p27": "left cover side flap outline", "p28": "left cover/cover-side fold",
}


def _dps(q, a, b):
    ax, ay = a; bx, by = b; px, py = q
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) if l2 else 0
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def _flat(p, n=32):
    c = p["cal_mm"]
    if p["kind"] == "line":
        return [tuple(q) for q in c]
    return [tuple((1 - i / n) ** 3 * c[0][j] + 3 * (1 - i / n) ** 2 * (i / n) * c[1][j] +
                  3 * (1 - i / n) * (i / n) ** 2 * c[2][j] + (i / n) ** 3 * c[3][j] for j in (0, 1)) for i in range(n + 1)]


def topology(samples: dict[str, dict]) -> dict:
    tol = 0.08
    out = {"paths": {}, "crease_endpoints": {}, "panels": {}, "crease_adjacency": {}}
    # --- paths
    s0 = samples[BASE]
    paths: dict[str, list] = {}
    for pid, p in s0["_prim"].items():
        paths.setdefault(pid.split(".")[0], []).append(p)
    for path, ps in paths.items():
        seps = sorted({p["separation"] for p in ps})
        assert len(seps) == 1, path
        out["paths"][path] = {"separation": seps[0], "role": PATH_ROLE.get(path, "?"),
                              "primitives": [p["id"] for p in ps], "geometry": "".join(p["orientation"] for p in ps)}
    # --- crease endpoints vs cut geometry, every sample
    for n, s in samples.items():
        cuts = [(p["id"], _flat(p)) for p in s["_prim"].values() if p["separation"] == "Cut"]
        creases = [p for p in s["_prim"].values() if p["separation"] == "Crease"]
        tally = {"ON_CUT": 0, "ON_CUT_ENDPOINT": 0, "ON_CREASE_ONLY": 0, "FREE": 0}
        detail = []
        for p in creases:
            for end in (0, 1):
                q = tuple(p["cal_mm"][end])
                best = min((_dps(q, a, b)[0], cid, _dps(q, a, b)[1]) for cid, pl in cuts for a, b in zip(pl, pl[1:]))
                on_cut = best[0] < tol
                if on_cut:
                    cut_prim = s["_prim"][best[1]]
                    ends = (cut_prim["cal_mm"][0], cut_prim["cal_mm"][-1])
                    at_end = any(math.dist(q, e) < tol for e in ends)
                    tally["ON_CUT_ENDPOINT" if at_end else "ON_CUT"] += 1
                else:
                    other = any(o is not p and _dps(q, *o["cal_mm"])[0] < tol for o in creases)
                    tally["ON_CREASE_ONLY" if other else "FREE"] += 1
                detail.append({"crease": p["id"], "end": end, "touches_cut": best[1] if on_cut else None,
                               "at_cut_endpoint": at_end if on_cut else None})
        out["crease_endpoints"][n] = {"tally": tally, "detail": detail if n == BASE else "see BASE"}
    # --- left/right mirror symmetry about the bbox centre line (all points, all samples)
    sym = {}
    for n, s in samples.items():
        pts = [(q[0] - s["_W"] / 2, q[1]) for p in s["_prim"].values() for q in p["cal_mm"]]
        sym[n] = round(max(min(math.hypot(-x - u, y - v) for u, v in pts) for x, y in pts), 3)
    out["mirror_symmetry_max_error_mm"] = sym
    # --- panels (BASE frame) and crease adjacency
    lm = {lid: {n: xy(s, pid, idx)[0 if ax == "x" else 1] for n, s in samples.items()}
          for lid, (_, _, pid, idx, ax) in LANDMARKS.items()}
    rect = {name: (lm[a][BASE], lm[b][BASE], lm[c][BASE], lm[d][BASE]) for name, (a, b, c, d) in PANEL_DEFS.items()}
    for name, r in rect.items():
        out["panels"][name] = {"x_c": [round(r[0], 2), round(r[1], 2)], "y_b": [round(r[2], 2), round(r[3], 2)],
                               "w": round(r[1] - r[0], 2), "h": round(r[3] - r[2], 2)}

    def panel_at(x, y):
        hits = [(nm, (r[1] - r[0]) * (r[3] - r[2])) for nm, r in rect.items() if r[0] - 0.01 <= x <= r[1] + 0.01 and r[2] - 0.01 <= y <= r[3] + 0.01]
        return min(hits, key=lambda t: t[1])[0] if hits else None
    for p in s0["_prim"].values():
        if p["separation"] != "Crease":
            continue
        (xa, ya), (xb, yb) = [(q[0] - s0["_W"] / 2, q[1]) for q in p["cal_mm"]]
        mx, my = (xa + xb) / 2, (ya + yb) / 2
        off = 0.4
        a, b = ((mx, my - off), (mx, my + off)) if p["orientation"] == "H" else ((mx - off, my), (mx + off, my))
        out["crease_adjacency"][p["id"]] = [panel_at(*a), panel_at(*b)]
    return out


# --------------------------------------------------------------------------
# generated markdown
# --------------------------------------------------------------------------
def md_landmarks(L: dict) -> str:
    rows = ["| ID | meaning | prim.pt | dependency | coef L / W / D | intercept (mm, in u) | max resid mm | status |", "|---|---|---|---|---|---|---|---|"]
    for key in ("landmarks", "distances"):
        for lid, v in L[key].items():
            ref = f"{v['primitive']}.{v['point_index']}" if key == "landmarks" else "Δ " + " → ".join(v["between"])
            if v["status"] == "UNCLEAN":
                coef = "raw " + " / ".join(f"{v['coef_raw'][p]:+g}" for p in "LWD")
                rows.append(f"| {lid} | {v['meaning']} | {ref} | unclean | {coef} | — | — | DERIVED (not linear-fit) |")
            else:
                c = v["coef"]
                rows.append(f"| {lid} | {v['meaning']} | {ref} | {v['depends_on']} | {c['L']:+g} / {c['W']:+g} / {c['D']:+g} | "
                            f"{v['intercept_mm']:+g} ({v['intercept_in_u']:+g}u) | {v['max_residual_mm']} | {v['status']} |")
    return "\n".join(rows) + "\n"


def md_directional(Dr: dict) -> str:
    rows = ["| pair | axis | points | unchanged (≤0.4 mm) | max unchanged Δ mm | clean moving (k histogram) | unclean | unclean paths | Bézier handles unchanged / total |", "|---|---|---|---|---|---|---|---|---|"]
    for pair, r in Dr.items():
        for ax in ("x", "y"):
            v = r[ax]
            kh = "; ".join(f"{k:g}×{n}" for k, n in v["clean_k_histogram"].items()) or "—"
            rows.append(f"| {pair} ({r['parameter']}{r['delta']:+d}) | {ax} | {v['total']} | {v['invariant']} | {v['max_abs_delta_among_invariant_mm']} | "
                        f"{v['clean_moving']} ({kh}) | {v['unclean']} | {', '.join(v['unclean_paths']) or '—'} | {v['bezier_handles']['unchanged']} / {v['bezier_handles']['total']} |")
    return "\n".join(rows) + "\n"


def md_unit(Un: dict) -> str:
    e = Un["estimates"]["per_pair"]
    rows = ["| pair parameter | n features | median unit mm | Q1–Q3 |", "|---|---|---|---|"]
    for p, v in e.items():
        rows.append(f"| {p} | {v['n']} | {v['median_mm']} | {v['q1_q3_mm'][0]}–{v['q1_q3_mm'][1]} |")
    rows += ["", "Relative error of each pair estimate against candidate values (estimate/candidate − 1):", "",
             "| candidate mm | D pair | W pair | L pair |", "|---|---|---|---|"]
    for c, v in Un["candidates"].items():
        rows.append(f"| {c} | {v['D']:+.4%} | {v['W']:+.4%} | {v['L']:+.4%} |")
    rows += ["", "| sample | unit gap (page mm) | smallest arc r / unit gap | slot height / u | double-crease strip / u |", "|---|---|---|---|---|"]
    for n, v in Un["checks"].items():
        rows.append(f"| {n} | {v['unit_gap_mm_page']} | {v['smallest_arc_radius_over_unit']} | {v['slot_height_over_unit']} | {v['double_crease_strip_over_unit']} |")
    return "\n".join(rows) + "\n"


def md_slot(Sl: dict) -> str:
    rows = ["| sample | L | outer left x_c | outer right x_c | centre x_c | outer width | flat width | tab width | height | slot bottom − front fold |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n, r in Sl["per_sample"].items():
        rows.append(f"| {n} | {r['L']} | {r['outer_left_xc']} | {r['outer_right_xc']} | {r['center_xc']} | {r['outer_width']} | {r['flat_width']} | {r['tab_width']} | {r['height']} | {r['y_bottom_minus_front_fold']} |")
    return "\n".join(rows) + "\n"


def md_arcs(Ar: dict) -> str:
    rows = ["| prim | role | sample | Bézier-fit radius mm | r / u | tangent-length radius mm | sweep ° | circular? | r / (D/2) |", "|---|---|---|---|---|---|---|---|---|"]
    for pid, v in Ar.items():
        if pid.startswith("_"):
            continue
        for n, f in v["per_sample"].items():
            rows.append(f"| {pid} | {v['role']} | {n} | {f['radius_mm']} | {f['radius_over_unit']} | {f['extent_radius_mm'] if f['extent_radius_mm'] is not None else '—'} | {f['sweep_deg']} | {'yes' if f['circular'] else 'NO ' + str(f['handle_ratio'])} | {f['radius_over_half_D']} |")
    rows += ["", "Tuck-corner radius vs D/2 (HYPOTHESIS test, 2 distinct D only):", "", "| sample | D/2 in u | r in u | r = floor(D/2) in u | r = round(D/2) in u |", "|---|---|---|---|---|"]
    for n, t in Ar["_tuck_radius_floor_test"].items():
        rows.append(f"| {n} | {t['D_half_over_u']} | {t['radius_over_u']} | {t['floor_matches']} | {t['round_matches']} |")
    rows += ["", "Cover side flap tip (right flap): geometry vs W, D (mm, calibrated):", "",
             "| sample | L | W | D | run to fold | drop | taper ° | rise | tip arc r | sweep ° | tuck r | pred. run = D − r(1−sinα) | pred. rise = r·cosα | tanα·W | tanα·W/(D−10) |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, t in Ar["_cover_tip_table"].items():
        rows.append(f"| {n} | {t['L']} | {t['W']} | {t['D']} | {t['run_mm']} | {t['drop_mm']} | {t['taper_deg']} | {t['rise_mm']} | {t['arc_radius_mm']} | {t['arc_sweep_deg']} | {t['tuck_radius_mm']} | {t['pred_run_mm']} | {t['pred_rise_mm']} | {t['tan_taper_times_W']} | {t['tan_taper_times_W_over_Dminus10']} |")
    return "\n".join(rows) + "\n"


def md_topology(T: dict) -> str:
    rows = ["| path | sep | role | primitives | shape |", "|---|---|---|---|---|"]
    for p, v in T["paths"].items():
        rows.append(f"| {p} | {v['separation']} | {v['role']} | {len(v['primitives'])} | {v['geometry']} |")
    rows += ["", "Crease endpoints versus Cut geometry:", "", "| sample | on cut interior | at cut endpoint | on crease only | free |", "|---|---|---|---|---|"]
    for n, v in T["crease_endpoints"].items():
        t = v["tally"]
        rows.append(f"| {n} | {t['ON_CUT']} | {t['ON_CUT_ENDPOINT']} | {t['ON_CREASE_ONLY']} | {t['FREE']} |")
    rows += ["", "Panels (BASE frame; x from symmetry axis, y from bottom edge):", "", "| panel | x range | y range | w | h |", "|---|---|---|---|---|"]
    for n, v in T["panels"].items():
        rows.append(f"| {n} | {v['x_c'][0]} … {v['x_c'][1]} | {v['y_b'][0]} … {v['y_b'][1]} | {v['w']} | {v['h']} |")
    rows += ["", "Crease adjacency (panel on each side of the crease line):", "", "| crease | panel A | panel B |", "|---|---|---|"]
    for c, (a, b) in T["crease_adjacency"].items():
        rows.append(f"| {c} | {a} | {b} |")
    return "\n".join(rows) + "\n"


def update_block(path: Path, name: str, body: str) -> None:
    b, e = f"<!-- BEGIN GEN:{name} -->", f"<!-- END GEN:{name} -->"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{b}\n{body}{e}"
    if b in text and e in text:
        pre, rest = text.split(b, 1)
        text = pre + block + rest.split(e, 1)[1]
    else:
        text = text.rstrip() + f"\n\n{block}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    samples = load()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {"landmarks": landmark_table(samples), "directional": directional(samples), "unit": unit_analysis(samples),
               "slot": slot_analysis(samples), "arcs": arc_analysis(samples), "topology": topology(samples)}
    for name, data in results.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    update_block(DOC, "landmarks", md_landmarks(results["landmarks"]))
    update_block(DOC, "directional", md_directional(results["directional"]))
    update_block(DOC, "unit", md_unit(results["unit"]))
    update_block(DOC, "slot", md_slot(results["slot"]))
    update_block(DOC, "arcs", md_arcs(results["arcs"]))
    update_block(DOC, "topology", md_topology(results["topology"]))
    print("wrote", ", ".join(f"{n}.json" for n in results), "->", OUT)


if __name__ == "__main__":
    main()
