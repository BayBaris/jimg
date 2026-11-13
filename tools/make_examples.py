"""`examples/` klasorunu sifirdan uretir: belgeler ve gorseller.

Neden bir betik? Ornekler public depoya girecek ve icindeki **her bayt bu
projeye ait olmali**. Disaridan alinan bir gorsel telif sorusu dogurur; burada
uretilen sekiller icin boyle bir soru yoktur. Betik ayni zamanda kaynagin
kaydidir: `examples/` silinip yeniden uretilebilir.

Belgeler ELLE tasarlandi, rastgele degil. Her biri farkli bir ozellik kumesini
tetikler ve tetikledigi sey `check.py --datasets` ile dogrulanabilir:

  product-catalog — gomulu base64 + goreli yollu gorsel, siniflandirma + sayisal
                    sutun, ic ice nesne  → tablo, grafik, galeri, gruplama
  server-log      — sema varyanti (durum alanina gore), uzun metin, seyrek sutun
                    → varyanta bolme, metin sarma, otomatik gizleme
  app-config      — anahtarli + pivot + anahtar-deger + anahtar-liste
                    → agac, transpoze, `keyed`/`pivot` ayrimi

Calistirma:
    .\\.venv\\Scripts\\python.exe tools\\make_examples.py
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw        # noqa: E402

OUT = ROOT / "examples"
ASSETS = OUT / "assets"

# Gorsel kenari. Kaynak, en buyuk gosterim kipinin uzerinde tutulur ki "Buyuk"
# secildiginde bulaniklasmasin.
ICON_PX = 256

# Arayuzun grafik paletiyle ayni aile — ornekler ekranda yabanci durmasin.
PALETTE = ["#4c8dff", "#7fd1a3", "#e0af68", "#c792ea", "#7dcfff",
           "#ff8a8a", "#9ece6a", "#d8a657"]


def _icon(shape: str, color: str) -> Image.Image:
    """Tek bir ornek gorsel: yuvarlatilmis zemin + geometrik sekil.

    Yazi tipi KULLANILMAZ — harf cizmek sistemdeki fonta bagimlilik demekti ve
    ornekler her makinede ayni gorunmeli.
    """
    img = Image.new("RGB", (ICON_PX, ICON_PX), "#1b1e24")
    d = ImageDraw.Draw(img)
    pad = ICON_PX // 10
    d.rounded_rectangle([pad, pad, ICON_PX - pad, ICON_PX - pad],
                        radius=ICON_PX // 8, fill="#21252d", outline=color, width=4)

    cx = cy = ICON_PX // 2
    r = ICON_PX // 4

    if shape == "circle":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    elif shape == "ring":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=ICON_PX // 16)
    elif shape == "triangle":
        d.polygon([(cx, cy - r), (cx + r, cy + r), (cx - r, cy + r)], fill=color)
    elif shape == "bars":
        w = r // 2
        for i, h in enumerate((r, r * 2, r * 3 // 2)):
            x = cx - r + i * (w + w // 2)
            d.rectangle([x, cy + r - h, x + w, cy + r], fill=color)
    elif shape == "diagonal":
        d.line([(cx - r, cy + r), (cx + r, cy - r)], fill=color, width=ICON_PX // 14)
        d.ellipse([cx + r - 14, cy - r - 14, cx + r + 14, cy - r + 14], fill=color)
    elif shape == "grid":
        s = r // 2
        for gx in (-1, 1):
            for gy in (-1, 1):
                d.rectangle([cx + gx * s - s // 2 - 6, cy + gy * s - s // 2 - 6,
                             cx + gx * s + s // 2 - 6, cy + gy * s + s // 2 - 6], fill=color)
    else:                                   # square
        d.rectangle([cx - r, cy - r, cx + r, cy + r], fill=color)
    return img


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _data_uri(img: Image.Image) -> str:
    return "data:image/png;base64," + base64.b64encode(_png_bytes(img)).decode("ascii")


def _write_json(name: str, data: object) -> Path:
    p = OUT / name
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# --- 1) Urun katalogu ------------------------------------------------------
# Gosterdigi: gomulu base64 ILE goreli yollu gorselin yan yana durmasi (galeri
# ikisini ayri kaynak grubunda listeler), siniflandirma + bayrak sutunlarindan
# kirilim, sayisal sutunlardan olcu, ic ice nesneden genisletilebilir hucre.

PRODUCTS = [
    # (id, name, category, price, stock, active, shape, color, embedded?)
    ("P-1001", "Aurora Desk Lamp", "Lighting", 249.90, 34, True, "circle", 0, True),
    ("P-1002", "Basalt Side Table", "Furniture", 1180.00, 7, True, "square", 1, False),
    ("P-1003", "Cirrus Shelf Unit", "Storage", 890.50, 0, False, "grid", 2, False),
    ("P-1004", "Delta Wall Clock", "Decor", 320.00, 52, True, "ring", 3, True),
    ("P-1005", "Ember Floor Lamp", "Lighting", 640.00, 12, True, "diagonal", 4, False),
    ("P-1006", "Fjord Storage Box", "Storage", 145.75, 118, True, "bars", 5, False),
    ("P-1007", "Granite Bookend", "Decor", 95.00, 61, False, "triangle", 6, True),
    ("P-1008", "Harbor Lounge Chair", "Furniture", 2450.00, 3, True, "square", 7, False),
]


def build_catalog() -> None:
    products = []
    for pid, name, cat, price, stock, active, shape, ci, embedded in PRODUCTS:
        icon = _icon(shape, PALETTE[ci])
        if embedded:
            image = _data_uri(icon)
        else:
            fname = f"{pid.lower()}.png"
            (ASSETS / fname).write_bytes(_png_bytes(icon))
            image = f"assets/{fname}"

        products.append({
            "id": pid,
            "name": name,
            "category": cat,
            "price": price,
            "stock": stock,
            "active": active,
            "image": image,
            "dimensions": {"width_cm": 40 + ci * 7, "height_cm": 55 + ci * 3,
                           "depth_cm": 30 + ci * 2},
        })

    _write_json("product-catalog.json", {
        "catalog": {
            "title": "Example Product Catalog",
            "currency": "TRY",
            "item_count": len(products),
            "generated_by": "tools/make_examples.py",
        },
        "products": products,
    })


# --- 2) Sunucu gunlugu -----------------------------------------------------
# Gosterdigi: sema varyanti. `status` alani IKI degerlidir ve hangi alanlarin
# bulunacagini belirler — basarisiz kayitlar `error_code` ve `stack_trace`
# tasir. Varyant bolme bunu yakalar ve etiketi `status = failed` olur.
#
# ⚠ `level` UC degerlidir ve bilerek oyle: varyant ayirici olmak icin deger
# sayisi grup sayisina esit olmali (`discover._find_discriminator`), yani
# ayirici `status` olur. `level` ise grafikte kirilim olarak kullanilir.

TRACE = (
    "Traceback (most recent call last): "
    "File \"handlers/checkout.py\", line 214, in reserve_stock "
    "response = self._client.post(endpoint, json=payload, timeout=timeout) "
    "File \"net/pool.py\", line 88, in post raise UpstreamTimeout(endpoint) "
    "UpstreamTimeout: inventory-service did not respond within 2.50s"
)

ENTRIES = [
    # (ts, level, status, service, duration_ms, error_code)
    ("2026-08-16T09:00:04Z", "info", "ok", "checkout-api", 128, None),
    ("2026-08-16T09:00:19Z", "info", "ok", "inventory-service", 64, None),
    ("2026-08-16T09:01:02Z", "warn", "ok", "checkout-api", 940, None),
    ("2026-08-16T09:01:37Z", "error", "failed", "inventory-service", 2500, "E-TIMEOUT"),
    ("2026-08-16T09:02:11Z", "info", "ok", "payment-gateway", 212, None),
    ("2026-08-16T09:02:48Z", "info", "ok", "checkout-api", 143, None),
    ("2026-08-16T09:03:20Z", "warn", "ok", "payment-gateway", 1180, None),
    ("2026-08-16T09:03:55Z", "error", "failed", "payment-gateway", 3010, "E-DECLINED"),
    ("2026-08-16T09:04:30Z", "info", "ok", "inventory-service", 77, None),
    ("2026-08-16T09:05:08Z", "info", "ok", "checkout-api", 165, None),
    ("2026-08-16T09:05:41Z", "error", "failed", "checkout-api", 2500, "E-TIMEOUT"),
    ("2026-08-16T09:06:15Z", "info", "ok", "inventory-service", 91, None),
]


def build_log() -> None:
    entries = []
    for ts, level, status, service, ms, code in ENTRIES:
        row = {"timestamp": ts, "level": level, "status": status,
               "service": service, "duration_ms": ms}
        if code is not None:
            row["error_code"] = code
            row["stack_trace"] = TRACE
        entries.append(row)

    _write_json("server-log.json", {
        "window": {
            "started_at": "2026-08-16T09:00:00Z",
            "duration_minutes": 7,
            "environment": "staging",
        },
        "entries": entries,
    })


# --- 3) Uygulama yapilandirmasi --------------------------------------------
# Gosterdigi: dort veri kumesi turu tek belgede.
#   runtime    → keyvalue (skaler agirlikli nesne)
#   servers    → keyed    (dis anahtar sayisi >= ic anahtar sayisi: satir olur)
#   thresholds → pivot    (dis anahtar AZ, ic anahtar COK: sutun olur)
#   features   → keylist  (nesne → liste haritasi)

def build_config() -> None:
    _write_json("app-config.json", {
        "runtime": {
            "environment": "staging",
            "region": "eu-central",
            "debug": False,
            "max_upload_mb": 25,
            "locale": "en-US",
        },
        "servers": {
            "srv-01": {"host": "10.0.1.11", "role": "web", "cores": 4, "active": True},
            "srv-02": {"host": "10.0.1.12", "role": "web", "cores": 4, "active": True},
            "srv-03": {"host": "10.0.2.21", "role": "worker", "cores": 8, "active": True},
            "srv-04": {"host": "10.0.2.22", "role": "worker", "cores": 8, "active": False},
            "srv-05": {"host": "10.0.3.31", "role": "cache", "cores": 2, "active": True},
            "srv-06": {"host": "10.0.3.32", "role": "cache", "cores": 2, "active": False},
        },
        "thresholds": {
            "cpu": {"warn": 70, "critical": 90, "window_s": 60,
                    "cooldown_s": 300, "notify": True},
            "memory": {"warn": 75, "critical": 92, "window_s": 120,
                       "cooldown_s": 600, "notify": True},
        },
        "features": {
            "stable": ["search", "export-csv", "dark-theme"],
            "beta": ["chart-suggestions", "image-gallery"],
            "disabled": ["legacy-importer"],
        },
    })


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    build_catalog()
    build_log()
    build_config()

    docs = sorted(OUT.glob("*.json"))
    assets = sorted(ASSETS.glob("*.png"))
    total = sum(p.stat().st_size for p in docs + assets)
    print(f"{len(docs)} belge · {len(assets)} gorsel · {total / 1024:.1f} KB")
    for p in docs:
        print(f"  {p.name:24} {p.stat().st_size / 1024:6.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
