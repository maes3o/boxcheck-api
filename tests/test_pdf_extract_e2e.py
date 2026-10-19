"""End-to-end test: build a real PDF with pymupdf (business-card size, with a
TrimBox and some text placed dangerously close to the left edge), then run it
through pdf_extract.py + checks.py exactly as main.py would. This is the one
test that exercises the actual pymupdf extraction glue, not just the pure
geometry math.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf

from geometry import mm_to_pt
from pdf_extract import get_trimbox_pt, get_text_items_pt
from checks import run_tier1_product_checks


def _make_business_card_pdf(tmp_path, text_x_mm: float) -> str:
    w_pt, h_pt = mm_to_pt(90.0), mm_to_pt(50.0)
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.set_trimbox(page.mediabox)  # trim == full page, exact (avoids float rounding vs mediabox)
    page.insert_text((mm_to_pt(text_x_mm), mm_to_pt(25)), "Ivan Petrenko", fontsize=10)
    path = str(tmp_path / "card.pdf")
    doc.save(path)
    doc.close()
    return path


def test_e2e_safe_card_passes_both_checks(tmp_path):
    path = _make_business_card_pdf(tmp_path, text_x_mm=10.0)  # well clear of 3mm safe zone
    doc = pymupdf.open(path)
    page = doc[0]

    trimbox_pt = get_trimbox_pt(page)
    text_items = get_text_items_pt(page)
    results, _status, _eff_pid, _eff_fid = run_tier1_product_checks(trimbox_pt, text_items, "business_card")
    doc.close()

    by_check = {r["check"]: r for r in results}
    assert by_check["product_format_match"]["severity"] == "ok"
    assert by_check["safe_zone"]["severity"] == "ok"


def test_e2e_text_too_close_to_edge_flagged(tmp_path):
    path = _make_business_card_pdf(tmp_path, text_x_mm=1.0)  # 1mm from edge, needs 3mm
    doc = pymupdf.open(path)
    page = doc[0]

    trimbox_pt = get_trimbox_pt(page)
    text_items = get_text_items_pt(page)
    assert len(text_items) == 1  # sanity: extraction actually found the text
    results, _status, _eff_pid, _eff_fid = run_tier1_product_checks(trimbox_pt, text_items, "business_card")
    doc.close()

    by_check = {r["check"]: r for r in results}
    assert by_check["safe_zone"]["severity"] == "warning"
    assert by_check["safe_zone"]["details"]["violation_count"] == 1


def test_e2e_wrong_size_flagged(tmp_path):
    w_pt, h_pt = mm_to_pt(120.0), mm_to_pt(80.0)  # not a standard business-card size
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.set_trimbox(page.mediabox)
    path = str(tmp_path / "wrong_size.pdf")
    doc.save(path)
    doc.close()

    doc = pymupdf.open(path)
    page = doc[0]
    trimbox_pt = get_trimbox_pt(page)
    text_items = get_text_items_pt(page)
    results, _status, _eff_pid, _eff_fid = run_tier1_product_checks(trimbox_pt, text_items, "business_card")
    doc.close()

    by_check = {r["check"]: r for r in results}
    assert by_check["product_format_match"]["severity"] == "warning"
