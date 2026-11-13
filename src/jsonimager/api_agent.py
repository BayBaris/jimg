"""`Api`nin Agent yuzu: saglayici cagrisi ve sohbet dizisi.

⚠ Metotlar Faz 9.5'e kadar `claude_*` adiniyordu ve gerekcesi "bu metotlar
GERCEKTEN `claude` CLI'sini calistirir" idi. Saglayici secilebilir olunca o
gerekce dustu: adlar `agent_*`. Beklenen metot listesi JS kaynagindan
cikariliyor (`check_api`), yani ad degisimi denetimle kilitli.

Hangi saglayicinin kullanildigi `settings.agent.provider`dan gelir; cagrinin
kendisi `providers.py`dedir. Bu modul yalnizca **belge tarafini** bilir: sema,
sohbet dizisi ve dogrulama.

⚠ Gizlilik: varsayilan olarak YALNIZCA sema gider (bkz. `schema.py`). Hucre
degerleri, varyant etiketlerindeki degerler ve dosya yolu gonderilmez. Yuk
kurucusu saglayicidan BAGIMSIZ tek yerdedir — `K-14` boylece saglayici basina
degil, bir kez kanitlanir.

9.27 — tek istisna `agent.send_values` ayaridir (varsayilan kapali): aciksa
SECILI tablonun EKRANDA gorunen satirlari ve sutunlari da gider, en fazla
`VALUE_ROWS` satir ve `VALUE_CHARS` karakter, gorsel hucreleri yer tutucuyla.
Hangi tablonun gidecegini arayuz soyler ama sinirlar BURADA uygulanir.

Sohbet surekliligi: saglayici her cagrida SIFIRDAN baslar; sureklilik `_chats`
dizisinin isteme yazilmasiyla kurulur. Sohbete yalnizca TAMAMLANAN tur yazilir —
basarisiz cagrida soru da eklenmez, yoksa yanitsiz bir soru sonraki istemi
kirletir.
"""

from __future__ import annotations

import string
import traceback

from . import export_text as T
from . import flatten as F
from . import i18n as I18N
from . import keys as KEYS
from . import providers as P
from . import schema as SCHEMA
from . import settings as S

# 9.27 — degerler acikken giden tablonun sinirlari. Satir siniri istemi kucuk
# modellerin baglamina sigdirir; karakter siniri uzun metin sutunlarina karsi
# ikinci kemer (hucre basina `export_text.MAX_CELL` zaten var).
VALUE_ROWS = 100
VALUE_CHARS = 20_000

# `claude --effort` duzeyleri. Anahtarlar CLI'nin kendi degerleridir ve oldugu
# gibi gecirilir; aciklama yalnizca menude gorunur. Varsayilan `medium`: sema
# sorulari cogunlukla yapisal, en yuksek cabaya gerek duymuyor.
AGENT_EFFORTS = ["low", "medium", "high", "xhigh", "max"]
AGENT_EFFORT_DEFAULT = "medium"
AGENT_EFFORT_KEYS = set(AGENT_EFFORTS)

# Model listesi artik SAGLAYICIDAN gelir (`providers.Provider.models`); burada
# yalnizca varsayilanin adi durur. Etiket ve aciklama `model.<k>.label` /
# `model.<k>.note` anahtarlariyla `i18n`dedir ve CAGRI ANINDA cozulur.
AGENT_MODEL_DEFAULT = "opus"

# Kullanicinin yazabilecegi model kimliginin sinirlari (9.5.5). Gercek
# kimlikler `gemini-3.7-flash`, `openai/gpt-oss-120b`, `claude-opus-5`,
# `gpt-5.6-sol` — nokta, tire, alt cizgi, egik cizgi ve iki nokta yetiyor.
# ⚠ Bosluk ve denetim karakteri BILEREK disarida: kopyala-yapistirdan gelen
# gorunmez bir bosluk, kimligi ekranda dogru gosterip istegi 400 ile
# dusururdu ve kullanici sebebini goremezdi.
MODEL_ID_CHARS = frozenset(string.ascii_letters + string.digits + "-_./:")
MODEL_ID_MAX = 100
# Menu bir acilir listede ciziliyor; sinirsiz liste onu kullanilmaz yapardi.
MODEL_LIST_MAX = 24


def valid_model_id(value: object) -> bool:
    """Kimlik yazilabilir mi? Denetim de bu islevi cagirir."""
    return (isinstance(value, str) and bool(value)
            and len(value) <= MODEL_ID_MAX
            and set(value) <= MODEL_ID_CHARS)


def _model_view(prov: P.Provider, key: str) -> dict:
    """Bir modelin arayuz gorunumu: etiket, aciklama, ozel mi.

    ⚠ **Ozel modelin etiketi KIMLIGIN KENDISIDIR.** `i18n.t` eksik anahtarda
    anahtarin kendisine dusuyor (bilincli: bos hucre gormekten iyi), yani
    kullanicinin ekledigi model menude `model.gemini-4.0.label` diye
    gorunurdu. Ayrim bu yuzden burada ACIKCA yapilir, `t`nin dusme yoluna
    birakilmaz.
    """
    builtin = key in prov.models()
    return {"key": key,
            "label": I18N.t(f"model.{key}.label") if builtin else key,
            "note": I18N.t(f"model.{key}.note") if builtin else "",
            "custom": not builtin}


def _reply(view: dict, error: str | None) -> dict:
    """Kopru yazicilarinin ortak donusu: gorunum + `ok` (+ varsa `error`).

    ⚠ Kalip ucuncu kez cogalmaya baslamisti. `api_settings._reply`in kendi
    docstring'i tuzagi anlatiyor ("bes ayri yerde elle kurulan sozluktu"):
    sozlesmeye ortak bir alan eklendiginde kopyalarin biri unutulursa arayuz
    iki ayri donus sekli bilmek zorunda kalir. `api_settings` disarida kaldi —
    onun gorunumu (`settings` + cozulmus kabuk) baska bir sozlesme.
    """
    out = {"ok": error is None, **view}
    if error is not None:
        out["error"] = error
    return out


class AgentMixin:
    """Sohbet seridi ve saglayici kopru metotlari."""

    def _provider(self) -> P.Provider:
        agent = self._settings.get("agent") or {}
        # Ozel saglayicinin adresi her cagrida ayardan verilir (9.21): tek
        # kaynak ayar, saglayici nesnesi yalnizca son okunan degeri tasir.
        P.PROVIDERS[P.CUSTOM].configure(agent.get("custom_url"))
        return P.get(agent.get("provider"))

    def agent_endpoint_set(self, url: str = "") -> dict:
        """Ozel saglayicinin adresini yazar; bos dize adresi siler (9.21).

        Gecersiz adres YAZILMAZ ve cevrilmis sebep doner. Donuste iki deger
        var: `url` kullanicinin yazdigi (kutuda o gorunur), `endpoint` istegin
        gercekten gidecegi tam adres — arayuz onu kullaniciya soyler.
        """
        text = url.strip() if isinstance(url, str) else ""
        endpoint, err = P.custom_endpoint(text)
        if text and not endpoint:
            return {"ok": False, "error": I18N.t(err)}
        self._settings = S.apply_patch(self._settings, {"agent": {"custom_url": text}})
        try:
            S.save(self._settings)
        except OSError as exc:
            return {"ok": False, "url": text, "endpoint": endpoint,
                    "error": I18N.t("err.settings_write", error=exc)}
        return {"ok": True, "url": text, "endpoint": endpoint}

    # --- Model listesi (9.5.5) ----------------------------------------------
    #
    # Kullanicinin listesi EKLEME degil TAMAMEN YERINE GECMEDIR. Iki kume
    # (eklenen + gizlenen) tutmak ayni isi iki kez yapmakti ve asil ihtiyaci —
    # emekliye ayrilan bir kimligi CIKARMAK — ekleme listesi zaten
    # karsilamiyor. Bos ya da yok olan girdi fabrika listesi demek; `reset`
    # girdiyi siler, fabrika listesini kopyalamaz (kopyalasaydi liste bir
    # sonraki surumde donar kalirdi).
    #
    # ⚠ Kullanici listesi `Provider.models()`e GIRMEZ, koprude birlesir.
    # `check_i18n`in model ailesi `PROVIDERS[*].models()`ten turuyor; girseydi
    # denetim kullanicinin makinesindeki ayar dosyasina bagli olurdu.

    def _model_map(self) -> dict[str, list[str]]:
        """Ayardaki liste haritasi — YALNIZCA gecerli girdiler.

        ⚠ Suzme BURADA yapilir, cunku `settings._merge` bunu yapamaz: bu
        agacin tabani `{}` ve oradaki her anahtar "bilinmeyen" sayiliyor,
        bilinmeyen anahtar da oldugu gibi korunuyor (eski surum yeni ayari
        silmesin diye, bilincli). Bedeli bozuk bir degerin dosyada
        kalabilmesi; okuyan taraf bu yuzden suzer ve dosyayi duzeltmez.
        """
        raw = (self._settings.get("agent") or {}).get("models")
        if not isinstance(raw, dict):
            return {}

        out: dict[str, list[str]] = {}
        for name, value in raw.items():
            if name not in P.PROVIDERS or not isinstance(value, list):
                continue
            # `dict.fromkeys` SIRAYI korur: kullanicinin yazdigi sira listenin
            # sirasidir, alfabetik siralamak secimi tanidiksiz yapardi.
            ids = list(dict.fromkeys(m for m in value if valid_model_id(m)))
            if ids:
                out[name] = ids[:MODEL_LIST_MAX]
        return out

    def _models(self, prov: P.Provider) -> list[str]:
        """Saglayicinin GECERLI model listesi — tek kaynak.

        ⚠ `agent_status` ile `agent_ask`in dogrulamasi bu ayni islevden
        beslenmek ZORUNDA. Ayrisirlarsa menude gorunen bir model "bilinmeyen
        model" hatasi verir; hicbir test bunu kendiliginden yakalamaz cunku
        iki yol da tek basina dogru gorunur.
        """
        return self._model_map().get(prov.key) or prov.models()

    def agent_models(self) -> dict:
        """Duzenleyicinin cizdigi liste: her saglayici, listesi, ozel mi."""
        return _reply(self._models_view(), None)

    def _model_provider(self, name: str) -> P.Provider | None:
        """Adi KAYITLI bir saglayiciya cozer, yoksa `None` — `_key_provider`in
        kardesi (oradaki `needs_key` suzgeci burada yok, her saglayicinin
        listesi duzenlenebilir).

        ⚠ `providers.get()` BURADA DA KULLANILMAZ ve gerekce aynidir: o islev
        taninmayan degeri varsayilana dusuruyor, yani arayuzden gelen yanlis
        bir ad listeyi sessizce `cli`nin altina yazardi. Kural uc yazicida uc
        kez tekrarlanmak yerine tek yerde durur — kopyalardan biri bir gun
        `P.get()`e cevrilirse denetim yalnizca birini yakalardi.
        """
        return P.PROVIDERS.get(name or "")

    def agent_model_add(self, provider: str, model: str = "") -> dict:
        """Listeye bir model kimligi ekler."""
        prov = self._model_provider(provider)
        if prov is None:
            return self._models_reply(
                I18N.t("err.unknown_provider", provider=provider))

        model = (model or "").strip()
        if not valid_model_id(model):
            return self._models_reply(I18N.t("err.model_invalid", model=model))

        current = self._models(prov)
        if model in current:
            return self._models_reply(I18N.t("err.model_exists", model=model))
        if len(current) >= MODEL_LIST_MAX:
            return self._models_reply(
                I18N.t("err.model_limit", max=MODEL_LIST_MAX))
        return self._write_models(prov.key, [*current, model])

    def agent_model_remove(self, provider: str, model: str) -> dict:
        """Listeden bir model kimligi cikarir."""
        prov = self._model_provider(provider)
        if prov is None:
            return self._models_reply(
                I18N.t("err.unknown_provider", provider=provider))

        current = self._models(prov)
        if model not in current:
            return self._models_reply(I18N.t("err.model_missing", model=model))
        # ⚠ Son model CIKARILAMAZ. Bos liste "fabrika listesi" anlamina
        # geliyor (bkz. `_models`), yani sonuncuyu silmek listeyi silmek degil
        # SIFIRLAMAK olurdu — kullanici cikardigi modelin geri geldigini
        # gorurdu. Sifirlamanin kendi dugmesi var.
        if len(current) == 1:
            return self._models_reply(I18N.t("err.model_last"))
        return self._write_models(prov.key, [m for m in current if m != model])

    def agent_models_reset(self, provider: str) -> dict:
        """Saglayicinin listesini fabrika ayarina dondurur."""
        prov = self._model_provider(provider)
        if prov is None:
            return self._models_reply(
                I18N.t("err.unknown_provider", provider=provider))
        return self._write_models(prov.key, None)

    def _write_models(self, name: str, ids: list[str] | None) -> dict:
        """Haritayi gunceller ve diske yazar. `ids is None` girdiyi SILER.

        ⚠ `settings.apply_patch` BURADA KULLANILAMAZ: birlestirme yalnizca
        yazar, silmez — tabanda duran bir saglayici anahtari yamada
        bulunmadigi icin korunur ve `reset` hicbir sey yapmazdi. Bu bir yama
        degil, sahibi belli bir alanin tamamen degistirilmesi.
        """
        agent = self._settings.setdefault("agent", {})
        models = dict(self._model_map())
        if ids is None:
            models.pop(name, None)
        else:
            models[name] = ids
        agent["models"] = models

        try:
            S.save(self._settings)
        except OSError as exc:
            # Diske yazilamadi; bellekteki deger yine de gecerli — kullanici
            # oturum boyunca kullanabilsin (`settings_set` ile ayni karar).
            return self._models_reply(I18N.t("err.settings_write", error=exc))
        return self._models_reply()

    def _models_view(self) -> dict:
        """Her saglayicinin listesi. Etiketler CAGRI ANINDA cozulur.

        ⚠ Harita BIR KEZ kurulur ve dogrudan okunur; `self._models(p)` cagrisi
        onu her saglayici icin bastan suzerdi (olculdu: dolu listede 430 µs'nin
        315'i bosa gidiyordu). Ifade `_models`in kendisiyle ayni oldugu icin
        "tek kaynak" guvencesi bozulmuyor.
        """
        overrides = self._model_map()
        return {"providers": [{"key": p.key,
                               "label": I18N.t(f"provider.{p.key}.label"),
                               # Fabrika listesinden sapmis mi? Duzenleyici
                               # `Varsayilana don` dugmesini buna gore acar.
                               "edited": p.key in overrides,
                               "models": [_model_view(p, m)
                                          for m in (overrides.get(p.key)
                                                    or p.models())]}
                              for p in P.PROVIDERS.values()],
               # Duzenleyici acilirken KULLANILAN saglayiciyi da buradan alir;
               # bunun icin ayri bir `settings_get` cagrisi acilmaz.
               "provider": self._provider().key,
               "max": MODEL_LIST_MAX}

    def _models_reply(self, error: str | None = None) -> dict:
        """Uc yazicinin ortak donusu.

        Liste her donuste yeniden kurulur ki arayuz durumu ikinci bir yerde
        saklamasin; basarisiz bir yazimdan sonra ekran gercegi gostermeyi
        birakirdi.
        """
        return _reply(self._models_view(), error)

    def _agent_enabled(self) -> bool:
        """Agent acik mi (9.19.4). Yalnizca acik `False` kapatir."""
        return self._settings.get("agent", {}).get("enabled") is not False

    def _values_on(self) -> bool:
        """Degerler gonderilsin mi (9.27). Yalnizca acik `True` acar."""
        return self._settings.get("agent", {}).get("send_values") is True

    def _values_block(self, doc_id: str, doc: dict, context: object) -> dict | None:
        """Secili tablonun gorunen degerleri, istem icin. Kapaliyken ya da baglam
        gecersizken `None` — o zaman yalnizca sema gider.

        `context` arayuzden gelir: `{ds, variant, rows}`. Tablo bu belgede
        aranir, satirlar kaynak indeks olarak suzulur; arayuz baska bir belgenin
        tablosunu ya da sinirsiz satiri bu yoldan gonderemez.
        """
        if not self._values_on() or not isinstance(context, dict):
            return None
        ds_id = context.get("ds")
        ds = next((d for d in doc["datasets"] if d.id == ds_id), None)
        if ds is None:
            return None
        variant = context.get("variant")
        if variant is not None and not any(v.id == variant for v in ds.variants):
            return None
        rows = context.get("rows")
        if rows is not None:
            if not isinstance(rows, list) or not all(type(i) is int for i in rows):
                return None
        table, view = self._table_for_output(doc, ds, doc_id, ds_id, variant)
        # Gorsel GITMEZ (SECURITY.md): gomulu veri ya da yol yerine yer tutucu.
        # Ic ice alt tablolar da gezilir — metin ciktisi onlari `alan=deger`
        # olarak aciyor ve gorsel yolu oradan sizardi.
        mark = {"k": F.C_SCALAR, "d": I18N.t("agent.image_cell")}

        def scrub(cells: list) -> list:
            out = []
            for c in cells:
                if c and c.get("k") == F.C_IMAGE:
                    c = mark
                elif c and c.get("sub"):
                    c = {**c, "sub": {**c["sub"], "rows": [scrub(r) for r in c["sub"]["rows"]]}}
                out.append(c)
            return out

        table = {**table, "rows": [scrub(r) for r in table["rows"]]}
        order = rows if rows is not None else list(range(len(table["rows"])))
        order = [i for i in order if 0 <= i < len(table["rows"])]
        text = T.table_markdown(table, view, order[:VALUE_ROWS])
        cut = len(text) > VALUE_CHARS
        if cut:
            text = text[:text.rfind("\n", 0, VALUE_CHARS)]
        sent = text.count("\n") - 1                 # baslik + ayirici satiri
        return {"label": table["label"], "text": text, "sent": max(sent, 0),
                "total": len(order)}

    def agent_status(self) -> dict:
        """Saglayici kullanilabilir mi? Sohbet penceresi buna gore etkinlesir."""
        prov = self._provider()
        # Kapaliyken saglayiciya HIC sorulmaz: CLI'nin kullanilabilirlik
        # denetimi bir surec baslatiyor, kapali bir ozellik icin o da calismamali.
        if self._agent_enabled():
            ok, detail = prov.available()
        else:
            ok, detail = False, I18N.t("err.agent_off")

        models = self._models(prov)
        # Saglayici degisince eski model secimi anlamsiz kalabilir; ilk uyeye
        # duser. Ayni kalip `theme.get_theme`de: disari daima CIZILEBILIR bir
        # deger gider.
        if self._model not in models:
            self._model = models[0] if models else AGENT_MODEL_DEFAULT
        # Listesi BOS saglayici (ozel saglayici, model eklenmeden) soru
        # soramaz: gonderilecek bir model kimligi yok. Sebep ekranda yazar.
        if ok and not models:
            ok, detail = False, I18N.t(
                "err.no_models", provider=I18N.t(f"provider.{prov.key}.label"))

        # ⚠ Donus TEK SEKILDIR — kullanilabilirlik bir ALAN, iki ayri sozlesme
        # degil. Once kullanilamaz durumda erken donuluyordu ve arayuz
        # `models`/`efforts`i o dalda da kosulsuz okuyor; her yeni alan icin
        # "hangi dala yazayim?" sorusu yeniden soruluyordu ve yanlis cevap
        # sessizce geciyordu (`usesEffort`te tam bu oldu). Uc listenin hicbiri
        # zaten kullanilabilirlige bagli degil: model listesi anahtarsiz da
        # cozuluyor, eylemler ve caba duzeyleri sabit.
        return {"ok": True, "available": ok,
                "enabled": self._agent_enabled(),
                # 9.27 — seritteki "veri gonderimi acik" isareti buna bakar.
                "values": self._values_on(),
                "error": "" if ok else detail,
                # `path` yalnizca kullanilabilirken anlamli: `available()`
                # basarisizken ikinci deger SEBEP metnidir, yol degil.
                "path": detail if ok else "",
                "provider": prov.key,
                # Etiketler CAGRI ANINDA cozulur: dil oturum icinde degisebilir.
                "actions": [{"key": k, "label": I18N.t(f"action.{k}.label"),
                             "question": I18N.t(f"action.{k}.q")} for k in SCHEMA.ACTIONS],
                "models": [_model_view(prov, k) for k in models],
                "model": self._model,
                # ⚠ Caba listesi saglayici onu KULLANMASA DA gider ve secilen
                # deger KORUNUR (`AK-16`): kullanici Gemini'ye gecip CLI'ye
                # donunce cabasini sifirlanmis bulmamali. Gizleme ekranin
                # isidir, verinin degil — donusun sekli saglayiciya gore
                # degisseydi arayuz iki ayri bicimi bilmek zorunda kalirdi.
                "usesEffort": prov.uses_effort,
                "efforts": [{"key": k, "label": I18N.t(f"effort.{k}.label"),
                             "note": I18N.t(f"effort.{k}.note")} for k in AGENT_EFFORTS],
                "effort": self._effort}

    # --- API anahtarlari (9.5.2.2) ------------------------------------------
    #
    # Metotlar `api_settings`te DEGIL burada: anahtar bir tercih degil, bir
    # SAGLAYICI ozelligi — hangi saglayicilarin anahtar istedigi `providers.py`
    # kaydindan geliyor ve liste oradan turemek zorunda. Ekranda ayarlar
    # penceresinde gorunmesi bunu degistirmiyor (menu/arac cubugu ayrimindaki
    # "kanonik ev" kalibi).
    #
    # ⚠ **Anahtarin KENDISI hicbir donuste yer almaz** — disari cikan tek bilgi
    # `saved`. `9.12`de ayar dosyasinin yolunun kopruden cikarilmasiyla ayni
    # gerekce: tasinmasi gerekmeyen bir degeri tasimak, onu bir gun bir tanilama
    # metnine ya da hata mesajina sizdirmanin en kolay yoludur.

    def agent_keys(self) -> dict:
        """Anahtar isteyen saglayicilar ve her biri icin YALNIZCA 'kayitli mi'."""
        return {"ok": True, **self._keys_view()}

    def agent_key_set(self, provider: str, value: str = "") -> dict:
        """Anahtari sifreleyip kaydeder. Deger donuste GERI VERILMEZ."""
        prov = self._key_provider(provider)
        if prov is None:
            return self._keys_reply(I18N.t("err.unknown_provider", provider=provider))
        try:
            KEYS.store(prov.key, value)
        except KEYS.KeyStoreError as exc:
            return self._keys_reply(str(exc))
        return self._keys_reply()

    def agent_key_clear(self, provider: str) -> dict:
        """Kayitli anahtari siler."""
        prov = self._key_provider(provider)
        if prov is None:
            return self._keys_reply(I18N.t("err.unknown_provider", provider=provider))
        try:
            KEYS.clear(prov.key)
        except KEYS.KeyStoreError as exc:
            return self._keys_reply(str(exc))
        return self._keys_reply()

    def _key_provider(self, name: str) -> P.Provider | None:
        """Adi anahtar isteyen KAYITLI bir saglayiciya cozer, yoksa `None`.

        ⚠ `providers.get()` BURADA KULLANILMAZ. O islev taninmayan degeri
        varsayilana dusuruyor (bozuk ayar dosyasi uygulamayi agentsiz
        birakmasin diye) ve burada aynisi yapilsaydi, arayuzden gelen yanlis
        bir ad anahtari sessizce `cli`nin altina yazardi — hem yanlis yere,
        hem de anahtar hic istemeyen bir saglayicinin altina.
        """
        prov = P.PROVIDERS.get(name or "")
        return prov if prov is not None and prov.needs_key else None

    def _keys_view(self) -> dict:
        """Arayuzun cizdigi liste. Etiketler CAGRI ANINDA cozulur (dil degisebilir)."""
        saved = set(KEYS.names())
        return {
            # Depo yoksa (DPAPI bulunamadi) alanlar acilir ama yazilamaz;
            # arayuz sebebi yaziyor, sessizce ise yaramayan bir kutu birakmiyor.
            "store": KEYS.available(),
            "providers": [{"key": p.key,
                           "label": I18N.t(f"provider.{p.key}.label"),
                           # Uyari METIN olarak gider, anahtar olarak degil:
                           # arayuz ikinci bir sozluk tutmuyor ve dil
                           # cozumlemesi tek yerde kaliyor.
                           "note": I18N.t(p.note) if p.note else "",
                           "saved": p.key in saved}
                          for p in P.PROVIDERS.values() if p.needs_key],
        }

    def _keys_reply(self, error: str | None = None) -> dict:
        """Iki yazicinin ortak donusu.

        Liste her donuste yeniden kurulur: arayuz "kayitli mi" durumunu ikinci
        bir yerde saklamasin, yoksa basarisiz bir yazimdan sonra ekran gercegi
        gostermeyi birakirdi.
        """
        return _reply(self._keys_view(), error)

    def agent_thread(self, doc_id: str) -> dict:
        """Belgenin sohbet dizisi. Arayuz pencereyi acinca bunu cizer.

        Sohbet Python tarafinda saklanir: gonderilen gecmisin tek kaynagi ile
        ekranda gorunenin tek kaynagi ayni olsun diye (bkz. gorunum durumu).
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        return {"ok": True, "doc": doc["name"], "messages": self._chats.get(doc_id, [])}

    def agent_reset(self, doc_id: str) -> dict:
        """Sohbeti temizler; sonraki soru gecmissiz gider."""
        self._chats.pop(doc_id, None)
        return {"ok": True, "messages": []}

    def agent_payload(self, doc_id: str) -> dict:
        """Gonderilecek semayi ONIZLEME icin dondurur — hicbir sey gonderilmez.

        Kullanicinin gitmeden once tam olarak neyin gidecegini gormesi icin.
        """
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        try:
            payload = SCHEMA.document_schema(doc["name"], doc["root"], doc["datasets"])
            text = SCHEMA.schema_markdown(payload)
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}
        return {"ok": True, "text": text, "chars": len(text),
                "datasets": payload["dataset_count"]}

    def agent_ask(self, doc_id: str, question: str, model: str | None = None,
                  effort: str | None = None, context: dict | None = None) -> dict:
        """Semayi, sohbet gecmisini ve soruyu SECILI saglayiciya gonderir.

        `context` (9.27): ekranda secili tablo `{ds, variant, rows}`. Yalnizca
        `agent.send_values` aciksa kullanilir; kapaliyken hic okunmaz.
        """
        # ⚠ Sinir BURADA, arayuzde degil (9.19.4): serit gizli olsa da kopru
        # cagrilabilir. Kapaliyken sema kurulmaz, saglayiciya dokunulmaz.
        if not self._agent_enabled():
            return {"ok": False, "error": I18N.t("err.agent_off")}
        doc = self._docs.get(doc_id)
        if doc is None:
            return {"ok": False, "error": I18N.t("err.doc_closed", id=doc_id)}
        question = (question or "").strip()
        if not question:
            return {"ok": False, "error": I18N.t("err.empty_question")}

        prov = self._provider()
        if not self._models(prov):
            return {"ok": False, "error": I18N.t(
                "err.no_models", provider=I18N.t(f"provider.{prov.key}.label"))}

        # Model ve caba arayuzden gelir ama BURADA dogrulanir: cagriya yalnizca
        # bilinen degerler girer. CLI'de kabuk kullanilmadigi icin enjeksiyon
        # riski yok, yine de tanimsiz bir deger anlasilmaz bir hata uretirdi.
        if model:
            # ⚠ `prov.models()` DEGIL `self._models(prov)`: dogrulama, menuyu
            # besleyen listeyle ayni olmak zorunda. Fabrika listesine bakmak,
            # kullanicinin kendi ekledigi modeli "bilinmeyen model" diye
            # reddederdi.
            if model not in self._models(prov):
                return {"ok": False, "error": I18N.t("err.unknown_model", model=model)}
            self._model = model
        if effort:
            if effort not in AGENT_EFFORT_KEYS:
                return {"ok": False,
                        "error": I18N.t("err.unknown_effort", effort=effort)}
            self._effort = effort

        try:
            payload = SCHEMA.document_schema(doc["name"], doc["root"], doc["datasets"])
            values = self._values_block(doc_id, doc, context)
            prompt = SCHEMA.build_prompt(payload, question, self._history(doc_id), values)
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        try:
            answer = prov.ask(prompt, self._model, self._effort)
        except P.ProviderError as exc:
            # Mesaj zaten cevrilmis; oldugu gibi gider.
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": traceback.format_exc(limit=3)}

        # Sohbete yalnizca TAMAMLANAN tur yazilir. Basarisiz cagrida soru da
        # eklenmez; yoksa yanitsiz bir soru gecmise girip sonraki turu kirletir.
        thread = self._chats.setdefault(doc_id, [])
        thread.append({"role": "user", "text": question})
        thread.append({"role": "assistant", "text": answer})

        return {"ok": True, "answer": answer, "sent_chars": len(prompt),
                "turns": len(thread) // 2, "model": self._model,
                "effort": self._effort, "provider": prov.key}

    def _history(self, doc_id: str) -> list[tuple[str, str]]:
        """Tamamlanmis (soru, yanit) ciftleri — istem gecmisi bundan kurulur."""
        msgs = self._chats.get(doc_id, [])
        return [(msgs[i]["text"], msgs[i + 1]["text"])
                for i in range(0, len(msgs) - 1, 2)
                if msgs[i]["role"] == "user" and msgs[i + 1]["role"] == "assistant"]
