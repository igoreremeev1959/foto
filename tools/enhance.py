#!/usr/bin/env python3
"""
Restore old scanned monochrome photographs.

These are colour-cast, low-contrast scans of aged B&W paper prints, so the
pipeline works from luminance and keeps the tonal response gentle:

  1. auto-trim the white scanner margin around the photo
  2. gentle despeckle of scanner grain
  3. robust black/white point stretch (percentiles) + midtone gamma
  4. mild clip-limited local contrast (CLAHE-like, tile blended)
  5. unsharp mask for micro detail
  6. 1.5x Lanczos upscale, light warm print tone, thin white border

Usage: python3 tools/enhance.py [src_dir] [out_dir]
"""
import os
import sys

import numpy as np
from PIL import Image, ImageFilter, ImageOps

SCALE = 1.5
BORDER = 10
WARM = (1.03, 1.00, 0.955)
TARGET_STD = 62.0            # typical contrast of a well-printed frame   # barely-there warm print tone (0.98..1.0 for neutral)


def trim_margin(im):
    """Crop away the bright scanner surround / album page around the photo."""
    g = np.asarray(im.convert("L")).astype(float)
    h, w = g.shape
    k = 6
    frame = np.concatenate(
        [g[:k].ravel(), g[-k:].ravel(), g[:, :k].ravel(), g[:, -k:].ravel()]
    )
    ref = np.median(frame)
    if ref < 200:                       # no white surround to remove
        return im
    mask = np.abs(g - ref) > 20
    rows = np.where(mask.mean(1) > 0.03)[0]
    cols = np.where(mask.mean(0) > 0.03)[0]
    if len(rows) == 0 or len(cols) == 0:
        return im
    y0, y1 = rows.min(), rows.max() + 1
    x0, x1 = cols.min(), cols.max() + 1
    if (y1 - y0) < h * 0.25 or (x1 - x0) < w * 0.25:   # implausible, keep as is
        return im
    pad = 2
    return im.crop((max(x0 - pad, 0), max(y0 - pad, 0),
                    min(x1 + pad, w), min(y1 + pad, h)))


def despeckle(im):
    """Knock down scanner grain without flattening real texture."""
    g = im.convert("L").filter(ImageFilter.MedianFilter(3))
    return Image.blend(im.convert("L"), g, 0.55).convert("RGB")


def tonemap(im, black_pct=0.6, white_pct=99.6, mid_target=0.55):
    """Stretch the histogram, then put the midtones where they belong."""
    g = np.asarray(im.convert("L")).astype(np.float32)
    lo, hi = np.percentile(g, [black_pct, white_pct])
    if hi - lo < 25:                    # already full range
        lo, hi = float(g.min()), float(g.max())
    lo = max(lo - 3.0, 0.0)
    hi = min(hi + 5.0, 255.0)

    x = np.arange(256, dtype=np.float32) / 255.0
    y = np.clip((x * 255.0 - lo) / max(hi - lo, 1.0), 0.0, 1.0)

    mid = np.percentile(y, 50)
    if mid > 0.02:
        gamma = np.log(mid_target) / np.log(mid)
        gamma = float(np.clip(gamma, 0.55, 1.6))
        y = y ** gamma

    # very dark scans keep their shadows crushed: open them up a little
    if mid < 0.40:
        lift = float(np.clip((0.40 - mid) * 0.9, 0.0, 0.30))
        y = y + lift * y * (1.0 - y) ** 2 * 4.0 * 0.5
        y = np.clip(y, 0.0, 1.0)

    lut = np.clip(y * 255.0, 0, 255).astype(np.uint8)
    out = np.asarray(im.convert("RGB")).copy()
    for c in range(3):
        out[..., c] = lut[out[..., c]]
    out = out.astype(np.float32)

    # hazy / flat scans (small spread) get an extra gentle S-curve,
    # vivid ones are left alone
    spread = float(out.mean(2).std())
    amount = float(np.clip((TARGET_STD - spread) / TARGET_STD, 0.0, 0.38))
    if amount > 0.02:
        v = out / 255.0
        v = (v - 0.45) * (1.0 + amount) + 0.45
        out = np.clip(v, 0.0, 1.0) * 255.0

    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def flatten_light(im, radius=0.22, strength=0.55, limit=0.28):
    """Even out a scan's bright corner glare / dark vignetting."""
    g = np.asarray(im.convert("L")).astype(np.float32)
    h, w = g.shape
    small = Image.fromarray(g.astype(np.uint8)).resize(
        (max(w // 8, 8), max(h // 8, 8)), Image.BILINEAR
    )
    r = max(min(small.size) * radius, 1.0)
    bg = small.filter(ImageFilter.GaussianBlur(r)).resize((w, h), Image.BICUBIC)
    bgv = np.maximum(np.asarray(bg).astype(np.float32), 1.0)

    target = float(np.median(g)) or 1.0
    gain = np.clip(target / bgv, 1.0 - limit, 1.0 + limit)
    gain /= max(float(np.median(gain)), 1e-6)      # keep exposure as it was
    gain = 1.0 + strength * (gain - 1.0)

    out = np.asarray(im.convert("RGB")).astype(np.float32) * gain[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def local_contrast(im, tiles=8, clip=1.0, strength=0.26):
    """CLAHE-style tile equalisation applied as a luminance gain, then blended."""
    g = np.asarray(im.convert("L")).astype(np.float32)
    h, w = g.shape
    t = max(2, min(tiles, min(h, w) // 64 or 2))
    th, tw = max(h // t, 1), max(w // t, 1)

    eq = np.empty((h, w), np.float32)
    for ty in range(t):
        y0, y1 = ty * th, (h if ty == t - 1 else (ty + 1) * th)
        for tx in range(t):
            x0, x1 = tx * tw, (w if tx == t - 1 else (tx + 1) * tw)
            tile = g[y0:y1, x0:x1]
            hist = np.bincount(tile.ravel().astype(np.uint8), minlength=256).astype(np.float32)
            hist = np.minimum(hist, max(clip * tile.size / 256.0, 1.0))
            cdf = np.cumsum(hist)
            rng = max(cdf[-1] - cdf[0], 1.0)
            lut = ((cdf - cdf[0]) / rng * 255.0).astype(np.uint8)
            eq[y0:y1, x0:x1] = lut[tile.astype(np.uint8)]

    # kill the tile grid with a blur the size of one tile
    eq_im = Image.fromarray(np.clip(eq, 0, 255).astype(np.uint8))
    eq_im = eq_im.filter(ImageFilter.GaussianBlur(max(th, tw) * 0.9))
    eqv = np.asarray(eq_im).astype(np.float32)

    gain = (eqv + 8.0) / (g + 8.0)
    gain = 1.0 + strength * (gain - 1.0)
    # keep the overall brightness untouched: only redistribute locally
    m = float(np.average(gain, weights=np.maximum(g, 1.0)))
    gain /= max(m, 1e-6)
    out = np.asarray(im.convert("RGB")).astype(np.float32) * gain[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def match_contrast(im, target=TARGET_STD, max_amount=0.45):
    """Nudge flat frames up to the contrast of the well-printed ones."""
    a = np.asarray(im.convert("L")).astype(np.float32)
    spread = float(a.std())
    amount = float(np.clip((target - spread) / target, 0.0, max_amount))
    if amount < 0.02:
        return im
    v = np.asarray(im.convert("RGB")).astype(np.float32) / 255.0
    out = (v - 0.5) * (1.0 + amount) + 0.5
    # fade the boost out of the extreme highlights so paper stays clean
    w = np.clip((0.85 - v) / 0.25, 0.0, 1.0)
    out = v + (out - v) * w
    return Image.fromarray(np.clip(out * 255.0, 0, 255).astype(np.uint8))


def enhance(path, out_path, warm=WARM):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im = trim_margin(im)
    im = despeckle(im)
    im = flatten_light(im)
    im = tonemap(im)
    im = local_contrast(im)
    im = match_contrast(im)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.5, percent=70, threshold=4))

    w, h = im.size
    im = im.resize((int(round(w * SCALE)), int(round(h * SCALE))), Image.LANCZOS)
    im = im.filter(ImageFilter.UnsharpMask(radius=1.1, percent=40, threshold=3))

    a = np.asarray(im).astype(np.float32) * np.array(warm, np.float32)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    canvas = Image.new("RGB", (im.width + 2 * BORDER, im.height + 2 * BORDER), "white")
    canvas.paste(im, (BORDER, BORDER))
    canvas.save(out_path, quality=95, subsampling=0, optimize=True)
    return im.size


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "."
    out = sys.argv[2] if len(sys.argv) > 2 else "restored"
    os.makedirs(out, exist_ok=True)
    for name in sorted(os.listdir(src)):
        if not name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        size = enhance(os.path.join(src, name), os.path.join(out, name))
        print(f"{name} -> {size[0]}x{size[1]}")


if __name__ == "__main__":
    main()
