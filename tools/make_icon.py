"""Uygulama logosunu uretir: simge SVG'si, `.ico`, sozcuk isareti ve onizleme tablosu.

Neden bir betik? `make_examples.py` ile ayni gerekce (bkz. o dosyanin basligi):
depoya ve dagitilan exe'ye giren **her bayt bu projeye ait olmali**. Disaridan
alinan bir logo telif sorusu dogurur. Betik ayni zamanda kaynagin kaydidir —
`assets/` silinip yeniden uretilebilir.

TASARIM (`K-33`) — ALTIGEN diyafram, ortasinda suslu parantez:

    alti DOLU kanat bir altigen kurar; dordu amber, ikisi (sag ust ve sol alt)
    vurgu renginde. Ortadaki aciklik vizordur ve icinde JSON figuru durur.

Metafor ilk logodakiyle ayni — JSON **cekiliyor** — yalnizca geometri degisti:
cizgi kanatlar yerine dolu kanatlar. Sozcuk isareti `JIMG` (JSON Imager):
`J` amber, `IMG` vurgu renginde; harfler ESIT aralikli, `J` ayri durmaz.

⚠ **Geometri TEK KAYNAKTIR** (`_blades`, `_brace_curves`, `wordmark`). SVG ve
Pillow ayni sayilardan turer: SVG yol komutu basar, Pillow ayni cokgeni
doldurup kenarini damgalar. Iki yere ayri koordinat yazmak `CONST_PAIRS`
sapmasinin gorsel karsiligi olurdu — `.ico` ile SVG sessizce ayrisirdi.

⚠ SVG'yi rasterlestiren bir bagimlilik EKLENMEZ (`K-06` ile ayni gerekce: exe
sismemeli). `.ico` Pillow ile ayri cizilir, iste bu yuzden geometri paylasilir.

Calistirma:
    .\\.venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw        # noqa: E402

ASSETS = ROOT / "assets"
WEB = ROOT / "src" / "jsonimager" / "web"

# `.ico` icine giren boyutlar. Windows 16'yi gorev cubugunda, 32'yi masaustunde,
# 256'yi dosya onizlemesinde kullanir; ucu de gomulmezse olcekleme bulaniklasir.
ICO_SIZES = (16, 32, 48, 256)

# --- Olculer ---------------------------------------------------------------

BOX = 64.0              # tasarim izgarasi; her iki cizici de bunu olcekler
CENTER = BOX / 2

# Altigen diyafram. Kanat i, dis altigenin i. kenarindan ic acikliga uzanan bir
# dortgendir; ic uclar `TWIST` kadar dondurulmustur — donme, diyaframin
# "kapanan kanat" duygusunu verir. `TWIST = 0` olsaydi sekil dilimlenmis bir
# altigen (pasta) gibi okunurdu.
BLADES = 6
OUTER_R = 28.0          # dis altigenin kose yaricapi (64 kutuda 4 birim pay)
HOLE_R = 11.5           # ic acikligin kose yaricapi (vizor)
# ⚠ `TWIST` kanat UCUNUN acisini belirler: uc acisi = 60° - atan(r·sin t /
# (R - r·cos t)). Ilk denemede 52° idi: uc 37°'ye iniyor ve kanat iceri
# cekilirken sivri uc orantisiz geri cekiliyordu (geri cekilme = d / sin(aci/2));
# kanatlar ince ucgenlere donustu, altigen butunlugu kayboldu (olculdu, onizleme
# tablosunda). 26°'de uc 44° ve dis hat altigen olarak okunuyor.
TWIST = 26.0            # ic uclarin donmesi, derece
BLADE_GAP = 1.6         # komsu kanatlar arasindaki bosluk
BLADE_ROUND = 0.5       # kanat koselerinin yuvarlakligi (buyurse uc daha da cekilir)
ACCENT_BLADES = (2, 5)  # vurgu rengindeki kanatlar: sol alt ve sag ust

# Suslu parantez — 64 birimlik izgarada tam boy tanimlanir, sonra `BRACE_S` ile
# merkeze dogru kucultulur. Ayri bir "kucuk parantez" geometrisi yazmak yerine
# olcekleme yapiliyor: tek kaynak korunsun.
BRACE_S = 0.42          # vizoru dolduracak olcek
BRACE_W = 2.8           # olcekten BAGIMSIZ: kucultulmus cizgi cok inceliyordu
GAP = 15.0
TIP = 4.0
INSET = 3.0
TOP, BOT = 13.0, BOX - 13.0

RADIUS = 14.0           # zeminin kose yuvarlakligi

# ⚠ **Parlama noktasi YOK ve geri eklenmemeli.** Ilk logoda iki kez denendi,
# ikisi de bozdu: halka + nokta birlikte GOZ gibi okunuyordu.


# --- Kucuk boyut profili ----------------------------------------------------
# ⚠ **16 px AYRI cizilir.** Ayrinti orada bilgi tasimiyor, leke uretiyor: kanat
# araligi 1.6/64*16 = 0.4 piksele iner ve alti kanat tek bir amber lekeye
# donusur; parantez ise birkac piksellik beyaz bir bulaniklik olur.
#
# Esik onizleme tablosunda GOZLE olculdu (ilk logoda 32 idi): dolu kanatlarla
# 32 px'te tam cizim sadelesmisten IYI okunuyor — parantez seciliyor ve kimligi
# o tasiyor; sadelesmis 32 bos bir firildak gibi duruyordu. 16'da tersi.
#
# Cozum ucuz cunku `.ico` **her boyut icin ayri bir goruntu tasir**. Sekil ayni
# okunur — iki renkli alti kanat — yalnizca aralik genisler ve parantez duser.
#
# Sadelesmis surum YALNIZCA Pillow tarafindadir; SVG her zaman tam surumdur.
SIMPLE_MAX_PX = 16      # bu boyuta kadar sadelesmis cizim
SIMPLE_GAP = 3.6        # 16 px'te ~0.9 piksel: kanatlar ayri okunsun ama incelmesin
SIMPLE_ROUND = 0.5


# --- Palet ------------------------------------------------------------------
# ⚠ Arayuz paletiyle akraba kalinir (`web/style.css :root`, koyu tema): amber
# `--json`, vurgu `--export` ile ayni deger. Simge kendi koyu zeminini tasidigi
# icin temayla degismez; sozcuk isareti ise zeminsizdir ve rengini CSS'teki
# belirteclerden alir (bkz. `wordmark`).
AMBER = "#e8a33d"       # dort kanat
ACCENT = "#7fd1a3"      # iki kanat (`K-33`: yesil)
BRACE = "#dfe3ea"       # ortadaki suslu parantez
BG = "#1b1e24"          # zemin


# --- Geometri: altigen diyafram ---------------------------------------------

def _pt(angle: float, radius: float) -> tuple[float, float]:
    a = math.radians(angle)
    return (CENTER + radius * math.cos(a), CENTER + radius * math.sin(a))


def _inset(poly: list[tuple[float, float]], d: float) -> list[tuple[float, float]]:
    """Disbukey cokgeni her kenarindan `d` kadar ICERI ceker.

    Her kenar ic normali yonunde kaydirilir, yeni koseler komsu iki kaydirilmis
    kenarin kesisimidir. Ic yon agirlik merkezine gore secilir, yani cokgenin
    donus yonunden bagimsizdir.
    """
    n = len(poly)
    cx = sum(p[0] for p in poly) / n
    cy = sum(p[1] for p in poly) / n
    lines = []
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        ex, ey = x1 - x0, y1 - y0
        length = math.hypot(ex, ey)
        nx, ny = -ey / length, ex / length
        if nx * (cx - x0) + ny * (cy - y0) < 0:
            nx, ny = -nx, -ny
        lines.append((x0 + nx * d, y0 + ny * d, ex, ey))
    out = []
    for i in range(n):
        ax, ay, adx, ady = lines[i - 1]
        bx, by, bdx, bdy = lines[i]
        den = adx * bdy - ady * bdx
        t = ((bx - ax) * bdy - (by - ay) * bdx) / den
        out.append((ax + adx * t, ay + ady * t))
    return out


def _blades(gap: float = BLADE_GAP, round_r: float = BLADE_ROUND
            ) -> list[tuple[list[tuple[float, float]], str]]:
    """Alti kanat: (ICERI cekilmis dortgen, renk).

    Komsu kanatlar bir kenari paylasir. Aralik, her kanadi `gap / 2` iceri
    cekerek acilir; yuvarlak koseler icin `round_r` kadar DAHA iceri cekilir ve
    cizerken ayni yaricapta yuvarlak bir kenar cizgisi eklenir. Sonuc: araligi
    `gap`, kose yaricapi `round_r` olan dolu bir kanat — SVG'de `stroke-linejoin:
    round`, Pillow'da kenar boyunca damga.
    """
    out = []
    for i in range(BLADES):
        a = i * 360.0 / BLADES
        quad = [_pt(a, OUTER_R), _pt(a + 60.0, OUTER_R),
                _pt(a + 60.0 + TWIST, HOLE_R), _pt(a + TWIST, HOLE_R)]
        out.append((_inset(quad, gap / 2 + round_r),
                    ACCENT if i in ACCENT_BLADES else AMBER))
    return out


# --- Geometri: suslu parantez -----------------------------------------------

def _brace_curves(sign: int, scale: float = BRACE_S) -> list[tuple[float, ...]]:
    """Tek parantezin iki kubik Bezier'i, merkeze gore `scale` ile kucultulmus.

    Sivri uc DISARI bakar, uclar merkeze dogru kivrilir.

    ⚠ Uctaki KOSE, iki egrinin FARKLI tegetle bulusmasindan dogar. Once ikisi
    de uca dikey giriyordu; ayni teget = puruzsuz gecis, yani suslu parantez
    degil duz bir `(` cikiyordu. Uca komsu denetim noktalari govde hizasina
    cekilince ust egri sola-asagi VARIR, alt egri saga-asagi CIKAR.
    """
    x = CENTER + sign * GAP
    end_x = x - sign * INSET
    tip_x = x + sign * TIP
    pull = (CENTER - TOP) * 0.55
    cusp = 3.5

    full = [
        (end_x, TOP, end_x, TOP + pull, x, CENTER - cusp, tip_x, CENTER),
        (tip_x, CENTER, x, CENTER + cusp, end_x, BOT - pull, end_x, BOT),
    ]
    return [tuple(CENTER + (v - CENTER) * scale for v in c) for c in full]


def _bezier_points(c: tuple[float, ...], steps: int) -> list[tuple[float, float]]:
    """Kubik Bezier'i ornekler — Pillow'un egrisi yok, nokta dizisi kullanir."""
    x0, y0, x1, y1, x2, y2, x3, y3 = c
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        a, b, cc, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        out.append((a * x0 + b * x1 + cc * x2 + d * x3,
                    a * y0 + b * y1 + cc * y2 + d * y3))
    return out


# --- SVG (simge) ------------------------------------------------------------

def build_svg() -> str:
    """Simgenin SVG'si — `.ico`nun 256 px karesiyle ayni cizim, zemin dahil.

    ⚠ **Zemin VARDIR.** Ilk logoda arayuz surumu zeminsizdi, cunku sol panel
    basliginda duruyordu ve acik temada koyu bir kare olarak ortaya cikardi.
    Baslikta artik sozcuk isareti var (`wordmark`); simge yalnizca Hakkinda
    penceresinde gorunuyor ve orada bir UYGULAMA SIMGESI olarak, kendi
    zeminiyle durmasi dogru — ortadaki acik renk parantez acik temada zeminsiz
    kalsa gorunmezdi.
    """
    parts = [f'<svg viewBox="0 0 {BOX:.0f} {BOX:.0f}" '
             f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">\n']
    parts.append(f'  <rect width="{BOX:.0f}" height="{BOX:.0f}" rx="{RADIUS:.0f}" '
                 f'fill="{BG}"/>\n')
    # Kenar cizgisi dolguyla AYNI renkte ve yuvarlak birlesimli: iceri cekilmis
    # dortgeni `BLADE_ROUND` kadar sisirir, koseler yuvarlanir (bkz. `_blades`).
    parts.append(f'  <g stroke-width="{2 * BLADE_ROUND:.2f}" stroke-linejoin="round">\n')
    for quad, color in _blades():
        d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in quad) + " Z"
        parts.append(f'    <path d="{d}" fill="{color}" stroke="{color}"/>\n')
    parts.append('  </g>\n')

    parts.append(f'  <g fill="none" stroke="{BRACE}" '
                 f'stroke-width="{BRACE_W:.2f}" stroke-linecap="round">\n')
    for sign in (-1, 1):
        up, lo = _brace_curves(sign)
        parts.append(
            f'    <path d="M {up[0]:.2f} {up[1]:.2f} '
            f'C {up[2]:.2f} {up[3]:.2f} {up[4]:.2f} {up[5]:.2f} {up[6]:.2f} {up[7]:.2f} '
            f'C {lo[2]:.2f} {lo[3]:.2f} {lo[4]:.2f} {lo[5]:.2f} {lo[6]:.2f} {lo[7]:.2f}"/>\n')
    parts.append('  </g>\n</svg>\n')
    return "".join(parts)


# --- Sozcuk isareti ---------------------------------------------------------
# Harfler KALIN, yuvarlak uclu TEK CIZGIDIR: her harf bir merkez cizgisi yoludur
# ve `WM_STROKE` kalinliginda, yuvarlak uc ve birlesimle cizilir. Hazir bir yazi
# tipi kullanilmaz — yazi tipi dosyasi bir bagimlilik ve bir lisans sorusudur,
# ve dort harf icin gereksizdir.
#
# ⚠ Harfler ESIT aralikla dizilir (`WM_GAP`, harf kutulari arasinda). `J` ile
# `IMG` yalnizca RENKLE ayrilir; aralarinda fazladan bosluk YOKTUR (kullanici:
# "IMG, J'den ayri durmasin").

WM_H = 40.0             # buyuk harf yuksekligi = kutu yuksekligi
WM_STROKE = 11.0        # cizgi kalinligi
WM_GAP = 3.0            # harf kutulari arasindaki bosluk


def _letters() -> list[tuple[str, float, str]]:
    """(harf, merkez cizgisinin genisligi, `{x}` ofsetli yol sablonu)."""
    y0, y1 = WM_STROKE / 2, WM_H - WM_STROKE / 2
    return [
        # J: ust cubuk, sag govde, alttan sola kivrilan kanca
        ("J", 14.0, lambda x: (
            f"M {x:g} {y0:g} H {x + 14:g} V {y1 - 7:g} "
            f"A 7 7 0 0 1 {x:g} {y1 - 7:g}")),
        # I: ust ve alt cubuk, ortada govde
        ("I", 14.0, lambda x: (
            f"M {x:g} {y0:g} H {x + 14:g} M {x + 7:g} {y0:g} V {y1:g} "
            f"M {x:g} {y1:g} H {x + 14:g}")),
        # M: iki govde, ortada asagi inen V
        ("M", 18.0, lambda x: (
            f"M {x:g} {y1:g} V {y0:g} L {x + 9:g} {y0 + 13:g} "
            f"L {x + 18:g} {y0:g} V {y1:g}")),
        # G: sola acik C + iceri donen cubuk
        ("G", 18.0, lambda x: (
            f"M {x + 18:g} {y0 + 2:g} Q {x + 18:g} {y0:g} {x + 12:g} {y0:g} H {x + 8:g} "
            f"A 8 8 0 0 0 {x:g} {y0 + 8:g} V {y1 - 8:g} A 8 8 0 0 0 {x + 8:g} {y1:g} "
            f"H {x + 12:g} Q {x + 18:g} {y1:g} {x + 18:g} {y1 - 6:g} V {WM_H / 2:g} "
            f"H {x + 10.5:g}")),
    ]


def wordmark() -> dict[str, str]:
    """`JIMG` sozcuk isareti: `viewBox`, cizgi kalinligi ve iki yol (`j`, `img`).

    Arayuz bunu `index.html`e SATIR ICI yazar ve rengi CSS belirtecinden alir
    (`.wm-j` → `--json`, `.wm-img` → `--export`): sozcuk isareti zeminsizdir ve
    temayla birlikte renk degistirmelidir; `<img>` ile yuklenen bir dosya bunu
    yapamaz. Satir ici kopyanin bu ciktiyla AYNI oldugunu `check_logo` denetler.
    """
    x = WM_STROKE / 2
    paths = {}
    for name, width, draw in _letters():
        paths[name] = draw(x)
        x += width + WM_STROKE + WM_GAP
    total = x - WM_GAP - WM_STROKE / 2
    return {
        "viewBox": f"0 0 {total:g} {WM_H:g}",
        "stroke": f"{WM_STROKE:g}",
        "j": paths["J"],
        "img": " ".join(paths[k] for k in "IMG"),
    }


def wordmark_markup() -> str:
    """`index.html`e yazilan satir ici SVG (`check_logo` bununla karsilastirir)."""
    w = wordmark()
    return (f'<svg class="wordmark" viewBox="{w["viewBox"]}" aria-hidden="true">'
            f'<path class="wm-j" stroke-width="{w["stroke"]}" d="{w["j"]}"></path>'
            f'<path class="wm-img" stroke-width="{w["stroke"]}" d="{w["img"]}"></path>'
            f'</svg>')


# --- Pillow (`.ico`) --------------------------------------------------------

SS = 8      # asiri ornekleme: buyuk ciz, kucult — Pillow'da kenar yumusatma yok


def _stroke(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]],
            width: float, fill: str) -> None:
    """Kalin egriyi DAMGALAYARAK cizer: yol boyunca ust uste daireler.

    ⚠ `d.line(..., joint="curve")` kullanilmaz. Kalin bir cizgiyi duz
    parcalarin dikdortgenleri olarak basiyor; asiri ornekleme altinda bile
    egrinin dis kenarinda **tirtikli fasetalar** birakiyor. Damga hem puruzsuz
    hem de SVG'deki yuvarlak uc ve birlesimin karsiligini bedava verir.
    """
    r = width / 2
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _edge_points(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Cokgenin kenarlari boyunca ~1 piksel arayla noktalar (damga icin)."""
    out = []
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
        steps = max(1, int(math.hypot(x1 - x0, y1 - y0)))
        out += [(x0 + (x1 - x0) * t / steps, y0 + (y1 - y0) * t / steps)
                for t in range(steps)]
    return out


def _dense(curve: tuple[float, ...]) -> list[tuple[float, float]]:
    """Egriyi ardisik noktalar ~1 piksel arayla dusecek sikilikta ornekler."""
    rough = _bezier_points(curve, 16)
    length = sum(((rough[i + 1][0] - rough[i][0]) ** 2
                  + (rough[i + 1][1] - rough[i][1]) ** 2) ** 0.5
                 for i in range(len(rough) - 1))
    return _bezier_points(curve, max(24, int(length)))


def build_png(px: int, simple: bool | None = None) -> Image.Image:
    """`.ico` karesi. Asiri ornekleme ile cizilip kucultulerek yumusatilir.

    `simple` verilmezse boyuta gore secilir: `SIMPLE_MAX_PX` ve altinda
    sadelesmis cizim (genis aralik, parantezsiz), ustunde tam cizim.
    Karsilastirma tablosu ikisini de acikca isteyebilsin diye parametre birakildi.
    """
    if simple is None:
        simple = px <= SIMPLE_MAX_PX
    k = px * SS / BOX
    size = int(px * SS)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(RADIUS * k), fill=BG)

    gap, round_r = (SIMPLE_GAP, SIMPLE_ROUND) if simple else (BLADE_GAP, BLADE_ROUND)
    for quad, color in _blades(gap, round_r):
        pts = [(x * k, y * k) for x, y in quad]
        d.polygon(pts, fill=color)
        _stroke(d, _edge_points(pts), 2 * round_r * k, color)

    if not simple:
        for sign in (-1, 1):
            for curve in _brace_curves(sign):
                _stroke(d, _dense(tuple(v * k for v in curve)), BRACE_W * k, BRACE)

    return img.resize((px, px), Image.LANCZOS)


# --- Onizleme ---------------------------------------------------------------

def build_sheet() -> Image.Image:
    """Onizleme: buyuk boy + kucuk boylarin TAM ve SADELESMIS hali yan yana.

    Kucuk boyutlar NEAREST ile 4x buyutulur — 16 px'in gercekten okunup
    okunmadigi ancak piksel piksel gorulunce anlasilir; LANCZOS onu yalanci bir
    puruzsuzlukle gizlerdi. Iki surumu yan yana basmak sadelestirmenin
    gerceklen ise yarayip yaramadigini **gozle olculebilir** kilar.
    """
    big, pad, gap, row = 224, 18, 16, 20
    small = (48, 32, 16)
    zoom = 4
    band = max(small) * zoom              # kucuk satirin yuksekligi (192)

    w = pad * 2 + max(big, sum(n * zoom + gap for n in small) - gap)
    h = pad * 2 + row + big + gap + 2 * (row + band) + gap
    sheet = Image.new("RGBA", (w, h), (20, 22, 26, 255))
    d = ImageDraw.Draw(sheet)

    d.text((pad, pad), "224 px — tam cizim", fill="#8b93a3")
    f = build_png(big, simple=False)
    sheet.paste(f, (pad, pad + row), f)

    # Kucuk boyutlar iki satir: ustte TAM cizim, altta SADELESMIS. Yan yana
    # degil ALT ALTA basilir ki ayni boyut dogrudan karsilastirilabilsin.
    y = pad + row + big + gap
    for label, simple in (("48 / 32 / 16 px — tam", False),
                          ("48 / 32 / 16 px — sade (.ico yalnizca 16'da bunu kullanir)", True)):
        d.text((pad, y), label, fill="#8b93a3")
        x = pad
        for n in small:
            s = build_png(n, simple=simple).resize((n * zoom, n * zoom),
                                                   Image.NEAREST)
            sheet.paste(s, (x, y + row + band - n * zoom), s)
            x += n * zoom + gap
        y += row + band + gap
    return sheet


def main() -> None:
    ASSETS.mkdir(exist_ok=True)

    svg = WEB / "logo.svg"
    svg.write_text(build_svg(), encoding="utf-8")

    # ⚠ **`append_images` SART.** Yalnizca `sizes=` verilirse Pillow oteki
    # boyutlari uretmez — en buyuk goruntuyu kendi KUCULTUR (bkz.
    # `IcoImagePlugin._save`: eslesen boyut saglanmadiysa `thumbnail`).
    # Yani boyut basina ayri cizim yapip yalnizca `sizes=` yazmak, o cizimleri
    # sessizce cope atar; sadelesmis 16/32 px kareleri hic dosyaya girmezdi.
    # `check_logo` her kareyi ureticinin ciktisiyla karsilastirarak bunu
    # yakaliyor — nitekim ilk yazimda tam olarak bu oldu.
    frames = [build_png(n) for n in ICO_SIZES]
    ico = ASSETS / "icon.ico"
    frames[-1].save(ico, format="ICO", sizes=[(n, n) for n in ICO_SIZES],
                    append_images=frames[:-1])

    build_sheet().save(ASSETS / "icon-variants.png")

    print(f"logo.svg   {svg.stat().st_size} bayt")
    print(f"icon.ico   {ico.stat().st_size} bayt · {', '.join(map(str, ICO_SIZES))}")
    print("onizleme   assets/icon-variants.png")
    # Sozcuk isareti dosyaya YAZILMAZ: `index.html`deki satir ici kopya elle
    # (Edit ile) guncellenir ve `check_logo` bu ciktiyla karsilastirir.
    print("sozcuk isareti (index.html `#btn-app` icine):")
    print(wordmark_markup())


if __name__ == "__main__":
    main()
