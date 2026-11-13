"""Belgenin ICINDEKI gorselleri bulur ve okur.

Kaynaklar (`K-10`):
  data  — `data:image/png;base64,…` veya on eki olmayan ham base64
  file  — belgenin bulundugu klasore GORELI yol (`assets/icon.png`); yalnizca
          klasorun ALTINDA cozulur, `..` ile disari cikan yol reddedilir
  file  — MUTLAK yol (`C:\\…`), yalnizca belge basina IZINLE (`9.6.5.1`)
  url   — https adresi, yalnizca `settings.images.allow_url` ile: galeri,
          kaydetme ve tablo hucresinin onizlemesi (`9.6.5.2`, `K-32`; ag tarafi
          `remote_images.py`). Tablo KURULURKEN istek gitmez

Izin `Sources` nesnesiyle elden tasinir; modulde durum yoktur. UNC yollari
(`\\\\sunucu\\pay`) hicbir durumda acilmaz: diskten degil agdan okunur. http(s)
adresleri ayar kapaliyken hic istenmez, acikken tablo hucresi yine istemez. Paylasilan bir JSON'un isaret ettigi rastgele dosyayi
izinsiz acmamak aracin guvenlik sinirlarindan biridir.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
import re
from pathlib import Path
from typing import Any, NamedTuple, TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from . import i18n as I18N

if TYPE_CHECKING:                       # yalnizca tip denetimi icin
    from PIL import Image

# ⚠ Pillow TEPEDEN ice aktarilmaz (Faz 8.6). Bu modulu `flatten` ice aktariyor,
# `flatten`i de `chart_data` — yani grafik sutun listesi gibi CIZIM YAPMAYAN her
# yol Pillow'u bosuna yukluyordu (56 ms). Ice aktarma, goruntuye gercekten
# dokunan iki islevin icinde. Zincir `check.py --> check_import_chain` ile
# denetlenir; tepeye tasinirsa kazanc sessizce kaybolur.

# Pillow ile islenebilen bicimler.
RASTER_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
}
# SVG yalnizca arayuzde gosterilir; Pillow onu acamaz, PNG ciktisina girmez.
VECTOR_MIME = {"svg": "image/svg+xml"}
ALL_EXT = {"." + e for e in (*RASTER_MIME, *VECTOR_MIME)}

# 9.6.4 — kaydedilecek dosyanin uzantisi. `RASTER_MIME`in TERSI degil: `jpg` ve
# `jpeg` ayni mime'a gidiyor, geri donuste tek bir uzanti secilmeli.
MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
            "image/webp": "webp", "image/bmp": "bmp", "image/svg+xml": "svg"}

# Windows'ta dosya adi olamayan kok adlar; uzanti kurtarmaz (`con.png` da olmaz).
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME_STEM = 120       # JSON yolu uzun olabilir; turetilen ad kirpilir

# 9.6.5.1 — yol turleri; `path_kind` bunlardan birini dondurur.
PATH_RELATIVE, PATH_ABSOLUTE, PATH_UNC = "relative", "absolute", "unc"


class Sources(NamedTuple):
    """Belgenin gorselleri hangi kaynaklardan okunabilir — IZIN, deger degil.

    Once her okuyucu yalnizca `base_dir` aliyordu; izin bilgisi hicbir imzada
    yoktu ve mutlak yol sabit bir kosulla reddediliyordu. Politika artik
    okuyucudan okuyucuya ELDEN tasiniyor, modulde durum tutulmuyor: iki belge
    ayni anda farkli izinle acik olabilir (`9.6.5.1`).
    """
    base_dir: Path | None = None
    absolute: bool = False      # belge basina onay (`Api.gallery_allow_absolute`)
    url: bool = False           # 9.6.5.2 — `settings.images.allow_url`


DATA_URI = re.compile(r"^data:(image/[a-z0-9.+-]+);base64,\s*(.+)$", re.IGNORECASE | re.DOTALL)

# Ham base64'un ilk karakterleri bicimi ele verir; tum metni cozmeye gerek yok.
B64_PREFIX = {
    "iVBORw0KGgo": "image/png",
    "/9j/": "image/jpeg",
    "R0lGODdh": "image/gif",
    "R0lGODlh": "image/gif",
    "Qk": "image/bmp",
    "UklGR": "image/webp",
}

MAX_PATH_LEN = 260        # daha uzun metinler yol olamaz, dosya sistemine sorulmaz
MAX_URL_LEN = 2048        # 9.6.5.2 — daha uzun metin gorsel adresi sayilmaz
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
MIN_B64_LEN = 64          # daha kisa metinler gorsel tasiyamaz
THUMB_PX = 96             # tablo hucresindeki onizleme kenari
MAX_SCAN = 400            # bir belgede en fazla kac gorsel toplanir

# 9.6.1 — URETIM boyutu GOSTERIM boyutundan ayridir. Onizlemeyi kim isterse
# gosterecegi kutuyu soyler; buradaki iki sayi yalnizca sinirdir. Once tek bir
# `PREVIEW_PX = 900` vardi ve galeri her gorseli o boyda uretiyordu: 124 px'lik
# bir kart icin 900 px'lik PNG.
PREVIEW_PX = 400          # kutu belirtilmezse kullanilan uretim kenari
MAX_PREVIEW_PX = 900      # istenen kutu ne olursa olsun asilmaz
MAX_PIXELS = 40_000_000   # bu olcunun ustundeki gorselin GOVDESI cozulmez


def _b64_mime(text: str) -> str | None:
    for prefix, mime in B64_PREFIX.items():
        if text.startswith(prefix):
            return mime
    return None


def detect(value: Any) -> dict | None:
    """Bir degerin gorsel tasiyip tasimadigini DOSYAYA DOKUNMADAN sinar.

    Dondurulen tanimlayici hafiftir; icerik `load()` ile istendiginde okunur.
    Buyuk belgelerde her metin icin disk erisimi yapmamak kritiktir.
    """
    if not isinstance(value, str) or len(value) < 3:
        return None

    m = DATA_URI.match(value.strip())
    if m:
        return {"source": "data", "mime": m.group(1).lower(), "payload": m.group(2)}

    stripped = value.strip()
    if len(stripped) >= MIN_B64_LEN:
        mime = _b64_mime(stripped)
        if mime:
            return {"source": "data", "mime": mime, "payload": stripped}

    # 9.6.5.2 — adres. Eskiden `https://…/x.png` goreli DOSYA saniliyordu ve
    # belge klasorunde aranip reddediliyordu. http de TANINIR (dosya sanilmasin),
    # ama `remote_images.allowed` onu hicbir durumda acmaz.
    if URL_RE.match(stripped):
        if len(stripped) > MAX_URL_LEN or any(c.isspace() for c in stripped):
            return None
        try:
            suffix = Path(unquote(urlsplit(stripped).path)).suffix.lower()
        except ValueError:
            return None
        if suffix not in ALL_EXT:
            return None                  # uzantisiz adres: anlamak icin istek gerekirdi
        return {"source": "url", "url": stripped,
                "mime": RASTER_MIME.get(suffix[1:]) or VECTOR_MIME.get(suffix[1:])}

    if len(stripped) <= MAX_PATH_LEN and "\n" not in stripped:
        suffix = Path(stripped).suffix.lower()
        if suffix in ALL_EXT:
            return {"source": "file", "mime": RASTER_MIME.get(suffix[1:]) or VECTOR_MIME.get(suffix[1:]),
                    "path": stripped}
    return None


def path_kind(raw: str) -> str:
    """Yolun turu — dosya sistemine DOKUNMADAN (`9.6.5.1`).

    ⚠ `Path.is_absolute()` tek basina yetmez: Windows'ta surucusuz kok yol
    (`\\x\\a.png`) ona gore goreli sayilir ama belge klasorune degil gecerli
    surucunun kokune gider. Iki bolu ile baslayan her bicim (`\\\\sunucu\\pay`,
    `\\\\?\\`, `//sunucu`) UNC sayilir: diskten degil AGDAN okunabilir.
    """
    norm = raw.replace("\\", "/")
    if norm.startswith("//"):
        return PATH_UNC
    if norm.startswith("/") or re.match(r"[A-Za-z]:/", norm):
        return PATH_ABSOLUTE
    return PATH_RELATIVE


def resolve(desc: dict, src: Sources) -> Path | None:
    """Dosya kaynagini diskteki yola cevirir; izin disindakini REDDEDER.

    Goreli yol belge klasorunun ALTINDA cozulur. Mutlak yol yalnizca
    `src.absolute` ile — belge basina onay. UNC hicbir durumda: onay "diskimdeki
    dosya" icin verilir, ag paylasimi onun kapsaminda degil ve Windows o adrese
    baglanirken kullanicinin kimlik bilgisini gonderir.

    ⚠ Izin disindaki yolda dosya sistemine HIC dokunulmaz — `resolve()` ve
    `is_file()` dahil. Goreli kacis (`../disari/x.png`) bu yuzden once
    SOZDIZIMSEL olarak reddedilir; eskiden once diskte cozuluyor, sonra
    reddediliyordu. Cozulmus yolda ikinci denetim baglantilar icin durur.
    """
    if desc.get("source") != "file":
        return None
    raw = desc["path"]
    kind = path_kind(raw)
    if kind == PATH_UNC or (kind == PATH_ABSOLUTE and not src.absolute):
        return None
    try:
        if kind == PATH_ABSOLUTE:
            target = Path(raw).resolve()
        else:
            if src.base_dir is None:
                return None
            base = src.base_dir.resolve()
            lexical = Path(os.path.normpath(base / raw.replace("\\", "/")))
            lexical.relative_to(base)        # sozdizimsel kacis: diske inmeden
            target = lexical.resolve()
            target.relative_to(base)         # baglanti disari cikariyorsa
    except (ValueError, OSError):
        return None
    if target.drive.startswith("\\\\"):      # baglanti bir ag paylasimina cikti
        return None
    return target if target.is_file() else None


def load(desc: dict, src: Sources) -> bytes | None:
    """Gorsel baytlarini dondurur; okunamazsa None."""
    if desc["source"] == "data":
        try:
            return base64.b64decode(desc["payload"], validate=False)
        except (binascii.Error, ValueError):
            return None

    if desc["source"] == "url":
        # 9.6.5.2 — AG. Izin (`src.url`) yoksa modul hic yuklenmez; adres kurali
        # (`allowed`) `fetch` icinde ayrica sinanir.
        if not src.url:
            return None
        from . import remote_images as RM
        return RM.fetch(desc["url"])

    target = resolve(desc, src)
    if target is None:
        return None
    try:
        return target.read_bytes()
    except OSError:
        return None


def _data_uri(mime: str, raw: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _open_header(fp: io.BytesIO):
    """Yalnizca BASLIGI okur: bicim ve olcu gelir, govde cozulmez.

    Pillow'un bomba uyarisi burada bastirilir cunku karar bize ait: olcuyu
    okuyup `MAX_PIXELS` ile kendimiz karsilastiriyoruz. Bastirilmasaydi her
    dogrulama kosusunun basina bir `DecompressionBombWarning` dusuyordu ve
    sessiz kip artik sessiz olmuyordu.
    """
    import warnings

    from PIL import Image

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        try:
            return Image.open(fp)
        except Exception:
            return None


def open_image(desc: dict, src: Sources) -> Image.Image | None:
    """Pillow goruntusu acar. SVG icin None doner (Pillow acamaz).

    ⚠ `MAX_PIXELS`i asan gorsel COZULMEZ (`9.6.1`). Basligi okumak ucuzdur,
    govdeyi cozmek degil: orneklerden birinde 104 megapiksellik bir PNG var ve
    `load()` onu ~400 MB'a aciyordu. Paylasilan bir JSON'un isaret ettigi
    gorselin boyu bizim denetimimizde degil — sinir Pillow'un kendi bomba
    uyarisiyla ayni yeri koruyor, ama uyari yerine MODELLENMIS bir sonuc verir.
    """
    from PIL import Image

    if desc.get("mime") in VECTOR_MIME.values():
        return None
    raw = load(desc, src)
    if raw is None:
        return None
    try:
        img = _open_header(io.BytesIO(raw))
        if img is None or img.width * img.height > MAX_PIXELS:
            return None
        img.load()
        return img
    except Exception:
        return None


def thumbnail(desc: dict, src: Sources, box: int = THUMB_PX) -> dict | None:
    """Kucultulmus onizleme uretir: {uri, width, height}.

    SVG kucultulemez; oldugu gibi gecirilir (arayuz zaten olceklendirir).
    """
    if desc.get("mime") in VECTOR_MIME.values():
        raw = load(desc, src)
        return {"uri": _data_uri(desc["mime"], raw), "width": box, "height": box} if raw else None

    from PIL import Image

    img = open_image(desc, src)
    if img is None:
        return None

    w, h = img.size
    img = img.convert("RGBA") if img.mode in ("P", "LA", "RGBA") else img.convert("RGB")
    img.thumbnail((box, box), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"uri": _data_uri("image/png", buf.getvalue()),
            "width": img.width, "height": img.height,
            "source_width": w, "source_height": h}


# --- Belge taramasi --------------------------------------------------------

def _path_str(path: list) -> str:
    parts: list[str] = []
    for p in path:
        parts.append(f"[{p}]" if isinstance(p, int) else ("." if parts else "") + str(p))
    return "".join(parts) or "$"


def scan(root: Any, src: Sources, limit: int = MAX_SCAN) -> list[dict]:
    """Belgeyi gezip gorsel tasiyan tum degerleri toplar."""
    found: list[dict] = []

    def walk(node: Any, path: list) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [k])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [i])
        else:
            desc = detect(node)
            if desc is None:
                return
            if desc["source"] == "file" and resolve(desc, src) is None:
                return               # yol cozulemedi, gorsel sayilmaz
            if desc["source"] == "url" and not url_permitted(desc, src):
                return               # izin ya da adres kurali yok: istek de yok
            found.append({"json_path": _path_str(path), "desc": desc})

    walk(root, [])
    return found


def _measure(desc: dict, src: Sources) -> tuple[int, int, int] | None:
    """(genislik, yukseklik, bayt) — KUCULTMEDEN. Okunamayan gorselde None.

    Baslik yeter; LANCZOS + PNG yeniden kodlama bedeli odenmez. SVG'nin ic
    olcusu yoktur, sifir donulur ve olceklendirmeyi ekran yapar.

    ⚠ Adres INDIRILMEZ (`9.6.5.2`): liste her gorsel icin baytlari okuyor ve
    adreste bu, galeri acilir acilmaz 400 istege kadar ag trafigi demekti.
    Olcu ve bayt onizleme istendikce gelir (`thumbs`).
    """
    if desc["source"] == "url":
        return 0, 0, 0
    raw = load(desc, src)
    if raw is None:
        return None
    if desc.get("mime") in VECTOR_MIME.values():
        return 0, 0, len(raw)

    img = _open_header(io.BytesIO(raw))
    return (img.width, img.height, len(raw)) if img is not None else None


def _origin_parts(desc: dict, src: Sources) -> tuple[str | None, str | None]:
    """(grup, ad) — kaynaga gore gruplama ve kart basligi icin (`9.6.3`).

    Gomulu gorselin ne klasoru ne dosya adi vardir; ikisi de `None` doner ve
    arayuz JSON yoluna duser. Dosya kaynaginda grup, belge klasorune GORELI ust
    klasordur (`assets`) — belgenin yaninda duran gorselde bos dize.

    Belge klasorunun DISINDAKI mutlak yollu gorselin (`9.6.5.1`) goreli bir
    karsiligi yoktur; grubu o zaman mutlak ust klasordur. Grup yalnizca bu
    durumda mutlak yol tasir — ayni klasoru baska turlu adlandirmanin yolu yok.
    """
    if desc["source"] == "url":
        # 9.6.5.2 — grup ana makine, ad son yol parcasi (`9.6.3`teki kural).
        parts = urlsplit(desc["url"])
        return (parts.hostname or "").lower() or None, Path(unquote(parts.path)).name or None

    target = resolve(desc, src)
    if target is None:
        return None, None
    if src.base_dir is not None:
        try:
            rel = target.relative_to(src.base_dir.resolve())
            parent = rel.parent.as_posix()   # belgenin yanindaki dosyada "."
            return ("" if parent == "." else parent), target.name
        except (ValueError, OSError):
            pass
    return target.parent.as_posix(), target.name


def catalog(root: Any, src: Sources, limit: int = MAX_SCAN) -> list[dict]:
    """Galeri listesi — ONIZLEME TASIMAZ (9.6.1).

    Onceki hali her gorselin 900 px'lik data URI'sini tek yanitta yolluyordu;
    yuz gorselli bir belgede yanit onlarca megabayt oluyordu ve hepsi kart
    ekrana girmeden uretiliyordu. Onizleme artik `thumbs()` ile parca parca
    istenir.
    """
    items = []
    for hit in scan(root, src, limit):
        desc = hit["desc"]
        measured = _measure(desc, src)
        if measured is None:
            continue                     # acilamayan gorsel listeye girmez
        width, height, nbytes = measured
        group, name = _origin_parts(desc, src)
        items.append({
            # 9.6.3 — KAYNAK ayrimi: `group` gruplama anahtari, `name` kart
            # basligi. Ikisi de `origin` METNINDEN degil cozulmus yoldan
            # turuyor; `origin` cevrilebilir bir gosterim dizesidir ve dil
            # degisince gruplar ikiye bolunurdu.
            "group": group,
            "name": name,
            "json_path": hit["json_path"],
            "source": desc["source"],
            # ⚠ `origin` GOSTERIM metnidir, karsilastirilamaz. Kaynak ayrimi
            # gereken yerde `embedded` bayragi kullanilir — `cell.embedded` ile
            # ayni tuzak (Faz 9.2.2): ceviri dize esitligini koparirdi.
            "origin": desc.get("path") or desc.get("url") or I18N.t("gallery.embedded"),
            # Eskiden `not desc.get("path")` idi; adres geldiginde (`9.6.5.2`)
            # yolu olmayan her sey gomulu sayilirdi.
            "embedded": desc["source"] == "data",
            "mime": desc.get("mime"),
            # Cozulmus TAM yol — yalnizca dosya kaynagi icin. `origin` belgede
            # YAZDIGI gibi (`assets/p-1001.png`), bu ise diskteki karsiligi;
            # Ayrinti kipi kaynagi tam haliyle gosteriyor (`9.6.2`). Birlestirme
            # arayuzde yapilmiyor: ayrac ve `..` cozumu Python'un isi.
            "full": desc.get("url") or (str(resolved) if (resolved := resolve(desc, src)) else None),
            "width": width,
            "height": height,
            "bytes": nbytes,
            # Onizlemesi HIC uretilmeyecek gorsel (`MAX_PIXELS`): arayuz onu
            # istemez, bos bir kart birakmak yerine sebebini yazar.
            "oversize": width * height > MAX_PIXELS,
        })
    # 9.6.3 — grup SIRASI burada, arayuzde degil: gomulu -> belge klasoru ->
    # klasorler alfabetik; grup icinde belge sirasi korunur (`sorted` kararli).
    # Sira once JS'te bir karsilastiriciya birakilmisti ve orada `null` anahtar
    # uzerinde `localeCompare` cagriliyordu — denetimin ulasamadigi bir yerde.
    return sorted(items, key=_group_rank)


def _group_rank(item: dict) -> tuple[int, str]:
    group = item["group"]
    if item["source"] == "url":
        return 4, (group or "").casefold()   # adresler en sonda, ana makineye gore
    if group is None:
        return 0, ""
    if group == "":
        return 1, ""
    # Belge klasorunun disindaki mutlak gruplar goreli klasorlerden SONRA (`9.6.5.1`).
    return (3 if path_kind(group) == PATH_ABSOLUTE else 2), group.casefold()


def _count_refs(root: Any, keep, limit: int) -> int:
    count = 0

    def walk(node: Any) -> None:
        nonlocal count
        if count >= limit:
            return
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        else:
            desc = detect(node)
            if desc and keep(desc):
                count += 1

    walk(root)
    return count


def absolute_refs(root: Any, limit: int = MAX_SCAN) -> int:
    """Mutlak yolla isaret edilen gorsel sayisi — dosyaya DOKUNMADAN (`9.6.5.1`).

    Sayim sozdizimseldir: izin istenirken diskte o dosyanin gercekten olup
    olmadigina bakmak, izinden once dosya sistemini yoklamak olurdu. Bu yuzden
    izinden sonra gorunen sayi daha az olabilir; mesaj "N gorsel var" demez,
    "N gorsele isaret ediyor" der.
    """
    return _count_refs(root, lambda d: d["source"] == "file"
                       and path_kind(d["path"]) == PATH_ABSOLUTE, limit)


def url_refs(root: Any, limit: int = MAX_SCAN) -> int:
    """Ayar acilsa istek gidebilecek adres sayisi — AGA CIKMADAN (`9.6.5.2`).

    Adres kuralini gecmeyenler (http, yerel ag, parolali) SAYILMAZ: ayar onlari
    hic acmayacak, bilgi cubugu acacakmis gibi soylemesin.
    """
    from . import remote_images as RM

    return _count_refs(root, lambda d: d["source"] == "url" and RM.allowed(d["url"]), limit)


def url_permitted(desc: dict, src: Sources) -> bool:
    """Adres okunabilir mi — izin VE adres kurali, AGA CIKMADAN (`9.6.5.2`)."""
    if not src.url:
        return False
    from . import remote_images as RM

    return RM.allowed(desc["url"])


def thumbs(root: Any, src: Sources, json_paths: list[str],
           box: int = PREVIEW_PX, limit: int = MAX_SCAN) -> list[dict]:
    """Yalnizca ISTENEN gorsellerin onizlemesini uretir.

    Belge her cagride yeniden taranir; tanimlayicilar onbellege ALINMAZ. Tarama
    dosyaya dokunmaz (`detect` metin isi, `resolve` yalnizca `is_file`), asil
    bedel kuculttmedir — onbellek ise belge kapaninca temizlenmesi gereken
    ikinci bir durum olurdu (`_drop_views` kalibi) ve bayat onizleme uretirdi.
    """
    want = set(json_paths)
    if not want:
        return []
    box = max(16, min(int(box), MAX_PREVIEW_PX))

    hits = [h for h in scan(root, src, limit) if h["json_path"] in want]

    # 9.6.5.2 — adresler PARALEL indirilir, sonuc onbellege girer; asagidaki
    # `thumbnail` onbellekten okur. Sirayla olsa cevrimdisi bir galeri her kart
    # icin zaman asimini beklerdi.
    urls = [h["desc"]["url"] for h in hits if h["desc"]["source"] == "url"]
    if urls and src.url:
        from . import remote_images as RM
        RM.fetch_many(urls)

    out = []
    for hit in hits:
        thumb = thumbnail(hit["desc"], src, box)
        if thumb is None:
            continue                     # uretilemedi: kart onizlemesiz kalir
        entry = {"json_path": hit["json_path"], "uri": thumb["uri"],
                 "width": thumb["width"], "height": thumb["height"]}
        if hit["desc"]["source"] == "url":
            # Liste adresin olcusunu bilmiyordu (indirmez); onizlemeyle gelir.
            raw = load(hit["desc"], src)     # onbellekten — ikinci istek yok
            entry.update(source_width=thumb.get("source_width", thumb["width"]),
                         source_height=thumb.get("source_height", thumb["height"]),
                         bytes=len(raw) if raw else 0)
        out.append(entry)
    return out


# --- Kaydetme adlari (9.6.4) -----------------------------------------------

def export_name(desc: dict, json_path: str) -> str:
    """Kaydedilecek dosyanin adi — KAYNAKTAN turer (`9.6.4`).

    Dosya kaynaginda belgede yazan ad aynen kalir. Gomulu gorselin adi yoktur;
    JSON yolu belgede biricik olan tek seydir, dosya adina guvenli bicimde
    cevrilir ve uzanti mime'dan gelir. Disk erisimi YOK — saf islev.
    """
    if desc.get("source") == "file":
        return Path(desc["path"].replace("\\", "/")).name
    if desc.get("source") == "url":
        # 9.6.5.2 — adresin son yol parcasi; sorgu dizesi ada girmez. Parca
        # kullanilamazsa (bos, ayrilmis ad) asagidaki JSON yolu kuralina duser.
        name = Path(unquote(urlsplit(desc["url"]).path)).name
        stem = re.sub(r"[^\w-]+", "-", Path(name).stem)[:MAX_NAME_STEM].strip("-")
        if stem and stem.upper() not in WIN_RESERVED:
            return f"{stem}{Path(name).suffix.lower()}"
    stem = re.sub(r"[^\w-]+", "-", json_path)[:MAX_NAME_STEM].strip("-") or "image"
    if stem.upper() in WIN_RESERVED:
        stem = "_" + stem
    return f"{stem}.{MIME_EXT.get(desc.get('mime'), 'bin')}"


def unique_names(names: list[str], taken: set[str] | None = None) -> list[str]:
    """Cakisan adlara `-2`, `-3` ekler; sira korunur (`9.6.4`).

    ⚠ Karsilastirma BUYUK/KUCUK HARFE DUYARSIZ: Windows'ta `Logo.png` ile
    `logo.png` ayni dosyadir ve duyarli bir karsilastirma ikincisini birincinin
    yerine yazdirirdi. `taken` hedef klasorde zaten duran adlardir.
    """
    used = {n.casefold() for n in (taken or ())}
    out: list[str] = []
    for name in names:
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        candidate, i = name, 2
        while candidate.casefold() in used:
            candidate = f"{stem}-{i}{dot}{ext}"
            i += 1
        used.add(candidate.casefold())
        out.append(candidate)
    return out
