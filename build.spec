# PyInstaller spec — tek dosya JSON Imager.exe
#
#   .\.venv\Scripts\python.exe -m PyInstaller build.spec --noconfirm --clean
#
# Dikkat edilen noktalar:
#   web/       arayuz varliklari `jsonimager/web` altina gomulur; `paths.asset_dir()`
#              paketlenmis calismada `sys._MEIPASS` altindan okur.
#   examples/  ornek belgeler kokte gomulur. `paths.examples_dir()` bunlari ilk
#              calistirmada `%APPDATA%` altina KOPYALAR — `_MEIPASS` gecicidir,
#              agacta gorunen yol kalici olmali.
#   assets/    `icon.ico` iki yerde gerekir: EXE(icon=) exe DOSYASININ simgesini
#              belirler, datas'a eklenmesi ise PENCERE simgesini calisma aninda
#              okunabilir kilar (`paths.icon_path()`). Biri digerinin yerine
#              gecmez — yalnizca `EXE(icon=)` yazilirsa pencere varsayilan
#              simgeyle acilir.
#   webview    pywebview kendi JS dosyalarini calisma aninda okur, bu yuzden
#              `collect_all` ile tamami alinir.
#   clr_loader pythonnet'in .NET yukleyicisi; ikili dosyalari toplanmazsa
#              exe acilirken WebView2 arka ucu bulunamaz.
#   kancalar   pywebview ve pythonnet kendi PyInstaller kancalarini paketin ICINDE
#              tasiyor (`__pyinstaller/`, `_pyinstaller/`). `collect_all` onlari alt
#              modul sayip ice aktariyordu; kancalar `PyInstaller.utils.hooks`u,
#              o da PyInstaller'in derleme modullerini exe'ye cekiyordu. Bunlar GPL-2.0
#              ve onyukleyici istisnasinin DISINDA — MIT bir exe'de dagitilamaz.
#              Suzgec kancalari keser, `excludes` geri kalan derleme araclarini.
#              Liste `tools/check.py BUILD_ONLY` ile ayni olmali (`check_bundle`).
#   kunye      exe'nin surum bilgisi (Ozellikler > Ayrintilar) `tools/version_info.py`den
#              gelir ve `jsonimager.__version__`i okur — Hakkinda penceresiyle ayni
#              kaynak. Buraya surum numarasi YAZILMAZ (`check_version_info`).

import os
import sys

from PyInstaller.utils.hooks import collect_all

# `SPECPATH` bu dosyanin klasoru; derleme baska bir dizinden baslatilsa da bulunur.
sys.path.insert(0, os.path.join(SPECPATH, "tools"))
import version_info  # noqa: E402

datas = [("src/jsonimager/web", "jsonimager/web"), ("examples", "examples"),
         ("assets", "assets")]
binaries = []
hiddenimports = ["clr"]


def not_a_hook(name):
    return "_pyinstaller" not in name


for pkg in ("webview", "clr_loader", "pythonnet"):
    d, b, h = collect_all(pkg, filter_submodules=not_a_hook)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Kullanilmayan agir bagimliliklar disarida birakilir; arac yalnizca
    # Pillow kullanir (K-06).
    excludes=["tkinter", "matplotlib", "numpy", "scipy", "pandas",
              "PySide6", "PyQt5", "PyQt6", "test", "unittest", "pydoc",
              # Derleme araclari: calisma zamaninda hicbiri ice aktarilmiyor
              # (`cffi` setuptools'u yalnizca C derleme yolunda istiyor).
              "PyInstaller", "setuptools", "pkg_resources", "_distutils_hack",
              "packaging", "altgraph", "pefile", "ordlookup", "win32ctypes"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="JSON Imager",
    icon="assets/icon.ico",
    version=version_info.build(),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # masaustu uygulamasi: konsol penceresi acilmaz
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
