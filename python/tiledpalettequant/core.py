"""Tiled palette quantization.

Python port (written by Claude, Anthropic) of the algorithm by rilden from
https://github.com/rilden/tiledpalettequant (worker.js). The image is split into tiles, and every tile is drawn with one of
``num_palettes`` palettes of ``colors_per_palette`` colors each, like on retro
consoles (NES, SNES, GBA, Mega Drive...).

Hot loops are compiled with numba when it is installed. Without numba the very
same code runs as plain Python, which works but is dramatically slower.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Callable, Optional

import numpy as np

try:
    from numba import njit as _njit

    HAVE_NUMBA = True

    def jit(func):
        return _njit(cache=True, nogil=True)(func)

except ImportError:  # pragma: no cover - depends on the environment
    HAVE_NUMBA = False

    def jit(func):
        return func


class ColorZero(IntEnum):
    UNIQUE = 0
    SHARED = 1
    TRANSPARENT_FROM_TRANSPARENT = 2
    TRANSPARENT_FROM_COLOR = 3


class Dither(IntEnum):
    OFF = 0
    FAST = 1
    SLOW = 2


class DitherPattern(IntEnum):
    DIAGONAL4 = 0
    HORIZONTAL4 = 1
    VERTICAL4 = 2
    DIAGONAL2 = 3
    HORIZONTAL2 = 4
    VERTICAL2 = 5


DITHER_PATTERNS = {
    DitherPattern.DIAGONAL4: ((0, 2), (3, 1)),
    DitherPattern.HORIZONTAL4: ((0, 3), (1, 2)),
    DitherPattern.VERTICAL4: ((0, 1), (3, 2)),
    DitherPattern.DIAGONAL2: ((0, 1), (1, 0)),
    DitherPattern.HORIZONTAL2: ((0, 1), (0, 1)),
    DitherPattern.VERTICAL2: ((0, 0), (1, 1)),
}

COLOR_ZERO_ABBREVIATIONS = {
    ColorZero.UNIQUE: "u",
    ColorZero.SHARED: "s",
    ColorZero.TRANSPARENT_FROM_TRANSPARENT: "t",
    ColorZero.TRANSPARENT_FROM_COLOR: "tc",
}


def _clamp(value, lo, hi):
    return lo if value < lo else hi if value > hi else value


@dataclass
class Options:
    tile_width: int = 8
    tile_height: int = 8
    num_palettes: int = 8
    colors_per_palette: int = 4
    bits_per_channel: int = 5
    fraction_of_pixels: float = 0.1
    color_zero: ColorZero = ColorZero.UNIQUE
    color_zero_value: tuple = (0, 0, 0)
    dither: Dither = Dither.OFF
    dither_weight: float = 0.5
    dither_pattern: DitherPattern = DitherPattern.DIAGONAL4

    def validated(self) -> "Options":
        """Return a copy with every value clamped to the range the web UI allows."""
        return replace(
            self,
            tile_width=_clamp(int(self.tile_width), 1, 32),
            tile_height=_clamp(int(self.tile_height), 1, 32),
            num_palettes=_clamp(int(self.num_palettes), 1, 16),
            colors_per_palette=_clamp(int(self.colors_per_palette), 2, 256),
            bits_per_channel=_clamp(int(self.bits_per_channel), 2, 8),
            fraction_of_pixels=_clamp(float(self.fraction_of_pixels), 0.01, 10.0),
            color_zero=ColorZero(self.color_zero),
            color_zero_value=tuple(_clamp(int(c), 0, 255) for c in self.color_zero_value[:3]),
            dither=Dither(self.dither),
            dither_weight=_clamp(float(self.dither_weight), 0.01, 1.0),
            dither_pattern=DitherPattern(self.dither_pattern),
        )

    @property
    def total_colors(self) -> int:
        return self.num_palettes * self.colors_per_palette

    @property
    def is_transparent(self) -> bool:
        return self.color_zero in (
            ColorZero.TRANSPARENT_FROM_TRANSPARENT,
            ColorZero.TRANSPARENT_FROM_COLOR,
        )

    def settings_suffix(self) -> str:
        """File name suffix used by the original web app, e.g. ``-8x8-8p4c-u``."""
        return (
            f"-{self.tile_width}x{self.tile_height}"
            f"-{self.num_palettes}p{self.colors_per_palette}c"
            f"-{COLOR_ZERO_ABBREVIATIONS[self.color_zero]}"
        )


class Cancelled(Exception):
    """Raised from :func:`quantize` when ``should_stop`` returns True."""


# --------------------------------------------------------------------------
# Compiled kernels
# --------------------------------------------------------------------------

# alpha = 255 / (2 ** n - 1)
ALPHA_VALUES = np.array([0.0, 255.0, 85.0, 36.42857, 17.0, 8.22581, 4.04762, 2.00787, 1.0])


@jit
def _to_nbit(value, bits):
    alpha = ALPHA_VALUES[bits]
    return math.floor(math.floor(value / alpha + 0.5) * alpha + 0.5)


@jit
def _dist(pal, i, r, g, b):
    dr = pal[i, 0] - r
    dg = pal[i, 1] - g
    db = pal[i, 2] - b
    return 2.0 * dr * dr + 4.0 * dg * dg + db * db


@jit
def _closest_color(pal, r, g, b):
    # Scans from the end so that ties go to the highest index, as in the original.
    n = pal.shape[0]
    min_i = n - 1
    min_d = _dist(pal, min_i, r, g, b)
    for i in range(n - 2, -1, -1):
        d = _dist(pal, i, r, g, b)
        if d < min_d:
            min_i = i
            min_d = d
    return min_i, min_d


@jit
def _closest_color_dither(pal, r, g, b, x, y, weight, bits, pattern, ndp):
    lr = r * r
    lg = g * g
    lb = b * b
    er = 0.0
    eg = 0.0
    eb = 0.0
    # columns: color index, distance, brightness, compared color r, g, b
    cand = np.empty((4, 6))
    for i in range(ndp):
        cr = min(max(lr + er * weight, 0.0), 65025.0) ** 0.5
        cg = min(max(lg + eg * weight, 0.0), 65025.0) ** 0.5
        cb = min(max(lb + eb * weight, 0.0), 65025.0) ** 0.5
        mi, md = _closest_color(pal, cr, cg, cb)
        pr = pal[mi, 0]
        pg = pal[mi, 1]
        pb = pal[mi, 2]
        cand[i, 0] = mi
        cand[i, 1] = md
        cand[i, 2] = 0.299 * pr * pr + 0.587 * pg * pg + 0.114 * pb * pb
        cand[i, 3] = cr
        cand[i, 4] = cg
        cand[i, 5] = cb
        rr = _to_nbit(pr, bits)
        rg = _to_nbit(pg, bits)
        rb = _to_nbit(pb, bits)
        er += lr - rr * rr
        eg += lg - rg * rg
        eb += lb - rb * rb
    for i in range(ndp - 1):
        for j in range(i + 1, ndp):
            if cand[i, 2] > cand[j, 2]:
                for k in range(6):
                    tmp = cand[i, k]
                    cand[i, k] = cand[j, k]
                    cand[j, k] = tmp
    k = pattern[x & 1, y & 1]
    return int(cand[k, 0]), cand[k, 1], cand[k, 3], cand[k, 4], cand[k, 5]


@jit
def _palette_dist(pal, start, end, tc_col, tc_cnt):
    total = 0.0
    for i in range(start, end):
        _, d = _closest_color(pal, tc_col[i, 0], tc_col[i, 1], tc_col[i, 2])
        total += tc_cnt[i] * d
    return total


@jit
def _palette_dist_dither(pal, start, end, px_col, px_x, px_y, weight, bits, pattern, ndp):
    total = 0.0
    for p in range(start, end):
        _, d, _r, _g, _b = _closest_color_dither(
            pal, px_col[p, 0], px_col[p, 1], px_col[p, 2], px_x[p], px_y[p],
            weight, bits, pattern, ndp,
        )
        total += d
    return total


@jit
def _tile_palette_dist(pal, t, slow, tiles, dith):
    tc_start, tc_col, tc_cnt, tp_start, px_col, px_x, px_y, px_tile = tiles
    weight, bits, pattern, ndp = dith
    if slow:
        return _palette_dist_dither(
            pal, tp_start[t], tp_start[t + 1], px_col, px_x, px_y, weight, bits, pattern, ndp
        )
    return _palette_dist(pal, tc_start[t], tc_start[t + 1], tc_col, tc_cnt)


@jit
def _closest_palette(pals, t, slow, tiles, dith):
    num = pals.shape[0]
    if num == 1:
        return 0
    best = 0
    best_d = np.inf
    for p in range(num):
        d = _tile_palette_dist(pals[p], t, slow, tiles, dith)
        if d < best_d:
            best = p
            best_d = d
    return best


@jit
def _train(pals, seq, alpha, shared_idx, slow, tiles, dith):
    """Move the closest palette color towards randomly picked pixels."""
    tc_start, tc_col, tc_cnt, tp_start, px_col, px_x, px_y, px_tile = tiles
    weight, bits, pattern, ndp = dith
    beta = 1.0 - alpha
    for k in range(seq.shape[0]):
        p = seq[k]
        r = px_col[p, 0]
        g = px_col[p, 1]
        b = px_col[p, 2]
        pi = _closest_palette(pals, px_tile[p], slow, tiles, dith)
        if slow:
            ci, _d, tr, tg, tb = _closest_color_dither(
                pals[pi], r, g, b, px_x[p], px_y[p], weight, bits, pattern, ndp
            )
        else:
            ci, _d = _closest_color(pals[pi], r, g, b)
            tr = r
            tg = g
            tb = b
        if ci != shared_idx:
            pals[pi, ci, 0] = beta * pals[pi, ci, 0] + alpha * tr
            pals[pi, ci, 1] = beta * pals[pi, ci, 1] + alpha * tg
            pals[pi, ci, 2] = beta * pals[pi, ci, 2] + alpha * tb


@jit
def _palette_totals(pals, tiles, dith):
    """Sum of tile errors per palette, each tile counted for its closest palette."""
    tp_start = tiles[3]
    num_tiles = tp_start.shape[0] - 1
    out = np.zeros(pals.shape[0])
    for t in range(num_tiles):
        best = 0
        best_d = np.inf
        for p in range(pals.shape[0]):
            d = _tile_palette_dist(pals[p], t, False, tiles, dith)
            if d < best_d:
                best = p
                best_d = d
        out[best] += best_d
    return out


@jit
def _color_errors(pals, tiles, dith):
    tc_start, tc_col, tc_cnt = tiles[0], tiles[1], tiles[2]
    num_tiles = tc_start.shape[0] - 1
    out = np.zeros((pals.shape[0], pals.shape[1]))
    for t in range(num_tiles):
        pi = _closest_palette(pals, t, False, tiles, dith)
        for i in range(tc_start[t], tc_start[t + 1]):
            ci, d = _closest_color(pals[pi], tc_col[i, 0], tc_col[i, 1], tc_col[i, 2])
            out[pi, ci] += tc_cnt[i] * d
    return out


@jit
def _replace_stats(pals, slow, tiles, dith):
    tc_start, tc_col, tc_cnt, tp_start, px_col, px_x, px_y, px_tile = tiles
    weight, bits, pattern, ndp = dith
    num_pals = pals.shape[0]
    num_colors = pals.shape[1]
    num_tiles = tp_start.shape[0] - 1
    total_pal = np.zeros(num_pals)
    removed_pal = np.zeros(num_pals)
    total_col = np.zeros((num_pals, num_colors))
    second_col = np.zeros((num_pals, num_colors))
    dists = np.empty(num_pals)
    remaining = np.empty((max(num_colors - 1, 1), 3))
    for t in range(num_tiles):
        best = 0
        if num_pals > 1:
            best_d = np.inf
            for p in range(num_pals):
                dists[p] = _tile_palette_dist(pals[p], t, slow, tiles, dith)
                if dists[p] < best_d:
                    best = p
                    best_d = dists[p]
            second = np.inf
            for p in range(num_pals):
                if p != best and dists[p] < second:
                    second = dists[p]
            total_pal[best] += best_d
            removed_pal[best] += second
        if num_colors < 2:
            continue
        pal = pals[best]
        if slow:
            for p in range(tp_start[t], tp_start[t + 1]):
                ci, d, _r, _g, _b = _closest_color_dither(
                    pal, px_col[p, 0], px_col[p, 1], px_col[p, 2], px_x[p], px_y[p],
                    weight, bits, pattern, ndp,
                )
                total_col[best, ci] += d
                n = 0
                for j in range(num_colors):
                    if j != ci:
                        remaining[n, 0] = pal[j, 0]
                        remaining[n, 1] = pal[j, 1]
                        remaining[n, 2] = pal[j, 2]
                        n += 1
                _ci2, d2, _r, _g, _b = _closest_color_dither(
                    remaining, px_col[p, 0], px_col[p, 1], px_col[p, 2], px_x[p], px_y[p],
                    weight, bits, pattern, ndp,
                )
                second_col[best, ci] += d2
        else:
            for i in range(tc_start[t], tc_start[t + 1]):
                r = tc_col[i, 0]
                g = tc_col[i, 1]
                b = tc_col[i, 2]
                ci, d = _closest_color(pal, r, g, b)
                d2 = np.inf
                for j in range(num_colors):
                    if j != ci:
                        dj = _dist(pal, j, r, g, b)
                        if dj < d2:
                            d2 = dj
                total_col[best, ci] += d * tc_cnt[i]
                second_col[best, ci] += d2 * tc_cnt[i]
    return total_pal, removed_pal, total_col, second_col


@jit
def _kmeans(pals, slow, shared_idx, tiles, dith):
    tc_start, tc_col, tc_cnt, tp_start, px_col, px_x, px_y, px_tile = tiles
    weight, bits, pattern, ndp = dith
    num_pals = pals.shape[0]
    num_colors = pals.shape[1]
    num_tiles = tp_start.shape[0] - 1
    counts = np.zeros((num_pals, num_colors))
    sums = np.zeros((num_pals, num_colors, 3))
    for t in range(num_tiles):
        pi = _closest_palette(pals, t, slow, tiles, dith)
        if slow:
            for p in range(tp_start[t], tp_start[t + 1]):
                ci, _d, _r, _g, _b = _closest_color_dither(
                    pals[pi], px_col[p, 0], px_col[p, 1], px_col[p, 2], px_x[p], px_y[p],
                    weight, bits, pattern, ndp,
                )
                counts[pi, ci] += 1.0
                for c in range(3):
                    sums[pi, ci, c] += px_col[p, c]
        else:
            for i in range(tc_start[t], tc_start[t + 1]):
                ci, _d = _closest_color(pals[pi], tc_col[i, 0], tc_col[i, 1], tc_col[i, 2])
                counts[pi, ci] += tc_cnt[i]
                for c in range(3):
                    sums[pi, ci, c] += tc_col[i, c] * tc_cnt[i]
    for i in range(num_pals):
        for j in range(num_colors):
            for c in range(3):
                if counts[i, j] == 0.0 or j == shared_idx:
                    sums[i, j, c] = pals[i, j, c]
                else:
                    sums[i, j, c] /= counts[i, j]
    return sums


@jit
def _mean_square_error(pals, tiles, dith):
    tc_start, tc_col, tc_cnt = tiles[0], tiles[1], tiles[2]
    num_tiles = tc_start.shape[0] - 1
    total = 0.0
    count = 0.0
    for t in range(num_tiles):
        pi = _closest_palette(pals, t, False, tiles, dith)
        for i in range(tc_start[t], tc_start[t + 1]):
            _ci, d = _closest_color(pals[pi], tc_col[i, 0], tc_col[i, 1], tc_col[i, 2])
            total += d * tc_cnt[i]
            count += tc_cnt[i]
    return total / count


@jit
def _assign(pals, use_dither, tiles, dith):
    """Pick a palette for every tile and a color for every (non-transparent) pixel."""
    tc_start, tc_col, tc_cnt, tp_start, px_col, px_x, px_y, px_tile = tiles
    weight, bits, pattern, ndp = dith
    num_tiles = tp_start.shape[0] - 1
    tile_pal = np.zeros(num_tiles, np.int64)
    px_ci = np.zeros(px_col.shape[0], np.int64)
    for t in range(num_tiles):
        pi = _closest_palette(pals, t, use_dither, tiles, dith)
        tile_pal[t] = pi
        for p in range(tp_start[t], tp_start[t + 1]):
            if use_dither:
                ci, _d, _r, _g, _b = _closest_color_dither(
                    pals[pi], px_col[p, 0], px_col[p, 1], px_col[p, 2], px_x[p], px_y[p],
                    weight, bits, pattern, ndp,
                )
            else:
                ci, _d = _closest_color(pals[pi], px_col[p, 0], px_col[p, 1], px_col[p, 2])
            px_ci[p] = ci
    return tile_pal, px_ci


@jit
def _seed_jit_rng(seed):
    np.random.seed(seed)


@jit
def _reverse(a, left, right):
    while left < right:
        tmp = a[left]
        a[left] = a[right]
        a[right] = tmp
        left += 1
        right -= 1


@jit
def _cdist(a, b):
    return 2.0 * (a[0] - b[0]) ** 2 + 4.0 * (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


@jit
def _sort_palettes(pals, start):
    """Reorder palettes and colors so that similar colors share indexes.

    Colors before ``start`` stay in place (shared or transparent color zero).
    """
    pair_iterations = 2000
    t_iterations = 10000
    palette_iterations = 100000
    up_weight = 2.0
    num_pals = pals.shape[0]
    num_colors = pals.shape[1]
    if num_colors == 2 and start == 1:
        return pals.copy()

    # pal_dist[i + 1, j + 1] is the distance between palettes i and j
    pal_dist = np.zeros((num_pals + 2, num_pals + 2))
    # color_index[p1, p2, i] is the index in p2 of the color matching color i of p1
    color_index = np.empty((num_pals, num_pals, num_colors), np.int64)
    for i in range(num_pals):
        for j in range(num_pals):
            for k in range(num_colors):
                color_index[i, j, k] = k

    for p1 in range(num_pals - 1):
        for p2 in range(p1 + 1, num_pals):
            index = color_index[p1, p2]
            for _it in range(pair_iterations):
                i1 = start + int(np.random.random() * (num_colors - start - 1))
                i2 = i1 + 1 + int(np.random.random() * (num_colors - i1 - 1))
                if np.random.random() < 0.5:
                    i1, i2 = i2, i1
                straight = _cdist(pals[p1, i1], pals[p2, index[i1]]) + _cdist(
                    pals[p1, i2], pals[p2, index[i2]]
                )
                swapped = _cdist(pals[p1, i1], pals[p2, index[i2]]) + _cdist(
                    pals[p1, i2], pals[p2, index[i1]]
                )
                if swapped < straight:
                    tmp = index[i1]
                    index[i1] = index[i2]
                    index[i2] = tmp
            total = 0.0
            for i in range(num_colors):
                total += _cdist(pals[p1, i], pals[p2, index[i]])
            pal_dist[p1 + 1, p2 + 1] = total
            pal_dist[p2 + 1, p1 + 1] = total

    for p1 in range(1, num_pals):
        for p2 in range(p1):
            for i in range(num_colors):
                for j in range(num_colors):
                    if color_index[p2, p1, j] == i:
                        color_index[p1, p2, i] = j
                        break

    pal_index = np.arange(num_pals + 2)
    if num_pals > 2:
        for _it in range(palette_iterations):
            i1 = max(1, int(np.random.random() * num_pals))
            i2 = min(num_pals, i1 + 1 + int(np.random.random() * num_pals))
            straight = pal_dist[pal_index[i1 - 1], pal_index[i1]] + pal_dist[pal_index[i2], pal_index[i2 + 1]]
            swapped = pal_dist[pal_index[i1 - 1], pal_index[i2]] + pal_dist[pal_index[i1], pal_index[i2 + 1]]
            if swapped < straight:
                _reverse(pal_index, i1, i2)

    pal1 = pals[pal_index[1] - 1]
    p1_index = np.arange(num_colors + 2)
    p1_dist = np.zeros((num_colors + 2, num_colors + 2))
    for i in range(1, num_colors + 1):
        for j in range(1, num_colors + 1):
            p1_dist[i, j] = _cdist(pal1[i - 1], pal1[j - 1])
    if num_colors > 2:
        for _it in range(palette_iterations):
            i1 = max(1 + start, int(np.random.random() * num_colors))
            i2 = min(num_colors, i1 + 1 + int(np.random.random() * num_colors))
            straight = p1_dist[p1_index[i1 - 1], p1_index[i1]] + p1_dist[p1_index[i2], p1_index[i2 + 1]]
            swapped = p1_dist[p1_index[i1 - 1], p1_index[i2]] + p1_dist[p1_index[i1], p1_index[i2 + 1]]
            if swapped < straight:
                _reverse(p1_index, i1, i2)

    p_index = np.zeros((num_pals, num_colors), np.int64)
    for i in range(num_colors):
        p_index[0, i] = p1_index[i + 1] - 1
    for i in range(1, num_pals):
        p1 = pal_index[i] - 1
        p2 = pal_index[i + 1] - 1
        for j in range(num_colors):
            p_index[i, j] = color_index[p1, p2, p_index[i - 1, j]]

    if num_colors >= 4:
        for i in range(1, num_pals):
            p1 = pal_index[i] - 1
            p2 = pal_index[i + 1] - 1
            it = 0
            while it < t_iterations:
                a = max(start, int(np.random.random() * num_colors))
                b = max(start, int(np.random.random() * num_colors))
                if a == b:
                    continue
                up1 = p_index[i - 1, a]
                c1 = p_index[i, a]
                up2 = p_index[i - 1, b]
                c2 = p_index[i, b]
                straight = up_weight * _cdist(pals[p2, c1], pals[p1, up1])
                straight += up_weight * _cdist(pals[p2, c2], pals[p1, up2])
                swapped = up_weight * _cdist(pals[p2, c2], pals[p1, up1])
                swapped += up_weight * _cdist(pals[p2, c1], pals[p1, up2])
                if a > 0:
                    left1 = p_index[i, a - 1]
                    straight += _cdist(pals[p2, c1], pals[p2, left1])
                    swapped += _cdist(pals[p2, c2], pals[p2, left1])
                if a + 1 < num_colors:
                    right1 = p_index[i, a + 1]
                    straight += _cdist(pals[p2, c1], pals[p2, right1])
                    swapped += _cdist(pals[p2, c2], pals[p2, right1])
                if b > 0:
                    left2 = p_index[i, b - 1]
                    straight += _cdist(pals[p2, c2], pals[p2, left2])
                    swapped += _cdist(pals[p2, c1], pals[p2, left2])
                if b + 1 < num_colors:
                    right2 = p_index[i, b + 1]
                    straight += _cdist(pals[p2, c2], pals[p2, right2])
                    swapped += _cdist(pals[p2, c1], pals[p2, right2])
                if swapped < straight:
                    p_index[i, a] = c2
                    p_index[i, b] = c1
                it += 1

    out = np.empty_like(pals)
    for i in range(num_pals):
        src = pal_index[i + 1] - 1
        for j in range(num_colors):
            for c in range(3):
                out[i, j, c] = pals[src, p_index[i, j], c]
    return out


# --------------------------------------------------------------------------
# Python-level orchestration
# --------------------------------------------------------------------------


def reduce_colors(values, bits):
    """Round color components to ``bits`` bits per channel (kept in 0..255)."""
    alpha = ALPHA_VALUES[bits]
    values = np.asarray(values, dtype=np.float64)
    return np.floor(np.floor(values / alpha + 0.5) * alpha + 0.5)


def _f64(a):
    return np.ascontiguousarray(a, dtype=np.float64)


class _Tiles:
    """Flat arrays describing every non-empty tile, its unique colors and pixels."""

    def __init__(self, work_rgb, mask, tile_width, tile_height):
        height, width = mask.shape
        tiles_x = -(-width // tile_width)
        ys, xs = np.nonzero(~mask)
        if xs.size == 0:
            raise ValueError("image has no opaque pixels to quantize")
        grid_id = (ys // tile_height) * tiles_x + (xs // tile_width)
        order = np.argsort(grid_id, kind="stable")
        xs = xs[order].astype(np.int64)
        ys = ys[order].astype(np.int64)
        grid_id = grid_id[order]
        unique_ids, first, px_tile = np.unique(grid_id, return_index=True, return_inverse=True)
        num_tiles = unique_ids.size
        num_px = xs.size

        colors = work_rgb[ys, xs].astype(np.int64)
        packed = (colors[:, 0] << 16) | (colors[:, 1] << 8) | colors[:, 2]
        keys, counts = np.unique(px_tile.astype(np.int64) * (1 << 24) + packed, return_counts=True)
        tc_tile = keys >> 24
        tc_packed = keys & 0xFFFFFF
        tc_col = np.stack(
            [(tc_packed >> 16) & 255, (tc_packed >> 8) & 255, tc_packed & 255], axis=1
        )

        self.num_tiles = num_tiles
        self.tiles_x = tiles_x
        self.tiles_y = -(-height // tile_height)
        self.tile_gx = unique_ids % tiles_x
        self.tile_gy = unique_ids // tiles_x
        self.xs = xs
        self.ys = ys
        self.px_tile = px_tile.astype(np.int64).ravel()
        self.arrays = (
            np.searchsorted(tc_tile, np.arange(num_tiles + 1)).astype(np.int64),
            _f64(tc_col),
            _f64(counts),
            np.append(first, num_px).astype(np.int64),
            _f64(colors),
            xs,
            ys,
            self.px_tile,
        )

    @property
    def num_pixels(self):
        return self.xs.size


class _Shuffle:
    """Endless stream of pixel indexes, reshuffled after every full pass."""

    def __init__(self, n, rng):
        self.perm = np.arange(n, dtype=np.int64)
        self.pos = n
        self.rng = rng

    def take(self, count):
        parts = []
        while count > 0:
            if self.pos >= self.perm.size:
                self.rng.shuffle(self.perm)
                self.pos = 0
            chunk = self.perm[self.pos:self.pos + count]
            self.pos += chunk.size
            count -= chunk.size
            parts.append(chunk)
        return np.concatenate(parts) if len(parts) > 1 else parts[0].copy()


@dataclass
class QuantizeResult:
    rgba: np.ndarray
    """(H, W, 4) uint8 quantized image; transparent pixels keep their source values."""
    indices: np.ndarray
    """(H, W) global color index: palette * colors_per_palette + color."""
    palettes: np.ndarray
    """(num_palettes, colors_per_palette, 3) uint8, including color zero."""
    options: Options
    mse: float = 0.0
    elapsed: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def can_be_indexed(self) -> bool:
        return self.options.total_colors <= 256

    def image(self):
        from PIL import Image

        return Image.fromarray(self.rgba, "RGBA")

    def indexed_image(self, with_transparency=True):
        """8-bit paletted PIL image (only when there are at most 256 colors)."""
        from PIL import Image

        if not self.can_be_indexed:
            raise ValueError("more than 256 colors, can't build an indexed image")
        img = Image.fromarray(self.indices.astype(np.uint8), "P")
        flat = self.palettes.reshape(-1, 3).astype(np.uint8)
        pal = np.zeros((256, 3), np.uint8)
        pal[: flat.shape[0]] = flat
        img.putpalette(pal.tobytes())
        if with_transparency and self.options.is_transparent:
            alpha = np.full(flat.shape[0], 255, np.uint8)
            alpha[:: self.options.colors_per_palette] = 0
            img.info["transparency"] = alpha.tobytes()
        return img

    def palette_image(self):
        return palette_image(self.palettes)

    def _truecolor_image(self):
        img = self.image()
        if not self.options.is_transparent:
            img = img.convert("RGB")
        return img

    def save_image(self, path):
        """Save by extension: .bmp is always indexed, .png is indexed when possible."""
        ext = str(path).lower().rsplit(".", 1)[-1]
        if ext == "bmp":
            if self.can_be_indexed:
                self.indexed_image(with_transparency=False).save(path, format="BMP")
            else:
                self.image().convert("RGB").save(path, format="BMP")
        elif ext == "png":
            if self.can_be_indexed:
                img = self.indexed_image()
                kwargs = {}
                if "transparency" in img.info:
                    kwargs["transparency"] = img.info["transparency"]
                img.save(path, format="PNG", optimize=True, **kwargs)
            else:
                self._truecolor_image().save(path, format="PNG", optimize=True)
        else:
            self._truecolor_image().save(path)

    def save_palette(self, path):
        self.palette_image().save(path)


def palette_image(palettes):
    """Palette strip like in the web app: one row of 16px tall swatches per palette."""
    from PIL import Image

    pals = np.clip(np.rint(np.asarray(palettes, dtype=np.float64)), 0, 255).astype(np.uint8)
    num_pals, num_colors = pals.shape[:2]
    cell_w = min(16, math.ceil(512 / max(num_colors, 1)))
    cell_h = 16
    img = np.repeat(np.repeat(pals, cell_h, axis=0), cell_w, axis=1)
    return Image.fromarray(img, "RGB")


def _render(tiles, source_rgba, pals_q, tile_pal, px_ci, opts, adjusted):
    """Build the RGBA image and global indexes from palette/color assignments."""
    pals_u8 = np.clip(pals_q, 0, 255).astype(np.uint8)
    rgba = source_rgba.copy()
    rgba[tiles.ys, tiles.xs, :3] = pals_u8[tile_pal[tiles.px_tile], px_ci]
    rgba[tiles.ys, tiles.xs, 3] = 255

    height, width = source_rgba.shape[:2]
    grid = np.zeros((tiles.tiles_y, tiles.tiles_x), np.int64)
    grid[tiles.tile_gy, tiles.tile_gx] = tile_pal
    grid = np.repeat(np.repeat(grid, opts.tile_height, axis=0), opts.tile_width, axis=1)
    indices = grid[:height, :width] * opts.colors_per_palette
    indices[tiles.ys, tiles.xs] += px_ci + adjusted
    dtype = np.uint8 if opts.total_colors <= 256 else np.uint16
    return rgba, indices.astype(dtype)


def transparency_mask(rgba, opts):
    if opts.color_zero == ColorZero.TRANSPARENT_FROM_TRANSPARENT:
        return rgba[:, :, 3] < 255
    if opts.color_zero == ColorZero.TRANSPARENT_FROM_COLOR:
        return np.all(rgba[:, :, :3] == np.array(opts.color_zero_value, np.uint8), axis=2)
    return np.zeros(rgba.shape[:2], bool)


def quantize(
    rgba,
    options: Options,
    progress: Optional[Callable[[float], None]] = None,
    preview: Optional[Callable[[np.ndarray, np.ndarray], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    seed: Optional[int] = None,
) -> QuantizeResult:
    """Quantize an (H, W, 4) uint8 RGBA image.

    ``progress(percent)`` is called as work advances. ``preview(rgba, palettes)``
    receives intermediate results. If ``should_stop()`` returns True the run is
    aborted with :class:`Cancelled`.
    """
    t0 = time.perf_counter()
    opts = options.validated()
    rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected an (H, W, 4) RGBA array")

    rng = np.random.default_rng(seed)
    _seed_jit_rng(int(rng.integers(0, 2**31 - 1)))

    def report(value):
        if should_stop is not None and should_stop():
            raise Cancelled()
        if progress is not None:
            progress(float(value))

    report(0)

    slow = opts.dither == Dither.SLOW
    use_dither = opts.dither != Dither.OFF
    shared = opts.color_zero == ColorZero.SHARED
    shared_idx = 0 if shared else -1
    transparent = opts.is_transparent
    adjusted = 1 if transparent else 0
    bits = opts.bits_per_channel
    zero_value = np.array(opts.color_zero_value, np.float64)

    mask = transparency_mask(rgba, opts)
    work = rgba[:, :, :3] if use_dither else reduce_colors(rgba[:, :, :3], bits).astype(np.uint8)
    tiles = _Tiles(work, mask, opts.tile_width, opts.tile_height)
    tarr = tiles.arrays
    pattern = np.array(DITHER_PATTERNS[opts.dither_pattern], np.int64)
    ndp = 2 if opts.dither_pattern in (
        DitherPattern.DIAGONAL2, DitherPattern.HORIZONTAL2, DitherPattern.VERTICAL2
    ) else 4
    dith = (float(opts.dither_weight), int(bits), pattern, int(ndp))
    shuffle = _Shuffle(tiles.num_pixels, rng)

    iterations = opts.fraction_of_pixels * tiles.num_pixels
    alpha = 0.3
    final_alpha = 0.05
    if slow:
        iterations /= 5
        alpha = 0.1
        final_alpha = 0.02
    steps = max(1, math.ceil(iterations))

    def train(pals, count, a):
        _train(pals, shuffle.take(count), a, shared_idx, slow, tarr, dith)

    def mse(pals):
        return _mean_square_error(_f64(pals), tarr, dith)

    def display_palettes(pals):
        pals = np.asarray(pals)
        if transparent:
            zero = np.broadcast_to(reduce_colors(zero_value, bits), (pals.shape[0], 1, 3))
            pals = np.concatenate([zero, pals], axis=1)
        return pals

    def show(pals):
        if preview is None:
            return
        pals_q = _f64(reduce_colors(pals, bits))
        tile_pal, px_ci = _assign(pals_q, False, tarr, dith)
        image, _ = _render(tiles, rgba, pals_q, tile_pal, px_ci, opts, adjusted)
        preview(image, np.clip(np.rint(display_palettes(pals)), 0, 255).astype(np.uint8))

    end_index = opts.colors_per_palette - (1 if transparent else 0)
    start_index = 3 if shared else 2
    build_steps = (opts.num_palettes - 1) + max(0, end_index - start_index + 1) + 1
    build_done = 0

    def build_progress():
        nonlocal build_done
        build_done += 1
        report(25.0 * build_done / build_steps)

    # 1. Split palettes, one color each (two in shared mode).
    avg = tarr[4].mean(axis=0)
    pals = np.array([[zero_value, avg]] if shared else [[avg]], np.float64)
    split = 0
    for num in range(2, opts.num_palettes + 1):
        pals = np.ascontiguousarray(np.concatenate([pals, pals[split:split + 1]], axis=0))
        train(pals, steps, alpha)
        split = int(np.argmax(_palette_totals(pals, tarr, dith)))
        build_progress()
    show(pals)

    # 2. Grow every palette by one color at a time.
    for _num_colors in range(start_index, end_index + 1):
        if pals.shape[1] >= 2:
            split_idx = np.argmax(_color_errors(pals, tarr, dith), axis=1)
        else:
            split_idx = np.zeros(pals.shape[0], np.int64)
        new_colors = pals[np.arange(pals.shape[0]), split_idx][:, None, :]
        pals = np.ascontiguousarray(np.concatenate([pals, new_colors], axis=1))
        train(pals, steps, alpha)
        build_progress()
        show(pals)
    build_progress()

    # 3. Repeatedly replace the weakest colors/palettes and keep the best result.
    replace_iterations = 10
    min_mse = mse(pals)
    min_pals = pals.copy()
    for i in range(replace_iterations):
        pals = _replace_weakest(pals, slow, shared_idx, tarr, dith, 0.5, 0.5)
        train(pals, steps, alpha)
        m = mse(pals)
        if m < min_mse:
            min_mse = m
            min_pals = pals.copy()
        report(25 + 40 * (i + 1) / replace_iterations)
        show(min_pals if i == replace_iterations - 1 else pals)
    pals = min_pals

    # 4. Fine tuning with a smaller learning rate.
    if not use_dither:
        pals = _f64(reduce_colors(pals, bits))
    final_chunks = 10
    for i in range(final_chunks):
        train(pals, steps, final_alpha)
        report(65 + 25 * (i + 1) / final_chunks)

    # 5. A few k-means passes (only without dithering).
    if not use_dither:
        pals = _f64(reduce_colors(pals, bits))
        for i in range(3):
            pals = _kmeans(pals, slow, shared_idx, tarr, dith)
            report(90 + 8 * (i + 1) / 3)
    pals = reduce_colors(pals, bits)

    # 6. Sort so that similar colors line up, then draw the final image.
    sort_start = 1 if (shared or transparent) else 0
    sorted_pals = _sort_palettes(_f64(display_palettes(pals)), sort_start)
    pals_q = _f64(sorted_pals[:, 1:] if transparent else sorted_pals)
    tile_pal, px_ci = _assign(pals_q, use_dither, tarr, dith)
    image, indices = _render(tiles, rgba, pals_q, tile_pal, px_ci, opts, adjusted)
    final_mse = float(mse(pals_q))
    if progress is not None:
        progress(100.0)

    return QuantizeResult(
        rgba=image,
        indices=indices,
        palettes=np.clip(sorted_pals, 0, 255).astype(np.uint8),
        options=opts,
        mse=final_mse,
        elapsed=time.perf_counter() - t0,
    )


def _replace_weakest(pals, slow, shared_idx, tarr, dith, min_color_factor, min_palette_factor):
    total_pal, removed_pal, total_col, second_col = _replace_stats(pals, slow, tarr, dith)
    num_pals, num_colors = pals.shape[:2]
    result = pals.copy()
    if num_colors > 1:
        for p in range(num_pals):
            max_c = int(np.argmax(total_col[p]))
            min_c = int(np.argmin(second_col[p]))
            if (
                min_c != max_c
                and min_c != shared_idx
                and second_col[p, min_c] < min_color_factor * total_col[p, max_c]
            ):
                result[p, min_c] = pals[p, max_c]
    if num_pals > 1:
        max_p = int(np.argmax(total_pal))
        min_p = int(np.argmin(removed_pal))
        if min_p != max_p and removed_pal[min_p] < min_palette_factor * total_pal[max_p]:
            result[min_p] = result[max_p]
    return result


def load_image(path):
    """Load any Pillow-supported image as an (H, W, 4) uint8 RGBA array."""
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return np.asarray(img.convert("RGBA")).copy()


def warmup():
    """Compile (or load from cache) every numba kernel on a tiny image."""
    rng = np.random.default_rng(0)
    img = np.empty((16, 16, 4), np.uint8)
    img[:, :, :3] = rng.integers(0, 256, (16, 16, 3))
    img[:, :, 3] = 255
    quantize(img, Options(tile_width=4, tile_height=4, num_palettes=3, colors_per_palette=4,
                          fraction_of_pixels=0.5, dither=Dither.SLOW), seed=0)
    quantize(img, Options(tile_width=4, tile_height=4, num_palettes=3, colors_per_palette=4,
                          fraction_of_pixels=0.5), seed=0)
