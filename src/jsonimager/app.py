"""pywebview penceresi ve Python <-> JS kopru sinifi.

Arayuzun Python'a eristigi TEK kapi `Api` sinifidir. Sinifin GOVDESI bes
mixin'e bolunmustur (Faz 8.6); burada yalnizca durum, bilesim ve pencere durur.

⚠ **Mixin, alt nesne DEGIL.** `self.table = TableApi()` gibi bir alt nesne
kurulamaz: pywebview `js_api` niteliklerini OZYINELEMELI gezer (bkz. asagidaki
sinif aciklamasi) ve alt nesnenin icine iner. Mixin'ler siniftir, ornek
niteligi degil — metotlar ornekte DUZ kalir, pywebview bugunkunun aynisini
gorur, kaynak yine de dosyalara ayrilir. Bu, `8.4`'te JS icin verilen kararin
Python'daki karsiligidir: **dosya bolunur, nesne bolunmez.**

Mixin'ler arasi sozlesme: durum burada, `Api.__init__` icinde kurulur; hepsi
`self._docs`, `self._views` gibi alanlari ortak okur. Ayrica birkac yardimci
mixin sinirini asar ve bu KASITLIDIR — `_key` · `_table_for_output` ·
`_safe_name` · `_stem` `api_table`'da, `_base_dir` · `_ds_label` `api_docs`'ta
durur; cikti uretenlerin hepsi ayni tabloyu ayni anahtarla bulmak zorunda.
"""

from __future__ import annotations

import threading
from typing import Any

import webview

from . import settings as S
from .api_agent import AGENT_EFFORT_DEFAULT, AGENT_MODEL_DEFAULT, AgentMixin
from .api_chart import ChartMixin
from .api_docs import DocsMixin
from .api_edit import EditMixin
from .api_export import ExportMixin
from .api_settings import SettingsMixin
from .api_table import TableMixin
from .paths import asset_dir, icon_path

# ⚠ Cizim modulleri (`img_table` · `img_tree` · `img_chart` · `draw`) HICBIR
# `api_*` modulunde tepeden ice aktarilmaz (Faz 8.6). Hepsi Pillow tasiyor ve
# Pillow yalnizca gorsel uretilirken gerekiyor; tepeye yazilirsa acilista 56 ms
# bosuna harcanir ve hicbir gorsel istemeyen oturum da bedelini oder. Ice
# aktarma, gercekten cizen metotlarin icindedir.
#
# `chart_data` bu kisitin DISINDADIR: Pillow'a dokunmaz ve `chart_columns`
# arayuz her veri kumesi actiginda cagriliyor.
# Zincir `check.py --> check_import_chain` ile denetlenir.

WINDOW_TITLE = "JSON Imager"

# En kucuk pencere (9.14.3). Birim MANTIKSAL piksel ve olcu CERCEVE DAHIL:
# pywebview WinForms'ta `MinimumSize`i ekran olcegiyle carpip dis boyuta
# yaziyor. Icerik yaklasik 16 px dar, 39 px kisa kalir -> 784x421.
# - Ust sinir hedef kucuk ekran: %150 olcekli 1366x768'in calisma alani
#   910x464 (gorev cubugu 48). 960x580 o ekrana hic sigmiyordu.
# - Alt sinir olcumle: 784 = Ayarlar (760) + dar kaplama boslugu (2x12);
#   Agent seridi kapaliyken kenar cubugu + ana alan 756 px'e sigiyor.
# Denetim: `check.py --> check_web` 9. madde.
WINDOW_MIN_W, WINDOW_MIN_H = 800, 460


class Api(DocsMixin, TableMixin, EditMixin, ChartMixin, AgentMixin, ExportMixin,
          SettingsMixin):
    """JS tarafindan `pywebview.api.<metot>()` ile cagrilir.

    DIKKAT: Butun ic durum alt cizgi ile baslamak ZORUNDA. pywebview, js_api
    nesnesinin alt niteliklerini ozyinelemeli olarak gezip JS'e acilacak
    metotlari cikarir (webview/util.py get_functions) ve alt cizgi ile
    baslamayan her nesnenin ICINE iner. `self.window = window` yazildiginda
    pywebview WinForms/COM nesnelerinin icinde kaybolup "maximum recursion
    depth exceeded" hatalari uretir. Yalnizca metotlar public olmali.

    Mixin sirasi davranisi degistirmez — metot adlari cakismaz — ama okuma
    sirasini verir: belge → tablo → duzenleme → grafik → agent → disa aktarim →
    ayarlar.
    """

    def __init__(self) -> None:
        # Ayarlar BIR KEZ yuklenir; her okuma diske gitmez. `load()` hicbir
        # kosulda istisna firlatmaz, bozuk dosya varsayilana duser.
        self._settings: dict[str, Any] = S.load()
        # Dil ve tema, belge okunmadan ONCE kurulmali: uretilen sutun basliklari
        # ve tur adlari `i18n`den geliyor ve `startup()` ilk belgeyi hemen
        # aciyor. Ikisini de `_apply_prefs` kuruyor (`api_settings`) — ayni
        # islem ayarlar degisince ve sifirlaninca da yapilmali, uc yere elle
        # yazilsaydi biri unutulurdu.
        self._apply_prefs()
        self._window: webview.Window | None = None
        self._docs: dict[str, dict] = {}     # doc_id -> {name, path, root, datasets}
        self._folders: list[dict] = []       # acilan klasor agaclari
        self._views: dict[str, dict] = {}    # gorunum anahtari -> durum
        self._transposed: set[str] = set()   # transpoze acik olan tablolar
        self._chats: dict[str, list[dict]] = {}   # doc_id -> Agent sohbet dizisi
        self._absolute_ok: set[str] = set()  # 9.6.5.1 — mutlak yola izin verilen belgeler
        self._model = AGENT_MODEL_DEFAULT    # secili model, oturum boyunca kalir
        self._effort = AGENT_EFFORT_DEFAULT  # secili caba duzeyi
        self._png: bytes | None = None       # son uretilen gorsel (kaydetmek icin)
        self._scene: Any = None              # son uretilen vektor sahnesi (SVG/PDF)
        self._drawio: Any = None             # agac dugum/kenar modeli (.drawio)
        self._quit_ok = False                # 10.5.3 — cikis onaylandi, kapanis sormaz
        self._restored = False               # 9.19.5 — son oturum bu surecte geri acildi


def _fit_screen(window: webview.Window) -> None:
    """Acilis boyutu ekrandan buyukse pencere ekrana kisilir ve buyutulur (9.14.5).

    1420x880, %150 olcekli 1366x768'in calisma alanindan (910x464) buyuk:
    baslik ekranda kaliyordu ama alt kenar gorev cubugunun altina iniyordu.

    `before_show` UI is parcaciginda ve pencere GOSTERILMEDEN calisir (pywebview
    `Event(should_lock=True)`), form dogrudan degistirilir — `Invoke` gerekmez,
    `window.maximize()` ise UI is parcacigini bekleyip kilitlenirdi.
    Karsilastirma formun KENDI olcu uzayinda yapilir: `Size` ve `WorkingArea`
    ayni piksel biriminde, olcek ne olursa olsun donusum gerekmez. Ekran,
    WinForms'un `CenterScreen`de sectigi gibi imlecin bulundugu ekrandir.
    Kisilan boyut, pencere buyutulmus halden geri alininca kullanilir.
    """
    form = window.native
    if form is None:
        return
    from System.Drawing import Size
    from System.Windows.Forms import Cursor, FormWindowState, Screen

    area = Screen.FromPoint(Cursor.Position).WorkingArea
    if form.Width <= area.Width and form.Height <= area.Height:
        return
    form.Size = Size(min(form.Width, area.Width), min(form.Height, area.Height))
    form.WindowState = FormWindowState.Maximized


def _on_closing(api: Api, window: Any) -> bool | None:
    """Pencere kapanirken kaydedilmemis belge varsa kapanisi iptal eder (10.5.3, KB-5).

    ⚠ `closing` UI is parcaciginda EŞZAMANLI calisir ve `False` donerse
    kapanis iptal edilir (pywebview `Event(should_lock=True)`). Buradan JS'i
    BEKLEYEREK cagirmak kilitlenirdi: `evaluate_js` yaniti UI is parcacigindan
    bekliyor, o da bu islevin donmesini. Bu yuzden soru penceresi ayri bir is
    parcacigindan acilir ve islev hemen doner. Kullanici onaylarsa JS
    `quit_app` cagirir; bayrak konur, pencere yeniden kapanir ve bu kez gecer.
    """
    if api._quit_ok or not api.dirty_docs()["docs"]:
        return None
    threading.Thread(target=window.evaluate_js, args=("askQuit()",), daemon=True).start()
    return False


def main() -> None:
    api = Api()
    index = asset_dir() / "index.html"
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(index),
        js_api=api,
        width=1420,
        height=880,
        min_size=(WINDOW_MIN_W, WINDOW_MIN_H),
    )
    api._window = window   # public isim verilemez, sinif docstring'ine bak
    window.events.before_show += _fit_screen
    window.events.closing += lambda: _on_closing(api, window)

    # Simge `create_window`da degil `start`ta verilir — pywebview'de pencere
    # basina degil UYGULAMA capinda bir ayardir. WinForms tarafi dosyayi
    # `System.Drawing.Icon` ile aciyor, yani gercek bir `.ico` sart; PNG
    # kabul edilmez (bkz. platforms/winforms.py).
    icon = icon_path()
    webview.start(icon=str(icon) if icon else None)
