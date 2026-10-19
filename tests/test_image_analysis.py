import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pymupdf
from PIL import Image

from image_analysis import get_image_regions


def test_rgb_image_flagged():
    img = Image.new("RGB", (300, 200), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(50, 50, 250, 150), stream=buf.getvalue())

    regions = get_image_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0]["is_rgb"] is True
    assert regions[0]["is_cmyk"] is False


def test_high_dpi_image_not_flagged_low_dpi():
    # 900x600px placed into a 1x0.667 inch box -> 900 dpi, well above 300
    img = Image.new("RGB", (900, 600), (10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(0, 0, 72, 48), stream=buf.getvalue())

    regions = get_image_regions(page)
    doc.close()

    assert regions[0]["effective_dpi"] > 800
    assert regions[0]["low_dpi"] is False


def test_low_dpi_image_flagged():
    # 150x100px placed into a 3x2 inch box (216x144pt) -> 50 dpi
    img = Image.new("RGB", (150, 100), (10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(0, 0, 216, 144), stream=buf.getvalue())

    regions = get_image_regions(page)
    doc.close()

    assert regions[0]["effective_dpi"] < 100
    assert regions[0]["low_dpi"] is True


def test_bbox_matches_actual_placed_rect():
    img = Image.new("RGB", (300, 200), (0, 0, 0))  # aspect 1.5
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    # requested rect has a different aspect ratio (2.0) than the image (1.5);
    # insert_image preserves aspect and centers, so the true bbox differs
    # from the naive requested rect — get_image_regions must reflect what
    # was ACTUALLY placed, not the request.
    page.insert_image(pymupdf.Rect(50, 50, 250, 150), stream=buf.getvalue())

    regions = get_image_regions(page)
    doc.close()

    x0, y0, x1, y1 = regions[0]["bbox_pt"]
    assert 70 <= x0 <= 80
    assert 220 <= x1 <= 230


def test_cmyk_pixmap_not_flagged_rgb():
    # Build a raw CMYK pixmap directly (no PIL CMYK->PNG path needed)
    w, h = 100, 80
    samples = bytes([0, 0, 0, 255] * (w * h))  # solid K=255 (black), C=M=Y=0
    pix = pymupdf.Pixmap(pymupdf.csCMYK, w, h, samples, False)

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(0, 0, 100, 80), pixmap=pix)

    regions = get_image_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0]["is_cmyk"] is True
    assert regions[0]["is_rgb"] is False


def test_separation_colorspace_not_flagged_rgb():
    # Real-world case that broke this before the fix: die-line/dimension
    # markup images and gradient rasters embedded as Separation/DeviceN
    # (spot color) rather than DeviceRGB — e.g. Separation(Lab, PANTONE ...)
    # in a real packaging file, 28/28 misflagged "needs CMYK conversion"
    # before this test was written. insert_image only supports device
    # colorspaces directly, so a normal RGB image is inserted and its
    # /ColorSpace entry is overridden to a Separation array afterward —
    # mirrors what a real spot-color markup image looks like on disk.
    img = Image.new("RGB", (100, 100), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=buf.getvalue())
    img_xref = page.get_images(full=True)[0][0]
    doc.xref_set_key(
        img_xref, "ColorSpace",
        "[/Separation/Spot1/DeviceGray<</FunctionType 2/Domain[0 1]/C0[1]/C1[0]/N 1>>]",
    )

    regions = get_image_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0]["cs_name"].lower().startswith("separation")
    assert regions[0]["is_rgb"] is False


def test_gradient_separation_not_flagged_rgb():
    # Second validation for round-5 Issue B: the reported case was
    # specifically a GRADIENT (varying pixel values), not a flat spot-color
    # swatch like test_separation_colorspace_not_flagged_rgb above — the
    # original business-card file that surfaced this was never supplied by
    # Володимир, so this constructs the closest honest equivalent: a real
    # multi-value gradient raster, still declared in a Separation
    # colorspace rather than DeviceRGB, to confirm the fix generalizes past
    # a single solid-color test case.
    img = Image.linear_gradient("L").resize((100, 100)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=buf.getvalue())
    img_xref = page.get_images(full=True)[0][0]
    doc.xref_set_key(
        img_xref, "ColorSpace",
        "[/Separation/Spot1/DeviceGray<</FunctionType 2/Domain[0 1]/C0[1]/C1[0]/N 1>>]",
    )

    regions = get_image_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0]["cs_name"].lower().startswith("separation")
    assert regions[0]["is_rgb"] is False


def test_gradient_devicen_not_flagged_rgb():
    # Same as test_gradient_separation_not_flagged_rgb but for DeviceN
    # (multi-colorant spot) rather than Separation (single colorant) — the
    # task named both as candidates for what the original file "apparently
    # contained", so both get a permanent regression test rather than
    # guessing which one it actually was.
    img = Image.linear_gradient("L").resize((100, 100)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(50, 50, 150, 150), stream=buf.getvalue())
    img_xref = page.get_images(full=True)[0][0]
    doc.xref_set_key(
        img_xref, "ColorSpace",
        "[/DeviceN[/Spot1]/DeviceCMYK<</FunctionType 2/Domain[0 1]/C0[0 0 0 0]/C1[0 0 0 1]/N 1>>]",
    )

    regions = get_image_regions(page)
    doc.close()

    assert len(regions) == 1
    assert regions[0]["cs_name"].lower().startswith("devicen")
    assert regions[0]["is_rgb"] is False


def test_same_resource_placed_twice_shares_xref():
    # A repeated logo (same encoded bytes placed twice) is the case Phase C
    # exists for: two placements, one underlying resource.
    img = Image.new("RGB", (100, 100), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(pymupdf.Rect(0, 0, 100, 100), stream=data)
    page.insert_image(pymupdf.Rect(150, 150, 250, 250), stream=data)

    regions = get_image_regions(page)
    doc.close()

    assert len(regions) == 2
    assert regions[0]["xref"] == regions[1]["xref"]
    assert regions[0]["xref"] != 0


def test_no_images_returns_empty_list():
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    regions = get_image_regions(page)
    doc.close()
    assert regions == []
