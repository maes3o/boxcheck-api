import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pymupdf
from PIL import Image

from geometry import mm_to_pt
from checks import (
    check_product_format_match,
    check_safe_zone,
    check_safe_zone_multi,
    check_image_quality,
    build_annotations,
    run_tier1_product_checks,
)


def _trimbox_for_mm(w_mm: float, h_mm: float):
    return (0.0, 0.0, mm_to_pt(w_mm), mm_to_pt(h_mm))


def test_format_match_ok_severity():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = check_product_format_match(trim, "business_card")
    assert result["severity"] == "ok"
    assert "message_ua" in result and "message_en" in result


def test_format_match_business_card_85x55_iso():
    # Round 12 phase F item 20 — the single most-missing business card
    # format per the source doc's own priority call-out.
    trim = _trimbox_for_mm(85.0, 55.0)
    result = check_product_format_match(trim, "business_card")
    assert result["severity"] == "ok"
    assert result["details"]["matched_format_id"] == "eu_85x55"


def test_format_match_label_round_uses_bounding_square():
    # Round 12 phase F item 22 — a round label has no separate "diameter"
    # field in ProductFormat; represented as width_mm == height_mm (the
    # circle's own bounding square) — a 25×25mm trimbox should match the
    # "Round, 25 mm" catalog entry, not read as a tiny rectangular label.
    trim = _trimbox_for_mm(25.0, 25.0)
    result = check_product_format_match(trim, "label_sticker")
    assert result["severity"] == "ok"
    assert result["details"]["matched_format_id"] == "round_25mm"


def test_format_match_poster_a0():
    # Round 12 phase F item 21 — A0 added; large-format DPI/profile logic
    # deliberately untouched (no approved backend numbers exist for it).
    trim = _trimbox_for_mm(841.0, 1189.0)
    result = check_product_format_match(trim, "poster")
    assert result["severity"] == "ok"
    assert result["details"]["matched_format_id"] == "a0"


def test_format_match_no_product_selected_is_info():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = check_product_format_match(trim, None)
    assert result["severity"] == "info"


def test_format_match_unknown_product_is_info():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = check_product_format_match(trim, "not_a_real_product")
    assert result["severity"] == "info"


def test_format_match_wrong_size_is_warning():
    trim = _trimbox_for_mm(100.0, 60.0)
    result = check_product_format_match(trim, "business_card")
    assert result["severity"] == "warning"
    assert result["details"]["deviation_mm"] > 0
    # Round 12 phase G: consequence sentence appended to the message.
    assert "неправильного розміру" in result["message_ua"]
    assert "wrong size" in result["message_en"]


def test_format_match_explicit_format_mismatch_is_warning():
    trim = _trimbox_for_mm(210.0, 297.0)  # A4 dims, but format=a6 requested
    result = check_product_format_match(trim, "flyer", format_id="a6")
    assert result["severity"] == "warning"
    assert result["details"]["expected_format_id"] == "a6"
    assert "неправильного розміру" in result["message_ua"]


def test_format_match_product_without_catalog_is_info():
    # Round 12 phase F: label_sticker got a real formats[] catalog (see
    # products.py), so it's no longer a "no catalog" example — a 50×50mm
    # trimbox now legitimately matches the new "Round, 50 mm" entry
    # (represented as a 50×50mm bounding square). packaging_box still has
    # formats: [] this phase (Phase F deliberately didn't add packaging
    # sizes — see PROGRESS.md), so it still exercises this code path.
    trim = _trimbox_for_mm(50.0, 50.0)
    result = check_product_format_match(trim, "packaging_box")
    assert result["severity"] == "info"


def test_safe_zone_ok_when_clear():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    result = check_safe_zone(trim, text_items, "business_card")
    assert result["severity"] == "ok"


def test_safe_zone_warning_when_close():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(0.5), mm_to_pt(10), mm_to_pt(20), mm_to_pt(15)))]
    result = check_safe_zone(trim, text_items, "business_card")
    assert result["severity"] == "warning"
    assert result["details"]["violation_count"] == 1
    # Round 12 phase G: consequence sentence appended to the message.
    assert "можуть бути обрізані" in result["message_ua"]
    assert "may be cut" in result["message_en"]


def test_safe_zone_critical_when_crossing_trim():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Logo", (mm_to_pt(-2), mm_to_pt(10), mm_to_pt(5), mm_to_pt(15)))]
    result = check_safe_zone(trim, text_items, "business_card")
    assert result["severity"] == "critical"
    assert "можуть бути обрізані" in result["message_ua"]


def test_safe_zone_info_when_no_product():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = check_safe_zone(trim, [], None)
    assert result["severity"] == "info"


def test_run_tier1_product_checks_returns_two_results():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    results, _status, _eff_pid, _eff_fid = run_tier1_product_checks(trim, text_items, "business_card")
    assert len(results) == 2
    checks = {r["check"] for r in results}
    assert checks == {"product_format_match", "safe_zone"}
    assert all(r["severity"] == "ok" for r in results)


def test_run_tier1_product_checks_no_product_no_trimbox_is_none_status():
    # Round 11 phase B: today's baseline case, unchanged — no product, and
    # no real TrimBox to auto-detect from (has_real_trimbox=False, e.g.
    # TrimBox == MediaBox) — both checks stay genuinely skipped.
    trim = _trimbox_for_mm(90.0, 50.0)
    results, status, _eff_pid, _eff_fid = run_tier1_product_checks(trim, [], None, has_real_trimbox=False)
    assert status == "none"
    by_check = {r["check"]: r for r in results}
    assert by_check["product_format_match"]["severity"] == "info"
    assert by_check["safe_zone"]["severity"] == "info"


def test_run_tier1_product_checks_auto_detects_from_real_trimbox():
    # No product selected, but the file's own TrimBox exactly matches a
    # catalog format (business_card eu_90x50) and has_real_trimbox=True —
    # should auto-detect and actually run the safe-zone check instead of
    # skipping it.
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    results, status, eff_pid, eff_fid = run_tier1_product_checks(trim, text_items, None, has_real_trimbox=True)
    assert status == "auto_trimbox"
    by_check = {r["check"]: r for r in results}
    assert by_check["product_format_match"]["severity"] == "ok"
    assert "автоматично визначено" in by_check["product_format_match"]["message_ua"]
    assert by_check["safe_zone"]["severity"] == "ok"
    assert "автоматично визначено" in by_check["safe_zone"]["message_ua"]
    # Round 12 phase E item 2: the auto-detect confirmation banner needs the
    # EFFECTIVE (auto-matched) ids, not None — main.py previously echoed
    # back the raw (unset) query params here instead of these.
    assert eff_pid == "business_card"
    assert eff_fid is not None


def test_run_tier1_product_checks_declared_size_matches_catalog():
    # No product, no usable real TrimBox, but a declared custom size that
    # matches a catalog format — should auto-detect from the declared size
    # even though has_real_trimbox is False.
    trim = _trimbox_for_mm(90.0, 50.0)  # the PDF's own geometry, irrelevant here
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    results, status, _eff_pid, _eff_fid = run_tier1_product_checks(
        trim, text_items, None, has_real_trimbox=False,
        declared_width_mm=90.0, declared_height_mm=50.0,
    )
    assert status == "auto_declared"
    by_check = {r["check"]: r for r in results}
    assert by_check["product_format_match"]["severity"] == "ok"
    assert "введеному розміру" in by_check["product_format_match"]["message_ua"]


def test_run_tier1_product_checks_declared_size_no_match_uses_generic_fallback():
    # Declared size doesn't match anything in the catalog — format-match
    # check stays "skipped" (nothing to compare a made-up size against),
    # but safe-zone still runs with a clearly-labeled generic margin
    # instead of being skipped outright.
    trim = _trimbox_for_mm(137.0, 61.0)
    text_items = [("Logo", (mm_to_pt(1), mm_to_pt(10), mm_to_pt(20), mm_to_pt(15)))]
    results, status, _eff_pid, _eff_fid = run_tier1_product_checks(
        trim, text_items, None, has_real_trimbox=False,
        declared_width_mm=137.0, declared_height_mm=61.0,
    )
    assert status == "declared_no_match"
    by_check = {r["check"]: r for r in results}
    assert by_check["product_format_match"]["severity"] == "info"
    assert by_check["safe_zone"]["severity"] in ("warning", "critical")
    assert "орієнтовний відступ" in by_check["safe_zone"]["message_ua"]
    assert by_check["safe_zone"]["details"]["required_safe_zone_mm"] == 5.0


def test_every_tier1_product_default_format_matches_itself():
    from products import PRODUCTS
    for product_id, product in PRODUCTS.items():
        if product["tier"] != 1:
            continue
        for fmt in product["formats"]:
            trim = _trimbox_for_mm(fmt["width_mm"], fmt["height_mm"])
            result = check_product_format_match(trim, product_id, format_id=fmt["id"])
            assert result["severity"] == "ok", f"{product_id}/{fmt['id']} should self-match"


def _page_with_rgb_image(w_mm=90.0, h_mm=50.0):
    doc = pymupdf.open()
    page = doc.new_page(width=mm_to_pt(w_mm), height=mm_to_pt(h_mm))
    img = Image.new("RGB", (150, 100), (200, 50, 50))  # low-res + RGB -> both flags
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page.insert_image(pymupdf.Rect(0, 0, mm_to_pt(w_mm), mm_to_pt(h_mm)), stream=buf.getvalue())
    return doc, page


def test_image_quality_no_images_is_info():
    doc = pymupdf.open()
    page = doc.new_page(width=mm_to_pt(90), height=mm_to_pt(50))
    result = check_image_quality(page)
    doc.close()
    assert result["severity"] == "info"
    assert result["details"] is None


def test_image_quality_flags_rgb_and_low_dpi():
    doc, page = _page_with_rgb_image()
    result = check_image_quality(page)
    doc.close()
    assert result["severity"] == "warning"
    assert result["details"]["rgb_count"] == 1
    assert result["details"]["low_dpi_count"] == 1
    assert len(result["details"]["regions"]) == 1
    # Round 12 phase G: both RGB and low-DPI consequence sentences should
    # be present since both problems are flagged on this image.
    assert "Кольори зображення можуть змінитися" in result["message_ua"]
    assert "нечітким" in result["message_ua"]
    assert "colors may change" in result["message_en"]
    assert "soft, blurry" in result["message_en"]


def test_image_quality_all_clean_is_ok():
    doc = pymupdf.open()
    w_pt, h_pt = mm_to_pt(90), mm_to_pt(50)
    page = doc.new_page(width=w_pt, height=h_pt)
    # high-res CMYK image -> neither rgb nor low_dpi flag should trip
    w, h = 1200, 800
    samples = bytes([0, 0, 0, 255] * (w * h))
    pix = pymupdf.Pixmap(pymupdf.csCMYK, w, h, samples, False)
    page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), pixmap=pix)
    result = check_image_quality(page)
    doc.close()
    assert result["severity"] == "ok"
    assert result["details"]["rgb_count"] == 0
    assert result["details"]["low_dpi_count"] == 0


def test_image_quality_counts_unique_resource_not_placements():
    # Phase C: the same embedded image placed twice (once small/high-DPI,
    # once large/low-DPI) is ONE image resource that needs fixing, not two —
    # image_count/rgb_count/low_dpi_count must reflect that, even though
    # `regions` (used for canvas pins) still has one entry per placement.
    img = Image.new("RGB", (150, 100), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=mm_to_pt(200), height=mm_to_pt(200))
    page.insert_image(pymupdf.Rect(0, 0, 40, 26.7), stream=data)  # small -> high DPI
    page.insert_image(pymupdf.Rect(50, 50, 500, 350), stream=data)  # large -> low DPI

    result = check_image_quality(page)
    doc.close()

    assert result["details"]["image_count"] == 1
    assert result["details"]["rgb_count"] == 1
    assert result["details"]["low_dpi_count"] == 1
    assert len(result["details"]["regions"]) == 2


def test_build_annotations_merges_safe_zone_and_image_regions():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("X" * 5, (mm_to_pt(85), mm_to_pt(10), mm_to_pt(95), mm_to_pt(15)))]
    sz = check_safe_zone(trim, text_items, "business_card")

    doc, page = _page_with_rgb_image()
    iq = check_image_quality(page)
    doc.close()

    annotations = build_annotations(sz, iq)
    kinds = {a["kind"] for a in annotations}
    assert "safe_zone_violation" in kinds
    assert "rgb_image" in kinds
    assert "low_dpi_image" in kinds
    for a in annotations:
        assert "bbox_pt" in a and "label_ua" in a and "label_en" in a and "severity" in a


def test_build_annotations_empty_when_nothing_flagged():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    sz = check_safe_zone(trim, text_items, "business_card")

    doc = pymupdf.open()
    page = doc.new_page(width=mm_to_pt(90), height=mm_to_pt(50))
    iq = check_image_quality(page)
    doc.close()

    assert build_annotations(sz, iq) == []


def test_build_annotations_groups_repeated_rgb_resource():
    # Round 6 phase E: the same RGB resource placed many times (e.g. a
    # repeated background texture) must collapse into ONE pin with a count,
    # not one pin per placement — this is the "84 individual pins for one
    # recurring issue" problem the phase exists to fix.
    img = Image.new("RGB", (150, 100), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=mm_to_pt(200), height=mm_to_pt(200))
    page.insert_image(pymupdf.Rect(0, 0, 40, 26.7), stream=data)
    page.insert_image(pymupdf.Rect(50, 50, 500, 350), stream=data)
    page.insert_image(pymupdf.Rect(100, 100, 300, 200), stream=data)

    sz = {"check": "safe_zone", "severity": "info", "details": None}
    iq = check_image_quality(page)
    doc.close()

    annotations = build_annotations(sz, iq)
    rgb_annotations = [a for a in annotations if a["kind"] == "rgb_image"]
    assert len(rgb_annotations) == 1
    assert rgb_annotations[0]["count"] == 3
    assert len(rgb_annotations[0]["instances"]) == 3
    assert "×3" in rgb_annotations[0]["label_ua"]


def test_run_tier1_product_checks_with_page_adds_image_quality():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    doc, page = _page_with_rgb_image()
    results, _status, _eff_pid, _eff_fid = run_tier1_product_checks(trim, text_items, "business_card", page=page)
    doc.close()
    checks = {r["check"] for r in results}
    assert checks == {"product_format_match", "safe_zone", "image_quality"}


# --- Phase D: real multi-page checking ---------------------------------


def test_safe_zone_multi_single_page_passthrough():
    trim = _trimbox_for_mm(90.0, 50.0)
    clean_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    result = check_safe_zone_multi([(trim, clean_items)], "business_card")
    assert result == check_safe_zone(trim, clean_items, "business_card")


def test_safe_zone_multi_no_product_is_info():
    trim = _trimbox_for_mm(90.0, 50.0)
    result = check_safe_zone_multi([(trim, []), (trim, [])], None)
    assert result["severity"] == "info"


def test_safe_zone_multi_all_pages_clean_is_ok():
    trim = _trimbox_for_mm(90.0, 50.0)
    clean_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    result = check_safe_zone_multi([(trim, clean_items), (trim, clean_items)], "business_card")
    assert result["severity"] == "ok"
    assert result["details"] is None
    assert "2" in result["message_ua"]


def test_safe_zone_multi_aggregates_across_pages():
    # A violation on page 2 must not go unreported just because page 1 (the
    # only one with a canvas render) is clean.
    trim = _trimbox_for_mm(90.0, 50.0)
    clean_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]
    crossing_items = [("X" * 5, (mm_to_pt(85), mm_to_pt(10), mm_to_pt(95), mm_to_pt(15)))]

    result = check_safe_zone_multi([(trim, clean_items), (trim, crossing_items)], "business_card")

    assert result["severity"] == "critical"  # crosses_trim on page 2
    assert result["details"]["pages_with_violations"] == [2]
    assert result["details"]["violation_count"] == 1
    # page 1's own violations stay empty — nothing to pin on page 1's canvas
    assert result["details"]["violations"] == []
    assert "стор. 2" in result["message_ua"]
    # Round 12 phase A item 3: the message must still name WHAT the page-2
    # violation actually is (text + side), not just its page number and
    # count — confirmed missing via a live 2-page test before this fix,
    # since details["violations"] being page-1-only left this message as
    # the reader's only source of detail for a non-page-1 violation.
    assert "XXXXX" in result["message_ua"]
    assert "XXXXX" in result["message_en"]


def test_image_quality_multi_page_aggregates_and_scopes_regions_to_page1():
    # page 1: one RGB, low-res image. page 2: one clean high-res CMYK image.
    doc, _ = _page_with_rgb_image()
    page2 = doc.new_page(width=mm_to_pt(90), height=mm_to_pt(50))
    w, h = 1200, 800
    samples = bytes([0, 0, 0, 255] * (w * h))
    pix = pymupdf.Pixmap(pymupdf.csCMYK, w, h, samples, False)
    page2.insert_image(pymupdf.Rect(0, 0, mm_to_pt(90), mm_to_pt(50)), pixmap=pix)
    # Re-fetch fresh Page wrappers: doc.new_page() above can invalidate a
    # Page object obtained before it, so grab both by index right before use
    # rather than reusing the earlier `page1` handle.
    page1, page2 = doc[0], doc[1]

    result = check_image_quality([page1, page2])
    doc.close()

    assert result["details"]["image_count"] == 2  # both pages counted
    assert result["details"]["rgb_count"] == 1
    assert result["details"]["low_dpi_count"] == 1
    assert len(result["details"]["regions"]) == 1  # page 1 only, for canvas pins


def test_run_tier1_product_checks_multi_page_aggregates_image_quality():
    trim = _trimbox_for_mm(90.0, 50.0)
    text_items = [("Ivan Petrenko", (mm_to_pt(10), mm_to_pt(10), mm_to_pt(40), mm_to_pt(15)))]

    doc, _ = _page_with_rgb_image()
    page2 = doc.new_page(width=mm_to_pt(90), height=mm_to_pt(50))
    w, h = 1200, 800
    samples = bytes([0, 0, 0, 255] * (w * h))
    pix = pymupdf.Pixmap(pymupdf.csCMYK, w, h, samples, False)
    page2.insert_image(pymupdf.Rect(0, 0, mm_to_pt(90), mm_to_pt(50)), pixmap=pix)
    page1, page2 = doc[0], doc[1]

    results, _status, _eff_pid, _eff_fid = run_tier1_product_checks(trim, text_items, "business_card", page=[page1, page2])
    doc.close()

    checks = {r["check"] for r in results}
    assert checks == {"product_format_match", "safe_zone", "image_quality"}
    iq = next(r for r in results if r["check"] == "image_quality")
    assert iq["details"]["image_count"] == 2
