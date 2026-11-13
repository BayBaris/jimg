"""Duzenlenmis belgeyi yazmak: yalnizca degisen belirtec (Faz 10.3).

`render` saftir: ozgun baytlari belirteclere ayirir ve `json.loads` ile okunan
OZGUN koku duzenlenmis kokle paralel yurur. Duzenleme yapiyi degistirmedigi
icin (`edit_core`) iki agac ayni sekli tasir; farkli cikan her skaler deger ya
da anahtar icin yalnizca o belirtecin araligi degistirilir. Bosluk, girinti,
satir sonu (CRLF), `\\u` kacislari ve dokunulmayan sayilarin yazimi oldugu gibi
kalir — `json.dumps` ile bastan yazmak 13 belgenin 5'inde dosyanin tamamini
degistirirdi (K-31 on olcumu).

Karsilastirma bellekteki DEGERLERLE yapilir, belirtec cozulmez: ozgun kok
`json.loads` ile zaten elde. Sonuc yazilmadan once geri okunur ve kokle
karsilastirilir; tutmazsa hicbir sey yazilmaz.

G/C yalnizca `save`dedir.
"""

from __future__ import annotations

import codecs
import json
import os
import re
from pathlib import Path
from typing import Any

from .edit_core import same

ERR_ENCODING = "encoding"
ERR_SYNTAX = "syntax"
ERR_STRUCTURE = "structure"
ERR_DUPLICATE = "duplicate_keys"
ERR_VERIFY = "verify"
ERR_CHANGED = "changed_on_disk"

# Tek belirtec: once bosluk, sonra metin · sabit · sayi · noktalama. Sabitler
# sayidan ONCE: `-Infinity` sayi kalibina `-` ile baslar. `NaN`/`Infinity`
# JSON degil ama `json.loads` kabul ediyor; kabul edilen belge yazilabilmeli.
_TOKEN = re.compile(
    r'[ \t\r\n]*(?:'
    r'(?P<str>"[^"\\]*(?:\\.[^"\\]*)*")'     # acilmis bicim: MB'lik veri URI'sinde hizli
    r'|(?P<lit>true|false|null|NaN|-?Infinity)'
    r'|(?P<num>-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'|(?P<p>[{}\[\]:,])'
    r')', re.S)
_TAIL = re.compile(r"[ \t\r\n]*")


class WriteError(ValueError):
    """Yazilmayan kayit. `reason` arayuzun cevirdigi anahtar."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _tokens(text: str):
    """(tur, bas, son) — tur `str`/`lit`/`num` ya da noktalama karakterinin kendisi."""
    pos, end = 0, len(text)
    while True:
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if _TAIL.match(text, pos).end() == end:
                return
            raise WriteError(ERR_SYNTAX)
        kind = m.lastgroup
        s, e = m.span(kind)
        yield (text[s] if kind == "p" else kind), s, e
        pos = m.end()


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _walk(nxt, orig: Any, new: Any, edits: list) -> None:
    kind, s, e = nxt()
    if kind == "{":
        if not (isinstance(orig, dict) and isinstance(new, dict)) or len(orig) != len(new):
            raise WriteError(ERR_STRUCTURE)
        pairs = zip(orig.items(), new.items())
        n = 0
        kind, s, e = nxt()
        while kind != "}":
            if kind != "str":
                raise WriteError(ERR_SYNTAX)
            pair = next(pairs, None)
            if pair is None:
                raise WriteError(ERR_DUPLICATE)   # belirtec kokten fazla
            (ko, vo), (kn, vn) = pair
            if ko != kn:
                edits.append((s, e, _dump(kn)))
            if nxt()[0] != ":":
                raise WriteError(ERR_SYNTAX)
            _walk(nxt, vo, vn, edits)
            n += 1
            kind, s, e = nxt()
            if kind == ",":
                kind, s, e = nxt()
            elif kind != "}":
                raise WriteError(ERR_SYNTAX)
        if n != len(orig):
            raise WriteError(ERR_DUPLICATE)
    elif kind == "[":
        if not (isinstance(orig, list) and isinstance(new, list)) or len(orig) != len(new):
            raise WriteError(ERR_STRUCTURE)
        for i in range(len(orig)):
            if i and nxt()[0] != ",":
                raise WriteError(ERR_SYNTAX)
            _walk(nxt, orig[i], new[i], edits)
        if nxt()[0] != "]":
            raise WriteError(ERR_SYNTAX)
    elif kind in ("str", "lit", "num"):
        if isinstance(orig, (dict, list)) or isinstance(new, (dict, list)):
            raise WriteError(ERR_STRUCTURE)
        if not same(orig, new):
            edits.append((s, e, _dump(new)))
    else:
        raise WriteError(ERR_SYNTAX)


def render(raw: bytes, root: Any) -> bytes:
    """Duzenlenmis kokun baytlari: ozgunden yalnizca degisen belirtecler farkli."""
    bom = codecs.BOM_UTF8 if raw.startswith(codecs.BOM_UTF8) else b""
    try:
        text = raw[len(bom):].decode("utf-8")
    except UnicodeDecodeError:
        raise WriteError(ERR_ENCODING) from None
    try:
        orig = json.loads(text)
    except ValueError:
        raise WriteError(ERR_SYNTAX) from None

    edits: list[tuple[int, int, str]] = []
    it = _tokens(text)

    def nxt():
        tok = next(it, None)
        if tok is None:
            raise WriteError(ERR_SYNTAX)
        return tok

    try:
        _walk(nxt, orig, root, edits)
    except RecursionError:
        raise WriteError(ERR_STRUCTURE) from None
    if next(it, None) is not None:
        raise WriteError(ERR_SYNTAX)
    if not edits:
        return raw

    parts, pos = [], 0
    for s, e, rep in edits:        # yuruyus sirasi = metin sirasi
        parts += [text[pos:s], rep]
        pos = e
    parts.append(text[pos:])
    out = "".join(parts)
    # Geri okuma: yazilacak metin kokun KENDISI olmali (sira ve tur dahil).
    if _dump(json.loads(out)) != _dump(root):
        raise WriteError(ERR_VERIFY)
    return bom + out.encode("utf-8")


def _atomic(target: Path, data: bytes) -> None:
    """Ayni klasorde gecici dosya -> fsync -> `os.replace`. Yarida kalan yazim
    hedefi bozmaz; gecici dosya hata olursa silinir."""
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save(path: Path, expected: bytes, data: bytes, *, backup: bool, force: bool = False,
         conflict_backup: bool = False) -> None:
    """Belgeyi yazar. Diskteki bayt `expected` degilse yazmaz (KB-3), `force` ile yazar.

    `backup`: once diskteki hal `<ad>.bak`a yazilir. "Oturumdaki ilk kayit mi"
    karari (KB-4) cagirandadir. Diskteki hal yedeklenir, `expected` degil.

    `conflict_backup`: zorla yazimda baska programin surumu HER ZAMAN korunur.
    `.bak` bu kayitta yaziliyorsa oraya girer; daha once yazildiysa oturumun
    ozgun halini ezmemek icin `<ad>.conflict.bak`a yazilir. Ilk yazimda bu
    yoktu: ayni oturumda ikinci kez zorla yazim, obur surumu yedeksiz eziyordu.
    """
    current = path.read_bytes()
    changed = current != expected
    if changed and not force:
        raise WriteError(ERR_CHANGED)
    if backup:
        _atomic(path.with_name(path.name + ".bak"), current)
    elif changed and conflict_backup:
        _atomic(path.with_name(path.name + ".conflict.bak"), current)
    _atomic(path, data)
