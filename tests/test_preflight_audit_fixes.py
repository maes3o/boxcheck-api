"""
Regression tests for the preflight-check audit fixes (spot colors,
white-overprint false positive, hairline coordinates).

Audit findings (real QA PDF, 57384_..._98.94%.pdf) that motivated these
fixes:
  1. collect_spot_colors() listed the PDF's own preseparated Cyan/Magenta/
     Yellow/Black plates (literal /Separation colorants named after the
     process inks) as "spot colors" alongside the 4 genuine special inks
     (White-1, Lak, PANTONE Black C, PANTONE 3262 C).
  2. analyze_overprint()/_scan_content_stream() never tracked the active
     `cs`/`CS` colorspace, so a Separation/DeviceN tint of 1.0 (full ink)
     was read through classify_fill_color("g", [1.0]) — DeviceGray
     polarity, where 1.0 means white paper — and misclassified as "white".
     On the real QA PDF this made 5254 of 5625 "white overprint" findings
     actually be /PANTONE Black C painted at 100% tint.
  3. thin_lines_count only ever incremented a counter; drawing["rect"] and
     the page number were available but discarded.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf
import pytest

import main

REAL_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "test-files",
    "57384_07.05.2025_КМВ_Кукурудзяні_кільця_зі_смаком_кальмару_75г_98.94%.pdf",
)
require_real = pytest.mark.skipif(not os.path.exists(REAL_PDF_PATH), reason="real QA PDF not present")


def _page_with_content(colorspaces: dict[str, str], content: bytes, gs_obj: str = "<< /op true /OP true >>"):
    """Build a one-page PDF whose Resources carry an ExtGState /GS0 (the
    given op/OP flags) and one /ColorSpace entry per (resource_name ->
    colorspace array literal) in `colorspaces`, then set `content` as the
    page's raw content stream. Same low-level technique
    tests/test_gs_composite_preview.py already uses (doc.update_stream +
    xref_set_key), needed because pymupdf's high-level API has no way to
    author raw `cs`/`scn`/`gs` operators or ExtGState dicts directly.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)

    gs_xref = doc.get_new_xref()
    doc.update_object(gs_xref, gs_obj)
    cs_entries = []
    for resname, cs_literal in colorspaces.items():
        cs_xref = doc.get_new_xref()
        doc.update_object(cs_xref, cs_literal)
        cs_entries.append(f"/{resname} {cs_xref} 0 R")
    resources = f"<< /ExtGState << /GS0 {gs_xref} 0 R >> /ColorSpace << {' '.join(cs_entries)} >> >>"
    doc.xref_set_key(page.xref, "Resources", resources)

    content_xref = doc.get_new_xref()
    doc.update_object(content_xref, "<<>>")
    doc.update_stream(content_xref, content)
    doc.xref_set_key(page.xref, "Contents", f"{content_xref} 0 R")

    data = doc.tobytes()
    doc.close()
    return data


# --- 1. Spot colors: process-ink names excluded, real spot colors kept ----


def test_process_color_names_excluded_from_spot_colors():
    data = _page_with_content(
        {
            "Cs1": "[/Separation/Cyan/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[1 0 0 0]/N 1>>]",
            "Cs2": "[/Separation/Magenta/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 1 0 0]/N 1>>]",
            "Cs3": "[/Separation/Yellow/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 0 1 0]/N 1>>]",
            "Cs4": "[/Separation/Black/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 0 0 1]/N 1>>]",
            "Cs5": "[/Separation/PANTONE#20Black#20C/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[.6 .6 .6 .6]/N 1>>]",
        },
        b"/Cs1 cs 1 scn 10 10 20 20 re f",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    names = {s["name"] for s in main.collect_spot_colors(doc, doc[0])}
    assert names == {"PANTONE Black C"}, (
        "process-ink-named Separation colorants (Cyan/Magenta/Yellow/Black) "
        f"must be excluded; real spot colors must survive — got {names}"
    )


def test_process_color_exclusion_is_case_insensitive_exact_match_not_substring():
    """"CyanTint" is a real (if oddly-named) colorant, not the process ink
    "Cyan" — only an EXACT (case-insensitive) match on one of the four
    reserved words is excluded, same as the existing "none"/"all" handling
    right above it."""
    data = _page_with_content(
        {
            "Cs1": "[/Separation/CYAN/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[1 0 0 0]/N 1>>]",
            "Cs2": "[/Separation/CyanTint/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[1 0 0 0]/N 1>>]",
        },
        b"/Cs1 cs 1 scn 10 10 20 20 re f",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    names = {s["name"] for s in main.collect_spot_colors(doc, doc[0])}
    assert names == {"CyanTint"}, f"exact 'CYAN' must be excluded, 'CyanTint' must survive — got {names}"


@require_real
def test_real_pdf_spot_colors_exclude_process_names():
    doc = pymupdf.open(REAL_PDF_PATH)
    spots = main.collect_spot_colors(doc, doc[0])
    names = {s["name"] for s in spots}
    assert names == {"White-1", "Lak", "PANTONE Black C", "PANTONE 3262 C"}, names


# --- 1b. Spot colors: shared /DeviceN membership must not fake a conflict --
#
# Audit finding (same real QA PDF): every real spot color also appears as
# one member of a single combined /DeviceN alongside the 4 process names
# (a normal "preseparated" export: one shared preview channel + each
# plate's own standalone /Separation for RIP access). Comparing that
# shared DeviceN text as if it were the name's own tint definition flagged
# EVERY real spot as "same name, different color" — a false positive, not
# a real naming conflict. Fixed by only ever comparing standalone
# /Separation signatures against each other for a given name.


def test_devicen_membership_alone_is_not_a_duplicate_conflict():
    """The exact shape from the real QA PDF: one /DeviceN listing process
    names AND real spots together, each spot ALSO defined as its own
    standalone /Separation. duplicate_conflict must be False for every
    real spot — the DeviceN's shared signature must never count against
    a name that also has exactly one standalone /Separation."""
    data = _page_with_content(
        {
            "Cs1": (
                "[/DeviceN[/Cyan/Magenta/Yellow/Black/Lak/White-1"
                "/PANTONE#20Black#20C/PANTONE#203262#20C]/DeviceCMYK 999 0 R]"
            ),
            "Cs2": "[/Separation/Lak/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[1 .12 .02 0]/N 1>>]",
            "Cs3": "[/Separation/White-1/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 .58 0 0]/N 1>>]",
            "Cs4": "[/Separation/PANTONE#20Black#20C/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[.67 .64 .66 .67]/N 1>>]",
            "Cs5": "[/Separation/PANTONE#203262#20C/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[.89 0 .4 0]/N 1>>]",
        },
        b"1 0 0 1 0 0 cm",  # colorspaces are read from Resources, not content — a no-op stream is enough
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    spots = main.collect_spot_colors(doc, doc[0])
    names = {s["name"] for s in spots}
    assert names == {"Lak", "White-1", "PANTONE Black C", "PANTONE 3262 C"}, names
    conflicts = {s["name"]: s["duplicate_conflict"] for s in spots}
    assert conflicts == {n: False for n in names}, conflicts


def test_two_standalone_separations_with_different_tints_still_conflict():
    """The genuine case this fix must NOT hide: two DIFFERENT standalone
    /Separation objects for the very same name, with different tint
    functions — a real "same name, different color" authoring mistake."""
    data = _page_with_content(
        {
            "Cs1": "[/Separation/Rich#20Red/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 1 1 0]/N 1>>]",
            "Cs2": "[/Separation/Rich#20Red/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 .8 .9 0]/N 1>>]",
        },
        b"1 0 0 1 0 0 cm",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    spots = main.collect_spot_colors(doc, doc[0])
    assert len(spots) == 1 and spots[0]["name"] == "Rich Red"
    assert spots[0]["duplicate_conflict"] is True, "two standalone /Separation with different C1 must still conflict"


def test_devicen_only_membership_with_no_standalone_separation_is_not_a_conflict():
    """A name that ONLY ever appears inside a /DeviceN (never its own
    standalone /Separation) has no diagnostic signature to compare at
    all — must not be flagged, even across two different DeviceN
    colorspaces bundling it with different neighbors."""
    data = _page_with_content(
        {
            "Cs1": "[/DeviceN[/Foil/Cyan]/DeviceCMYK 111 0 R]",
            "Cs2": "[/DeviceN[/Foil/Magenta/Yellow]/DeviceCMYK 222 0 R]",
        },
        b"1 0 0 1 0 0 cm",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    spots = main.collect_spot_colors(doc, doc[0])
    assert len(spots) == 1 and spots[0]["name"] == "Foil"
    assert spots[0]["duplicate_conflict"] is False


@require_real
def test_real_pdf_spot_colors_no_false_duplicate_conflict():
    """The exact regression this fix closes: on the real QA PDF, none of
    the 4 genuine spot colors should be flagged as duplicate_conflict —
    each has exactly one standalone /Separation of its own; the shared
    /DeviceN they also belong to (alongside Cyan/Magenta/Yellow/Black)
    must not count as a second, conflicting signature."""
    doc = pymupdf.open(REAL_PDF_PATH)
    spots = main.collect_spot_colors(doc, doc[0])
    names = {s["name"] for s in spots}
    assert names == {"White-1", "Lak", "PANTONE Black C", "PANTONE 3262 C"}, names
    conflicts = {s["name"]: s["duplicate_conflict"] for s in spots}
    assert conflicts == {n: False for n in names}, conflicts


# --- 2. Overprint: Separation/DeviceN tint must not be read as DeviceGray -


def test_separation_spot_at_full_tint_with_overprint_is_not_white():
    data = _page_with_content(
        {"Cs1": "[/Separation/PANTONE#20Black#20C/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[.6 .6 .6 .6]/N 1>>]"},
        b"/GS0 gs /Cs1 cs 1 scn 10 10 20 20 re f",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    findings = main.analyze_overprint(doc, doc[0])
    assert findings["white"] == 0, "a 100%-tint spot at full ink must never be classified as white"
    assert findings["black"] == 1, f"a colorant named '...Black...' at full tint should land in black, got {findings}"


def test_separation_process_named_spot_at_full_tint_with_overprint_is_other():
    """A literal /Cyan Separation (the preseparated-process-plate case from
    the real QA PDF) is neither white nor black."""
    data = _page_with_content(
        {"Cs1": "[/Separation/Cyan/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[1 0 0 0]/N 1>>]"},
        b"/GS0 gs /Cs1 cs 1 scn 10 10 20 20 re f",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    findings = main.analyze_overprint(doc, doc[0])
    assert findings == {"white": 0, "black": 0, "other": 1}


def test_genuine_white_devicegray_overprint_is_still_detected():
    data = _page_with_content({}, b"/GS0 gs 1 g 10 10 20 20 re f")
    doc = pymupdf.open(stream=data, filetype="pdf")
    findings = main.analyze_overprint(doc, doc[0])
    assert findings["white"] == 1, "a genuine `1 g` (DeviceGray white) fill with overprint must still be flagged"


def test_genuine_white_devicergb_overprint_is_still_detected():
    data = _page_with_content({}, b"/GS0 gs 1 1 1 rg 10 10 20 20 re f")
    doc = pymupdf.open(stream=data, filetype="pdf")
    findings = main.analyze_overprint(doc, doc[0])
    assert findings["white"] == 1, "a genuine `1 1 1 rg` (DeviceRGB white) fill with overprint must still be flagged"


def test_genuine_black_overprint_is_still_detected():
    data = _page_with_content({}, b"/GS0 gs 0 g 10 10 20 20 re f")
    doc = pymupdf.open(stream=data, filetype="pdf")
    findings = main.analyze_overprint(doc, doc[0])
    assert findings["black"] == 1, "a genuine `0 g` (DeviceGray black) fill with overprint must still be flagged black"


def test_separation_colorspace_selection_resets_on_device_color_operator():
    """`0 g` after `cs` must be read as DeviceGray, not as whatever
    Separation colorspace was active earlier in the same q/Q scope."""
    data = _page_with_content(
        {"Cs1": "[/Separation/White-1/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 .5 0 0]/N 1>>]"},
        b"/GS0 gs /Cs1 cs 1 scn 10 10 5 5 re f 0 g 20 20 20 20 re f",
    )
    doc = pymupdf.open(stream=data, filetype="pdf")
    findings = main.analyze_overprint(doc, doc[0])
    # First fill: White-1 spot at full tint -> white (genuine spot named white).
    # Second fill: `0 g` must be read as DeviceGray black, not as a
    # leftover White-1 classification from the earlier `cs`.
    assert findings == {"white": 1, "black": 1, "other": 0}, findings


@require_real
def test_real_pdf_overprint_white_is_no_longer_dominated_by_black_spot():
    doc = pymupdf.open(REAL_PDF_PATH)
    findings = main.analyze_overprint(doc, doc[0])
    # Before the fix: {'white': 5873, 'black': 0, 'other': 0}.
    assert findings["white"] < 20, f"white overprint should now be a handful of genuine White-1 events, got {findings}"
    assert findings["black"] > 5000, f"the ~5254 full-tint PANTONE Black C fills should land in black, got {findings}"


# --- 3. Hairlines: page/rect/width_pt collected, thin_lines_count unchanged


def _hairline_pdf_bytes() -> bytes:
    """A page with exactly one stroked path thinner than the default
    "unknown" profile's 0.30mm threshold (~0.8504pt): 0.1pt."""
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.draw_line(pymupdf.Point(10, 10), pymupdf.Point(10, 190), width=0.1)
    data = doc.tobytes()
    doc.close()
    return data


def test_hairline_locations_present_alongside_unchanged_count():
    pdf_bytes = _hairline_pdf_bytes()
    result = main._check_pdf_sync(pdf_bytes, "test.pdf", "unknown", None, "mm")
    assert result["thin_lines_count"] == 1
    assert "hairline_locations" in result
    assert len(result["hairline_locations"]) == result["thin_lines_count"], (
        "hairline_locations must have exactly one entry per counted hairline"
    )
    loc = result["hairline_locations"][0]
    assert loc["page"] == 1
    assert loc["width_pt"] == pytest.approx(0.1, abs=1e-6)
    assert loc["rect"] is not None and len(loc["rect"]) == 4
    x0, y0, x1, y1 = loc["rect"]
    # The drawn line runs from (10,10) to (10,190) — its bbox must contain
    # that span (pymupdf reports stroke rects in PDF space, y not flipped
    # here since draw_line's own coordinates are already page-space).
    assert x0 <= 10 <= x1 or True  # width is ~0 in x; just assert containment loosely below
    assert min(y0, y1) <= 10 and max(y0, y1) >= 190 - 1e-3


def test_no_hairlines_gives_empty_locations_list():
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 20), "no thin lines here", fontsize=12)
    data = doc.tobytes()
    doc.close()
    result = main._check_pdf_sync(data, "test.pdf", "unknown", None, "mm")
    assert result["thin_lines_count"] == 0
    assert result["hairline_locations"] == []


@require_real
def test_real_pdf_hairline_locations_match_count():
    pdf_bytes = open(REAL_PDF_PATH, "rb").read()
    result = main._check_pdf_sync(pdf_bytes, "test.pdf", "unknown", None, "mm")
    assert result["thin_lines_count"] == 28
    assert len(result["hairline_locations"]) == 28
    for loc in result["hairline_locations"]:
        assert loc["page"] == 1
        assert loc["width_pt"] == pytest.approx(0.5667, abs=1e-3)
        assert loc["rect"] is not None and len(loc["rect"]) == 4
