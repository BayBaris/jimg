"""Gorunum: renk paletleri ve yazi tipi aileleri (`9.4`).

Ekran ile cizimin ORTAK sozlugu burasidir.

⚠ **Bu modul `i18n.py`nin renk karsiligidir.** Orada iki dil vardi, burada iki
tema var; ikisinde de deger uretildigi yerde degil, OKUNDUGU anda cozulur ve
gecerli secim modul duzeyinde durur (`set_theme`). Alternatif her cizim ve disa
aktarim imzasina bir `theme` parametresi gecirmekti — `lang` icin elenen
secenegin aynisi, onlarca imzayi kirletirdi.

⚠ **Anahtarlar CSS OZEL OZELLIK adlaridir**, bas kismindaki `--` olmadan:
`"panel-2"` → `--panel-2`. Boylece `check.py --> check_theme` eslesmeyi
mekanik olarak kurar; elle tutulan bir eslesme listesi (`CONST_PAIRS` gibi)
gerekmez ve yeni bir renk eklendiginde denetim kendiliginden kapsar.

⚠ **Buradaki her anahtar `style.css`te de BULUNMAK ZORUNDA** ve degeri ayni
olmali. Ters yon serbesttir: golgeler, imlecler ve yalnizca ekranda gorunen
tonlar CSS'te durur, Pillow'un onlara isi yoktur.

`SERIES` bunun istisnasidir ve bilerek CSS'te YOKTUR: grafik serisi renkleri
yalnizca cizimde kullanilir (grafik ekranda da Python'un urettigi SVG'dir),
CSS'e yazilsalardi kullanilmayan belirtec olarak dururlardi.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, NamedTuple

# Cizilebilir temalar. `SYSTEM` bir tema DEGIL, bir tercihtir: `set_theme`
# icinde ikisinden birine cozulur ve `get_theme()` her zaman cizilebilir bir ad
# dondurur (`i18n`de dilin `auto` degeriyle ayni kalip).
THEMES = ("dark", "light")
SYSTEM = "system"
CHOICES = (SYSTEM, *THEMES)      # ayarlar ekranindaki sira
DEFAULT_THEME = "dark"

# --- Paletler --------------------------------------------------------------
#
# Acik paletin kendi degerleri vardir, koyunun cevrilmisi DEGILDIR: koyu zemin
# icin secilmis pastel tonlar (`#7fd1a3`, `#e0af68`) beyaz uzerinde okunmuyor.
# Acik tarafta ton koyulasir, doygunluk artar.

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#14161a",
        "panel": "#1b1e24",
        "panel-2": "#21252d",
        "line": "#2c313b",
        "text": "#dfe3ea",
        "text-2": "#c6cddb",
        "muted": "#8b93a3",
        "accent": "#4c8dff",
        "accent-dim": "#2a3a56",
        "warn": "#d8a657",
        "row-alt": "#191c22",
        "bool": "#7fd1a3",
        "group-row": "#1d222b",
        "missing": "#1e222a",
        # Sutun gruplari — sira `columns.GROUP_ORDER` ile AYNI (bkz. `group_colors`).
        "g0": "#6ea8fe",
        "g1": "#c792ea",
        "g2": "#7fd1a3",
        "g3": "#e0af68",
        "g4": "#7dcfff",
        "g5": "#a0a8b8",
        "g6": "#6b7280",
    },
    "light": {
        "bg": "#f4f6f9",
        "panel": "#ffffff",
        "panel-2": "#eaeef4",
        "line": "#d3dae4",
        "text": "#161a20",
        "text-2": "#3f4855",
        "muted": "#5c6675",
        "accent": "#2563eb",
        "accent-dim": "#dce8ff",
        "warn": "#a86a00",
        "row-alt": "#eef1f6",
        "bool": "#147a4c",
        "group-row": "#e7ecf3",
        "missing": "#e4e8ee",
        "g0": "#2e5fbf",
        "g1": "#7a3fb5",
        "g2": "#147a4c",
        "g3": "#96650f",
        "g4": "#1f7391",
        "g5": "#4d5665",
        "g6": "#6b7280",
    },
}

# Grafik serisi renkleri. Sira ANLAMLIDIR: ilk seri ilk rengi alir ve iki tema
# arasinda ayni sirayla karsilik gelir — koyudan aciga gecen kullanici
# serilerin yer degistirdigini gormemeli.
SERIES: dict[str, list[str]] = {
    "dark": ["#4c8dff", "#7fd1a3", "#e0af68", "#c792ea", "#7dcfff",
             "#ff8a8a", "#a0a8b8", "#d8a657", "#6ea8fe", "#9ece6a"],
    "light": ["#2563eb", "#147a4c", "#a86a00", "#7a3fb5", "#1f7391",
              "#c02b2b", "#5c6675", "#8a5a12", "#3b6fd4", "#4d7c22"],
}


# --- Yazi tipi aileleri ----------------------------------------------------
#
# Liste KUCUK ve HAZIR tutulur; sistemdeki tum yazi tipleri taranmaz. Sebep
# kalinlik: Pillow'da kalin metin ayri bir TTF dosyasidir ve dosya adi aileden
# tahmin edilemez (`segoeui` → `segoeuib`, `georgia` → `georgiab`, ama pek cok
# ailede baska bir sema var). Taranan bir listede cogu aile kalin metni normal
# agirlikta basardi — ekranda kalin, PNG'de duz.
#
# ⚠ **Bir aile UC ayri bicimde tanimlanmak zorunda**, cunku uc arka uc yazi
# tipini uc ayri sekilde istiyor:
#   `css`  — tarayici yigini. SVG ciktisina yazilir ve `style.css`teki
#            `--font` ile AYNI olmali (`check_theme` karsilastirir).
#   `pdf`  — PDF'in base-14 adlari. Gomulu yazi tipi yok (`K-12`), yani
#            secim bu ucluyle sinirli: Helvetica · Times · Courier.
#   TTF    — Pillow adaylari; SIRALI, ilk bulunan kullanilir. Sonuncular
#            Windows disi bir ortam icin (DejaVu, cogu Linux'ta var).
#
# Anahtar ucunu de baglar; adlarin ayni aileyi gosterdigini INSAN bilir,
# denetim degil ("Georgia" ↔ `georgia.ttf` ↔ `Times-Roman`).

FONT_DEFAULT = "system"


class Family(NamedTuple):
    css: str
    pdf: tuple[str, str]          # (duz, kalin)
    regular: tuple[str, ...]
    bold: tuple[str, ...]


FONTS: dict[str, Family] = {
    "system": Family(
        css='"Segoe UI", system-ui, sans-serif',
        pdf=("Helvetica", "Helvetica-Bold"),
        regular=("segoeui.ttf", "arial.ttf", "tahoma.ttf", "verdana.ttf",
                 "DejaVuSans.ttf"),
        bold=("segoeuib.ttf", "arialbd.ttf", "tahomabd.ttf", "verdanab.ttf",
              "DejaVuSans-Bold.ttf"),
    ),
    "serif": Family(
        css='Georgia, "Times New Roman", serif',
        pdf=("Times-Roman", "Times-Bold"),
        regular=("georgia.ttf", "times.ttf", "DejaVuSerif.ttf"),
        bold=("georgiab.ttf", "timesbd.ttf", "DejaVuSerif-Bold.ttf"),
    ),
    "mono": Family(
        css='Consolas, "Cascadia Mono", ui-monospace, monospace',
        pdf=("Courier", "Courier-Bold"),
        regular=("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"),
        bold=("consolab.ttf", "courbd.ttf", "DejaVuSansMono-Bold.ttf"),
    ),
}


# --- Olculer: yazi tipi boyutundan turer -----------------------------------
#
# ⚠ **Taban boyutta (12) bugunku sayilarin AYNISI cikmali.** Formuller ona gore
# secildi; biri degistirilirse varsayilan gorunum sessizce kayar:
#   font 12 · title 16 · small 10 · row 26 · head 30 · group 22 · wrap 16
#   title_h 46 · char_w 7
#
# ⚠ **`char_w` TAMSAYI aritmetigiyle hesaplanir** (`* 7 // 12`), yuvarlama ile
# degil: ayni sayiyi tarayicidaki JS de uretmek zorunda ve `round()` iki dilde
# ayni davranmiyor (Python bankaci yuvarlamasi yapar). Bolme once carpma sonra
# taban alma sirasiyla yazilirsa iki taraf her boyutta ayni tamsayiyi verir.

FONT_SIZES = (11, 12, 13, 14, 16)
FONT_SIZE_DEFAULT = 12

# 9.19.1 — satir yogunlugu: tablo GOVDESINDEKI hucrenin ust/alt dolgusu (px).
# Ekran `td` dolgusunu, cizim satir yuksekligini AYNI sayidan turetir
# (`Metrics.cell_pad_y`); baslik satiri, grup seridi ve agac etkilenmez.
DENSITIES = ("compact", "normal", "comfortable")
DENSITY_DEFAULT = "normal"
CELL_PAD_Y = {"compact": 3, "normal": 6, "comfortable": 10}

# 9.19.3 — disa aktarimin temasi. `app`: uygulamayla ayni (bugune kadarki
# davranis); otekiler ciktiyi o temaya SABITLER — koyu temada calisip beyaz
# zemine basmak isteyen icin. Sira ayarlar ekranindaki siradir.
EXPORT_APP = "app"
EXPORT_THEMES = (EXPORT_APP, "light", "dark")

CHAR_W_BASE = 7        # taban boyutta karakter basina piksel (`state.js` ile esit)
BADGE_CHAR_W_BASE = 5  # ayni sey, basliktaki kucuk tip rozeti icin
SIZE_BASE = 12         # iki katsayinin da olculdugu boyut


class Metrics(NamedTuple):
    """Cizimin boyuta bagli olculeri. `TH.metrics()` ile CIZIM ANINDA okunur."""

    font: int
    title: int
    small: int
    title_h: int
    row_h: int
    head_h: int
    group_h: int
    wrap_line_h: int
    cell_pad_y: int
    char_w: int
    badge_char_w: int


# --- Gecerli tema, yazi tipi ve boyut --------------------------------------

_current = DEFAULT_THEME
_family = FONT_DEFAULT
_size = FONT_SIZE_DEFAULT
_density = DENSITY_DEFAULT
# Disa aktarim sirasinda GECICI tema (`using`). Is parcacigina ozel: kopru her
# cagriyi kendi is parcaciginda calistirir ve modul degiskenini gecici
# degistirmek, ayni anda cizilen baska bir ciktiyi yanlis temaya dusururdu.
_local = threading.local()


def detect_theme() -> str:
    """Isletim sisteminin UYGULAMA temasi.

    Windows bunu kayit defterinde tutuyor: `AppsUseLightTheme` 1 ise acik.
    Yanindaki `SystemUsesLightTheme` GOREV CUBUGU icindir ve ayri ayarlanabilir
    — uygulama penceresi icin dogru anahtar bu degil.

    ⚠ Cozum BURADA yapilir, CSS'te `prefers-color-scheme` ile degil. Iki ayri
    yerde karar verilseydi (WebView2 kendi medya sorgusuyla, Python kayit
    defteriyle) ekran ile PNG farkli temaya duserdi — tam da bu fazin engellemek
    icin var oldugu sey. Arayuze COZULMUS deger gider.

    Okunamayan anahtar, Windows disi bir sistem ya da beklenmedik tip:
    varsayilan tema. Tercih bir kolayliktir, uygulamayi durdurmamali.
    """
    if sys.platform != "win32":
        return DEFAULT_THEME
    try:
        import winreg

        key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            light, _ = winreg.QueryValueEx(handle, "AppsUseLightTheme")
    except (OSError, ValueError):
        return DEFAULT_THEME
    return "light" if light else "dark"


def set_theme(name: str | None) -> str:
    """Gecerli temayi kurar ve CIZILEBILIR adi dondurur.

    `"system"` isletim sisteminden cozulur. Taninmayan ad varsayilana duser —
    bozuk bir ayar dosyasi cizimi durdurmamali (`settings.load` ile ayni tutum).
    """
    global _current
    if name == SYSTEM:
        name = detect_theme()
    _current = name if name in THEMES else DEFAULT_THEME
    return _current


def get_theme() -> str:
    """CIZILECEK tema: disa aktarim sabitlemesi varsa o, yoksa uygulamanin temasi."""
    return getattr(_local, "theme", None) or _current


@contextmanager
def using(name: str | None) -> Iterator[None]:
    """Blok boyunca cizimi verilen temaya sabitler (9.19.3).

    `app`, `None` ya da taninmayan ad: sabitleme yok, uygulamanin temasi
    gecerli kalir — bozuk bir ayar ciktiyi durdurmamali. Ic ice kullanimda
    dis blogun degeri geri gelir.
    """
    prev = getattr(_local, "theme", None)
    _local.theme = name if name in THEMES else prev
    try:
        yield
    finally:
        _local.theme = prev


def set_font(name: str | None) -> str:
    """Gecerli yazi tipi ailesini kurar ve kurulan anahtari dondurur.

    Taninmayan ad varsayilana duser: eski bir ayar dosyasinda bos dize
    (`9.1`'in ilk semasi) ya da artik sunulmayan bir aile durabilir.
    """
    global _family
    _family = name if name in FONTS else FONT_DEFAULT
    return _family


def get_font() -> str:
    return _family


def font_files(bold: bool = False) -> tuple[str, ...]:
    """Gecerli ailenin TTF adaylari — ilk bulunan kullanilir (`draw._font`)."""
    fam = FONTS[_family]
    return fam.bold if bold else fam.regular


def set_size(size: Any) -> int:
    """Yazi tipi boyutunu kurar. Listede olmayan deger varsayilana duser."""
    global _size
    _size = size if size in FONT_SIZES else FONT_SIZE_DEFAULT
    return _size


def get_size() -> int:
    return _size


def set_density(name: Any) -> str:
    """Satir yogunlugunu kurar. Taninmayan deger varsayilana duser."""
    global _density
    _density = name if name in DENSITIES else DENSITY_DEFAULT
    return _density


def get_density() -> str:
    return _density


def metrics() -> Metrics:
    """Gecerli boyutun olculeri."""
    n = _size
    pad = CELL_PAD_Y[_density]
    return Metrics(
        font=n,
        title=n + 4,
        small=n - 2,
        title_h=n * 3 + 10,
        # Yogunluk satiri iki dolgu farki kadar acar/kapatir; `normal`de
        # sonuc `9.19`dan onceki formulle birebir aynidir.
        row_h=n * 2 + 2 + 2 * (pad - CELL_PAD_Y[DENSITY_DEFAULT]),
        head_h=n * 2 + 6,
        group_h=n * 2 - 2,
        wrap_line_h=n + 4,
        cell_pad_y=pad,
        char_w=n * CHAR_W_BASE // SIZE_BASE,
        badge_char_w=n * BADGE_CHAR_W_BASE // SIZE_BASE,
    )


def font_css() -> str:
    """Gecerli ailenin tarayici yigini — SVG ciktisina yazilir."""
    return FONTS[_family].css


def font_pdf(bold: bool = False) -> str:
    """Gecerli ailenin PDF base-14 adi."""
    return FONTS[_family].pdf[1 if bold else 0]


class Palette:
    """Palete NITELIKLE erisim: `p.accent_dim` → `PALETTES[...]["accent-dim"]`.

    Tek kural var ve o da ad donusumu: alt cizgi tireye cevrilir. Sozluk
    erisimi (`p["accent-dim"]`) de acik birakildi — dinamik anahtar gerektiginde
    (grup renkleri, `g0`…`g6`) niteligi elde kurmak zorunda kalmayalim.
    """

    __slots__ = ("_c",)

    def __init__(self, colors: dict[str, str]) -> None:
        self._c = colors

    def __getattr__(self, name: str) -> str:
        try:
            return self._c[name.replace("_", "-")]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, key: str) -> str:
        return self._c[key]


def active() -> Palette:
    """Gecerli temanin paleti."""
    return Palette(PALETTES[get_theme()])


def series() -> list[str]:
    """Gecerli temanin grafik serisi renkleri."""
    return SERIES[get_theme()]


def group_colors(order: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Grup anahtari → renk. Sira `columns.GROUP_ORDER`den gelir.

    Renkler paletten `g0`…`g6` olarak okunur, cunku CSS tarafinda da indeksle
    dagitiliyorlar (`.group-row th.g-3`). Eslemeyi burada kurmak, ayni sirayi
    ucuncu bir yere yazmaktan iyi: `check_i18n` zaten `ORDER_GROUPS` ile
    `GROUP_ORDER` esitligini denetliyor.
    """
    p = PALETTES[get_theme()]
    return {key: p[f"g{i}"] for i, key in enumerate(order)}
