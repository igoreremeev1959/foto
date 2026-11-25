#!/usr/bin/env python3
"""Batch restoration of the whole photo set.

For every original scan it writes two improved versions:

    restored/bw/<name>.jpg     - cleaned-up black & white scan
    restored/color/<name>.jpg  - cleaned-up version of the colorized copy
                                 (taken from color/<name> — цвет.jpg)

and regenerates index.html with a three-column before/after/colour gallery.

    python3 make_restored.py
"""
import os
import html
from urllib.parse import quote

import cv2

import tools_restore as tr

# original  ->  colorized copy
PAIRS = [
    ("изоб 1.jpg",  "изоб 1 — цвет.jpg",  "Малыш в коляске"),
    ("изоб2.jpg",   "изоб2 — цвет.jpg",   "Девочка и малыш с игрушечным котом"),
    ("изоб4.jpg",   "изоб4 — цвет.jpg",   "Мальчик на дороге"),
    ("изоб5.jpg",   "изоб5 — цвет.jpg",   "Мама с малышом у серванта"),
    ("изоб6.jpg",   "изоб6 — цвет.jpg",   "Папа, малыш и девочка во дворе"),
    ("изоб6а.jpg",  "изоб6а — цвет.jpg",  "Брат и малыш в кепке"),
    ("изоб8.jpg",   "изоб8 — цвет.jpg",   "Мальчик в узорчатой рубашке"),
    ("изоб9.jpg",   "изоб9 — цвет.jpg",   "Мама, малыш и девочка в очках"),
    ("изоб10.jpg",  "изоб10 — цвет.jpg",  "Мальчик в комбинезоне"),
]

# per-photo overrides: harsh scans need gentler smoothing, fine textures more
# detail preservation, colourful copies a lower speck threshold, etc.
BW_OVERRIDES = {
    "изоб 1.jpg": dict(denoise_strength=2.0, flatten_strength=0.40, sharpen=0.90),
    "изоб8.jpg":  dict(denoise_strength=3.0, sharpen=0.75),
}
COLOR_OVERRIDES = {
    "изоб5.jpg":  dict(denoise_strength=3.0, speck_thresh=30),
}

BW_DIR = os.path.join("restored", "bw")
COL_DIR = os.path.join("restored", "color")


def bw_job(src, dst):
    # monochrome scan: neutral grey duplicate + the scan's own (mild) tint back
    kw = dict(mode="bw", scale=2, denoise_strength=4, flatten_strength=0.55,
              level_lo=0.7, level_hi=99.3, sharpen=0.85)
    kw.update(BW_OVERRIDES.get(os.path.basename(src), {}))
    return tr.restore(src, dst, **kw)


def color_job(src, dst, name):
    # colourised copy: gentler flatten/chroma so hues are not pulled around
    kw = dict(mode="color", scale=2, denoise_strength=3.5, flatten_strength=0.35,
              level_lo=0.7, level_hi=99.3, sharpen=0.55, speck_thresh=30)
    kw.update(COLOR_OVERRIDES.get(name, {}))
    return tr.restore(src, dst, **kw)


def build_gallery():
    cards = []
    for orig, col, title in PAIRS:
        bw = os.path.join(BW_DIR, orig)
        cfix = os.path.join(COL_DIR, orig)

        def fig(path, cap, fallback=None):
            if os.path.exists(path):
                return (f'<figure><img loading="lazy" src="{quote(path)}" alt="{html.escape(cap)}">'
                        f'<figcaption>{cap}</figcaption></figure>')
            if fallback and os.path.exists(fallback):
                return (f'<figure><img loading="lazy" src="{quote(fallback)}" alt="{html.escape(cap)}">'
                        f'<figcaption>{cap}</figcaption></figure>')
            return f'<figure><div class="soon">нет файла</div><figcaption>{cap}</figcaption></figure>'

        cards.append(f'''
    <section class="card">
      <h2>{html.escape(title)}</h2>
      <div class="trio">
        {fig(orig, "Оригинал")}
        {fig(bw, "Улучшено, ч/б")}
        {fig(cfix, "Улучшено, цвет", fallback=os.path.join("color", col))}
      </div>
    </section>''')

    page = f'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Реставрация семейных фото — до и после</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:28px 20px 56px; background:#141210; color:#ece5da;
         font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  header {{ max-width:1280px; margin:0 auto 28px; }}
  h1 {{ font-size:1.5rem; font-weight:600; margin:0 0 8px; }}
  header p {{ margin:0; color:#a79c8d; font-size:.9rem; line-height:1.55; max-width:74ch; }}
  .grid {{ max-width:1280px; margin:0 auto; display:grid; gap:26px; }}
  .card {{ background:#1d1a17; border:1px solid #2c2723; border-radius:14px; padding:16px 16px 8px; }}
  h2 {{ font-size:.95rem; font-weight:600; margin:0 0 12px; color:#d9cfc1; }}
  .trio {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; align-items:start; }}
  figure {{ margin:0; }}
  figure img {{ width:100%; height:auto; display:block; border-radius:8px; background:#0d0c0b; }}
  figcaption {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.12em;
                color:#8d8377; padding:8px 2px 4px; }}
  .soon {{ aspect-ratio:4/3; display:grid; place-items:center; border:1px dashed #3a332d;
           border-radius:8px; color:#8d8377; font-size:.8rem; }}
  code {{ background:#241f1b; padding:.1em .35em; border-radius:4px; }}
  @media (max-width:900px) {{ .trio {{ grid-template-columns:1fr 1fr; }} }}
  @media (max-width:620px) {{ .trio {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header>
  <h1>Реставрация семейных фото</h1>
  <p>Оригинал → очищенный ч/б скан → раскрашенная версия. Убрана пыль и царапины, приглушено зерно,
     выровнены пересветы и контраст, мягкое повышение резкости и увеличение в 2 раза.
     Скрипт: <code>make_restored.py</code> (пайплайн — <code>tools_restore.py</code>).</p>
</header>
<div class="grid">{''.join(cards)}
</div>
</body>
</html>'''
    with open("index.html", "w", encoding="utf-8") as fh:
        fh.write(page)
    print("index.html:", len(page), "bytes")


def main():
    os.makedirs(BW_DIR, exist_ok=True)
    os.makedirs(COL_DIR, exist_ok=True)

    for orig, col, _ in PAIRS:
        bw_job(orig, os.path.join(BW_DIR, orig))
        print("bw   ", orig)
        csrc = os.path.join("color", col)
        if os.path.exists(csrc):
            color_job(csrc, os.path.join(COL_DIR, orig), orig)
            print("color", orig)

    build_gallery()


if __name__ == "__main__":
    main()
