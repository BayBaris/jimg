'use strict';

/* Disa aktarma paneli: sekmeler, metin ciktisi, galeri ve kaydet menusu.
 *
 * Panel HER ACILISTA `Belge Özeti / Anahat`a doner — bir kesif noktasidir,
 * kaldigi yerden devam eden bir arac degil. Hedefli acilislar (hucredeki
 * gorsele tiklamak) bunun disindadir.
 *
 * Her sekme TEK bir isi temsil eder; bir sekmeye ait denetim baska sekmede
 * gorunmez. Yeni cikti bicimi arac cubuguna degil ilgili SEKMEYE eklenir.
 */

let textKind = 'outline';    // panel her acilista buraya doner
let exportCat = 'text';

/** Ekranda gorunen satirlarin kaynak indeksleri, gosterim sirasiyla. */
function currentRowOrder() {
  return sortRows(filterRows()).map((x) => x.i);
}

/** Ekranda ACIK birakilan satirlarin kaynak indeksleri.
 *
 * ⚠ `expanded` zaten KAYNAK indeks tutuyor (`filterRows` her satiri kendi
 * indeksiyle esliyor), yani cevirim gerekmiyor — `row_order` ile ayni
 * uzlasim. Ikisi karisirsa siralanmis bir tabloda yanlis satir acilirdi.
 */
function currentExpanded() {
  return [...expanded].sort((a, b) => a - b);
}

/* Her sekme TEK bir isi temsil eder; grafik denetimleri yalnizca Grafik
 * sekmesinde durur, boylece "bu ayar neye ait" sorusu dogmaz. */
const CATS = ['text', 'table', 'tree', 'chart', 'gallery'];

/** Tablo sekmesinin alt sekmesi: aynı veri, iki taşıma biçimi.
 *
 * Varsayilan `image`: Tablo sekmesi acilinca kullanici once tablonun KENDISINI
 * gorur. Markdown bir tasima bicimidir, once gosterilecek sey degil. Sira
 * `index.html`'de de ayni — ilk dugme varsayilan olan olmali.
 */
let tableSub = 'image';          // 'image' | 'markdown'

/** Onizleme kipinde gosterilen TEK sekme; kaydet akisinda `null`. */
let panelOnly = null;

/** O an gösterilen içerik metin mi? (Belge Özeti ve Tablo→Markdown) */
const showsText = () => exportCat === 'text'
  || (exportCat === 'table' && tableSub === 'markdown');

/** O an gösterilen içerik çizim mi? */
const showsVector = () => exportCat === 'tree' || exportCat === 'chart'
  || (exportCat === 'table' && tableSub === 'image');

function switchCategory(cat) {
  if (!sel) return;
  exportCat = cat;

  for (const tab of $('export-tabs').querySelectorAll('.tab')) {
    tab.classList.toggle('on', tab.dataset.cat === cat);
    // Tablo ve grafik acik bir veri kumesi ister; agac ve galeri belge yeter.
    tab.disabled = (tab.dataset.cat === 'table' || tab.dataset.cat === 'chart') && !cur;
    // Onizlemede yalnizca hedef sekme durur. `.tab` kendi `display`ini
    // yazmadigi icin `hidden` tek basina yeter — `[hidden]` esligi gerekmiyor.
    tab.hidden = panelOnly !== null && tab.dataset.cat !== panelOnly;
  }
  // Tek sekme kalinca ayraclarin isi kalmiyor; sekme seridi zaten ortali
  // (`.tabs { justify-content: center }`), yani ikon kendiliginden ortada.
  for (const sep of $('export-tabs').querySelectorAll('.tab-sep')) {
    sep.hidden = panelOnly !== null;
  }
  for (const c of CATS) {
    const bar = $('cat-' + c);
    if (bar) bar.hidden = c !== cat;
  }

  const text = showsText(), vector = showsVector();

  $('text-out').hidden = !text;
  $('svg-wrap').hidden = !vector;
  $('gallery-wrap').hidden = cat !== 'gallery';
  if (cat !== 'gallery') stopGalleryWatch();   // 9.6.1 — sekmeden cikinca durur
  hideTip();

  // Gorsel panoya kopyalanamiyor (webview kisiti); dugme yalnizca metinde.
  $('text-copy').hidden = !text;
  // ⚠ Onizlemede kaydet menusu HIC yok: bu ekranlar bakip kapatmak icin.
  // Galeride bicim menusu yok; orada kendi iki dugmesi var (`9.6.4`) ve ikisi
  // de onizlemede gizli.
  $('btn-save').parentElement.hidden = panelOnly !== null || cat === 'gallery';
  const galleryActions = cat === 'gallery' && panelOnly === null;
  $('gallery-select').hidden = !galleryActions;
  $('gallery-save').hidden = !galleryActions;
  $('save-menu').hidden = true;
  $('zoombar').hidden = !vector;      // yalnizca cizim gosterilen sekmelerde

  if (cat === 'text') openExport(textKind);
  else if (cat === 'table') showTableSub(tableSub);
  else if (cat === 'gallery') showGallery();
  else if (cat === 'chart') renderChart();
  else renderVector(cat);
}

/** Tablo sekmesinin alt sekmesini açar. */
function showTableSub(sub) {
  tableSub = sub;
  for (const b of $('table-subs').querySelectorAll('.segbtn')) {
    b.classList.toggle('on', b.dataset.sub === sub);
  }
  $('note-table').textContent =
    t(sub === 'markdown' ? 'panel.table_markdown' : 'panel.table_image');

  const text = showsText(), vector = showsVector();
  $('text-out').hidden = !text;
  $('svg-wrap').hidden = !vector;
  $('text-copy').hidden = !text;
  $('zoombar').hidden = !vector;

  if (sub === 'markdown') openExport('table');
  else renderVector('table');
}

const MIN_PANEL_W = 520, MIN_PANEL_H = 320;
let resizing = false;

/** Panelin sağ alt köşesinden yeniden boyutlandırma; ölçü oturum boyunca korunur. */
function initPanelResize() {
  const grip = $('panel-grip');
  // ⚠ `id` ile: `.tpanel` sinifini Ayarlar/Modeller/Hakkinda da tasiyor ve DOM'da
  // once geliyorlar — sinifla secim gizli Ayarlar panelini buyutuyordu.
  const panel = $('export-panel');

  grip.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    e.stopPropagation();

    // Panel normalde kaplama tarafından ORTALANIR: genişlik büyüyünce iki kenar
    // birden açılır, tutamak farenin altından kaçar. Sürükleme boyunca sol-üst
    // köşeyi sabitleriz; böylece yalnızca sağ ve alt kenar hareket eder ve
    // tutamak imleci birebir takip eder.
    const r = panel.getBoundingClientRect();
    panel.style.position = 'absolute';
    panel.style.left = r.left + 'px';
    panel.style.top = r.top + 'px';
    panel.style.width = r.width + 'px';
    panel.style.height = r.height + 'px';

    resizing = true;

    const move = (ev) => {
      const maxW = window.innerWidth - r.left - 8;
      const maxH = window.innerHeight - r.top - 8;
      panel.style.width = Math.max(MIN_PANEL_W, Math.min(maxW, ev.clientX - r.left)) + 'px';
      panel.style.height = Math.max(MIN_PANEL_H, Math.min(maxH, ev.clientY - r.top)) + 'px';
    };

    const up = () => {
      try { grip.releasePointerCapture(e.pointerId); } catch { /* yakalanmamis olabilir */ }
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
      // `click` olayi `pointerup`tan SONRA gelir ve mousedown/mouseup ortak
      // atasina (kaplamaya) dusebilir; bayrak bir tur sonra indirilir ki
      // kaplamanin kapatma isleyicisi tetiklenmesin.
      setTimeout(() => { resizing = false; }, 0);
      if (!$('zoombar').hidden) zoomFit();
    };

    // Dinleyiciler DOCUMENT uzerinde: fare panelin disina ciktiginda da
    // olaylar gelmeye devam eder. Pointer capture yalnizca bir iyilestirme —
    // basarisiz olursa (bazi ortamlarda istisna firlatir) boyutlandirma yine
    // calisir ve `resizing` bayragi takili kalmaz.
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
    try { grip.setPointerCapture(e.pointerId); } catch { /* zorunlu degil */ }
  });
}

/** Kaydet akisi: butun sekmeler ve kaydet menusu acik. */
function openPanel(cat) {
  // Dogrudan bir sekmeye acilmadiysa panel HER ZAMAN Belge Ozeti / Anahat ile
  // baslar. `cat` bir Event olabilir: dugmeye dogrudan dinleyici olarak bagli.
  return showPanel(typeof cat === 'string' ? cat : 'text', null);
}

/** Onizleme akisi: TEK sekme, kaydet menusu yok.
 *
 * ⚠ Ayrim kullanicidan geldi: bu ekranlar bakip kapatmak icin — kitap
 * simgesi belge ozetini, hucredeki gorsele tiklamak galeriyi acar ve ikisi de
 * kaydet akisina hic girmez. Sekme SILINMEDI, kaydet panelinde duruyor:
 * belge raporunun MD/TXT cikisi ile `9.6`nin "Secilenleri kaydet" isi oradan
 * gelecek — hizli yol, tek yol degil.
 */
function openPreview(cat) {
  return showPanel(cat, cat);
}

function showPanel(target, only) {
  if (!sel) return setStatus(t('msg.pick_doc'), true);
  panelOnly = only;

  // Panel her acilista VARSAYILAN olcusune doner ve kaplama tarafindan yeniden
  // ortalanir. Onceki oturumdan kalan boyut tasinmaz: kucultulmus bir panel
  // bir daha acildiginda kucuk kalmasin. Alt sinir CSS'te (min-width/height)
  // ve surukleme sirasinda MIN_PANEL_* ile korunur.
  const panel = $('export-panel');
  panel.style.position = '';
  panel.style.left = '';
  panel.style.top = '';
  panel.style.width = '';
  panel.style.height = '';

  $('export-overlay').hidden = false;

  // Onceki oturumun sekmesi tasinmaz: panel bir kesif noktasidir, kaldigi
  // yerden devam eden bir arac degil.
  if (target === 'text') textKind = 'outline';
  switchCategory(target);
}

/* --- Metin ciktisi -------------------------------------------------------- */

const TEXT_NOTES = { report: 'panel.report', outline: 'panel.outline' };

async function openExport(kind) {
  if (!sel) return;
  const needsTable = kind === 'table' || kind === 'csv';
  if (needsTable && !cur) kind = 'report';

  // `table`/`csv` artik Tablo sekmesinin isi; Belge Ozeti secicisi yalnizca
  // rapor ve anahat tasir.
  if (!needsTable) {
    textKind = kind;
    for (const b of $('text-kinds').querySelectorAll('.segbtn')) {
      b.classList.toggle('on', b.dataset.kind === kind);
    }
    $('note-text').textContent = TEXT_NOTES[kind] ? t(TEXT_NOTES[kind]) : '';
  }

  setInfo(t('msg.generating'));
  $('text-out').value = '';

  const res = await api.export_text(
    kind, sel.docId,
    needsTable ? sel.dsId : null,
    needsTable ? sel.variantId : null,
    needsTable ? currentRowOrder() : null,
    needsTable ? currentExpanded() : null
  );

  if (!res.ok) {
    setInfo(res.error, 'error');
    return;
  }
  $('text-out').value = res.text;
  $('text-out').dataset.name = res.name;
  const lines = res.text ? res.text.split('\n').length : 0;
  setInfo(t('msg.text_info', {name: res.name, lines: fmtNum(lines),
                             chars: fmtNum(res.text.length)}));
}

function closeExport() {
  $('export-overlay').hidden = true;
}

function setInfo(text, cls) {
  const el = $('text-info');
  el.textContent = text;
  el.className = cls || '';
}

async function copyText() {
  const ta = $('text-out');
  if (!ta.value) return;
  try {
    await copyToClipboard(ta.value);
    setInfo(t('msg.copied'), 'ok');
  } catch (err) {
    setInfo(t('msg.copy_failed', {error: err}), 'error');
  }
}

/** Ekranda görünen metni diske yazar (Belge Özeti ve Tablo→Markdown). */
async function saveText() {
  const ta = $('text-out');
  if (!ta.value) return;
  const res = await api.save_text(ta.value, ta.dataset.name || 'cikti.txt');
  if (res.cancelled) return;
  if (!res.ok) return setInfo(res.error, 'error');
  setInfo(t('msg.saved', {path: res.path}), 'ok');
}

/** Son üretilen PNG'yi diske yazar (`Api._png`). */
async function saveImage(name) {
  const res = await api.save_image(name || 'gorsel.png');
  if (res.cancelled) return;
  if (!res.ok) return setInfo(res.error, 'error');
  setInfo(t('msg.saved', {path: res.path}), 'ok');
}

/* --- Gorseller sekmesi ---------------------------------------------------- */

/* Onizleme kartlar ekrana GIRDIKCE istenir (`9.6.1`). Liste cagrisi yalnizca
 * olcu ve kaynak tasir; 900 px'lik data URI'ler artik tek yanitta gelmiyor.
 *
 * ⚠ Gozlemci her galeri kurulusunda yenilenir. Eskisi kapatilmazsa DOM'dan
 * dusmus kartlar icin geri cagri uretmeye devam eder ve kapali bir belgenin
 * yollari koprunun onune gider. */
let galleryWatch = null;                 // IntersectionObserver | null
let thumbQueue = new Set();              // istenmeyi bekleyen json yollari
let thumbTimer = 0;

/* Gorunum kipi -> onizlemenin EKRANDAKI kenari (px). Uretim kutusu bunun IKI
 * KATI istenir: yuksek yogunluklu ekranda 1x uretilen onizleme bulanik duruyor
 * ve tavani `images.MAX_PREVIEW_PX` zaten tutuyor. Bu sayilar CSS'e ikinci kez
 * YAZILMAZ; `--gshot` degiskeni olarak asagida koke yaziliyor (`9.4.5.3`teki
 * `metrics` kalibi — iki calisma zamaninda iki formul tutmamak icin). */
const GALLERY_VIEWS = {detail: 45, list: 45, small: 84, medium: 124, large: 200};

/* Ayrinti ile Liste AYNI duzendir (yatay satir, kucuk onizleme); tek fark
 * Ayrinti'nin ucuncu satiri: gorselin nereden geldigi — dosya kaynaginda
 * COZULMUS tam yol, gomuluda etiketi. Izgara kipleri tek satirda ozetler. */
const GALLERY_ROW_VIEWS = new Set(['detail', 'list']);

/* `null` = tercih henuz okunmadi. Kip bir kez, galeri ILK acildiginda okunuyor;
 * `_shell()` sunumuna eklenmedi cunku kok ogeye yazilan bir tercih degil. */
let galleryView = null;

/* 9.6.5.2 — son kurulumun ogeleri ve gruplama karari: adresin olcusu ancak
 * onizlemeyle gelir, olcu satiri o an ayni kuralla yeniden yaziliyor. */
let galleryItems = new Map();
let galleryGrouped = false;

function galleryBox() {
  return GALLERY_VIEWS[galleryView] * 2;
}

function stopGalleryWatch() {
  if (galleryWatch) galleryWatch.disconnect();
  galleryWatch = null;
  clearTimeout(thumbTimer);
  thumbQueue = new Set();
}

/* Gorunur kartlar tek tek degil TOPLU istenir: hizli kaydirmada her kart bir
 * kopru cagrisi olurdu ve pywebview cagrilari siraya giriyor. */
function queueThumb(jsonPath) {
  thumbQueue.add(jsonPath);
  clearTimeout(thumbTimer);
  thumbTimer = setTimeout(flushThumbs, 60);
}

async function flushThumbs() {
  const docId = sel.docId;
  const paths = [...thumbQueue];
  thumbQueue = new Set();
  if (!paths.length) return;

  const res = await api.gallery_thumbs(docId, paths, galleryBox());
  // Yanit gelene kadar baska bir belgeye gecilmis olabilir; kartlar o belgenin
  // degil, bunlar yerlestirilirse yanlis gorsel gosterilir.
  if (!res.ok || docId !== sel.docId) return;

  const cardOf = (p) => $('gallery-wrap').querySelector(`.gcard[data-path="${CSS.escape(p)}"]`);
  for (const th of res.thumbs) {
    const card = cardOf(th.json_path);
    if (!card) continue;
    const shot = card.querySelector('.shot');
    const img = document.createElement('img');
    img.src = th.uri;
    img.alt = th.json_path;
    shot.replaceChildren(img);
    shot.classList.remove('loading');
    // 9.6.5.2 — adresin olcusu ve boyutu ancak indirilince bilinir; liste
    // bunlari sifir getirdi, olcu satiri simdi yerinde yaziliyor.
    const item = galleryItems.get(th.json_path);
    if (item && th.bytes !== undefined) {
      Object.assign(item, {width: th.source_width, height: th.source_height, bytes: th.bytes});
      card.querySelector('.meta span:not(.gsrc)').replaceWith(galleryInfoLine(item, galleryGrouped));
    }
  }
  // Istenip DONMEYEN kart: onizleme uretilemedi (adres yanit vermedi, gorsel
  // bozuk). "Yukleniyor" kutusunda birakmak, hic gelmeyecek bir seyi beklemek.
  const got = new Set(res.thumbs.map((th) => th.json_path));
  for (const p of paths) {
    const shot = got.has(p) ? null : cardOf(p)?.querySelector('.shot.loading');
    if (!shot) continue;
    shot.className = 'shot failed';
    shot.textContent = t('gallery.no_preview');
  }
}

/** Kartın ölçü satırı: `256×256 · 0.9 KB`, satır kiplerinde kaynak olmadan.
 *
 * ⚠ SVG'nin iç ölçüsü yok (`images._measure` sıfır döndürür); o zaman satır
 * yalnızca bayt taşır. İzgara kiplerinde kaynak aynı satırın sonunda durur —
 * orada kart dar ve üçüncü bir satır kartı iki katına çıkarırdı.
 */
function galleryInfoLine(it, grouped) {
  const parts = [];
  if (it.width && it.height) parts.push(`${it.width}×${it.height}`);
  // Bayt 0 ise yazilmaz: adres onizlemesi gelene kadar boyut BILINMIYOR
  // (`9.6.5.2`), "0.0 KB" yanlis bir bilgi olurdu.
  if (it.bytes) parts.push(`${(it.bytes / 1024).toFixed(1)} KB`);
  // Kaynak ekranda BIR KEZ yazilir. Grup basligi varsa onu zaten soyluyor;
  // satir kiplerinde Liste sade kaliyor, Ayrinti kendi satirinda gosteriyor.
  if (!grouped && !GALLERY_ROW_VIEWS.has(galleryView)) parts.push(it.origin);
  const info = document.createElement('span');
  info.textContent = parts.join(' · ');
  return info;
}

/** Görselleri kaynağına göre gruplar (`9.6.3`).
 *
 * ⚠ Anahtar `origin` METNİ DEĞİL, köprüden gelen `group`/`embedded` çiftidir:
 * `origin` gömülü görselde çevrilebilir bir etiket taşıyor ve dil değişince
 * aynı grup ikiye bölünürdü (`cell.embedded` tuzağının üçüncü tekrarı).
 *
 * ⚠ Burada SIRALANMAZ. Sıra köprüden gelir (`images.catalog`: gömülü → belge
 * klasörü → klasörler alfabetik) ve `Map` ekleme sırasını koruyor. Önce burada
 * `localeCompare` ile sıralanıyordu: gömülü grubun anahtarı `null` olunca
 * karşılaştırıcı üç grupta çöküyor, iki grupta da yanlış sıra veriyordu — ve
 * `check.py` JS'e ulaşamadığı için ikisi de görünmüyordu.
 */
function galleryGroups(items) {
  const byKey = new Map();
  for (const it of items) {
    // Kaynak türü anahtarın PARÇASI (`9.6.5.2`): `assets` adlı bir klasör ile
    // `assets` adlı bir ana makine aynı gruba düşmemeli.
    const key = it.embedded ? null : `${it.source}:${it.group || ''}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(it);
  }
  return [...byKey.entries()]
    .map(([key, list]) => ({key, items: list, label: galleryGroupLabel(list[0])}));
}

function galleryGroupLabel(it) {
  if (it.embedded) return t('gallery.embedded');
  return it.group || t('gallery.same_folder');
}

/** Tek görselin kartı. Başlık kaynaktan türer, JSON yolu ipucunda kalır. */
function galleryCard(it, grouped) {
  const card = document.createElement('div');
  card.className = 'gcard';
  card.dataset.path = it.json_path;

  const shot = document.createElement('div');
  shot.className = 'shot loading';
  if (it.oversize) {
    // Onizleme uretilmeyecek: istemek de gozlemek de bosuna.
    shot.className = 'shot toobig';
    shot.textContent = t('gallery.too_large');
  }

  const meta = document.createElement('div');
  meta.className = 'meta';
  const name = document.createElement('b');
  // Dosya kaynaginda DOSYA ADI, gomuluda JSON yolu — gomulunun baska adi yok.
  name.textContent = it.name || it.json_path;
  meta.append(name, galleryInfoLine(it, grouped));
  // Kaynak YALNIZCA Ayrinti'da ve kendi satirinda: Liste sade kalsin diye
  // (gorsel, ad, olcu), izgara kiplerinde de zaten olcu satirinin sonunda.
  if (galleryView === 'detail') {
    const src = document.createElement('span');
    src.className = 'gsrc';
    src.textContent = it.full || it.origin;
    meta.append(src);
  }

  card.append(shot, meta);
  // ⚠ Ipucu JSON yolu: baslik dosya adina donunce gorselin BELGEDEKI yeri
  // ekrandan tamamen kaybolurdu ve aranan sey cogu zaman odur.
  card.title = it.json_path;
  return card;
}

/** Seçili kipi ekrana yazar: ölçü değişkeni, düzen özniteliği, seçili düğme. */
function applyGalleryView() {
  const wrap = $('gallery-wrap');
  wrap.dataset.view = galleryView;
  wrap.style.setProperty('--gshot', GALLERY_VIEWS[galleryView] + 'px');
  for (const b of $('gallery-views').querySelectorAll('.segbtn')) {
    b.classList.toggle('on', b.dataset.view === galleryView);
  }
}

/** Kip değiştirir: tercih diske yazılır, galeri yeni kutuda yeniden kurulur.
 *
 * ⚠ Kartlar yeniden kuruluyor çünkü önizlemeler ESKİ kutuda üretilmişti.
 * Elde olanı büyütmek bedava görünür ama Liste kipinden Büyük kipe geçen
 * kullanıcıya 80 px'lik bir görseli 400 px'e esnetilmiş hâlde gösterirdi.
 */
function setGalleryView(view) {
  if (view === galleryView) return;
  galleryView = view;
  applySetting({images: {view}});
  showGallery();
}

/* --- Secim ve kaydetme (9.6.4) ---------------------------------------------
 *
 * Secim JSON yolu KUMESIDIR ve ekranda yasar. Ayni belgede kip degisince kartlar
 * yeniden kuruluyor ama secim korunuyor; belge degisince sifirlaniyor — baska
 * bir belgenin yolu bu belgede baska bir gorseli gosterebilirdi.
 *
 * Tiklama dosya gezgini uzlasimini izler: tik tek secer, Ctrl ekler/cikarir,
 * Shift EKRANDAKI sirayla aralik secer, bos alana tik secimi kaldirir. */
let gallerySel = new Set();
let gallerySelDoc = null;
let galleryAnchor = null;              // Shift araligi buradan baslar

function galleryCards() {
  return [...$('gallery-wrap').querySelectorAll('.gcard')];
}

/** Seçimi kartlara ve iki düğmeye yazar; etiketler seçim sayısını taşır. */
function paintGallerySelection() {
  const cards = galleryCards();
  for (const c of cards) {
    // Onizlemede secim GOSTERILMEZ: kaydet panelinde yapilan secim ayni
    // belgenin onizlemesinde vurgulu kalirdi ve orada hicbir eylemi yok.
    c.classList.toggle('selected', panelOnly === null && gallerySel.has(c.dataset.path));
  }
  const n = gallerySel.size;
  const all = n > 0 && n === cards.length;
  $('gallery-select').textContent = t(all ? 'ui.gallery_select_none' : 'ui.gallery_select_all');
  $('gallery-select').disabled = cards.length === 0;
  $('gallery-save').textContent = t('ui.gallery_save', {n});
  $('gallery-save').disabled = n === 0;
}

function onGalleryClick(e) {
  if (panelOnly !== null) return;      // onizlemede secim yok, kaydetme de yok (`9.13`)
  const card = e.target.closest('.gcard');
  if (!card) {
    gallerySel = new Set();
    galleryAnchor = null;
    return paintGallerySelection();
  }
  const path = card.dataset.path;
  const order = galleryCards().map((c) => c.dataset.path);
  const multi = e.ctrlKey || e.metaKey;
  if (e.shiftKey && order.includes(galleryAnchor)) {
    const [from, to] = [order.indexOf(galleryAnchor), order.indexOf(path)]
      .sort((a, b) => a - b);
    if (!multi) gallerySel = new Set();
    for (const p of order.slice(from, to + 1)) gallerySel.add(p);
  } else if (multi) {
    if (gallerySel.has(path)) gallerySel.delete(path);
    else gallerySel.add(path);
    galleryAnchor = path;
  } else {
    gallerySel = new Set([path]);
    galleryAnchor = path;
  }
  paintGallerySelection();
}

function toggleGallerySelectAll() {
  const order = galleryCards().map((c) => c.dataset.path);
  const all = order.length > 0 && gallerySel.size === order.length;
  gallerySel = all ? new Set() : new Set(order);
  galleryAnchor = null;
  paintGallerySelection();
}

/** Seçilenleri kaydeder. Sıra EKRANDAKİ sıradır: çakışan adlardan hangisinin
 * `-2` alacağını o belirliyor (`Api._pick_images`). */
async function saveGallerySelection() {
  const paths = galleryCards().map((c) => c.dataset.path).filter((p) => gallerySel.has(p));
  if (!paths.length) return;
  const res = await api.save_images(sel.docId, paths);
  if (res.cancelled) return;
  if (!res.ok) return setInfo(res.error, 'error');
  let text = res.path ? t('msg.saved', {path: res.path})
    : t('msg.images_saved', {n: res.count, folder: res.folder});
  if (res.skipped) text += ' · ' + t('msg.images_skipped', {n: res.skipped});
  setInfo(text, res.skipped ? 'error' : 'ok');
}

/** Galerinin üstündeki bilgi çubuğu; `action` varsa düğmesiyle.
 *
 * Mutlak yol (`9.6.5.1`) düğmeyle gelir — izin belgeye aittir ve orada
 * verilir. Adres (`9.6.5.2`) düğmesiz gelir — izin kullanıcıya aittir ve
 * ayarlardan verilir (`K-10`); çubuk yalnızca yerini söyler. */
function galleryNotice(text, action) {
  const bar = document.createElement('div');
  bar.className = 'gnotice';
  const span = document.createElement('span');
  span.textContent = text;
  bar.append(span);
  if (action) {
    const btn = document.createElement('button');
    btn.className = 'btn';
    btn.textContent = action.label;
    btn.addEventListener('click', action.run);
    bar.append(btn);
  }
  return bar;
}

/** İzin verir; galeri ve AÇIK tablo yeni izinle yeniden kurulur.
 *
 * ⚠ Tablo `select()` ile değil YERİNDE yenilenir: `select` filtreyi ve açık
 * satırları sıfırlıyor. İzin görünümü değiştirmemeli — hücrelere yalnızca
 * önizleme ekler, satır sırası ve indeksleri aynı kalır. */
async function allowAbsoluteImages(docId) {
  const res = await api.gallery_allow_absolute(docId);
  if (!res.ok) return setInfo(res.error, 'error');
  if (cur && sel && sel.docId === docId && sel.dsId) {
    const tbl = await api.table(sel.docId, sel.dsId, sel.variantId);
    if (tbl.ok) {
      cur.table = tbl.table;
      render();
    }
  }
  if (sel && sel.docId === docId) showGallery();
}

async function showGallery() {
  const box = $('gallery-wrap');
  stopGalleryWatch();
  box.replaceChildren();
  if (gallerySelDoc !== sel.docId) {
    gallerySel = new Set();
    galleryAnchor = null;
    gallerySelDoc = sel.docId;
  }
  paintGallerySelection();
  setInfo(t('msg.scanning_images'));

  if (galleryView === null) {
    const s = await api.settings_get();
    const stored = s.ok && s.settings.images && s.settings.images.view;
    // Bilinmeyen bir deger ayar dosyasina elle yazilmis olabilir; kip listesi
    // burada TEK kaynak, `Orta` da varsayilan (`settings.DEFAULTS`).
    galleryView = GALLERY_VIEWS[stored] ? stored : 'medium';
  }
  applyGalleryView();

  const res = await api.gallery(sel.docId);
  if (!res.ok) return setInfo(res.error, 'error');
  // 9.6.5.1 — izin bekleyen mutlak yollar: cubuk gorsellerin USTUNDE, bos
  // galeride de (belgenin tek gorseli mutlak yolla olabilir).
  if (res.absolute_refs) {
    box.append(galleryNotice(t('gallery.absolute_blocked', {n: res.absolute_refs}),
      {label: t('ui.gallery_allow_absolute'), run: () => allowAbsoluteImages(sel.docId)}));
  }
  if (res.url_refs) box.append(galleryNotice(t('gallery.url_blocked', {n: res.url_refs})));

  if (!res.items.length) {
    const p = document.createElement('div');
    p.className = 'gempty';
    p.textContent = t('msg.gallery_empty');
    box.append(p);
    gallerySel = new Set();
    paintGallerySelection();
    return setInfo(t('msg.gallery_none', {doc: res.doc}));
  }

  galleryWatch = new IntersectionObserver((entries, obs) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      obs.unobserve(e.target);           // bir kartin onizlemesi bir kez istenir
      queueThumb(e.target.dataset.path);
    }
  }, {root: box, rootMargin: '200px'});  // ekrana girmeden once hazirlanir

  const groups = galleryGroups(res.items);
  const grouped = groups.length > 1;
  galleryItems = new Map(res.items.map((it) => [it.json_path, it]));
  galleryGrouped = grouped;
  for (const g of groups) {
    // ⚠ Tek gruplu belgede baslik YAZILMAZ: "gömülü base64" diye tek bir
    // baslik altinda duran sekiz gorsel hicbir sey ayirmiyor, yalnizca yer
    // kapliyor. Baslik bir AYRIM oldugunda anlamli.
    if (grouped) {
      const head = document.createElement('div');
      head.className = 'ghead';
      head.textContent = g.label;
      box.append(head);
    }
    for (const it of g.items) {
      const card = galleryCard(it, grouped);
      // Gozlem EKLEDIKTEN SONRA baslar: kart kurmak ile gozlemek ayri isler,
      // ikincisi ogenin DOM'da olmasini varsayar.
      box.append(card);
      if (!it.oversize) galleryWatch.observe(card);
    }
  }
  // Ayni belgede kartlar yeniden kuruldu: secim korunur, ama ekranda artik
  // olmayan yol secimde KALMAZ — kaydedilecek sey gorunen seydir.
  const shown = new Set(res.items.map((it) => it.json_path));
  gallerySel = new Set([...gallerySel].filter((p) => shown.has(p)));
  paintGallerySelection();
  setInfo(t('msg.gallery_info',
           {doc: res.doc, n: res.items.length, dir: res.base_dir}));
}

/* --- Kaydet menusu -------------------------------------------------------- */

/* Her sekmenin uretebildigi bicimler. Tek dugme, bicim listesi. Olcut basit:
 * PDF yalnizca METIN tasiyan ciktilarda (grafikte eksen etiketinden ibaret,
 * gerekmiyor), PNG yalnizca gorsellestirilmis ciktilarda. SVG raftan kaldirildi
 * (`K-19`) — ureticisi duruyor, ekran cizimi ve HTML onu kullaniyor. */
const SAVE_FORMATS = {
  text: [['MD/TXT', 'fmt.text', () => saveText()]],
  'table:markdown': [['MD', 'fmt.md', () => saveText()],
                     ['CSV', 'fmt.csv', () => saveTableAs('csv')]],
  'table:image': [['PNG', 'fmt.png', () => savePng()],
                  ['PDF', 'fmt.pdf', () => saveVector('pdf')],
                  ['HTML', 'fmt.html', () => saveTableAs('html')]],
  tree: [['PNG', 'fmt.png', () => savePng()],
         ['PDF', 'fmt.pdf', () => saveVector('pdf')],
         ['drawio', 'fmt.drawio', () => saveDrawio()]],
  chart: [['PNG', 'fmt.png', () => savePng()]],
};

/** Kaydet menüsünün anahtarı: Tablo sekmesi alt sekmesine göre ayrışır. */
const saveKey = () => exportCat === 'table' ? 'table:' + tableSub : exportCat;

/** Açık tabloyu ekranda gösterilmeyen bir metin biçiminde kaydeder (CSV, HTML). */
async function saveTableAs(kind) {
  const res = await api.export_text(kind, sel.docId, sel.dsId, sel.variantId,
                                    currentRowOrder(), currentExpanded());
  if (!res.ok) return setInfo(res.error, 'error');
  const out = await api.save_text(res.text, res.name);
  if (out.cancelled) return;
  if (!out.ok) return setInfo(out.error, 'error');
  setInfo(t('msg.saved_chars',
           {path: out.path, chars: fmtNum(res.text.length)}), 'ok');
}

function buildSaveMenu() {
  const m = $('save-menu');
  m.className = 'menu save-menu';
  m.replaceChildren();
  for (const [ext, desc, run] of SAVE_FORMATS[saveKey()] || []) {
    // Uzanti sutunu DAR: `wide` yok, bicim adlari sabit genislikte dizilsin.
    menuItem(m, { label: ext, labelClass: 'ext', side: t(desc), run });
  }
}

async function savePng() {
  const needsTable = exportCat !== 'tree';
  const res = await api.export_image(
    exportCat, sel.docId,
    needsTable ? sel.dsId : null,
    needsTable ? sel.variantId : null,
    needsTable ? currentRowOrder() : null,
    // Acik satirlar cizim SECENEKLERINDEN gecer (`scale` ile ayni yol).
    exportCat === 'chart' ? chartOptions()
                          : { expanded: needsTable ? currentExpanded() : null });
  if (!res.ok) return setInfo(res.error, 'error');
  return saveImage(res.name);
}

async function saveDrawio() {
  const res = await api.save_drawio($('svg-wrap').dataset.name || 'agac');
  if (res.cancelled) return;
  if (!res.ok) return setInfo(res.error, 'error');
  setInfo(t('msg.saved_drawio',
           {path: res.path, nodes: res.nodes, edges: res.edges}), 'ok');
}

async function saveVector(fmt) {
  const name = $('svg-wrap').dataset.name || 'grafik';
  const res = await api.save_vector(fmt, name);
  if (res.cancelled) return;
  if (!res.ok) return setInfo(res.error, 'error');
  setInfo(t('msg.saved_bytes',
           {path: res.path, kb: (res.bytes / 1024).toFixed(1)}), 'ok');
}
