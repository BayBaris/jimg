"""`Api`nin duzenleme yuzu (Faz 10.4): hucre duzenleme, geri al/yinele, kaydetme.

Uc saf modulu birlestirir: `edit_map` (hucre nerede) · `edit_core` (kokte
degistir, yigina it) · `json_write` (yalnizca degisen belirteci yaz). Her
islemden sonra `discover` yeniden kosar — 5 MB belgede 4 ms; degerden
turetilen etiketler (varyant ayirici basligi) boylece guncel kalir.

⚠ Anahtar yeniden adlandirmasi bir veri kumesinin YOLUNDAN geciyorsa o veri
kumesinin kimligi degisir (`ds.id` yoldan turer). Gorunum durumu (sutun
sirasi, genislik, transpoze) kimlikle anahtarlandigi icin yeni kimlige
TASINIR; tasinmasa kullanici duzenlemeden sonra ayarlarini kaybederdi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import discover as D
from . import edit_core as EC
from . import edit_map as EM
from . import i18n as I18N
from . import json_write as JW


class EditMixin:
    """Belge duzenleme ve kaydetme."""

    # --- Durum -------------------------------------------------------------

    @staticmethod
    def _edit_state(doc: dict) -> dict:
        h = doc["history"]
        return {"dirty": EC.dirty(h), "can_undo": bool(h.done), "can_redo": bool(h.undone)}

    def edit_state(self, doc_id: str) -> dict:
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        return {"ok": True, "edit": self._edit_state(doc)}

    @staticmethod
    def _edited_cells(doc: dict, ds: D.Dataset, variant_id: str | None) -> list[list[int]]:
        """Son kayittan BU YANA degisen hucrelerin (ri, ci) listesi (10.5.2).

        Kayit isareti islem kimligidir; ondan buyuk kimlikli islemler
        kaydedilmemis demektir. Yol arada yeniden adlandirilmis bir atanin
        altindaysa hucre bulunamaz ve isaret dusler — yanlis hucreyi
        isaretlemektense isaretsiz birakilir.
        """
        h = doc["history"]
        out = []
        for oid, (kind, path, _old, new) in h.done:
            if oid <= h.saved:
                continue
            if kind == EC.KEYS:
                # Cok yollu islemlerden yalnizca pivot ic anahtari bir HUCREDIR
                # (anahtar sutunu); digerleri sutun adi (`_edited_cols`).
                if ds.kind != D.PIVOT or EditMixin._keys_depth(ds, path) != 2:
                    continue
                at = EM.cell_at(doc["root"], ds, variant_id, list(ds.path) + [new], EM.SHARED)
            elif kind == EC.KEY:
                # Islem yolu ESKI adi tasir; anahtar artik yeni adda duruyor.
                # Eski yolla aranirsa satir bulunamaz ve isaret sessizce duserdi
                # (anahtar-deger ve anahtarli tablonun anahtar sutunu, 9.25).
                at = EM.cell_at(doc["root"], ds, variant_id, list(path[:-1]) + [new], kind)
            else:
                at = EM.cell_at(doc["root"], ds, variant_id, path, kind)
            if at and list(at) not in out:
                out.append(list(at))
        return out

    def _ds_changed(self, doc: dict, ds: D.Dataset, variant_id: str | None) -> bool:
        """Bu tabloda kaydedilmemis hucre ya da sutun adi degisikligi var mi (9.25).

        Agactaki isaret icin: tablodaki isaretlerle AYNI hesap, boylece agac
        "degisti" deyip tabloda hicbir sey isaretli olmamasi olmaz. Tablonun
        kendi adi ayri isarettir (`edited`, 10.6).
        """
        if not EC.dirty(doc["history"]):
            return False
        if self._edited_cells(doc, ds, variant_id):
            return True
        cols = self._edited_cols(doc, ds)
        variant = next((v for v in ds.variants if v.id == variant_id), None)
        if variant is not None:                  # varyant yalnizca kendi sutunlarini gosterir
            cols = [c for c in cols if c in variant.keys]
        return bool(cols)

    @staticmethod
    def _keys_depth(ds: D.Dataset, paths: list[list]) -> int | None:
        """Cok yollu islemin yollari veri kumesinin kac adim altinda (yoksa None).

        1: pivot sutunu (dugumun dis anahtari) · 2: satirdaki alan ya da pivot
        ic anahtari. Veri kumesine dusmeyen islem None.
        """
        n = len(ds.path)
        rel = [p for p in paths if list(p[:n]) == list(ds.path)]
        return len(rel[0]) - n if rel else None

    def _edited_cols(self, doc: dict, ds: D.Dataset) -> list[str]:
        """Son kayittan bu yana ADI degisen sutunlarin simdiki anahtarlari (10.7.2)."""
        h = doc["history"]
        out: list[str] = []
        for oid, (kind, path, _old, new) in h.done:
            if oid <= h.saved or kind != EC.KEYS:
                continue
            depth = self._keys_depth(ds, path)
            if depth is None or (ds.kind == D.PIVOT and depth == 2):
                continue                          # baska tablo ya da pivot ic anahtari
            if depth in (1, 2) and new not in out:
                out.append(new)
        return out

    @staticmethod
    def _renamed_paths(doc: dict) -> set[tuple]:
        """Son kayittan bu yana ADI degisen anahtarlarin SIMDIKI yollari (10.6).

        Bir veri kumesinin yolu bu kumedeyse tablonun adi degismistir; basligi
        ve agactaki satiri hucreler gibi isaretlenir. Hucre adi degisimi de
        (anahtar-deger tablosunda bir satir) ayni yoldan gelir.
        """
        h = doc["history"]
        return {tuple(path[:-1]) + (new,)
                for oid, (kind, path, _old, new) in h.done
                if oid > h.saved and kind == EC.KEY}

    # --- Islem sonrasi -----------------------------------------------------

    @staticmethod
    def _moved_ids(datasets: list[D.Dataset], key_path: list, new_name: str) -> dict[str, str]:
        """`key_path`teki anahtar `new_name` olunca kimligi degisen veri kumeleri."""
        n = len(key_path)
        out = {}
        for ds in datasets:
            if list(ds.path[:n]) == list(key_path):
                moved = list(key_path[:-1]) + [new_name] + list(ds.path[n:])
                out[ds.id] = D.path_id(moved)
        return out

    def _move_views(self, doc_id: str, ids: dict[str, str]) -> None:
        """Gorunum durumunu eski veri kumesi kimliginden yenisine tasir.

        Anahtar `doc_id|ds_id|variant_id|N/T`; varyant kimligi de veri kumesi
        kimligiyle baslar (`<ds_id>#v0`), o da cevrilir.
        """
        if not ids:
            return
        head = doc_id + "|"

        def moved(key: str) -> str:
            if not key.startswith(head):
                return key
            parts = key[len(head):].split("|")
            old = parts[0]
            if old not in ids:
                return key
            new = ids[old]
            parts[0] = new
            if len(parts) > 1 and parts[1].startswith(old + "#"):
                parts[1] = new + parts[1][len(old):]
            return head + "|".join(parts)

        self._views = {moved(k): v for k, v in self._views.items()}
        self._transposed = {moved(k) for k in self._transposed}

    def _after(self, doc_id: str, doc: dict, op: EC.Op, forward: bool) -> dict[str, str]:
        """Islemden SONRA: veri kumeleri yeniden, gorunum tasinir. Kimlik eslemesi doner.

        `op` UYGULANMIS islemdir. Anahtar isleminde ileri yon yolu eski adla,
        geri yon yeni adla tasir (`edit_core._do`).
        """
        ids: dict[str, str] = {}
        kind, path, old, new = op
        src, dst = (old, new) if forward else (new, old)
        if kind == EC.KEY:
            ids = self._moved_ids(doc["datasets"], path[:-1] + [src], dst)
        elif kind == EC.KEYS:
            # Her yol ayri bir alt veri kumesinin atasi olabilir (ornegin her
            # satirdaki ayni adli dizi): eslemeler birlestirilir.
            for p in path:
                ids.update(self._moved_ids(doc["datasets"], p[:-1] + [src], dst))
            owners = self._column_owners(doc["datasets"], path)
        doc["datasets"] = D.discover(doc["root"])
        self._move_views(doc_id, ids)
        if kind == EC.KEYS:
            self._rename_view_column(doc_id, {ids.get(o, o) for o in owners}, src, dst)
        return {a: b for a, b in ids.items() if a != b}

    @staticmethod
    def _column_owners(datasets: list[D.Dataset], paths: list[list]) -> set[str]:
        """Yeniden adlandirilan anahtari SUTUN olarak gosteren veri kumeleri.

        Anahtarin ust nesnesi veri kumesinin dugumu (pivot sutunu) ya da bir
        satiri (kayit/anahtarli tablo) ise o veri kumesinin sutunudur.
        """
        out = set()
        for ds in datasets:
            n = len(ds.path)
            if any(list(p[:n]) == list(ds.path) and len(p) - 1 - n in (0, 1) for p in paths):
                out.add(ds.id)
        return out

    def _rename_view_column(self, doc_id: str, ds_ids: set[str], old: str, new: str) -> None:
        """Sutun anahtarini veri kumelerinin N gorunumlerinde degistirir (10.7).

        Gorunum sutunu ANAHTARLA tutar: sira, genislik, gizlilik ve siralama.
        Tasinmasa yeniden adlandirilan sutun "yeni" sanilir — genisligi ve
        gizliligi kaybolur, sona eklenirdi. T gorunumleri sutun adi tasimaz.
        """
        for vkey, view in self._views.items():
            parts = vkey[len(doc_id) + 1:].split("|") if vkey.startswith(doc_id + "|") else []
            if not parts or parts[0] not in ds_ids or not vkey.endswith("|N"):
                continue
            swap = lambda k: new if k == old else k  # noqa: E731
            for name in ("order", "hidden", "autoHidden", "longHidden"):
                if isinstance(view.get(name), list):
                    view[name] = [swap(k) for k in view[name]]
            if isinstance(view.get("widths"), dict):
                view["widths"] = {swap(k): w for k, w in view["widths"].items()}
            if isinstance(view.get("sort"), dict) and view["sort"].get("key") == old:
                view["sort"] = {**view["sort"], "key": new}

    # --- Duzenleme ---------------------------------------------------------

    def edit_cell(self, doc_id: str, ds_id: str, variant_id: str | None,
                  ri: int, ci: int, text: str) -> dict:
        """Hucreyi duzenler; `table()` sonucunu + `edit` durumunu doner.

        `ri`/`ci` TRANSPOZESIZ tablonun indeksleridir (arayuz transpozede
        cevirir). Duzenlenemeyen hucre ve kurala takilan deger `ok: False` +
        cevrilmis ileti doner; kok degismez.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
        if ds is None:
            return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}
        root = doc["root"]
        try:
            loc = EM.locate(root, ds, variant_id, int(ri), int(ci))
        except (IndexError, KeyError, TypeError, ValueError):
            return {"ok": False, "error": I18N.t("edit.why_unmapped")}
        if isinstance(loc, str):
            return {"ok": False, "error": I18N.t(f"edit.why_{loc}")}
        path, target = loc
        try:
            if target == EM.SHARED:
                # Pivot ic anahtari: her pivot sutununda birlikte (10.7).
                op = EC.rename_many_op(root, EM.pivot_key_paths(root, ds, path[-1]), str(text))
            elif target == EM.KEY:
                op = EC.rename_op(root, path, str(text))
            else:
                op = EC.set_value_op(root, path, EC.parse_input(str(text), D.resolve(root, path)))
        except EC.EditError as e:
            return {"ok": False, "error": I18N.t(f"edit.err_{e.reason}")}
        return self._apply_and_table(doc_id, doc, op, ds_id, variant_id)

    def rename_dataset(self, doc_id: str, ds_id: str, variant_id: str | None,
                       name: str) -> dict:
        """Tablonun adini degistirir (10.6): adi ust nesnedeki ANAHTARIN kendisidir.

        Kok tablonun adi dosya adidir, varyant basligi ise ayirici sutundan
        turer — ikisi de anahtar degil, nedenle reddedilir. Gorunum durumu
        yeni kimlige `_after` icinde tasinir (10.4).
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
        if ds is None:
            return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}
        if variant_id:
            return {"ok": False, "error": I18N.t(f"edit.err_{EC.ERR_VARIANT_NAME}")}
        try:
            op = EC.rename_op(doc["root"], list(ds.path), str(name))
        except EC.EditError as e:
            return {"ok": False, "error": I18N.t(f"edit.err_{e.reason}")}
        return self._apply_and_table(doc_id, doc, op, ds_id, None)

    def rename_column(self, doc_id: str, ds_id: str, variant_id: str | None,
                      ci: int, name: str) -> dict:
        """Sutunun adini degistirir (10.7): alan veri kumesinin TUM satirlarinda.

        `ci` TRANSPOZESIZ tablonun sutun indeksidir. Tek islemdir; geri al tek
        adimda hepsini dondurur. Sutun sirasi, genislik, gizlilik ve siralama
        yeni ada `_after` icinde tasinir.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
        if ds is None:
            return {"ok": False, "error": I18N.t("err.dataset_missing", id=ds_id)}
        try:
            found = EM.column_paths(doc["root"], ds, variant_id, int(ci))
        except (IndexError, KeyError, TypeError, ValueError):
            return {"ok": False, "error": I18N.t("edit.why_unmapped")}
        if isinstance(found, str):
            return {"ok": False, "error": I18N.t(f"edit.why_{found}")}
        paths, _old = found
        try:
            op = EC.rename_many_op(doc["root"], paths, str(name))
        except EC.EditError as e:
            return {"ok": False, "error": I18N.t(f"edit.err_{e.reason}")}
        return self._apply_and_table(doc_id, doc, op, ds_id, variant_id)

    def _apply_and_table(self, doc_id: str, doc: dict, op: EC.Op,
                         ds_id: str, variant_id: str | None) -> dict:
        """Islemi uygular; secimin YENI kimligiyle tabloyu + durumu doner."""
        ids: dict[str, str] = {}
        if EC.apply(doc["root"], doc["history"], op):
            ids = self._after(doc_id, doc, op, forward=True)
        new_ds = ids.get(ds_id, ds_id)
        new_var = variant_id
        if variant_id and ds_id in ids:
            new_var = ids[ds_id] + variant_id[len(ds_id):]
        res = self.table(doc_id, new_ds, new_var)
        # `renamed`: kimligi degisen TUM veri kumeleri — arayuz secili tablo
        # baskasiysa (ornegin adi degisen tablonun altindaki) secimi tasir.
        res.update({"edit": self._edit_state(doc), "ds_id": new_ds, "variant_id": new_var,
                    "renamed": ids})
        return res

    def undo_edit(self, doc_id: str) -> dict:
        return self._step(doc_id, EC.undo, forward=False)

    def redo_edit(self, doc_id: str) -> dict:
        return self._step(doc_id, EC.redo, forward=True)

    def _step(self, doc_id: str, fn: Any, forward: bool) -> dict:
        """Geri al / yinele. Arayuz gecerli tabloyu kendisi yeniden ister;
        `renamed` veri kumesi kimligi degistiyse secimi tasimasi icindir."""
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        op = fn(doc["root"], doc["history"])
        ids = self._after(doc_id, doc, op, forward) if op else {}
        return {"ok": True, "edit": self._edit_state(doc), "renamed": ids}

    # --- Cikis (10.5.3) ----------------------------------------------------

    def dirty_docs(self) -> dict:
        """Kaydedilmemis degisikligi olan belgeler — cikis sorusu icin."""
        docs = [{"id": d["path"], "name": d["name"]}
                for d in self._docs.values() if EC.dirty(d["history"])]
        return {"ok": True, "docs": docs}

    def quit_app(self) -> dict:
        """Kullanici cikisi onayladi: kapanis olayi bir daha sormaz.

        Pencere yoksa (gelistirme sunucusu) yalnizca bayrak konur.
        """
        self._quit_ok = True
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}

    # --- Kaydetme ----------------------------------------------------------

    def save_doc(self, doc_id: str, force: bool = False) -> dict:
        """Belgeyi yazar: yalnizca degisen belirtecler (`json_write`).

        KB-4: `.bak` bu oturumdaki ILK kayittan once ve ayar aciksa yazilir.
        KB-3: diskte degismisse `reason: changed_on_disk` doner; arayuz sorar
        ve onayla `force=True` ile yeniden cagirir.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        h = doc["history"]
        try:
            data = JW.render(doc["raw"], doc["root"])
            if data is not doc["raw"]:
                enabled = bool(self._settings.get("documents", {}).get("backup", True))
                backup = enabled and not doc["backed_up"]
                # Zorla yazimda diskteki surum her zaman korunur (ayar aciksa):
                # `.bak` bu oturumda zaten yazildiysa `.conflict.bak`a.
                JW.save(Path(doc["path"]), doc["raw"], data, backup=backup, force=bool(force),
                        conflict_backup=enabled)
                doc["backed_up"] = doc["backed_up"] or backup
                doc["raw"] = data
                doc["size"] = len(data)
        except JW.WriteError as e:
            return {"ok": False, "reason": e.reason, "error": I18N.t(f"edit.save_{e.reason}")}
        except OSError as e:
            return {"ok": False, "reason": "failed", "error": I18N.t("edit.save_failed", error=e)}
        EC.mark_saved(h)
        return {"ok": True, "edit": self._edit_state(doc),
                "message": I18N.t("edit.saved", name=doc["name"])}
