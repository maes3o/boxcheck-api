"""Round 6 phase G: tests for the ICC-managed CMYK->sRGB LUT (cmyk_lut.py)."""

from __future__ import annotations

import cmyk_lut


def _idx(c: int, m: int, y: int, k: int, n: int) -> int:
    return ((c * n + m) * n + y) * n + k


def test_lut_byte_length_matches_grid():
    data = cmyk_lut.build_lut()
    assert len(data) == cmyk_lut.GRID_N**4 * 3


def test_white_corner_is_near_white():
    data = cmyk_lut.build_lut()
    i = _idx(0, 0, 0, 0, cmyk_lut.GRID_N) * 3
    r, g, b = data[i], data[i + 1], data[i + 2]
    assert r > 240 and g > 240 and b > 240


def test_k_only_is_dark_but_not_pure_black():
    # Real printer K ink isn't a perfect (0,0,0) black — a color-managed
    # profile should reflect that, unlike a naive formula that would just
    # invert K directly to (255-K, 255-K, 255-K).
    data = cmyk_lut.build_lut()
    last = cmyk_lut.GRID_N - 1
    i = _idx(0, 0, 0, last, cmyk_lut.GRID_N) * 3
    r, g, b = data[i], data[i + 1], data[i + 2]
    assert r < 100 and g < 100 and b < 100
    assert not (r == 0 and g == 0 and b == 0)


def test_rich_black_lightens_to_gray_not_white_without_k():
    # Round 3's original regression case, now against the real ICC LUT
    # instead of the naive formula: a rich-black mix (moderate C/M/Y + high
    # K) must lighten to a dark GRAY when K is removed, not jump to white,
    # because the remaining C/M/Y ink still contributes coverage.
    data = cmyk_lut.build_lut()
    n = cmyk_lut.GRID_N
    mid_high = n * 2 // 3  # a moderately-high but not maxed grid index
    last = n - 1

    with_k = _idx(mid_high, mid_high, mid_high, last, n) * 3
    without_k = _idx(mid_high, mid_high, mid_high, 0, n) * 3

    def luminance(base: int) -> float:
        r, g, b = data[base], data[base + 1], data[base + 2]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    lum_with_k = luminance(with_k)
    lum_without_k = luminance(without_k)

    assert lum_without_k > lum_with_k  # removing ink should lighten it...
    assert lum_without_k < 200  # ...but not anywhere near white


def test_get_lut_bytes_caches_to_disk_and_matches_build():
    built = cmyk_lut.build_lut()
    # Force a clean in-memory cache so this exercises the disk-cache path.
    cmyk_lut._lut_cache = None
    if cmyk_lut._CACHE_PATH.exists():
        cmyk_lut._CACHE_PATH.unlink()

    first = cmyk_lut.get_lut_bytes()
    assert first == built
    assert cmyk_lut._CACHE_PATH.exists()

    # Second call should come from the (now populated) in-memory cache and
    # be byte-identical, not a fresh (potentially non-deterministic) build.
    second = cmyk_lut.get_lut_bytes()
    assert second == first


def test_get_lut_bytes_rebuilds_on_stale_cache_size():
    cmyk_lut._lut_cache = None
    cmyk_lut._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cmyk_lut._CACHE_PATH.write_bytes(b"not the right size")

    data = cmyk_lut.get_lut_bytes()
    assert len(data) == cmyk_lut.GRID_N**4 * 3
