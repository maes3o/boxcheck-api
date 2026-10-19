import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pymupdf

from geometry import mm_to_pt
from render_preview import (
    render_page_preview,
    render_ink_heatmap,
    render_cmyk_data_bitmap,
    _cmyk_pixmap_array,
)


def _blank_card_pdf(tmp_path):
    w_pt, h_pt = mm_to_pt(90.0), mm_to_pt(50.0)
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    path = str(tmp_path / "blank.pdf")
    doc.save(path)
    doc.close()
    return path


def _colorful_card_pdf(tmp_path):
    w_pt, h_pt = mm_to_pt(90.0), mm_to_pt(50.0)
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    # a dense dark rectangle -> high CMYK ink coverage when rendered
    page.draw_rect(pymupdf.Rect(0, 0, w_pt, h_pt), color=(0, 0, 0), fill=(0.05, 0.05, 0.05), width=0)
    path = str(tmp_path / "colorful.pdf")
    doc.save(path)
    doc.close()
    return path


def test_preview_renders_expected_dimensions(tmp_path):
    path = _blank_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    result = render_page_preview(page, max_dimension_px=900)
    doc.close()

    assert result["url"].startswith("data:image/png;base64,")
    # 90x50mm card -> aspect ratio 1.8; longest side scaled to ~900px
    assert result["width_px"] == 900
    assert 495 <= result["height_px"] <= 505
    assert result["scale"] > 0


def test_preview_scale_maps_points_to_pixels_correctly(tmp_path):
    path = _blank_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    result = render_page_preview(page, max_dimension_px=900)
    doc.close()

    page_w_pt = mm_to_pt(90.0)
    assert abs(page_w_pt * result["scale"] - result["width_px"]) < 1.5


def test_blank_page_heatmap_is_none(tmp_path):
    path = _blank_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    result = render_ink_heatmap(page)
    doc.close()
    assert result is None


def test_dense_page_heatmap_present_and_high_coverage(tmp_path):
    path = _colorful_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    result = render_ink_heatmap(page, max_dimension_px=600)
    doc.close()

    assert result is not None
    assert result["url"].startswith("data:image/png;base64,")
    assert result["max_coverage_pct"] > 50  # dark near-black fill -> high CMYK sum


def _pure_cyan_card_pdf(tmp_path):
    # A pure-cyan (C=255, M=0, Y=0, K=0) fill lets us assert the exact channel
    # mapping round-trips: R (=Cyan) should read ~255, G/B (~Magenta/Yellow)
    # should read ~0, the constant alpha should read ~255 (opaque — the alpha
    # byte must NOT carry K anymore), and the separate k_data plane should
    # read ~0 (K=0%).
    w_pt, h_pt = mm_to_pt(90.0), mm_to_pt(50.0)
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    w, h = 100, 60
    samples = bytes([255, 0, 0, 0] * (w * h))
    pix = pymupdf.Pixmap(pymupdf.csCMYK, w, h, samples, False)
    page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), pixmap=pix)
    path = str(tmp_path / "cyan.pdf")
    doc.save(path)
    doc.close()
    return path


def _pure_key_card_pdf(tmp_path):
    # A pure-black (C=0, M=0, Y=0, K=255) fill: the opaque CMY PNG must read
    # ~0 in R/G/B with alpha ~255, and the k_data plane must read ~255 (K=100%)
    # — proving K really moved out of the alpha slot into its own plane.
    w_pt, h_pt = mm_to_pt(90.0), mm_to_pt(50.0)
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    w, h = 100, 60
    samples = bytes([0, 0, 0, 255] * (w * h))
    pix = pymupdf.Pixmap(pymupdf.csCMYK, w, h, samples, False)
    page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt), pixmap=pix)
    path = str(tmp_path / "key.pdf")
    doc.save(path)
    doc.close()
    return path


def test_cmyk_data_bitmap_dimensions_and_scale_match_preview(tmp_path):
    path = _blank_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    preview = render_page_preview(page, max_dimension_px=900)
    cmyk = render_cmyk_data_bitmap(page, max_dimension_px=900)
    doc.close()

    assert cmyk["url"].startswith("data:image/png;base64,")
    assert cmyk["width_px"] == preview["width_px"]
    assert cmyk["height_px"] == preview["height_px"]
    assert cmyk["scale"] == preview["scale"]


def test_cmyk_data_bitmap_encodes_channels_as_rgba(tmp_path):
    path = _pure_cyan_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    result = render_cmyk_data_bitmap(page, max_dimension_px=400)
    doc.close()

    import base64
    import io
    from PIL import Image

    # Opaque CMY plane: constant alpha=255 (opaque) after the K-plane split —
    # K no longer travels in the alpha slot (canvas premultiplication
    # destroyed C/M/Y wherever K=0 there). K lives in k_data instead.
    header, b64data = result["url"].split(",", 1)
    img = Image.open(io.BytesIO(base64.b64decode(b64data)))
    assert img.mode == "RGBA"
    arr = np.array(img)
    # sample the center pixel: R (Cyan) should be near-full, G/B near-zero,
    # alpha is a constant 255
    cy, cx = arr.shape[0] // 2, arr.shape[1] // 2
    r, g, b, a = arr[cy, cx]
    assert r > 240
    assert g < 15
    assert b < 15
    assert a == 255

    # K plane: separate opaque grayscale PNG, direct polarity
    # (byte = 0-100% ink). Pure-cyan fill has K=0% -> plane reads ~0.
    k_header, k_b64data = result["k_data"]["url"].split(",", 1)
    k_img = Image.open(io.BytesIO(base64.b64decode(k_b64data)))
    assert k_img.mode == "L"
    k_arr = np.array(k_img)
    assert result["k_data"]["width_px"] == result["width_px"]
    assert result["k_data"]["height_px"] == result["height_px"]
    assert int(k_arr[cy, cx]) < 15


def test_cmyk_data_bitmap_k_plane_carries_key_ink(tmp_path):
    path = _pure_key_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    result = render_cmyk_data_bitmap(page, max_dimension_px=400)
    doc.close()

    import base64
    import io
    from PIL import Image

    header, b64data = result["url"].split(",", 1)
    img = Image.open(io.BytesIO(base64.b64decode(b64data)))
    arr = np.array(img)
    cy, cx = arr.shape[0] // 2, arr.shape[1] // 2
    r, g, b, a = arr[cy, cx]
    # pure-key fill: CMY plane reads ~0 with the constant opaque alpha
    assert r < 15
    assert g < 15
    assert b < 15
    assert a == 255

    k_header, k_b64data = result["k_data"]["url"].split(",", 1)
    k_img = Image.open(io.BytesIO(base64.b64decode(k_b64data)))
    assert k_img.mode == "L"
    k_arr = np.array(k_img)
    # K=100% -> plane reads near-full
    assert int(k_arr[cy, cx]) > 240


def test_cmyk_data_bitmap_reuses_precomputed_array(tmp_path):
    path = _blank_card_pdf(tmp_path)
    doc = pymupdf.open(path)
    page = doc[0]
    arr, _ = _cmyk_pixmap_array(page, max_dimension_px=500)
    result = render_cmyk_data_bitmap(page, max_dimension_px=500, cmyk_arr=arr)
    doc.close()

    assert result["width_px"] == arr.shape[1]
    assert result["height_px"] == arr.shape[0]
