"""Tiled palette quantization: Python port of rilden/tiledpalettequant."""

from .core import (
    HAVE_NUMBA,
    Cancelled,
    ColorZero,
    Dither,
    DitherPattern,
    Options,
    QuantizeResult,
    load_image,
    palette_image,
    quantize,
)

__version__ = "1.0.0"

__all__ = [
    "HAVE_NUMBA",
    "Cancelled",
    "ColorZero",
    "Dither",
    "DitherPattern",
    "Options",
    "QuantizeResult",
    "load_image",
    "palette_image",
    "quantize",
]
