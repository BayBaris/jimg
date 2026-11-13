"""Grafigin VERI tarafi: sutun rolleri, oneriler ve olcumler.

Buradaki hicbir fonksiyon cizim yapmaz ve **Pillow'a dokunmaz**. Ayrilmasinin
sebebi de bu: `Api.chart_columns()` arayuz her veri kumesi actiginda cagriliyor
ve yalnizca sutun listesi istiyor — o yol artik cizim yiginini hic gormez.

⚠ Ice aktarma zinciri gozetilmelidir: `flatten` → `images` → Pillow. `images`
Pillow'u ISLEV ICINDE ice aktarir (bkz. `images.open_image`), bu yuzden bu modul
Pillow'suz kalir. `flatten`'a Pillow'u tepeden ice aktaran bir baglanti
eklenirse kazanc sessizce kaybolur; `check.py --> check_import_chain` bunu
denetler.

Olcumler iki listede tutulur ve KARISTIRILMAMALIDIR:
  AGGS         — tum olcumler; `count` dahil
  COMPARE_AGGS — kullaniciya SUNULANLAR; `count` disarida

Iki liste de yalnizca ANAHTAR tasir; etiket ve aciklama `i18n` sozlugundedir
(`agg.<k>.label` / `agg.<k>.note`).

`count` listede yoktur cunku kayit saymak Dagilim modunun isidir;
karsilastirmada secilince sayisal sutun devre disi kaliyor ve mod, Dagilim'in
kopyasina donuyordu. Kodda durur, yalnizca Dagilim modu kullanir.
"""

from __future__ import annotations

from . import columns as COL
from . import flatten as F
from . import i18n as I18N

# --- Olcumler --------------------------------------------------------------

# Olcum secenekleri — yalnizca ANAHTAR listesi (Faz 9.2.6). Etiket
# `agg.<k>.label`, aciklama `agg.<k>.note` olarak sozluktedir ve CAGRI ANINDA
# cozulur: dil oturum icinde degisebiliyor.
#
# "count" sayisal sutun GEREKTIRMEZ — kategorilerin kac satirda gectigini
# sayar; bool/enum sutunlarin dagilimi boyle gorulur.
AGGS = ("count", "sum", "avg", "median", "min", "max")

# Kullaniciya SUNULAN olcumler. `count` disaridadir (bkz. modul aciklamasi).
# `median` aykiri degere dayaniklidir — JSON'larda tek bir buyuk kayit
# ortalamayi yaniltir, ortanca "tipik deger" sorusunu her belgede yanitlar.
COMPARE_AGGS = ("sum", "avg", "median", "min", "max")

# Tek sayisal sutunun dagilim KIPI (`numeric_distribution` ucuncu donusu).
# ⚠ Bunlar ANAHTARDIR, etiket degil: cagiran taraf `unit == UNIT_ROWS` diye
# KARSILASTIRIYOR. Once "kayit"/"kova" yaziyordu ve `G_ID = "Kimlik"` ile
# birebir ayni tuzakti — cevirmek karsilastirmayi koparirdi.
UNIT_ROWS = "rows"
UNIT_BINS = "bins"


# --- Sutun rolleri ve oneriler (Faz 7.4) -----------------------------------
# Eski arayuz dort karar istiyordu (kategori · olcum · deger · tur) ve bunlarin
# ANLAMLI olup olmadigini denetlemiyordu: serbest metin kategori secilebiliyor,
# ilgisiz bir sayisal alan bir siniflandirmayla eslestirilebiliyordu.
# Cozum: sutunlari once ROLE ayirmak, listeleri ona gore suzmek.

# Kac kategori cizime girer. Bu bir VERI sinirisidir (toplama sonrasi kesme),
# cizim olcusu degil — `img_chart` icindeki CHART_W/CHART_H ile karistirilmamali.
CHART_MAX_CATS = 24

BREAKDOWN_MIN = 2       # tek degerli sutun grafige donmez
BREAKDOWN_MAX = CHART_MAX_CATS
ROW_BAR_LIMIT = 24      # bunun altinda her kayit kendi cubugu, ustunde histogram
HIST_BINS = 10


def _uniques(table: dict, idx: int) -> int:
    seen = set()
    for r in table["rows"]:
        cell = r[idx] if idx < len(r) else None
        if cell and cell.get("k") != F.C_MISSING:
            seen.add(cell.get("d"))
    return len(seen)


def chart_roles(table: dict) -> dict:
    """Sutunlari grafikteki rolune gore ayirir.

    breakdown — "neye gore" sorusunun yaniti: siniflandirma ve bayrak
                sutunlari, 2 ≤ benzersiz ≤ 24. Kimlik sutunlari haric: her satir
                benzersiz oldugu icin 7 dilimli bir pasta anlamsizdir.
    measure   — "ne kadar" sorusunun yaniti: sayisal sutunlar.
    excluded  — serbest metin, uzun metin (`wrap`), ic ice ve asiri kardinalite.
    """
    breakdown, measure, excluded = [], [], []

    for i, c in enumerate(table["columns"]):
        item = {"key": c["key"], "label": c["label"], "group": c.get("group")}

        if c["kind"] != F.C_SCALAR or c.get("long"):
            excluded.append(item)
            continue
        if c.get("numeric"):
            measure.append(item)
            continue

        uniq = _uniques(table, i)
        item["uniq"] = uniq
        if c.get("group") in (COL.G_CAT, COL.G_FLAG) and BREAKDOWN_MIN <= uniq <= BREAKDOWN_MAX:
            breakdown.append(item)
        else:
            excluded.append(item)

    return {"breakdown": breakdown, "measure": measure, "excluded": excluded}


def chart_suggestions(table: dict, limit: int = 6) -> dict:
    """Tablodan otomatik grafik onerileri — belgeye ozel kod YOK.

    Kullanicinin "anahtarlarin, bayraklarin ne kadar/ne siklikta/hangi oranda
    oldugunu gormesi" istegi bu listeyle karsilanir: arac soruyu kendisi kurar,
    kullanici yalnizca tiklar.

    MODA GORE ayri listeler doner; arayuz secili modun onerilerini gosterir.
    Baslikta "… dagilimi" yazmaz — hangi modda oldugu zaten bellidir, sutun
    adi yeter.
    """
    roles = chart_roles(table)
    rows = len(table["rows"])
    distribution, compare = [], []

    # Az degerli kirilimlar once: net bir cevap veriyorlar (bool → 2 dilim).
    for c in sorted(roles["breakdown"], key=lambda x: x["uniq"]):
        distribution.append({
            "mode": "distribution", "cat": c["key"], "numeric": None, "agg": "count",
            "chart": "pie" if c["uniq"] <= 6 else "bar",
            "title": c["label"],
            "note": I18N.t("card.breakdown", n=c["uniq"], rows=rows),
        })

    for m in roles["measure"]:
        distribution.append({
            "mode": "distribution", "cat": None, "numeric": m["key"], "agg": "sum",
            "chart": "bar",
            "title": m["label"],
            "note": (I18N.t("card.measure", rows=rows) if rows <= ROW_BAR_LIMIT
                     else I18N.t("card.measure_bins", rows=rows, bins=HIST_BINS)),
        })

    # Kirilim x olcu: "X'e gore Y ne kadar" — en bilgi yogun kart.
    for c in roles["breakdown"][:3]:
        for m in roles["measure"][:2]:
            compare.append({
                "mode": "compare", "cat": c["key"], "numeric": m["key"], "agg": "sum",
                "chart": "bar",
                "title": f"{c['label']} × {m['label']}",
                "note": I18N.t("card.compare"),
            })

    return {"distribution": distribution[:limit], "compare": compare[:limit]}


# --- Olcum uretimi ---------------------------------------------------------

def _numeric_values(table: dict, num_key: str,
                    row_order: list[int] | None) -> list[tuple[str, float]]:
    """Sayisal sutunun (etiket, deger) ciftleri. Etiket ilk kimlik sutunundan."""
    keys = [c["key"] for c in table["columns"]]
    if num_key not in keys:
        raise ValueError(I18N.t("err.numeric_missing"))
    ni = keys.index(num_key)

    # Cubuk etiketi icin kimlik sutunu aranir; yoksa satir numarasi kullanilir.
    label_i = next((i for i, c in enumerate(table["columns"])
                    if c.get("group") == COL.G_ID and c["kind"] == F.C_SCALAR), None)

    rows = table["rows"]
    if row_order is not None:
        rows = [rows[i] for i in row_order if 0 <= i < len(rows)]

    out = []
    for n, r in enumerate(rows, 1):
        cell = r[ni] if ni < len(r) else None
        if not cell or "v" not in cell:
            continue
        lab = str(n)
        if label_i is not None and label_i < len(r) and r[label_i]:
            lab = r[label_i].get("d") or str(n)
        out.append((lab, float(cell["v"])))
    return out


def numeric_distribution(table: dict, num_key: str, row_order: list[int] | None
                         ) -> tuple[list[tuple[str, float]], dict, str]:
    """Tek sayisal sutunun dagilimi.

    Kucuk tabloda (`ROW_BAR_LIMIT` altinda) **her kayit kendi cubugu** olur —
    "hangi kayit daha buyuk" sorusu dogrudan yanitlanir. Buyuk tabloda bu
    okunmaz hale gelir, onun yerine **histogram** cizilir.
    """
    pairs = _numeric_values(table, num_key, row_order)
    values = [v for _, v in pairs]
    stats = {
        "rows": len(pairs), "cats": len(pairs), "hidden": 0,
        "total": sum(values) if values else 0.0,
        "avg": (sum(values) / len(values)) if values else 0.0,
        "min": min(values) if values else 0.0,
        "max": max(values) if values else 0.0,
    }

    if len(pairs) <= ROW_BAR_LIMIT:
        pairs.sort(key=lambda kv: -kv[1])
        return pairs, stats, UNIT_ROWS

    lo, hi = stats["min"], stats["max"]
    if hi <= lo:
        return [(f"{lo:g}", float(len(values)))], {**stats, "cats": 1}, UNIT_BINS

    step = (hi - lo) / HIST_BINS
    counts = [0] * HIST_BINS
    for v in values:
        k = min(HIST_BINS - 1, int((v - lo) / step))
        counts[k] += 1

    bins = [(f"{lo + i * step:g}–{lo + (i + 1) * step:g}", float(n))
            for i, n in enumerate(counts)]
    return bins, {**stats, "cats": HIST_BINS}, UNIT_BINS


def _aggregate(table: dict, cat_key: str, num_key: str | None, agg: str,
               row_order: list[int] | None) -> tuple[list[tuple[str, float]], dict]:
    """Kategorilere gore olcum uretir ve ozet istatistigi dondurur."""
    if agg not in AGGS:
        raise ValueError(I18N.t("err.unknown_agg", agg=agg))

    keys = [c["key"] for c in table["columns"]]
    if cat_key not in keys:
        raise ValueError(I18N.t("err.category_missing"))
    if agg != "count":
        if not num_key or num_key not in keys:
            raise ValueError(I18N.t("err.agg_needs_measure"))
    ci = keys.index(cat_key)
    ni = keys.index(num_key) if (num_key and num_key in keys) else None

    rows = table["rows"]
    if row_order is not None:
        rows = [rows[i] for i in row_order if 0 <= i < len(rows)]

    buckets: dict[str, list[float]] = {}
    used = 0
    for r in rows:
        c = r[ci] if ci < len(r) else None
        if not c or c.get("k") == F.C_MISSING:
            continue
        label = c.get("d") or "—"

        if agg == "count":
            buckets.setdefault(label, []).append(1.0)
            used += 1
            continue

        n = r[ni] if (ni is not None and ni < len(r)) else None
        if not n or "v" not in n:
            continue                      # sayisal olmayan hucre olcume girmez
        buckets.setdefault(label, []).append(float(n["v"]))
        used += 1

    def _median(vs: list[float]) -> float:
        s = sorted(vs)
        n = len(s)
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

    reduce = {
        "count": lambda vs: float(len(vs)),
        "sum": lambda vs: float(sum(vs)),
        "avg": lambda vs: sum(vs) / len(vs),
        "median": _median,
        "min": lambda vs: min(vs),
        "max": lambda vs: max(vs),
    }[agg]

    items = [(k, reduce(v)) for k, v in buckets.items()]
    items.sort(key=lambda kv: -abs(kv[1]))
    shown = items[:CHART_MAX_CATS]

    values = [v for _, v in items]
    stats = {
        "rows": used,
        "cats": len(items),
        "hidden": max(0, len(items) - len(shown)),
        "total": sum(values) if values else 0.0,
        "avg": (sum(values) / len(values)) if values else 0.0,
        "min": min(values) if values else 0.0,
        "max": max(values) if values else 0.0,
    }
    return shown, stats
