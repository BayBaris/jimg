"""Veri kumesi kesfi.

Bir JSON belgesi genellikle tek bir tablo degildir; icinde farkli sekillerde
tabloya donusebilen birden fazla dugum barindirir. Bu modul belgeyi gezer ve
tabloya uygun her dugumu bir `Dataset` olarak isaretler (`[D-01]`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import i18n as I18N

# --- Veri kumesi turleri ---------------------------------------------------

RECORDS = "records"    # nesne dizisi           -> tam tablo (sutunlar = anahtarlarin birlesimi)
KEYVALUE = "keyvalue"  # skaler agirlikli nesne -> Anahtar | Deger tablosu
KEYLIST = "keylist"    # nesne -> liste haritasi -> Anahtar | Adet | Ogeler tablosu
KEYED = "keyed"        # nesne -> nesne haritasi, DIS anahtarlar satir olur
PIVOT = "pivot"        # nesne -> nesne haritasi, DIS anahtarlar sutun olur

# Arayuzde ve metin ciktisinda gorunen adlar artik `i18n`'dedir (Faz 9.2):
# tur kodu ANAHTARDIR (`records`), etiketi dile gore cozulur.

# Bir nesnenin kendi basina "Anahtar-Deger" tablosu sayilmasi icin gereken
# en az skaler alan sayisi. Altinda kalanlar tablo olarak degersizdir; yalnizca
# icine inilip cocuklari aranir (ornek: kok dugum, engineRequirements).
MIN_KEYVALUE_FIELDS = 2

# Pivot sayilmak icin alt nesnelerin anahtar kumelerinin ortusme esigi.
PIVOT_OVERLAP = 0.5


@dataclass
class Variant:
    """Ayni alan kumesini paylasan satir grubu.

    Nesne dizilerinde her satir ayni alanlara sahip olmayabilir; bu durumda
    tabloda cogu bos kalan seyrek sutunlar olusur. Varyantlar bu satirlari
    kendi tam dolu tablolarina ayirir.
    """

    id: str            # "<dataset id>#v0"
    label: str         # "<ayirt edici sutun> = <deger>" veya "Varyant 2"
    rows: list[int]    # kaynak dizideki satir indeksleri
    keys: list[str]    # bu varyantta bulunan alanlar
    # Ayirt edici sutunun ADI. `label` degeri de icerdigi icin sema ciktisinda
    # (schema.py) etiket degil bu alan kullanilir — deger disari sizmasin.
    discriminator: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        return len(self.keys)


@dataclass
class Dataset:
    """Tabloya donusebilen tek bir dugum."""

    id: str                       # nokta ile ayrilmis yol, ornek "parent.child"
    path: list[str | int]         # kok'ten dugume giden yol
    label: str                    # arayuzde gorunen ad
    kind: str                     # RECORDS | KEYVALUE | KEYLIST | PIVOT
    row_count: int
    col_count: int
    # ⚠ Notlar METIN DEGIL, (anahtar, parametre) ciftidir. Kesif belge acilirken
    # BIR KEZ calisir; metni orada pisirseydik dil degisince notlar eski dilde
    # kalirdi — tablo yeniden kurulsa bile, cunku `Dataset` yeniden uretilmiyor.
    # Cozum `kind_label` ile ayni: sakla anahtari, coz okuma aninda.
    notes: list[tuple[str, dict]] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)

    @property
    def kind_label(self) -> str:
        """Tur kodunun GECERLI DILDEKI adi. Kod (`self.kind`) degismez."""
        return I18N.t(f"kind.{self.kind}")

    @property
    def label_text(self) -> str:
        """Gorunen ad. Bos `label` kok dugumdur ve adi dile baglidir."""
        return self.label or I18N.t("ds.root")

    @property
    def note_texts(self) -> list[str]:
        """Notlarin GECERLI DILDEKI metinleri."""
        return [I18N.t(key, **params) for key, params in self.notes]


# --- Yardimcilar -----------------------------------------------------------

def is_scalar(x: Any) -> bool:
    """Tabloda tek hucreye sigan deger mi? (None dahil)"""
    return not isinstance(x, (dict, list))


def is_records(node: Any) -> bool:
    """Nesne dizisi mi? Tum ogeler dict olmali."""
    return isinstance(node, list) and len(node) > 0 and all(isinstance(x, dict) for x in node)


def is_scalar_list(node: Any) -> bool:
    return isinstance(node, list) and len(node) > 0 and all(is_scalar(x) for x in node)


def _dict_children(node: dict) -> dict[str, dict]:
    return {k: v for k, v in node.items() if isinstance(v, dict)}


def _dict_table_keys(children: dict[str, dict]) -> tuple[list[str], list[str]] | None:
    """Nesne->nesne haritasi tabloya uygun mu?

    Uygunsa (dis anahtarlar, ic anahtarlarin birlesimi) dondurur. Bu sekil
    gercek dunyada en yaygin JSON tablo bicimidir:
        {"U-0001": {...}, "U-0002": {...}}   -> kullanicilar
        {"tr": {...}, "en": {...}}           -> diller

    Ic degerlerin skaler olmasi SART DEGILDIR; liste ve nesne degerleri
    hucre olarak zaten uc modda gosterilir (bkz. flatten [D-03]).
    """
    if len(children) < 2:
        return None

    key_sets = [set(v.keys()) for v in children.values()]
    if any(not ks for ks in key_sets):
        return None

    union: set[str] = set().union(*key_sets)
    inter: set[str] = set.intersection(*key_sets)
    if not union or len(inter) / len(union) < PIVOT_OVERLAP:
        return None

    inner: list[str] = []
    seen: set[str] = set()
    for sub in children.values():
        for k in sub:
            if k not in seen:
                seen.add(k)
                inner.append(k)

    return list(children.keys()), inner


def _is_keylist(node: dict) -> bool:
    """Tum (veya neredeyse tum) degerleri skaler liste olan nesne."""
    if not node:
        return False
    listish = sum(1 for v in node.values() if is_scalar_list(v))
    return listish / len(node) >= 0.8


# --- Kesif -----------------------------------------------------------------

def discover(root: Any) -> list[Dataset]:
    """Belgeyi gezip tabloya uygun tum dugumleri bulur."""
    found: list[Dataset] = []
    _walk(root, [], found)
    return found


def _walk(node: Any, path: list[str | int], out: list[Dataset]) -> None:
    if is_records(node):
        out.append(_records_dataset(node, path))
        # Satir icindeki ic ice diziler ust duzey veri kumesi degildir;
        # hucre olarak islenir. Bu yuzden satirlarin icine inilmez.
        return

    if isinstance(node, dict):
        _walk_dict(node, path, out)
        return

    if isinstance(node, list):
        # Karisik veya ic ice dizi: ogelerin icine bakmaya devam et.
        for i, item in enumerate(node):
            if isinstance(item, (dict, list)):
                _walk(item, path + [i], out)


def _is_map(node: dict, children: dict[str, dict]) -> bool:
    """Dugum bir HARITA mi — alt nesneleri tek bir tablonun satir/sutunlari mi?

    ⚠ Anahtar ortusmesi (`_dict_table_keys`) tek basina yetmez (9.22): iki alt
    nesnenin anahtarlari TESADUFEN ortusebilir. Olculen ornek: kokunde uc skaler
    alan, ayni durum anahtarlarini tasiyan iki kucuk nesne (etiketler ve
    sayilar) ve iki buyuk kayit dizisi olan bir belge. Kok pivot sayiliyor, iki
    kayit dizisi hic taranmiyordu — belgenin asil verisi agacta yoktu. Harita,
    alt nesnelerin dugumun en az YARISI oldugu yerdir; geri kalani ust veridir
    (surum, ad) ve not olarak kalir.
    """
    return 2 * len(children) >= len(node)


def _walk_rest(node: dict, members: set[str], path: list[str | int],
               out: list[Dataset]) -> list[str]:
    """Tabloya GIRMEYEN kap alanlari (dizi, nesne) tarar; veri kumesine donusenleri dondurur.

    Harita ve anahtar-liste tablolari yalnizca kendi uyelerini gosterir. Kalan
    alanlar taranmazsa icindeki kayit dizileri SESSIZCE kaybolur (9.22).
    """
    promoted = []
    for k, v in node.items():
        if k not in members and isinstance(v, (dict, list)):
            before = len(out)
            _walk(v, path + [k], out)
            if len(out) > before:
                promoted.append(k)
    return promoted


def _walk_dict(node: dict, path: list[str | int], out: list[Dataset]) -> None:
    children = _dict_children(node)

    shape = _dict_table_keys(children) if _is_map(node, children) else None
    if shape:
        outer, inner = shape
        # Yon secimi: satir sayisi sutun sayisindan buyuk olacak sekilde.
        #   kimlik -> kayit sozlugu : 4 dis / 3 ic  -> dis anahtarlar SATIR  (Anahtarli tablo)
        #   dil -> metin sozlugu    : 2 dis / 14 ic -> dis anahtarlar SUTUN (Pivot)
        # Kullanici her iki durumda da Transpoze ile cevirebilir.
        if len(outer) >= len(inner):
            ds = _keyed_dataset(node, outer, inner, path)
        else:
            ds = _pivot_dataset(node, outer, path)
        out.append(ds)
        # Uye alt nesneler ayrica Anahtar-Deger tablosu yapilmaz; uye OLMAYAN
        # kaplar ise taranir.
        promoted = _walk_rest(node, set(outer), path, out)
        _note_rest(ds, node, set(outer), promoted)
        return

    if _is_keylist(node):
        ds = _keylist_dataset(node, path)
        out.append(ds)
        lists = {k for k, v in node.items() if is_scalar_list(v)}
        promoted = _walk_rest(node, lists, path, out)
        _note_rest(ds, node, lists, promoted)
        return

    ds: Dataset | None = None
    scalar_keys = [k for k, v in node.items() if is_scalar(v)]
    if len(scalar_keys) >= MIN_KEYVALUE_FIELDS:
        ds = _keyvalue_dataset(node, path)
        out.append(ds)

    # Skaler alanlari az olan dugumler (kok, engineRequirements) tablo olarak
    # emit edilmez ama cocuklari yine de taranir.
    promoted: list[str] = []   # kendi veri kumesine donusen alanlar
    inline: list[str] = []     # yalnizca hucre icinde gorunecek alanlar
    for k, v in node.items():
        if isinstance(v, (dict, list)):
            before = len(out)
            _walk(v, path + [k], out)
            (promoted if len(out) > before else inline).append(k)

    if ds is not None:
        if promoted:
            ds.notes.append(("ds.note_promoted", {"list": ", ".join(promoted)}))
        if inline:
            ds.notes.append(("ds.note_inline", {"list": ", ".join(inline)}))


def _note_rest(ds: Dataset, node: dict, members: set[str], promoted: list[str]) -> None:
    """Tabloya girmeyen alanlarin notu: kendi veri kumesine donusenler ayri, kalanlar ayri.

    Once tek bir "dahil edilmeyen alan" notu vardi ve kendi tablosu olan bir
    kayit dizisini de "dahil edilmedi" diye yaziyordu — kullanici veriyi kayip
    sanardi.
    """
    if promoted:
        ds.notes.append(("ds.note_promoted", {"list": ", ".join(promoted)}))
    skipped = [k for k in node if k not in members and k not in promoted]
    if skipped:
        ds.notes.append(("ds.note_skipped", {"list": ", ".join(skipped)}))


# --- Dataset kuruculari ----------------------------------------------------

def path_id(path: list[str | int]) -> str:
    if not path:
        return "$"
    parts: list[str] = []
    for p in path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            parts.append(("." if parts else "") + p)
    return "".join(parts)


def _label(path: list[str | int]) -> str:
    """Dugumun ham adi. Kok icin BOS doner — gorunen metin `label_text`te."""
    if not path:
        return ""
    return str(path[-1])


def _records_dataset(node: list[dict], path: list[str | int]) -> Dataset:
    keys: list[str] = []
    seen: set[str] = set()
    for row in node:
        for k in row:
            if k not in seen:
                seen.add(k)
                keys.append(k)

    ds_id = path_id(path)
    # Seyreklik ve varyant AYRI NOT OLARAK yazilmaz: seyreklik arayuzde
    # "otomatik gizlendi" bildirimiyle, varyant ise kendi kutusuyla ve rapordaki
    # kendi bolumuyle zaten anlatiliyor. Iki kez soylenince not alani sisiyordu.
    notes: list[tuple[str, dict]] = []
    variants = detect_variants(node, keys, ds_id)

    return Dataset(
        id=ds_id, path=list(path), label=_label(path), kind=RECORDS,
        row_count=len(node), col_count=len(keys), notes=notes, variants=variants,
    )


def detect_variants(node: list[dict], keys: list[str], ds_id: str) -> list[Variant]:
    """Satirlari alan kumelerine gore gruplar.

    Yalnizca anlamli bolunmelerde varyant uretilir: en az 2, en fazla satir
    sayisinin yarisi kadar grup olmali. Aksi halde her satir kendi varyanti
    olur ve bolme bilgi tasimaz.
    """
    groups: dict[tuple[str, ...], list[int]] = {}
    for i, row in enumerate(node):
        sig = tuple(k for k in keys if k in row)
        groups.setdefault(sig, []).append(i)

    if len(groups) < 2 or len(groups) > max(2, len(node) // 2):
        return []

    disc = _find_discriminator(node, list(groups.values()))
    variants: list[Variant] = []
    for gi, (sig, idxs) in enumerate(groups.items()):
        if disc is not None:
            label = f"{disc} = {node[idxs[0]][disc]}"
        else:
            label = I18N.t("variant.generic", n=gi + 1, fields=len(sig))
        variants.append(Variant(id=f"{ds_id}#v{gi}", label=label, rows=idxs,
                                keys=list(sig), discriminator=disc))
    return variants


def _find_discriminator(node: list[dict], groups: list[list[int]]) -> str | None:
    """Varyant bolunmesiyle birebir ortusen bir sutun var mi?

    Cogu belgede eksik alanlar rastgele degildir: bir tur/durum sutununun
    degeri hangi alanlarin bulunacagini belirler. Boyle bir sutun varsa
    varyant basligi teknik "Varyant 1" yerine anlamli olur.
    """
    if not node:
        return None

    common = [k for k in node[0] if all(k in r and is_scalar(r[k]) for r in node)]
    owner = {i: gi for gi, idxs in enumerate(groups) for i in idxs}

    for k in common:
        by_val: dict[Any, list[int]] = {}
        try:
            for i, r in enumerate(node):
                by_val.setdefault(r[k], []).append(i)
        except TypeError:       # hashlanamayan deger
            continue
        if len(by_val) != len(groups):
            continue
        if all(len({owner[i] for i in idxs}) == 1 for idxs in by_val.values()):
            return k
    return None


def _keyvalue_dataset(node: dict, path: list[str | int]) -> Dataset:
    # Notlar cagiran tarafta doldurulur: hangi ic ice alanin ayri bir veri
    # kumesine donustugu ancak cocuklar tarandiktan sonra bilinir.
    return Dataset(
        id=path_id(path), path=list(path), label=_label(path), kind=KEYVALUE,
        row_count=len(node), col_count=2,
    )


def _keylist_dataset(node: dict, path: list[str | int]) -> Dataset:
    return Dataset(
        id=path_id(path), path=list(path), label=_label(path), kind=KEYLIST,
        row_count=len(node), col_count=3,
    )


def _keyed_dataset(node: dict, outer: list[str], inner: list[str],
                   path: list[str | int]) -> Dataset:
    """Dis anahtarlarin satir oldugu tablo (kimlik -> kayit sozlugu sekli)."""
    ds_id = path_id(path)
    rows_src = [node[k] for k in outer]

    notes: list[tuple[str, dict]] = []
    variants = detect_variants(rows_src, inner, ds_id)

    return Dataset(
        id=ds_id, path=list(path), label=_label(path), kind=KEYED,
        row_count=len(outer), col_count=len(inner) + 1, notes=notes, variants=variants,
    )


def _pivot_dataset(node: dict, cols: list[str], path: list[str | int]) -> Dataset:
    rows: list[str] = []
    seen: set[str] = set()
    for c in cols:
        for k in node[c]:
            if k not in seen:
                seen.add(k)
                rows.append(k)

    # Tabloya girmeyen alanlarin notu cagiranda (`_note_rest`): hangisinin
    # kendi veri kumesine donustugu ancak onlar tarandiktan sonra bilinir.
    notes: list[tuple[str, dict]] = []
    missing = [c for c in cols if len(node[c]) < len(rows)]
    if missing:
        notes.append(("ds.note_missing", {"list": ", ".join(missing)}))

    return Dataset(
        id=path_id(path), path=list(path), label=_label(path), kind=PIVOT,
        row_count=len(rows), col_count=len(cols) + 1, notes=notes,
    )


def resolve(root: Any, path: list[str | int]) -> Any:
    """Yol boyunca ilerleyip dugumu dondurur."""
    node = root
    for p in path:
        node = node[p]
    return node
