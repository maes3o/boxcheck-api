"""Round 12 phase B item 8: coverage for page1_has_declared_trimbox/
page1_has_declared_bleedbox — main.py's honest detection of whether a PDF's
own page dict actually declares a TrimBox/BleedBox, vs. pymupdf's
page.trimbox/bleedbox convenience properties, which silently fall back to
CropBox/MediaBox when neither is declared and would otherwise make it
impossible to tell "declared" from "defaulted" for the Document Geometry
card's "no declared BleedBox/TrimBox" messaging
(boxcheck_reaudit_questions_and_answers.md section 5).
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf

import main


def _make_pdf(declare_trimbox: bool) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    if declare_trimbox:
        page.set_trimbox(pymupdf.Rect(10, 10, 190, 190))
    page.insert_text((20, 20), "test", fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def test_declared_trimbox_detected():
    data = _make_pdf(declare_trimbox=True)
    result = main._check_pdf_sync(data, "declared.pdf", "unknown", None, "mm")
    assert result["page1_has_declared_trimbox"] is True


def test_undeclared_trimbox_detected():
    """pymupdf's own page.trimbox would silently return MediaBox here —
    the raw xref key is what actually distinguishes this from the
    declared case above."""
    data = _make_pdf(declare_trimbox=False)
    result = main._check_pdf_sync(data, "undeclared.pdf", "unknown", None, "mm")
    assert result["page1_has_declared_trimbox"] is False


def test_bleedbox_never_declared_by_this_fixture():
    """Neither fixture ever calls set_bleedbox — confirms the BleedBox
    check is independent of the TrimBox one, not accidentally coupled."""
    data = _make_pdf(declare_trimbox=True)
    result = main._check_pdf_sync(data, "declared.pdf", "unknown", None, "mm")
    assert result["page1_has_declared_bleedbox"] is False
