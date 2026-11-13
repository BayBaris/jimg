"""Sutunlari icerik turune gore basliklara ayirir.

17 sutunluk bir tabloda hangi sutunun ne ise yaradigi ilk bakista anlasilmaz.
Bu modul her sutunu icerigine bakarak bir gruba atar; arayuz bunlari sutun
basliklarinin uzerinde ikinci bir baslik satiri olarak gosterir.
"""

from __future__ import annotations

import re
from typing import Any

# ⚠ Bu degerler ANAHTARDIR, etiket degil (Faz 9.2). Once `G_ID = "Kimlik"`
# yaziyordu: aynı dize hem tanimlayici hem ekranda gorunen metindi ve kopruden
# gecerken JS tarafinda **dize esitligiyle** karsilastiriliyordu. Etiketi
# cevirmek eslesmeyi koparirdi. Gorunen metin artik `i18n.t("group.<anahtar>")`.
G_ID = "id"
G_CAT = "cat"
G_NUM = "num"
G_FLAG = "flag"
G_NEST = "nest"
G_TEXT = "text"
G_OTHER = "other"

# Arayuzde gruplarin gosterim sirasi. Sira ayni zamanda RENK indeksidir
# (`gcell g-0…g-6`), yani degistirmek renkleri de kaydirir.
GROUP_ORDER = [G_ID, G_CAT, G_NUM, G_FLAG, G_NEST, G_TEXT, G_OTHER]

# Kimlik sayilabilmesi icin anahtar adinin bitisi veya tam esleme.
_ID_EXACT = {"id", "_key", "key", "uuid", "guid", "slug", "code"}
_ID_SUFFIX = ("id", "key", "name", "kod")

# Bu uzunlugun ustundeki ortalama metin "Metin" grubuna girer.
LONG_TEXT_AVG = 80

# Kimlik sayilmak icin gereken benzersizlik orani. Tam benzersizlik sart
# degildir: olculen bir kayit tablosunda ad sutunu 8 satirda 7 farkli deger
# tasiyordu ama yine de satirin birincil etiketiydi.
ID_UNIQUE_RATIO = 0.8

# Kategorik sayilmak icin benzersiz deger sayisi bu esigin altinda kalmali.
CAT_MIN_DISTINCT = 4
CAT_RATIO = 0.6

# Adi bu kelimelerden birini iceren sutunlar kategorik olmaya yatkindir.
# Kelime bazinda eslesir (bkz. `_words`) — "multiplier" icindeki "tip" saymaz.
_CAT_WORDS = {
    "type", "kind", "category", "status", "state", "scope", "class", "group",
    "stage", "phase", "activation", "severity", "priority",
    "tur", "tür", "tip", "kategori", "durum", "kapsam", "grup", "sinif",
    "sınıf", "asama", "aşama", "oncelik", "öncelik",
}


def _words(key: str) -> list[str]:
    """camelCase / snake_case anahtarini kelimelere ayirir."""
    spaced = re.sub(r"[_\-\s]+", " ", key)
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return [p.lower() for p in spaced.split() if p]


def _is_identity_name(key: str) -> bool:
    low = key.lower().lstrip("_")
    return low in _ID_EXACT or low.endswith(_ID_SUFFIX)


def _is_category_name(key: str) -> bool:
    return any(w in _CAT_WORDS for w in _words(key))


def classify(col: dict, values: list[Any], row_count: int) -> str:
    """Tek bir sutunu bir gruba atar.

    `col` flatten._column ciktisi, `values` sutunun dolu ham degerleri.
    """
    if col["kind"] in ("records", "object", "list"):
        return G_NEST

    dtype = col["dtype"]
    if dtype == "bool":
        return G_FLAG
    if dtype in ("int", "float"):
        return G_NUM

    texts = [v for v in values if isinstance(v, str)]
    if not texts:
        return G_OTHER

    uniq = len(set(texts))
    if _is_identity_name(col["key"]) and uniq >= len(texts) * ID_UNIQUE_RATIO:
        return G_ID

    avg = sum(len(t) for t in texts) / len(texts)
    if avg > LONG_TEXT_AVG:
        return G_TEXT

    # Az sayida farkli deger tasiyan kisa metinler kategorik kabul edilir
    # (enum benzeri alanlar: durum, tur, kapsam vb.).
    if uniq <= max(CAT_MIN_DISTINCT, row_count * CAT_RATIO):
        return G_CAT

    # Kardinalite tek basina yetmez: az satirli tabloda "Category" (6 benzersiz)
    # ile "Author" (7 benzersiz) istatistiksel olarak ayirt edilemez. Esigi
    # gevsetmek ikisini de kategorik yapardi. Kimlik tespitinde oldugu gibi
    # SUTUN ADI ikinci sinyal olarak kullanilir: adi kategorik ve en az bir
    # deger tekrar ediyorsa kategoriktir.
    if _is_category_name(col["key"]) and uniq < len(texts):
        return G_CAT

    return G_OTHER


def group_sort_key(group: str) -> int:
    try:
        return GROUP_ORDER.index(group)
    except ValueError:
        return len(GROUP_ORDER)


def ordered_keys(columns: list[dict]) -> list[str]:
    """Sutun anahtarlarini grup sirasina gore dizer (grup ici sira korunur)."""
    return [
        c["key"]
        for c in sorted(columns, key=lambda c: (group_sort_key(c.get("group", G_OTHER)),))
    ]
