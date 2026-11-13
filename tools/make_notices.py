r"""THIRD-PARTY-NOTICES.md ureteci.

Belge ELLE yazilmaz: lisans metinleri ~200 KB ve kurulu paketlerden okunur. Kapi
(`check.py --> check_notices`) depodaki dosyanin bu ureticinin BUGUNKU ciktisiyla
ayni oldugunu dogrular; bir bagimlilik yukseltilince kirmizi yanar ve belge
yeniden uretilir.

Kaynaklar:
  - `requirements.txt` calisma zamani kapanisi (`check.runtime_closure`) — her
    dagitimin dist-info icindeki lisans dosyalari
  - Python calisma zamani: `sys.base_prefix/LICENSE.txt` + CPython'un gomulu
    yazilim bildirimi (`licenses/cpython-incorporated.txt`)
  - PyInstaller onyukleyicisi ve calisma zamani kancalari: `COPYING.txt`
  - Yerelde metni olmayan Microsoft bilesenleri: `licenses/` (kaynak basliginda)

Calistirma:
    .\.venv\Scripts\python.exe tools\make_notices.py
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distribution
from pathlib import Path

from check import ROOT, runtime_closure

OUT = ROOT / "THIRD-PARTY-NOTICES.md"
LICENSES = ROOT / "licenses"

# Paket olmayan bilesenler: (baslik, `licenses/` dosyasi ya da None, ozet lisans).
# Surum `licenses/` dosyasinin `Version:` satirindan okunur — tek yer.
VENDORED = (
    ("Microsoft WebView2 SDK", "webview2-sdk.txt", "BSD-3-Clause-style (Microsoft)"),
    (".NET Standard facade assemblies", "dotnet-standard.txt", "MIT"),
    # 9.10.3 / `AK-18`: Python calisma zamanina gomulu, ama CPython'un kendi iki
    # bildiriminde ADIYLA gecmeyen iki bilesen. Surum CPython 3.14.6 kaynagindan.
    ("HACL*", "hacl-star.txt", "MIT"),
    ("zlib-ng", "zlib-ng.txt", "Zlib"),
)


def anchor(title: str) -> str:
    """GitHub baslik capasi: kucuk harf, bosluk tire, noktalama duser."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def _dist_license_files(name: str) -> list[Path]:
    dist = distribution(name)
    files = [f for f in (dist.files or [])
             if ".dist-info" in str(f) and re.search(r"licen[cs]e|copying|notice|authors",
                                                     Path(str(f)).name, re.I)]
    return sorted((Path(str(dist.locate_file(f))) for f in files), key=lambda p: p.name)


def _license_id(name: str) -> str:
    """Ozet tablo icin lisans: metadata ifadesi > kisa `License` > dosyanin ilk satiri."""
    meta = distribution(name).metadata
    if expr := meta.get("License-Expression"):
        return expr
    short = (meta.get("License") or "").strip()
    if short and "\n" not in short and len(short) <= 40:
        return short
    for path in _dist_license_files(name):
        first = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0]
        if re.search(r"licen[cs]e", first, re.I) and len(first) <= 40:
            return first.strip()
    return "see text"


def vendored(path: Path) -> tuple[dict[str, str], str]:
    """`licenses/` dosyasi: `Anahtar: deger` basligi, `----` satiri, sonra birebir metin."""
    head, _, body = path.read_text(encoding="utf-8").partition("\n----\n")
    fields = dict(line.split(": ", 1) for line in head.splitlines() if ": " in line)
    return fields, body


def _block(text: str) -> str:
    # Satir sonu bosluklari kirpilir (belge standardi); metnin kendisi degismez.
    lines = [line.rstrip() for line in text.strip("\n").splitlines()]
    fence = "````" if any(line.startswith("```") for line in lines) else "```"
    return f"{fence}text\n" + "\n".join(lines) + f"\n{fence}\n"


def build_notices() -> str:
    """Belgenin tamami. Yalnizca okur."""
    sections: list[tuple[str, str, str, str]] = []   # (baslik, surum, lisans, govde)

    for key, version in runtime_closure().items():
        dist = distribution(key)
        title = dist.metadata["Name"]
        files = _dist_license_files(key)
        if files:
            body = "".join(f"`{p.name}`:\n\n{_block(p.read_text(encoding='utf-8', errors='replace'))}\n"
                           for p in files)
        else:
            meta = dist.metadata
            body = (f"The distribution declares `License: {meta.get('License')}` in its metadata "
                    f"and ships no license file. Author: {meta.get('Author')}.\n\n")
        sections.append((title, version, _license_id(key), body))

    py = Path(sys.base_prefix) / "LICENSE.txt"
    cp_fields, cp_text = vendored(LICENSES / "cpython-incorporated.txt")
    sections.append((
        "Python runtime", sys.version.split()[0], "PSF-2.0 and others",
        "The Windows build of CPython, including the Microsoft Visual C++ runtime "
        "and Universal CRT it redistributes.\n\n"
        f"`LICENSE.txt` shipped with the runtime:\n\n{_block(py.read_text(encoding='utf-8'))}\n"
        f"Licenses and acknowledgements for software incorporated in CPython "
        f"(source: {cp_fields['Source']}):\n\n{_block(cp_text)}\n"))

    pyi = distribution("pyinstaller")
    copying = next(p for p in _dist_license_files("pyinstaller") if p.name.startswith("COPYING"))
    sections.append((
        "PyInstaller bootloader", pyi.version, "GPL-2.0-or-later WITH Bootloader-exception",
        "The executable starts through the PyInstaller bootloader and run-time hooks. "
        "The bootloader exception permits distributing the resulting program under "
        "its own license; the run-time hooks are Apache-2.0. No other PyInstaller "
        "code is bundled.\n\n"
        f"`{copying.name}`:\n\n{_block(copying.read_text(encoding='utf-8'))}\n"))

    for title, filename, lic in VENDORED:
        fields, text = vendored(LICENSES / filename)
        sections.append((title, fields["Version"], lic,
                         f"{fields['Scope']}\n\nSource: {fields['Source']}\n\n{_block(text)}\n"))

    out = [
        "# Third-Party Notices\n",
        "<!-- Generated by tools/make_notices.py from the installed packages. Do not edit. -->\n",
        "JSON Imager is licensed under the MIT License (see `LICENSE`). The Windows "
        "executable bundles the components below; each section reproduces the license "
        "text that ships with that component.\n",
        "## Contents\n",
        "| Component | Version | License |\n|---|---|---|",
    ]
    out += [f"| [{t}](#{anchor(t)}) | {v} | {lic} |" for t, v, lic, _ in sections]
    out.append("")
    for title, version, _lic, body in sections:
        out.append(f"## {title}\n")
        out.append(f"Version {version}\n")
        out.append(body.rstrip("\n") + "\n")
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> int:
    OUT.write_text(build_notices(), encoding="utf-8", newline="\n")
    print(f"yazildi: {OUT.name} ({OUT.stat().st_size / 1024:,.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
