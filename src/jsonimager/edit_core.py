"""Duzenleme cekirdegi (Faz 10.2). Saf: G/C yok, kok YERINDE degisir.

Iki islem var: bir skaler degeri yazmak ve bir nesne anahtarini yeniden
adlandirmak. Ikisi de yapiyi (oge sayisi, sira) degistirmez — yazici (10.3)
buna dayanir: ozgun metin ile duzenlenmis kok ayni sekli tasir.

Islem once KURULUR (`set_value_op`, `rename_op`: kurallar burada, hata
burada), sonra `apply` ile uygulanir ve yiginla izlenir. Geri alma LIFO'dur:
bir degerin yolu sonradan yeniden adlandirilan bir ata anahtar tasiyabilir,
ama ters sirada geri alininca ata once eski adina doner ve yol yine gecerli.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import discover as D

VALUE, KEY = "value", "key"
# 10.7 — ayni anahtari BIRDEN COK nesnede birlikte yeniden adlandirmak (sutun
# adi, pivot ic anahtari). Tek islemdir: geri al tek adimda hepsini dondurur.
KEYS = "keys"

# Red nedenleri. Arayuz iletiyi `edit.err_<neden>`den kurar (10.4/10.5).
ERR_NUMBER = "not_number"
ERR_BOOL = "not_bool"
ERR_EMPTY_KEY = "empty_key"
ERR_KEY_EXISTS = "key_exists"
ERR_INDEX_KEY = "index_key"
ERR_ROOT_NAME = "root_name"        # 10.6 — kok tablonun adi dosya adidir
ERR_VARIANT_NAME = "variant_name"  # 10.6 — varyant basligi bir anahtar degil

# JSON sayi dilbilgisi (RFC 8259). `float()` daha genis: `nan`, `inf`, `1_000`,
# `+1`, `.5` kabul eder ve bunlar JSON'a yazilamaz.
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")

Op = tuple[str, list, Any, Any]


class EditError(ValueError):
    """Kurala takilan duzenleme. `reason` arayuzun cevirdigi anahtar."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def same(a: Any, b: Any) -> bool:
    """Ture duyarli esitlik: Python'da `True == 1` ve `1 == 1.0` dogru, JSON'da
    ucu de ayri deger. Duz `==` ile `1 -> true` duzenlemesi "degismedi" sayilip
    hic yazilmazdi."""
    return type(a) is type(b) and a == b


def _number(text: str) -> int | float:
    if not _NUMBER.fullmatch(text):
        raise EditError(ERR_NUMBER)
    if any(ch in text for ch in ".eE"):
        value = float(text)
        if value != value or value in (float("inf"), float("-inf")):
            raise EditError(ERR_NUMBER)   # 1e999 -> inf: JSON'a yazilamaz
        return value
    return int(text)


def parse_input(text: str, old: Any) -> Any:
    """Kullanicinin yazdigi metni hucrenin turune cevirir (KB-2).

    - Dolu hucrede tur KORUNUR: sayi hucresine sayi disi reddedilir, mantiksal
      hucreye yalnizca `true`/`false`, metin hucresine yazilan her sey metindir
      (`12` metin kalir).
    - Bos (`null`) hucrede metin JSON gibi yorumlanir: sayi · `true` · `false`
      · `null`; hicbiri degilse metin.
    """
    if isinstance(old, str):
        return text
    t = text.strip()
    if isinstance(old, bool):          # bool, int'ten ONCE: bool int'in alt sinifi
        if t.lower() not in ("true", "false"):
            raise EditError(ERR_BOOL)
        return t.lower() == "true"
    if isinstance(old, (int, float)):
        return _number(t)
    # old is None
    if t in ("true", "false"):
        return t == "true"
    if t == "null":
        return None
    try:
        return _number(t)
    except EditError:
        return text


def set_value_op(root: Any, path: list, value: Any) -> Op:
    """Deger yazma islemini kurar; yol skaler bir degeri gostermeli."""
    old = D.resolve(root, path)
    if isinstance(old, (dict, list)):
        raise TypeError("yol skaler bir degeri gostermiyor")
    return (VALUE, list(path), old, value)


def rename_op(root: Any, path: list, new_key: str) -> Op:
    """Anahtar yeniden adlandirma islemini kurar; yol ANAHTARIN kendisini gosterir."""
    if not path:
        raise EditError(ERR_ROOT_NAME)    # kokun adi yok; gorunen ad dosya adi
    if isinstance(path[-1], int):
        raise EditError(ERR_INDEX_KEY)    # dizi ogesi: adi yok
    parent = D.resolve(root, path[:-1])
    if not isinstance(parent, dict) or path[-1] not in parent:
        raise TypeError("yol bir nesne anahtarini gostermiyor")
    if not new_key.strip():
        raise EditError(ERR_EMPTY_KEY)
    if new_key != path[-1] and new_key in parent:
        raise EditError(ERR_KEY_EXISTS)
    return (KEY, list(path), path[-1], new_key)


def rename_many_op(root: Any, paths: list[list], new_key: str) -> Op:
    """Ayni adli anahtari her yolda birlikte yeniden adlandiran islemi kurar (10.7).

    Yollarin hepsi ayni ESKI adi gostermeli. Yeni ad yollardan HERHANGI birinin
    ust nesnesinde zaten varsa reddedilir: o satirda iki alan ayni adi
    alirdi ve biri sessizce kaybolurdu.
    """
    if not paths:
        raise TypeError("yol yok")
    old = paths[0][-1]
    for p in paths:
        if not p or isinstance(p[-1], int) or p[-1] != old:
            raise TypeError("yollar ayni adli anahtari gostermiyor")
    if not new_key.strip():
        raise EditError(ERR_EMPTY_KEY)
    if new_key != old and any(new_key in D.resolve(root, p[:-1]) for p in paths):
        raise EditError(ERR_KEY_EXISTS)
    return (KEYS, [list(p) for p in paths], old, new_key)


def _rename(parent: dict, old: str, new: str) -> None:
    """Sirayi koruyarak yeniden adlandirir; nesne YERINDE degisir (baska
    yerlerde tutulan gondermeler gecerli kalir)."""
    items = [(new if k == old else k, v) for k, v in parent.items()]
    parent.clear()
    parent.update(items)


def _do(root: Any, op: Op, forward: bool) -> None:
    kind, path, old, new = op
    src, dst = (old, new) if forward else (new, old)
    if kind == VALUE:
        D.resolve(root, path[:-1])[path[-1]] = dst
    elif kind == KEYS:
        # `path` burada YOL LISTESI; her birinin ust nesnesi degismez.
        for p in path:
            _rename(D.resolve(root, p[:-1]), src, dst)
    else:
        # Ileri: yol eski adi tasir. Geri: anahtar artik yeni adda duruyor.
        _rename(D.resolve(root, path[:-1]), src, dst)


@dataclass
class History:
    """Yapilanlar ve geri alinanlar. Kayit isareti islem KIMLIGIDIR, sayac
    degil: kayittan sonra geri alinip yeni islem yapilirsa yigin ayni boya
    doner ama belge artik kaydedilen hal degildir."""
    done: list[tuple[int, Op]] = field(default_factory=list)
    undone: list[tuple[int, Op]] = field(default_factory=list)
    saved: int = 0          # kayit anindaki en ustteki islemin kimligi (0: hic)
    _next: int = 1


def _top(h: History) -> int:
    return h.done[-1][0] if h.done else 0


def dirty(h: History) -> bool:
    return _top(h) != h.saved


def mark_saved(h: History) -> None:
    h.saved = _top(h)


def apply(root: Any, h: History, op: Op) -> bool:
    """Islemi uygular ve yigina iter. Degismeyen duzenleme yok sayilir (False)."""
    if same(op[2], op[3]):
        return False
    _do(root, op, forward=True)
    h.done.append((h._next, op))
    h._next += 1
    h.undone.clear()
    return True


def undo(root: Any, h: History) -> Op | None:
    if not h.done:
        return None
    entry = h.done.pop()
    _do(root, entry[1], forward=False)
    h.undone.append(entry)
    return entry[1]


def redo(root: Any, h: History) -> Op | None:
    if not h.undone:
        return None
    entry = h.undone.pop()
    _do(root, entry[1], forward=True)
    h.done.append(entry)
    return entry[1]
