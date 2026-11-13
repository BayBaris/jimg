"""Grafik cizimi: sahne, eksenler ve pasta.

Veri tarafi burada DEGIL `chart_data`'dadir — bu modul yalnizca gelen
(etiket, deger) ciftlerini geometriye cevirir. Ayrim kasitli: sutun listesi
isteyen arayuz cagrilari cizim yigini hic yuklemesin.

Grafigin altinda TEK SATIRLIK aciklama vardir (`Scene.meta.explain`) ve sahnenin
parcasidir — PNG, SVG ve PDF ciktilarinin hepsinde gorunur. Eski `_scene_summary`
serit Faz 7.4b'de kaldirildi: aciklama satiriyla ust uste biniyordu.

Pasta dilimleri COKLU-KENAR olarak uretilir; SVG ile PDF birebir ayni sekli alsin.
"""

from __future__ import annotations

import math

from . import i18n as I18N
from . import theme as TH
from .chart_data import UNIT_ROWS, _aggregate, numeric_distribution
from .draw import PAD, _fit, _fmt_num, scene_to_png
from .vector import Scene

# ⚠ **Tuval SABITTIR, yalnizca yazilar puntoyla buyur** (`9.4.5.2`). Grafik bir
# tabloya degil kendi cercevesine ciziliyor; tuvali de buyutmek ayni veriyi
# daha buyuk bir PNG olarak uretirdi ve `AK-14`'un sikayet ettigi boyutu
# kotulestirirdi. Bunun bedeli: etiketler icin ayrilan yer punto buyudukce
# GORECELI olarak daralir, bu yuzden kirpma KARAKTER degil PIKSEL olcusuyle
# yapilir (`_fit`) — `_clip` kullanilsaydi 16 puntoda gosterge tuvali tasardi.
CHART_W = 720
CHART_H = 480          # alt kisimda aciklama satirina yer birakir
PIE_GAP_PX = 3          # dilimler arasi bosluk (kullanici istegi: 2-5 px)
LEGEND_ROWS = 14        # gostergede en fazla kac kategori

# Kategorileri ayiran dongusel palet `theme.SERIES`tedir ve CSS'te YOKTUR:
# grafik ekranda da Python'un urettigi SVG'dir, tarayici bu renkleri hic
# gormez. Sira iki temada da ayni — koyudan aciga gecen kullanici serilerin
# yer degistirdigini gormemeli.


def chart_scene(table: dict, cat_key: str, num_key: str | None = None, chart: str = "bar",
                row_order: list[int] | None = None, title: str | None = None,
                agg: str = "sum", source: str | None = None) -> Scene:
    """Grafigin geometrisini BIR KEZ uretir; PNG/SVG/PDF ayni sahneyi kullanir.

    `title` veri kumesinin adidir ve ORTALI yazilir; `source` (belge adi) onun
    altinda kucuk bir alt bilgi olarak durur.
    """
    pal, m = TH.active(), TH.metrics()
    label_of = {c["key"]: c["label"] for c in table["columns"]}

    if cat_key:
        data, stats = _aggregate(table, cat_key, num_key, agg, row_order)
        cat_label = label_of[cat_key]
        # "Adet" olcumu sayisal sutun kullanmaz; Y ekseni olcumun kendisidir.
        y_label = (I18N.t("agg.count.label") if agg == "count" else
                   I18N.t("chart.axis_measure", name=label_of[num_key],
                          agg=I18N.lower(I18N.t(f"agg.{agg}.label"))))
        explain = I18N.t("chart.explain_breakdown", rows=stats["rows"],
                         cat=cat_label, cats=stats["cats"])
    else:
        # Kirilimsiz mod: tek sayisal sutunun kendi dagilimi (Faz 7.4).
        data, stats, unit = numeric_distribution(table, num_key, row_order)
        by_row = unit == UNIT_ROWS
        cat_label = (I18N.t("chart.axis_records") if by_row
                     else I18N.t("chart.axis_range", name=label_of[num_key]))
        y_label = label_of[num_key] if by_row else I18N.t("agg.count.label")
        explain = (I18N.t("chart.explain_rows", rows=stats["rows"], name=label_of[num_key])
                   if by_row else
                   I18N.t("chart.explain_bins", rows=stats["rows"],
                          name=label_of[num_key], bins=stats["cats"]))

    sc = Scene(CHART_W, CHART_H, pal.bg)
    sc.meta = dict(stats, agg=agg, agg_label=I18N.t(f"agg.{agg}.label"),
                   x=cat_label, y=y_label, explain=explain)

    sc.text(CHART_W / 2, PAD + m.title, title or f"{y_label} / {cat_label}",
            size=m.title, fill=pal.text, bold=True, anchor="middle")
    if source:
        # Alt baslik ofseti uc cizicide de AYNI: `m.title * 2`.
        sc.text(CHART_W / 2, PAD + m.title * 2, source,
                size=m.small, fill=pal.muted, anchor="middle")

    # Olcum SOL USTTE: altbilgideki ozet serit kaldirilinca (kullanici geri
    # bildirimi) bu bilgi bir yere tasinmaliydi ve basligin yanina degil,
    # cizimin kendi kosesine ait.
    note = (I18N.t("chart.note_agg", label=I18N.t(f"agg.{agg}.label")) if cat_key
            else I18N.t("chart.note_distribution"))
    if stats.get("hidden"):
        note += I18N.t("chart.note_hidden", n=stats["hidden"])
    sc.text(PAD, PAD + m.title, note, size=m.small, fill=pal.muted)

    if not data:
        sc.text(CHART_W / 2, PAD + 70, I18N.t("chart.no_data"),
                size=m.font, fill=pal.muted, anchor="middle")
        return sc

    # Palet ve olculer BIR KEZ okunup geciriliyor: sahne tek bir tema/punto
    # anlik goruntusunden cizilir, alt cizerler yeniden okumaz.
    total = sum(v for _, v in data)
    if chart == "pie":
        _scene_pie(sc, data, total, pal, m)
    else:
        _scene_xy(sc, data, total, cat_label, y_label, pal, m, line=(chart == "line"))

    # Tek cumlelik aciklama: kullanici ne gordugunu okumadan anlamali.
    sc.text(CHART_W / 2, CHART_H - 14, _fit(explain, m.small, False, CHART_W - PAD * 2),
            size=m.small, fill=pal.muted, anchor="middle")
    return sc


def _tip(label: str, v: float, total: float) -> str:
    # ⚠ Ondalik ayrac ve yuzde isaretinin YERI dile bagli: `%12,3` (tr) ile
    # `12.3%` (en). Once ikisi de Turkce sabitti ve `_fmt_num` dili izlerken
    # hemen yanindaki yuzde izlemiyordu.
    pct = f"{(abs(v) / total * 100 if total else 0):.1f}"
    if I18N.get_lang() == "tr":
        return f"{label} · {_fmt_num(v)} · %{pct.replace('.', ',')}"
    return f"{label} · {_fmt_num(v)} · {pct}%"


def _scene_xy(sc: Scene, data, total: float, cat_label: str, num_label: str,
              pal: TH.Palette, m: TH.Metrics, line: bool) -> None:
    colors = TH.series()
    left, right = PAD + 64, CHART_W - PAD
    # Ustte baslik + kaynak, altta yalnizca tek satirlik aciklama kaldi
    # (ozet serit kaldirildi) — cizim alani buyudu.
    top, bottom = PAD + 58, CHART_H - PAD - 56
    plot_w, plot_h = right - left, bottom - top

    vmax = max(v for _, v in data)
    vmin = min(0.0, min(v for _, v in data))
    span = (vmax - vmin) or 1.0
    y_of = lambda v: bottom - (v - vmin) / span * plot_h            # noqa: E731

    for i in range(5):
        gy = top + plot_h * i / 4
        sc.line([(left, gy), (right, gy)], stroke=pal.line, sw=1)
        sc.text(left - 8, gy + 4, _fmt_num(vmax - span * i / 4),
                size=m.small, fill=pal.muted, anchor="end")

    n = len(data)
    slot = plot_w / n

    if line:
        pts = [(left + slot * (i + 0.5), y_of(v)) for i, (_, v) in enumerate(data)]
        sc.line(pts, stroke=pal.accent, sw=2)
        for (x, y), (label, v) in zip(pts, data):
            sc.rect(x - 4, y - 4, 8, 8, fill=pal.accent, r=4, hover=_tip(label, v, total))
    else:
        bw = max(6.0, slot * 0.62)
        for i, (label, v) in enumerate(data):
            cx = left + slot * (i + 0.5)
            y0, y1 = sorted((y_of(v), y_of(0)))
            sc.rect(cx - bw / 2, y0, bw, max(1.0, y1 - y0),
                    fill=colors[i % len(colors)],
                    hover=_tip(label, v, total))

    sc.line([(left, y_of(0)), (right, y_of(0))], stroke=pal.muted, sw=1)

    step = max(1, math.ceil(n / max(1, int(plot_w / 56))))
    for i, (label, _) in enumerate(data):
        if i % step:
            continue
        sc.text(left + slot * (i + 0.5), bottom + 18,
                _fit(label, m.small, False, slot * step),
                size=m.small, fill=pal.muted, anchor="middle")

    # Eksen adlari belgedeki sutun adlarindan gelir.
    sc.text((left + right) / 2, bottom + 40, cat_label,
            size=m.small, fill=pal.text, anchor="middle")
    sc.text(PAD + 14, (top + bottom) / 2, num_label, size=m.small, fill=pal.text,
            anchor="middle", rot=90)


def _scene_pie(sc: Scene, data, total: float, pal: TH.Palette, m: TH.Metrics) -> None:
    colors = TH.series()
    r = min(CHART_H - PAD * 2 - 130, 260) // 2
    cx, cy = PAD + 40 + r, PAD + 62 + r
    gap = min(4.0, math.degrees(PIE_GAP_PX / max(1.0, float(r))))

    start = -90.0
    for i, (label, v) in enumerate(data):
        sweep = abs(v) / total * 360.0 if total else 0.0
        a0, a1 = (start + gap / 2, start + sweep - gap / 2) if sweep > gap * 2 else (start, start + sweep)
        sc.slice(cx, cy, r, a0, a1, colors[i % len(colors)],
                 hover=_tip(label, v, total))
        start += sweep

    lx, ly = cx + r + 30, PAD + 62
    text_w = CHART_W - lx - PAD - 15
    for i, (label, v) in enumerate(data[:LEGEND_ROWS]):
        sc.rect(lx, ly + 3, 9, 9, fill=colors[i % len(colors)],
                hover=_tip(label, v, total))
        sc.text(lx + 15, ly + 11, _fit(_tip(label, v, total), m.small, False, text_w),
                size=m.small, fill=pal.text)
        ly += m.small + 7
    if len(data) > LEGEND_ROWS:
        # ⚠ Bu satir uzun sure ASCII Turkce kaldigi icin `check_py_strings`in
        # kor noktasindaydi: denetim Turkce KARAKTER ariyor, "kategori daha"da
        # yok. Gozle bulundu (`9.4.6`).
        sc.text(lx + 15, ly + 11, I18N.t("chart.legend_more", n=len(data) - LEGEND_ROWS),
                size=m.small, fill=pal.muted)


def render_chart(table: dict, cat_key: str, num_key: str | None = None, chart: str = "bar",
                 row_order: list[int] | None = None, scale: int = 2,
                 title: str | None = None, agg: str = "sum",
                 source: str | None = None) -> bytes:
    return scene_to_png(
        chart_scene(table, cat_key, num_key, chart, row_order, title, agg, source), scale)
