"""`Api`nin ayar yuzu: tercihleri okur, yazar, varsayilana dondurur.

Ayarlar `Api.__init__` icinde BIR KEZ yuklenir ve `self._settings` icinde durur;
her okuma diske gitmez. Yazma anlik: `settings_set` cagrisi hem bellegi hem
dosyayi gunceller, boylece uygulama beklenmedik bicimde kapansa da tercih kalir.

Arayuz yalnizca **degisen anahtari** gonderir (`apply_patch`). Tamamini
gondermek, iki pencere acikken birinin digerinin degisikligini ezmesi demekti.
"""

from __future__ import annotations

import platform
import sys
import traceback
from typing import Any

from . import i18n as I18N
from . import providers as P
from . import settings as S
from . import theme as TH
from .paths import is_frozen


# Ucuncu taraf atiflari (Faz 9.3.4). Degerler kurulu paketlerin metadata'sindan
# OKUNARAK yazildi, ezberden degil.
#
# ⚠ Liste ELLE tutulur ama denetlenir: `check.py --> check_about` her girdiyi
# `importlib.metadata` ile karsilastirir. Calisma aninda okumak daha cazip
# gorunuyor, ama PyInstaller dist-info'yu her paket icin gomuyor — dondurulmus
# exe'de liste sessizce bosalirdi. Elle liste + denetim, sessiz bosalmadan iyi.
THIRD_PARTY = (
    ("pywebview", "6.2.1", "BSD-3-Clause"),
    ("pythonnet", "3.1.0", "MIT"),
    ("pillow", "12.3.0", "MIT-CMU"),
)


class SettingsMixin:
    """Kullanici tercihleri ve uygulama kunyesi."""

    def settings_get(self) -> dict:
        """Gecerli ayarlar.

        ⚠ **Dosya yolu DONMEZ** (`9.12`). Once ayarlar ekraninin altbilgisinde
        gosteriliyordu; kaldirilinca kopruden de cikarildi, cunku kullanici adi
        iceren bir degeri "belki lazim olur" diye tasimak onu bir gun tanilama
        metnine ya da bir hata mesajina sizdirmanin en kolay yoludur.
        """
        return {"ok": True, "settings": self._settings, "defaults": S.defaults()}

    def strings(self) -> dict:
        """Kabugun acilis sunumu: sozluk, dil ve tema.

        Sozlugun TEK KAYNAGI Python'dur (`i18n.STRINGS`). Arayuz kendi
        kopyasini tutmaz; iki sozluk zamanla birbirinden sapardi ve sapmayi
        kimse fark etmezdi.

        `lang`, `theme` ve `font` burada birlikte durur cunku ucu de ayni sey:
        **Python'da cozulmus** bir tercih (`auto` → `tr`, `system` → `dark`) ve
        arayuz ucunu de kok ogeye yaziyor (`<html lang>`, `data-theme`,
        `data-font`). Tercihin ham hali ayarlar ekraninda gorunur
        (`settings_get`).
        """
        return {"ok": True, **self._shell(),
                "langs": list(I18N.CHOICES), "themes": list(TH.CHOICES),
                "fonts": list(TH.FONTS), "sizes": list(TH.FONT_SIZES),
                "densities": list(TH.DENSITIES),
                "exportThemes": list(TH.EXPORT_THEMES),
                # Saglayici listesi de ayni yerden: dil/tema/yazi tipiyle ayni
                # kalip, arayuzde sabitlenmis ikinci bir kopya yok. Etiketler
                # ANAHTAR olarak gidiyor (`provider.<k>.label`), digerlerinde
                # oldugu gibi — cozum arayuzde, cagri aninda.
                "providers": list(P.PROVIDERS),
                "strings": I18N.table()}

    def settings_set(self, patch: dict | None = None) -> dict:
        """Kismi degisikligi uygular ve diske yazar.

        Dil, tema ya da yazi tipi degistiyse ilgili modul de guncellenir
        (`_apply_prefs`). Donen degerler COZULMUS haldedir: arayuz onlari kok
        ogeye yaziyor ve cizim de ayni degerleri okuyor — tek karar noktasi.
        """
        try:
            before = self._settings
            self._settings = S.apply_patch(self._settings, patch or {})
            self._apply_prefs()
            self._after_change(before)
            S.save(self._settings)
        except OSError as exc:
            # Diske yazilamadi (salt okunur profil, dolu disk). Bellekteki
            # deger yine de gecerli: kullanici oturum boyunca kullanabilsin.
            return self._reply(I18N.t("err.settings_write", error=exc))
        except Exception:
            return self._reply(traceback.format_exc(limit=3))
        return self._reply()

    def settings_reset(self) -> dict:
        """Tum tercihleri varsayilana dondurur."""
        try:
            before = self._settings
            self._settings = S.defaults()
            self._apply_prefs()
            self._after_change(before)
            S.save(self._settings)
        except OSError as exc:
            return self._reply(I18N.t("err.settings_write", error=exc))
        return self._reply()

    def _reply(self, error: str | None = None) -> dict:
        """Iki yazicinin da ortak donusu: ayarlar + cozulmus kabuk sunumu.

        Bes ayri yerde elle kurulan sozluktu; yeni bir ortak alan eklendiginde
        besini birden guncellemek gerekiyordu — `_apply_prefs`in anlattigi
        tuzagin donus tarafindaki karsiligi.
        """
        out = {"ok": error is None, "settings": self._settings, **self._shell()}
        if error is not None:
            out["error"] = error
        return out

    def _after_change(self, before: dict) -> None:
        """Bir ayar DEGISTIGINDE bir kez yapilmasi gereken isler (9.19).

        `_apply_prefs` her cagrida ayni sonucu verir (durumu kurar); buradakiler
        ise GECISE baglidir ve iki yazicinin (`settings_set`, `settings_reset`)
        ikisinde de calismali.
        """
        def pick(data: dict, group: str, key: str):
            return (data.get(group) or {}).get(key)

        # Sarma kapandi: "uzun metin" diye gizlenen sutunlarin gerekcesi kalmadi.
        if pick(before, "table", "wrap") is not False and not self._wrap():
            self._unhide_long()

        # Geri yukleme acildi → o anki oturum yazilir; kapandi → yollar diskten
        # SILINIR. Kapali bir ayarin dosyasi geride kalmamali.
        was, now = bool(pick(before, "documents", "restore")), self._restoring()
        if now and not was:
            self._save_session()
        elif was and not now:
            S.clear_session()

    def _apply_prefs(self) -> None:
        """Ayarlari surece uygular: dil, tema, yazi tipi.

        ⚠ Uc cagri yeri var (`Api.__init__`, `settings_set`, `settings_reset`)
        ve UCU DE ayni islemi yapmali. Once `set_lang` uc yere elle yazilmisti;
        tema eklenince biri unutulsaydi "ayarlari sifirla" dedikten sonra tema
        eski kalirdi — kullanicinin sebebini bulamayacagi bicimde. Yeni bir
        tercih eklenirse BURAYA yazilir.
        """
        I18N.set_lang(self._settings.get("language"))
        TH.set_theme(self._settings.get("theme"))
        font = self._settings.get("font") or {}
        TH.set_font(font.get("family"))
        TH.set_size(font.get("size"))
        TH.set_density((self._settings.get("table") or {}).get("density"))

    def _shell(self) -> dict:
        """Arayuzun kok ogeye yazdigi COZULMUS tercihler.

        Uc donusun de tasidigi ortak parca (`strings`, `settings_set`,
        `settings_reset`); tek yerde durur ki biri eksik kalmasin.

        ⚠ `metrics` de buradan gider: puntodan tureyen olculeri ekran da
        kullaniyor (baslik satiri, grup seridi, tip rozeti). Formulu CSS'e
        `calc()` ile ikinci kez yazmak iki calisma zamaninda IKI formul demek
        olurdu — paletin `--danger: var(--danger)` kazasinin olcu karsiligi.
        Tek kaynak `theme.metrics()`; arayuz cozulmus sayilari kok ogeye yazar.
        """
        return {"lang": I18N.get_lang(), "theme": TH.get_theme(),
                "font": TH.get_font(), "fontSize": TH.get_size(),
                "metrics": TH.metrics()._asdict(),
                # 9.19.4 — arayuz Agent dugmesini buna gore gizler.
                "agent": self._agent_enabled()}

    def app_info(self) -> dict:
        """Hakkinda penceresinin kunyesi.

        ⚠ **Dosya yolu ICERMEZ** — bu sozluk tanilama metnine de besleniyor ve
        orada kullanici adi/klasor yapisi disari cikmamali. Ayar dosyasinin yolu
        `settings_get()` ile ayri gelir ve YALNIZCA ayarlar ekraninda gorunur.

        Son hata mesaji da BILEREK yok: `err.write_failed` gibi mesajlar
        `OSError`i oldugu gibi tasiyor ve o da dosya yolu iceriyor — tanilamaya
        koymak yol sizdirmanin en kolay yolu olurdu.
        """
        return {
            "ok": True,
            "name": "JSON Imager",
            "version": _app_version(),
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()}",
            "frozen": is_frozen(),
            # 9.9.2 — yerel depodan okunur, aga cikmaz. Paketlenmis uygulamada
            # HTTPS'in sertifika bulup bulmadiginin ilk kaniti.
            "tls_roots": _tls_roots(),
            "language": I18N.get_lang(),
            "third_party": [{"name": n, "version": v, "license": lic}
                            for n, v, lic in THIRD_PARTY],
        }


def _tls_roots() -> int:
    """`providers.tls_roots` — ice aktarma cagri anindadir; `providers` acilis
    yolunda degil ve Hakkinda penceresi acilmadan yuklenmesi gerekmiyor."""
    from . import providers
    return providers.tls_roots()


def _app_version() -> str:
    """Surumun TEK kaynagi `jsonimager.__version__`.

    Paket kendi kendini ice aktardigi icin dogrudan degil, modul uzerinden
    okunur — `__init__` bu moduleu de ice aktarabilir ve dongu dogardi.
    """
    return getattr(sys.modules.get("jsonimager"), "__version__", "0.0.0")
