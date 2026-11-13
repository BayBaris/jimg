"""`Api`nin grafik yuzu: sutun rolleri ve etkilesimli SVG.

Iki metot, iki ayri maliyet sinifi:
  `chart_columns` — yalnizca `chart_data`; Pillow'a DOKUNMAZ, arayuz her veri
                    kumesi acilisinda cagiriyor
  `chart_svg`     — `img_chart` gerekir; ice aktarma metodun ICINDE (Faz 8.6)
"""

from __future__ import annotations

import traceback

from . import chart_data as CD
from . import i18n as I18N
from . import vector as VEC


def _chart_error(cat: str | None, num: str | None, agg: str) -> str | None:
    """Grafik secimi tutarli mi? Iki mod var (Faz 7.4).

    kirilim  — bir kategorik sutun; olcum `count` degilse sayisal sutun da ister
    dagilim  — kirilim YOK, yalnizca sayisal sutun (histogram / sirali cubuk)
    """
    if not cat and not num:
        return I18N.t("err.pick_breakdown_or_measure")
    if cat and agg != "count" and not num:
        return I18N.t("err.agg_needs_measure")
    return None


class ChartMixin:
    """Grafik sutun rolleri ve SVG uretimi."""

    def chart_columns(self, doc_id: str, ds_id: str, variant_id: str | None = None) -> dict:
        """Grafik icin sutun ROLLERI ve otomatik oneriler (Faz 7.4).

        Eski surum tum skaler sutunlari kategori olarak sunuyordu; serbest
        metin de listeye giriyor ve anlamsiz grafikler uretilebiliyordu.
        Artik sutunlar role ayrilir (`CD.chart_roles`) ve arac tablodan
        kendi sorularini kurar (`CD.chart_suggestions`). Hicbir kural belgeye
        ozel degildir (`[D-06]`).

        Bu metot CIZIM YIGININI HIC YUKLEMEZ: `chart_data` Pillow'a dokunmaz
        (Faz 8.6). Arayuz her veri kumesi actiginda buraya ugruyor.
        """
        res = self.table(doc_id, ds_id, variant_id)
        if not res["ok"]:
            return res

        table = res["table"]
        roles = CD.chart_roles(table)
        return {
            "ok": True,
            "breakdown": roles["breakdown"],
            "measure": roles["measure"],
            "excluded": [c["label"] for c in roles["excluded"]],
            # `count` listeye girmez: kayit saymak Dagilim modunun isidir.
            # Etiketler CAGRI ANINDA cozulur — dil oturum icinde degisebilir.
            "aggs": [{"key": k, "label": I18N.t(f"agg.{k}.label"),
                      "note": I18N.t(f"agg.{k}.note")}
                     for k in CD.COMPARE_AGGS],
            "suggestions": CD.chart_suggestions(table),
            "rows": len(table["rows"]),
            "row_bar_limit": CD.ROW_BAR_LIMIT,
        }

    def chart_svg(self, doc_id: str, ds_id: str, variant_id: str | None = None,
                  row_order: list[int] | None = None, options: dict | None = None) -> dict:
        """Grafigi etkilesimli SVG olarak uretir (ciktinin temasinda, 9.19.3)."""
        with self._out_theme():
            return self._chart_svg(doc_id, ds_id, variant_id, row_order, options)

    def _chart_svg(self, doc_id: str, ds_id: str, variant_id: str | None,
                   row_order: list[int] | None, options: dict | None) -> dict:
        """Grafigi etkilesimli SVG olarak uretir (hover icin `data-tip` tasir).

        Ayni sahne PDF'e de basilabilir; geometri tek yerde uretilir.
        """
        from . import img_chart as ICH

        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
        if ds is None:
            return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}

        opt = options or {}
        cat, num = opt.get("category"), opt.get("numeric")
        agg = opt.get("agg") or "sum"
        if (err := _chart_error(cat, num, agg)):
            return {"ok": False, "error": err}

        try:
            table, _ = self._table_for_output(doc, ds, doc_id, ds_id, variant_id)
            scene = ICH.chart_scene(table, cat, num, opt.get("chart") or "bar", row_order,
                                    title=table["label"], agg=agg, source=doc["name"])
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        self._scene = scene
        name = f"{self._stem(doc)}-{self._safe_name(table['label'])}-grafik"
        return {"ok": True, "svg": VEC.to_svg(scene), "name": name,
                "stats": scene.meta}
