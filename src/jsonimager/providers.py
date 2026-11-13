"""Agent saglayicilari: bir soruyu bir modele goturen yollar.

Faz 9.5'e kadar tek yol vardi (`claude -p`) ve cagri `api_agent` icinde
gomuluydu. Artik agent katmani "CLI calistiran" degil **"bir saglayiciya soru
soran"** katman: hangi saglayicinin secildigi ayardan gelir, geri kalan kod
degismez.

Sozlesme uc islevdir:

    build_request(prompt, model, effort, key) -> (url, headers, body)  # saf
    parse_response(status, body) -> yanit metni
    parse_error(status, body)    -> cevrilmis kullanici mesaji

⚠ **Anahtar `build_request`e ARGUMAN olarak gelir**, icinde okunmaz: islev
boylece G/C'siz kalir ve denetim onu aga cikmadan sinayabilir. Okuma `ask`in
isidir (`keys.read`).

CLI de bir saglayicidir; farki istegi argv olarak kurmasidir. Ortak yuz
`ask()`; HTTP saglayicilari onu `_HttpProvider` uzerinden paylasir.

⚠ **Saglayici basina sinif YAZILMAZ.** Olculdu (`9.5` taramasi): Gemini ve
Groq dahil bugun bedava katman sunan sagalayicilarin hepsi OpenAI uyumlu
`/chat/completions` konusuyor. Yeni bir saglayici bu yuzden yeni bir sinif
degil, **taban URL + model listesi** demek.

⚠ **Yuk kurucusu ORTAK kalir** (`schema.build_prompt`). Saglayiciya ozel bir
yuk kurucu yazilirsa "yalnizca sema gider" guvencesi (`K-14`) saglayici basina
yeniden kanitlanmak zorunda kalir; bugun tek yerde kanitlaniyor.

⚠ **Anahtar argv'ye YAZILMAZ.** Komut satiri ayni makinedeki baska
sureclerden gorulebiliyor; HTTP saglayicilari anahtari baslikta/govdede
tasir. CLI zaten anahtar istemiyor (`K-13`).
"""

from __future__ import annotations

import functools
import ipaddress
import json
import shutil
import socket
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import i18n as I18N
from . import keys as KEYS

CLI = "cli"
GEMINI = "gemini"
GROQ = "groq"
ANTHROPIC = "anthropic"
OPENAI = "openai"
CUSTOM = "custom"
CLAUDE_BIN = "claude"
TIMEOUT = 180        # saniye — hem CLI hem HTTP icin


@functools.cache
def tls_context() -> ssl.SSLContext:
    """IKI HTTPS yolunun da (bu modul ve `remote_images`) kullandigi TLS baglami (9.24, `K-35`).

    Dogrulama Windows'un KENDI zincir dogrulayicisina birakilir (`truststore`).
    ⚠ Olculdu (Windows Sandbox, 9.9.3): Python'un varsayilan baglami Windows
    deposunun o anki anlik goruntusunu okuyor — temiz makinede 11 kok — ve
    Windows'un eksik koku indirme mekanizmasini TETIKLEMIYOR; Gemini de https
    gorselleri de `CERTIFICATE_VERIFY_FAILED` ile dustu. Windows'un dogrulayicisi
    Edge'in yaptigini yapar: eksik koku indirir, sirket koklerini tanir.

    Elenen: `certifi` (Mozilla kok paketi exe'ye gomulur) — sirket aginda araya
    giren kok sertifikayi gormez ve kokler ancak yeni derlemeyle guncellenir.

    ⚠ Dogrulama KAPATILMAZ: `check_hostname` ve `CERT_REQUIRED` truststore'un
    varsayilanidir ve `check_tls_probe` ikisini de olcer. Onbellekli: baglam
    is parcaciklari arasinda paylasilabilir, her istekte kurmanin anlami yok.
    """
    import truststore
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def tls_roots() -> int:
    """Windows deposunda O AN bulunan kok sertifika sayisi (9.9.2). AGA CIKMAZ.

    ⚠ `9.24`ten beri bu sayi istegin dogrulandigi yer DEGIL: dogrulama
    Windows'un zincir dogrulayicisinda (`tls_context`) ve o eksik koku
    gerektiginde indirir. Sayi yine de tanilamada kalir — temiz bir makinede
    dusuk cikmasi (Sandbox'ta 11) artik bir hata degil, "kokler ihtiyac
    oldukca gelecek" demek. Hata olursa -1.

    `ssl` bu modulde ice aktarilir: ag modulu sayilan iki dosyadan biri bu
    (`check_security`), baska bir module tasinirsa o kapi kirmizi yanar.
    """
    try:
        return int(ssl.create_default_context().cert_store_stats().get("x509_ca", 0))
    except Exception:
        return -1

# Hata govdesinden kullaniciya tasinacak en fazla karakter. Sinir sart:
# saglayicilar hata govdesine bazen istegin tamamini geri koyuyor ve o govde
# istemi — yani semayi — iceriyor.
ERROR_DETAIL_CHARS = 300

# Kullaniciya AYRI bir cumle soylenen HTTP durumlari. Geri kalanlar genel
# mesaja duser; gerekce her durumda ayni: "HTTP 429" tek basina kullaniciya ne
# yapacagini soylemiyor.
#
# ⚠ 404 ve 503 GERCEK cagrida olculdu (Gemini, 2026-08-31): ikisi de "bu model
# bu anahtarla kullanilamiyor" demek oluyor ve kullanicinin yapabilecegi tek
# sey modeli degistirmek.
#
# ⚠ Tablo, `check_providers`in sondaladigi durum listesini de BESLIYOR. Elle
# tutulan ikinci bir liste, buraya yeni bir durum eklendiginde sessizce
# eskirdi.
STATUS_ERRORS = {
    401: "err.key_rejected",
    403: "err.key_rejected",
    429: "err.rate_limited",
    404: "err.model_unavailable",
    503: "err.provider_busy",
}


def _error_detail(body: bytes) -> str:
    """Hata govdesinden kullaniciya gosterilecek metni cikarir.

    ⚠ **Bos dizeye DUSULMEZ.** Once yazilan surum yalnizca OpenAI bicimindeki
    `error.message`i okuyordu ve baska bir sekil geldiginde bos donuyordu;
    gercek bir cagrida `Saglayici 404 dondurdu: ` diye bir mesaj cikti ve
    kullaniciya hicbir sey soylemiyordu — dahasi "govde bos" ile "govdeyi
    okuyamadim" ayirt edilemiyordu. Sekil taninmiyorsa HAM govde kirpilarak
    gecer: anlasilmaz bir ayrinti, hicbir ayrintidan iyidir.
    """
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body.decode("utf-8", "replace").strip()

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
    # Taninmayan sekil: govdenin kendisi gider.
    return json.dumps(data, ensure_ascii=False)


# --- Ozel saglayicinin adresi (9.21, `K-34`) -------------------------------
#
# Listedeki saglayicilarin ucu KAYNAKTA sabittir; ozel saglayicininkini
# kullanici girer. Bu, uygulamanin "kullanicinin yazdigi bir adrese" cikan
# tek yoludur ve kurali burada, tek islevde durur.
CUSTOM_URL_MAX = 300
CHAT_PATH = "/chat/completions"


def _is_loopback(host: str) -> bool:
    """Bu bilgisayar mi: `localhost` adi ya da geri dongu IP'si (127.x, ::1).

    ⚠ Ad TAM eslesir: `localhost.ornek.com` baska bir makinedir.
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def custom_endpoint(raw: object) -> tuple[str, str]:
    """Kullanicinin girdigi adresi dogrular: (uc nokta, hata ANAHTARI). SAF.

    Ikisinden biri daima bostur. Kural (`K-34`):
      - `https` her adrese; `http` YALNIZCA bu bilgisayara (`_is_loopback`).
        Sifresiz baglanti semayi ve anahtari yol uzerindeki herkese acardi;
        ayni makinede yol yok.
      - Adreste kullanici adi/parola, sorgu ya da parca OLMAZ: anahtar
        basliga yazilir (`build_request`), adrese degil.
      - Yol `/chat/completions` ile bitmiyorsa eklenir — kullanici taban
        adresi girer (`…/v1`), tam ucu degil.
    """
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return "", "err.custom_unset"
    if (len(text) > CUSTOM_URL_MAX or "\\" in text
            or any(c.isspace() or ord(c) < 32 for c in text)):
        return "", "err.custom_bad"
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        parts.port                                  # bozuk port burada duser
    except ValueError:
        return "", "err.custom_bad"

    if (not host or "@" in parts.netloc or parts.query or parts.fragment
            or parts.scheme not in ("http", "https")):
        return "", "err.custom_bad"
    if parts.scheme == "http" and not _is_loopback(host):
        return "", "err.custom_http"

    path = parts.path.rstrip("/")
    if not path.endswith(CHAT_PATH):
        path += CHAT_PATH
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", "")), ""


def net_error(reason: object) -> str:
    """Baglanti hatasini CEVRILMIS bir cumleye cevirir (9.23). SAF.

    ⚠ Temiz bir makinede (Windows Sandbox, 9.9.3) kullaniciya ham Python
    metni gidiyordu: `[SSL: CERTIFICATE_VERIFY_FAILED] … (_ssl.c:1082)` ve
    ag yokken `[Errno 11001] getaddrinfo failed`. Ikisi de dogru ama
    kullaniciya ne yapacagini soylemiyor. Taninan sebepler kendi cumlesini
    alir; taninmayan ham ayrintiyla genel cumleye duser — hicbir ayrinti
    atilmaz.
    """
    if isinstance(reason, ssl.SSLCertVerificationError):
        return I18N.t("err.tls_verify")
    if isinstance(reason, socket.gaierror):
        return I18N.t("err.net_offline")
    if isinstance(reason, ConnectionRefusedError):
        return I18N.t("err.net_refused")
    if isinstance(reason, TimeoutError):
        return I18N.t("err.timeout", seconds=TIMEOUT)
    return I18N.t("err.net_failed", error=reason)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Yonlendirmeyi IZLEMEZ: 3xx bir hata olarak doner.

    Istek, kaynakta sabit ya da kullanicinin girip dogrulattigi adrese gider;
    yonlendirme onu — anahtarla birlikte — dogrulanmamis baska bir adrese
    tasirdi.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProviderError(Exception):
    """Kullaniciya GOSTERILEBILIR hata.

    Mesaj zaten cevrilmistir; cagiran onu oldugu gibi arayuze verir. Teknik
    ayrinti (traceback) bu sinifin disinda kalir — `api_agent` onu ayrica
    yakalar.
    """


class Provider:
    """Bir saglayicinin yuzu. Alt siniflar `ask` ya da uc islevi doldurur."""

    key: str = ""
    needs_key: bool = True
    # Anahtar ISTEGE BAGLI mi (9.21). Yerel sunucular anahtar istemez; ozel
    # saglayici anahtar satirini gosterir (`needs_key`) ama anahtarsiz da calisir.
    key_optional: bool = False

    # Saglayiciya ozel uyarinin i18n ANAHTARI (bos ise uyari yok). Metnin
    # kendisi degil anahtar duruyor: uyari cagri aninda cozulmeli, cunku dil
    # oturum icinde degisebiliyor. Uyari SAGLAYICIYA baglidir, faza degil —
    # olculdu (`9.5` taramasi): bedava katmanda veriyi egitime alan da var
    # almayan da var.
    note: str = ""

    # Caba (`effort`) bu saglayicida ANLAMLI MI? (`AK-16`) Arayuz secicisini
    # buna gore gizler.
    #
    # ⚠ Varsayilan **False**, cunku yanlis taraf pahali: hicbir sey yapmayan
    # bir secici gostermek, olmayan bir secicinin yoklugundan kotudur —
    # kullanici cabayi yukseltip yanitin degismedigini goruyor ve sebebini
    # bulamiyor. Yeni bir saglayici cabayi gercekten gonderiyorsa bunu ACIKCA
    # bildirir.
    uses_effort: bool = False

    def models(self) -> list[str]:
        """Sunulan model anahtarlari. Kullanici ayarlardan ekleyebilir (`9.5.5`)."""
        raise NotImplementedError

    def available(self) -> tuple[bool, str]:
        """(kullanilabilir mi, degilse sebep). Arayuz sohbeti buna gore acar."""
        raise NotImplementedError

    def ask(self, prompt: str, model: str, effort: str) -> str:
        raise NotImplementedError


class CliProvider(Provider):
    """`claude -p` — anahtar istemeyen varsayilan yol (`K-13`).

    ⚠ CLI'ye tam model kimligi degil TAKMA AD gecirilir (`opus`): takma ad her
    zaman o ailenin guncel surumune baglanir. Bu koruma yalnizca burada var —
    HTTP saglayicilari tam kimlik ister (`AK-13`).
    """

    key = CLI
    needs_key = False
    # `claude -p --effort <duzey>`: caba burada GERCEKTEN gidiyor ve tek
    # gittigi yer burasi (`AK-16`).
    uses_effort = True

    MODELS = ["opus", "sonnet", "haiku"]

    def models(self) -> list[str]:
        return list(self.MODELS)

    def available(self) -> tuple[bool, str]:
        path = shutil.which(CLAUDE_BIN)
        return (True, path) if path else (False, I18N.t("err.cli_missing_long"))

    def ask(self, prompt: str, model: str, effort: str) -> str:
        exe = shutil.which(CLAUDE_BIN)
        if not exe:
            raise ProviderError(I18N.t("err.cli_missing"))

        try:
            proc = subprocess.run(
                [exe, "-p", "--model", model, "--effort", effort, prompt],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=TIMEOUT,
                # Belge klasoru sizmasin diye notr bir calisma dizini kullanilir.
                cwd=str(Path.home()),
            )
        except subprocess.TimeoutExpired:
            raise ProviderError(I18N.t("err.timeout", seconds=TIMEOUT)) from None
        except OSError as exc:
            raise ProviderError(I18N.t("err.spawn_failed", error=exc)) from None

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:600]
            raise ProviderError(I18N.t("err.cli_exit", code=proc.returncode,
                                       detail=detail))
        return (proc.stdout or "").strip()


class _HttpProvider(Provider):
    """OpenAI uyumlu `/chat/completions` konusan saglayicilarin ortak govdesi.

    Alt sinif yalnizca uc sey verir: `key`, `URL` ve `MODELS`. Istek kurulumu,
    yanit cozumu ve hata cevirisi burada ORTAK durur — saglayici basina
    kopyalanan bir istek kurucusu, `K-14`un ("yalnizca sema gider") saglayici
    basina yeniden kanitlanmasini gerektirirdi.
    """

    URL = ""
    MODELS: list[str] = []

    def models(self) -> list[str]:
        return list(self.MODELS)

    def available(self) -> tuple[bool, str]:
        """Anahtar kayitli mi? Sohbet penceresi buna gore acilir."""
        if not KEYS.available():
            return False, I18N.t("err.keys_unavailable")
        if not KEYS.has(self.key):
            return False, I18N.t("err.key_missing",
                                 provider=I18N.t(f"provider.{self.key}.label"))
        # Ayrinti olarak UC NOKTA doner, anahtar degil: bu deger `agent_status`
        # icinde arayuze gidiyor (CLI'de `claude`un yolu oraya gidiyordu).
        return True, self.URL

    def build_request(self, prompt: str, model: str, effort: str,
                      key: str) -> tuple[str, dict[str, str], bytes]:
        """Istegi kurar. SAF: ag yok, disk yok, anahtar disaridan gelir.

        ⚠ **Anahtar URL'ye YAZILMAZ, basliga yazilir.** Gemini'nin kendi
        (OpenAI uyumlu olmayan) ucu anahtari `?key=` ile alabiliyor; sorgu
        dizesi vekil gunluklerine ve hata izlerine oldugu gibi dusuyor. Ortak
        yol bu yuzden `Authorization` basligidir ve denetim bunu ariyor.

        ⚠ **`effort` GONDERILMEZ.** OpenAI uyumlu uclarda karsiligi
        `reasoning_effort` ve her modelde gecerli degil; gecersiz oldugunda
        istek 400 ile dusuyor. Caba bugun yalnizca CLI'de anlamli (`AK-16`).
        """
        body = json.dumps({
            "model": model,
            # Tek turluk istek: sohbet surekliligi zaten isteme yaziliyor
            # (`schema.build_prompt`), yani mesaj dizisi tek uyeli kalir ve
            # gecmisin tek kaynagi degismez.
            "messages": [{"role": "user", "content": prompt}],
        }, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        # Anahtar yoksa baslik HIC yazilmaz (yalnizca `key_optional`da olur):
        # bos bir `Bearer ` bazi sunucularda 401 uretiyor.
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return self.URL, headers, body

    def _open(self, req: urllib.request.Request):
        """Istegi gonderir — yonlendirmeyi IZLEMEDEN (`_NoRedirect`).

        ⚠ Olculdu (9.21, geri dongude): `urllib` 302'yi izlerken POST'u GET'e
        cevirir ve `Authorization` basligini YENI adrese tasir. Govde gitmez
        ama anahtar gider. Kural bu yuzden yalnizca ozel saglayicida degil
        HEPSINDE gecerli: sabit bir API ucunun POST'u yonlendirmesi icin
        mesru bir sebep yok.
        """
        return urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=tls_context())
        ).open(req, timeout=TIMEOUT)

    def parse_response(self, status: int, body: bytes) -> str:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError(I18N.t("err.bad_response")) from None

        choices = data.get("choices") or []
        text = ""
        if choices:
            text = ((choices[0] or {}).get("message") or {}).get("content") or ""
        text = text.strip()
        if not text:
            # Bos yanit HTTP 200 ile geliyor (icerik suzgeci, kesilmis uretim).
            # Sessizce bos donmek, kullaniciya bos bir baloncuk gostermekti.
            raise ProviderError(I18N.t("err.empty_answer"))
        return text

    def parse_error(self, status: int, body: bytes) -> str:
        """HTTP hatasini CEVRILMIS bir kullanici mesajina donusturur.

        Kullanicinin gercekten karsilasacagi iki durum ayri ayri anlatilir:
        anahtarin reddedilmesi ve kotanin dolmasi. "HTTP 429" tek basina
        kullaniciya ne yapacagini soylemiyor.
        """
        label = I18N.t(f"provider.{self.key}.label")
        detail = _error_detail(body)[:ERROR_DETAIL_CHARS]

        if (key := STATUS_ERRORS.get(status)):
            # ⚠ Ayrinti VARSA cumlenin sonuna eklenir, atilmaz. Gemini bu iki
            # durumda govdeyi bos birakiyor ve ilk yazim buna bakip ayrintiyi
            # hic okumamisti; ama ayni taban sinifi OpenAI ve Anthropic de
            # kullaniyor ve onlarin 404 govdesi HANGI modelin reddedildigini
            # yaziyor. Tek bir saglayicinin bos govdesi, otekilerin
            # ayrintisini atmak icin gerekce degil.
            return I18N.t(key, provider=label) + (f" {detail}" if detail else "")

        # ⚠ Ayrinti gercekten yoksa AYRI bir cumle kullanilir. Bos bir
        # `{detail}` ile kurulan mesaj ekranda `Saglayici 500 dondurdu: `
        # diye, havada asili bir iki nokta ile bitiyordu.
        if not detail:
            return I18N.t("err.http_bare", status=status)
        return I18N.t("err.http_status", status=status, detail=detail)

    def ask(self, prompt: str, model: str, effort: str) -> str:
        key = KEYS.read(self.key) or ""
        if not key and not self.key_optional:
            raise ProviderError(I18N.t(
                "err.key_missing", provider=I18N.t(f"provider.{self.key}.label")))

        url, headers, body = self.build_request(prompt, model, effort, key)
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
        try:
            with self._open(req) as resp:
                return self.parse_response(resp.status, resp.read())
        except urllib.error.HTTPError as exc:
            # ⚠ Govde BIR KEZ okunur ve `parse_error`a verilir; istisnayi
            # zincire baglamiyoruz (`from None`) cunku traceback istek
            # nesnesini, o da anahtari tasiyor.
            raise ProviderError(self.parse_error(exc.code, exc.read())) from None
        except urllib.error.URLError as exc:
            raise ProviderError(net_error(exc.reason)) from None
        except TimeoutError:
            raise ProviderError(I18N.t("err.timeout", seconds=TIMEOUT)) from None


class CustomProvider(_HttpProvider):
    """Adresini KULLANICININ girdigi OpenAI uyumlu servis (9.21, `K-34`).

    Yerel sunucular ve toplayici servisler icin: listedeki saglayicilarin
    hicbirinde barinmayan (cogu acik kaynakli) modellere giden yol. Sinif
    yeni bir sozlesme getirmez — istek, yanit ve hata cozumu `_HttpProvider`in
    aynisidir; farki ucun kaynakta degil AYARDA durmasidir.

    ⚠ Adres her kullanimda yeniden dogrulanir (`custom_endpoint`): ayar
    dosyasi elle duzenlenebilir ve yazarken yapilan dogrulama onu kapsamaz.
    ⚠ Yonlendirme izlenmez — hicbir HTTP saglayicisinda (`_HttpProvider._open`).
    ⚠ Fabrika model listesi YOK: kullanici kendi modelini ekler (`9.5.5`).
    """

    key = CUSTOM
    key_optional = True
    note = "provider.custom.note"
    MODELS: list[str] = []

    def __init__(self) -> None:
        self._raw = ""

    def configure(self, raw: object) -> None:
        """Ayardaki HAM adresi alir (`api_agent._provider` her cagrida verir)."""
        self._raw = raw if isinstance(raw, str) else ""

    @property
    def URL(self) -> str:                    # noqa: N802 — taban sinifin alan adi
        return custom_endpoint(self._raw)[0]

    def available(self) -> tuple[bool, str]:
        url, err = custom_endpoint(self._raw)
        return (True, url) if url else (False, I18N.t(err))

    def ask(self, prompt: str, model: str, effort: str) -> str:
        url, err = custom_endpoint(self._raw)
        if not url:
            raise ProviderError(I18N.t(err))
        return super().ask(prompt, model, effort)


class GeminiProvider(_HttpProvider):
    """Google Gemini — OpenAI uyumlu ucu uzerinden (`9.5.3`).

    ⚠ **Bedava katmanda gonderilen, Google'in urunlerini gelistirmek icin
    kullanilabiliyor** (ucretli katmanda tersi). Giden sey yalnizca sema
    (`K-14`) ama sifir degil; uyari kullaniciya ayarlar ekraninda gosterilir
    (`9.5.3.2`), `K-10`daki "sessizce acma, soyleyerek ac" kalibiyla.

    ⚠ Bedava katman AEA/Isvicre/BK'de kullanilamiyor (Google'in ek sartlari).
    """

    key = GEMINI
    note = "provider.gemini.data_note"
    URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    # ⚠ Liste **gercek bir anahtarla olculdu** (2026-08-31), belgeden
    # kopyalanmadi. Belgenin "guncel" dedigi uc model bu anahtarla
    # calismiyordu: `gemini-3.7-flash` dort denemede de 503, `gemini-2.5-pro`
    # ve `gemini-2.5-flash*` 404. Yani saglayicinin model SAYFASI, bir
    # anahtarin gercekten erisebildigi modellerin listesi degil — fabrika
    # listesine yalnizca calistigi GORULEN kimlikler girer.
    #
    # Olcum tek bir bedava katman anahtariyla yapildi; ucretli bir anahtarda
    # daha fazlasi acilabilir. Kullanici eksigi kendi ekleyebiliyor (`9.5.5`),
    # o yuzden liste "en genis" degil "calistigi kanitlanmis" olacak sekilde
    # tutulur.
    MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]


class GroqProvider(_HttpProvider):
    """Groq — bedava katmanda gonderileni egitime ALMIYOR (`K-28`).

    ⚠ **`groq/compound` aileleri BILEREK listede yok.** O modellerin gomulu
    web arama ve kod calistirma araclari var; sema bir arama sorgusuna
    girebilirdi. "Ag'a cikis yalnizca kullanicinin actigi iki yoldan"
    kuralinin (`K-22`) model secimindeki karsiligi.
    """

    key = GROQ
    note = "provider.groq.free_note"
    URL = "https://api.groq.com/openai/v1/chat/completions"
    MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


class AnthropicProvider(_HttpProvider):
    """Anthropic API — OpenAI UYUMLULUK KATMANI uzerinden (`9.5.4`).

    ⚠ **Bu uc, Anthropic'in kendi ucu degil.** Native yol `/v1/messages`tir ve
    baska bir istek/yanit sekli konusur. Uyumluluk katmani belgede "model
    yeteneklerini denemek icin" diye tanimli, "uzun omurlu urun cozumu"
    degil. Yine de bilerek secildi: alternatif, `K-14`un tek yerde
    kanitlanan guvencesini bozan saglayiciya ozel bir yuk kurucu yazmakti.
    Bedeli sunlar ve hicbiri bu uygulamada kullanilmiyor: onbellek, dusunme
    dokumu, PDF, alinti. **Uc bozulursa cozum native sinif degil**, once
    olcum — sozlesme `_HttpProvider`da ortak durmali.

    ⚠ Bedava katmani YOK: istekler hesaba faturalanir (`provider.*.paid_note`).
    Bunun karsiliginda gonderilen veri egitime alinmaz — Gemini'nin bedava
    katmanindaki durumun tersi.
    """

    key = ANTHROPIC
    note = "provider.anthropic.paid_note"
    URL = "https://api.anthropic.com/v1/chat/completions"
    MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]


class OpenAiProvider(_HttpProvider):
    """OpenAI — sozlesmenin kaynagi olan uc (`9.5.4`).

    ⚠ **Takma ad degil TAM kimlik yazilir.** `gpt-5.6`, `gpt-5.6-sol`un takma
    adi ve CLI'deki `opus` gibi gorunuyor; ama o takma ad yalnizca bir
    NESLIN icindeki bir katmani gosteriyor, "en gunceli" degil. Yaniltici
    bir guvence vermektense uc katman acikca listelenir (`AK-13`).
    """

    key = OPENAI
    note = "provider.openai.paid_note"
    URL = "https://api.openai.com/v1/chat/completions"
    MODELS = ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]


# Kayit: anahtar -> saglayici.
# ⚠ Sira ONEMLI: ilk uye varsayilandir ve anahtar istemeyen yol olmali —
# yeni kullanici hicbir sey yapilandirmadan calistirabilmeli (`K-13`).
# Bedava katmani olanlar ucretlilerden ONCE gelir: secici bu sirayi
# oldugu gibi ciziyor ve listenin basi "once bunu dene" demek.
PROVIDERS: dict[str, Provider] = {
    CLI: CliProvider(),
    GEMINI: GeminiProvider(),
    GROQ: GroqProvider(),
    ANTHROPIC: AnthropicProvider(),
    OPENAI: OpenAiProvider(),
    # Sonda: once hazir saglayicilar denenir, ozel adres bilenin isidir.
    CUSTOM: CustomProvider(),
}
DEFAULT = CLI


def get(key: str | None) -> Provider:
    """Saglayiciyi anahtarindan bulur; taninmayan deger varsayilana duser.

    Ayar dosyasindaki bozuk bir deger uygulamayi agentsiz birakmamali —
    `i18n.set_lang` ve `theme.set_theme` ile ayni kalip.
    """
    return PROVIDERS.get(key or "", PROVIDERS[DEFAULT])
