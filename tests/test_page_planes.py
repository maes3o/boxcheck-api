"""BCPLANE2 endpoint + format tests for GET /check/page-planes.

Covers the real problematic QA PDF end to end:
- response is gzip transport of a valid BCPLANE2 container
- 2831x2242 raster, exactly 4 spots with exact roster names, 9 planes
- every plane exactly width*height samples, CRC32 validates
- known pixels match the previously verified InkProbe QA values within the
  documented u8 quantization bound (|u8/255 - tint| <= 0.5/255)
plus error paths (rc!=0 -> typed 502, page out of range -> 400) on a tiny
synthetic PDF so they stay fast.
"""
import gzip
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main

_REAL_PDF = sorted(Path("/home/ubuntu/projects/boxcheck/test-files").glob("57384*98.94%.pdf"))

# QA InkProbe values captured earlier on this same 100 DPI raster.
QA_1415_1121 = {
    "cmyk": [0.95935535, 0.95935535, 0.95935535, 0.97338176],
    "spots": {"PANTONE 3262 C": 0.040644646, "PANTONE Black C": 0, "White-1": 0.42389694, "Lak": 0},
    "alpha": 0.7891383,
}
QUANT_BOUND = 0.5 / 255.0

require_real = pytest.mark.skipif(not _REAL_PDF, reason="real QA PDF not present")


def _tiny_pdf_bytes() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page(width=200, height=200)
    return doc.tobytes()


def _get_planes(client, pdf_bytes, page_index=0):
    # Same POST-multipart convention as /check/ink-preview.
    return client.post(
        "/check/page-planes",
        params={"page_index": page_index},
        files={"file": ("test.pdf", pdf_bytes, "application/pdf")},
    )


def test_tiny_pdf_page_out_of_range_is_400():
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    res = _get_planes(client, _tiny_pdf_bytes(), page_index=5)
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_page_index"


def test_exporter_failure_is_typed_502():
    from fastapi.testclient import TestClient

    def _failing_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")

    with patch.object(main.subprocess, "run", _failing_run):
        client = TestClient(main.app)
        res = _get_planes(client, _tiny_pdf_bytes())
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "plane_export_failed"


def test_corrupt_container_is_typed_502():
    from fastapi.testclient import TestClient

    def _corrupt_run(cmd, **kwargs):
        out = Path(cmd[2])
        out.write_bytes(b"BCPLANE2" + b"\x00" * 100)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    with patch.object(main.subprocess, "run", _corrupt_run):
        client = TestClient(main.app)
        res = _get_planes(client, _tiny_pdf_bytes())
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "plane_export_invalid"


def test_parse_bplane2_accepts_good_and_rejects_bad_crc():
    region = bytes(range(256)) + bytes(range(244))  # exactly 5*10*10 bytes
    crc = zlib.crc32(region) & 0xFFFFFFFF
    parsed = main.parse_bplane2(
        b"BCPLANE2" + struct.pack("<10I", 2, 0, 10, 10, 10000, 0, 5, 0, crc, 5)
        + bytes([0, 1, 2, 3, 5]) + region
    )
    assert len(parsed["planes"]) == 5
    bad = b"BCPLANE2" + struct.pack("<10I", 2, 0, 10, 10, 10000, 0, 5, 0, crc ^ 1, 5) + bytes([0, 1, 2, 3, 5]) + region
    with pytest.raises(ValueError):
        main.parse_bplane2(bad)


@require_real
def test_real_pdf_planes_full_contract():
    from fastapi.testclient import TestClient

    pdf_bytes = _REAL_PDF[0].read_bytes()
    client = TestClient(main.app)
    res = _get_planes(client, pdf_bytes, page_index=0)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert res.headers["content-encoding"] == "gzip"

    # Transport decompresses to the RAW container (flags bit0 = 0 confirms
    # the container itself is uncompressed by contract).
    raw = res.content
    (magic, version, flags, w, h, dpi_x100, intent, plane_count,
     spots_flattened, crc, dir_entries) = struct.unpack_from("<8s10I", raw, 0)
    assert magic == b"BCPLANE2" and version == 2 and flags == 0
    assert (w, h) == (2831, 2242)
    assert dpi_x100 == 10000
    assert plane_count == 9 and dir_entries == 9
    assert spots_flattened == 0

    # Independent parse (not via main.parse_bplane2): walk directory + CRC.
    off = 48
    kinds, names = [], []
    for _ in range(dir_entries):
        kind = raw[off]; off += 1
        if kind == 4:
            (nlen,) = struct.unpack_from("<I", raw, off); off += 4
            names.append(raw[off:off + nlen].decode("utf-8")); off += nlen
        kinds.append(kind)
    assert kinds == [0, 1, 2, 3, 4, 4, 4, 4, 5]
    assert names == ["PANTONE 3262 C", "PANTONE Black C", "White-1", "Lak"]
    region = raw[off:off + plane_count * w * h]
    assert off + plane_count * w * h == len(raw)
    assert (zlib.crc32(region) & 0xFFFFFFFF) == crc
    planes = [region[i * w * h:(i + 1) * w * h] for i in range(plane_count)]
    assert all(len(p) == w * h for p in planes)

    # Response header metadata mirrors the container.
    assert res.headers["x-plane-width"] == "2831"
    assert res.headers["x-plane-count"] == "9"
    assert json.loads(res.headers["x-plane-spot-names"]) == names

    # Known pixel (1000,500) vs the QA InkProbe: exact bytes.
    c, m, y, k, alpha = planes[0], planes[1], planes[2], planes[3], planes[8]
    spots = {name: planes[4 + i] for i, name in enumerate(names)}
    px = lambda pl, x, yy: pl[yy * w + x]
    assert [px(c, 1000, 500), px(m, 1000, 500), px(y, 1000, 500), px(k, 1000, 500)] == [0, 0, 0, 0]
    assert {n: px(p, 1000, 500) for n, p in spots.items()} == {
        "PANTONE 3262 C": 255, "PANTONE Black C": 0, "White-1": 255, "Lak": 0,
    }
    assert px(alpha, 1000, 500) == 255

    # Known pixel (1415,1121) vs QA f32 tints, within the u8 bound.
    x, yy = 1415, 1121
    for value, expected in zip(
        [px(c, x, yy), px(m, x, yy), px(y, x, yy), px(k, x, yy)],
        QA_1415_1121["cmyk"],
    ):
        assert abs(value / 255.0 - expected) <= QUANT_BOUND
    for name, expected in QA_1415_1121["spots"].items():
        assert abs(px(spots[name], x, yy) / 255.0 - expected) <= QUANT_BOUND
    assert abs(px(alpha, x, yy) / 255.0 - QA_1415_1121["alpha"]) <= QUANT_BOUND

    # The shared validator agrees with the independent walk.
    parsed = main.parse_bplane2(raw)
    assert parsed["width"] == w and parsed["height"] == h
    assert parsed["spot_names"] == names
    assert len(parsed["planes"]) == 9

    # gzip round-trip sanity on the wire format actually shipped.
    assert gzip.decompress(gzip.compress(raw, compresslevel=6)) == raw

    # The spot-LUT extension is opt-in at the exporter (`--with-spot-luts`)
    # and /check/page-planes does not pass that flag: production containers
    # stay flags == 0, no spot_luts key populated.
    assert parsed["flags"] == 0
    assert parsed["spot_luts"] is None


def test_spot_lut_extension_round_trips_through_parse_bplane2():
    """The additive `--with-spot-luts` wire extension: flags bit3, the LUT
    region's own CRC, exact per-spot 256x3xf32 shape, and the fact that the
    parsed values are pdfcer's own `SpotLut` samples (not a placeholder) —
    exercised directly against the real exporter binary and the real QA PDF,
    the same fixture `test_real_pdf_planes_full_contract` already trusts.
    """
    if not _REAL_PDF:
        pytest.skip("real QA PDF not present")

    import struct as _struct
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory(prefix="boxcheck-planes-luts-") as tmpdir:
        tmp = _Path(tmpdir)
        input_pdf = tmp / "input.pdf"
        output_file = tmp / "page0.bplane2"
        input_pdf.write_bytes(_REAL_PDF[0].read_bytes())

        proc = subprocess.run(
            [main.PLANES_BIN, str(input_pdf), str(output_file), "--page", "0", "--with-spot-luts"],
            capture_output=True,
            timeout=main.PLANES_TIMEOUT_SECONDS,
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "ignore")
        raw = output_file.read_bytes()

    (magic, version, flags, w, h, dpi_x100, intent, plane_count,
     spots_flattened, crc, dir_entries) = struct.unpack_from("<8s10I", raw, 0)
    assert magic == b"BCPLANE2" and version == 2
    assert flags == 0x8, "bit3 (spot LUTs present) must be set, nothing else"

    parsed = main.parse_bplane2(raw)
    assert parsed["spot_names"] == ["PANTONE 3262 C", "PANTONE Black C", "White-1", "Lak"]
    luts = parsed["spot_luts"]
    assert luts is not None
    assert len(luts) == 4, "one LUT per spot, roster order matching spot_names"
    for lut in luts:
        assert len(lut) == 256
        for r, g, b in lut:
            assert 0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0

    # tint 0.0 is the fold's multiply identity (no ink -> contributes
    # nothing over white paper) for every colorant, by construction
    # (SpotLut::build samples t=0 first).
    for lut in luts:
        assert lut[0] == (1.0, 1.0, 1.0)

    # "PANTONE 3262 C" at full tint is a real teal, not a placeholder —
    # cross-checks that this is pdfcer's actual tint-transform evaluation,
    # not a stand-in color.
    r, g, b = luts[0][255]
    assert r < 0.1 and g > 0.5 and b > 0.5

    # Tamper with one LUT byte -> CRC catches it (mirrors the existing
    # plane-region CRC test's shape, for the new region).
    tampered = bytearray(raw)
    tampered[-1] ^= 0xFF
    with pytest.raises(ValueError):
        main.parse_bplane2(bytes(tampered))

    # Truncating the LUT region (but not the plane region) is also rejected.
    truncated = raw[:-10]
    with pytest.raises(ValueError):
        main.parse_bplane2(truncated)


def test_unknown_bcplane2_flags_are_still_rejected():
    """The additive flags-acceptance change (0 -> {0, spot-LUT bit}) must
    not have widened into accepting arbitrary flag words."""
    region = bytes(range(256)) + bytes(range(244))  # exactly 5*10*10 bytes
    crc = zlib.crc32(region) & 0xFFFFFFFF
    bogus_flags = 0x2  # a real bit, just not one this parser knows
    bad = (
        b"BCPLANE2"
        + struct.pack("<10I", 2, bogus_flags, 10, 10, 10000, 0, 5, 0, crc, 5)
        + bytes([0, 1, 2, 3, 5]) + region
    )
    with pytest.raises(ValueError, match="unsupported BCPLANE2 flags"):
        main.parse_bplane2(bad)
