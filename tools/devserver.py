r"""Gelistirme sunucusu — arayuzu masaustu penceresi olmadan tarayicida acar.

`web/` klasorunu HTTP uzerinden sunar ve `Api` sinifini `/api/<metot>` ucuna
baglar. index.html sunulurken `window.pywebview.api` yerine fetch tabanli bir
vekil enjekte edilir; uretim dosyalari degistirilmez.

Calistirma:  .\.venv\Scripts\python.exe tools\devserver.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jsonimager import settings as S       # noqa: E402
from jsonimager.app import Api             # noqa: E402
from jsonimager.paths import asset_dir     # noqa: E402

# 9.19.5 — oturum dosyasi burada AYRI. Ayarlar gercek dosyadan okunur (bilerek:
# onizleme kullanicinin gordugunu gostermeli), ama onizlemede acilip kapanan
# belgeler gercek uygulamanin bir sonraki acilista geri yukleyecegi listeyi
# ezmemeli.
S.session_path = lambda: Path(tempfile.gettempdir()) / "jsonimager-dev-session.json"

PORT = 8765
WEB = asset_dir()

MIME = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
        ".json": "application/json", ".svg": "image/svg+xml"}

# Masaustu kabugunda pywebview `pywebview.api` nesnesini enjekte eder ve
# `pywebviewready` olayini tetikler. Tarayicida ikisini de biz taklit ederiz.
# index.html'deki CSP `script-src 'self'` oldugu icin satir ici script calismaz;
# vekil ayri bir dosya olarak sunulur.
STUB_PATH = "/__dev_stub.js"
STUB_TAG = f'<script src="{STUB_PATH}"></script>'
STUB_JS = """
window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) =>
  fetch('/api/' + String(name), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  }).then(r => r.json())
})};
window.addEventListener('DOMContentLoaded', () =>
  window.dispatchEvent(new Event('pywebviewready')));
"""

# Yerlesim matrisi (9.14.5): uygulamayi sabit boyutlu iframe'lerde acip olcen
# sayfa. `tools/` altinda durur, exe'ye girmez; uygulamanin CSP'si disinda.
MATRIX = {"/__matrix": ("layout_matrix.html", "text/html"),
          "/__matrix.js": ("layout_matrix.js", "text/javascript")}

# Tarayicida dosya/klasor diyalogu yok; agac Api.startup() icinde samples/
# klasoru taranarak kurulur, ayrica tohumlamaya gerek yok.
api = Api()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # sessiz
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == STUB_PATH:
            return self._send(200, STUB_JS.encode("utf-8"), "text/javascript")
        if self.path.split("?")[0] in MATRIX:
            name, ctype = MATRIX[self.path.split("?")[0]]
            return self._send(200, (ROOT / "tools" / name).read_bytes(), ctype)

        name = self.path.split("?")[0].lstrip("/") or "index.html"
        target = (WEB / name).resolve()
        if WEB not in target.parents or not target.is_file():
            return self._send(404, b"not found", "text/plain")

        data = target.read_bytes()
        if target.name == "index.html":
            text = data.decode("utf-8")
            # Vekil fetch kullandigi icin dev ortaminda connect-src acilir.
            text = text.replace("default-src 'none';", "default-src 'none'; connect-src 'self';")
            text = text.replace("</head>", STUB_TAG + "</head>")
            data = text.encode("utf-8")

        self._send(200, data, MIME.get(target.suffix, "application/octet-stream"))

    def do_POST(self) -> None:
        if not self.path.startswith("/api/"):
            return self._send(404, b"not found", "text/plain")

        method = self.path[len("/api/"):]
        fn = getattr(api, method, None)
        if not callable(fn) or method.startswith("_"):
            return self._send(404, json.dumps({"ok": False, "error": f"yok: {method}"}).encode(), "application/json")

        length = int(self.headers.get("Content-Length") or 0)
        args = json.loads(self.rfile.read(length) or b"[]")
        try:
            result = fn(*args)
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")


def main() -> None:
    print(f"JSON Imager dev sunucusu:  http://localhost:{PORT}")
    print(f"Sunulan klasor: {WEB}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
