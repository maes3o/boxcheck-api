"""Ink Coverage — native colorant detection (no Ghostscript needed)."""
import os
import sys

import pymupdf
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import ink_fixtures as fx
from ink_content_scan import (
    Budget, Lexer, Ref, ScanBudgetExceeded, decode_name, parse_obj, scan_page,
)


def scan(pdf_bytes: bytes, page: int = 0, **kw):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    try:
        return scan_page(doc, doc[page], **kw)
    finally:
        doc.close()


# ---- lexer / object parser ------------------------------------------------

def test_parse_obj_dict_array_refs_names():
    o = parse_obj("<< /A [ 1 2.5 /Name#20X (str) ] /B 12 0 R /C << /D true >> >>")
    assert o["A"] == [1, 2.5, "Name X", b"str"]
    assert isinstance(o["B"], Ref) and int(o["B"]) == 12
    assert o["C"] == {"D": True}


def test_decode_name_utf8_and_latin1_fallback():
    assert decode_name(b"PANTONE#20185#20C") == "PANTONE 185 C"
    assert decode_name(b"#D0#A4#D0#B0") == "Фа"
    assert decode_name(b"Caf#E9") == "Café"          # not valid UTF-8 -> latin-1


def test_lexer_string_with_nested_parens_and_escapes():
    lex = Lexer(rb"(a(b)c\)d) /N", Budget())
    kind, val = lex.next()
    assert val == rb"a(b)c\)d"
    assert lex.next() == ("name", "N")


def test_token_budget_exceeded():
    with pytest.raises(ScanBudgetExceeded):
        scan(fx.cmyk_quarter(), max_tokens=3)


# ---- families, tints ---------------------------------------------------------

def test_cmyk_paints_only_nonzero_channels():
    r = scan(fx.cmyk_quarter())
    assert list(r["colorants"]) == ["Cyan", "Magenta"]
    assert r["colorants"]["Cyan"]["tint"] == {"min": 1.0, "max": 1.0}
    assert r["colorants"]["Magenta"]["tint"] == {"min": 0.5, "max": 0.5}
    assert r["colorants"]["Cyan"]["used_via"][0]["family"] == "DeviceCMYK"
    assert r["zero_tint_only"] == {} and r["converted"] == {}


def test_separation_spot():
    r = scan(fx.spot_pdf("PANTONE 185 C", 0.8))
    c = r["colorants"]["PANTONE 185 C"]
    assert c["families"] == ["Separation"] and c["tint"] == {"min": 0.8, "max": 0.8}
    assert c["paint"]["sources"] == ["path"]


def test_devicen_group_and_both_components():
    r = scan(fx.devicen_pdf(["Alpha Ink", "Beta Ink"], [0.4, 0.7]))
    a, b = r["colorants"]["Alpha Ink"], r["colorants"]["Beta Ink"]
    assert a["used_via"][0] == {"family": "DeviceN", "devicen_group": "Alpha Ink+Beta Ink", "paints": 1}
    assert a["tint"]["max"] == 0.4 and b["tint"]["max"] == 0.7


@pytest.mark.parametrize("name", ["White", "Lak", "Varnish", "Die Cut", "Crease", "Perforation", "White-1"])
def test_technical_and_production_colorants_are_plain_colorants(name):
    """No classification: they are reported like any other colorant."""
    r = scan(fx.spot_pdf(name))
    assert list(r["colorants"]) == [name]


def test_tint_zero_goes_to_zero_tint_only():
    r = scan(fx.spot_pdf("Zero Spot", 0.0))
    assert r["colorants"] == {} and list(r["zero_tint_only"]) == ["Zero Spot"]


def test_devicen_zero_components_are_zero_tint_only():
    r = scan(fx.devicen_pdf(["Used DN", "Zero DN"], [0.5, 0.0]))
    assert list(r["colorants"]) == ["Used DN"] and list(r["zero_tint_only"]) == ["Zero DN"]


def test_declared_but_unused_is_separate():
    r = scan(fx.declared_unused_pdf())
    assert list(r["colorants"]) == ["Used Spot"]
    assert sorted(u["name"] for u in r["declared_unused"]) == ["Unused DN A", "Unused DN B", "Unused Spot"]


def test_unpainted_text_does_not_count_as_use():
    r = scan(fx.invisible_text_only_pdf())          # Tr 3
    assert r["colorants"] == {} and [u["name"] for u in r["declared_unused"]] == ["Ghost Spot"]


def test_visible_text_counts_as_fill():
    r = scan(fx.text_mode3_pdf())
    assert r["colorants"]["Text Spot"]["paint"]["sources"] == ["text"]


def test_all_and_none():
    r = scan(fx.all_none_pdf())
    assert r["colorants"] == {} and "all_used" in r["flags"]


def test_rgb_and_gray_are_converted_never_native():
    r = scan(fx.rgb_gray_pdf())
    assert r["colorants"] == {} and r["converted"] == {"DeviceRGB": 1, "DeviceGray": 1}


# ---- forms, pages ----------------------------------------------------------

def test_nested_form_xobjects_are_followed():
    assert list(scan(fx.nested_form_pdf())["colorants"]) == ["Black"]


def test_self_referencing_form_terminates():
    r = scan(fx.self_referencing_form_pdf())
    assert list(r["colorants"]) == ["Cyan"]


def test_form_depth_capped_at_10():
    r = scan(fx.deep_nesting_pdf(30))
    assert r["colorants"]["Cyan"]["used_via"][0]["paints"] == 10


def test_multipage_each_page_has_own_colorants():
    pdf = fx.multipage_pdf()
    assert list(scan(pdf, 0)["colorants"]) == ["Cyan"]
    assert list(scan(pdf, 1)["colorants"]) == ["Page Two Spot"]
    assert list(scan(pdf, 2)["colorants"]) == ["Black"]


# ---- overprint / OPM --------------------------------------------------------

def test_overprint_vs_knockout_paint_counts_and_opm():
    r = scan(fx.overprint_pdf(opm=1))
    assert r["colorants"]["Cyan"]["paint"]["knockout_paints"] == 1
    assert r["colorants"]["Magenta"]["paint"]["overprint_paints"] == 1
    assert r["colorants"]["Magenta"]["paint"]["opm"] == [1]
    ko = scan(fx.overprint_pdf(opm=0, overprint=False))
    assert ko["colorants"]["Magenta"]["paint"]["overprint_paints"] == 0


def test_spot_overprinted_by_cmyk():
    r = scan(fx.spot_under_cmyk_pdf(True))
    assert r["colorants"]["Cyan"]["paint"]["overprint_paints"] == 1
    assert r["colorants"]["Under Spot"]["paint"]["knockout_paints"] == 1


# ---- tokenizer gaps closed ---------------------------------------------------

def test_inline_image_payload_with_fake_EI_is_skipped():
    r = scan(fx.inline_image_pdf())
    assert list(r["colorants"]) == ["Black"]          # painted AFTER the image
    assert "image" in r["flags"] and r["converted"] == {"DeviceGray": 1}


def test_imagemask_uses_fill_colour():
    r = scan(fx.imagemask_pdf())
    c = r["colorants"]["Mask Spot"]
    assert c["paint"]["sources"] == ["imagemask"] and "unvalidated:image" in c["flags"]


def test_ctm_scales_stroke_width():
    # 0.05 w under a 10x CTM = 0.5 pt -> thin at 150 dpi ( < 2 px )
    thin = scan(fx.ctm_stroke_pdf(10, 0.05))
    assert thin["thin_stroke_paints"] == 1 and thin["min_stroke_width_pt"] == pytest.approx(0.5)
    # 10 w under a 0.1x CTM = 1 pt -> 2.08 px, not thin
    assert scan(fx.ctm_stroke_pdf(0.1, 10))["thin_stroke_paints"] == 0


def test_thin_stroke_flagged_on_colorant():
    r = scan(fx.thin_stroke_pdf(0.25))
    c = r["colorants"]["Thin Line"]
    assert c["thin_stroke_paints"] == 1 and c["min_stroke_width_pt"] == pytest.approx(0.25)


def test_transparency_flagged():
    r = scan(fx.transparency_pdf())
    assert "transparency" in r["flags"]
    assert "transparency_used" in r["colorants"]["Glass Spot"]["flags"]


def test_optional_content_layer_is_detected_regardless_of_state():
    """Every OCG is forced ON before Ghostscript runs, so detection counts
    layers that are OFF by default too."""
    assert list(scan(fx.ocg_off_pdf())["colorants"]) == ["Layer Spot"]


# ---- names -------------------------------------------------------------------

def test_non_ascii_hex_escaped_name():
    assert list(scan(fx.unicode_name_pdf("Фарба №1"))["colorants"]) == ["Фарба №1"]


def test_colorant_limit_32():
    r = scan(fx.multi_spot_pdf(["S%02d" % i for i in range(33)]))
    assert len(r["colorants"]) == 32 and "colorant_limit" in r["flags"]


def test_flate_bomb_hits_stream_cap():
    with pytest.raises(ScanBudgetExceeded):
        scan(fx.flate_bomb_pdf(70))
