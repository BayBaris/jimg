"""API anahtarlarinin sifreli deposu (Faz 9.5.2, `K-23`).

Anahtarlar `settings.json`da DURMAZ: o dosya duz metin, elle duzenlenebilir ve
kullanici onu kolayca kopyalayip paylasiyor. Anahtarlar ayri bir kapta,
**Windows DPAPI** ile sifrelenmis olarak tutulur (`%APPDATA%\\JSON Imager\\
keys.json`). DPAPI'nin secilme sebebi `K-23`te yazili: yeni bagimlilik
getirmiyor ve cozme yetkisi isletim sistemi tarafindan **o kullanici hesabina**
bagli — dosyanin kendisi baska bir makineye kopyalansa ise yaramaz.

⚠ **Duz metne DUSULMEZ.** DPAPI bulunamazsa ya da sifreleme basarisiz olursa
anahtar **yazilmaz** ve hata dondurulur. "Sifreleyemedim, oyleyse duz yazayim"
davranisi kullaniciya sifreli sanacagi bir dosya birakirdi; kabul edilebilir
tek sonuc, anahtarin hic kaydedilmemesidir.

⚠ **Cozulmus anahtar KOPRUDEN GECMEZ.** `read()` yalnizca Python tarafinda,
saglayici cagrisini kurarken cagrilir. Arayuze giden tek bilgi "kayitli mi"dir
(`names()`), tipki `9.12`de ayar dosyasinin yolunun kopruden cikarilmasi gibi:
tasinmasi gerekmeyen bir sirri tasimak, onu bir gun bir tanilama metnine
sizdirmanin en kolay yoludur.

⚠ **Kap bicimi ile sir ayrildi.** Dosya okunabilir bir JSON'dur, degerler
base64'lenmis DPAPI bloblaridir. Boylece bozuk bir girdi otekileri dusurmez ve
kabin kendisi (hangi saglayicilarin anahtari var) ayrica cozulmeden okunabilir.

⚠ **Cozulemeyen girdi SILINMEZ.** Baska bir hesapta uretilmis bir blob burada
cozulmez; `read()` `None` doner ve hata cagri aninda, anlasilir bicimde cikar.
Sessizce silmek, kullanicinin dosyayi geri getirebilecegi durumu (yanlis
hesapla acilmis oturum) geri donulmez yapardi.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import json
import os
import re
from ctypes import wintypes
from pathlib import Path

from . import i18n as I18N
from .paths import config_dir

FILE_NAME = "keys.json"
BACKUP_NAME = "keys.bak"

# Ad, dosyada anahtar olarak ve saglayici kimligi olarak kullaniliyor; serbest
# metin kabul etmek kabi bozabilirdi. Kalip saglayici anahtarlarinin kalibidir
# (`providers.CLI` ve kardesleri).
NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")

# DPAPI'ye verilen ek entropi. **Sir degildir** — exe'nin icinden okunabilir;
# isi, ayni kullanici hesabinda calisan baska bir programin blobu kazara ya da
# ugrasmadan cozmesini engellemek. Degistirilirse eski kayitlar cozulmez.
_ENTROPY = b"JSON Imager/keys/v1"

# CRYPTPROTECT_UI_FORBIDDEN: cagri hicbir kosulda pencere acmasin. Arayuz zaten
# pywebview penceresinin icinde; DPAPI'nin acacagi bir istem oraya cizilemez ve
# uygulama yanit bekleyerek kilitlenirdi.
_UI_FORBIDDEN = 0x1


class KeyStoreError(Exception):
    """Kullaniciya GOSTERILEBILIR hata; mesaj zaten cevrilmistir.

    `providers.ProviderError` ile ayni sozlesme: cagiran mesaji oldugu gibi
    arayuze verir, teknik ayrinti disarida kalir.
    """


class _Blob(ctypes.Structure):
    """DPAPI'nin `DATA_BLOB` yapisi: uzunluk + bayt isaretcisi."""

    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _load_api():
    """crypt32/kernel32'yi baglar; Windows disinda `None` doner.

    Imza ELLE bildirilir: bildirilmezse ctypes donus tipini `int` sayar ve
    64 bitte isaretci donduren cagrilarda degeri kirpar.
    """
    try:
        crypt32 = ctypes.WinDLL("crypt32")
        kernel32 = ctypes.WinDLL("kernel32")
    except (AttributeError, OSError):
        return None, None

    blob_p = ctypes.POINTER(_Blob)
    crypt32.CryptProtectData.argtypes = [blob_p, wintypes.LPCWSTR, blob_p,
                                         ctypes.c_void_p, ctypes.c_void_p,
                                         wintypes.DWORD, blob_p]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [blob_p, ctypes.c_void_p, blob_p,
                                           ctypes.c_void_p, ctypes.c_void_p,
                                           wintypes.DWORD, blob_p]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


_CRYPT32, _KERNEL32 = _load_api()


def path() -> Path:
    return config_dir() / FILE_NAME


def available() -> bool:
    """DPAPI bu sistemde var mi? Ayarlar ekrani alani buna gore acar."""
    return _CRYPT32 is not None


def _buffer(data: bytes) -> tuple[_Blob, ctypes.Array]:
    """`DATA_BLOB` ve ONU BESLEYEN tamponu birlikte dondurur.

    ⚠ Ikisi birlikte donmek zorunda: yapinin icindeki isaretci tampona bakiyor
    ve tampon yalnizca yerel degisken olsaydi cagri sirasinda toplanip
    serbestlestirilebilirdi. Cagiran ikisini de canli tutar.
    """
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _take(out: _Blob) -> bytes:
    """DPAPI'nin ayirdigi tamponu kopyalar ve **serbest birakir**."""
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _KERNEL32.LocalFree(out.pbData)


def _protect(raw: bytes) -> bytes:
    if _CRYPT32 is None:
        raise KeyStoreError(I18N.t("err.keys_unavailable"))
    src, src_buf = _buffer(raw)
    ent, ent_buf = _buffer(_ENTROPY)
    out = _Blob()
    ok = _CRYPT32.CryptProtectData(ctypes.byref(src), None, ctypes.byref(ent),
                                   None, None, _UI_FORBIDDEN, ctypes.byref(out))
    del src_buf, ent_buf
    if not ok:
        raise KeyStoreError(I18N.t("err.keys_encrypt"))
    return _take(out)


def _unprotect(blob: bytes) -> bytes | None:
    """Cozulemezse `None` — istisna DEGIL.

    Cozulememe beklenen bir durum (baska hesapta uretilmis kayit, entropi
    degismis eski kayit) ve okuma yolunun tamamini dusurmemeli; cagiran onu
    "anahtar yok" gibi ele alir.
    """
    if _CRYPT32 is None:
        return None
    src, src_buf = _buffer(blob)
    ent, ent_buf = _buffer(_ENTROPY)
    out = _Blob()
    ok = _CRYPT32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent),
                                     None, None, _UI_FORBIDDEN, ctypes.byref(out))
    del src_buf, ent_buf
    if not ok:
        return None
    return _take(out)


def _read_container(target: Path | None = None) -> dict[str, str]:
    """Kabi okur. HICBIR KOSULDA istisna firlatmaz.

    Bozuk dosya `keys.bak`a alinir ve bos kapla devam edilir — `settings.py`
    ile ayni kalip; ayarlar gibi anahtarlar da bir kolayliktir ve uygulamanin
    acilmasina engel olmamali.
    """
    p = target or path()
    try:
        raw = p.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _quarantine(p)
        return {}

    if not isinstance(data, dict):
        _quarantine(p)
        return {}
    return {k: v for k, v in data.items()
            if isinstance(k, str) and isinstance(v, str) and NAME_RE.match(k)}


def _quarantine(p: Path) -> None:
    try:
        p.replace(p.with_name(BACKUP_NAME))
    except OSError:
        pass


def _write_container(data: dict[str, str], target: Path | None = None) -> None:
    """Kabi ATOMIK yazar; bosaldiysa dosyayi SILER.

    Yazim `settings.save` ile ayni: once gecici dosya, sonra `os.replace`.
    Silme kismi ona ek — son anahtar kaldirildiginda geride bos bir kap
    birakmak, kullaniciya hala bir sey saklandigini dusundururdu.
    """
    p = target or path()
    if not data:
        try:
            p.unlink()
        except OSError:
            pass
        return

    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, p)


def names(target: Path | None = None) -> list[str]:
    """Anahtari KAYITLI olan saglayicilar. Disariya cikan tek bilgi budur.

    ⚠ Girdinin cozulup cozulmedigine BAKILMAZ: bakmak, her durum sorgusunda
    anahtari bellege acmak demekti. Cozulemeyen bir kayit `read()`te ortaya
    cikar ve hata cagri aninda anlasilir bicimde verilir.
    """
    return sorted(_read_container(target))


def has(name: str, target: Path | None = None) -> bool:
    return name in _read_container(target)


def read(name: str, target: Path | None = None) -> str | None:
    """Cozulmus anahtar — YALNIZCA Python tarafi icin. Yoksa `None`.

    ⚠ Bu degerin kopruden gecen bir donuse, gunluge ya da hata mesajina
    girmemesi gerekiyor (modul basligi).
    """
    blob = _read_container(target).get(name)
    if not blob:
        return None
    try:
        raw = base64.b64decode(blob, validate=True)
    except (binascii.Error, ValueError):
        return None
    plain = _unprotect(raw)
    if plain is None:
        return None
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return None


def store(name: str, value: str, target: Path | None = None) -> None:
    """Anahtari sifreleyip kaydeder. Basarisizlikta DISKE DOKUNMAZ."""
    if not NAME_RE.match(name or ""):
        # Cagiran hatasi, kullanici hatasi degil: cevrilmis mesaj uretilmez.
        # ⚠ Metin BOSLUKSUZ tutuluyor: `check_py_strings` bosluklu her dizeyi
        # "sozluge girmemis cumle" sayiyor ve hakli — bu dize kullaniciya
        # gitmedigi icin sozluge girmemeli, o yuzden cumle de olmamali.
        raise ValueError(f"invalid_provider_name:{name!r}")

    value = (value or "").strip()
    if not value:
        raise KeyStoreError(I18N.t("err.keys_empty"))

    blob = _protect(value.encode("utf-8"))       # basarisizsa buradan cikar
    data = _read_container(target)
    data[name] = base64.b64encode(blob).decode("ascii")
    try:
        _write_container(data, target)
    except OSError as exc:
        raise KeyStoreError(I18N.t("err.keys_write", error=exc)) from None


def clear(name: str, target: Path | None = None) -> None:
    """Anahtari siler. Yoksa sessiz gecer — silme istegi hep basarilidir."""
    data = _read_container(target)
    if data.pop(name, None) is None:
        return
    try:
        _write_container(data, target)
    except OSError as exc:
        raise KeyStoreError(I18N.t("err.keys_write", error=exc)) from None
