"""Run with: python -m pytest tests  (or simply: python tests/test_core.py)"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiledpalettequant import core  # noqa: E402
from tiledpalettequant.core import ColorZero, Dither, DitherPattern, Options  # noqa: E402


def make_image(width=40, height=24, seed=0):
    rng = np.random.default_rng(seed)
    img = np.empty((height, width, 4), np.uint8)
    yy, xx = np.mgrid[0:height, 0:width]
    img[:, :, 0] = xx * 255 // max(width - 1, 1)
    img[:, :, 1] = yy * 255 // max(height - 1, 1)
    img[:, :, 2] = rng.integers(0, 256, (height, width))
    img[:, :, 3] = 255
    return img


def check_result(img, res, opts):
    h, w = img.shape[:2]
    cpp = opts.colors_per_palette
    assert res.rgba.shape == (h, w, 4)
    assert res.indices.shape == (h, w)
    assert res.palettes.shape == (opts.num_palettes, cpp, 3)
    assert res.indices.max() < opts.num_palettes * cpp
    # every pixel's color must come from its palette entry
    flat = res.palettes.reshape(-1, 3)
    opaque = res.rgba[:, :, 3] == 255
    if opts.is_transparent:
        opaque &= ~core.transparency_mask(img, opts)
    assert np.array_equal(res.rgba[opaque][:, :3], flat[res.indices[opaque]])
    # every tile uses a single palette
    pal_of = res.indices // cpp
    for ty in range(0, h, opts.tile_height):
        for tx in range(0, w, opts.tile_width):
            assert len(np.unique(pal_of[ty:ty + opts.tile_height, tx:tx + opts.tile_width])) == 1
    # palette colors are representable with the requested bit depth
    reduced = core.reduce_colors(res.palettes, opts.bits_per_channel)
    assert np.array_equal(reduced, res.palettes)


def test_modes():
    img = make_image()
    for cz in ColorZero:
        for dither in Dither:
            opts = Options(tile_width=8, tile_height=8, num_palettes=3, colors_per_palette=4,
                           color_zero=cz, color_zero_value=(255, 0, 255), dither=dither,
                           dither_pattern=DitherPattern.HORIZONTAL2)
            src = img.copy()
            src[0:5, 0:9, 3] = 0
            src[10:14, 20:30, :3] = (255, 0, 255)
            res = core.quantize(src, opts, seed=1)
            check_result(src, res, opts)
            if cz == ColorZero.SHARED:
                assert (res.palettes[:, 0] == core.reduce_colors((255, 0, 255), 5)).all()
            if opts.is_transparent:
                mask = core.transparency_mask(src, opts)
                assert (res.indices[mask] % 4 == 0).all()
                assert (res.indices[~mask] % 4 != 0).all()


def test_odd_sizes_and_limits():
    img = make_image(37, 19)
    for opts in (
        Options(tile_width=5, tile_height=3, num_palettes=1, colors_per_palette=2),
        Options(tile_width=1, tile_height=1, num_palettes=2, colors_per_palette=3, bits_per_channel=8),
        Options(tile_width=32, tile_height=32, num_palettes=16, colors_per_palette=20, bits_per_channel=2),
    ):
        res = core.quantize(img, opts, seed=2)
        check_result(img, res, opts.validated())


def test_seed_is_reproducible():
    img = make_image()
    a = core.quantize(img, Options(num_palettes=2), seed=5)
    b = core.quantize(img, Options(num_palettes=2), seed=5)
    assert np.array_equal(a.rgba, b.rgba)
    assert np.array_equal(a.palettes, b.palettes)


def test_cancel():
    img = make_image()
    try:
        core.quantize(img, Options(), should_stop=lambda: True)
    except core.Cancelled:
        return
    raise AssertionError("expected Cancelled")


def test_save_formats(tmp_path=None):
    import tempfile
    from PIL import Image

    tmp = Path(tmp_path or tempfile.mkdtemp())
    img = make_image()
    img[0:4, 0:4, 3] = 0
    res = core.quantize(img, Options(num_palettes=2, colors_per_palette=4,
                                     color_zero=ColorZero.TRANSPARENT_FROM_TRANSPARENT), seed=0)
    res.save_image(tmp / "a.png")
    res.save_image(tmp / "a.bmp")
    res.save_palette(tmp / "p.png")
    png = Image.open(tmp / "a.png")
    assert png.mode == "P" and "transparency" in png.info
    assert np.array_equal(np.asarray(png), res.indices)
    bmp = Image.open(tmp / "a.bmp")
    assert bmp.mode == "P" and np.array_equal(np.asarray(bmp), res.indices)
    assert Image.open(tmp / "p.png").size == (4 * 16, 2 * 16)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
