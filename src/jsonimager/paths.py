"""Calisma zamani yollari: varlik klasoru ve proje koku.

`app.py`'den AYRI durur cunku `api_docs` de `project_root()`u cagiriyor ve
`app`i ice aktarsaydi dongusel bir zincir dogardi (`app` → `api_docs` → `app`).

⚠ Dondurulmus (PyInstaller) calismada UC FARKLI klasor vardir ve
karistirilmamalidir:
  `sys._MEIPASS`   — varliklarin cikarildigi GECICI dizin   → `asset_dir()`
  `sys.executable` — exe'nin durdugu klasor                 → `project_root()`
  `%APPDATA%`      — kullaniciya ait, KALICI yazma alani    → `config_dir()`
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "JSON Imager"


def asset_dir() -> Path:
    """`web/` klasoru. PyInstaller ile paketlendiginde gecici cikarma dizinine bakar."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "jsonimager" / "web"
    return Path(__file__).resolve().parent / "web"


def icon_path() -> Path | None:
    """Pencere simgesi (`assets/icon.ico`), yoksa `None`.

    ⚠ `examples_dir()`in aksine **kopyalanmaz**: simge yalnizca acilista
    okunur, agacta bir yol olarak gorunmez. Gecici `_MEIPASS` yolu burada
    sorun degil.

    Dosya yoksa `None` doner ve pencere isletim sisteminin varsayilan
    simgesiyle acilir — eksik bir simge uygulamayi dusurmemeli.
    """
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else project_root()
    p = root / "assets" / "icon.ico"
    return p if p.is_file() else None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def project_root() -> Path:
    """Gelistirmede depo koku, paketlenmis exe'de exe'nin bulundugu klasor.

    `startup()` buradaki `samples/` klasorunu arar; exe yaninda boyle bir
    klasor varsa acilir, yoksa agac bos baslar ve kullanici dosya diyalogunu
    kullanir.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def config_dir() -> Path:
    """Kullanici ayarlarinin klasoru: `%APPDATA%\\JSON Imager\\`.

    Exe'nin YANI DEGIL: Program Files altina kurulmus bir uygulama oraya
    yazamaz. `%APPDATA%` kullaniciya aittir ve exe silinse de kalir.

    Klasor burada OLUSTURULMAZ — yalnizca yol dondurulur. Olusturmak yazan
    tarafin isi (`settings.save`), boylece salt okuma cagrilari diske dokunmaz.
    """
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME

    # Windows disi ortam ya da APPDATA tanimsiz: XDG alisverisine dus. Arac
    # Windows hedefli ama gelistirme/dogrulama baska yerde de kosabilmeli.
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / APP_DIR_NAME


def examples_dir() -> Path | None:
    """Ilk calistirmada agacta gorunecek ornek belgelerin klasoru.

    Gelistirmede depodaki `examples/` DOGRUDAN kullanilir: dosyayi duzenleyince
    sonuc hemen gorunur, araya kopya girmez.

    ⚠ Dondurulmus calismada durum farkli. Ornekler exe'nin icinde gelir ve
    `sys._MEIPASS` altina cikar — orasi **gecici** bir klasordur, uygulama
    kapaninca silinir ve yolu her acilista degisir. Agacta boyle bir yol hem
    cirkin durur hem de kullanicinin "dosyam nerede" sorusunu yanitsiz birakir.
    Bu yuzden ornekler bir kez `%APPDATA%` altina KOPYALANIR; oradan sonra
    kalicidirlar, kullanici silebilir ve yol anlamli kalir.

    Kopyalama basarisiz olursa `None` doner — ornekler bir kolayliktir,
    uygulamanin acilmasina engel olmamali.
    """
    if not is_frozen():
        src = project_root() / "examples"
        return src if src.is_dir() else None

    target = config_dir() / "examples"
    if target.is_dir():
        return target

    src = Path(getattr(sys, "_MEIPASS", "")) / "examples"
    if not src.is_dir():
        return None
    try:
        shutil.copytree(src, target)
    except OSError:
        return None
    return target
