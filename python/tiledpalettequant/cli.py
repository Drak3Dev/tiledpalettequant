"""Command line interface: quantize an image without the GUI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import core
from .core import ColorZero, Dither, DitherPattern, Options

COLOR_ZERO_CHOICES = {
    "unique": ColorZero.UNIQUE,
    "shared": ColorZero.SHARED,
    "transparent": ColorZero.TRANSPARENT_FROM_TRANSPARENT,
    "transparent-color": ColorZero.TRANSPARENT_FROM_COLOR,
}
DITHER_CHOICES = {"off": Dither.OFF, "fast": Dither.FAST, "slow": Dither.SLOW}
PATTERN_CHOICES = {p.name.lower(): p for p in DitherPattern}


def parse_color(text):
    text = text.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise argparse.ArgumentTypeError(f"expected a color like #ff00ff, got {text!r}")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a color like #ff00ff, got {text!r}") from None


def build_parser():
    p = argparse.ArgumentParser(
        prog="tiledpalettequant-cli",
        description="Quantize an image to tiles that each use one of several small palettes.",
    )
    p.add_argument("input", type=Path, help="input image")
    p.add_argument("-o", "--output", type=Path,
                   help="output image (.png or .bmp); default: <input>-<settings>.png next to the input")
    p.add_argument("-p", "--palette-output", type=Path,
                   help="palette image; default: <output>-palette.png")
    p.add_argument("--no-palette", action="store_true", help="don't write the palette image")
    p.add_argument("--tile-width", type=int, default=8, help="1..32 (default 8)")
    p.add_argument("--tile-height", type=int, default=8, help="1..32 (default 8)")
    p.add_argument("--palettes", type=int, default=8, help="1..16 (default 8)")
    p.add_argument("--colors", type=int, default=4, help="colors per palette, 2..256 (default 4)")
    p.add_argument("--bits", type=int, default=5, help="bits per channel, 2..8 (default 5)")
    p.add_argument("--fraction", type=float, default=0.1, help="fraction of pixels, 0.01..10 (default 0.1)")
    p.add_argument("--color-zero", choices=COLOR_ZERO_CHOICES, default="unique",
                   help="color index zero behaviour (default unique)")
    p.add_argument("--shared-color", type=parse_color, default=(0, 0, 0),
                   help="color for --color-zero shared (default #000000)")
    p.add_argument("--transparent-color", type=parse_color, default=(255, 0, 255),
                   help="color for the transparent modes (default #ff00ff)")
    p.add_argument("--dither", choices=DITHER_CHOICES, default="off", help="default off")
    p.add_argument("--dither-weight", type=float, default=0.5, help="0.01..1 (default 0.5)")
    p.add_argument("--dither-pattern", choices=PATTERN_CHOICES, default="diagonal4",
                   help="default diagonal4")
    p.add_argument("--seed", type=int, help="random seed for reproducible results")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    color_zero = COLOR_ZERO_CHOICES[args.color_zero]
    if color_zero == ColorZero.SHARED:
        zero_value = args.shared_color
    elif color_zero == ColorZero.UNIQUE:
        zero_value = (0, 0, 0)
    else:
        zero_value = args.transparent_color
    opts = Options(
        tile_width=args.tile_width,
        tile_height=args.tile_height,
        num_palettes=args.palettes,
        colors_per_palette=args.colors,
        bits_per_channel=args.bits,
        fraction_of_pixels=args.fraction,
        color_zero=color_zero,
        color_zero_value=zero_value,
        dither=DITHER_CHOICES[args.dither],
        dither_weight=args.dither_weight,
        dither_pattern=PATTERN_CHOICES[args.dither_pattern],
    ).validated()

    if not core.HAVE_NUMBA and not args.quiet:
        print("warning: numba is not installed, this will be very slow (pip install numba)",
              file=sys.stderr)

    rgba = core.load_image(args.input)
    output = args.output or args.input.with_name(args.input.stem + opts.settings_suffix() + ".png")
    palette_output = args.palette_output or output.with_name(output.stem + "-palette.png")

    def progress(value):
        if not args.quiet:
            print(f"\r{value:5.1f}%", end="", file=sys.stderr, flush=True)

    result = core.quantize(rgba, opts, progress=progress, seed=args.seed)
    if not args.quiet:
        print(file=sys.stderr)
    result.save_image(output)
    if not args.no_palette:
        result.save_palette(palette_output)
    if not args.quiet:
        print(f"{output}  ({result.elapsed:.1f} s, MSE {result.mse:.1f})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
