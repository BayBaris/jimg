"""Tablo hucresinin JSON'daki yeri (Faz 10.1). Saf: G/C yok.

Bir hucre ya bir DEGERE (skaler) ya da bir ANAHTARA (dis anahtar sutunu:
yeniden adlandirma) karsilik gelir; ikisi de degilse duzenlenemezlik nedeni
doner. Adres transpozesiz tablonun indeksleridir (`ri`, `ci`).

⚠ Satir ve sutun sirasi tablo kurucularinin kullandigi yardimcilardan okunur
(`flatten.record_keys`, `table_rows`, `pivot_cols`). Sira burada ayrica
hesaplansaydi iki yer sessizce ayrisir ve duzenleme BASKA bir hucreye
yazardi. Kapi: `check.py --> check_edit_map` her adresi geri cozer.
"""

from __future__ import annotations

from typing import Any

from . import discover as D
from . import flatten as F
from . import images as IM

VALUE, KEY = "value", "key"
# 10.7 — pivot ic anahtari: tum pivot sutunlarinda BIRLIKTE yeniden adlandirilir.
# Yol `ds.path + [ic_anahtar]` bicimindedir (gercek bir JSON yolu degil);
# anahtar yollari `pivot_key_paths` ile acilir.
SHARED = "shared"

# Duzenlenemezlik nedenleri. Arayuz ipucunu `edit.why_<neden>`den kurar (10.5).
WHY_LIST = "list"          # skaler liste — oge ekleme/cikarma v1'de yok
WHY_NESTED = "nested"      # nesne ya da nesne dizisi — alt tablo
WHY_MISSING = "missing"    # alan bu satirda yok — eklemek yapisal degisiklik
WHY_IMAGE = "image"        # gorsel yolu ya da gomulu gorsel
WHY_DERIVED = "derived"    # turetilmis sutun (anahtar-liste `_count`)
WHY_SYNTHETIC = "synthetic"  # 10.7 — sutun adini uygulama uretiyor (Anahtar, Deger...)
# Esleme ile tablonun boyutu ayristi: bir HATADIR, kapi bunu basarisizlik sayar.
# Kendi adi var ki mesru bir nedenin (ornegin `derived`) arkasina saklanmasin —
# ilk yazimda boyle oldu ve uc belgenin tum hucreleri "turetilmis" gorundu.
WHY_UNMAPPED = "unmapped"

Loc = tuple[list, str]

# Anahtar sutununun yer tutucusu: gercek bir alan `_key` adini tasiyabilir,
# bu yuzden sutunlar ADLA degil konumla ayrilir.
_KEY_COL = None


def _grid(root: Any, ds: D.Dataset, variant_id: str | None) -> tuple[Any, list, list]:
    """(dugum, satir konumlari, sutun anahtarlari) — tablo kurucusuyla ayni sira."""
    node = D.resolve(root, ds.path)
    variant = next((v for v in ds.variants if v.id == variant_id), None)
    only_rows = variant.rows if variant else None
    only_keys = list(variant.keys) if variant else None

    if ds.kind == D.RECORDS:
        rows = F.table_rows(node, only_rows)
        cols = only_keys if only_keys is not None else F.record_keys([node[i] for i in rows])
    elif ds.kind == D.KEYED:
        rows = F.table_rows(node, only_rows)
        inner = only_keys if only_keys is not None else F.record_keys([node[k] for k in rows])
        cols = [_KEY_COL] + inner
    elif ds.kind == D.PIVOT:
        pcols = F.pivot_cols(node)
        rows = F.record_keys([node[c] for c in pcols])
        cols = [_KEY_COL] + pcols
    elif ds.kind == D.KEYLIST:   # Anahtar · Adet · Ogeler
        rows = list(node.keys())
        cols = [_KEY_COL, 1, 2]
    else:                        # KEYVALUE: Anahtar · Deger
        rows = list(node.keys())
        cols = [_KEY_COL, 1]
    return node, rows, cols


def _value(container: dict | list, key: Any, path: list) -> Loc | str:
    if isinstance(container, dict) and key not in container:
        return WHY_MISSING
    v = container[key]
    if isinstance(v, dict) or (isinstance(v, list) and v and not all(D.is_scalar(x) for x in v)):
        return WHY_NESTED
    if isinstance(v, list):
        return WHY_LIST
    if isinstance(v, str) and IM.detect(v) is not None:
        return WHY_IMAGE
    return path + [key], VALUE


def _locate(node: Any, ds: D.Dataset, rows: list, cols: list, ri: int, ci: int) -> Loc | str:
    r, c = rows[ri], cols[ci]
    base = list(ds.path)
    if ds.kind == D.RECORDS:
        return _value(node[r], c, base + [r])
    if ds.kind == D.PIVOT:
        # Satir ic anahtar, sutun dis anahtar: deger `node[sutun][satir]`.
        # Anahtar sutunu ic anahtardir ve birden cok nesnede gecer (10.7).
        return (base + [r], SHARED) if c is _KEY_COL else _value(node[c], r, base + [c])
    if c is _KEY_COL:
        return base + [r], KEY
    if ds.kind == D.KEYED:
        return _value(node[r], c, base + [r])
    if ds.kind == D.KEYLIST:
        return WHY_DERIVED if ci == 1 else WHY_LIST
    return _value(node, r, base)   # KEYVALUE `_value`


def _value_path(ds: D.Dataset, rows: list, cols: list, ri: int, ci: int) -> list | None:
    """Hucredeki DEGERIN yolu — duzenlenebilir olsun olmasin. Anahtar ve
    turetilmis sutunlarda deger yok: None. `_locate` ile ayni konum kurallari."""
    r, c = rows[ri], cols[ci]
    base = list(ds.path)
    if c is _KEY_COL:
        return None
    if ds.kind in (D.RECORDS, D.KEYED):
        return base + [r, c]
    if ds.kind == D.PIVOT:
        return base + [c, r]
    if ds.kind == D.KEYVALUE:
        return base + [r]
    return None                      # KEYLIST: adet ve ogeler


def locate(root: Any, ds: D.Dataset, variant_id: str | None, ri: int, ci: int) -> Loc | str:
    """Hucrenin yeri: `(yol, "value" | "key")` ya da duzenlenemezlik nedeni.

    Anahtar hedefinde yol ANAHTARIN kendisini gosterir; ust nesne `yol[:-1]`.
    Gecersiz indeks `IndexError` firlatir — cagiran tabloyla eslesmeyen bir
    adres gondermistir.
    """
    node, rows, cols = _grid(root, ds, variant_id)
    return _locate(node, ds, rows, cols, ri, ci)


def pivot_key_paths(root: Any, ds: D.Dataset, inner: str) -> list[list]:
    """Pivot ic anahtarinin gectigi her pivot sutunundaki anahtar yolu (10.7)."""
    node = D.resolve(root, ds.path)
    return [list(ds.path) + [c, inner] for c in F.pivot_cols(node) if inner in node[c]]


def column_paths(root: Any, ds: D.Dataset, variant_id: str | None,
                 ci: int) -> tuple[list[list], str] | str:
    """Sutun adinin belgede gectigi her anahtar yolu + eski ad; ya da neden (10.7).

    K-31: ad veri kumesinin TUM satirlarinda degisir — varyant yalnizca
    gorunumdur, alani tasiyan her satir birlikte yeniden adlandirilir.
    Uygulamanin urettigi sutunlar (`_key`, `_value`, `_count`, `_items`)
    belgede bir ad degil: `synthetic`.
    """
    node, rows, cols = _grid(root, ds, variant_id)
    c = cols[ci]
    if c is _KEY_COL or ds.kind in (D.KEYVALUE, D.KEYLIST):
        return WHY_SYNTHETIC
    base = list(ds.path)
    if ds.kind == D.PIVOT:
        return [base + [c]], c                   # pivot sutunu tek dis anahtar
    if ds.kind == D.RECORDS:
        paths = [base + [i, c] for i, row in enumerate(node) if isinstance(row, dict) and c in row]
    else:                                        # KEYED
        paths = [base + [k, c] for k, row in node.items() if isinstance(row, dict) and c in row]
    return paths, c


def cell_at(root: Any, ds: D.Dataset, variant_id: str | None,
            path: list, target: str) -> tuple[int, int] | None:
    """`locate`in TERSI: yol hangi hucrede gorunuyor (10.5.2, degisen hucre isareti).

    Yol bu veri kumesine (ya da bu varyantin satirina) dusmuyorsa None.
    """
    if list(path[:len(ds.path)]) != list(ds.path):
        return None
    rest = list(path[len(ds.path):])
    if not rest:
        return None
    node, rows, cols = _grid(root, ds, variant_id)
    try:
        if target == SHARED:                 # pivot ic anahtari: anahtar sutunu
            return (rows.index(rest[0]), 0) if ds.kind == D.PIVOT and len(rest) == 1 else None
        if ds.kind == D.PIVOT:
            if target == KEY or len(rest) != 2:
                return None
            return rows.index(rest[1]), cols.index(rest[0])
        if target == KEY:
            return rows.index(rest[0]), 0
        if ds.kind == D.RECORDS:
            return (rows.index(rest[0]), cols.index(rest[1])) if len(rest) == 2 else None
        if ds.kind == D.KEYED:
            return (rows.index(rest[0]), cols.index(rest[1])) if len(rest) == 2 else None
        if ds.kind == D.KEYVALUE:
            return (rows.index(rest[0]), 1) if len(rest) == 1 else None
    except ValueError:
        return None
    return None


def attach_edit(table: dict, root: Any, ds: D.Dataset, variant_id: str | None) -> None:
    """Duzenlenemeyen ust duzey hucreye `x: <neden>` yazar (transpozeden ONCE).

    Duzenlenebilir hucre isaretsizdir: arayuz adresi hucrenin konumundan
    bilir, her hucreye adres yazmak buyuk belgede yuku sisirirdi.
    """
    node, rows, cols = _grid(root, ds, variant_id)
    if len(rows) != len(table["rows"]) or len(cols) != len(table["columns"]):
        # Tablo ile eslemenin boyutu ayrisirsa hicbir hucre duzenlenebilir
        # sayilmaz — yanlis hucreye yazmaktansa hic yazmamak.
        for row in table["rows"]:
            for cell in row:
                cell["x"] = WHY_UNMAPPED
        return
    for ri, row in enumerate(table["rows"]):
        for ci, cell in enumerate(row):
            loc = _locate(node, ds, rows, cols, ri, ci)
            if isinstance(loc, str):
                cell["x"] = loc
            if cell.get("remote"):
                # `K-32` (9.15) — uzak gorselin belgedeki yolu: arayuz onizlemeyi
                # bu yolla galeri kopru metodundan ister. Dizge `images.scan`in
                # urettigiyle AYNI olmali, yoksa onizleme sessizce gelmez.
                path = _value_path(ds, rows, cols, ri, ci)
                if path is not None:
                    cell["jp"] = IM._path_str(path)
