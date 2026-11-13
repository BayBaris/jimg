"""`Api`nin belge ve agac yuzu: acma, kapatma, klasor tarama.

Mixin'ler icin ortak kural (bkz. `app.Api`): DURUM `Api.__init__` icinde kurulur,
mixin'ler yalnizca okur ve yazar. Burada `self._docs`, `self._folders` ve
kapatma sirasinda `self._views` / `self._transposed` kullanilir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import webview

from . import discover as D
from . import edit_core as EC
from . import i18n as I18N
from . import images as IM
from . import settings as S
from .paths import examples_dir, project_root

# Klasor taramasinda ust sinirlar — cok buyuk agaclarda arayuz bogulmasin.
MAX_SCAN_FILES = 800
MAX_SCAN_DEPTH = 8
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "Library", "Temp", "obj", "bin"}


def _scan_folder(folder: Path) -> tuple[dict, int]:
    """Klasoru .json dosyalari icin tarar, arayuz agaci uretir."""
    count = 0

    def walk(d: Path, depth: int) -> dict | None:
        nonlocal count
        children: list[dict] = []
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return None

        for e in entries:
            if count >= MAX_SCAN_FILES:
                break
            if e.is_dir():
                if depth >= MAX_SCAN_DEPTH or e.name in SKIP_DIRS or e.name.startswith("."):
                    continue
                sub = walk(e, depth + 1)
                if sub and sub["children"]:      # bos klasorleri gosterme
                    children.append(sub)
            elif e.suffix.lower() == ".json":
                count += 1
                children.append({"type": "file", "name": e.name, "path": str(e)})

        return {"type": "dir", "name": d.name or str(d), "path": str(d), "children": children}

    tree = walk(folder, 0) or {"type": "dir", "name": folder.name, "path": str(folder), "children": []}
    return tree, count


def _is_unc(path: str) -> bool:
    """Ag paylasimi yolu mu (iki egik cizgiyle baslar)."""
    return path.startswith(("\\\\", "//"))


class DocsMixin:
    """Belge yukleme, kapatma ve sol paneldeki agac."""

    # --- Belge yukleme ----------------------------------------------------

    def startup(self) -> dict:
        """Pencere acilirken cagrilir.

        Iki klasor aranir ve ikisi de istege baglidir:
          `examples/` — depoyla gelen ornekler; exe'de ilk calistirmada
                        `%APPDATA%` altina kopyalanir (bkz. `paths.examples_dir`)
          `samples/`  — kullanicinin kendi belgeleri, izlenmez (`K-09`)

        Ilk belge yalnizca hicbir belge acik degilse acilir; boylece sayfa
        yenilendiginde kullanicinin secimi ezilmez.
        """
        self._restore_session()
        for folder in (examples_dir(), project_root() / "samples"):
            if folder is not None:
                self._add_startup_folder(folder)
        return self.tree()

    # --- Oturum (9.19.5) --------------------------------------------------

    def _restoring(self) -> bool:
        return bool(self._settings.get("documents", {}).get("restore"))

    def _save_session(self) -> None:
        """Acik belge ve klasor yollarini yazar; ayar kapaliyken HICBIR SEY yazmaz.

        Yazilamazsa sessiz gecilir: geri yukleme bir kolayliktir, belge acmayi
        ya da kapatmayi basarisiz kilmamali.
        """
        if not self._restoring():
            return
        try:
            S.save_session(list(self._docs), [f["path"] for f in self._folders])
        except OSError:
            pass

    def _restore_session(self) -> None:
        """Son oturumun belgelerini ve klasorlerini geri acar — surec basina BIR KEZ.

        `startup()` her sayfa yenilemesinde cagriliyor; bayrak olmasa kullanicinin
        kapattigi belge yenilemede geri gelirdi.

        ⚠ Artik var olmayan ya da okunamayan yol SESSIZCE atlanir: tasinmis bir
        dosya icin her acilista hata gostermek, ozelligi kapattirirdi.
        ⚠ Ag yolu (UNC) geri ACILMAZ: erisilemeyen bir paylasim acilisi
        dakikalarca bekletebilir. Kullanici o belgeyi elle acar.
        """
        if self._restored or not self._restoring():
            return
        self._restored = True

        session = S.load_session()
        for path in session["folders"]:
            folder = Path(path)
            if (not _is_unc(path) and folder.is_dir()
                    and not any(f["path"] == str(folder) for f in self._folders)):
                self._folders.append(_scan_folder(folder)[0])
        for path in session["docs"]:
            p = Path(path)
            if not _is_unc(path) and p.is_file() and str(p) not in self._docs:
                self._load_one(p)

    def _add_startup_folder(self, folder: Path) -> None:
        """Acilis klasorunu agaca ekler; ayni klasoru IKI KEZ eklemez.

        `startup()` her sayfa yenilemesinde cagriliyor — dev sunucusunda bu sik
        oluyor — ve koruma olmazsa agacta ayni klasor birikirdi.
        """
        if not folder.is_dir():
            return
        if any(f["path"] == str(folder) for f in self._folders):
            return

        tree, _ = _scan_folder(folder)
        if not tree["children"]:
            return

        self._folders.append(tree)
        if not self._docs:
            first = next(iter(sorted(folder.glob("*.json"))), None)
            if first is not None:
                self._load_one(first)

    def open_files(self) -> dict:
        """Coklu dosya secimi."""
        paths = self._dialog(webview.FileDialog.OPEN, allow_multiple=True,
                             file_types=(I18N.t("dlg.json_files"),
                                         I18N.t("dlg.all_files")))
        if paths is None:
            return {"ok": False, "cancelled": True}

        errors = [e for p in paths if (e := self._load_one(Path(p)))]
        self._save_session()
        out = self.tree()
        out["errors"] = errors
        return out

    def open_folder(self) -> dict:
        """Klasor acar ve altindaki tum .json dosyalarini agaca dizer."""
        paths = self._dialog(webview.FileDialog.FOLDER)
        if paths is None:
            return {"ok": False, "cancelled": True}

        folder = Path(paths[0])
        tree, count = _scan_folder(folder)
        self._folders = [f for f in self._folders if f["path"] != str(folder)]
        self._folders.append(tree)
        self._save_session()

        out = self.tree()
        out["message"] = I18N.t("msg.folder_scanned", name=folder.name, n=count)
        if count >= MAX_SCAN_FILES:
            out["message"] += I18N.t("msg.folder_capped", limit=MAX_SCAN_FILES)
        return out

    def open_path(self, path: str) -> dict:
        """Agactan tiklanan dosyayi acar."""
        err = self._load_one(Path(path))
        self._save_session()
        out = self.tree()
        if err:
            out["errors"] = [err]
        else:
            out["opened"] = str(Path(path))
        return out

    def close_doc(self, doc_id: str) -> dict:
        self._docs.pop(doc_id, None)
        self._chats.pop(doc_id, None)
        self._drop_views(doc_id)
        # 9.6.5.1 — izin belgeyle biter: ayni yoldan yeniden acilan belge,
        # aradan degismis olabilecek bir icerik icin yeniden sorar.
        self._absolute_ok.discard(doc_id)
        self._save_session()
        return self.tree()

    def _drop_views(self, doc_id: str) -> None:
        """Bir belgeye ait tum gorunum durumunu siler (genislik, gizlilik, transpoze)."""
        for key in [k for k in self._views if k.startswith(doc_id + "|")]:
            self._views.pop(key, None)
        self._transposed = {k for k in self._transposed if not k.startswith(doc_id + "|")}

    def close_folder(self, path: str) -> dict:
        self._folders = [f for f in self._folders if f["path"] != path]
        self._save_session()
        return self.tree()

    def _dialog(self, kind: int, **kwargs: Any) -> list[str] | None:
        """Dosya diyalogu. Pencere yoksa (dev sunucusu) None doner."""
        if self._window is None:
            return None
        try:
            result = self._window.create_file_dialog(kind, **kwargs)
        except Exception:
            return None
        return list(result) if result else None

    def _load_one(self, p: Path) -> str | None:
        """Tek belge yukler. Hata varsa mesaji dondurur, basarida None."""
        try:
            # Ozgun BAYT saklanir (10.4): kaydetme yalnizca degisen belirteci
            # yazar ve geri kalani buradan alir. `read_text` evrensel satir
            # sonuyla CRLF'yi LF'ye cevirirdi.
            raw = p.read_bytes()
            root = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            return I18N.t("err.read_failed", name=p.name, error=exc)
        except json.JSONDecodeError as exc:
            return I18N.t("err.json_parse", name=p.name, line=exc.lineno,
                          col=exc.colno, msg=exc.msg)
        except OSError as exc:
            return I18N.t("err.read_failed", name=p.name, error=exc)

        doc_id = str(p)
        # Belge YENIDEN aciliyorsa kayitli gorunumler dusurulur: sutun
        # genislikleri, gizlilik ve siralama varsayilana doner (K-17). Baska
        # belgelerin gorunumune dokunulmaz.
        if doc_id in self._docs:
            self._drop_views(doc_id)

        self._docs[doc_id] = {
            "name": p.name,
            "path": doc_id,
            "root": root,
            "datasets": D.discover(root),
            "size": p.stat().st_size,
            "raw": raw,                    # 10.4 — son okunan/yazilan bayt
            "history": EC.History(),       # 10.4 — geri al/yinele
            "backed_up": False,            # 10.4 — KB-4: bu oturumda .bak yazildi mi
        }
        return None

    # --- Agac -------------------------------------------------------------

    def tree(self) -> dict:
        return {
            "ok": True,
            "folders": self._folders,
            "docs": [self._doc_summary(d) for d in self._docs.values()],
        }

    @staticmethod
    def _ds_label(doc: dict, ds: D.Dataset) -> str:
        # Kok duzeyindeki tablolarda `ds.root` yerine dosya adi daha okunur.
        if not ds.path:
            return Path(doc["name"]).stem
        return ds.label_text

    @staticmethod
    def _base_dir(doc: dict) -> Path:
        """Goreli gorsel yollarinin cozulecegi klasor: belgenin bulundugu yer."""
        return Path(doc["path"]).parent

    def _sources(self, doc: dict) -> IM.Sources:
        """Belgenin gorsel izinleri: klasor + mutlak yol onayi + adres ayari.

        Gorsele dokunan her okuyucu `_base_dir` yerine bunu alir; izin tek
        yerden gelir. `_base_dir` yalnizca gosterim icin kaldi (galeri bilgisi).
        Adres ayari belgeye degil kullaniciya aittir (`9.6.5.2`), mutlak yol
        onayi ise belgeye (`9.6.5.1`).
        """
        return IM.Sources(self._base_dir(doc),
                          absolute=doc["path"] in self._absolute_ok,
                          url=bool(self._settings.get("images", {}).get("allow_url")))

    def _doc_summary(self, doc: dict) -> dict:
        renamed = self._renamed_paths(doc)      # 10.6 — adi degisen tablolar
        return {
            "id": doc["path"],
            "name": doc["name"],
            "path": doc["path"],
            "size": doc["size"],
            "dirty": EC.dirty(doc["history"]),   # 10.4 — kaydedilmemis degisiklik
            "datasets": [
                {
                    "id": ds.id, "label": self._ds_label(doc, ds), "kind": ds.kind,
                    "kind_label": ds.kind_label, "rows": ds.row_count,
                    "cols": ds.col_count, "notes": ds.note_texts,
                    "edited": tuple(ds.path) in renamed,
                    # 9.25 — icerigi kaydedilmeden degisti (hucre ya da sutun adi).
                    "dirty": self._ds_changed(doc, ds, None),
                    "variants": [
                        {"id": v.id, "label": v.label, "rows": v.row_count, "cols": v.col_count,
                         "dirty": self._ds_changed(doc, ds, v.id)}
                        for v in ds.variants
                    ],
                }
                for ds in doc["datasets"]
            ],
        }
