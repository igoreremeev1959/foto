"""Restoration pipeline for old scanned family photos (B&W scans and colourised copies).

    python3 tools_restore.py IN.jpg OUT.jpg [--scale 2] [--denoise 4] [--mode bw|color|auto]

Pipeline (each stage optional, tuned for film scans):

  1. dust_scratch  - detect small specks and thin bright scratches, inpaint
  2. denoise       - edge-preserving (non-local means)
  3. flatten       - partially even out flash hotspots / flare / vignetting
  4. auto_levels   - percentile tone stretch
  5. keep_brightness - gamma back so overall exposure matches the original
  6. unsharp       - luminance-only sharpening at native resolution
  7. upscale       - Lanczos 2x (sharpen *before* upscaling)
  8. grain         - whisper of film grain so it does not look plastic

Why the two modes: a monochrome scan is stored as RGB with a tiny random
channel imbalance. Stretching each channel separately amplifies that imbalance
into coloured speckles, so B&W jobs are processed on a neutral duplicate of the
luminance (bit-identical channels => exactly zero colour noise), while colour
jobs only touch luminance and clean the chroma channels separately.
"""
import sys

import cv2
import numpy as np


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #
def dust_scratch(img, speck_thresh=45, max_speck_area=70,
                 scratch_thresh=34, max_scratch_area=1200):
    """Inpaint isolated bright/dark specks and thin bright scratch lines."""
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    med = cv2.medianBlur(grey, 5)
    diff = cv2.absdiff(grey, med)

    # --- small specks (dust) ------------------------------------------------ #
    mask = cv2.threshold(diff, speck_thresh, 255, cv2.THRESH_BINARY)[1]
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    specks = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] <= max_speck_area:
            specks[lab == i] = 255

    # --- thin bright scratches --------------------------------------------- #
    tophat = cv2.morphologyEx(grey, cv2.MORPH_TOPHAT,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    cand = cv2.threshold(tophat, scratch_thresh, 255, cv2.THRESH_BINARY)[1]
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
    lines = np.zeros_like(mask)
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        elong = max(w, h) / max(1, min(w, h))
        fill = area / float(w * h)
        if 40 < area <= max_scratch_area and elong >= 5 and fill < 0.45:
            lines[lab == i] = 255

    mask = cv2.bitwise_or(specks, lines)
    if not mask.any():
        return img
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
    return cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)


def denoise(img, strength=4, chromatic=False):
    """strength in NLM units; chromatic also smooths colour noise."""
    if chromatic:
        return cv2.fastNlMeansDenoisingColored(img, None, strength, strength, 7, 21)
    return cv2.fastNlMeansDenoising(img, None, strength, 7, 21)


def flatten(img, sigma_frac=0.16, strength=0.75, lo=0.62, hi=1.55):
    """Even out large-scale illumination: flash hotspots, flare, vignetting."""
    f = img.astype(np.float32)
    L = f.mean(axis=2) if f.ndim == 3 else f
    sigma = max(img.shape[:2]) * sigma_frac
    bg = cv2.GaussianBlur(L, (0, 0), sigma)
    target = float(np.median(bg))
    gain = np.clip(np.power(target / np.maximum(bg, 1.0), strength), lo, hi)
    out = f * (gain[..., None] if f.ndim == 3 else gain)
    return np.clip(out, 0, 255).astype(np.uint8)


def auto_levels(img, lo=1.0, hi=99.0):
    out = np.empty_like(img)
    chans = [img] if img.ndim == 2 else [img[..., c] for c in range(img.shape[2])]
    res = []
    for ch in chans:
        a, b = np.percentile(ch, [lo, hi])
        a = min(a, b - 8)
        res.append(np.clip((ch.astype(np.float32) - a) * (255.0 / max(b - a, 1)), 0, 255)
                   .astype(np.uint8))
    if img.ndim == 2:
        return res[0]
    for c in range(img.shape[2]):
        out[..., c] = res[c]
    return out


def keep_brightness(img, target_median):
    """Gamma-correct so median luminance matches the original frame."""
    L = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    cur = float(np.median(L))
    target = float(target_median)
    if cur <= 1 or target <= 1:
        return img
    gamma = float(np.clip(np.log(target / 255.0) / np.log(cur / 255.0), 0.5, 2.0))
    lut = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(img, lut)


def unsharp(img, amount=0.65, radius=1.1, thresh=3):
    """Luminance-only sharpening: no colour fringing, no chroma noise boost."""
    if img.ndim == 2:
        L = img.astype(np.float32)
        Lb = cv2.GaussianBlur(L, (0, 0), radius)
        d = L - Lb
        d[np.abs(d) < thresh] = 0
        return np.clip(L + amount * d, 0, 255).astype(np.uint8)

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L = lab[..., 0].astype(np.float32)
    Lb = cv2.GaussianBlur(L, (0, 0), radius)
    d = L - Lb
    d[np.abs(d) < thresh] = 0
    lab[..., 0] = np.clip(L + amount * d, 0, 255).astype(np.uint8)
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def clean_chroma(img, blur=5, gain=1.0):
    """Median-smooth the colour channels so chroma noise cannot sparkle."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, a, b = cv2.split(lab)
    a = cv2.medianBlur(a, blur)
    b = cv2.medianBlur(b, blur)
    if gain != 1.0:
        a = np.clip(128 + (a.astype(np.float32) - 128) * gain, 0, 255).astype(np.uint8)
        b = np.clip(128 + (b.astype(np.float32) - 128) * gain, 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([L, a, b]), cv2.COLOR_LAB2BGR)


def upscale(img, scale=2):
    if scale <= 1:
        return img
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)


def grain(img, sigma=1.3, seed=7):
    rng = np.random.default_rng(seed)
    n = rng.normal(0, sigma, img.shape[:2]).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), 0.7)
    if img.ndim == 3:
        n = n[..., None]
    return np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
# pipelines
# --------------------------------------------------------------------------- #
def _finish(img, target_median, scale, add_grain, keep_bright):
    if keep_bright:
        img = keep_brightness(img, target_median)
    img = upscale(img, scale)
    if add_grain:
        img = grain(img)
    return img


def restore_bw(path, out_path=None, scale=2, denoise_strength=5,
               flatten_strength=0.55, level_lo=0.7, level_hi=99.3,
               sharpen=0.7, add_grain=True, keep_bright=True, tint=None):
    """Clean a monochrome scan. `tint` = optional (B,G,R) float gain for sepia etc."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("cannot read " + path)

    # work on a neutral grey duplicate: identical channels => zero colour noise
    img = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    target = float(np.median(img[..., 0]))

    img = dust_scratch(img)
    if denoise_strength:
        img = denoise(img, denoise_strength)
    if flatten_strength:
        img = flatten(img, strength=flatten_strength)
    img = auto_levels(img, level_lo, level_hi)
    if sharpen:
        img = unsharp(img, amount=sharpen)

    out = _finish(img, target, scale, add_grain, keep_bright)

    if tint is not None:
        out = np.clip(out.astype(np.float32) * np.array(tint, np.float32), 0, 255).astype(np.uint8)

    if out_path:
        cv2.imwrite(out_path, out, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return out


def restore_color(path, out_path=None, scale=2, denoise_strength=3.5,
                  flatten_strength=0.35, level_lo=0.7, level_hi=99.3,
                  sharpen=0.55, add_grain=True, keep_bright=True, chroma_gain=1.06,
                  speck_thresh=45):
    """Clean a colourised copy: full tone work, but colour is touched gently."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("cannot read " + path)

    target = float(np.median(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)))

    img = dust_scratch(img, speck_thresh=speck_thresh)
    if denoise_strength:
        img = denoise(img, denoise_strength, chromatic=True)
    if flatten_strength:
        img = flatten(img, strength=flatten_strength)

    # tone on luminance only, so hues are not stretched per channel
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L = auto_levels(lab[..., 0], level_lo, level_hi)
    img = cv2.cvtColor(cv2.merge([L, lab[..., 1], lab[..., 2]]), cv2.COLOR_LAB2BGR)

    img = clean_chroma(img, blur=3, gain=chroma_gain)
    if sharpen:
        img = unsharp(img, amount=sharpen)

    out = _finish(img, target, scale, add_grain, keep_bright)

    if out_path:
        cv2.imwrite(out_path, out, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return out


def auto_tint(path, max_gain=0.10):
    """Derive a gentle per-channel gain from the scan's own colour cast.

    Old prints often sit slightly warm/sepia even when "black and white".
    Restoring them neutral is safe but loses that character, so we measure the
    cast and re-apply a clipped, normalised version of it.
    Returns (B, G, R) gains or None when the scan is essentially neutral.
    """
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("cannot read " + path)
    means = img.reshape(-1, 3).mean(axis=0)          # B, G, R
    ref = float(means.mean())
    if ref <= 1:
        return None
    gains = np.clip(means / ref, 1.0 - max_gain, 1.0 + max_gain)
    if np.abs(gains - 1.0).max() < 0.015:            # already neutral
        return None
    return tuple(float(g) for g in gains)


def looks_monochrome(path, threshold=34.0):
    """Mean max-min channel spread: small => monochrome (possibly sepia) scan."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("cannot read " + path)
    a = img.astype(np.int16)
    return float((a.max(2) - a.min(2)).mean()) < threshold


def restore(path, out_path=None, mode="auto", auto_tint_cast=True, **kw):
    if mode == "auto":
        mode = "bw" if looks_monochrome(path) else "color"
    if mode == "bw":
        if auto_tint_cast and "tint" not in kw:
            kw["tint"] = auto_tint(path)
        return restore_bw(path, out_path, **kw)
    return restore_color(path, out_path, **kw)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--"))
    if len(args) != 2:
        raise SystemExit(__doc__)
    restore(args[0], args[1],
            mode=opts.get("mode", "auto"),
            scale=float(opts.get("scale", 2)),
            denoise_strength=float(opts.get("denoise", 4)))
    print("written", args[1])
