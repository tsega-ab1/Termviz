#!/usr/bin/env python3
"""Fast pixel-array -> braille conversion (numpy, no Python pixel loops).

Each terminal character packs a 2-wide x 4-tall block of pixels into one
Unicode braille glyph (U+2800..U+28FF): a white pixel becomes a raised dot.
"""

import numpy as np

# dot weights for the 4 rows x 2 columns of one braille cell
_WEIGHTS = np.array([[0x01, 0x08],
                     [0x02, 0x10],
                     [0x04, 0x20],
                     [0x40, 0x80]], dtype=np.uint32)


def braille_lines(bw_arr, threshold=128):
    """bw_arr: 2D array. Returns a list of strings, one per 4 pixel rows.
    Sizes that aren't multiples of 4x2 are padded with off pixels."""
    on = np.asarray(bw_arr) >= threshold
    pad_h, pad_w = (-on.shape[0]) % 4, (-on.shape[1]) % 2
    if pad_h or pad_w:
        on = np.pad(on, ((0, pad_h), (0, pad_w)))
    h, w = on.shape
    blocks = on.reshape(h // 4, 4, w // 2, 2).astype(np.uint32)
    codes = (blocks * _WEIGHTS[None, :, None, :]).sum(axis=(1, 3)) + 0x2800
    codes = np.ascontiguousarray(codes, dtype="<u4")
    return [row.tobytes().decode("utf-32-le") for row in codes]
