"""JSONtoText — belgeyi ve tablolari okunabilir metne cevirir.

Dort cikti bicimi (`[D-05]`, `AK-02`):
  report   Belgenin tamami: her veri kumesi bir Markdown tablosu + uyarilar
  outline  Ham JSON yapisinin girintili agac dokumu
  table    Yalnizca acik olan tablo, Markdown
  csv      Yalnizca acik olan tablo, CSV

Ekranla birebir olmasi icin satir sirasi arayuzden `row_order` olarak gelir;
siralama/filtre mantigi burada tekrarlanmaz.
"""

from __future__ import annotations

import csv
import io
from string import Template
from typing import Any

from . import discover as D
from . import flatten as F
from . import i18n as I18N
from . import theme as TH

MAX_CELL = 300          # tek hucrede gosterilecek en fazla karakter
REPORT_ROW_CAP = 200    # belge raporunda tablo basina satir siniri
OUTLINE_MAX_DEPTH = 8
OUTLINE_MAX_ITEMS = 60
OUTLINE_MAX_STR = 120

KINDS = ("report", "outline", "table", "csv", "html")


# --- Hucre metni -----------------------------------------------------------

def cell_text(cell: dict | None, null_as: str | None = None) -> str:
    """Bir hucreyi duz metne cevirir.

    Ic ice tablo tasiyan hucrelerde ekranda yalnizca "2 oge" rozeti gorunur;
    metin ciktisinda veri kaybolmasin diye alt tablo `alan=deger` ciftleri
    halinde aciklanir.

    `null_as` verilirse bos deger yer tutucusu ("—") onunla degistirilir; CSV
    gibi makine tarafindan okunacak ciktilarda bos hucre bos kalmalidir.
    """
    if not cell or cell.get("k") == F.C_MISSING:
        return ""

    text = cell.get("d", "")
    if null_as is not None and text == F.EMPTY_DISPLAY:
        return null_as
    sub = cell.get("sub")
    if sub and [c["key"] for c in sub["columns"]] == ["_key", "_value"]:
        # 11.2 — ic ice NESNE anahtar-deger alt tablosu olarak geliyor; "Anahtar"
        # ve "Deger" uygulamanin urettigi sutun adlari, belgenin degil. Cift
        # dogrudan `anahtar=deger` yazilir (`Anahtar=width, Deger=40` degil).
        pairs = [f"{row[0].get('d', '')}={row[1].get('d', '')}" for row in sub["rows"]
                 if len(row) > 1 and row[1].get("k") != F.C_MISSING]
        if pairs:
            text = ", ".join(pairs)
    elif sub:
        parts = []
        for row in sub["rows"]:
            pairs = [
                f"{c['label']}={row[i].get('d', '')}"
                for i, c in enumerate(sub["columns"])
                if i < len(row) and row[i].get("k") != F.C_MISSING and row[i].get("d")
            ]
            if pairs:
                parts.append(", ".join(pairs))
        if parts:
            text = " | ".join(parts)

    text = " ".join(text.split())          # satir sonlarini duzle
    if len(text) > MAX_CELL:
        text = text[: MAX_CELL - 1].rstrip() + "…"
    return text


def _md_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("|", "\\|")


# --- Gorunur sutun / satir secimi -----------------------------------------

def _select(table: dict, view: dict | None, row_order: list[int] | None):
    cols = table["columns"]
    if view:
        hidden = set(view.get("hidden") or ())
        order = [k for k in (view.get("order") or []) if k not in hidden]
        by_key = {c["key"]: c for c in cols}
        cols = [by_key[k] for k in order if k in by_key] or table["columns"]

    idxs = [table["columns"].index(c) for c in cols]
    all_rows = table["rows"]
    # `order` satirlarin KAYNAK indeksleridir; HTML ciktisi acik satirlari
    # bununla esliyor (`expanded` de kaynak indeks tasir).
    order = (list(range(len(all_rows))) if row_order is None
             else [i for i in row_order if 0 <= i < len(all_rows)])
    return cols, idxs, [all_rows[i] for i in order], order


# --- Tablo ciktilari -------------------------------------------------------

def table_markdown(table: dict, view: dict | None = None,
                   row_order: list[int] | None = None,
                   row_cap: int | None = None) -> str:
    cols, idxs, rows, _ = _select(table, view, row_order)
    if not cols:
        return I18N.t("out.no_columns")

    out = ["| " + " | ".join(_md_escape(c["label"]) for c in cols) + " |"]
    out.append("|" + "|".join("---:" if c.get("numeric") else "---" for c in cols) + "|")

    shown = rows if row_cap is None else rows[:row_cap]
    for r in shown:
        out.append("| " + " | ".join(
            _md_escape(cell_text(r[i] if i < len(r) else None)) for i in idxs) + " |")

    if row_cap is not None and len(rows) > row_cap:
        out.append("\n" + I18N.t("out.more_rows",
                                 n=len(rows) - row_cap, cap=row_cap))
    return "\n".join(out)


# --- HTML tablo (K-18) -----------------------------------------------------
# Gomulu SVG degil, GERCEK bir HTML tablosu: metin secilebilir ve kopyalanabilir.
# Tek dosya, gomulu CSS, disariya hicbir istek yok — e-postayla gonderilebilir.

# ⚠ Sablon `string.Template` ($ad) ile doldurulur, f-string ile DEGIL: metin
# bastan sona CSS suslu parantezi iceriyor ve f-string'de her birini ikiye
# katlamak gerekirdi — kopyalanan bir CSS parcasi sessizce bozulurdu.
_HTML_CSS = Template("""\
:root { color-scheme: $scheme }
body { margin:0; padding:24px; background:$bg; color:$text;
       font:${size}px/1.5 $family }
h1 { margin:0 0 4px; font-size:18px }
.doc { color:$muted; font-size:12px; margin-bottom:14px }
table { border-collapse:collapse; background:$panel }
th,td { border:1px solid $line; padding:6px 10px; text-align:left;
        vertical-align:top; max-width:420px }
th { background:$panel2; font-weight:600; white-space:nowrap; position:sticky; top:0 }
td.num { text-align:right; font-variant-numeric:tabular-nums }
td.wrap { white-space:normal; overflow-wrap:anywhere }
td.plain { white-space:nowrap }
tr:nth-child(even) td { background:$rowalt }
.null { color:$muted }
.bool { color:$bool }
.foot { color:$muted; font-size:11.5px; margin-top:10px }
tr.detail td { background:$panel; border-top:0; max-width:none }
details { margin:2px 0 }
summary { cursor:pointer; color:$muted; font-size:.92em }
.sublabel { color:$muted; font-size:.86em; margin:8px 0 3px }
table.sub { background:$panel2; font-size:.92em }
table.sub th, table.sub td { padding:4px 8px; position:static }
""")


def _html_css() -> str:
    """Gomulu CSS'i gecerli paletten uretir.

    ⚠ `color-scheme` de temayi izlemeli: tarayici kaydirma cubugunu ve form
    ogelerini ona gore boyar. Sabit `dark` kalsaydi acik temali bir ciktida
    kenardaki kaydirma cubugu koyu kalirdi.

    ⚠ Yazi tipi ailesi ve punto da ayardan gelir. Palet gocu yapilirken burasi
    `13px "Segoe UI"` sabitinde kalmisti: HTML, kullanicinin secimini yok sayan
    TEK cikti arka ucuydu — SVG (`vector.to_svg`) ve PDF ikisini de okuyor.
    """
    pal = TH.active()
    return _HTML_CSS.substitute(
        scheme=TH.get_theme(), bg=pal.bg, text=pal.text, muted=pal.muted,
        panel=pal.panel, panel2=pal.panel_2, line=pal.line,
        rowalt=pal.row_alt, bool=pal.bool,
        family=TH.font_css(), size=TH.metrics().font)


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def table_html(table: dict, view: dict | None = None,
               row_order: list[int] | None = None,
               title: str = "", source: str = "",
               expanded: set[int] | None = None) -> str:
    """Açık tabloyu tek dosyalık, paylaşılabilir HTML olarak yazar.

    Sarılan sütunlar burada da sarılır (`wrap` bayrağı) — ekran, çizim ve HTML
    aynı sütunları sarılmış kabul eder.

    ⚠ **İç içe hücre burada düzleştirilmez, GERÇEK bir iç tablo olur.** MD ve
    CSV'de `alan=değer` düzleştirmesi kalıyor (orada yapı yok, veriyi
    kaybetmemenin tek yolu o); HTML yapı taşıyabildiği için düzleştirme yanlış
    tercihti — hücreyi taşırıyor ve "bu sütun ne?" sorusunu doğuruyordu.

    Ekranda **açık bırakılan** satır burada da açık gelir (`<details open>`);
    kapalı olanlar da yazılır ama kapalı — hiçbir durumda veri kaybolmaz ve
    okuyucu kendi açabilir. `<details>` yerli HTML'dir: betik yok, tek dosya
    korunur (`K-18`).
    """
    cols, idxs, rows, order = _select(table, view, row_order)
    open_rows = set(expanded or ())
    head = "".join(f"<th>{_esc(c['label'])}</th>" for c in cols)

    body = []
    for src_i, r in zip(order, rows):
        cells, subs = [], []
        for c, i in zip(cols, idxs):
            cell = r[i] if i < len(r) else None
            sub = cell.get("sub") if cell else None
            # Ic ice hucrede ANA satir ekrandaki gibi ozet rozeti gosterir
            # (`2 oge`); ayrinti asagidaki acilir satirda durur.
            txt = cell.get("d", "") if sub else cell_text(cell)
            klass = "wrap" if c.get("wrap") else "plain"
            if c.get("numeric"):
                klass += " num"
            if txt == F.EMPTY_DISPLAY:
                klass += " null"
            elif txt in ("true", "false"):
                klass += " bool"
            cells.append(f'<td class="{klass}">{_esc(txt)}</td>')
            if sub:
                subs.append((c["label"], sub))
        body.append("<tr>" + "".join(cells) + "</tr>")
        if subs:
            body.append(_detail_row(subs, len(cols), src_i in open_rows))

    hidden = len(table["columns"]) - len(cols)
    foot = [table.get("kind_label", ""),
            I18N.t("foot.shape", rows=len(rows), cols=len(cols))]
    if hidden > 0:
        foot.append(I18N.t("foot.hidden", n=hidden))

    return (
        f"<!doctype html>\n<html lang=\"{I18N.get_lang()}\"><head><meta charset=\"utf-8\">\n"
        f"<title>{_esc(title or table.get('label', 'Tablo'))}</title>\n"
        f"<style>{_html_css()}</style></head>\n<body>\n"
        f"<h1>{_esc(title or table.get('label', 'Tablo'))}</h1>\n"
        f'<div class="doc">{_esc(source)}</div>\n'
        f"<table><thead><tr>{head}</tr></thead>\n<tbody>\n"
        + "\n".join(body)
        + f'\n</tbody></table>\n<div class="foot">{_esc(" · ".join(p for p in foot if p))}'
          "</div>\n</body></html>\n"
    )


def _detail_row(subs: list[tuple[str, dict]], span: int, is_open: bool) -> str:
    """Ic ice hucrelerin acilir ayrinti satiri (`<details>`).

    Her ic ice hucre kendi basligiyla ayri bir tablo olur; ekrandaki ayrinti
    satirinin karsiligi. Satir tablonun tamamini kapsar (`colspan`), yani ana
    tablonun sutun hizasi bozulmaz.
    """
    parts = []
    for label, sub in subs:
        cols = sub["columns"]
        head = "".join(f"<th>{_esc(c['label'])}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(
                f"<td>{_esc(cell_text(row[i] if i < len(row) else None))}</td>"
                for i in range(len(cols))) + "</tr>"
            for row in sub["rows"])
        parts.append(f'<div class="sublabel">{_esc(label)}</div>'
                     f'<table class="sub"><thead><tr>{head}</tr></thead>'
                     f"<tbody>{body}</tbody></table>")
    return (f'<tr class="detail"><td colspan="{span}">'
            f'<details{" open" if is_open else ""}>'
            f'<summary>{_esc(I18N.t("cell.nested"))}</summary>'
            f'{"".join(parts)}</details></td></tr>')


def table_csv(table: dict, view: dict | None = None,
              row_order: list[int] | None = None, delimiter: str = ",") -> str:
    cols, idxs, rows, _ = _select(table, view, row_order)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow([c["label"] for c in cols])
    for r in rows:
        w.writerow([cell_text(r[i] if i < len(r) else None, null_as="") for i in idxs])
    return buf.getvalue()


# --- Belge raporu ----------------------------------------------------------

def document_markdown(name: str, root: Any, datasets: list[D.Dataset]) -> str:
    out = [f"# {name}", ""]
    out.append(I18N.t("out.report_sub", n=len(datasets)))
    out.append("")

    out.append(I18N.t("out.index_head"))
    out.append("|---|---|---|---|")
    for i, ds in enumerate(datasets, 1):
        out.append(f"| {i} | `{_md_escape(ds.id)}` | {ds.kind_label} | {ds.row_count} × {ds.col_count} |")
    out.append("")

    for i, ds in enumerate(datasets, 1):
        out.append(f"## {i}. {ds.label_text}")
        out.append("")
        out.append(f"`{ds.id}` · {ds.kind_label} · {ds.row_count} × {ds.col_count}")
        out.append("")
        for n in ds.note_texts:
            out.append(f"> {n}")
        if ds.notes:
            out.append("")

        try:
            table = F.build_table(root, ds)
            out.append(table_markdown(table, row_cap=REPORT_ROW_CAP))
        except Exception as exc:
            out.append(I18N.t("out.table_failed",
                              error=f"{type(exc).__name__}: {exc}"))
        out.append("")

        for v in ds.variants:
            out.append(I18N.t("out.variant_head", label=v.label))
            out.append("")
            out.append(I18N.t("out.variant_sub",
                              rows=v.row_count, cols=v.col_count))
            out.append("")
            try:
                vt = F.build_table(root, ds, v.id)
                out.append(table_markdown(vt, row_cap=REPORT_ROW_CAP))
            except Exception as exc:
                out.append(I18N.t("out.table_failed",
                                  error=f"{type(exc).__name__}: {exc}"))
            out.append("")

    return "\n".join(out)


# --- Girintili anahat ------------------------------------------------------

def _scalar_preview(v: Any) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        s = " ".join(v.split())
        if len(s) > OUTLINE_MAX_STR:
            s = s[: OUTLINE_MAX_STR - 1] + "…"
        return f'"{s}"'
    return str(v)


def _shape(v: Any) -> str:
    if isinstance(v, dict):
        return f"{{{len(v)} alan}}"
    if isinstance(v, list):
        if v and all(isinstance(x, dict) for x in v):
            return I18N.t("out.records", n=len(v))
        return I18N.t("out.items", n=len(v))
    return ""


def _walk_outline(node: Any, prefix: str, lines: list[str], depth: int) -> None:
    if depth >= OUTLINE_MAX_DEPTH:
        lines.append(prefix + "└─ …")
        return

    if isinstance(node, dict):
        items: list[tuple[str, Any]] = list(node.items())
    elif isinstance(node, list):
        items = [(f"[{i}]", v) for i, v in enumerate(node)]
    else:
        return

    truncated = len(items) > OUTLINE_MAX_ITEMS
    shown = items[:OUTLINE_MAX_ITEMS]

    for i, (key, val) in enumerate(shown):
        last = (i == len(shown) - 1) and not truncated
        branch = "└─ " if last else "├─ "
        pad = "   " if last else "│  "

        if isinstance(val, (dict, list)):
            lines.append(f"{prefix}{branch}{key}  {_shape(val)}")
            _walk_outline(val, prefix + pad, lines, depth + 1)
        else:
            lines.append(f"{prefix}{branch}{key}: {_scalar_preview(val)}")

    if truncated:
        lines.append(prefix + "└─ "
                     + I18N.t("out.more_items", n=len(items) - OUTLINE_MAX_ITEMS))


def outline(name: str, root: Any) -> str:
    lines = [f"{name}  {_shape(root)}"]
    _walk_outline(root, "", lines, 0)
    return "\n".join(lines)
