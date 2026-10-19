"""Ink Coverage — planner, reconciliation, and Ghostscript integration."""
import json
import os
import shutil
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import ink_fixtures as fx
import ink_gs_measure as gm
from ink_coverage import InkError, analyze_ink_coverage, reconcile, select_pages

needs_gs = pytest.mark.skipif(shutil.which("gs") is None, reason="ghostscript not installed")
CORPUS = Path("/tmp/ink_validation_corpus_v1")
needs_corpus = pytest.mark.skipif(not (CORPUS / "manifest.json").exists(), reason="validation corpus not present")

TOL = 0.4   # pp at 150 dpi (corpus numbers were taken at 144 dpi with pixel-aligned edges)


def run(pdf: bytes, **opts):
    return analyze_ink_coverage(pdf, opts)


def page_colorants(r, page=0):
    return {c["name"]: c for c in r["pages"][page]["colorants"]}


def mean(r, name, page=0):
    return page_colorants(r, page)[name]["measured"]["ink_mean_pct"]


# ---- DPI / pixel-budget planning (pure) ---------------------------------------

def test_dpi_default_150_and_budget_clamp():
    assert gm.plan_base_dpi(200, 200) == {"dpi": 150.0, "pixel_budget_limited": False}
    big = gm.plan_base_dpi(2400, 2400)
    assert 72 <= big["dpi"] < 150 and big["pixel_budget_limited"]
    px = -(-2400 * big["dpi"] // 72)
    assert px * px <= gm.BASE_PIXEL_BUDGET


def test_dpi_floor_72_page_too_large():
    with pytest.raises(gm.PageTooLarge):
        gm.plan_base_dpi(14400, 14400)


def test_thin_stroke_pass_up_to_600_dpi_and_40mpx():
    assert gm.plan_thin_stroke_dpi(200, 200, 150) == {"dpi": 600.0, "pixel_budget_limited": False}
    p = gm.plan_thin_stroke_dpi(2000, 1500, 150)
    assert 150 < p["dpi"] < 600 and p["pixel_budget_limited"]
    # near the 72 dpi floor the 40 Mpx budget still allows a higher second pass
    base = gm.plan_base_dpi(4400, 4400)["dpi"]
    second = gm.plan_thin_stroke_dpi(4400, 4400, base)
    assert base < 75 and second["dpi"] > base and second["pixel_budget_limited"]
    # a second pass is skipped when it would not beat the base resolution
    assert gm.plan_thin_stroke_dpi(200, 200, 600.0) is None


def test_gs_command_is_safer_never_nosafer():
    args = gm.gs_args("gs", Path("/x/in.pdf"), 2, 150.0, Path("/x/p.tif"))
    assert "-dSAFER" in args and "-dNOSAFER" not in args
    for flag in ("-dBATCH", "-dNOPAUSE", "-dQUIET", "-dNumRenderingThreads=1", "-dUseCropBox",
                 "-dGraphicsAlphaBits=4", "-dTextAlphaBits=4", "-sDEVICE=tiffsep"):
        assert flag in args


def test_select_pages_truncates_at_10():
    sel, trunc = select_pages(25, None)
    assert sel == list(range(1, 11)) and trunc
    assert select_pages(3, None) == ([1, 2, 3], False)
    assert select_pages(5, [2, 2, 9, 4]) == ([2, 4], False)
    with pytest.raises(InkError):
        select_pages(3, [9])


# ---- reconciliation (pure) ------------------------------------------------------

def _scan(used=None, zero=None, converted=None, flags=None):
    def info(name, family="Separation", tmax=1.0):
        return {"name": name, "families": [family],
                "used_via": [{"family": family, "devicen_group": None, "paints": 1}],
                "tint": {"min": tmax, "max": tmax}, "tint_unknown": False,
                "paint": {"sources": ["path"], "overprint_paints": 0, "knockout_paints": 1, "opm": [0]},
                "thin_stroke_paints": 0, "min_stroke_width_pt": None, "flags": []}
    return {"colorants": {n: info(n) for n in (used or [])},
            "zero_tint_only": {n: info(n, tmax=0.0) for n in (zero or [])},
            "declared_unused": [], "converted": converted or {}, "flags": set(flags or []),
            "thin_stroke_paints": 0, "min_stroke_width_pt": None}


def _plate(mean_pct, area=None):
    return {"ink_mean_pct": mean_pct, "area_any_ink_pct": mean_pct if area is None else area,
            "max_ink_pct": 100.0, "mean_ink_on_inked_area_pct": 100.0,
            "full_ink_equivalent_mm2": 1.0, "duplicate": False}


def codes(rec):
    return [(d["code"], d.get("colorant")) for d in rec["diagnostics"]]


def test_reconcile_default_empty_cmyk_plates_are_not_usage():
    rec = reconcile(_scan(used=["Spot A"]),
                    {"Cyan": _plate(0), "Magenta": _plate(0), "Yellow": _plate(0), "Black": _plate(0),
                     "Spot A": _plate(10)})
    assert [c["name"] for c in rec["colorants"]] == ["Spot A"]
    assert rec["derived_process_plates"] == [] and rec["diagnostics"] == []


def test_reconcile_used_but_zero_ink():
    rec = reconcile(_scan(used=["Offpage"]), {"Cyan": _plate(0)})
    assert ("painted_but_no_ink_measured", "Offpage") in codes(rec)
    assert rec["colorants"][0]["measured"]["ink_mean_pct"] == 0


def test_reconcile_plate_with_ink_but_no_detected_use():
    rec = reconcile(_scan(used=[]), {"Mystery": _plate(5)})
    assert ("ink_on_plate_without_detected_use", "Mystery") in codes(rec)
    c = rec["colorants"][0]
    assert c["name"] == "Mystery" and c["used_via"] == [] and c["accuracy"]["level"] == "unvalidated"


def test_reconcile_converted_process_ink_is_derived_not_native():
    rec = reconcile(_scan(converted={"DeviceRGB": 1}),
                    {"Cyan": _plate(2), "Black": _plate(0)})
    assert rec["colorants"] == []
    assert rec["derived_process_plates"] == [
        {"plate": "Cyan", "origin": "conversion", "measured": {
            "ink_mean_pct": 2, "area_any_ink_pct": 2, "max_ink_pct": 100.0,
            "mean_ink_on_inked_area_pct": 100.0, "full_ink_equivalent_mm2": 1.0}}]


def test_reconcile_zero_tint_only_keeps_plate_measurement():
    rec = reconcile(_scan(zero=["Zero Spot"]), {"Zero Spot": _plate(0)})
    assert rec["colorants"] == [] and rec["zero_tint_only"][0]["name"] == "Zero Spot"
    assert rec["zero_tint_only"][0]["measured"]["ink_mean_pct"] == 0


def test_reconcile_ambiguous_names_get_no_measurement():
    rec = reconcile(_scan(used=["Spot A", "spot a"]), {"Spot A": _plate(5), "spot a": _plate(7)})
    assert all(c["measured"] is None for c in rec["colorants"])
    assert [c for c in codes(rec) if c[0] == "ambiguous_plate_name"]


def test_reconcile_plates_only_has_no_scanner_alarm():
    rec = reconcile(None, {"Cyan": _plate(3), "Spot": _plate(4)})
    assert {c["name"] for c in rec["colorants"]} == {"Cyan", "Spot"}
    assert rec["diagnostics"] == []


def test_reconcile_gs_component_limit_does_not_invent_zeros():
    names = ["S%02d" % i for i in range(12)]
    plates = {n: _plate(1) for n in names[:10]}
    plates["Magenta"] = _plate(2)
    rec = reconcile(_scan(used=names), plates)
    by = {c["name"]: c for c in rec["colorants"]}
    assert by["S11"]["measured"] is None and "no_plate_gs_component_limit" in by["S11"]["accuracy"]["flags"]
    assert ("gs_component_limit_exceeded", None) in codes(rec)
    assert rec["derived_process_plates"][0]["origin"] == "gs_component_limit"


def test_plate_name_helpers():
    assert gm.fix_plate_name("%D0%A4%D0%B0") == "Фа"
    assert gm.fix_plate_name("PANTONE 185 C") == "PANTONE 185 C"
    assert gm.norm_name("Spot  A") == gm.norm_name("spot a")


# ---- Ghostscript integration -------------------------------------------------------

@needs_gs
def test_engine_metadata_and_gs_pin():
    r = run(fx.cmyk_quarter())
    assert r["schema_version"] == 1
    eng = r["document"]["engine"]
    assert eng["method"] == "gs-tiffsep-raster+content-scan"
    assert eng["gs_version"] == "9.55.0"            # production pin: do not upgrade silently
    assert eng["pymupdf"] and eng["analysis_ms"] >= 0


@needs_gs
def test_cmyk_quarter_measured():
    r = run(fx.cmyk_quarter())
    assert mean(r, "Cyan") == pytest.approx(25.0, abs=TOL)
    assert mean(r, "Magenta") == pytest.approx(12.5, abs=TOL)
    c = page_colorants(r)["Cyan"]
    assert c["measured"]["area_any_ink_pct"] == pytest.approx(25.0, abs=TOL)
    assert c["measured"]["max_ink_pct"] == 100.0
    assert c["measured"]["full_ink_equivalent_mm2"] == pytest.approx(0.25 * 4978.086, rel=0.02)
    assert c["accuracy"]["level"] == "exact"
    assert r["pages"][0]["measurement"]["peak_total_pct"] == pytest.approx(150.0, abs=1.0)
    assert r["pages"][0]["measurement"]["plate_px"] == [417, 417]
    assert [c["id"] for c in r["document"]["colorants"]] == ["c0", "c1"]


@needs_gs
def test_separation_and_devicen_and_spot():
    r = run(fx.spot_pdf("PANTONE 185 C", 0.8, (0, 0, 100, 100)))
    assert mean(r, "PANTONE 185 C") == pytest.approx(20.0, abs=TOL)
    r = run(fx.devicen_pdf(["Alpha Ink", "Beta Ink"], [0.4, 0.7]))
    assert mean(r, "Alpha Ink") == pytest.approx(10.0, abs=TOL)
    assert mean(r, "Beta Ink") == pytest.approx(17.5, abs=TOL)


@needs_gs
@pytest.mark.parametrize("name", ["White", "Lak", "Varnish", "Die Cut", "Perforation"])
def test_technical_colorants_measured_like_any_other(name):
    r = run(fx.spot_pdf(name))
    assert mean(r, name) == pytest.approx(25.0, abs=TOL)


@needs_gs
def test_declared_unused_and_zero_tint_reported_separately():
    r = run(fx.declared_unused_pdf())
    p = r["pages"][0]
    assert [c["name"] for c in p["colorants"]] == ["Used Spot"]
    assert sorted(u["name"] for u in p["declared_but_unused"]) == ["Unused DN A", "Unused DN B", "Unused Spot"]
    z = run(fx.spot_pdf("Zero Spot", 0.0))["pages"][0]
    assert z["colorants"] == [] and z["painted_zero_tint_only"][0]["name"] == "Zero Spot"
    assert z["painted_zero_tint_only"][0]["measured"]["ink_mean_pct"] == 0
    assert "id" in z["painted_zero_tint_only"][0]


@needs_gs
def test_form_xobject_and_multipage():
    assert mean(run(fx.nested_form_pdf()), "Black") == pytest.approx(0.8 * 6.25, abs=TOL)
    r = run(fx.multipage_pdf())
    assert [p["page"] for p in r["pages"]] == [1, 2, 3] and r["document"]["complete"]
    assert mean(r, "Cyan", 0) == pytest.approx(50.0, abs=TOL)
    assert mean(r, "Page Two Spot", 1) == pytest.approx(25.0, abs=TOL)
    assert mean(r, "Black", 2) == pytest.approx(25.0, abs=TOL)
    by_name = {c["name"]: c for c in r["document"]["colorants"]}
    assert by_name["Cyan"]["pages"] == [1] and by_name["Page Two Spot"]["pages"] == [2]
    assert [c["name"] for c in r["document"]["colorants"]][:2] == ["Cyan", "Black"]   # process first


@needs_gs
def test_overprint_opm_and_knockout():
    # Cyan 0..100, Magenta 50..150 over it: overlap 50x100 pt = 12.5% of page
    ov = run(fx.overprint_pdf(opm=1))
    assert mean(ov, "Cyan") == pytest.approx(25.0, abs=TOL)         # kept under overprint
    assert page_colorants(ov)["Magenta"]["paint"]["overprint_paints"] == 1
    ko = run(fx.overprint_pdf(opm=0, overprint=False))
    assert mean(ko, "Cyan") == pytest.approx(12.5, abs=TOL)          # knocked out in the overlap
    assert mean(run(fx.spot_under_cmyk_pdf(True)), "Under Spot") == pytest.approx(25.0, abs=TOL)
    assert mean(run(fx.spot_under_cmyk_pdf(False)), "Under Spot") == pytest.approx(12.5, abs=TOL)


@needs_gs
def test_thin_stroke_second_pass_and_no_correction_factor():
    r = run(fx.thin_stroke_pdf(0.25))
    p = r["pages"][0]
    m = p["measurement"]
    assert [x["reason"] for x in m["passes"]] == ["base", "thin_strokes"]
    assert m["dpi_effective"] == 600.0 and not m["pixel_budget_limited"]
    c = page_colorants(r)["Thin Line"]
    assert c["accuracy"]["level"] == "approximate" and "thin_strokes" in c["accuracy"]["flags"]
    assert c["accuracy"]["min_stroke_width_pt"] == pytest.approx(0.25)
    assert any(d["code"] == "thin_strokes" for d in p["diagnostics"])
    # geometry: 160 pt x 0.25 pt / 40000 pt^2 = 0.1 %; raster value reported as measured
    assert c["measured"]["ink_mean_pct"] == pytest.approx(0.1, abs=0.03)
    assert c["measured"]["ink_mean_pct"] != 0.1


@needs_gs
def test_converted_spaces_separate_from_native():
    p = run(fx.rgb_gray_pdf())["pages"][0]
    assert p["colorants"] == []
    assert {c["family"] for c in p["converted_color_spaces"]} == {"DeviceRGB", "DeviceGray"}
    assert {d["plate"] for d in p["derived_process_plates"]} >= {"Black", "Magenta", "Yellow"}
    assert all(d["origin"] == "conversion" for d in p["derived_process_plates"])


@needs_gs
def test_separation_all_diagnostic():
    p = run(fx.all_none_pdf())["pages"][0]
    assert any(d["code"] == "separation_all_used" for d in p["diagnostics"])
    assert {d["origin"] for d in p["derived_process_plates"]} == {"separation_all"}


@needs_gs
def test_transparency_marks_unvalidated():
    p = run(fx.transparency_pdf())["pages"][0]
    assert any(d["code"] == "transparency_used" for d in p["diagnostics"])
    assert p["colorants"][0]["accuracy"]["level"] == "unvalidated"


@needs_gs
def test_ocg_off_layer_is_measured_after_flatten():
    assert mean(run(fx.ocg_off_pdf()), "Layer Spot") == pytest.approx(25.0, abs=TOL)


@needs_gs
def test_geometry_rotation_userunit_cropbox():
    g = run(fx.rotated_pdf())["pages"][0]["geometry"]
    assert (g["width_pt"], g["height_pt"], g["rotation"]) == (100.0, 200.0, 90)
    assert run(fx.userunit_pdf())["pages"][0]["geometry"]["user_unit"] == 2.0
    crop = run(fx.cropbox_pdf())
    assert crop["pages"][0]["geometry"]["box"] == "CropBox"
    assert mean(crop, "Cyan") == pytest.approx(100.0, abs=TOL)       # coverage of the CropBox only


@needs_gs
def test_unicode_and_hex_escaped_names_match_plates():
    r = run(fx.unicode_name_pdf("Фарба №1"))
    assert mean(r, "Фарба №1") == pytest.approx(25.0, abs=TOL)
    assert r["pages"][0]["diagnostics"] == []


@needs_gs
def test_case_variant_names_are_ambiguous():
    p = run(fx.case_variant_names_pdf())["pages"][0]
    assert [c["measured"] for c in p["colorants"]] == [None, None]
    assert [d["code"] for d in p["diagnostics"]].count("ambiguous_plate_name") == 2


def test_max_spots_request_follows_detected_spots():
    assert gm.spot_plane_request(0) is None and gm.spot_plane_request(10) is None   # GS default is enough
    assert gm.spot_plane_request(11) == 11 and gm.spot_plane_request(25) == 25
    assert gm.spot_plane_request(40) == 32                                          # v1 cap
    assert gm.spot_plane_request(None) == 32                                        # plates-only: unknown count
    base = gm.gs_args("gs", Path("/x/in.pdf"), 1, 150.0, Path("/x/p.tif"))
    assert not any(a.startswith("-dMaxSpots") for a in base)
    many = gm.gs_args("gs", Path("/x/in.pdf"), 1, 150.0, Path("/x/p.tif"), 12)
    assert "-dMaxSpots=12" in many and "-dSAFER" in many and "-dNOSAFER" not in many


@needs_gs
@pytest.mark.parametrize("n", [11, 12, 20, 32])
def test_more_than_10_spots_each_get_their_own_plate(n):
    """Regression: Ghostscript 9.55 defaults to 10 spot planes and folds the
    rest into CMYK. -dMaxSpots=N (N = detected spots) keeps every spot on its
    own plate and the CMYK plates empty."""
    names = ["S%02d" % i for i in range(n)]
    p = run(fx.multi_spot_pdf(names))["pages"][0]
    spots = {c["name"]: c for c in p["colorants"] if c["name"] in names}
    assert set(spots) == set(names)
    for name, c in spots.items():
        assert c["measured"] is not None, name
        assert c["measured"]["area_any_ink_pct"] > 0, f"{name} has no plate ink"
        assert c["measured"]["ink_mean_pct"] == pytest.approx(25 / 40000 * 100, abs=0.03), name
        assert "no_plate_gs_component_limit" not in c["accuracy"]["flags"]
    # nothing folded into CMYK: no process colorants, no derived plates, no alarms
    assert [c["name"] for c in p["colorants"] if c["name"] not in names] == []
    assert p["derived_process_plates"] == []
    assert p["diagnostics"] == []


@needs_gs
def test_spot_planes_confirmed_in_raw_ghostscript_output(tmp_path):
    names = ["S%02d" % i for i in range(14)]
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(fx.multi_spot_pdf(names))
    for max_spots, expected in ((None, 14), (14, 18)):       # 4 + 10 default  vs  4 + 14 requested
        out = tmp_path / f"o{max_spots}"
        out.mkdir()
        rc, _ = gm.run_gs(pdf, 1, 72.0, out, 30.0, max_spots)
        assert rc == 0
        assert len([f for f in os.listdir(out) if f.startswith("p(")]) == expected


@needs_gs
def test_33_spots_cap_at_32_and_the_extra_one_is_not_silently_measured():
    names = ["S%02d" % i for i in range(33)]
    p = run(fx.multi_spot_pdf(names))["pages"][0]
    codes_ = {d["code"] for d in p["diagnostics"]}
    assert "colorant_limit_exceeded" in codes_
    own = [c for c in p["colorants"] if c["name"] in names]
    assert len(own) == 32 and all(c["measured"]["area_any_ink_pct"] > 0 for c in own)
    # the 33rd spot was never detected, so GS folded it into CMYK: surfaced as an alarm, not hidden
    assert "ink_on_plate_without_detected_use" in codes_


@needs_gs
def test_ceiling_reached_is_still_reported_not_zeroed():
    """If Ghostscript runs out of planes anyway (detection undercounted),
    spots without a plate are `measured: null` plus a diagnostic."""
    from ink_coverage import reconcile
    names = ["S%02d" % i for i in range(12)]
    plates = {n: _plate(1) for n in names[:10]}
    plates["Magenta"] = _plate(2)
    rec = reconcile(_scan(used=names), plates, spot_ceiling=10)
    assert ("gs_component_limit_exceeded", None) in codes(rec)
    # with the ceiling raised and every spot present, there is no such diagnostic
    rec2 = reconcile(_scan(used=names), {n: _plate(1) for n in names}, spot_ceiling=12)
    assert rec2["diagnostics"] == []


@needs_gs
def test_detection_budget_degrades_to_plates_only(monkeypatch):
    import ink_content_scan as cs
    import ink_coverage
    monkeypatch.setattr(ink_coverage, "scan_page",
                        lambda doc, page, **kw: cs.scan_page(doc, page, max_tokens=3, **kw))
    p = run(fx.spot_pdf("PANTONE 185 C"))["pages"][0]
    assert p["measurement"]["detection"] == "plates_only"
    assert any(d["code"] == "detection_budget_exceeded" for d in p["diagnostics"])
    assert [c["name"] for c in p["colorants"]] == ["PANTONE 185 C"]       # plates still list it
    assert p["colorants"][0]["accuracy"]["level"] == "unvalidated"


@needs_gs
def test_flate_bomb_degrades_not_crashes():
    p = run(fx.flate_bomb_pdf(70))["pages"][0]
    assert p["measurement"]["detection"] == "plates_only"


@needs_gs
def test_giant_mediabox_respects_pixel_budget():
    r = run(fx.giant_mediabox_pdf())
    p = r["pages"][0]
    assert p["status"] == "failed" and p["error"] == "page_too_large_for_pixel_budget"
    assert p["colorants"][0]["measured"] is None and r["document"]["complete"] is False


@needs_gs
def test_truncates_at_10_pages():
    pdf = fx.make_pdf([{"content": "1 0 0 0 k 0 0 10 10 re f"}] * 12)
    r = run(pdf)
    assert r["document"]["page_count"] == 12 and r["document"]["truncated"] is True
    assert len(r["pages"]) == 10


@needs_gs
def test_fake_gs_that_hangs_gives_skipped_timeout(tmp_path, monkeypatch):
    fake = tmp_path / "gs"
    fake.write_text('#!/bin/sh\n[ "$1" = "--version" ] && echo 9.55.0 && exit 0\nexec sleep 60\n')
    fake.chmod(0o755)
    monkeypatch.setenv("INK_GS_BIN", str(fake))
    monkeypatch.setattr(gm, "GS_PAGE_TIMEOUT_S", 1.5)
    r = run(fx.cmyk_quarter())
    assert r["pages"][0]["status"] == "skipped_timeout" and r["document"]["complete"] is False


@needs_gs
def test_fake_gs_that_crashes_gives_failed_page(tmp_path, monkeypatch):
    fake = tmp_path / "gs"
    fake.write_text('#!/bin/sh\n[ "$1" = "--version" ] && echo 9.55.0 && exit 0\nexit 139\n')
    fake.chmod(0o755)
    monkeypatch.setenv("INK_GS_BIN", str(fake))
    p = run(fx.cmyk_quarter())["pages"][0]
    assert p["status"] == "failed" and p["error"] == "gs_failed" and p["measurement"]["gs_returncode"] == 139


@needs_gs
def test_total_deadline_marks_remaining_pages_skipped():
    pdf = fx.make_pdf([{"content": "1 0 0 0 k 0 0 10 10 re f"}] * 3)
    r = analyze_ink_coverage(pdf, {"deadline_s": 0.5})
    assert [p["status"] for p in r["pages"]] == ["skipped_timeout"] * 3
    assert r["document"]["complete"] is False


def test_invalid_inputs_raise_typed_errors():
    for bad, code in [(b"hello", "invalid_pdf"), (b"%PDF-1.4\ntruncated", "invalid_pdf")]:
        with pytest.raises(InkError) as e:
            analyze_ink_coverage(bad)
        assert e.value.code == code
    doc = pymupdf.open(stream=fx.cmyk_quarter(), filetype="pdf")
    enc = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    with pytest.raises(InkError) as e:
        analyze_ink_coverage(enc)
    assert e.value.code == "encrypted_pdf"
    with pytest.raises(InkError) as e:
        analyze_ink_coverage(b"%PDF" + b"0" * (25 * 1024 * 1024 + 1))
    assert e.value.code == "file_too_large"


# ---- independent validation corpus as regression input ---------------------------------

def _corpus_cases():
    if not (CORPUS / "manifest.json").exists():
        return []
    return json.loads((CORPUS / "manifest.json").read_text())["cases"]


@needs_gs
@needs_corpus
@pytest.mark.parametrize("case", _corpus_cases(), ids=lambda c: c["case_id"])
def test_validation_corpus_regression(case):
    """Mean ink of every colorant matches the hand-derived expectation.
    Thin-stroke cases (08a-c) carry the documented raster overshoot: they are
    held to a wider bound and are NOT corrected."""
    r = run((CORPUS / case["filename"]).read_bytes())
    thin = case["suitability"] == "numeric_exact_thin_stroke"
    tol = 0.5 if thin else (0.6 if case["suitability"] == "numeric_exact_gradient" else TOL)
    for page, mp in zip(r["pages"], case["pages"]):
        got = {c["name"]: c["measured"] for c in page["colorants"]}
        got.update({c["name"]: c["measured"] for c in page["painted_zero_tint_only"]})
        for name, exp in mp["expected_analytic_hand_derived"].items():
            have = got[name]["ink_mean_pct"] if name in got else 0.0
            assert have == pytest.approx(exp["mean_ink_pct"], abs=tol), (case["case_id"], page["page"], name)
        # declared-but-unused resources must never become colorants
        unused = set(mp.get("declared_unused", {}))
        assert not (unused & {c["name"] for c in page["colorants"]})


@needs_gs
@pytest.mark.skipif(not sorted(Path(__file__).resolve().parent.parent.glob("test-files/57384*98.94%.pdf")),
                    reason="real QA PDF not present")
def test_real_qa_pdf_detects_and_measures_spots():
    f = sorted(Path(__file__).resolve().parent.parent.glob("test-files/57384*98.94%.pdf"))[0]
    r = run(f.read_bytes())
    by = page_colorants(r)
    for name in ("Lak", "PANTONE 3262 C", "PANTONE Black C", "White-1"):
        assert name in by and by[name]["measured"]["area_any_ink_pct"] > 0, name
