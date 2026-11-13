"""Belgedeki gorsel ADRESLERINI indirir — araci aga cikaran ikinci yol (`K-22`).

Birinci yol Agent saglayicisidir (`providers.py`). Bu modul yalnizca kullanici
ayarlardan acmissa (`settings.images.allow_url`) cagrilir: galeri, kaydetme ve
tablo hucresinin onizlemesi icin. Tablo KURULURKEN istek gitmez; hucrenin
onizlemesi cizimden sonra galeri yolundan istenir (`K-32`, 9.6.5.2'nin yerine).

Adres bir izleme pikselidir: istek gittigi an adresin sahibi kullanicinin IP'sini
ve istegin zamanini ogrenir. Sinirlar bu yuzden dar tutuldu ve HEPSI burada;
ag cagrisinin tek noktasi `_urlopen`.
"""

from __future__ import annotations

import ipaddress
import itertools
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

TIMEOUT_S = 8
ATTEMPT_S = 1.5           # tek bir adrese baglanma denemesi (bkz. `_connect_any`)
MAX_BYTES = 15 * 1024 * 1024
MAX_REDIRECTS = 3
PARALLEL = 4              # ayni anda en fazla bu kadar istek
FAIL_TTL_S = 60           # basarisiz adres bu kadar sure yeniden denenmez
USER_AGENT = "JSON Imager"
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}

_cache: dict[str, bytes] = {}
_failed: dict[str, float] = {}
_prefer_v4 = False        # bir kez IPv6 dusup IPv4 baglaninca oturum boyunca True
_lock = threading.Lock()


def allowed(url: str) -> bool:
    """Adrese istek gonderilebilir mi — AGA CIKMADAN.

    Yalnizca https. Kullanici adi/parola tasiyan adres yok: kimlik bilgisi
    gunluklere ve yonlendirmelere sizar. `localhost` ve literal ozel, loopback,
    yerel baglanti IP'si yok — bir belge kullanicinin yerel agindaki cihazlara
    istek attiramasin.

    Bu kural AGA CIKMADAN verilebilen kismidir: literal IP ve ad. Ozel bir IP'ye
    COZULEN ad ancak cozumlemeden sonra anlasilir; o denetim baglanti aninda,
    baglanilacak adresin ta kendisi uzerinde yapilir (`_public_infos`, `9.7.2`).
    Izinden once ad cozumlenmez — DNS sorgusu da bir istektir.
    """
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        has_credentials = parts.username is not None or parts.password is not None
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or not host or has_credentials:
        return False
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        return False
    try:
        return public_ip(host)
    except ValueError:
        return True                      # ad; IP degil — cozulunce denetlenir


def public_ip(raw: str) -> bool:
    """Adres internette yonlendirilebilir mi — literal ve cozulmus adres ICIN TEK KURAL.

    `is_global` IPv4'e eslenmis loopback'i (`::ffff:127.0.0.1`), CGNAT'i, yerel
    baglantiyi ve 6to4'u zaten reddediyor; olculdu. ⚠ Multicast'i reddetmiyor:
    `224.0.0.1` icin `True` donuyor — ayrica eleniyor. Kapsam kimligi
    (`fe80::1%12`) ayrilmadan ayristirilamaz. Gecersiz metin `ValueError` firlatir.
    """
    ip = ipaddress.ip_address(raw.split("%", 1)[0])
    return ip.is_global and not ip.is_multicast


def fetch(url: str) -> bytes | None:
    """Gorselin baytlarini indirir; bir sinir asilirsa ya da istek duserse None.

    ⚠ Onbellegin iki yuzu var. Basarili yanit oturum boyunca tutulur: galeri
    kip degistikce yeniden kuruluyor ve her kurulum yeni bir istek olmamali.
    Basarisizlik yalnizca `FAIL_TTL_S` boyunca hatirlanir: hic hatirlanmasa
    onizleme hatti ayni olu adresi iki kez bekler (onceden indirme + okuma),
    sonsuza dek hatirlansa cevrimdisiyken dusen adres baglanti gelince
    denenemez.
    """
    if not allowed(url):
        return None
    with _lock:
        if url in _cache:
            return _cache[url]
        failed_at = _failed.get(url)
        if failed_at is not None and time.monotonic() - failed_at < FAIL_TTL_S:
            return None

    raw = _download(url)
    with _lock:
        if raw is None:
            _failed[url] = time.monotonic()
        else:
            _cache[url] = raw
            _failed.pop(url, None)
    return raw


def fetch_many(urls: list[str]) -> None:
    """Adresleri PARALEL indirip onbellege koyar; sonuc `fetch` ile okunur.

    Sirayla indirmek cevrimdisiyken 20 kartlik bir galeriyi 20 × `TIMEOUT_S`
    bekletirdi.
    """
    todo = list(dict.fromkeys(u for u in urls if allowed(u)))
    if len(todo) < 2:
        for url in todo:
            fetch(url)
        return
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(PARALLEL, len(todo))) as pool:
        list(pool.map(fetch, todo))


def clear_cache() -> None:
    global _prefer_v4
    with _lock:
        _cache.clear()
        _failed.clear()
        _prefer_v4 = False


def _download(url: str) -> bytes | None:
    """`TIMEOUT_S` TUM isi kapsar — ad cozumlemesi dahil.

    ⚠ `urllib`in `timeout`u yalnizca soket islemlerine uygulanir; ad cozumlemesi
    (`getaddrinfo`) onun disinda kalir. Olculdu: bu makinede cozulemeyen bir ad
    12,1 saniyede donuyor ve isletim sistemi basarisizligi onbellege almiyor —
    galerideki kart "yukleniyor"da takili kaliyordu. Is bu yuzden bir artalan
    ipliginde yurur ve sure dolunca beklenmez; gec gelen sonuc atilir. Iplik
    `daemon`: uygulamanin kapanisini geciktirmez.
    """
    box: dict[str, bytes | None] = {}
    worker = threading.Thread(target=lambda: box.update(raw=_download_now(url)), daemon=True)
    worker.start()
    worker.join(TIMEOUT_S)
    return box.get("raw")


def _download_now(url: str) -> bytes | None:
    import urllib.request                # ISLEV ICINDE: acilis yolu bunu yuklemesin

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "image/*"})
    try:
        with _urlopen(req) as resp:
            if not resp.headers.get_content_type().startswith("image/"):
                return None
            length = resp.headers.get("Content-Length", "")
            if length.isdigit() and int(length) > MAX_BYTES:
                return None              # govdeyi hic okumadan
            raw = resp.read(MAX_BYTES + 1)
    except Exception:
        return None
    return raw if 0 < len(raw) <= MAX_BYTES else None


def _urlopen(req: Any):
    """Ag cagrisinin TEK noktasi — `check.py` burayi sahte bir yanitla degistirir."""
    import urllib.request

    opener = urllib.request.build_opener(_redirect_handler(), _https_handler())
    return opener.open(req, timeout=TIMEOUT_S)


def _ordered(infos: list, prefer_v4: bool) -> list:
    """Adres ailelerini HARMANLAR: v6, v4, v6, v4… (RFC 8305 §4 ruhu).

    ⚠ `socket.create_connection` adresleri cozumlemenin verdigi sirayla dener ve
    her birinde zaman asiminin TAMAMINI bekler. Olculdu: bu makinede IPv6 calismiyor,
    ad cozumlemesi IPv6'yi once veriyor, iki IPv6 adresi 8'er saniye bekletip
    IPv4 0,06 s'de baglaniyordu — 16 s. Tarayicilar iki aileyi yaristirdigi icin
    ayni gorsel orada aninda geliyordu.
    """
    v6 = [i for i in infos if i[0] == socket.AF_INET6]
    v4 = [i for i in infos if i[0] != socket.AF_INET6]
    first, second = (v4, v6) if prefer_v4 else (v6, v4)
    return [i for pair in itertools.zip_longest(first, second) for i in pair if i]


def _connect_any(infos: list, timeout: float, make_socket=socket.socket):
    """Adresleri harmanlanmis sirayla, her birine `ATTEMPT_S` taniyarak dener.

    Bir IPv6 denemesi dusup IPv4 baglaninca oturumun geri kalaninda IPv4 once
    denenir: bozuk IPv6'nin bedeli her gorselde degil, oturumda bir kez odenir.
    """
    global _prefer_v4
    last: OSError | None = None
    v6_failed = False
    for family, stype, proto, _, addr in _ordered(infos, _prefer_v4):
        sock = make_socket(family, stype, proto)
        sock.settimeout(ATTEMPT_S)
        try:
            sock.connect(addr)
        except OSError as exc:
            sock.close()
            last = exc
            v6_failed = v6_failed or family == socket.AF_INET6
            continue
        sock.settimeout(timeout)
        if v6_failed and family != socket.AF_INET6:
            with _lock:
                _prefer_v4 = True
        return sock
    raise last or OSError("adres yok")


def _public_infos(infos: list) -> list:
    """Cozumlenen adreslerden yalnizca internette yonlendirilebilenler (`9.7.2`).

    ⚠ Denetim BAGLANILACAK adres uzerinde: once cozup denetleyip sonra yeniden
    cozmek, arada farkli bir yanit donduren bir DNS sunucusuna (rebinding) acik
    kalirdi. Burada ayni sonuc hem denetleniyor hem kullaniliyor.
    """
    kept = []
    for info in infos:
        try:
            if public_ip(str(info[4][0])):
                kept.append(info)
        except ValueError:
            pass
    return kept


def _happy_connect(address, timeout=None, source_address=None, *args, via_proxy=False, **kwargs):
    """`http.client`in `socket.create_connection` yerine cagirdigi baglayici.

    `via_proxy`: baglanti hedefe degil sistemin VEKIL sunucusuna. Vekil kullanicinin
    kendi ag ayaridir ve cogu zaman ozel bir IP'dedir (kurumsal ag) — reddedilseydi
    vekil arkasinda hicbir gorsel gelmezdi. Hedefin adresi o durumda vekilde cozulur,
    burada gorulmez; adres kurali (`allowed`) yine de uygulanmistir.
    """
    host, port = address
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not via_proxy:
        infos = _public_infos(infos)
        if not infos:
            raise OSError("adres internette yonlendirilebilir degil")
    wait = timeout if isinstance(timeout, (int, float)) else TIMEOUT_S
    return _connect_any(infos, wait)


def _https_connection():
    import http.client

    class Connection(http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            # `http.client` bu niteligi ORNEK uzerinde tutuyor; TLS sarmalamasi
            # ondan sonra geldigi icin yalnizca TCP baglantisi degisiyor.
            #
            # ⚠ Vekil kararı CAGRI ANINDA verilir: `set_tunnel` kurucudan SONRA
            # cagriliyor ve `connect()` vekile baglanirken `_tunnel_host` doludur
            # (olculdu: `http.client` once `(host, port)` = vekil ile baglanir,
            # tuneli sonra acar).
            self._create_connection = lambda address, *a, **k: _happy_connect(
                address, *a, via_proxy=self._tunnel_host is not None, **k)

    return Connection


def _https_handler():
    import urllib.request

    # Agent saglayicilariyla AYNI baglam (9.24, `K-35`): dogrulama Windows'un
    # zincir dogrulayicisinda. Tek kaynak `providers.tls_context`.
    from .providers import tls_context

    connection = _https_connection()

    class Handler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(connection, req, context=self._context)

    return Handler(context=tls_context())


def _redirect_handler():
    import urllib.request

    class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
        max_redirections = MAX_REDIRECTS

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            # Yonlendirme de AYNI kapidan gecer: https'ten http'ye, yerel bir
            # adrese ya da parolali bir adrese gidilmez. `None` donunce urllib
            # 3xx yanitini hata olarak firlatir.
            if not allowed(newurl):
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    return HttpsOnlyRedirect()
