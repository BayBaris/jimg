"""Cizimin ortak zemini: olculer, yazi tipi ve PNG arka ucu.

Renk BURADA DURMAZ (Faz 9.4): palet `theme.py`dedir ve ciziciler onu okur.
Once `BG`/`TEXT`/`LINE` gibi sabitler bu dosyadaydi ve `web/style.css` ile elle
esit tutuluyordu; iki tema gelince ayni degeri dort yere yazmak gerekecekti.
Olculer burada kaldi: onlar temadan bagimsiz.

Cikti EKRANDA GORUNENIN AYNISI olmalidir. Pillow disinda bagimlilik yoktur
(`K-06`).

Bu modul tabloyu, agaci ya da grafigi BILMEZ; uc cizici de (`img_table`,
`img_tree`, `img_chart`) buradan beslenir. Bagimlilik tek yone akar.

⚠ `scene_to_png` yazi tipi yukleyicisiyle AYNI dosyada kalmalidir. Ayrilirsa
`vector.py` ile dongusel ice aktarma dogar: `vector` sahneyi tanimlar, PNG arka
ucu sahneyi okur ve yazi tipini olcer. Bugunku yerlesim kasitlidir.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import i18n as I18N
from . import theme as TH
from .vector import Scene

# --- Olculer (mantiksal piksel; `scale` ile buyutulur) ---------------------
# Yalnizca UCUNUN DE kullandigi olculer burada. Tabloya ozel olanlar
# (`ROW_H`, `MIN_W`…) `img_table`, grafige ozel olanlar `img_chart` icinde.

PAD = 16

# ⚠ **Punto ve ondan tureyen yukseklikler BURADA DURMAZ**, `theme.metrics()`ten
# CIZIM ANINDA okunur (palet ile ayni kalip). Uc cizicinin de gocu `9.4.5.2`de
# bitti ve taban sabitleri (`FONT_SIZE`, `TITLE_H`…) silindi; buraya yenisi
# eklenirse boyut ayari o cizimde sessizce calismaz.
# Goc `check.py --> SIZED_MODULES` ile kilitlidir.


# --- Yazi tipi -------------------------------------------------------------

# ⚠ Onbellek anahtari AILEYI de tasir. Once yalnizca `(boyut, kalin)` idi;
# kullanici aileyi degistirdiginde ayni anahtar eski yuklenmis yazi tipini
# dondurur ve cizim eski ailede kalirdi — ekran ise aninda degisirdi.
_FONT_CACHE: dict[tuple[str, int, bool], Any] = {}


def _font(size: int, bold: bool = False):
    """Gecerli ailenin yazi tipi. Aday listesi `theme.font_files`ta."""
    key = (TH.get_font(), size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in TH.font_files(bold):
        for path in (fonts_dir / name, Path(name)):
            try:
                _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
                return _FONT_CACHE[key]
            except OSError:
                continue

    # Sistem yazi tipi bulunamazsa cikti cirkinlesir ama uretim durmaz.
    _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


# --- Metin yardimcilari ----------------------------------------------------

def _oneline(text: str) -> str:
    """Satir sonlarini bosluga cevirir.

    Pillow cok satirli metnin genisligini olcemez ("can't measure length of
    multiline text"); JSON degerlerinde satir sonu sik gorulur.
    """
    return " ".join(str(text).split()) if text else ""


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    if not text:
        return 0
    return int(draw.textlength(_oneline(text), font=font))


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    text = _oneline(text)
    if not text or _text_w(draw, text, font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _text_w(draw, text[:mid] + ell, font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell if lo else ""


def _clip(text: str, n: int) -> str:
    """Karakter sayisina gore kirpar (piksele gore degil) — etiketler icin."""
    text = _oneline(text)
    return text if len(text) <= n else text[: max(1, n - 1)] + "…"


def _fmt_num(v: float) -> str:
    """Sayi bicimi ARAYUZ dilini izler.

    Turkce: binlik nokta, ondalik virgul (`1.234,50`).
    Ingilizce: binlik virgul, ondalik nokta (`1,234.50`).

    Once Turkce bicim sabitti ve Ingilizce arayuzde de grafik eksenleri Turkce
    ayracla ciziliyordu — ekran ile cizim ayni dilde olmali.
    """
    if abs(v - round(v)) < 1e-9:
        s = f"{int(round(v)):,}"
        return s.replace(",", ".") if I18N.get_lang() == "tr" else s

    s = f"{v:,.2f}"
    if I18N.get_lang() != "tr":
        return s
    return s.replace(",", "@").replace(".", ",").replace("@", ".")


# Olcum icin tek seferlik cizim baglami — sahne kurarken metin genisligi
# gerekir ama henuz bir goruntu yoktur.
_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def _fit(text: str, size: int, bold: bool, max_w: float) -> str:
    return _ellipsize(_MEASURE, text, _font(size, bold), int(max_w))


def _baseline(top: float, h: float, size: float) -> float:
    return top + (h + size * 0.72) / 2


# --- PNG arka ucu ----------------------------------------------------------

def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class _S:
    """Olculeri `scale` ile carpan minik yardimci."""

    def __init__(self, scale: int) -> None:
        self.k = scale

    def __call__(self, v: float) -> int:
        return int(round(v * self.k))


def scene_to_png(sc: Scene, scale: int = 2) -> bytes:
    """Sahnenin PNG arka ucu.

    SVG ve PDF `vector.py` icindedir; PNG burada cunku Pillow yazi tipi
    yukleyicisi bu modulde. Ucu de AYNI sahneden uretilir.
    """
    img = Image.new("RGB", (max(1, int(sc.w * scale)), max(1, int(sc.h * scale))), sc.bg)
    d = ImageDraw.Draw(img)
    s = _S(scale)

    for it in sc.items:
        if it["t"] == "rect":
            box = [s(it["x"]), s(it["y"]), s(it["x"] + it["w"]), s(it["y"] + it["h"])]
            if it["r"]:
                d.rounded_rectangle(box, radius=s(it["r"]), fill=it["fill"],
                                    outline=it["stroke"], width=max(1, s(it["sw"])))
            else:
                d.rectangle(box, fill=it["fill"], outline=it["stroke"],
                            width=max(1, s(it["sw"])) if it["stroke"] else 0)

        elif it["t"] == "poly":
            pts = [(s(x), s(y)) for x, y in it["pts"]]
            if len(pts) >= 3:
                d.polygon(pts, fill=it["fill"], outline=it["stroke"])

        elif it["t"] == "line":
            pts = [(s(x), s(y)) for x, y in it["pts"]]
            if len(pts) >= 2:
                d.line(pts, fill=it["stroke"], width=max(1, s(it["sw"])))

        elif it["t"] == "image":
            try:
                raw = base64.b64decode(it["uri"].split(",", 1)[1])
                thumb = Image.open(io.BytesIO(raw))
                thumb.load()
                thumb = thumb.convert("RGBA")
                thumb.thumbnail((max(1, s(it["w"])), max(1, s(it["h"]))), Image.LANCZOS)
                px = s(it["x"]) + (s(it["w"]) - thumb.width) // 2
                py = s(it["y"]) + (s(it["h"]) - thumb.height) // 2
                img.paste(thumb, (px, py), thumb)
            except Exception:
                pass

        elif it["t"] == "text":
            font = _font(s(it["size"]), bold=it["bold"])
            text = _oneline(it["s"])
            if it["rot"]:
                _axis_title(img, s, text, font, it["fill"], it["x"], it["y"], rotate=True)
                continue
            w = _text_w(d, text, font)
            x = s(it["x"])
            if it["anchor"] == "middle":
                x -= w // 2
            elif it["anchor"] == "end":
                x -= w
            d.text((x, s(it["y"] - it["size"] * 0.85)), text, font=font, fill=it["fill"])

    return _to_png(img)


def _axis_title(img, s, text: str, font, color: str, cx: float, cy: float,
                rotate: bool) -> None:
    """Eksen adini cizer; Y ekseninde 90 derece dondurur.

    Pillow metni dogrudan donduremez, gecici bir katmana cizip dondururuz.
    """
    tmp = Image.new("RGBA", (s(400), s(24)), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    td.text((0, 0), text, font=font, fill=color)
    bbox = tmp.getbbox()
    if bbox is None:
        return
    tmp = tmp.crop(bbox)
    if rotate:
        tmp = tmp.rotate(90, expand=True)
    img.paste(tmp, (s(cx) - tmp.width // 2, s(cy) - tmp.height // 2), tmp)
