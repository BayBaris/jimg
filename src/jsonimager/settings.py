"""Kullanici ayarlari: yukle, birlestir, kaydet, varsayilana don.

Bu modul, uygulamanin diske **kalici** olarak yazdigi tek yerdir (`K-23`).
Dosya `%APPDATA%\\JSON Imager\\settings.json`; API anahtarlari BURADA DURMAZ,
sifreli ayri bir dosyadadir (`9.5`).

⚠ **Bozuk ayar dosyasi uygulamayi dusurmez.** Cozumlenemeyen dosya
`settings.bak`'a alinir ve varsayilanlarla devam edilir. Ayarlar bir kolayliktir;
kullanicinin belgesini acmasina engel olmamalidir.

⚠ **Gorunum durumu buraya YAZILMAZ.** Sutun genisligi/gizliligi veri kumesi
basinadir ve dosyayi belge sayisiyla sisirirdi; ayrica `K-17` (belge yeniden
acilinca gorunum duser) bozulmus bir gorunumden cikis yolu olarak duruyor.
Burada yalnizca **genel tercihler** tutulur.

Bilinmeyen anahtarlar KORUNUR: kullanici yeni surumde ayar yapip eski surume
donerse, eski surum anlamadigi anahtari silmemeli.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .paths import config_dir

FILE_NAME = "settings.json"
# 9.19.5 — acik belgelerin ve klasorlerin yollari. AYRI dosya, ayarlarin
# icinde degil: ayarlar kopruden arayuze ve tanilama metnine gider, yollar ise
# kullanici adi tasir ve tasinmasi gerekmeyen yere gitmemeli (`9.12`).
SESSION_NAME = "session.json"
BACKUP_NAME = "settings.bak"

# Dosya bicimi surumu. Bir anahtarin ANLAMI ya da TIPI degisirse artirilir ve
# `_migrate`e bir adim eklenir; yeni anahtar eklemek surum artirmaz (eksik
# anahtar zaten varsayilanindan doluyor).
SETTINGS_VERSION = 1

# Her anahtarin tuketildigi asama yorumda yazilidir: sema, fazlarin doldurdugu
# sozlesmedir. Tip de buradan gelir — dosyadaki deger farkli tipteyse
# varsayilana donulur (bkz. `_merge`).
DEFAULTS: dict[str, Any] = {
    "version": SETTINGS_VERSION,
    # 9.2 — "auto": isletim sistemi dili (tr → Turkce, digeri → Ingilizce)
    "language": "auto",
    # 9.4 — "system" isletim sistemi temasini izler; cozum PYTHON'da yapilir
    # (`theme.detect_theme`), yani dilin "auto" degeriyle ayni kalip.
    "theme": "system",
    "font": {
        # 9.4 — `theme.FONTS` anahtari: system | serif | mono
        "family": "system",
        "size": 12,
    },
    # 9.6 — URL varsayilan olarak KAPALI (`K-10`). Mutlak yolun ayari YOK
    # (`9.6.5.1`, karar): izin belge basina verilir ve oturumla biter; kalici
    # bir "her zaman izin ver" anahtari bilerek tanimlanmadi. ⚠ Eski dosyalarda
    # `allow_absolute` alani KALIR: `_merge` bilinmeyen anahtari korur. Hicbir yerde
    # okunmaz ve okunmamasi `check.py -> _check_absolute_policy` ile denetlenir.
    # 9.19.1 / 9.19.2 — tablo govdesi. `density`: `theme.DENSITIES` anahtari.
    # `wrap`: tek satira sigmayan metin sutunu sarilsin mi; kapaliyken kirpilir.
    "table": {
        "density": "normal",
        "wrap": True,
    },
    # 9.19.3 — `theme.EXPORT_THEMES` anahtari: app | light | dark
    "export": {
        "theme": "app",
    },
    "images": {
        "allow_url": False,
        "view": "medium",    # detail | list | small | medium | large
    },
    # 9.5 — "cli": anahtar istemeyen varsayilan yol (`K-13`)
    "agent": {
        # 9.19.4 — kapaliyken serit gizlenir VE kopru soruyu reddeder
        # (`api_agent.agent_ask`); gizleme tek basina bir sinir degildir.
        "enabled": True,
        # 9.27 — `K-14`un istisnasi: aciksa SECILI tablonun gorunen satirlari da
        # gider (sinirli, gorselsiz). Varsayilan KAPALI ve yalnizca acik `True`
        # acar (`api_agent._values_on`) — bozuk bir deger veri gondermez.
        "send_values": False,
        "provider": "cli",
        # 9.21 — ozel saglayicinin adresi, kullanicinin YAZDIGI haliyle. Kural
        # `providers.custom_endpoint`te; hem yazarken hem her kullanimda sinanir.
        "custom_url": "",
        # 9.5.5 — saglayici anahtari -> model kimlikleri. Kullanicinin listesi
        # EKLEME degil TAMAMEN YERINE GECMEDIR: bir saglayicinin girdisi varsa
        # listesi odur, yoksa `Provider.MODELS`. `AK-13`in cozumu bu — yeni bir
        # model cikinca yeni derleme beklenmez, emekliye ayrilan kimlik
        # cikarilabilir.
        #
        # ⚠ **Taban `{}` oldugu icin `_merge` bu agacta TIP DENETIMI YAPMAZ**:
        # bilinmeyen anahtar oldugu gibi korunuyor (yukaridaki kural) ve
        # buradaki her anahtar "bilinmeyen". Dogrulama bu yuzden OKUYAN
        # taraftadir (`api_agent._model_map`), dosyanin kendisinde degil.
        "models": {},
    },
    # 10.4 — KB-4: kaydedilen belgenin oturumdaki ilk hali `<ad>.json.bak`a yazilir.
    "documents": {
        "backup": True,
        # 9.19.5 — acilista son oturumdaki belgeler ve klasorler geri acilir.
        # Varsayilan KAPALI: acikken yollar diske yazilir (`SESSION_NAME`).
        "restore": False,
    },
}


def path() -> Path:
    return config_dir() / FILE_NAME


def defaults() -> dict[str, Any]:
    """Varsayilanlarin KOPYASI. Cagiran uzerinde oynayabilsin diye derin kopya."""
    return copy.deepcopy(DEFAULTS)


def _merge(base: dict[str, Any], loaded: Any) -> dict[str, Any]:
    """Varsayilanlarin uzerine dosyadaki degerleri yazar.

    Uc kural:
      - eksik anahtar  → varsayilan
      - tipi tutmayan  → varsayilan (bozuk deger tuketiciyi dusurmesin)
      - bilinmeyen     → oldugu gibi korunur
    """
    if not isinstance(loaded, dict):
        return copy.deepcopy(base)

    out: dict[str, Any] = {}
    for key, dval in base.items():
        if key not in loaded:
            out[key] = copy.deepcopy(dval)
            continue

        lval = loaded[key]
        if isinstance(dval, dict):
            out[key] = _merge(dval, lval)
        elif _same_kind(dval, lval):
            out[key] = lval
        else:
            out[key] = copy.deepcopy(dval)

    for key, lval in loaded.items():
        if key not in base:
            out[key] = lval
    return out


def _same_kind(dval: Any, lval: Any) -> bool:
    """Tip esitligi. `bool` ONCE bakilir: Python'da `bool` bir `int` alt tipidir
    ve `isinstance(True, int)` dogru doner — kontrol edilmezse `true` bir sayi
    alanina yazilabilirdi."""
    if isinstance(dval, bool) or isinstance(lval, bool):
        return isinstance(dval, bool) and isinstance(lval, bool)
    if isinstance(dval, (int, float)):
        return isinstance(lval, (int, float))
    return type(dval) is type(lval)


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Eski surumleri bugunku bicime tasir.

    Bugun tek surum var, yani yapacak is yok. Yine de ayri bir islev: yeni bir
    surum geldiginde eklenecek yer belli olsun ve cagri zinciri degismesin.
    """
    version = data.get("version")
    if not isinstance(version, int) or version > SETTINGS_VERSION:
        # Gelecekten gelen ya da bozuk surum: anahtarlar yine de birlestirilir,
        # yalnizca surum bugunku degere cekilir.
        data["version"] = SETTINGS_VERSION
    return data


def load(target: Path | None = None) -> dict[str, Any]:
    """Ayarlari okur. HICBIR KOSULDA istisna firlatmaz.

    Dosya yoksa varsayilanlar doner ve diske yazilmaz — ilk calistirmada
    kullanici hicbir sey degistirmediyse ortada dosya da olmaz.
    """
    p = target or path()
    try:
        raw = p.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return defaults()

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        _quarantine(p)
        return defaults()

    return _migrate(_merge(DEFAULTS, loaded))


def _quarantine(p: Path) -> None:
    """Bozuk dosyayi `settings.bak` olarak saklar; kullanici elle kurtarabilsin.

    Basarisiz olursa sessiz gecilir: karantina bir kolayliktir, ayar yuklemenin
    onune gecmemeli.
    """
    try:
        p.replace(p.with_name(BACKUP_NAME))
    except OSError:
        pass


def save(data: dict[str, Any], target: Path | None = None) -> Path:
    """Ayarlari diske yazar ve yazilan yolu dondurur.

    Yazim ATOMIK: once gecici dosyaya yazilir, sonra `os.replace` ile yerine
    konur. Yarim yazilmis bir dosya, bir sonraki acilista karantinaya giderdi.
    """
    p = target or path()
    p.parent.mkdir(parents=True, exist_ok=True)

    data = dict(data)
    data["version"] = SETTINGS_VERSION

    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, p)
    return p


def session_path() -> Path:
    return config_dir() / SESSION_NAME


def load_session(target: Path | None = None) -> dict[str, list[str]]:
    """Son oturumun yollari. HICBIR KOSULDA istisna firlatmaz.

    Dosya yoksa, okunamiyorsa ya da bicimi tutmuyorsa bos oturum doner:
    geri yukleme bir kolayliktir, acilisi durdurmamali. Yalnizca dize olan
    ogeler alinir — dosya elle bozulmus olabilir.
    """
    try:
        data = json.loads((target or session_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = {}
    return {key: [p for p in data.get(key) or () if isinstance(p, str)]
            if isinstance(data.get(key), list) else []
            for key in ("docs", "folders")}


def save_session(docs: list[str], folders: list[str], target: Path | None = None) -> Path:
    """Oturumu diske yazar (atomik, `save` ile ayni kalip)."""
    p = target or session_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"docs": docs, "folders": folders},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def clear_session(target: Path | None = None) -> None:
    """Oturum dosyasini siler. Ayar kapatilinca yollar diskte KALMAZ."""
    try:
        (target or session_path()).unlink()
    except OSError:
        pass


def apply_patch(current: dict[str, Any], patch: Any) -> dict[str, Any]:
    """Arayuzden gelen kismi degisikligi mevcut ayarlarin uzerine yazar.

    Arayuz yalnizca degisen anahtari gonderir; tamamini gondermek, iki pencere
    acikken birinin digerinin degisikligini ezmesi demekti.
    """
    if not isinstance(patch, dict):
        return current
    return _merge(_merge(DEFAULTS, current), patch)
