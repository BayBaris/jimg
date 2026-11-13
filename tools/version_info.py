"""Exe'nin surum kunyesi (Faz 9.9.1) — tek kaynak `jsonimager.__version__`.

`build.spec` bunu ice aktarir ve `EXE(version=build())` yazar; boylece Windows'un
Ozellikler > Ayrintilar sekmesindeki surum, Hakkinda penceresindekiyle AYNI
yerden gelir. Kunye elle yazilsaydi surum yukseltilirken iki yer guncellenir,
biri unutulurdu.

Saf kisim (`read_version`, `file_version`, `copyright_line`) PyInstaller
gerektirmez — `check.py` onlari PyInstaller kurulu olmayan agacta da sinar.
`build()` PyInstaller'i ICERIDE ice aktarir.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = "JSON Imager"
# ABD Ingilizcesi + Unicode kod sayfasi. Kunye metinleri (urun adi, telif)
# dilden bagimsiz; tek bir dil tablosu yeterli.
LANG_CODEPAGE = "040904B0"


def read_version(root: Path = ROOT) -> str:
    """`__version__`i paketi ICE AKTARMADAN okur (derleme tanimi paketi yuklemesin)."""
    text = (root / "src" / "jsonimager" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise ValueError("jsonimager/__init__.py icinde __version__ bulunamadi")
    return m.group(1)


def file_version(version: str) -> tuple[int, int, int, int]:
    """Windows'un dort parcali sayisal surumu: `1.2.3` -> (1, 2, 3, 0).

    Sayisal olmayan ek (`1.0.0rc1`) o parcada kesilir; metin hali
    (`FileVersion` dizgesi) eki tasimaya devam eder.
    """
    nums: list[int] = []
    for part in version.split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        nums.append(int(m.group(0)))
        if m.end() != len(part):
            break
    return tuple((nums + [0, 0, 0, 0])[:4])   # type: ignore[return-value]


def copyright_line(root: Path = ROOT) -> str:
    """`LICENSE`in telif satiri — kunye ile lisans ayni sahibi soyler."""
    for line in (root / "LICENSE").read_text(encoding="utf-8").splitlines():
        if line.startswith("Copyright"):
            return line.strip()
    raise ValueError("LICENSE icinde telif satiri bulunamadi")


def strings(root: Path = ROOT) -> dict[str, str]:
    """Kunyenin metin alanlari."""
    version = read_version(root)
    return {
        "ProductName": PRODUCT,
        "FileDescription": PRODUCT,
        "InternalName": PRODUCT,
        "OriginalFilename": f"{PRODUCT}.exe",
        "FileVersion": version,
        "ProductVersion": version,
        "LegalCopyright": copyright_line(root),
    }


def build(root: Path = ROOT):
    """`EXE(version=)` icin `VSVersionInfo` nesnesi."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
        VSVersionInfo,
    )

    numbers = file_version(read_version(root))
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0,
                          OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable(
                LANG_CODEPAGE, [StringStruct(k, v) for k, v in strings(root).items()])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
