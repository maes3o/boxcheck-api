import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from geometry import (
    mm_to_pt, pt_to_mm, match_product_size, check_safe_zone_text, Rect,
)
from products import PRODUCTS


def _trimbox_for_mm(w_mm: float, h_mm: float) -> tuple[float, float, float, float]:
    return (0.0, 0.0, mm_to_pt(w_mm), mm_to_pt(h_mm))


# --------------------------------------------------------------------- size matching

def test_business_card_exact_eu_match():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = match_product_size(trim, PRODUCTS["business_card"]["formats"], tolerance_mm=0.5)
    assert result.matched
    assert result.format_id == "eu_90x50"
    assert result.deviation_mm == 0.0


def test_business_card_within_tolerance():
    trim = _trimbox_for_mm(90.3, 49.8)  # 0.3/0.2mm off, tolerance 0.5
    result = match_product_size(trim, PRODUCTS["business_card"]["formats"], tolerance_mm=0.5)
    assert result.matched
    assert result.format_id == "eu_90x50"


def test_business_card_outside_tolerance():
    trim = _trimbox_for_mm(91.0, 50.0)  # 1mm off, tolerance 0.5
    result = match_product_size(trim, PRODUCTS["business_card"]["formats"], tolerance_mm=0.5)
    assert not result.matched
    assert result.format_id == "eu_90x50"
    assert result.deviation_mm == 1.0


def test_business_card_rotated_still_matches():
    # landscape trimbox (50x90) should still match the 90x50 format, rotated
    trim = _trimbox_for_mm(50.0, 90.0)
    result = match_product_size(trim, PRODUCTS["business_card"]["formats"], tolerance_mm=0.5)
    assert result.matched
    assert result.rotated is True


def test_flyer_picks_closest_of_multiple_formats():
    trim = _trimbox_for_mm(148.0, 210.0)  # exact A5
    result = match_product_size(trim, PRODUCTS["flyer"]["formats"], tolerance_mm=1.0)
    assert result.matched
    assert result.format_id == "a5"


def test_flyer_us_4x6_matches():
    fmt = next(f for f in PRODUCTS["flyer"]["formats"] if f["id"] == "us_4x6")
    trim = _trimbox_for_mm(fmt["width_mm"], fmt["height_mm"])
    result = match_product_size(trim, PRODUCTS["flyer"]["formats"], tolerance_mm=1.0)
    assert result.matched
    assert result.format_id == "us_4x6"


def test_explicit_format_id_checks_only_that_one():
    trim = _trimbox_for_mm(210.0, 297.0)  # A4 dims
    result = match_product_size(
        trim, PRODUCTS["flyer"]["formats"], tolerance_mm=1.0, format_id="a6"
    )
    assert not result.matched
    assert result.format_id == "a6"
    assert result.deviation_mm > 100  # wildly off vs a6


def test_unknown_format_id_returns_no_match():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = match_product_size(
        trim, PRODUCTS["business_card"]["formats"], tolerance_mm=0.5, format_id="does_not_exist"
    )
    assert not result.matched
    assert result.format_id is None


def test_poster_us_18x24_matches():
    fmt = next(f for f in PRODUCTS["poster"]["formats"] if f["id"] == "us_18x24")
    assert abs(fmt["width_mm"] - 457.2) < 0.1
    assert abs(fmt["height_mm"] - 609.6) < 0.1
    trim = _trimbox_for_mm(fmt["width_mm"], fmt["height_mm"])
    result = match_product_size(trim, PRODUCTS["poster"]["formats"], tolerance_mm=2.0)
    assert result.matched
    assert result.format_id == "us_18x24"


# --------------------------------------------------------------------- safe zone

def test_safe_zone_no_violation_when_text_well_inside():
    trim = _trimbox_for_mm(90.0, 50.0)
    # text 10mm from every edge, well past a 3mm safe zone
    x0, y0 = mm_to_pt(10.0), mm_to_pt(10.0)
    x1, y1 = mm_to_pt(40.0), mm_to_pt(20.0)
    violations = check_safe_zone_text(trim, [("Hello", (x0, y0, x1, y1))], safe_zone_mm=3.0)
    assert violations == []


def test_safe_zone_flags_text_too_close_to_edge():
    trim = _trimbox_for_mm(90.0, 50.0)
    # text starts 1mm from left edge, safe zone requires 3mm
    x0, y0 = mm_to_pt(1.0), mm_to_pt(20.0)
    x1, y1 = mm_to_pt(20.0), mm_to_pt(25.0)
    violations = check_safe_zone_text(trim, [("Тел: 000", (x0, y0, x1, y1))], safe_zone_mm=3.0)
    assert len(violations) == 1
    assert violations[0].side == "left"
    assert violations[0].crosses_trim is False
    assert violations[0].min_margin_mm == 1.0


def test_safe_zone_detects_text_crossing_trim_line():
    trim = _trimbox_for_mm(90.0, 50.0)
    # text starts before x0 (negative margin) — crosses the cut line
    x0, y0 = mm_to_pt(-2.0), mm_to_pt(20.0)
    x1, y1 = mm_to_pt(10.0), mm_to_pt(25.0)
    violations = check_safe_zone_text(trim, [("Logo", (x0, y0, x1, y1))], safe_zone_mm=3.0)
    assert len(violations) == 1
    assert violations[0].crosses_trim is True
    assert violations[0].min_margin_mm == -2.0


def test_safe_zone_ignores_text_outside_trim_entirely():
    trim = _trimbox_for_mm(90.0, 50.0)
    # a note far outside the trim area (e.g. artboard scratch text)
    x0, y0 = mm_to_pt(-50.0), mm_to_pt(-50.0)
    x1, y1 = mm_to_pt(-30.0), mm_to_pt(-40.0)
    violations = check_safe_zone_text(trim, [("scratch note", (x0, y0, x1, y1))], safe_zone_mm=3.0)
    assert violations == []


def test_safe_zone_ignores_empty_text():
    trim = _trimbox_for_mm(90.0, 50.0)
    x0, y0 = mm_to_pt(0.5), mm_to_pt(20.0)
    x1, y1 = mm_to_pt(5.0), mm_to_pt(25.0)
    violations = check_safe_zone_text(trim, [("   ", (x0, y0, x1, y1))], safe_zone_mm=3.0)
    assert violations == []


def test_safe_zone_sorted_by_severity_and_capped():
    trim = _trimbox_for_mm(90.0, 50.0)
    items = []
    for i in range(30):
        margin_mm = 30 - i  # decreasing margin, all violate a 30mm safe zone
        x0 = mm_to_pt(margin_mm)
        items.append((f"item{i}", (x0, mm_to_pt(20.0), x0 + mm_to_pt(2), mm_to_pt(22.0))))
    violations = check_safe_zone_text(trim, items, safe_zone_mm=100.0, max_results=25)
    assert len(violations) == 25
    # worst (smallest margin) first
    assert violations[0].min_margin_mm <= violations[-1].min_margin_mm


def test_pt_mm_roundtrip():
    assert abs(pt_to_mm(mm_to_pt(42.0)) - 42.0) < 1e-9
