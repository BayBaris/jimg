'use strict';

/* Uygulama kabugu: logo menusu ve sol panelin daraltilmasi (Faz 9.3.2).
 *
 * `main.js`ten AYRI durur cunku orasi "baslatma ve olay baglama"dir; kabugun
 * kendi davranisi oraya girseydi dosya cop kutusuna donerdi. Ayarlar ekrani
 * (`9.3.3`) ve Hakkinda/tanilama (`9.3.4`) de buraya gelecek.
 *
 * ⚠ **Menu kanonik ev, ikonlar kisayol.** Ayni eylem hem `app-menu` icinde hem
 * arac cubugunda duruyor ve ikisi de AYNI islevi cagiriyor (`runOpen`,
 * `openPanel`, `toggleDock`). Menude ikinci bir uygulama yazilsaydi ikisi
 * zamanla birbirinden sapardi.
 */

/* Kenar cubugu kisayoli. Tus adi CEVRILMEZ: `Ctrl` ve `B` tus etiketleri,
   arayuz metni degil — Turkce klavyede de ayni yaziyor. */
const SIDEBAR_KEY = 'Ctrl+B';

/** Uygulama menusu: logoya tiklayinca acilir.
 *
 * Ayarlar ve Yardim maddeleri BILEREK yok — ekranlari `9.3.3` ve `9.3.4`te
 * kuruluyor. Hicbir sey yapmayan bir menu maddesi birakmak, olmayan maddeden
 * daha kotudur.
 */
function buildAppMenu() {
  const m = $('app-menu');
  m.replaceChildren();

  // Aciklama satiri YOK, grup basligi var: baslik zaten hangi bolumde
  // oldugunu soyluyor ve etiketler kendi kendini anlatiyor. Kisayol varsa
  // satirin sagina yazilir — menu, kisayolun ogrenildigi yerdir.
  const groups = [
    [t('menu.file'), [
      [t('ui.open_files'), '', () => runOpen(() => api.open_files())],
      [t('menu.open_folder'), '', () => runOpen(() => api.open_folder())],
    ]],
    [t('menu.view'), [
      [t('menu.sidebar'), SIDEBAR_KEY, toggleSidebar],
      [t('ui.export'), '', () => openPanel()],
      // 9.19.4 — kapali Agent menude de gorunmez: hicbir sey yapmayan madde
      // birakilmaz (§1).
      ...(agentOn ? [[t('ui.agent'), '', () => toggleDock()]] : []),
    ]],
    // Basliksiz bolum: tek maddelik bir grup "AYARLAR / Ayarlar" diye iki kez
    // okunurdu. Ustune ince bir ayrac konur, baslik konmaz.
    ['', [
      [t('ui.settings'), '', () => openSettings()],
    ]],
    // ⚠ Tanilama menude YOK. Hakkinda penceresinde GORUNEN bilgiyi kopyaliyor,
    // yani baglami o pencere; menuden cagirmak kullaniciya ne kopyalandigini
    // gostermeden pano degistirirdi. Dugmesi Hakkinda'nin altbilgisinde.
    [t('menu.help'), [
      [t('ui.about'), '', () => openAbout()],
    ]],
  ];

  for (const [head, items] of groups) {
    if (head) m.append(menuHead(head));
    else m.append(Object.assign(document.createElement('div'),
                                { className: 'menu-sep' }));
    for (const [label, side, run] of items) {
      menuItem(m, { label, side, sideClass: 'menu-key', run });
    }
  }
}

/* --- Ayarlar ekrani (Faz 9.3.3) ------------------------------------------- */

/** Ayarlar penceresini acar ve gecerli degerleri doldurur.
 *
 * Degerler HER ACILISTA kopruden alinir, arayuzde onbelleklenmez: ayarlar tek
 * kaynak olarak Python tarafinda duruyor (`Api._settings`) ve ikinci bir kopya
 * tutmak sapma uretirdi.
 */
async function openSettings() {
  // Iki modal ust uste binmesin: disa aktarma paneli aciksa kapanir.
  if (!$('export-overlay').hidden) closeExport();

  const res = await api.settings_get();
  if (!res.ok) return setStatus(res.error, true);

  // Liste kopruden gelir (`i18n.CHOICES`); JS'te sabitlenmis ikinci bir kopya
  // yok — tema, yazi tipi ve boyut seciciyle ayni kalip.
  fillSelect($('set-language'),
             langKeys.map((k) => ({ key: k, label: t(`lang.${k}`) })),
             res.settings.language);

  // ⚠ Secicide TERCIH gorunur (`system`), cozulmus deger degil. Cozulmus hali
  // `data-theme` olarak kok ogede duruyor; ikisini karistirmak "Sistem"
  // secildikten sonra secicide `Koyu` yazmasi demekti.
  fillSelect($('set-theme'),
             themeKeys.map((k) => ({ key: k, label: t(`theme.${k}`) })),
             res.settings.theme);

  fillSelect($('set-font'),
             fontKeys.map((k) => ({ key: k, label: t(`font.${k}`) })),
             (res.settings.font || {}).family);

  // Boyut etiketi CEVRILMEZ: sayi ve `px` birim adi, arayuz metni degil.
  fillSelect($('set-font-size'),
             fontSizes.map((n) => ({ key: String(n), label: `${n} px` })),
             String((res.settings.font || {}).size));

  // ⚠ Seçili sağlayıcı `settings.agent`ten okunur, `agent_status`tan değil:
  // `agent_status` çalışabilir bir değere düşürüyor (tanınmayan ad varsayılana
  // düşer) ve seçicide TERCİH görünmeli, çözülmüş değer değil — temadaki
  // `Sistem` ile aynı ayrım.
  fillSelect($('set-provider'),
             providerKeys.map((k) => ({ key: k, label: t(`provider.${k}.label`) })),
             (res.settings.agent || {}).provider);

  // 9.19 — yeni tercihler. Listeler yine kopruden (`theme.DENSITIES`,
  // `theme.EXPORT_THEMES`); bool ayarlar iki anahtarli secici.
  const s = res.settings;
  fillSelect($('set-export-theme'),
             exportThemeKeys.map((k) => ({ key: k, label: t(`export_theme.${k}`) })),
             (s.export || {}).theme);
  fillSelect($('set-density'),
             densityKeys.map((k) => ({ key: k, label: t(`density.${k}`) })),
             (s.table || {}).density);
  fillSelect($('set-wrap'),
             [{ key: 'on', label: t('ui.wrap_on') },
              { key: 'off', label: t('ui.wrap_off') }],
             (s.table || {}).wrap === false ? 'off' : 'on');
  fillSelect($('set-agent'),
             [{ key: 'on', label: t('ui.agent_on') },
              { key: 'off', label: t('ui.agent_off') }],
             (s.agent || {}).enabled === false ? 'off' : 'on');
  fillSelect($('set-agent-values'),
             [{ key: 'off', label: t('ui.agent_values_off') },
              { key: 'on', label: t('ui.agent_values_on') }],
             (s.agent || {}).send_values === true ? 'on' : 'off');
  fillSelect($('set-restore'),
             [{ key: 'off', label: t('ui.restore_off') },
              { key: 'on', label: t('ui.restore_on') }],
             (s.documents || {}).restore ? 'on' : 'off');

  // 9.21 — ozel saglayicinin adresi: kullanicinin YAZDIGI haliyle gosterilir.
  $('set-custom-url').value = (s.agent || {}).custom_url || '';
  $('set-custom-url').placeholder = t('ui.custom_url_hint');

  // 9.6.5.2 — gorsel adresleri; ayar bir bool, secici iki anahtar.
  fillSelect($('set-images-url'),
             [{ key: 'off', label: t('ui.images_url_off') },
              { key: 'on', label: t('ui.images_url_on') }],
             (res.settings.images || {}).allow_url ? 'on' : 'off');

  // 10.5.2 — KB-4: yedek. Ayni kalip, ayar yine bool.
  fillSelect($('set-backup'),
             [{ key: 'on', label: t('ui.backup_on') },
              { key: 'off', label: t('ui.backup_off') }],
             (res.settings.documents || {}).backup === false ? 'off' : 'on');

  await fillKeys();
  await openModelList();

  showSettingsTab(settingsTab, false);
  $('settings-overlay').hidden = false;
}

function closeSettings() { $('settings-overlay').hidden = true; }

/* Ayarlarda son acilan sekme (9.14.2). Oturum boyunca kalir, diske yazilmaz:
   pencere kapatilip yeniden acildiginda — ya da Modeller'den `‹` ile
   donuldugunde — kullanici biraktigi yerde olur. */
let settingsTab = 'view';

/** Sekmeyi secer: paneli gosterir, `aria-selected` ve dolasan `tabindex`i yazar. */
function showSettingsTab(key, focus) {
  const tabs = [...document.querySelectorAll('#settings-overlay .set-tab')];
  if (!tabs.some((b) => b.dataset.tab === key)) key = tabs[0].dataset.tab;
  settingsTab = key;
  for (const b of tabs) {
    const on = b.dataset.tab === key;
    b.classList.toggle('on', on);
    b.setAttribute('aria-selected', String(on));
    b.tabIndex = on ? 0 : -1;
    $(b.getAttribute('aria-controls')).hidden = !on;
    if (on && focus) b.focus();
  }
  // Yeni panel bastan okunur; onceki sekmenin kaydirma konumu tasinmaz.
  document.querySelector('#settings-overlay .set-panes').scrollTop = 0;
}

/** Dikey sekme listesi klavyesi: yukari/asagi dongusel, Home/End uclar. */
function settingsTabKey(e) {
  const tabs = [...document.querySelectorAll('#settings-overlay .set-tab')];
  const i = tabs.findIndex((b) => b.dataset.tab === settingsTab);
  const next = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault();
  showSettingsTab(tabs[(next + tabs.length) % tabs.length].dataset.tab, true);
}

/* --- API anahtarlari (Faz 9.5.2.2) ---------------------------------------- */

/** Anahtar satirlarini köprüden kurar.
 *
 * Liste `agent_keys()`ten gelir; hangi sağlayıcının anahtar istediğini
 * `providers.py` kaydı biliyor. Burada sabitlenmiş ikinci bir liste, dil ve
 * tema seçicilerinde olduğu gibi zamanla sapardı.
 *
 * ⚠ **Kutuya kayıtlı anahtar YAZILAMAZ** — köprü değeri döndürmüyor ve
 * döndürmemeli. "Kayıtlı mı" bilgisi yer tutucuda görünür, değerin kendisi
 * hiçbir yerde görünmez.
 *
 * ⚠ Anahtar isteyen sağlayıcı yoksa bölümün tamamı gizlenir: boş bir başlık
 * bırakmak, ekranı hazır olmayan madde bırakmak olurdu.
 */
async function fillKeys() {
  const res = await api.agent_keys();
  const box = $('set-keys');
  const rows = $('set-keys-rows');

  rows.textContent = '';
  box.hidden = !res.ok || !res.providers.length;
  if (box.hidden) return;

  // Depo yoksa kutular açılır ama yazılamaz ve SEBEBİ yazar; sessizce işe
  // yaramayan bir alan bırakmak kullanıcıyı anahtarı arayarak dolaştırırdı.
  const note = $('set-keys-note');
  note.hidden = res.store;
  note.textContent = res.store ? '' : t('err.keys_unavailable');

  for (const p of res.providers) {
    const row = document.createElement('label');
    row.className = 'dlg-row';

    const label = document.createElement('span');
    label.className = 'lbl-txt';
    label.textContent = p.label;

    const field = document.createElement('span');
    field.className = 'key-field';

    const input = document.createElement('input');
    input.type = 'password';
    input.className = 'key-input';
    input.placeholder = p.saved ? t('ui.key_saved') : t('ui.key_enter');
    input.disabled = !res.store;
    // Yazarken değil, kutudan çıkarken/Enter'da yazılır: her tuş vuruşunda
    // şifreleyip diske yazmak yarım anahtarları kaydederdi.
    input.addEventListener('change', () => saveProviderKey(p, input));
    field.append(input);

    // Silme düğmesi yalnızca kayıtlı anahtarda KURULUR — `hidden` ile
    // gizlenmiyor, çünkü `.ibtn` kendi `display`ini yazıyor ve `[hidden]`
    // eşliği olmayan öğe gizlenmek yerine görünür kalırdı.
    if (p.saved) {
      const del = document.createElement('button');
      del.type = 'button';
      // `.ibtn.close` hover'da kırmızıya döner — silme düğmesinin doğru
      // ailesi bu; ayrı bir sınıf gerekmiyor.
      del.className = 'ibtn close';
      del.textContent = '×';
      del.setAttribute('aria-label', t('ui.key_clear'));
      del.addEventListener('click', () => clearProviderKey(p));
      field.append(del);
    }

    row.append(label, field);
    rows.append(row);
  }
  fillKeyInfo(res.providers);
}

/** Sağlayıcı notlarını başlığın altındaki TEK açıklamada toplar (9.18).
 *
 * Notlar satırların altında dururken blok üç ayrı paragrafla uzuyordu ve
 * ikisi aynı cümleydi. Aynı notu taşıyan sağlayıcılar tek satırda birleşir.
 *
 * ⚠ Not SAĞLAYICIYA bağlı, "bedava katman"a değil: Groq bedava katmanda
 * veriyi eğitime almıyor, Google alıyor. Metin köprüden çözülmüş gelir;
 * gruplama metne göre yapılır, yani iki dilde de aynı çalışır.
 */
function fillKeyInfo(providers) {
  const box = $('set-keys-info');
  box.textContent = '';

  const groups = new Map();
  for (const p of providers) {
    if (!p.note) continue;
    if (!groups.has(p.note)) groups.set(p.note, []);
    groups.get(p.note).push(p.label);
  }
  for (const [note, labels] of groups) {
    const line = document.createElement('span');
    line.className = 'set-desc';
    const who = document.createElement('span');
    who.className = 'key-who';
    who.textContent = labels.join(' · ');
    line.append(who, ` — ${note}`);
    box.append(line);
  }
}

/* --- Model listesi (Faz 9.5.5.2 · Ayarlar'in Agent sekmesinde, 9.14.2.1) --- */

/* Düzenlenen sağlayıcı. ⚠ Bu, KULLANILAN sağlayıcı değildir: blok
   `settings.agent.provider`a hiç dokunmaz, yalnızca hangi listenin
   düzenlendiğini tutar. Hemen üstteki seçiciyle aynı görünen bir kutu,
   birinin ne yaptığını yanlış öğretirdi — etiketi de bu yüzden ayrı. */
let mdlProvider = '';
/* Son köprü dönüşü. Üç yazıcı da (`ekle`, `çıkar`, `sıfırla`) listenin
   tamamını geri döndürüyor, yani ayrı bir okuma çağrısı açılmaz. */
let mdlData = null;

/** Ayarlar açılırken listeyi yükler. Düzenlemeye KULLANILAN sağlayıcıdan
 *  başlanır: bloğa bakan kullanıcı çoğunlukla o an kullandığı listeyi arıyor.
 *  ⚠ Bu bilgi `agent_models` dönüşünde geliyor; ayrı bir `settings_get`
 *  okuması gerekmiyor.
 */
async function openModelList() {
  mdlData = await api.agent_models();
  mdlProvider = mdlData.provider || mdlProvider;
  renderModels();
}

/** Veriyi tazeler. `res` verilirse köprü ÇAĞRILMAZ: üç yazıcı da listenin
 *  tamamını döndürüyor, ikinci bir çağrı aynı veriyi iki kez getirirdi.
 */
async function loadModels(res) {
  mdlData = res || await api.agent_models();
  renderModels();
}

/** Elde duran veriyi çizer. ⚠ Veri okumaktan AYRI durur: birleşikken
 *  sağlayıcı değişimi `fillModels(mdlData)` diye, işleve az önce kendisinin
 *  yazdığı değeri geri veren bir çağrı oluyordu — "tazele" mi "yalnızca çiz"
 *  mi belli değildi ve senkron bir iş `async` görünüyordu.
 */
function renderModels() {
  const list = (mdlData || {}).providers || [];
  if (!list.some((p) => p.key === mdlProvider)) mdlProvider = (list[0] || {}).key || '';
  const cur = list.find((p) => p.key === mdlProvider) || { models: [] };

  fillSelect($('mdl-provider'),
             list.map((p) => ({ key: p.key, label: p.label })), mdlProvider);
  $('mdl-new').placeholder = t('ui.model_new');
  $('mdl-state').textContent =
    cur.edited ? t('ui.models_edited') : t('ui.models_default', { max: mdlData.max });
  // ⚠ Sıfırlama yalnızca SAPMIŞ listede anlamlı; fabrika listesinde etkin
  // bırakmak hiçbir şey yapmayan bir düğme demekti.
  $('mdl-reset').disabled = !cur.edited;

  const rows = $('mdl-rows');
  rows.replaceChildren();
  for (const m of cur.models) {
    const row = document.createElement('div');
    row.className = 'dlg-row';

    const name = document.createElement('span');
    // ⚠ Özel modelin etiketi kimliğin kendisi; ayrımı köprü yapıyor
    // (`_model_view`), arayüz ikinci bir kural yazmıyor.
    name.className = m.custom ? 'lbl-txt mdl-id' : 'lbl-txt';
    name.textContent = m.label;

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'ibtn close';
    del.textContent = '×';
    del.setAttribute('aria-label', t('ui.model_remove'));
    // ⚠ Çağrı KIMLIKLE, ileti ETIKETLE: kullanıcı satırda `Sonnet` görüyor,
    // durum çubuğunda `sonnet` yazsaydı ikisini aynı şey saymazdı. Özel
    // modelde ikisi zaten aynı.
    del.addEventListener('click', () => removeModel(m.key, m.label));

    // Satırın altında açıklama YOK (9.20, kullanıcı kararı): listeyi düzenleyen
    // kişi ne eklediğini bilir. Model açıklaması yalnızca SEÇİM anında, sohbet
    // şeridinin model menüsünde görünür. Kullanıcının eklediği kimlik
    // eşaralıklı yazıyla ayrışır (`.mdl-id`).
    row.append(name, del);
    rows.append(row);
  }
}

async function addModel() {
  const box = $('mdl-new');
  const res = await api.agent_model_add(mdlProvider, box.value);
  if (!res.ok) return setStatus(res.error, true);
  // Kutu YALNIZCA başarıda boşaltılır: reddedilen kimliği silmek, kullanıcıyı
  // yazdığı şeyi baştan yazmaya zorlardı — anahtar kutusundaki kararın tersi,
  // çünkü orada kalan metin "kaydedildi" izlenimi veriyordu.
  setStatus(t('msg.model_added', { model: box.value.trim() }));
  box.value = '';
  await loadModels(res);
}

async function removeModel(key, label) {
  const res = await api.agent_model_remove(mdlProvider, key);
  if (!res.ok) return setStatus(res.error, true);
  setStatus(t('msg.model_removed', { model: label || key }));
  await loadModels(res);
}

async function resetModels() {
  const res = await api.agent_models_reset(mdlProvider);
  if (!res.ok) return setStatus(res.error, true);
  setStatus(t('msg.models_reset'));
  await loadModels(res);
}

/* ⚠ Adlar `saveKey`/`clearKey` OLAMAZ: `panel.js` zaten `saveKey` tanımlıyor
   ve JS dosyaları tek küresel kapsamı paylaşıyor — çarpışan ad ikinci dosyayı
   `SyntaxError` ile baştan sona çalıştırmıyor. İlk yazımda tam bu oldu ve
   `check_web` o zaman göremiyordu; artık görüyor. */
/** Özel sağlayıcının adresini yazar (9.21).
 *
 * Kutudan çıkarken/Enter'da çalışır. Geçersiz adres YAZILMAZ ve kutuda KALIR —
 * model kimliğindeki kararın aynısı: silinen metin kullanıcıyı baştan yazmaya
 * zorlardı. Başarıda isteğin gideceği TAM adres durum çubuğunda söylenir.
 */
async function saveCustomUrl(input) {
  const res = await api.agent_endpoint_set(input.value);
  if (!res.ok) return setStatus(res.error, true);
  input.value = res.url;
  setStatus(res.endpoint ? t('msg.custom_saved', { url: res.endpoint })
                         : t('msg.custom_cleared'));
  if (dockOpen) await loadChat();
}

async function saveProviderKey(p, input) {
  const value = input.value.trim();
  if (!value) return;
  const res = await api.agent_key_set(p.key, value);
  // Kutu HER DURUMDA boşaltılır: başarısız bir yazımdan sonra ekranda duran
  // metin "kaydedildi" izlenimi verirdi.
  input.value = '';
  if (!res.ok) return setStatus(res.error, true);
  setStatus(t('msg.key_saved', {provider: p.label}));
  await fillKeys();
}

async function clearProviderKey(p) {
  const res = await api.agent_key_clear(p.key);
  if (!res.ok) return setStatus(res.error, true);
  setStatus(t('msg.key_cleared', {provider: p.label}));
  await fillKeys();
}

/** Ayarı köprüye yazar ve değişen ne ise onu arayüze uygular.
 *
 * ⚠ Tema ve yazı tipi ile dil AYNI maliyette değil. İlk ikisi kök öğedeki bir
 * öznitelik — renkleri ve aileyi CSS dağıtıyor, tablo yeniden kurulmuyor. Dil
 * ise köprüden **çözülmüş metin** getiriyor (tür adları, üretilen sütun
 * başlıkları) ve orada ağaç ile açık tablo yeniden çekilmek zorunda. Üçünü aynı
 * yoldan geçirmek, tema değiştiren kullanıcıya bedava bir tablo yeniden çizimi
 * ödetirdi.
 */
async function applySetting(patch) {
  const res = await api.settings_set(patch);
  if (!res.ok) return setStatus(t('msg.settings_failed', {error: res.error}), true);
  applyShell(res);
  // ⚠ Anahtar ve model satırları JS'te kurulduğu için `applyStrings` onlara
  // dokunmaz: yer tutucu, açıklama ve `aria-label` çizim anında çözülüyor. Dil
  // değişince satırlar yeniden kurulmalı, yoksa pencere açıkken eski dilde
  // kalırlar. Model açıklamaları köprüden çevrilmiş geldiği için liste de
  // yeniden okunur.
  if ('language' in patch) { await relocalize(); await fillKeys(); await openModelList(); }
  // ⚠ Boyut değişince tablo YENİDEN KURULMALI: sütun genişliği `charW()`ten
  // hesaplanıyor ve o da boyutu okuyor. CSS tek başına metni büyütür, sütun
  // ölçüsü eski kalırdı — ekran ile PNG tam da orada ayrışırdı.
  //
  // Karar yamaya bakarak veriliyor, çağıranın geçtiği bayrakla değil: bayrak
  // dinleyicide unutulabilir ve tablo sessizce eski genişlikte kalırdı.
  else if (patch.font && 'size' in patch.font && cur) render();
  // ⚠ Sağlayıcı değişince sohbet şeridi YENİDEN YÜKLENMELİ: model listesi,
  // kullanılabilirlik ve hata metni sağlayıcıdan geliyor. Yüklenmezse şerit
  // eski sağlayıcının modellerini gösterip yeni sağlayıcıya soru sorardı —
  // `agent_status` seçimi düzeltirdi ama ekranda yazan yanlış kalırdı.
  // 9.27 — veri gönderimi değişince şeritteki işaret de `agent_status`tan gelir.
  else if (patch.agent && ('provider' in patch.agent || 'send_values' in patch.agent)) {
    await loadChat();
  }
}

/** Dil değişince arayüzün YENİDEN KURULMASI gereken üç yeri.
 *
 * ⚠ Sozlugu yeniden almak YETMEZ. Uc yerde metin, uretildigi anda dile
 * baglanip saklaniyor:
 *   1. Statik kabuk — `applyStrings()` (bunu `loadStrings` yapiyor)
 *   2. Agac — veri kumesi TUR adlari (`kind_label`) kopruden cozulmus gelir
 *   3. Acik tablo — uretilen sutun basliklari (`Anahtar`, `Değer`, `Adet`…)
 * Ikincisi ve ucuncusu yalnizca yeniden CEKILINCE tazelenir.
 */
async function relocalize() {
  await loadStrings();
  applyTree(await api.tree());
  if (sel) await select(sel.docId, sel.dsId, sel.variantId);
}

async function resetSettings() {
  const res = await api.settings_reset();
  if (!res.ok) return setStatus(t('msg.settings_failed', {error: res.error}), true);
  // ⚠ `Varsayılanlara dön` API ANAHTARLARINA DOKUNMAZ: anahtarlar ayrı bir
  // kapta ve `settings_reset` onu hiç açmıyor. Bir tercihi geri almak isteyen
  // kullanıcının anahtarını silmek, geri alınamaz bir yan etki olurdu.
  // Satırlar yine de yeniden kurulur (`openSettings` → `fillKeys`).
  // Sifirlama her tercihe dokunabilir, o yuzden burada tam yol izlenir.
  applyShell(res);
  await relocalize();
  await openSettings();       // secicileri yeni degerlerle tazele
}

/* --- Hakkinda ve tanilama (Faz 9.3.4) ------------------------------------- */

/** Kunye satirlarini `app_info()`ten kurar; ikisi de ayni kaynaktan besleniyor. */
function infoRows(info) {
  return [
    [t('about.runtime'), `Python ${info.python} · ${info.platform} · `
      + t(info.frozen ? 'about.frozen' : 'about.dev')],
    // 9.9.2 — paketlenmis uygulamada HTTPS'in sertifika bulabildiginin kaniti.
    [t('about.tls'), t('about.tls_roots', { n: info.tls_roots })],
    [t('ui.language'), info.language],
  ];
}

function kvInto(box, rows) {
  box.replaceChildren();
  for (const [k, v] of rows) {
    const a = document.createElement('span');
    a.className = 'k';
    a.textContent = k;
    const b = document.createElement('span');
    b.className = 'v';
    b.textContent = v;
    box.append(a, b);
  }
}

async function openAbout() {
  if (!$('export-overlay').hidden) closeExport();

  const info = await api.app_info();
  if (!info.ok) return setStatus(info.error, true);

  $('about-name').textContent = info.name;
  $('about-version').textContent = `v${info.version}`;
  kvInto($('about-runtime'), infoRows(info));
  kvInto($('about-third'),
         info.third_party.map((d) => [`${d.name} ${d.version}`, d.license]));

  $('about-overlay').hidden = false;
}

function closeAbout() { $('about-overlay').hidden = true; }

/** Tanılama metnini panoya kopyalar.
 *
 * ⚠ **Dosya yolu ve son hata mesajı BILEREK yok.** `app_info()` yol tasimiyor
 * (ayar dosyasinin yolu ayri bir cagriyla gelir ve yalnizca ayarlar ekraninda
 * gorunur); hata mesajlari ise `OSError`i oldugu gibi tasiyor ve o da yol
 * iceriyor. Destek icin surum ve ortam yeter, yol sizdirmaya degmez.
 */
async function copyDiagnostics() {
  const info = await api.app_info();
  if (!info.ok) return setStatus(info.error, true);

  const lines = [`${info.name} v${info.version}`];
  for (const [k, v] of infoRows(info)) lines.push(`${k}: ${v}`);
  for (const d of info.third_party) lines.push(`${d.name} ${d.version} (${d.license})`);

  try {
    await copyToClipboard(lines.join('\n'));
    setStatus(t('msg.copied'));
  } catch (err) {
    setStatus(t('msg.copy_failed', {error: err}), true);
  }
}

/* --- Sol panelin daraltilmasi --------------------------------------------- */

/** Panel daraltilmis mi? Oturum icinde tutulur, diske YAZILMAZ.
 *
 * Kalici olmasi `settings.json`'a yeni bir anahtar ister ve ayarlar ekrani
 * `9.3.3`te kuruluyor — tercih oraya eklenecekse orada eklenmeli, yoksa iki
 * ayri kalicilik mekanizmasi dogar.
 */
let sidebarOpen = true;
// 9.14.4: Agent seridine yer acmak icin panel KENDILIGINDEN daraltildi mi.
// Kullanici tercihinden (`sidebarOpen`) ayri tutulur: yer acilinca ya da serit
// kapaninca panel geri gelir. Karari `fitLayout` (agent.js) verir.
let sideAuto = false;
// Kendiliginden daraltilmis paneli kullanici acti: bu serit acilisi boyunca
// yeniden daraltilmaz, serit cekmeceye doner. Serit kapaninca sifirlanir.
let sideKeep = false;

/** Panel su an acik mi gorunuyor. */
function sideShown() { return sidebarOpen && !sideAuto; }

/** Kullanici paneli acar ya da daraltir (dugme, menu, Ctrl+B).
 *
 * ⚠ Panel TUMDEN gizlenmez, dar seride iner. Tumden gizlense logo da giderdi;
 * logo uygulama menusunun tek girisi ve her zaman erisilebilir kalmali.
 */
function setSidebar(open) {
  if (open && sideAuto) sideKeep = true;
  sidebarOpen = open;
  fitLayout();
  renderSidebar();
}

/** Aç/kapa GÖRÜNEN duruma göre: kendiliğinden daraltılmış panelde tercih zaten
 *  "açık"tır ve `!sidebarOpen` hiçbir şey değiştirmezdi. */
function toggleSidebar() { setSidebar(!sideShown()); }

/** Görünümü durumdan yazar; durumu değiştirmez. */
function renderSidebar() {
  const open = sideShown();
  $('side').classList.toggle('collapsed', !open);

  const b = $('btn-side');
  const label = t(open ? 'ui.collapse' : 'ui.expand');
  b.setAttribute('aria-label', label);
  b.setAttribute('data-tip', label);
  b.setAttribute('aria-expanded', String(open));

  // ⚠ Genislik degisimi `#main`i de daraltiyor ve `NARROW_W` esigi ona bakiyor.
  // `ResizeObserver` bunu kendisi yakaliyor, burada elle tetiklemeye gerek yok.
}

/* --- Daraltilmis seritteki belge simgeleri -------------------------------- */

/** JSON simgesi: `{ }`.
 *
 * ⚠ Genel bir BELGE simgesi degil. Once katlanmis koseli dosya sekli
 * cizilmisti; o her turlu dosyayi anlatiyor, JSON'u anlatmiyor. Suslu parantez
 * JSON'un kendi isareti ve 14 px'te bile okunuyor — dosya cercevesi + icine
 * sigdirilmis parantez o boyutta lekeye donusurdu.
 *
 * Sekil ayrica projenin gorsel diliyle akraba: imlec ailesi ve logo da suslu
 * parantezden turer (Faz 8.1, 9.3.1).
 */
const JSON_ICON_PATHS = [
  'M6.5 2.4c-1.4 0-2 .6-2 1.9v1.7c0 1.1-.5 1.7-1.6 1.8 1.1.1 1.6.7 1.6 1.8v1.7'
    + 'c0 1.3.6 1.9 2 1.9',
  'M9.5 2.4c1.4 0 2 .6 2 1.9v1.7c0 1.1.5 1.7 1.6 1.8-1.1.1-1.6.7-1.6 1.8v1.7'
    + 'c0 1.3-.6 1.9-2 1.9',
];

function jsonIcon() {
  return svgIcon(JSON_ICON_PATHS, { cls: 'ico brace-ico' });
}

/** Acik belgeleri seritte JSON simgesi olarak cizer.
 *
 * Panel daraltilinca agac gizleniyor ve acik belgeler tamamen gorunmez
 * kaliyordu; serit yalnizca uygulama dugmelerini tasiyordu. Simgeye tiklamak
 * belgeyi secer ama paneli ACMAZ: serit hizli gecis icin var, tabloya ayrilan
 * genis alani geri daraltmasi anlamsiz olurdu.
 *
 * `renderTree` tarafindan cagrilir — agacin yeniden kuruldugu TEK yer orasi,
 * boylece iki liste ayrisamaz.
 */
function renderRailDocs() {
  const box = $('rail-docs');
  box.replaceChildren();

  for (const doc of (tree.docs || [])) {
    const b = document.createElement('button');
    b.className = 'btn icon rail-doc' + (sel && sel.docId === doc.id ? ' on' : '');
    b.setAttribute('data-tip', doc.name);
    b.setAttribute('aria-label', doc.name);
    b.setAttribute('aria-haspopup', 'menu');
    // 11.1 — simge + kisa ad: uzanti dusurulur, sigmazsa CSS uc nokta koyar.
    const name = document.createElement('span');
    name.className = 'rail-name';
    name.textContent = doc.name.replace(/\.json$/i, '');
    b.append(jsonIcon(), name);
    // 11.1 — tik belgeyi SECMEZ, tablolarini listeler: hangi tabloda
    // olundugu daraltilmis panelde baska yerden gorunmuyordu.
    b.addEventListener('click', (e) => openRailPop(e, doc, b));
    box.append(b);
  }
}

/** Seritteki belgenin tablolari ve varyantlari; secili olan isaretli (11.1).
 *  Ayni belgeye ikinci tik listeyi kapatir. Disari tik ve Esc de kapatir
 *  (`MENUS`). */
function openRailPop(e, doc, btn) {
  e.stopPropagation();
  const pop = $('rail-pop');
  const again = !pop.hidden && pop.dataset.doc === doc.id;
  for (const id of MENUS) $(id).hidden = true;
  if (again) return;

  pop.dataset.doc = doc.id;
  pop.replaceChildren(menuHead(doc.name));
  const item = (label, size, on, sub, run) => {
    const it = document.createElement('button');
    it.type = 'button';
    it.className = 'menu-item' + (sub ? ' sub' : '') + (on ? ' on' : '');
    it.setAttribute('role', 'menuitem');
    const l = document.createElement('span');
    l.textContent = label;
    const d = document.createElement('span');
    d.className = 'desc';
    d.textContent = size;
    it.append(l, d);
    it.addEventListener('click', (ev) => { ev.stopPropagation(); pop.hidden = true; run(); });
    pop.append(it);
  };
  const here = (dsId, vId) => !!sel && sel.docId === doc.id && sel.dsId === dsId
    && (sel.variantId || null) === vId;
  for (const ds of doc.datasets) {
    item(ds.label, `${ds.rows}×${ds.cols}`, here(ds.id, null), false,
         () => select(doc.id, ds.id, null));
    for (const v of ds.variants || []) {
      item(v.label, `${v.rows}×${v.cols}`, here(ds.id, v.id), true,
           () => select(doc.id, ds.id, v.id));
    }
  }
  // Kutucugun hizasinda; ekranin altina tasacaksa yukari kaydirilir.
  const side = $('side').getBoundingClientRect();
  const top = btn.getBoundingClientRect().top - side.top;
  pop.hidden = false;
  // Pencere yüksekliği ölçülemiyorsa (gizli/küçültülmüş pencere 0 verir)
  // kaydırma yapılmaz; yoksa liste en üste yapışırdı.
  const room = window.innerHeight - side.top - pop.offsetHeight - 8;
  pop.style.top = (window.innerHeight ? Math.max(0, Math.min(top, room)) : top) + 'px';
}

function initShell() {
  $('btn-app').addEventListener('click', (e) => toggleMenu(e, 'app-menu', buildAppMenu));
  $('btn-side').addEventListener('click', toggleSidebar);

  $('settings-close').addEventListener('click', closeSettings);
  $('settings-reset').addEventListener('click', resetSettings);
  for (const b of document.querySelectorAll('#settings-overlay .set-tab')) {
    b.addEventListener('click', () => showSettingsTab(b.dataset.tab, true));
  }
  document.querySelector('#settings-overlay .set-nav').addEventListener('keydown', settingsTabKey);
  $('set-language').addEventListener('change',
    (e) => applySetting({ language: e.target.value }));
  $('set-theme').addEventListener('change',
    (e) => applySetting({ theme: e.target.value }));
  $('set-font').addEventListener('change',
    (e) => applySetting({ font: { family: e.target.value } }));
  // Boyutun tabloyu yeniden kurdurmasi `applySetting` icinde, yamaya bakarak.
  $('set-font-size').addEventListener('change',
    (e) => applySetting({ font: { size: Number(e.target.value) } }));
  // Kullanilan saglayici degisince duzenlenen liste de ona gecer: yan yana
  // duran iki secicinin ayri seyler gostermesi yalnizca kullanici liste
  // seciciyi bilerek degistirdiginde olmali.
  $('set-provider').addEventListener('change', async (e) => {
    await applySetting({ agent: { provider: e.target.value } });
    await openModelList();
  });
  // `K-32` — ayar degisince acik tablo YENIDEN kurulur: adres hucreleri gorsel
  // olur ya da metne doner. Bellekteki belgeden cizilir, yeniden baslatma ve
  // "once kaydet" sorusu gerekmez (kaydedilmemis degisiklikler kaybolmaz).
  $('set-images-url').addEventListener('change', async (e) => {
    await applySetting({ images: { allow_url: e.target.value === 'on' } });
    await refreshTable();
  });
  $('set-backup').addEventListener('change',
    (e) => applySetting({ documents: { backup: e.target.value === 'on' } }));
  // 9.19 — yogunluk ve Agent `applyShell`den gecer (kok ogeye yazilir), tablo
  // yeniden kurulmaz. Uzun metin sutunun CIZIMINI degistirir: tablo bellekteki
  // belgeden yeniden kurulur (`K-32`deki ayni yol).
  $('set-export-theme').addEventListener('change',
    (e) => applySetting({ export: { theme: e.target.value } }));
  $('set-density').addEventListener('change',
    (e) => applySetting({ table: { density: e.target.value } }));
  $('set-wrap').addEventListener('change', async (e) => {
    await applySetting({ table: { wrap: e.target.value === 'on' } });
    await refreshTable();
  });
  $('set-agent').addEventListener('change',
    (e) => applySetting({ agent: { enabled: e.target.value === 'on' } }));
  $('set-agent-values').addEventListener('change',
    (e) => applySetting({ agent: { send_values: e.target.value === 'on' } }));
  $('set-custom-url').addEventListener('change', (e) => saveCustomUrl(e.target));
  $('set-restore').addEventListener('change',
    (e) => applySetting({ documents: { restore: e.target.value === 'on' } }));
  $('mdl-add').addEventListener('click', addModel);
  $('mdl-reset').addEventListener('click', resetModels);
  // ⚠ Buradaki secici `applySetting` CAGIRMAZ: yalnizca duzenlenen listeyi
  // degistirir, kullanilan saglayiciyi degil.
  $('mdl-provider').addEventListener('change', (e) => {
    mdlProvider = e.target.value;
    renderModels();
  });
  // Enter da ekler: kimlik yapistirilip Enter'a basmak dogal siradir.
  $('mdl-new').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); addModel(); }
  });

  $('about-close').addEventListener('click', closeAbout);
  $('about-diag').addEventListener('click', copyDiagnostics);
  // Ortuye tiklamak kapatir; pencerenin ICINE tiklamak kapatmamali.
  for (const [id, close] of [['settings-overlay', closeSettings],
                             ['about-overlay', closeAbout]]) {
    $(id).addEventListener('click', (e) => { if (e.target === $(id)) close(); });
  }

  // Ctrl+B: kenar cubugu ac/kapa. Bu kalip VS Code ve benzerlerinde standart;
  // kullanici zaten parmak aliskanligiyla deniyor.
  document.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'b')) return;
    e.preventDefault();
    toggleSidebar();
  });
}
