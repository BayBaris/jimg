"""Veri kumesi -> sutun + satir tablosu.

Hucreler uc modda uretilir (`[D-03]`):
  a) skaler      -> dogrudan gosterilir
  b) skaler dizi -> " . " ile birlestirilip tek hucrede gosterilir
  c) nesne dizisi / nesne -> ozet rozet + genisletilince alt tablo

Boylece nesne dizisi tasiyan alanlar `alan[0].x` seklinde indekslenip
sutun patlamasina yol acmaz.
"""

from __future__ import annotations

from typing import Any

from . import columns as COL
from . import discover as D
from . import i18n as I18N
from . import images as IM

# --- Hucre turleri ---------------------------------------------------------

C_SCALAR = "scalar"
C_LIST = "list"        # skaler dizi
C_RECORDS = "records"  # nesne dizisi -> alt tablo
C_OBJECT = "object"    # nesne        -> alt tablo
C_IMAGE = "image"      # gorsel tasiyan deger -> onizleme
C_MISSING = "missing"  # anahtar bu satirda hic yok

LIST_SEP = " · "
LIST_MAX_CHARS = 180
EMPTY_DISPLAY = "—"

# --- Uzun metin sutunlari --------------------------------------------------
# Uzun metin GRUBA gore degil, ICERIGE gore belirlenir: "Metin" grubuna
# girmeyen bir siniflandirma ya da kimlik sutunu da uzun olabiliyor.
# Bir hucre tek satira sigmiyorsa sutun sarilir (`wrap`); en uzun hucresi
# TEXT_MAX_LINES satiri asiyorsa sutun varsayilan olarak gizlenir
# (bkz. api_table.TableMixin._long_text_columns).
TEXT_COL_W = 420       # sarilan sutunun genisligi (px) — dar sutunda satir sayisi patlar
WRAP_CHARS = 52        # TEXT_COL_W genisliginde bir satira sigan karakter (olculdu)
TEXT_MAX_LINES = 3     # bunu asan sutun gizlenir
LONG_TEXT_CHARS = WRAP_CHARS * TEXT_MAX_LINES


# --- Deger bicimlendirme ---------------------------------------------------

def display_scalar(v: Any) -> str:
    if v is None:
        return EMPTY_DISPLAY
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, float):
        # 2.0 -> "2.0", 0.90 -> "0.9"
        return repr(v)
    return str(v)


def _truncate(s: str, limit: int = LIST_MAX_CHARS) -> str:
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def make_cell(v: Any) -> dict:
    """Tek bir degeri hucreye cevirir."""
    if isinstance(v, dict):
        return {
            "k": C_OBJECT,
            "d": I18N.t("cell.fields", n=len(v)) if v else EMPTY_DISPLAY,
            "n": len(v),
            "sub": keyvalue_table(v),
        }

    if isinstance(v, list):
        if not v:
            return {"k": C_LIST, "d": EMPTY_DISPLAY, "n": 0}
        if D.is_records(v):
            return {
                "k": C_RECORDS,
                "d": I18N.t("cell.items", n=len(v)),
                "n": len(v),
                "sub": records_table(v),
            }
        if all(D.is_scalar(x) for x in v):
            joined = LIST_SEP.join(display_scalar(x) for x in v)
            cell = {"k": C_LIST, "d": _truncate(joined), "n": len(v)}
            if len(joined) > LIST_MAX_CHARS:
                # Uzun metin paragraflarindan olusan listeler tek satira sigmaz;
                # kisaltilmis metnin yaninda tam icerik alt tabloda korunur.
                cell["sub"] = {
                    "columns": [{"key": "_item", "label": I18N.t("col.item"),
                                 "kind": C_SCALAR, "dtype": "str",
                                 "present": len(v), "total": len(v), "sparse": False, "numeric": False}],
                    "rows": [[{"k": C_SCALAR, "d": display_scalar(x)}] for x in v],
                }
            return cell
        # Karisik dizi: her ogeyi tek satirlik kayda sar
        wrapped = [x if isinstance(x, dict) else {"value": x} for x in v]
        return {"k": C_RECORDS, "d": I18N.t("cell.items", n=len(v)), "n": len(v),
                "sub": records_table(wrapped)}

    cell = {"k": C_SCALAR, "d": display_scalar(v)}
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        cell["v"] = v          # siralama ve grafik icin ham sayisal deger
    return cell


# --- Sutun tipi cikarimi ---------------------------------------------------

def _value_dtype(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    return "object"


def _merge_dtypes(seen: set[str]) -> str:
    seen = {s for s in seen if s != "null"}
    if not seen:
        return "null"
    if len(seen) == 1:
        return next(iter(seen))
    if seen == {"int", "float"}:
        return "float"
    return "mixed"


# Bir sutunda birden fazla hucre modu gorulurse en belirgin olani kazanir.
# Ornek: bir liste sutunu bazi satirlarda bos dizi (list), bazilarinda nesne dizisi
# (records) olur; sutun records sayilmalidir, aksi halde genisletme dugmesi kaybolur.
_KIND_RANK = {C_MISSING: 0, C_SCALAR: 1, C_LIST: 2, C_OBJECT: 3, C_RECORDS: 4, C_IMAGE: 5}


def _column(key: str, values: list[Any], present: int, total: int) -> dict:
    dtypes = {_value_dtype(v) for v in values}
    dtype = _merge_dtypes(dtypes)
    kinds = {make_cell(v)["k"] for v in values} if values else {C_SCALAR}
    kind = max(kinds, key=lambda k: _KIND_RANK.get(k, 0))
    col = {
        "key": key,
        "label": key,
        "kind": kind,
        "dtype": dtype,
        "present": present,
        "total": total,
        "sparse": present < total,
        "numeric": dtype in ("int", "float"),
    }
    col["group"] = COL.classify(col, values, total or 1)
    return col


# --- Tablo kuruculari ------------------------------------------------------
#
# ⚠ Satir ve sutun SIRASI asagidaki iki yardimcidan okunur ve `edit_map`
# (Faz 10) ayni yardimcilari cagirir: sira iki yerde ayri hesaplanirsa
# duzenleme sessizce BASKA bir hucreye yazar. Kapi: `check_edit_map`.

def record_keys(rows: list[dict]) -> list[str]:
    """Kayitlardaki alanlarin ilk goruldugu sirayla birlesimi."""
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    return keys


def pivot_cols(node: dict) -> list[str]:
    """Pivot tablosunun sutunlari: nesne olan dis anahtarlar (`discover` sekli)."""
    shape = D._dict_table_keys({k: v for k, v in node.items() if isinstance(v, dict)})
    return shape[0] if shape else []


def table_rows(node: Any, only_rows: list[int] | None = None) -> list:
    """Satirlarin kaynak konumlari: kayit dizisinde indeks, nesnede dis anahtar."""
    if isinstance(node, list):
        return list(only_rows) if only_rows is not None else list(range(len(node)))
    outer = list(node.keys())
    return [outer[i] for i in only_rows] if only_rows is not None else outer


def records_table(node: list[dict], only_rows: list[int] | None = None,
                  only_keys: list[str] | None = None) -> dict:
    """Nesne dizisini tabloya cevirir.

    `only_rows` / `only_keys` verilirse yalnizca o satirlar ve alanlar alinir;
    sema varyanti tablolari bu sekilde uretilir (bkz. discover.Variant).
    """
    src = [node[i] for i in only_rows] if only_rows is not None else node
    keys = list(only_keys) if only_keys is not None else record_keys(src)

    columns = []
    for k in keys:
        present_vals = [r[k] for r in src if k in r]
        columns.append(_column(k, present_vals, len(present_vals), len(src)))

    rows = []
    for r in src:
        rows.append([make_cell(r[k]) if k in r else {"k": C_MISSING, "d": ""} for k in keys])

    return {"columns": columns, "rows": rows}


def keyvalue_table(node: dict) -> dict:
    columns = [_plain_column("_key", I18N.t("col.key"), group=COL.G_ID,
                             present=len(node), total=len(node))]
    values = list(node.values())
    val_col = _column("_value", values, len(values), len(values))
    val_col["label"] = I18N.t("col.value")
    val_col["synthetic"] = True
    columns.append(val_col)

    rows = [[{"k": C_SCALAR, "d": str(k)}, make_cell(v)] for k, v in node.items()]
    return {"columns": columns, "rows": rows}


def keylist_table(node: dict) -> dict:
    n = len(node)
    columns = [
        _plain_column("_key", I18N.t("col.key"), group=COL.G_ID, present=n, total=n),
        _plain_column("_count", I18N.t("col.count"), group=COL.G_NUM, dtype="int",
                      numeric=True, present=n, total=n),
        _plain_column("_items", I18N.t("col.items"), group=COL.G_NEST, kind=C_LIST,
                      dtype="list", present=n, total=n),
    ]
    rows = []
    for k, v in node.items():
        items = v if isinstance(v, list) else [v]
        rows.append([
            {"k": C_SCALAR, "d": str(k)},
            {"k": C_SCALAR, "d": str(len(items)), "v": len(items)},
            make_cell(items),
        ])
    return {"columns": columns, "rows": rows}


def keyed_table(node: dict, only_rows: list[int] | None = None,
                only_keys: list[str] | None = None) -> dict:
    """Dis anahtarlarin satir oldugu tablo.

    {"U-0001": {...}, "U-0002": {...}} -> Anahtar | alan1 | alan2 ...
    Bkz. discover.KEYED.
    """
    outer = table_rows(node, only_rows)
    inner = list(only_keys) if only_keys is not None else record_keys([node[k] for k in outer])

    columns = [_plain_column("_key", I18N.t("col.key"), group=COL.G_ID,
                             present=len(outer), total=len(outer))]
    for ik in inner:
        vals = [node[k][ik] for k in outer if ik in node[k]]
        columns.append(_column(ik, vals, len(vals), len(outer)))

    rows = []
    for k in outer:
        row: list[dict] = [{"k": C_SCALAR, "d": str(k)}]
        for ik in inner:
            row.append(make_cell(node[k][ik]) if ik in node[k] else {"k": C_MISSING, "d": ""})
        rows.append(row)

    return {"columns": columns, "rows": rows}


def pivot_table(node: dict, cols: list[str]) -> dict:
    """Alt nesneleri sutun olarak yan yana getirir (`[D-04]`)."""
    row_keys = record_keys([node[c] for c in cols])

    columns = [_plain_column("_key", I18N.t("col.key"), group=COL.G_ID,
                             present=len(row_keys), total=len(row_keys))]
    for c in cols:
        present_vals = [node[c][k] for k in row_keys if k in node[c]]
        col = _column(c, present_vals, len(present_vals), len(row_keys))
        columns.append(col)

    rows = []
    for k in row_keys:
        row = [{"k": C_SCALAR, "d": str(k)}]
        for c in cols:
            row.append(make_cell(node[c][k]) if k in node[c] else {"k": C_MISSING, "d": ""})
        rows.append(row)

    return {"columns": columns, "rows": rows}


# Uygulamanin urettigi sutunlar: adlari belgede degil, sozlukte (10.7).
SYNTHETIC_KEYS = ("_key", "_value", "_count", "_items")


def _plain_column(key: str, label: str, **extra: Any) -> dict:
    # `synthetic`: adi belgenin bir ALAN ADI degil — sozlukten (Anahtar, Deger) ya
    # da transpozede satir kimliginden gelir (9.26). Agent semasi bunu
    # ayrica bildirir; yoksa model "Anahtar/Deger"i belgenin alan adi sanar.
    col = {
        "key": key, "label": label, "kind": C_SCALAR, "dtype": "str",
        "present": 0, "total": 0, "sparse": False, "numeric": False,
        "group": COL.G_OTHER, "synthetic": True,
    }
    col.update(extra)
    return col


def transpose_table(table: dict) -> dict:
    """Satirlarla sutunlari yer degistirir.

    Az satirli ama cok sutunlu tablolarda (ornek 7x17) alanlar asagi
    dogru okunur hale gelir. Basliklar kayit kimliginden turetilir.
    """
    cols, rows = table["columns"], table["rows"]

    # Baslik icin kimlik sutunu: once Kimlik grubundaki ilk sutun, yoksa ilki.
    head_i = next((i for i, c in enumerate(cols) if c.get("group") == COL.G_ID), 0)

    new_cols = [_plain_column("_field", I18N.t("col.field"), group=COL.G_ID)]
    for r_i, r in enumerate(rows):
        cell = r[head_i] if head_i < len(r) else None
        label = cell["d"] if cell and cell["k"] != C_MISSING and cell["d"] else f"#{r_i + 1}"
        new_cols.append(_plain_column(f"_r{r_i}", label, present=len(cols), total=len(cols)))

    new_rows = []
    for c_i, c in enumerate(cols):
        # Alan adini tasiyan ilk hucre, kaynak sutunun grubunu da tasir ki
        # arayuz transpoze modda grup ayraci cizebilsin.
        first = {"k": C_SCALAR, "d": c["label"], "g": c.get("group", COL.G_OTHER)}
        # 10.7.2 — bu hucre SUTUN ADIDIR ve duzenlenebilir; uygulamanin urettigi
        # sutunun adi belgede yok. Neden `edit_map.WHY_SYNTHETIC` ile ayni dize.
        if c["key"] in SYNTHETIC_KEYS:
            first["x"] = "synthetic"
        new_rows.append([first] + [r[c_i] if c_i < len(r) else {"k": C_MISSING, "d": ""} for r in rows])

    # Transpoze sutunun modu, icindeki en belirgin hucre moduna gore belirlenir.
    for j in range(1, len(new_cols)):
        kinds = {row[j]["k"] for row in new_rows} or {C_SCALAR}
        new_cols[j]["kind"] = max(kinds, key=lambda k: _KIND_RANK.get(k, 0))

    return {"columns": new_cols, "rows": new_rows}


IMAGE_THUMB_BUDGET = 240   # tek tabloda kac hucre icin onizleme uretilir


def attach_images(table: dict, src: IM.Sources,
                  budget: int = IMAGE_THUMB_BUDGET) -> tuple[int, int]:
    """Gorsel tasiyan hucreleri onizlemeli hucreye yukseltir.

    Tablo kurulduktan SONRA tek gecişte calisir; boylece hucre kuruculari
    gorselden habersiz kalir. Hucrenin gosterim metni zaten ham degerdir
    (data URI'de dev base64), okunabilir bir etiketle degistirilir.
    """
    made = 0
    blocked = 0          # 9.6.5.1 — izin bekleyen mutlak yollu hucreler
    image_cols: set[int] = set()

    for row in table["rows"]:
        for i, cell in enumerate(row):
            if not cell or cell.get("k") != C_SCALAR:
                continue
            desc = IM.detect(cell.get("d", ""))
            if desc is None:
                continue
            if desc["source"] == "url":
                # `K-32` (9.15) — tablo KURULURKEN adrese istek GONDERILMEZ:
                # hucreler burada okunuyor ve adresi indirmek, tablo acilmadan
                # once 240 istege kadar ag beklemesi demekti (9.6.5.2'nin
                # gerekcesi). Ayar aciksa hucre yalnizca "uzak gorsel" diye
                # isaretlenir; onizlemeyi arayuz cizimden SONRA galeri yolundan
                # ister. Ayar kapaliyken ya da adres kurali gecmiyorsa (http,
                # yerel ag, parolali) hucre duz metin kalir: `url_permitted`
                # izin VE adres kuralini AGA CIKMADAN sinar.
                if made < budget and IM.url_permitted(desc, src):
                    cell["k"] = C_IMAGE
                    cell["remote"] = True
                    cell["embedded"] = False
                    cell["src"] = desc["url"]
                    made += 1
                    image_cols.add(i)
                continue
            if desc["source"] == "file" and IM.resolve(desc, src) is None:
                # Izin bekleyen mutlak yol SAYILIR: durum satiri kullaniciya
                # izni nerede verecegini soyluyor. Sayim dosyaya dokunmaz —
                # `resolve` izinsiz yolu diske inmeden reddetti.
                if not src.absolute and IM.path_kind(desc["path"]) == IM.PATH_ABSOLUTE:
                    blocked += 1
                continue

            cell["k"] = C_IMAGE
            # ⚠ `embedded` BAYRAKTIR, `src` ise yoldur. Once `src` gomulu
            # gorsellerde "gömülü" dizesini tasiyordu ve arayuz onu dize
            # esitligiyle sinardi (`cell.src === 'gömülü'`) — `G_ID = "Kimlik"`
            # ile ayni tuzak: ceviri karsilastirmayi koparirdi.
            cell["embedded"] = desc["source"] == "data"
            cell["src"] = desc.get("path") or ""
            if cell["embedded"]:
                mime = (desc.get("mime") or "").split("/")[-1]
                cell["d"] = I18N.t("cell.embedded_image", format=mime)
            else:
                cell["d"] = desc["path"]

            if made < budget:
                thumb = IM.thumbnail(desc, src)
                if thumb:
                    cell["thumb"] = thumb["uri"]
                    cell["iw"] = thumb.get("source_width", thumb["width"])
                    cell["ih"] = thumb.get("source_height", thumb["height"])
            made += 1
            image_cols.add(i)

    for i in image_cols:
        if i < len(table["columns"]):
            table["columns"][i]["kind"] = C_IMAGE
            table["columns"][i]["numeric"] = False
    return made, blocked


def build_table(root: Any, ds: D.Dataset, variant_id: str | None = None,
                transpose: bool = False, sources: IM.Sources | None = None,
                wrap: bool = True) -> dict:
    """Bir `Dataset` (veya varyanti) icin tam tabloyu uretir.

    `wrap` kullanici tercihidir (9.19.2): kapaliyken hicbir sutun sarilmaz,
    uzun metin tek satirda kirpilir. Ayar buraya PARAMETRE olarak gelir —
    bu modul durum tutmaz.
    """
    node = D.resolve(root, ds.path)
    variant = next((v for v in ds.variants if v.id == variant_id), None)

    if ds.kind == D.RECORDS:
        if variant is not None:
            table = records_table(node, only_rows=variant.rows, only_keys=variant.keys)
        else:
            table = records_table(node)
    elif ds.kind == D.KEYED:
        if variant is not None:
            table = keyed_table(node, only_rows=variant.rows, only_keys=variant.keys)
        else:
            table = keyed_table(node)
    elif ds.kind == D.KEYLIST:
        table = keylist_table(node)
    elif ds.kind == D.PIVOT:
        table = pivot_table(node, pivot_cols(node))
    else:
        table = keyvalue_table(node)

    # Gorsel yukseltmesi transpozeden ONCE yapilir; transpoze hucreleri
    # oldugu gibi tasidigi icin onizlemeler her iki modda da korunur.
    images, blocked = attach_images(table, sources or IM.Sources())

    # Duzenlenemezlik nedeni (10.1) de transpozeden ONCE: adres transpozesiz
    # tablonun indeksleridir ve hucre nesnesi transpozeyle birlikte tasinir.
    # Yerel ice aktarma: `edit_map` bu modulun sira yardimcilarini kullaniyor.
    from . import edit_map as EM
    EM.attach_edit(table, root, ds, variant.id if variant else None)

    source_rows, source_cols = len(table["rows"]), len(table["columns"])
    if transpose:
        table = transpose_table(table)

    mark_wrap(table, wrap)

    table.update({
        "id": ds.id,
        "variant": variant.id if variant else None,
        "label": variant.label if variant else ds.label_text,
        "kind": ds.kind,
        "kind_label": ds.kind_label,
        "notes": [] if variant else ds.note_texts,
        "transposed": transpose,
        "images": images,
        "images_blocked": blocked,
        "source_shape": [source_rows, source_cols],
        "groups": _group_summary(table["columns"], transpose),
    })
    return table


def longest_cell(table: dict, idx: int) -> int:
    """Sutundaki en uzun gosterim metninin karakter sayisi."""
    rows = table["rows"]
    return max((len(r[idx].get("d") or "") for r in rows if idx < len(r) and r[idx]),
               default=0)


def mark_wrap(table: dict, enabled: bool = True) -> None:
    """Tek satira sigmayan skaler metin sutunlarini `wrap` olarak isaretler.

    Isaret tabloyla birlikte tasindigi icin ekran, PNG, PDF ve SVG ayni
    sutunlari sarilmis kabul eder; olcu tek yerde durur.

    Iki ayri isaret var (9.19.2): `long` sutunun ICERIGINI soyler (tek satira
    sigmiyor), `wrap` nasil CIZILECEGINI. Sarma kapaliyken `wrap` hicbir
    sutunda dogru olmaz ama `long` kalir — grafik, uzun metin sutununu
    kirilim adayi saymamak icin onu okur ve bu, cizim tercihine bagli olmamali.
    """
    for i, c in enumerate(table["columns"]):
        if c["kind"] != C_SCALAR or c.get("numeric"):
            continue
        c["long"] = longest_cell(table, i) > WRAP_CHARS
        c["wrap"] = c["long"] and enabled


def _group_summary(cols: list[dict], transposed: bool) -> list[dict]:
    """Arayuzun grup basligi cizebilmesi icin grup -> sutun sayisi ozeti."""
    if transposed:
        return []
    counts: dict[str, int] = {}
    for c in cols:
        counts[c.get("group", COL.G_OTHER)] = counts.get(c.get("group", COL.G_OTHER), 0) + 1
    return [
        {"name": g, "count": counts[g]}
        for g in sorted(counts, key=COL.group_sort_key)
    ]
