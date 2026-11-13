'use strict';

/* Baslatma ve olay baglama. EN SON yuklenir (bkz. index.html): buradaki
 * `init` diger dosyalarin tanimlarina dokunur, dolayisiyla hepsi cozulmus
 * olmali.
 *
 * Python ile tek temas noktasi `window.pywebview.api` (bkz. app.py -> Api).
 * Sutun sirasi/genisligi/gizliligi ve transpoze durumu Python'da saklanir.
 *
 * CSP `script-src 'self'`: satir ici `<script>` ve `onclick=""` CALISMAZ.
 * Olay baglama daima `addEventListener` ile, yani burada.
 */

window.addEventListener('pywebviewready', init);

async function init() {
  api = window.pywebview.api;

  // Dil sozlugu HER SEYDEN ONCE: `applyTree` ilk belgeyi cizerken grup ve tur
  // adlarini `t()` ile cozuyor. Sozluk gelmeden cizersek anahtarlar gorunur.
  await loadStrings();

  $('btn-open-files').addEventListener('click', () => runOpen(() => api.open_files()));
  $('btn-open-folder').addEventListener('click', () => runOpen(() => api.open_folder()));
  initShell();
  $('btn-transpose').addEventListener('click', onTranspose);
  $('btn-edit').addEventListener('click', toggleEditMode);
  // 10.6 — tablo adi: kipte baslikta cift tik ya da odaktayken F2/Enter.
  const renameTitle = () => sel && beginRename($('ds-title'), sel.docId, sel.dsId, sel.variantId);
  $('ds-title').addEventListener('dblclick', renameTitle);
  $('ds-title').addEventListener('keydown', (e) => {
    if (editOn && (e.key === 'F2' || e.key === 'Enter')) { e.preventDefault(); renameTitle(); }
  });
  $('btn-reset').addEventListener('click', (e) => toggleMenu(e, 'reset-menu', buildResetMenu));
  $('btn-doc').addEventListener('click', () => openPreview('text'));
  $('btn-export').addEventListener('click', openPanel);
  initAgentDock();
  initToolbarFit();
  initPressCursor();
  $('export-close').addEventListener('click', closeExport);
  $('text-copy').addEventListener('click', copyText);
  $('export-overlay').addEventListener('click', (e) => {
    // Boyutlandirma sirasinda fare panel disina cikar; o tiklama kapatmamali.
    if (resizing) return;
    if (e.target === $('export-overlay')) closeExport();
  });
  for (const b of $('text-kinds').querySelectorAll('.segbtn')) {
    b.addEventListener('click', () => openExport(b.dataset.kind));
  }
  for (const b of $('table-subs').querySelectorAll('.segbtn')) {
    b.addEventListener('click', () => showTableSub(b.dataset.sub));
  }
  for (const tab of $('export-tabs').querySelectorAll('.tab')) {
    tab.addEventListener('click', () => switchCategory(tab.dataset.cat));
  }
  $('chart-cat').addEventListener('change', (e) => {
    if (chartMode === 'distribution') chartPick = e.target.value;
    renderChart();
  });
  for (const id of ['chart-num', 'chart-agg']) {
    $(id).addEventListener('change', renderChart);
  }
  for (const b of $('chart-modes').querySelectorAll('.segbtn')) {
    b.addEventListener('click', () => { chartMode = b.dataset.mode; renderChart(); });
  }
  for (const b of $('gallery-views').querySelectorAll('.segbtn')) {
    b.addEventListener('click', () => setGalleryView(b.dataset.view));
  }
  $('gallery-wrap').addEventListener('click', onGalleryClick);
  // Shift ile aralik secerken tarayici aradaki METNI de seciyordu; yalnizca
  // Shift basiliyken engellenir ki Ayrinti'daki yol yine kopyalanabilsin.
  $('gallery-wrap').addEventListener('mousedown', (e) => { if (e.shiftKey) e.preventDefault(); });
  $('gallery-select').addEventListener('click', toggleGallerySelectAll);
  $('gallery-save').addEventListener('click', saveGallerySelection);
  $('chart-type-btn').addEventListener('click',
    (e) => toggleMenu(e, 'chart-type-menu', buildChartTypeMenu));
  $('chart-info').addEventListener('click',
    (e) => toggleMenu(e, 'chart-cards', buildChartCards));
  $('zoom-in').addEventListener('click', () => applyZoom(zoom * 1.25));
  $('zoom-out').addEventListener('click', () => applyZoom(zoom / 1.25));
  $('zoom-range').addEventListener('input', (e) => applyZoom(e.target.value / 100));
  $('zoom-fit').addEventListener('click', zoomFit);
  $('zoom-reset').addEventListener('click', () => applyZoom(1));
  // Dugme gibi gorunuyorsa dugme gibi davranmali: tek tik yeter, cift tik da
  // ayni sonucu verir (ikinci tik zararsiz).
  $('tbl-corner').addEventListener('click', () => resetWidths());
  initZoomGestures();
  initPanelResize();

  $('btn-save').addEventListener('click', (e) => toggleMenu(e, 'save-menu', buildSaveMenu));
  // Hucredeki onizlemeye tiklayinca YALNIZCA galeri acilir (onizleme kipi):
  // kullanici bir gorsele bakmak istedi, dosya uretmek degil.
  $('tbody').addEventListener('click', (e) => {
    if (e.target.tagName === 'IMG' && e.target.closest('td.cell-img')) {
      openPreview('gallery');
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    // Once ustteki katman kapanir: bilgi baloncugu, sonra ayarlar, sonra disa
    // aktarma paneli. Sira ekranda ust uste binme sirasidir.
    // Soru penceresi en ustte: baska bir pencerenin uzerine de acilabiliyor
    // ve yanitsiz kapanmamali — Escape `cancel` sayilir (10.5.2).
    if (!$('ask-overlay').hidden) return closeAsk();
    if (!$('cdock-pop').hidden) return toggleInfoPop(false);
    if (!$('rail-pop').hidden) { $('rail-pop').hidden = true; return; }
    if (!$('cell-menu').hidden) { $('cell-menu').hidden = true; return; }
    if (!$('about-overlay').hidden) return closeAbout();
    if (!$('settings-overlay').hidden) return closeSettings();
    if (!$('export-overlay').hidden) closeExport();
  });
  // Odak tuzagi AYNI onceligi okur; `cdock-pop` listede yok cunku o bir
  // baloncuk, modal degil — arkasindaki arayuz kullanilabilir kalmali.
  document.addEventListener('keydown',
    (e) => focusTrap(e, ['ask-overlay', 'about-overlay', 'settings-overlay', 'export-overlay']));
  $('ask-overlay').addEventListener('click', (e) => { if (e.target === $('ask-overlay')) closeAsk(); });

  // 10.5.2 — belge kisayollari. ⚠ Bir metin kutusunda yazarken geri alma
  // TARAYICININ isidir: kutunun kendi gecmisini calmamak icin hedef bir
  // giris ogesiyse karisilmaz. Ctrl+S her durumda kaydeder.
  document.addEventListener('keydown', (e) => {
    if (!e.ctrlKey || e.altKey || !sel) return;
    const key = e.key.toLowerCase();
    const typing = /^(input|textarea|select)$/i.test((e.target.tagName || ''));
    if (key === 's' && !e.shiftKey) { e.preventDefault(); saveDoc(); return; }
    // 9.29 — tablo araması. Gömülü tarayıcının kendi bul çubuğu açılmasın:
    // o, yalnızca ekrana çizilmiş satırlarda arar ve çıktıya yansımaz.
    if (key === 'f' && !e.shiftKey) { e.preventDefault(); $('filter').focus(); $('filter').select(); return; }
    if (typing) return;
    if (key === 'z' && !e.shiftKey) { e.preventDefault(); undoEdit(); }
    else if (key === 'y' || (key === 'z' && e.shiftKey)) { e.preventDefault(); redoEdit(); }
  });
  $('btn-cols').addEventListener('click', (e) => toggleMenu(e, 'col-menu', buildColMenu));
  // 9.29 — `render`, `renderBody` değil: transpozede sütun araması KAYITLARI
  // (sütunları) süzer, başlık da yeniden çizilmeli.
  $('filter').addEventListener('input', (e) => {
    filterText = fold(e.target.value.trim());
    if (cur) render();
    showSuggest();
  });
  $('filter').addEventListener('keydown', onFilterKey);
  initCellActions();
  $('filter').addEventListener('blur', () => { $('filter-suggest').hidden = true; });
  $('tree-filter').addEventListener('input', (e) => {
    treeFilter = e.target.value.trim().toLowerCase();
    renderTree();
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.menu-wrap')) {
      for (const id of MENUS) $(id).hidden = true;
    }
  });

  applyTree(await api.startup(), true);
}

/** Kabugun sunumunu kopruden alir (`Api.strings`): sozluk, dil ve tema.
 *
 * Sozlugun tek kaynagi Python'dur; burada yalnizca onbelleklenir. Cagri
 * basarisiz olursa `t()` anahtarin kendisini dondurur — arayuz cirkin gorunur
 * ama calismaya devam eder.
 *
 * Dil, tema ve yazi tipi BIRLIKTE gelir cunku ucu de ayni sey: Python'da
 * cozulmus bir tercih (`auto` → `tr`, `system` → `dark`) ve ucu de kok ogeye
 * yazilir.
 */
async function loadStrings() {
  const res = await api.strings();
  if (!res || !res.ok) return;
  strings = res.strings || {};
  langKeys = res.langs || [];
  themeKeys = res.themes || [];
  fontKeys = res.fonts || [];
  fontSizes = res.sizes || [];
  providerKeys = res.providers || [];
  densityKeys = res.densities || [];
  exportThemeKeys = res.exportThemes || [];
  applyStrings();

  // ⚠ `<html lang>` SABIT KALMAMALI. CSS `text-transform: uppercase` dile gore
  // davraniyor: `lang="tr"` altinda `i` → `İ` olur, ki Turkce icin dogrudur —
  // ama arayuz Ingilizceyken ayni kural "Identity"yi "İDENTİTY" yapar.
  document.documentElement.lang = res.lang;
  applyShell(res);
}

/** Cozulmus gorunum tercihlerini kok ogeye yazar; gerisini CSS dagitir.
 *
 * ⚠ Gelen tema `dark` ya da `light`tir, `system` DEGIL: cozum Python'da
 * yapiliyor (`theme.detect_theme`). CSS'te `prefers-color-scheme` kullanmak
 * ikinci bir karar noktasi acardi ve ekran ile PNG farkli temaya duserdi.
 *
 * Yazi tipi ailesi de anahtardir (`system`/`serif`/`mono`); CSS yigini
 * `style.css`teki `[data-font=…]` bloklarinda durur — tarayici TTF dosya adi
 * bilmez, Pillow da CSS yigini okuyamaz, iki taraf yalnizca ANAHTARI paylasir.
 */
function applyShell(res) {
  const root = document.documentElement;
  if (res.theme) root.dataset.theme = res.theme;
  if (res.font) root.dataset.font = res.font;
  if (res.fontSize) {
    // ⚠ Boyut bir PALET DEGERI degil, ayardan gelen bir sayi — CSS'te blok
    // tutmanin anlami yok, kok ogeye dogrudan yazilir. Sutun genisligi hesabi
    // da ayni sayiyi okuyor (`state.charW`), yani ekran ile PNG birlikte kayar.
    fontSize = res.fontSize;
    root.style.setProperty('--font-size', fontSize + 'px');
  }
  // ⚠ Puntodan tureyen olculer CSS'te YENIDEN HESAPLANMAZ, kopruden gelir.
  // `calc(var(--font-size) * …)` yazmak formulu iki calisma zamaninda iki kez
  // tutmak demekti; tek kaynak `theme.metrics()`. CSS bunlari `var()` ile
  // okur, denetimi `check.py --> METRIC_VARS` yapar.
  for (const [name, key] of Object.entries(METRIC_VARS)) {
    const v = (res.metrics || {})[key];
    if (v !== undefined) root.style.setProperty(name, v + 'px');
  }
  // 9.19.4 — Agent kapaliyken dugmesi CSS ile gizlenir (`[data-agent="off"]`),
  // acik serit de kapanir. ⚠ Bu yalnizca GORUNUM: asil sinir kopruda
  // (`agent_ask` soruyu reddeder).
  if (typeof res.agent === 'boolean') {
    agentOn = res.agent;
    root.dataset.agent = agentOn ? 'on' : 'off';
    if (!agentOn && dockOpen) setDock(false);
  }
}

/** Sozluk geldikten sonra statik kabugu boyar.
 *
 * Uc isaret var ve ucu de `index.html`'de duruyor:
 *   `data-i18n`       — ogenin METNI
 *   `data-i18n-rich`  — metin, `**kalin**` isaretleriyle (satir ici cizici)
 *   `data-i18n-attr`  — nitelik listesi, `nitelik:anahtar|nitelik:anahtar`
 *
 * HTML'de Turkce metin YER TUTUCU olarak durur: sozluk hic gelmezse arayuz
 * bos degil, Turkce gorunur. `t()` de anahtar bulamazsa anahtari dondurur.
 */
function applyStrings() {
  for (const el of document.querySelectorAll('[data-i18n]')) {
    el.textContent = t(el.dataset.i18n);
  }
  // Satir ici cizici: `renderMarkdown` blok `<p>` uretir ve bu metinler zaten
  // bir `<p>` icinde — `<p>` icine `<p>` gecersizdir.
  for (const el of document.querySelectorAll('[data-i18n-rich]')) {
    el.replaceChildren(...inlineNodes(t(el.dataset.i18nRich)));
  }
  for (const el of document.querySelectorAll('[data-i18n-attr]')) {
    for (const pair of el.dataset.i18nAttr.split('|')) {
      const [attr, key] = pair.split(':');
      if (attr && key) el.setAttribute(attr, t(key));
    }
  }
}

/* --- Arac cubugunun daralmasi -------------------------------------------- */

// Bunun altinda durum cubugu ("N satır · M sütun görünür") gizlenir: sayilar
// tabloda zaten gorunur, dar alanda ust uste binmekten baska ise yaramaz.
//
// ⚠ Eskiden bir de `COMPACT_W` vardi ve arama kutusunu buyutec DUGMESINE
// indiriyordu. Kutu artik bosta zaten ikon kadar (`style.css .search`), yani o
// esik gereksizlesti — iki ayri daralma mantigi tutmanin anlami kalmadi.
const NARROW_W = 470;

/** Alt bilgiyi ana alanın genişliğine uydurur. */
function initToolbarFit() {
  const fit = () => {
    const w = $('main').getBoundingClientRect().width;
    $('main').classList.toggle('narrow', w < NARROW_W);
  };

  new ResizeObserver(fit).observe($('main'));
  fit();
}

/* Imlec ailesinin "sol tus basili" durumu (Faz 8.1). CSS `:active` yalnizca
   BASILAN ogeyi etkiler; nokta ise fare nerede olursa olsun kaybolmali —
   surukleme sirasinda imlec baska ogelerin uzerinden gecer. Bu yuzden durum
   `body` sinifinda tutulur, dagitimi `style.css` yapar.

   Yalnizca SOL tus (`button === 0`) sayilir: sag tus cizim alaninda kaydirma
   demektir ve kendi imlecini korur. `pointercancel` de dinlenir, yoksa
   surukleme pencere disinda biterse sinif uzerinde kalir. */
function initPressCursor() {
  const off = () => document.body.classList.remove('pressing');
  document.addEventListener('pointerdown', (e) => {
    if (e.button === 0) document.body.classList.add('pressing');
  });
  document.addEventListener('pointerup', off);
  document.addEventListener('pointercancel', off);
  window.addEventListener('blur', off);
}
