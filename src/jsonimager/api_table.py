"""`Api`nin tablo yuzu: tablo kurma, transpoze ve gorunum durumu.

Gorunum durumu (sutun sirasi/genisligi/gizliligi, siralama, transpoze) PYTHON
tarafinda saklanir — PNG ciktisi ekranda gorunenle birebir ayni olsun diye.
Anahtar `_key()` ile kurulur: `doc_id|ds_id|variant_id` + `|T` / `|N`.

⚠ Seyreklik IKI AYRI mekanizmayla ele alinir, karistirilmamali:
  satir bazli — sema varyantina bolunur (`discover.detect_variants`)
  sutun bazli — burada GIZLENIR (`_sparse_columns`)
Varyant bolme satirlari ayirir, gizleme yalnizca gorunumu sadelestirir.
"""

from __future__ import annotations

import traceback
from pathlib import Path

from . import flatten as F
from . import i18n as I18N

# Sutunun dolu sayilmasi icin gereken en az doluluk orani. Altinda kalanlar
# varsayilan olarak gizlenir — veri yetersizliginden okumayi zorlastiriyorlar.
COLUMN_FILL_THRESHOLD = 0.5
MIN_COLS_FOR_AUTOHIDE = 4    # 2-3 sutunlu tablolarda gizleme anlamsiz
MIN_VISIBLE_COLS = 2         # tablo hicbir zaman bosalmamali

# Uzun metin esikleri `flatten` icindedir: olcu tabloyla birlikte tasinir ve
# ekran ile cizim ayni sutunlari sarilmis kabul eder.


class TableMixin:
    """Tablo kurulumu ve gorunum durumu."""

    @staticmethod
    def _key(doc_id: str, ds_id: str, variant_id: str | None) -> str:
        """Gorunum anahtarinin govdesi. `|T`/`|N` eki cagiran yerde eklenir.

        `api_chart` ve `api_export` de bunu cagirir: ucu de ayni tabloyu ayni
        anahtarla bulmak zorunda, yoksa cikti ekrandan sapar.
        """
        return f"{doc_id}|{ds_id}|{variant_id or ''}"

    def _wrap(self) -> bool:
        """Uzun metin sarilsin mi (9.19.2). Ekran ve tum ciktilar ayni yaniti alir."""
        return self._settings.get("table", {}).get("wrap") is not False

    def _unhide_long(self) -> None:
        """Sarma kapaninca "uzun metin" gerekcesiyle gizlenen sutunlari geri acar.

        O sutunlar satiri uzattiklari icin gizlenmisti; tek satirda kirpilan
        metin satiri uzatmaz, gerekce ortadan kalkar. Kullanicinin kendi
        gizledikleri `longHidden`de olmadigi icin dokunulmaz.
        """
        for view in self._views.values():
            long_hidden = set(view.get("longHidden") or ())
            if long_hidden:
                view["hidden"] = [k for k in view.get("hidden") or () if k not in long_hidden]
                view["longHidden"] = []

    def table(self, doc_id: str, ds_id: str, variant_id: str | None = None) -> dict:
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
        if ds is None:
            return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}

        base = self._key(doc_id, ds_id, variant_id)
        transpose = base in self._transposed
        try:
            table = F.build_table(doc["root"], ds, variant_id, transpose,
                                  self._sources(doc), self._wrap())
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        if variant_id is None:
            table["label"] = self._ds_label(doc, ds)
        # 10.5.2 — son kayittan bu yana degisen hucreler (`api_edit`).
        table["edited"] = self._edited_cells(doc, ds, variant_id)
        # 10.6 — tablonun ADI degistiyse baslik da isaretlenir.
        table["name_edited"] = variant_id is None and tuple(ds.path) in self._renamed_paths(doc)
        # 10.7.2 — adi degisen sutunlar (baslik hucresi; transpozede alan adi).
        table["cols_edited"] = self._edited_cols(doc, ds)

        vkey = base + ("|T" if transpose else "|N")
        view = self._views.get(vkey) or self._default_view(table)
        self._views[vkey] = view
        return {"ok": True, "table": table, "view": view, "doc": doc["name"]}

    def set_transpose(self, doc_id: str, ds_id: str, variant_id: str | None, on: bool) -> dict:
        base = self._key(doc_id, ds_id, variant_id)
        if on:
            self._transposed.add(base)
        else:
            self._transposed.discard(base)
        return self.table(doc_id, ds_id, variant_id)

    # --- Varsayilan gorunum -----------------------------------------------

    @staticmethod
    def _sparse_columns(table: dict) -> list[str]:
        """Satirlarin yarisindan fazlasi bos olan sutunlarin anahtarlari.

        "Bos" = alan hic yok, null, veya bos metin. Bu sutunlar varsayilan
        olarak gizlenir; Sutunlar menusunden geri acilabilir.
        """
        cols, rows = table["columns"], table["rows"]
        if len(cols) < MIN_COLS_FOR_AUTOHIDE or not rows:
            return []

        hidden = []
        for i, c in enumerate(cols):
            filled = sum(
                1 for r in rows
                if i < len(r) and r[i]
                and r[i].get("k") != F.C_MISSING
                and r[i].get("d") not in ("", F.EMPTY_DISPLAY)
            )
            if filled / len(rows) < COLUMN_FILL_THRESHOLD:
                hidden.append(c["key"])

        # Her sey gizlenip tablo bosalmasin.
        if len(cols) - len(hidden) < MIN_VISIBLE_COLS:
            return []
        return hidden

    @staticmethod
    def _long_text_columns(table: dict) -> list[str]:
        """Hucreleri dort satiri asan METIN sutunlarinin anahtarlari.

        Sarilan sutunlarda satir yuksekligi metinle birlikte buyur; uc satiri
        asanlar tabloyu okunmaz hale getirdigi icin varsayilan olarak gizlenir,
        filtre menusunden geri acilir.

        Olcut GRUP DEGIL ICERIKTIR: "Metin" grubuna girmeyen bir siniflandirma
        ya da kimlik sutunu da uzun olabiliyor. Olcu de ortalama degil EN UZUN
        hucredir — satir yuksekligini o belirler.
        """
        cols, rows = table["columns"], table["rows"]
        if len(cols) < MIN_COLS_FOR_AUTOHIDE or not rows:
            return []

        return [c["key"] for i, c in enumerate(cols)
                if c.get("wrap") and F.longest_cell(table, i) > F.LONG_TEXT_CHARS]

    def _default_view(self, table: dict) -> dict:
        sparse = self._sparse_columns(table)
        # Iki gizleme sebebi AYRI listelerde tutulur: kullaniciya "neden
        # gizlendi" sorusunun dogru yaniti ve sutun ADLARI verilsin.
        long_text = [k for k in self._long_text_columns(table) if k not in sparse]
        if len(table["columns"]) - len(sparse) - len(long_text) >= MIN_VISIBLE_COLS:
            hidden = sparse + long_text
        else:
            hidden, long_text = sparse, []

        return {
            "order": [c["key"] for c in table["columns"]],
            "widths": {},
            "hidden": hidden,
            "autoHidden": sparse,
            "longHidden": long_text,
            "sort": None,
            # Normal modda ikinci baslik satiri, transpoze modda satir ayraci.
            # VARSAYILAN KAPALI: tablo once oldugu gibi gorunmeli, arac kendi
            # siniflandirmasini kullaniciya dayatmamali. Filtre menusunden acilir.
            "groups": False,
            # Transpoze modda alan satirlarini gruplarina gore dizer.
            "rowGroupSort": False,
        }

    def set_view(self, doc_id: str, ds_id: str, variant_id: str | None, view: dict,
                 transposed: bool | None = None) -> dict:
        """Gorunum durumunu yazar. `transposed` gorunumun KENDI kipidir.

        ⚠ Kip verilmezse o anki transpoze durumuna bakilir — ama arayuz
        gorunumu gecikmeli gonderiyor ve arada transpoze acilirsa normal
        gorunum transpoze anahtarina yazilir, tablo bos cizilirdi (10.7.2).
        Arayuz kipi acikca gonderir; eski davranis yalnizca geriye uyum icin.
        """
        base = self._key(doc_id, ds_id, variant_id)
        if transposed is None:
            transposed = base in self._transposed
        self._views[base + ("|T" if transposed else "|N")] = view
        return {"ok": True}

    def reset_view(self, doc_id: str, ds_id: str, variant_id: str | None = None) -> dict:
        base = self._key(doc_id, ds_id, variant_id)
        for suffix in ("|T", "|N"):
            self._views.pop(base + suffix, None)
        return self.table(doc_id, ds_id, variant_id)

    # --- Cizim/disa aktarim icin ortak yardimci ---------------------------

    def _table_for_output(self, doc: dict, ds, doc_id: str, ds_id: str,
                          variant_id: str | None) -> tuple[dict, dict | None]:
        """Cikti uretenlerin ihtiyaci: (tablo, gorunum).

        Uc cikti yolu da (metin · PNG · SVG) ayni tabloyu ayni gorunumle
        kurmak zorunda; kod uc yere kopyalanirsa biri gunun birinde sapar.
        """
        base = self._key(doc_id, ds_id, variant_id)
        transpose = base in self._transposed
        table = F.build_table(doc["root"], ds, variant_id, transpose,
                              self._sources(doc), self._wrap())
        view = self._views.get(base + ("|T" if transpose else "|N"))
        # 9.29 — transpozede alan aramasi KAYITLARI (sutunlari) suzer; arayuz
        # onlari `searchHidden` olarak yazar. Normal kipte arama satir suzer ve
        # `row_order`la zaten gelir. Kullanicinin `hidden`ina karistirilmaz:
        # filtre menusu yalnizca onu gosterir, arama temizlenince bu bosalir.
        extra = view.get("searchHidden") if view else None
        if extra and isinstance(extra, list):
            view = {**view, "hidden": list(view.get("hidden") or ()) + [k for k in extra
                                                                       if isinstance(k, str)]}
        return table, view

    @staticmethod
    def _expanded_rows(table: dict, expanded: list[int] | None) -> set[int]:
        """Ekranda ACIK birakilan satirlarin kaynak indeksleri — tek yerde suzulur.

        ⚠ **Indeks uzlasimi tek: KAYNAK indeks.** `row_order` gibi `expanded` de
        `table["rows"]` icindeki sirayi tasir. Arayuz zaten oyle tutuyor —
        `filterRows` her satiri kendi kaynak indeksiyle esliyor, yani cevirim
        gerekmiyor (olculdu). Ikisi karisirsa siralanmis bir tabloda YANLIS
        satir acilir ve bunu ancak goz fark eder.

        Kapsam disi indeksler ve acilacak icerigi olmayan satirlar burada
        duser; boylece uc cikti yolu da ayni kumeyi gorur.
        """
        if not expanded:
            return set()
        rows = table.get("rows") or []
        return {i for i in expanded
                if 0 <= i < len(rows) and any(c and c.get("sub") for c in rows[i])}

    @staticmethod
    def _safe_name(label: str) -> str:
        """Dosya adi icin guvenli etiket.

        Harf/rakam disi her sey tire olur, ardisik tireler tek tireye iner.
        "(belge kökü)" gibi etiketler bastan/sondan tire birakmaz.
        """
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label)
        return "-".join(part for part in safe.split("-") if part) or "tablo"

    @staticmethod
    def _stem(doc: dict) -> str:
        return Path(doc["name"]).stem
