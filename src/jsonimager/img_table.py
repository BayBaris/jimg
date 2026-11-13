"""Tablo cizimi: yerlesim, metin sarma ve sahne.

Cikti EKRANLA BIREBIR olmalidir. Bunun iki sarti var:
  - `auto_width` arayuzdeki `autoWidth` ile ayni formulu kullanir
    (`web/js/columns.js`); esitlik `check.py --> CONST_PAIRS` ile denetlenir.
  - Sutun sirasi/genisligi/gizliligi ve satir sirasi DISARIDAN gelir
    (`view`, `row_order`), burada yeniden hesaplanmaz.

Satir yuksekligi SABIT DEGILDIR: sarilan hucreler satiri buyutur (`AK-10`).
"""

from __future__ import annotations

from . import columns as COL
from . import flatten as F
from . import i18n as I18N
from . import theme as TH
from .draw import (PAD, _baseline, _ellipsize, _fit, _font, _MEASURE, _oneline,
                   _text_w, scene_to_png)
from .vector import Scene

# --- Tabloya ozel olculer --------------------------------------------------
#
# ⚠ Yazi tipi boyutuna bagli olanlar BURADA YOK: `ROW_H`, `HEAD_H`, `GROUP_H`,
# `WRAP_LINE_H` ve punto olculeri `theme.metrics()`ten gelir ve CIZIM ANINDA
# okunur (paletle ayni kalip). Asagidakiler boyuttan bagimsizdir: dolgu,
# kenarlik payi ve gorsel onizlemesinin yuksekligi.

ROW_H_IMAGE = 48      # gorsel onizlemesi tasiyan tablolarda satir yuksekligi
CELL_PAD = 8
MIN_W, MAX_W = 60, 320
MAX_ROWS_DEFAULT = 300

# Sutun genisligi katsayilari. Karakter genislikleri (`char_w`, `badge_char_w`)
# boyuttan turer ve `theme.metrics`ten okunur; buradaki ikisi sabittir ve
# `state.js` ile AYNI olmak zorunda (`check.py --> CONST_PAIRS`). Karakter
# basina piksel kaba bir tahmindir: gercek olcum tarayicida metin olcmeyi
# gerektirirdi ve ayni sayiyi Pillow tarafinda tutturmak imkansizlasirdi.
PAD_X = 30          # dolgu + bosluk payi
BADGE_GAP = 5       # etiket ile rozet arasi (CSS `.th-inner { gap }` ile ayni)


def _badge_text(col: dict) -> str:
    """Basliktaki tip rozeti (`js/table.js` ile ayni kural)."""
    if col["kind"] == F.C_RECORDS:
        return "{}"
    if col["kind"] == F.C_LIST:
        return "[]"
    return col.get("dtype") or ""


def auto_width(col: dict, rows: list[list[dict]], idx: int) -> int:
    """Arayuzdeki `autoWidth` ile ayni hesap — cikti ekranla ayni genislikte olsun.

    ⚠ Baslik HER ZAMAN taban olusturur: bir sutun kendi adindan dar olamaz.
    Once yalnizca `max(etiket, veri)` hesaplaniyordu ve tip rozeti hic
    sayilmiyordu; sifirlanmis bir tabloda bile `category` → `catego…` diye
    kirpiliyordu.
    """
    m = TH.metrics()
    char_w = m.char_w
    # ⚠ Rozet payi da PUNTODAN turer. Sabit 5 px kalsaydi buyuk puntoda ayrilan
    # yer rozetin gercek genisliginden dar olur ve bu formulun kapatmak icin
    # yazildigi `category → catego…` kirpmasi geri gelirdi.
    head = (len(col["label"]) * char_w
            + len(_badge_text(col)) * m.badge_char_w + PAD_X)

    if col["kind"] in (F.C_RECORDS, F.C_OBJECT):
        body = 96
    elif col["kind"] == F.C_IMAGE:
        body = 120          # arayuzdeki ile ayni: onizleme sigsin
    elif col.get("wrap"):
        body = F.TEXT_COL_W   # uzun metin sutunu; arayuzde de bu genislikte
    else:
        longest = 0           # etiket artik `head`te hesaplaniyor
        for r in rows[:60]:
            cell = r[idx] if idx < len(r) else None
            if cell and cell.get("d"):
                longest = max(longest, len(cell["d"]))
        body = longest * char_w + PAD_X

    return min(MAX_W, max(MIN_W, head, body))


def _layout(table: dict, view: dict | None, row_order: list[int] | None,
            max_rows: int | None):
    cols = table["columns"]
    if view:
        hidden = set(view.get("hidden") or ())
        order = [k for k in (view.get("order") or []) if k not in hidden]
        by_key = {c["key"]: c for c in cols}
        picked = [by_key[k] for k in order if k in by_key]
        if picked:
            cols = picked

    idxs = [table["columns"].index(c) for c in cols]
    all_rows = table["rows"]
    # `order` satirlarin KAYNAK indeksleridir; acik satirlar (`expanded`) da
    # kaynak indeks tasidigi icin eslesme buradan kuruluyor.
    order = (list(range(len(all_rows))) if row_order is None
             else [i for i in row_order if 0 <= i < len(all_rows)])

    truncated = 0
    if max_rows is not None and len(order) > max_rows:
        truncated = len(order) - max_rows
        order = order[:max_rows]
    rows = [all_rows[i] for i in order]

    widths = []
    for c, i in zip(cols, idxs):
        w = (view or {}).get("widths", {}).get(c["key"]) or auto_width(c, table["rows"], i)
        widths.append(int(w))

    return cols, idxs, rows, widths, truncated, order


# --- Metin sarma (AK-10) ---------------------------------------------------
# Ekranda `td.cell-wrap` metni hucre icinde alt satirlara yayar; cizim de ayni
# sutunlari sarmali, yoksa PNG/PDF ekrandan farkli cikar. Sarilacak sutunlari
# `flatten.mark_wrap` isaretler (`wrap` bayragi).

# Satir yuksekligi (`wrap_line_h`) boyuttan, hucre boslugu satir yogunlugundan
# turer (9.19.1); satir siniri turemez.
WRAP_MAX_LINES = 8    # tek hucrede cizilecek en fazla satir


def _wrap_pad(m: TH.Metrics) -> int:
    """Sarilan hucrenin ust/alt boslugu — ekrandaki `td` dolgusunun 1 px altinda.

    `normal` yogunlukta `9.19`dan onceki sabit (5) cikar; yogunluk degisince
    ekrandaki dolguyla ayni adimda degisir.
    """
    return m.cell_pad_y - 1


def _wrap_lines(text: str, size: int, max_w: float,
                limit: int = WRAP_MAX_LINES) -> list[str]:
    """Metni piksel genisligine gore satirlara boler.

    Kelime sinirindan boler; tek basina sigmayan kelime kirpilir. `limit`
    asilirsa son satir "…" ile biter — sonsuz buyuyen bir hucre sahneyi
    on binlerce piksel yapardi.
    """
    text = _oneline(text)
    if not text:
        return [""]

    font = _font(size)
    width = max(20, int(max_w))
    lines: list[str] = []
    cur = ""

    for word in text.split(" "):
        trial = f"{cur} {word}".strip()
        if not cur or _text_w(_MEASURE, trial, font) <= width:
            cur = trial
            continue
        lines.append(cur)
        cur = word
        if len(lines) >= limit:
            break

    if cur and len(lines) < limit:
        lines.append(cur)

    over = len(lines) >= limit and _text_w(_MEASURE, text, font) > width * limit
    lines = [_ellipsize(_MEASURE, ln, font, width) for ln in lines[:limit]]
    if over and lines:
        lines[-1] = _ellipsize(_MEASURE, lines[-1] + " …", font, width)
    return lines or [""]


def _wrapped_cols(cols: list[dict]) -> bool:
    return any(c.get("wrap") for c in cols)


def _row_heights(rows, cols, widths, idxs, base_h: float) -> list[float]:
    """Her satirin yuksekligi: sarilan hucrelerin en uzunu belirler."""
    if not _wrapped_cols(cols):
        return [base_h] * len(rows)

    m = TH.metrics()
    out = []
    for r in rows:
        h = base_h
        for c, cw, i in zip(cols, widths, idxs):
            if not c.get("wrap"):
                continue
            cell = r[i] if i < len(r) else None
            if not cell or cell.get("k") != F.C_SCALAR:
                continue
            n = len(_wrap_lines(cell.get("d") or "", m.font, cw - CELL_PAD * 2))
            h = max(h, _wrap_pad(m) * 2 + n * m.wrap_line_h)
        out.append(h)
    return out


# --- Acik satirlarin ayrinti blogu (9.11.3) --------------------------------
# Ekranda `tr.detail` bir ic tablo gosteriyor; cizim de gostermeli, yoksa
# "cikti ekranla birebir" degismezi acik satirda bozulur.

DETAIL_PAD = 6
DETAIL_MIN_W = 40      # oranli kucultmede bir sutunun inebilecegi taban
DETAIL_MAX_ROWS = 10   # ic tablodan cizilecek en fazla satir


def _detail_blocks(table: dict, row: list) -> list[tuple[str, dict]]:
    """Satirdaki ic ice hucreler: (sutun etiketi, alt tablo).

    ⚠ GORUNUR sutunlar degil, tablonun TUM sutunlari gezilir — ekrandaki
    `buildDetailRow` de oyle yapiyor: gizlenmis bir sutunun ic icerigi
    ayrinti satirinda yine gorunur.
    """
    return [(c["label"], row[k]["sub"])
            for k, c in enumerate(table["columns"])
            if k < len(row) and row[k] and row[k].get("sub")]


def _detail_widths(sub: dict, avail: float) -> list[float]:
    """Ic tablonun sutun genislikleri; sigmiyorsa ORANLI kucultulur.

    Ayni `auto_width` formulu kullanilir (ekranla ayni sayilar), sonra toplam
    ana tablonun genisligini asiyorsa oranlanir — metin `_fit` ile kirpilir,
    yani tasma olmaz.
    """
    ws = [float(auto_width(c, sub["rows"], i)) for i, c in enumerate(sub["columns"])]
    total = sum(ws)
    if total > avail and total > 0:
        k = avail / total
        ws = [max(DETAIL_MIN_W, w * k) for w in ws]
    return ws


def _detail_height(blocks: list[tuple[str, dict]], m) -> float:
    """Ayrinti blogunun yuksekligi — sahne kurulmadan ONCE bilinmeli."""
    h = DETAIL_PAD
    for _, sub in blocks:
        shown = min(len(sub["rows"]), DETAIL_MAX_ROWS)
        extra = 1 if len(sub["rows"]) > DETAIL_MAX_ROWS else 0
        h += m.small + 4 + m.head_h + (shown + extra) * m.row_h + DETAIL_PAD
    return h


def _draw_detail(sc: Scene, blocks, x0: float, y: float, width: float, pal, m) -> None:
    """Acik satirin altina ic tablolari cizer."""
    y += DETAIL_PAD
    ind = x0 + DETAIL_PAD * 2
    avail = width - DETAIL_PAD * 3

    for label, sub in blocks:
        sc.text(ind, y + m.small, _fit(label, m.small, True, avail),
                size=m.small, fill=pal.muted, bold=True)
        y += m.small + 4

        ws = _detail_widths(sub, avail)
        span = sum(ws)
        sc.rect(ind, y, span, m.head_h, fill=pal.panel_2)
        cx = ind
        for c, w in zip(sub["columns"], ws):
            sc.text(cx + CELL_PAD, _baseline(y, m.head_h, m.small),
                    _fit(c["label"], m.small, True, w - CELL_PAD * 2),
                    size=m.small, fill=pal.text_2, bold=True)
            cx += w
        y += m.head_h

        for row in sub["rows"][:DETAIL_MAX_ROWS]:
            cx = ind
            for j, w in enumerate(ws):
                cell = row[j] if j < len(row) else None
                text = "" if not cell or cell.get("k") == F.C_MISSING else (cell.get("d") or "")
                sc.text(cx + CELL_PAD, _baseline(y, m.row_h, m.small),
                        _fit(text, m.small, False, w - CELL_PAD * 2),
                        size=m.small, fill=pal.text)
                cx += w
            sc.line([(ind, y + m.row_h), (ind + span, y + m.row_h)], stroke=pal.line, sw=1)
            y += m.row_h

        # ⚠ Sinir olmadan tek bir ic tablo sahneyi on binlerce piksel yapar —
        # `WRAP_MAX_LINES` ile ayni gerekce, `AK-14` zaten PNG boyutundan
        # sikayetci.
        if len(sub["rows"]) > DETAIL_MAX_ROWS:
            sc.text(ind + CELL_PAD, _baseline(y, m.row_h, m.small),
                    I18N.t("cell.more_rows", n=len(sub["rows"]) - DETAIL_MAX_ROWS),
                    size=m.small, fill=pal.muted)
            y += m.row_h
        y += DETAIL_PAD


# --- Sahne -----------------------------------------------------------------

def table_scene(table: dict, view: dict | None = None,
                row_order: list[int] | None = None,
                max_rows: int | None = MAX_ROWS_DEFAULT,
                title: str | None = None, subtitle: str | None = None,
                expanded: set[int] | None = None) -> Scene:
    """Tabloyu ekrandaki duzeniyle sahneye kurar (PNG/SVG/PDF ayni sahneden).

    `expanded` ekranda ACIK birakilan satirlarin kaynak indeksleridir; her biri
    icin altina ic tablolari tasiyan bir ayrinti blogu cizilir.
    """
    # Palet CIZIM ANINDA okunur: tema degisince bir sonraki cizim yeni renkleri
    # alir, modul yeniden yuklenmeye gerek kalmaz (`i18n.get_lang` ile ayni).
    pal, m = TH.active(), TH.metrics()
    cols, idxs, rows, widths, truncated, order = _layout(table, view, row_order, max_rows)
    if not cols:
        return Scene(400, 60, pal.bg)

    # Yedek deger `api_table._default_view` ile AYNI olmali (ikisi de kapali):
    # gorunum gecirilmeden cizim yapilan yollarda cikti ekrandan sapmasin.
    show_groups = bool((view or {}).get("groups", False)) and not table.get("transposed")
    has_expand = any(c.get("sub") for r in table["rows"] for c in r)
    has_image = any(c.get("kind") == F.C_IMAGE for c in cols)
    row_h = ROW_H_IMAGE if has_image else m.row_h

    exp_w = 28 if has_expand else 0
    table_w = sum(widths) + exp_w
    head_total = (m.group_h if show_groups else 0) + m.head_h

    # Satir yuksekligi artik SABIT DEGIL: sarilan hucreler satiri buyutur.
    heights = _row_heights(rows, cols, widths, idxs, row_h)

    # Acik satirlarin ayrinti bloklari: once OLCULUR (sahne yuksekligi bilinmeli),
    # sonra satirin altina cizilir.
    open_rows = set(expanded or ())
    details = [_detail_blocks(table, r) if src in open_rows else []
               for src, r in zip(order, rows)]
    detail_h = [_detail_height(b, m) if b else 0.0 for b in details]

    # Altbilgi: tablonun KENDI olculeri buraya yazilir, basliga degil. Ustte
    # yalnizca veri kumesi adi ve belge adi kalir.
    foot = _table_footer(table, cols, rows, truncated, max_rows)
    foot_h = 24 if foot else 0

    sc = Scene(table_w + PAD * 2,
               m.title_h + head_total + sum(heights) + sum(detail_h)
               + foot_h + PAD * 2, pal.bg)

    y = PAD
    if title:
        sc.text(PAD, y + m.title, title, size=m.title, fill=pal.text, bold=True)
    if subtitle:
        # Alt baslik ust basligin ALTINDA: ofset punto ile buyur, sabit 32
        # yazilsaydi buyuk boyutta ustteki metnin uzerine binerdi.
        sc.text(PAD, y + m.title * 2, subtitle, size=m.small, fill=pal.muted)
    y += m.title_h

    x0 = PAD
    if show_groups:
        # Grup rengi paletten INDEKSLE gelir (`g0`…`g6`); sira `GROUP_ORDER`.
        # CSS'te de indeksle dagitiliyor (`.group-row th.g-3`), yani ayni sirayi
        # ucuncu bir yere yazmak yerine tek yardimciyla kuruluyor.
        group_colors = TH.group_colors(COL.GROUP_ORDER)
        sc.rect(x0, y, table_w, m.group_h, fill=pal.group_row)
        gx, i = x0 + exp_w, 0
        while i < len(cols):
            g = cols[i].get("group", COL.G_OTHER)
            j, span = i, 0
            while j < len(cols) and cols[j].get("group", COL.G_OTHER) == g:
                span += widths[j]
                j += 1
            color = group_colors.get(g, pal.muted)
            # `g` ANAHTARDIR (`id`, `cat`…); ekranda gorunen metin dilden gelir.
            label = I18N.upper(I18N.t(f"group.{g}"))
            sc.text(gx + span / 2, _baseline(y, m.group_h, m.small),
                    _fit(label, m.small, False, span - 8),
                    size=m.small, fill=color, anchor="middle")
            sc.rect(gx, y + m.group_h - 2, span, 2, fill=color)
            gx, i = gx + span, j
        y += m.group_h

    sc.rect(x0, y, table_w, m.head_h, fill=pal.panel_2)
    sc.line([(x0, y + m.head_h), (x0 + table_w, y + m.head_h)], stroke=pal.line, sw=1)

    sort = (view or {}).get("sort") or {}
    cx = x0 + exp_w
    for c, cw in zip(cols, widths):
        sorted_here = sort.get("key") == c["key"]
        marker_w = (10 if c.get("sparse") else 0) + (12 if sorted_here else 0)

        # Tip rozeti etiketin HEMEN SAGINDA, ekrandaki gibi (`.th-badge`).
        # `auto_width` yerini zaten ayirmisti; cizilmeseydi o bosluk anlamsiz
        # dururdu ve ekran ile cikti ayni baslikta ayri sey gosterirdi.
        badge = _badge_text(c)
        badge_w = (_text_w(_MEASURE, badge, _font(m.small)) + BADGE_GAP
                   if badge else 0)

        label = _fit(c["label"], m.font, True,
                     max(12, cw - CELL_PAD * 2 - marker_w - badge_w))
        base = _baseline(y, m.head_h, m.font)
        sc.text(cx + CELL_PAD, base, label, size=m.font, fill=pal.text, bold=True)

        if badge:
            # Rozet etiketin GERCEK genisliginden sonra baslar: kirpilmis bir
            # etikette ayrilan yerin tamamini kullanmak arada bosluk birakirdi.
            bx = cx + CELL_PAD + _text_w(_MEASURE, label, _font(m.font, True))
            sc.text(bx + BADGE_GAP, base, badge, size=m.small, fill=pal.muted)

        mx = cx + cw - CELL_PAD
        if sorted_here:
            up = sort.get("dir", 1) > 0
            cy2 = y + m.head_h / 2
            sc.poly([(mx - 6, cy2 - 4), (mx - 10, cy2 + 3), (mx - 2, cy2 + 3)] if up
                    else [(mx - 6, cy2 + 4), (mx - 10, cy2 - 3), (mx - 2, cy2 - 3)],
                    fill=pal.accent)
            mx -= 12
        if c.get("sparse"):
            sc.text(mx - 8, _baseline(y, m.head_h, m.small), "◦",
                    size=m.small, fill=pal.warn)

        sc.line([(cx + cw, y), (cx + cw, y + m.head_h)], stroke=pal.line, sw=1)
        cx += cw
    y += m.head_h

    ry = y
    for ri, r in enumerate(rows):
        rh = heights[ri]
        if ri % 2:
            sc.rect(x0, ry, table_w, rh, fill=pal.row_alt)

        if has_expand:
            if any(r[i] and r[i].get("sub") for i in range(len(r))):
                # ⚠ `m` DEGIL: olcu nesnesi o adda ve golgelenirse satirin geri
                # kalani sessizce sayiya doner.
                my = ry + rh / 2
                sc.poly([(x0 + 10, my - 4.5), (x0 + 18, my), (x0 + 10, my + 4.5)],
                        fill=pal.muted)
            sc.line([(x0 + exp_w, ry), (x0 + exp_w, ry + rh)], stroke=pal.line, sw=1)

        cx = x0 + exp_w
        for c, cw, i in zip(cols, widths, idxs):
            _scene_cell(sc, r[i] if i < len(r) else None, c, cx, ry, cw, rh, pal, m)
            sc.line([(cx + cw, ry), (cx + cw, ry + rh)], stroke=pal.line, sw=1)
            cx += cw
        sc.line([(x0, ry + rh), (x0 + table_w, ry + rh)], stroke=pal.line, sw=1)
        ry += rh

        if details[ri]:
            dh = detail_h[ri]
            sc.rect(x0, ry, table_w, dh, fill=pal.panel)
            _draw_detail(sc, details[ri], x0, ry, table_w, pal, m)
            sc.line([(x0, ry + dh), (x0 + table_w, ry + dh)], stroke=pal.line, sw=1)
            ry += dh

    if foot:
        sc.line([(x0, ry + 1), (x0 + table_w, ry + 1)], stroke=pal.line, sw=1)
        sc.text(x0, ry + m.small + 7, _fit(foot, m.small, False, table_w),
                size=m.small, fill=pal.muted)
    return sc


def _table_footer(table: dict, cols: list[dict], rows: list,
                  truncated: int, max_rows: int | None) -> str:
    """Tablonun altında duran tek satırlık künye.

    Tür, şekil ve **gizli sütun sayısı** buraya yazılır; başlıkta yalnızca
    veri kümesi ve belge adı kalır. Aynı sayıyı iki yerde göstermemek için.
    """
    parts = [table.get("kind_label", "")]
    if table.get("transposed"):
        parts.append(I18N.t("foot.shape_transposed", rows=len(rows),
                            cols=max(0, len(cols) - 1)))
    else:
        parts.append(I18N.t("foot.shape", rows=len(rows), cols=len(cols)))

    hidden = len(table["columns"]) - len(cols)
    if hidden > 0:
        parts.append(I18N.t("foot.hidden", n=hidden))
    if truncated:
        parts.append(I18N.t("foot.truncated", n=truncated, limit=max_rows))
    if table.get("variant"):
        parts.append(I18N.t("foot.variant", name=table["variant"]))
    return " · ".join(p for p in parts if p)


def _scene_cell(sc: Scene, cell, col, cx: float, ry: float, cw: float, row_h: float,
                pal: TH.Palette, m: TH.Metrics) -> None:
    """⚠ Palet ve olculer PARAMETRE olarak gelir, burada okunmaz.

    "Cizim aninda oku" kurali sahne basina bir okuma demek, HUCRE basina degil:
    300 satir × 15 sutunda kendi okumasi 4500 gereksiz nesne uretiyordu. Ayrica
    imza artik bir sahnenin tek bir tema anlik goruntusunden cizildigini de
    soyluyor — konvansiyondan degil.
    """
    if not cell or cell.get("k") == F.C_MISSING:
        # Ekranda ayni ton `--missing`; ustune bir de tarama biniyor (CSS
        # `td.missing`). Duz ton iki tarafta da AYNI degeri tasimali.
        sc.rect(cx, ry, cw, row_h, fill=pal.missing)
        return

    kind, text = cell.get("k"), cell.get("d", "")

    if kind == F.C_IMAGE:
        if cell.get("thumb"):
            sc.image(cx + CELL_PAD / 2, ry + 4, cw - CELL_PAD, row_h - 8, cell["thumb"],
                     hover=f'{cell.get("src", "")} · {cell.get("iw", "?")}×{cell.get("ih", "?")}')
        else:
            sc.text(cx + CELL_PAD, _baseline(ry, row_h, m.small),
                    _fit(text, m.small, False, cw - CELL_PAD * 2),
                    size=m.small, fill=pal.muted)
        return

    if kind in (F.C_RECORDS, F.C_OBJECT):
        label = _fit(text, m.small, False, cw - CELL_PAD * 2 - 8)
        w = _text_w(_MEASURE, label, _font(m.small)) + 12
        # Rozetin uzerine gelince ic tablonun ozeti gorunur.
        sub = cell.get("sub") or {}
        tip = text
        if sub.get("columns"):
            tip += " · " + ", ".join(c["label"] for c in sub["columns"][:6])
        pill = m.small + 6
        sc.rect(cx + CELL_PAD, ry + (row_h - pill) / 2, w, pill,
                fill=pal.accent_dim, r=pill / 2, hover=tip)
        sc.text(cx + CELL_PAD + 6, _baseline(ry, row_h, m.small), label,
                size=m.small, fill=pal.text_2)
        return

    fill = pal.muted if text == F.EMPTY_DISPLAY else (
        pal.bool if text in ("true", "false") else pal.text)

    # Sarilan sutun: metin hucre icinde alt satirlara yayilir (ekranla ayni).
    if col.get("wrap"):
        lines = _wrap_lines(text, m.font, cw - CELL_PAD * 2)
        ty = ry + _wrap_pad(m) + m.font
        for ln in lines:
            sc.text(cx + CELL_PAD, ty, ln, size=m.font, fill=fill)
            ty += m.wrap_line_h
        if _oneline(text) != " ".join(lines):
            sc.rect(cx, ry, cw, row_h, fill=None, hover=_oneline(text)[:400])
        return

    label = _fit(text, m.font, False, cw - CELL_PAD * 2)

    # Metin kisaldiysa tam hali hover'da gorunur; SVG'de veri kaybolmaz.
    if label != _oneline(text):
        sc.rect(cx, ry, cw, row_h, fill=None, hover=_oneline(text)[:400])

    if col.get("numeric"):
        sc.text(cx + cw - CELL_PAD, _baseline(ry, row_h, m.font), label,
                size=m.font, fill=fill, anchor="end")
    else:
        sc.text(cx + CELL_PAD, _baseline(ry, row_h, m.font), label,
                size=m.font, fill=fill)


def render_table(table: dict, view: dict | None = None,
                 row_order: list[int] | None = None, scale: int = 2, *,
                 expanded: set[int] | None = None,
                 max_rows: int | None = MAX_ROWS_DEFAULT,
                 title: str | None = None, subtitle: str | None = None) -> bytes:
    return scene_to_png(
        table_scene(table, view, row_order, max_rows, title, subtitle, expanded), scale)
