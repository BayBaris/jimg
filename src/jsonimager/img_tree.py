"""Yapi agaci: yerlesim ve sahne.

Agac belgenin SEMASINI gosterir, icerigini degil: skaler alanlar tek dugumde
ozetlenir, kayit dizilerinde ilk kayit acilir. Dugum butcesi `TREE_MAX_NODES`;
kaldirilirsa gorsel on binlerce piksel olur.

`tree_layout` dugum + kenar dondurur ve IKI tuketicisi vardir: sahne (PNG/SVG/
PDF) ve `.drawio` (`vector.to_drawio`, `K-11`). Ayni yerlesimden beslendikleri
icin ciktilar birbirinden sapmaz.
"""

from __future__ import annotations

from typing import Any

from . import i18n as I18N
from . import theme as TH
from .draw import PAD, _fit, scene_to_png
from .vector import Scene

# ⚠ **Kutu olculeri PUNTODAN turer, sabit degil** (`9.4.5.2`). Yukseklik iki
# satir sigdirmali (baslik + aciklama); genislik karakter genisligiyle orantili
# buyur, boylece agac tumden olceklenir. Taban boyutta (12) bugunku sayilar
# cikar — 130 × 34.
#
# ⚠ Metin `_clip` ile DEGIL `_fit` ile kirpilir: `_clip` karakter sayar ve
# `char_w` yalnizca puntodan turer, AILEDEN degil. Consolas ya da Georgia
# secildiginde ayni 20 karakter kutuyu tasardi — ve Pillow'da kirpma yok.
# `_fit` gercek yazi tipiyle olcer; oteki iki cizici de onu kullaniyor.
NODE_W_BASE = 130      # taban boyuttaki kutu genisligi
NODE_GAP_Y = 8
NODE_GAP_X = 34
NODE_TEXT_PAD = 7      # kutu icindeki yatay dolgu (iki yanda)
TREE_MAX_DEPTH = 5
TREE_MAX_CHILDREN = 12
TREE_MAX_NODES = 220   # buyuk belgelerde gorsel kontrolden cikmasin
TREE_SCALAR_NAMES = 5  # ozet dugumde kac alan adi yazilsin


def _node_box(m: TH.Metrics) -> tuple[int, int]:
    """Kutunun (genislik, yukseklik) olcusu — ikisi de gecerli puntodan turer.

    Genislik `char_w` ile ayni TAMSAYI aritmetigini kullanir (`theme` icindeki
    gerekce gecerli): once carpma, sonra taban alma.
    """
    return NODE_W_BASE * m.char_w // TH.CHAR_W_BASE, m.font + m.small + 12


def _node_label(key: str, val: Any) -> tuple[str, str]:
    """(baslik, aciklama) — aciklama sekil veya deger onizlemesi."""
    if isinstance(val, dict):
        return str(key), I18N.t("tree.fields", n=len(val))
    if isinstance(val, list):
        if val and all(isinstance(x, dict) for x in val):
            return str(key), I18N.t("tree.records", n=len(val))
        return str(key), I18N.t("tree.items", n=len(val))
    if val is None:
        return str(key), "null"
    if isinstance(val, bool):
        return str(key), "true" if val else "false"
    if isinstance(val, str):
        v = " ".join(val.split())
        return str(key), f'"{v[:28]}…"' if len(v) > 28 else f'"{v}"'
    return str(key), str(val)


def _build_tree(key: str, val: Any, depth: int, budget: list[int]) -> dict:
    """Belgenin YAPISINI cikarir: her dugum `ad [oge sayisi]` bicimindedir.

    Tasarim kurallari:
      - **Skaler alanlar dugum olmaz.** Sayilari zaten ust dugumun etiketinde
        yazar (`{5 alan}`); adlari hover ipucunda gosterilir. Boylece agac
        en alt seviyeye inmez.
      - **Kayit dizilerinde ara `[0]` dugumu yoktur.** Ilk kaydin ic ice
        alanlari dogrudan dizinin altina asilir; kayitlar ayni semayi
        paylastigi icin bu semanin tamamini verir.
      - **"… N oge daha" dugumu yoktur.** O sayi ust dugumun etiketinde
        (`[8 kayit]`) zaten yazili; ikinci kez ve daha bulanik bir dille
        tekrarlamak okumayi zorlastiriyordu.
    """
    title, desc = _node_label(key, val)
    node = {"title": title, "desc": desc, "children": [], "fields": [],
            "container": isinstance(val, (dict, list))}

    if depth >= TREE_MAX_DEPTH or not node["container"] or budget[0] <= 0:
        return node

    if isinstance(val, dict):
        shape = val
    elif val and all(isinstance(x, dict) for x in val):
        shape = val[0]          # dizinin semasini ilk kayit temsil eder
    else:
        return node             # skaler dizi: yaprak, sayisi etiketinde

    node["fields"] = [k for k, v in shape.items() if not isinstance(v, (dict, list))]
    containers = [(k, v) for k, v in shape.items() if isinstance(v, (dict, list))]

    for k, v in containers[:TREE_MAX_CHILDREN]:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        node["children"].append(_build_tree(k, v, depth + 1, budget))
    return node


def _span(node: dict, node_h: int) -> int:
    """Alt agacin kapladigi dikey yeri BIR KEZ hesaplar ve dugume yazar.

    Once bu bilgi `_place` icinde her cocuk icin yeniden hesaplaniyordu ve her
    cagri alt agacin tamamini bastan yuruyordu: 221 dugumluk bir agacta 807
    cagri. Tek gecis yeter — yukseklik dugumun kendisinde durur.
    """
    kids = node["children"]
    node["span"] = node_h if not kids else max(
        node_h,
        sum(_span(c, node_h) for c in kids) + NODE_GAP_Y * (len(kids) - 1),
    )
    return node["span"]


def _place(node: dict, x: int, y: int, out: list, box: tuple[int, int]) -> int:
    """Dugumu dikeyde cocuklarinin ortasina hizalar. Merkez y'yi dondurur."""
    node_w, node_h = box
    if not node["children"]:
        cy = y + node_h // 2
        out.append((x, cy, node))
        return cy

    child_x = x + node_w + NODE_GAP_X
    cy_list = []
    cursor = y
    for c in node["children"]:
        cy_list.append(_place(c, child_x, cursor, out, box))
        cursor += c["span"] + NODE_GAP_Y
    cy = (cy_list[0] + cy_list[-1]) // 2
    out.append((x, cy, node))
    return cy


def tree_layout(name: str, root: Any) -> tuple[list[dict], list[tuple[str, str]], float, float]:
    """Agaci yerlestirir: (dugumler, kenarlar, genislik, yukseklik).

    Ayni yerlesim hem sahneye (PNG/SVG/PDF) hem `.drawio`'ya beslenir; boylece
    ciktilar birbirinden sapmaz.
    """
    m = TH.metrics()
    box = node_w, node_h = _node_box(m)

    tree = _build_tree(name, root, 0, [TREE_MAX_NODES])
    _span(tree, node_h)
    placed: list = []
    _place(tree, PAD, PAD + m.title_h, placed, box)

    ids = {id(node): f"n{i}" for i, (_, _, node) in enumerate(placed)}
    pos = {id(node): (x, y) for x, y, node in placed}

    nodes = [
        {"id": ids[id(node)], "x": x, "y": y - node_h / 2,
         "w": node_w, "h": node_h,
         "title": node["title"], "desc": node["desc"], "container": node["container"],
         "fields": node.get("fields", []), "cy": y}
        for x, y, node in placed
    ]
    edges = [
        (ids[id(node)], ids[id(child)])
        for _, _, node in placed
        for child in node["children"] if id(child) in ids
    ]

    w = max(n["x"] for n in nodes) + node_w + PAD
    h = max(n["cy"] for n in nodes) + node_h + PAD
    return nodes, edges, w, h


def _node_hover(n: dict) -> str:
    """Dugum ipucu: etiket + skaler alan adlari (agacta dugum olarak cizilmezler)."""
    tip = n["title"] + (" · " + n["desc"] if n["desc"] else "")
    fields = n.get("fields") or []
    if fields:
        shown = ", ".join(fields[:TREE_SCALAR_NAMES])
        if len(fields) > TREE_SCALAR_NAMES:
            shown += f" … +{len(fields) - TREE_SCALAR_NAMES}"
        tip += I18N.t("tree.hover_fields", list=shown)
    return tip


def tree_scene(name: str, root: Any) -> tuple[Scene, list[dict], list[tuple[str, str]]]:
    pal, m = TH.active(), TH.metrics()
    nodes, edges, w, h = tree_layout(name, root)
    by_id = {n["id"]: n for n in nodes}

    sc = Scene(w, h, pal.bg)
    sc.text(PAD, PAD + m.title, I18N.t("tree.title"),
            size=m.title, fill=pal.text, bold=True)
    sc.text(PAD, PAD + m.title * 2,
            I18N.t("tree.subtitle", name=name, depth=TREE_MAX_DEPTH),
            size=m.small, fill=pal.muted)

    # Once baglantilar, sonra kutular — cizgiler kutularin altinda kalsin.
    for src, dst in edges:
        a, b = by_id[src], by_id[dst]
        mid = a["x"] + a["w"] + NODE_GAP_X / 2
        sc.line([(a["x"] + a["w"], a["cy"]), (mid, a["cy"]),
                 (mid, b["cy"]), (b["x"], b["cy"])], stroke=pal.line, sw=1.5)

    for n in nodes:
        sc.rect(n["x"], n["y"], n["w"], n["h"], fill=pal.panel_2,
                stroke=pal.accent if n["container"] else pal.line, sw=1, r=5,
                hover=_node_hover(n))
        text_w = n["w"] - NODE_TEXT_PAD * 2
        sc.text(n["x"] + NODE_TEXT_PAD, n["y"] + m.font + 3,
                _fit(n["title"], m.font, True, text_w),
                size=m.font, fill=pal.text, bold=True)
        if n["desc"]:
            sc.text(n["x"] + NODE_TEXT_PAD, n["y"] + m.font + m.small + 6,
                    _fit(n["desc"], m.small, False, text_w),
                    size=m.small, fill=pal.muted)

    return sc, nodes, edges


def render_tree(name: str, root: Any, scale: int = 2) -> bytes:
    return scene_to_png(tree_scene(name, root)[0], scale)
