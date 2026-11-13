"""`Api`nin disa aktarim yuzu: metin, PNG, vektor sahne, galeri ve kaydetme.

`row_order` arayuzden gelir: siralama ve filtre orada uygulandigi icin cikti
ekranda gorunenle birebir olur. Bu mantik Python'da TEKRARLANMAZ — iki ayri
siralama uygulamasi gunun birinde saparcdi.

⚠ Cizim modulleri metotlarin ICINDE ice aktarilir (Faz 8.6): hepsi Pillow
tasiyor ve Pillow yalnizca gercekten gorsel uretilirken gerekiyor.

Kaydetme metotlari pencere ister; dev sunucusunda `self._window is None` olur ve
anlasilir bir hata doner.
"""

from __future__ import annotations

import base64
import io
import traceback
from pathlib import Path

import webview

from . import export_text as T
from . import i18n as I18N
from . import images as IM
from . import theme as TH
from . import vector as VEC


class ExportMixin:
    """Metin/gorsel cikti uretimi ve diske yazma."""

    # --- Cikti temasi (9.19.3) --------------------------------------------
    #
    # Renk ureten HER kopru metodu govdesini `_out_theme()` icinde calistirir:
    # public metot ince bir sarmalayici, asil is alt cizgili esinde. Tema
    # cizim cagrilarina TEK TEK sarilmadi — bir cagri unutuldugunda cikti iki
    # temanin karisimi olurdu ve bunu hicbir sey yakalamazdi. Sarmalayicilarin
    # tam listesi `check.py --> THEMED_OUTPUTS` ile denetlenir.

    def _out_theme(self):
        """Ciktinin temasi: ayar `app` ise uygulamaninki, degilse sabitlenen."""
        return TH.using(self._settings.get("export", {}).get("theme"))

    # --- Metin ------------------------------------------------------------

    def export_text(self, kind: str, doc_id: str, ds_id: str | None = None,
                    variant_id: str | None = None,
                    row_order: list[int] | None = None,
                    expanded: list[int] | None = None) -> dict:
        """Metin ciktisi uretir; HTML ciktinin temasini tasir (`_out_theme`)."""
        with self._out_theme():
            return self._export_text(kind, doc_id, ds_id, variant_id, row_order, expanded)

    def _export_text(self, kind: str, doc_id: str, ds_id: str | None,
                     variant_id: str | None, row_order: list[int] | None,
                     expanded: list[int] | None) -> dict:
        """Metin ciktisi uretir. `kind`: report | outline | table | csv | html.

        `row_order` arayuzden gelir; siralama ve filtre orada uygulandigi icin
        cikti ekranda gorunenle birebir olur. `expanded` ayni uzlasimi izler
        (KAYNAK indeks) ve yalnizca HTML'i etkiler: ekranda acik birakilan
        satir orada da acik gelir. MD/CSV'de yapi yok, duzlestirme kaliyor.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        if kind not in T.KINDS:
            return {"ok": False, "error": I18N.t("err.unknown_kind", kind=kind)}

        stem = self._stem(doc)
        try:
            if kind == "report":
                text = T.document_markdown(doc["name"], doc["root"], doc["datasets"])
                return {"ok": True, "text": text, "name": f"{stem}-rapor.md"}

            if kind == "outline":
                text = T.outline(doc["name"], doc["root"])
                return {"ok": True, "text": text, "name": f"{stem}-anahat.txt"}

            ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
            if ds is None:
                return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}

            table, view = self._table_for_output(doc, ds, doc_id, ds_id, variant_id)
            safe = self._safe_name(table["label"])

            if kind == "csv":
                text = T.table_csv(table, view, row_order)
                return {"ok": True, "text": text, "name": f"{stem}-{safe}.csv"}

            if kind == "html":
                text = T.table_html(table, view, row_order,
                                    title=table["label"], source=doc["name"],
                                    expanded=self._expanded_rows(table, expanded))
                return {"ok": True, "text": text, "name": f"{stem}-{safe}.html"}

            text = T.table_markdown(table, view, row_order)
            return {"ok": True, "text": text, "name": f"{stem}-{safe}.md"}
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

    # --- Belgedeki gorseller ----------------------------------------------

    def gallery(self, doc_id: str) -> dict:
        """Belgenin ICINDEKI gorsellerin LISTESI (gomulu base64 + goreli yol).

        ⚠ Onizleme tasimaz (`9.6.1`): kartlar ekrana girdikce `gallery_thumbs`
        ile istenir. Mutlak yollar ve http adresleri desteklenmez — bkz.
        images.py.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        try:
            items = IM.catalog(doc["root"], self._sources(doc))
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}
        # 9.6.5.1 — izin verilmemisse mutlak yollu gorsel sayisi; arayuz izin
        # cubugunu bundan kurar. Izin verilmisse 0: soracak bir sey kalmadi.
        refs = 0 if doc_id in self._absolute_ok else IM.absolute_refs(doc["root"])
        # 9.6.5.2 — ayar kapaliyken istek gidebilecek adres sayisi; cubuk yalnizca
        # yerini soyler, izin ayardan verilir (`K-10`).
        urls = 0 if self._sources(doc).url else IM.url_refs(doc["root"])
        return {"ok": True, "items": items, "doc": doc["name"],
                "base_dir": str(self._base_dir(doc)), "absolute_refs": refs,
                "url_refs": urls}

    def gallery_allow_absolute(self, doc_id: str) -> dict:
        """Bu belgedeki mutlak yollu gorsellere izin verir — oturum boyunca.

        Izin belge KIMLIGINE baglidir ve belge kapaninca duser. Kalici bir
        "her zaman izin ver" yolu bilerek yok (karar: `9.6.5`); UNC yollari
        izinle de acilmaz (`images.resolve`).
        """
        if doc_id not in self._docs:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        self._absolute_ok.add(doc_id)
        return {"ok": True}

    def gallery_thumbs(self, doc_id: str, json_paths: list[str],
                       box: int | None = None) -> dict:
        """Istenen gorsellerin onizlemesini uretir (`9.6.1`).

        `box` GOSTERIM kenaridir; uretim onu asmaz ve `IM.MAX_PREVIEW_PX` ile
        sinirlidir. Kapsam disi bir yol hata degildir — yaniti kucultur.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        try:
            items = IM.thumbs(doc["root"], self._sources(doc),
                              list(json_paths or []),
                              box or IM.PREVIEW_PX)
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}
        return {"ok": True, "thumbs": items}

    # --- PNG --------------------------------------------------------------

    def export_image(self, kind: str, doc_id: str, ds_id: str | None = None,
                     variant_id: str | None = None,
                     row_order: list[int] | None = None,
                     options: dict | None = None) -> dict:
        """PNG uretir (ciktinin temasinda)."""
        with self._out_theme():
            return self._export_image(kind, doc_id, ds_id, variant_id, row_order, options)

    def _export_image(self, kind: str, doc_id: str, ds_id: str | None,
                      variant_id: str | None, row_order: list[int] | None,
                      options: dict | None) -> dict:
        """PNG uretir. `kind`: table | tree | chart. Sonuc data URI olarak doner."""
        from PIL import Image

        from . import img_chart as ICH
        from . import img_table as ITB
        from . import img_tree as ITR
        from .api_chart import _chart_error

        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}

        opt = options or {}
        scale = int(opt.get("scale") or 2)
        stem = self._stem(doc)

        try:
            if kind == "tree":
                png = ITR.render_tree(doc["name"], doc["root"], scale)
                name = f"{stem}-agac.png"
            else:
                ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
                if ds is None:
                    return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}

                table, view = self._table_for_output(doc, ds, doc_id, ds_id, variant_id)
                safe = self._safe_name(table["label"])

                if kind == "chart":
                    cat, num = opt.get("category"), opt.get("numeric")
                    agg = opt.get("agg") or "sum"
                    if (err := _chart_error(cat, num, agg)):
                        return {"ok": False, "error": err}
                    png = ICH.render_chart(table, cat, num, opt.get("chart") or "bar",
                                           row_order, scale, title=table["label"],
                                           agg=agg, source=doc["name"])
                    name = f"{stem}-{safe}-grafik.png"
                elif kind == "table":
                    # Olculer ALTBILGIDE (img_table._table_footer); ustte
                    # yalnizca veri kumesi ve belge adi.
                    #
                    # ⚠ Acik satirlar `options` icinden gelir: cizim yollarinin
                    # yerlesik uzatma noktasi orasi (`scale`, grafik secimleri
                    # de oyle). `export_text`te options yok, orada ayri bir
                    # parametre var — ayrim bilerek.
                    png = ITB.render_table(table, view, row_order, scale,
                                           expanded=self._expanded_rows(
                                               table, opt.get("expanded")),
                                           title=table["label"], subtitle=doc["name"])
                    name = f"{stem}-{safe}.png"
                else:
                    return {"ok": False,
                            "error": I18N.t("err.unknown_image_kind", kind=kind)}
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        self._png = png
        img = Image.open(io.BytesIO(png))
        return {
            "ok": True,
            "data": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            "name": name, "bytes": len(png), "width": img.width, "height": img.height,
        }

    # --- Vektor sahne -----------------------------------------------------

    def scene_svg(self, kind: str, doc_id: str, ds_id: str | None = None,
                  variant_id: str | None = None, row_order: list[int] | None = None,
                  options: dict | None = None) -> dict:
        """Agac veya tabloyu etkilesimli SVG olarak uretir (ciktinin temasinda)."""
        with self._out_theme():
            return self._scene_svg(kind, doc_id, ds_id, variant_id, row_order, options)

    def _scene_svg(self, kind: str, doc_id: str, ds_id: str | None,
                   variant_id: str | None, row_order: list[int] | None,
                   options: dict | None) -> dict:
        """Agac veya tabloyu etkilesimli SVG olarak uretir.

        Ayni sahne PDF'e de basilir; agacta ayrica `.drawio` dugum modeli
        saklanir (K-11). Geometri tek yerde uretilir.
        """
        from . import img_table as ITB
        from . import img_tree as ITR

        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}

        stem = self._stem(doc)
        try:
            if kind == "tree":
                scene, nodes, edges = ITR.tree_scene(doc["name"], doc["root"])
                self._drawio = (nodes, edges, doc["name"])
                name = f"{stem}-agac"
            elif kind == "table":
                ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
                if ds is None:
                    return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}
                table, view = self._table_for_output(doc, ds, doc_id, ds_id, variant_id)
                scene = ITB.table_scene(
                    table, view, row_order, title=table["label"],
                    subtitle=doc["name"],
                    expanded=self._expanded_rows(table, (options or {}).get("expanded")))
                self._drawio = None
                name = f"{stem}-{self._safe_name(table['label'])}"
            else:
                return {"ok": False, "error": I18N.t("err.no_vector", kind=kind)}
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        self._scene = scene
        return {"ok": True, "svg": VEC.to_svg(scene), "name": name,
                "drawio": kind == "tree"}

    # --- Diske yazma ------------------------------------------------------

    def _ask_path(self, kind: int, **kwargs) -> tuple[Path | None, dict | None]:
        """Dosya/klasor diyalogu. (yol, hata_yaniti) doner; biri daima None'dir.

        ⚠ `api_docs._dialog` burada KULLANILMAZ: o, iptal ile pencere yoklugunu
        ayni `None` ile donduruyor. Acarken ikisi ayni sonuca varir (bir sey
        acilmaz), kaydederken varmaz — pencere yoksa kullanici neden
        kaydedemedigini ogrenmeli, iptalde ise hicbir mesaj beklenmez.
        """
        if self._window is None:
            return None, {"ok": False, "error": I18N.t("err.desktop_only")}
        try:
            result = self._window.create_file_dialog(kind, **kwargs)
        except Exception as exc:
            return None, {"ok": False, "error": str(exc)}
        if not result:
            return None, {"ok": False, "cancelled": True}
        return Path(result[0] if isinstance(result, (list, tuple)) else result), None

    def _save_dialog(self, filename: str) -> tuple[Path | None, dict | None]:
        """Kaydet diyalogu — ad onerilir, son soz kullanicinin."""
        return self._ask_path(webview.FileDialog.SAVE, save_filename=filename)

    def _folder_dialog(self) -> tuple[Path | None, dict | None]:
        """Klasor diyalogu — birden cok gorseli kaydetmek icin (`9.6.4`)."""
        return self._ask_path(webview.FileDialog.FOLDER)

    def save_drawio(self, suggested_name: str) -> dict:
        """Agaci draw.io semasi olarak yazar (ciktinin temasinda)."""
        with self._out_theme():
            return self._save_drawio(suggested_name)

    def _save_drawio(self, suggested_name: str) -> dict:
        """Agaci draw.io semasi olarak yazar (K-11) — cizim degil, nesne modeli."""
        if not self._drawio:
            return {"ok": False, "error": I18N.t("err.need_tree_tab")}

        nodes, edges, title = self._drawio
        data = VEC.to_drawio(nodes, edges, title).encode("utf-8")

        target, err = self._save_dialog(f"{suggested_name}.drawio")
        if err:
            return err
        try:
            target.write_bytes(data)
        except OSError as exc:
            return {"ok": False, "error": I18N.t("err.write_failed", error=exc)}
        return {"ok": True, "path": str(target), "bytes": len(data),
                "nodes": len(nodes), "edges": len(edges)}

    def save_vector(self, fmt: str, suggested_name: str) -> dict:
        """Son sahneyi PDF veya SVG olarak diske yazar (ciktinin temasinda)."""
        with self._out_theme():
            return self._save_vector(fmt, suggested_name)

    def _save_vector(self, fmt: str, suggested_name: str) -> dict:
        """Son sahneyi PDF veya SVG olarak diske yazar (`K-12`: elle vektör PDF)."""
        if self._scene is None:
            return {"ok": False, "error": I18N.t("err.need_chart")}
        if fmt not in ("pdf", "svg"):
            return {"ok": False, "error": I18N.t("err.unknown_format", fmt=fmt)}

        try:
            data = (VEC.to_pdf(self._scene, suggested_name) if fmt == "pdf"
                    else VEC.to_svg(self._scene).encode("utf-8"))
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        target, err = self._save_dialog(f"{suggested_name}.{fmt}")
        if err:
            return err
        try:
            target.write_bytes(data)
        except OSError as exc:
            return {"ok": False, "error": I18N.t("err.write_failed", error=exc)}
        return {"ok": True, "path": str(target), "bytes": len(data)}

    def save_image(self, suggested_name: str) -> dict:
        """Son uretilen PNG'yi diske yazar."""
        if self._png is None:
            return {"ok": False, "error": I18N.t("err.need_image")}

        target, err = self._save_dialog(suggested_name)
        if err:
            return err
        try:
            target.write_bytes(self._png)
        except OSError as exc:
            return {"ok": False, "error": I18N.t("err.write_failed", error=exc)}
        return {"ok": True, "path": str(target)}

    def save_text(self, text: str, suggested_name: str) -> dict:
        """Kaydet diyalogu acar ve metni UTF-8 olarak yazar."""
        target, err = self._save_dialog(suggested_name)
        if err:
            return err
        try:
            target.write_text(text, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": I18N.t("err.write_failed", error=exc)}
        return {"ok": True, "path": str(target)}

    # --- Belgedeki gorselleri kaydetme (9.6.4) ----------------------------

    def save_images(self, doc_id: str, json_paths: list[str] | None = None) -> dict:
        """Secilen gorselleri OZGUN baytlariyla diske yazar.

        Tek gorselde kaydet diyalogu: ad kaynaktan onerilir, secilen yola
        yazilir — `save_text`/`save_image` ile ayni uzlasim, ad kullanicinin.
        Birden cogunda klasor diyalogu: adlar kaynaktan turer, klasorde duranla
        cakisan sayi alir (`_write_images`).

        ⚠ Baytlar `images.load`dan gelir, galeriden DEGIL: galeri kucultulmus
        PNG onizleme tasiyor ve onu yazmak bir JPEG'i PNG'ye, 2000 px'lik bir
        gorseli 400 px'e sessizce cevirirdi.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        picked = self._pick_images(doc, json_paths)
        if not picked:
            return {"ok": False, "error": I18N.t("err.no_selection")}

        if len(picked) == 1:
            json_path, desc = picked[0]
            # Once oku, sonra sor: okunamayacak bir gorsel icin diyalog acmak
            # kullaniciya bos bir is yaptirirdi.
            raw = IM.load(desc, self._sources(doc))
            if raw is None:
                return {"ok": False, "error": I18N.t("err.image_unreadable")}
            target, err = self._save_dialog(IM.export_name(desc, json_path))
            if err:
                return err
            try:
                target.write_bytes(raw)
            except OSError as exc:
                return {"ok": False, "error": I18N.t("err.write_failed", error=exc)}
            return {"ok": True, "path": str(target), "count": 1, "skipped": 0}

        folder, err = self._folder_dialog()
        if err:
            return err
        try:
            written, skipped = self._write_images(doc, picked, folder)
        except OSError as exc:
            return {"ok": False, "error": I18N.t("err.write_failed", error=exc)}
        return {"ok": True, "folder": str(folder), "count": len(written),
                "skipped": skipped}

    def _pick_images(self, doc: dict, json_paths: list[str] | None) -> list[tuple[str, dict]]:
        """Istenen gorselleri ISTEK sirasiyla dondurur; belgede olmayan yol atlanir.

        Sira arayuzun sirasidir (gruplu ekran sirasi): cakisan adlardan
        hangisinin `-2` alacagini o belirliyor, belgedeki sira degil.
        """
        found = {hit["json_path"]: hit["desc"]
                 for hit in IM.scan(doc["root"], self._sources(doc))}
        return [(p, found[p]) for p in dict.fromkeys(json_paths or []) if p in found]

    def _write_images(self, doc: dict, picked: list[tuple[str, dict]],
                      folder: Path) -> tuple[list[Path], int]:
        """Klasore yazar: (yazilanlar, okunamayan sayisi).

        ⚠ Klasor listesi yalnizca bir TAHMIN. Dosya `"xb"` ile acilir: liste ile
        yazma arasinda ayni ad belirirse isletim sistemi reddeder ve bir sonraki
        bos ad secilir. Ustune yazma hicbir yolda yok — sessizce ezilen dosya,
        kullanicinin haberi olmadan kaybolan veridir.
        """
        src = self._sources(doc)
        try:
            used = {p.name for p in folder.iterdir()}
        except OSError:
            used = set()
        names = IM.unique_names([IM.export_name(d, j) for j, d in picked], used)
        used |= set(names)

        written: list[Path] = []
        skipped = 0
        for (_, desc), name in zip(picked, names):
            raw = IM.load(desc, src)
            if raw is None:
                skipped += 1
                continue
            while True:
                try:
                    with (folder / name).open("xb") as fh:
                        fh.write(raw)
                    break
                except FileExistsError:
                    name = IM.unique_names([name], used)[0]
                    used.add(name)
            written.append(folder / name)
        return written, skipped
