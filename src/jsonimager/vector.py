"""Sahne modeli ve SVG / PDF arka uclari.

Ayni cizimi uc kez yazmamak icin geometri BIR KEZ uretilir (sahne), sonra
istenen bicime basilir. Sahne, ilkel cizim ogelerinden olusan duz bir listedir.

  rect   dikdortgen (kose yaricapi istege bagli)
  poly   kapali coklu-kenar (pasta dilimleri de coklu-kenar olarak uretilir,
         boylece SVG ve PDF birebir ayni geometriyi kullanir)
  line   acik coklu-cizgi
  text   metin (yatay hizalama ve 90 derece dondurme destekler)

PDF metni cp1254 (Latin-5) ile kodlanir; Turkce harfler bu kod sayfasindadir.
WinAnsi'den ayrildigi alti kod icin /Differences yazilir.
"""

from __future__ import annotations

import base64
import io
import math
import zlib
from typing import Any

from . import theme as TH

# --- Sahne kurulumu --------------------------------------------------------


class Scene:
    """Cizim ilkelleri listesi.

    ⚠ Varsayilan renkler PALETTEN gelir, sabit degil (Faz 9.4). Once `#14161a`
    ve `#fff` yaziliydi; cagiranlarin hepsi rengi acikca gectigi icin bunlar
    gorunmuyordu ama acik temada koyu bir zemin ya da beyaz bir metin olarak
    ortaya cikarlardi — hicbir denetimin gostermedigi bicimde.
    """

    def __init__(self, w: float, h: float, bg: str | None = None) -> None:
        self.w, self.h, self.bg = w, h, bg or TH.active().bg
        self.items: list[dict] = []
        self.meta: dict = {}      # arayuze tasinan ek bilgi (ornek: grafik ozeti)

    def rect(self, x, y, w, h, fill=None, stroke=None, sw=1.0, r=0.0, hover=None):
        self.items.append({"t": "rect", "x": x, "y": y, "w": w, "h": h,
                           "fill": fill, "stroke": stroke, "sw": sw, "r": r, "hover": hover})

    def poly(self, pts, fill=None, stroke=None, sw=1.0, hover=None):
        self.items.append({"t": "poly", "pts": list(pts), "fill": fill,
                           "stroke": stroke, "sw": sw, "hover": hover})

    def line(self, pts, stroke=None, sw=1.0):
        self.items.append({"t": "line", "pts": list(pts),
                           "stroke": stroke or TH.active().text, "sw": sw})

    def text(self, x, y, s, size=12, fill=None, bold=False, anchor="start", rot=0):
        self.items.append({"t": "text", "x": x, "y": y, "s": str(s), "size": size,
                           "fill": fill or TH.active().text,
                           "bold": bold, "anchor": anchor, "rot": rot})

    def image(self, x, y, w, h, uri, hover=None):
        """Gomulu gorsel (data URI). Uc arka uc da bunu isler."""
        self.items.append({"t": "image", "x": x, "y": y, "w": w, "h": h,
                           "uri": uri, "hover": hover})

    def slice(self, cx, cy, r, a0, a1, fill, hover=None, steps_per_deg=1.0):
        """Pasta dilimini coklu-kenara cevirir; her arka uc ayni sekli alir."""
        span = a1 - a0
        n = max(2, int(abs(span) * steps_per_deg))
        pts = [(cx, cy)]
        for i in range(n + 1):
            a = math.radians(a0 + span * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        self.poly(pts, fill=fill, hover=hover)


# --- SVG -------------------------------------------------------------------

def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _attr(value: str) -> str:
    """Tirnaklariyla birlikte bir XML nitelik degeri.

    Yazi tipi yigini kendi icinde tirnak tasiyor (`"Segoe UI", system-ui, …`);
    dogrudan `f'x="{deger}"'` yazmak nitelik degerini erken kapatirdi.
    """
    return '"' + _esc(value) + '"'


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def to_svg(sc: Scene) -> str:
    """Etkilesimli SVG. `hover` tasiyan ogelere `data-tip` eklenir."""
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(sc.w)} {_fmt(sc.h)}" '
           f'width="100%" preserveAspectRatio="xMidYMid meet" class="vsvg">',
           f'<rect x="0" y="0" width="{_fmt(sc.w)}" height="{_fmt(sc.h)}" fill="{sc.bg}"/>']
    # Aile belge boyunca sabit: oge basina yeniden cozup kacislamak, buyuk bir
    # tabloda binlerce gereksiz dize islemi demekti.
    font_attr = _attr(TH.font_css())

    for it in sc.items:
        tip = f' data-tip="{_esc(it["hover"])}"' if it.get("hover") else ""
        cls = ' class="hot"' if it.get("hover") else ""

        if it["t"] == "rect":
            attrs = f'x="{_fmt(it["x"])}" y="{_fmt(it["y"])}" ' \
                    f'width="{_fmt(it["w"])}" height="{_fmt(it["h"])}"'
            if it["r"]:
                attrs += f' rx="{_fmt(it["r"])}"'
            out.append(f'<rect {attrs} fill="{it["fill"] or "none"}"'
                       + (f' stroke="{it["stroke"]}" stroke-width="{_fmt(it["sw"])}"' if it["stroke"] else "")
                       + f'{cls}{tip}/>')

        elif it["t"] in ("poly", "line"):
            pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in it["pts"])
            if it["t"] == "poly":
                out.append(f'<polygon points="{pts}" fill="{it["fill"] or "none"}"'
                           + (f' stroke="{it["stroke"]}" stroke-width="{_fmt(it["sw"])}"' if it["stroke"] else "")
                           + f'{cls}{tip}/>')
            else:
                out.append(f'<polyline points="{pts}" fill="none" stroke="{it["stroke"]}" '
                           f'stroke-width="{_fmt(it["sw"])}" stroke-linejoin="round"/>')

        elif it["t"] == "image":
            out.append(f'<image x="{_fmt(it["x"])}" y="{_fmt(it["y"])}" '
                       f'width="{_fmt(it["w"])}" height="{_fmt(it["h"])}" '
                       f'preserveAspectRatio="xMidYMid meet" '
                       f'href="{_esc(it["uri"])}"{cls}{tip}/>')

        elif it["t"] == "text":
            anchor = {"start": "start", "middle": "middle", "end": "end"}[it["anchor"]]
            transform = ""
            if it["rot"]:
                transform = f' transform="rotate({-it["rot"]} {_fmt(it["x"])} {_fmt(it["y"])})"'
            out.append(
                f'<text x="{_fmt(it["x"])}" y="{_fmt(it["y"])}" fill="{it["fill"]}" '
                f'font-size="{_fmt(it["size"])}" text-anchor="{anchor}"'
                f'{" font-weight=\"600\"" if it["bold"] else ""}'
                f' font-family={font_attr}{transform}>{_esc(it["s"])}</text>')

    out.append("</svg>")
    return "\n".join(out)


# --- PDF -------------------------------------------------------------------

# cp1254'un WinAnsi'den ayrildigi kodlar; PDF /Differences ile bildirilir.
CP1254_DIFF = {
    0xD0: "Gbreve", 0xDD: "Idotaccent", 0xDE: "Scedilla",
    0xF0: "gbreve", 0xFD: "dotlessi", 0xFE: "scedilla",
}


def _pdf_text(s: str) -> str:
    """Metni cp1254'e cevirip PDF dizesi olarak kacislar."""
    try:
        raw = s.encode("cp1254", errors="replace")
    except LookupError:
        raw = s.encode("latin-1", errors="replace")
    out = bytearray()
    for b in raw:
        if b in (0x28, 0x29, 0x5C):        # ( ) \
            out += b"\\" + bytes([b])
        elif b < 32 or b > 126:
            out += f"\\{b:03o}".encode("ascii")
        else:
            out.append(b)
    return out.decode("ascii")


def _rgb(color: str) -> tuple[float, float, float]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _approx_w(text: str, size: float, bold: bool) -> float:
    """Kaba genislik; yalnizca ortalama/saga yaslama icin.

    Katsayilar Helvetica'dan; Times daha dar, Courier esaralikli olduğu icin
    daha genis. Aile degisince hizalamada birkac piksel sapma olur — metin
    genisligi PDF'te zaten tahmin ediliyor (yazi tipi gomulu degil), bu yuzden
    aileye gore ayri katsayi tutmak yanilsamanin hassasiyetini artirmaktan
    ibaret olurdu.
    """
    return len(text) * size * (0.56 if bold else 0.52)


def _image_xobject(uri: str, bg: str) -> tuple[bytes, int, int] | None:
    """data URI'yi PDF gorsel akisina cevirir (DeviceRGB + FlateDecode).

    Saydamlik PDF'te ayri bir maske ister; onun yerine sahne zeminiyle
    birlestirilir — tablo hucrelerinde sonuc gorsel olarak aynidir.
    """
    try:
        from PIL import Image           # Pillow zaten proje bagimliligi
        raw = base64.b64decode(uri.split(",", 1)[1])
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, bg)
            flat.paste(img, mask=img.split()[-1])
            img = flat
        else:
            img = img.convert("RGB")
        return zlib.compress(img.tobytes()), img.width, img.height
    except Exception:
        return None


def to_pdf(sc: Scene, title: str = "JSON Imager") -> bytes:
    """Sahneyi VEKTOR PDF olarak yazar. Harici kutuphane kullanilmaz (K-12)."""
    ops: list[str] = []
    images: list[tuple[bytes, int, int]] = []
    r, g, b = _rgb(sc.bg)
    ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg 0 0 {sc.w:.2f} {sc.h:.2f} re f")

    def y(v: float) -> float:               # PDF ekseni yukari dogru
        return sc.h - v

    for it in sc.items:
        if it["t"] == "rect":
            if it.get("fill"):
                r, g, b = _rgb(it["fill"])
                ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg "
                           f"{it['x']:.2f} {y(it['y'] + it['h']):.2f} {it['w']:.2f} {it['h']:.2f} re f")
            if it.get("stroke"):
                r, g, b = _rgb(it["stroke"])
                ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {it['sw']:.2f} w "
                           f"{it['x']:.2f} {y(it['y'] + it['h']):.2f} {it['w']:.2f} {it['h']:.2f} re S")

        elif it["t"] in ("poly", "line"):
            pts = it["pts"]
            if not pts:
                continue
            path = f"{pts[0][0]:.2f} {y(pts[0][1]):.2f} m " + " ".join(
                f"{x:.2f} {y(py):.2f} l" for x, py in pts[1:])
            if it["t"] == "poly":
                if it.get("fill"):
                    r, g, b = _rgb(it["fill"])
                    ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg {path} h f")
                if it.get("stroke"):
                    r, g, b = _rgb(it["stroke"])
                    ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {it['sw']:.2f} w {path} h S")
            else:
                r, g, b = _rgb(it["stroke"])
                ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {it['sw']:.2f} w {path} S")

        elif it["t"] == "image":
            xo = _image_xobject(it["uri"], sc.bg)
            if xo is None:
                continue
            images.append(xo)
            # Oran korunarak hucreye ortalanir (SVG'deki xMidYMid ile ayni).
            iw, ih = xo[1], xo[2]
            k = min(it["w"] / iw, it["h"] / ih)
            dw, dh = iw * k, ih * k
            dx = it["x"] + (it["w"] - dw) / 2
            dy = y(it["y"] + (it["h"] + dh) / 2)
            ops.append(f"q {dw:.2f} 0 0 {dh:.2f} {dx:.2f} {dy:.2f} cm "
                       f"/Im{len(images)} Do Q")

        elif it["t"] == "text":
            r, g, b = _rgb(it["fill"])
            font = "F2" if it["bold"] else "F1"
            w = _approx_w(it["s"], it["size"], it["bold"])
            tx = it["x"] - (w / 2 if it["anchor"] == "middle" else w if it["anchor"] == "end" else 0)
            ty = y(it["y"]) - it["size"] * 0.28
            if it["rot"]:
                a = math.radians(it["rot"])
                cos_a, sin_a = math.cos(a), math.sin(a)
                # Dondurulmus metinde hizalama metnin kendi ekseninde yapilir.
                ox, oy = it["x"], y(it["y"])
                shift = (w / 2 if it["anchor"] == "middle" else w if it["anchor"] == "end" else 0)
                ops.append(f"BT /{font} {it['size']:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
                           f"{cos_a:.4f} {sin_a:.4f} {-sin_a:.4f} {cos_a:.4f} "
                           f"{ox - cos_a * shift:.2f} {oy - sin_a * shift:.2f} Tm "
                           f"({_pdf_text(it['s'])}) Tj ET")
            else:
                ops.append(f"BT /{font} {it['size']:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
                           f"{tx:.2f} {ty:.2f} Td ({_pdf_text(it['s'])}) Tj ET")

    content = zlib.compress("\n".join(ops).encode("latin-1", errors="replace"))
    diffs = " ".join(f"{code} /{name}" for code, name in sorted(CP1254_DIFF.items()))

    # Gorseller 8. nesneden sonra sirayla yerlesir.
    img_first = 9
    xobjects = " ".join(f"/Im{i + 1} {img_first + i} 0 R" for i in range(len(images)))
    res = f"/Font << /F1 5 0 R /F2 6 0 R >>"
    if images:
        res += f" /XObject << {xobjects} >>"

    objects: list[Any] = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {sc.w:.2f} {sc.h:.2f}] "
        f"/Resources << {res} >> /Contents 4 0 R >>",
        ("stream", content, "<< /Length %d /Filter /FlateDecode >>"),
        # ⚠ PDF'e yazi tipi GOMULMEZ (`K-12`), yani secim base-14 ile sinirli:
        # Helvetica · Times · Courier. Aile ayari bu ucluye eslenir
        # (`theme.Family.pdf`); gomseydik exe her ailenin TTF'ini tasirdi.
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{TH.font_pdf()} "
        "/Encoding 7 0 R >>",
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{TH.font_pdf(True)} "
        "/Encoding 7 0 R >>",
        f"<< /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [{diffs}] >>",
        f"<< /Title ({_pdf_text(title)}) /Producer (JSON Imager) >>",
    ]
    for data, iw, ih in images:
        objects.append(("stream", data,
                        f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
                        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 "
                        f"/Filter /FlateDecode /Length %d >>"))

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        if isinstance(obj, tuple):
            _, data, header = obj
            buf += f"{i} 0 obj\n{header % len(data)}\nstream\n".encode("latin-1")
            buf += data + b"\nendstream\nendobj\n"
        else:
            buf += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")

    xref_at = len(buf)
    buf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode("latin-1")
    buf += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 8 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode("latin-1")
    return bytes(buf)


# --- draw.io (diagrams.net) ------------------------------------------------

def to_drawio(nodes: list[dict], edges: list[tuple[str, str]],
              title: str = "JSON Imager") -> str:
    """Agaci DUZENLENEBILIR sema olarak yazar (K-11).

    Kutular gercek `mxCell` dugumu, baglantilar gercek kenar olur; draw.io'da
    tasinabilir ve metinleri degistirilebilir. SVG'nin aksine cizim degil,
    nesne modelidir.
    """
    # draw.io renkleri de temayi izler: dosya bir CIZIM degil nesne modeli ama
    # acildiginda ekranda gorunen sey yine bu palet.
    pal = TH.active()
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']

    for n in nodes:
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={pal.panel_2};"
                 "strokeColor=" + (pal.accent if n.get("container") else pal.line) +
                 f";fontColor={pal.text};align=left;spacingLeft=6;"
                 "verticalAlign=top;spacingTop=2")
        label = _esc(n["title"])
        if n.get("desc"):
            label += "&#10;" + _esc(n["desc"])
        cells.append(
            f'<mxCell id="{_esc(n["id"])}" value="{label}" style="{style}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{_fmt(n["x"])}" y="{_fmt(n["y"])}" '
            f'width="{_fmt(n["w"])}" height="{_fmt(n["h"])}" as="geometry"/></mxCell>')

    for i, (src, dst) in enumerate(edges):
        cells.append(
            f'<mxCell id="e{i}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;'
            f'strokeColor={pal.muted};endArrow=none;html=1" edge="1" parent="1" '
            f'source="{_esc(src)}" target="{_esc(dst)}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>')

    body = "\n        ".join(cells)
    return (
        f'<mxfile host="JSON Imager" type="device">\n'
        f'  <diagram name="{_esc(title)}">\n'
        f'    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" page="1" '
        f'background="{pal.bg}" math="0" shadow="0">\n'
        f'      <root>\n        {body}\n      </root>\n'
        f'    </mxGraphModel>\n  </diagram>\n</mxfile>\n'
    )
