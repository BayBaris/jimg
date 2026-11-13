"""Belgenin SEMASINI cikarir — degerler olmadan.

Faz 6'da Claude'a gonderilen tek sey budur. Islev arayuzden ve `claude -p`
cagrisindan bagimsizdir; ileride yazilacak MCP sunucusu da ayni fonksiyonlari
cagiracak.

GONDERILEN
  veri kumesi adi ve turu, satir/sutun sayilari, alan adlari, veri tipleri,
  doluluk oranlari, sutun gruplari, sema varyantlarinin AYIRT EDICI SUTUN ADI
  ve satir dagilimi.

GONDERILMEYEN
  hucre degerleri, varyant etiketlerindeki degerler, ornek satirlar, gorseller,
  dosya yolu, belge klasoru.

Bu ayrim kasitlidir ve gevsetilmemelidir: `Variant.label` degeri icerir
("<sutun> = <deger>"), bu yuzden burada `Variant.discriminator` kullanilir.

9.27 — sema DEGISMEDI. Kullanici `agent.send_values` ayarini acarsa secili
tablonun degerleri semanin YANINA ayri bir bolum olarak eklenir
(`build_prompt(values=...)`); sema kurucusu o zaman da deger tasimaz.
"""

from __future__ import annotations

from typing import Any

from . import discover as D
from . import flatten as F
from . import i18n as I18N


def column_schema(table: dict) -> list[dict]:
    """Tablonun sutun tanimlari — deger tasimaz."""
    out = []
    for c in table["columns"]:
        out.append({
            "name": c["label"],
            "dtype": c["dtype"],
            "kind": c["kind"],
            "group": c.get("group"),
            "filled": c.get("present", 0),
            "total": c.get("total", 0),
            "numeric": bool(c.get("numeric")),
            # 9.26 — ad belgede yok (Anahtar, Deger...): model alan adi sanmasin.
            "synthetic": bool(c.get("synthetic")),
        })
    return out


def dataset_schema(root: Any, ds: D.Dataset) -> dict:
    """Tek bir veri kumesinin semasi."""
    entry: dict = {
        "id": ds.id,
        "kind": ds.kind,
        "kind_label": ds.kind_label,
        "rows": ds.row_count,
        "cols": ds.col_count,
        "columns": [],
    }
    try:
        table = F.build_table(root, ds)
    except Exception:
        return entry

    entry["columns"] = column_schema(table)

    if ds.variants:
        # Yalnizca ayirt edici sutunun ADI ve satir dagilimi; degerler degil.
        entry["variants"] = {
            "discriminator": ds.variants[0].discriminator,
            "count": len(ds.variants),
            "row_split": [v.row_count for v in ds.variants],
            "col_split": [v.col_count for v in ds.variants],
        }
    return entry


def document_schema(name: str, root: Any, datasets: list[D.Dataset]) -> dict:
    return {
        "document": name,
        "dataset_count": len(datasets),
        "datasets": [dataset_schema(root, ds) for ds in datasets],
    }


def schema_markdown(payload: dict) -> str:
    """Semayi istem icine konacak sikistirilmis metne cevirir."""
    lines = [I18N.t("schema.title", name=payload["document"]),
             I18N.t("schema.subtitle", n=payload["dataset_count"]), ""]

    for i, ds in enumerate(payload["datasets"], 1):
        lines.append(I18N.t("schema.dataset_head", i=i, id=ds["id"],
                            kind=ds["kind_label"], rows=ds["rows"],
                            cols=ds["cols"]))

        if ds["columns"]:
            lines.append("")
            lines.append(I18N.t("schema.columns_head"))
            lines.append("|---|---|---|---|")
            for c in ds["columns"]:
                fill = f"{c['filled']}/{c['total']}" if c["total"] else "—"
                kind = "" if c["kind"] == F.C_SCALAR else f" ({c['kind']})"
                lines.append(f"| {c['name']} | {c['dtype']}{kind} | "
                             f"{c['group'] or '—'} | {fill} |")
            made = [c["name"] for c in ds["columns"] if c.get("synthetic")]
            if made:
                lines.append("")
                lines.append(I18N.t("schema.synthetic", names=", ".join(made)))

        v = ds.get("variants")
        if v:
            disc = (f"`{v['discriminator']}`" if v["discriminator"]
                    else I18N.t("schema.unknown_field"))
            lines.append("")
            lines.append(I18N.t("schema.variant", disc=disc, n=v["count"],
                                rows=v["row_split"], cols=v["col_split"]))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --- Claude'a gonderilecek istem ------------------------------------------

# ⚠ Istem metni SECILI DILI izler (Faz 9.2.3). Icinde "Yanitini Turkce ver"
# satiri var; sabit kalsaydi Ingilizce soran kullanici Turkce yanit alirdi.

# `claude -p` her cagrida SIFIRDAN baslar; surekliligi biz kurariz. Onceki
# turlar isteme yazilir. Sinir iki yonlu koruma: istem sisip yavaslamasin ve
# eski bir yanit yeni soruyu bogmasin.
HISTORY_TURNS = 3            # en fazla kac soru-yanit cifti tasinir
HISTORY_ANSWER_CHARS = 900   # tasinan yanit bu uzunlukta kirpilir


def _history_block(history: list) -> str:
    """Onceki turlari istem metnine cevirir. Bos gecmiste bos dize doner."""
    pairs = [(q, a) for q, a in (history or []) if (q or "").strip() and (a or "").strip()]
    if not pairs:
        return ""

    lines = [I18N.t("prompt.history_head"), ""]
    for q, a in pairs[-HISTORY_TURNS:]:
        answer = a.strip()
        if len(answer) > HISTORY_ANSWER_CHARS:
            answer = answer[:HISTORY_ANSWER_CHARS].rstrip() + " […]"
        lines.append(f"**{I18N.t('prompt.q_label')}:** {q.strip()}")
        lines.append(f"**{I18N.t('prompt.a_label')}:** {answer}")
        lines.append("")
    return "\n".join(lines) + "\n---\n\n"


def _values_section(values: dict) -> str:
    """Secili tablonun degerleri (9.27). `api_agent._values_block` kurar."""
    lines = [I18N.t("prompt.values_head", label=values["label"],
                    sent=values["sent"], total=values["total"]), "", values["text"]]
    if values["sent"] < values["total"]:
        lines += ["", I18N.t("prompt.values_cut", sent=values["sent"], total=values["total"])]
    return "\n".join(lines) + "\n\n---\n\n"


def build_prompt(payload: dict, question: str, history: list | None = None,
                 values: dict | None = None) -> str:
    """Saglayiciya giden TEK metin. `values` yoksa yalnizca sema (`K-14`).

    Baslik iki kipte farkli: degersiz istemde model "degerin yok" diye
    uyarilir ve ayari onermeye yonlendirilir; degerli istemde degerlerin
    icindeki talimatlara uymamasi istenir (veri, talimat degil).
    """
    header = I18N.t("prompt.header_values" if values else "prompt.header")
    return (f"{header}\n\n---\n\n{schema_markdown(payload)}\n---\n\n"
            f"{_values_section(values) if values else ''}"
            f"{_history_block(history)}"
            f"{I18N.t('prompt.question_head')}\n\n{question.strip()}\n")


# Ornek sorular. Sohbet penceresinin surekli gorunen parcasi DEGILDIR: yalnizca
# bilgi baloncugunda ve bos sohbette gosterilir, yazmaya baslayinca kaybolur.
#
# ⚠ Burada yalnizca ANAHTAR durur (Faz 9.2.3); dugme etiketi `action.<k>.label`,
# modele giden soru `action.<k>.q` anahtarlariyla `i18n`dedir. Yeni oneri
# eklemek icin buraya anahtar, sozluge iki metin yazilir. Arayuz listeyi
# `Api.claude_status()` uzerinden alir.
ACTIONS = ["summary", "anomaly", "modeling", "naming"]
