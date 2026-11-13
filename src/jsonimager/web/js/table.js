'use strict';

/* Tablonun kendisi: secim, uyari kutulari, cizim, filtre ve siralama.
 *
 * Sutunun GENISLIGI, SIRASI ve gizliligi burada degil `columns.js`'tedir —
 * bu dosya "ne cizilir"i, o dosya "nasil olculur"u bilir.
 *
 * Filtre/siralama mantigi Python'da TEKRARLANMAZ: disa aktarim ekranda gorunen
 * satirlarin kaynak indekslerini (`currentRowOrder`) oldugu gibi kullanir,
 * boylece cikti ekranla birebir olur.
 */

async function select(docId, dsId, variantId) {
  const res = await api.table(docId, dsId, variantId);
  if (!res.ok) return setStatus(res.error, true);

  sel = { docId, dsId, variantId };
  cur = { table: res.table, view: res.view, doc: res.doc };
  expanded = new Set();
  filterText = '';
  $('filter').value = '';

  renderTree();
  setTitle(res.table);
  setDsMeta(res);

  renderNotes();
  render();

  // Sohbet belge basinadir: baska bir belgeye gecilince serit o belgenin
  // dizisini gosterir. Ayni belgenin veri kumeleri arasinda gezinmek sohbeti
  // degistirmez, bu yuzden yalnizca belge degisince yeniden yuklenir.
  if (dockOpen && dockDocId !== docId) loadChat();
}

/* --- Uyari kutulari -------------------------------------------------------
 * Uc kutu, uc ayri anlam ve renk: yesil sema varyanti BULGUSU, mavi seyreklik
 * yuzunden gizlenenler, sari uzun metin ve tablonun kendi notlari.
 */

// Uyari satirlari tabloyu surekli asagi itmesin: bir kez okunur, sonra cekilir.
// Bilgi kaybolmaz — gizlenen sutunlar filtre menusunde isaretsiz durur.
const NOTES_MS = 5000;
let notesTimer = null;

function noteBox(kind, text) {
  const d = document.createElement('div');
  d.className = 'note' + (kind ? ' ' + kind : '');
  d.textContent = text;
  return d;
}

/** Anahtar listesini okunur sütun adlarına çevirir. */
function namesOf(keys) {
  return (keys || []).map((k) => (colByKey(k) || {}).label).filter(Boolean);
}

/** Açık tablonun şema varyantları — ağaçtaki veri kümesi kaydından. */
function currentVariants() {
  if (!sel || sel.variantId) return [];      // varyantın kendisi açıksa tekrar duyurma
  const doc = tree.docs.find((d) => d.id === sel.docId);
  const ds = doc && doc.datasets.find((x) => x.id === sel.dsId);
  return (ds && ds.variants) || [];
}

/** Uyarıları hemen çeker — kullanıcı görünümü kendi değiştirdiğinde. */
function hideNotes() {
  clearTimeout(notesTimer);
  $('notes').classList.add('gone');
}

/** Uyarı satırları + otomatik gizlenen sütun bildirimi. 5 saniye sonra çekilir.
 *
 * YALNIZCA yeni bir tablo acilirken cagrilir (`select`, `onReset`). Sutun
 * gizleyip gostermek uyariyi yeniden dogurmaz: kullanici zaten ne yaptigini
 * biliyor ve sari kutu her tikta bes saniye daha ekrani asagi itiyordu.
 */
function renderNotes() {
  const notes = $('notes');
  clearTimeout(notesTimer);
  notes.classList.remove('gone');
  notes.replaceChildren();
  if (!cur) return;

  // Sema varyanti bir UYARI degil, bir bulgudur: yesil kutu.
  const vars = currentVariants();
  if (vars.length) {
    notes.append(noteBox('variant', t('note.variants',
      {n: vars.length, list: vars.map((v) => v.label).join(', ')})));
  }

  const auto = namesOf(cur.view.autoHidden);
  if (auto.length) {
    notes.append(noteBox('auto-hide', t('note.auto_hidden',
      {n: auto.length, list: auto.join(', ')})));
  }

  const long = namesOf(cur.view.longHidden);
  if (long.length) {
    notes.append(noteBox('', t('note.long_hidden',
      {n: long.length, lines: TEXT_MAX_LINES, list: long.join(', ')})));
  }

  for (const n of cur.table.notes || []) notes.append(noteBox('', n));

  if (notes.children.length) {
    notesTimer = setTimeout(() => notes.classList.add('gone'), NOTES_MS);
  }
}

function clearTable() {
  sel = null; cur = null;
  $('tbl-corner').hidden = true;
  // Belge kapatildi: sohbetin dayandigi belge de yok, serit kapanir.
  if (dockOpen) setDock(false);
  setTitle(null);
  $('ds-meta').textContent = '';
  $('notes').replaceChildren();
  $('thead').replaceChildren();
  $('tbody').replaceChildren();
  $('cols').replaceChildren();
  $('placeholder').hidden = false;
  setStatus('');
}

async function onTranspose() {
  if (!sel) return;
  const res = await api.set_transpose(sel.docId, sel.dsId, sel.variantId, !cur.table.transposed);
  if (!res.ok) return setStatus(res.error, true);
  cur = { table: res.table, view: res.view, doc: res.doc };
  expanded = new Set();
  setDsMeta(res);
  render();
}

/** Başlık altındaki bilgi satırı: belge, tür, veri kümesi kimliği.
 *
 * Satir/sutun sayisi BURADA YAZMAZ — durum cubugunda zaten duruyor ve iki
 * yerde birden gorununce ayni bilgi tekrarlaniyordu.
 */
function setDsMeta(res) {
  const tbl = res.table;
  $('ds-meta').textContent = `${res.doc} · ${tbl.kind_label} · ${tbl.id}`
    + (tbl.variant ? ' → ' + tbl.variant : '');
}

/* --- Gruplar -------------------------------------------------------------- */

/** Gruba göre dizilim açık mı? Transpoze modda satırlar, normalde sütunlar. */
const groupSorted = () =>
  cur.table.transposed ? !!cur.view.rowGroupSort : !!cur.view.groupSort;

/** Gruba göre dizilimi açar/kapatır. Kapatınca belgedeki sıraya dönülür. */
function onGroupSort(on) {
  if (!cur) return;

  // Transpoze modda gruplanacak olan sutunlar degil, alan SATIRLARIDIR.
  if (cur.table.transposed) {
    cur.view.rowGroupSort = on;
    saveView();
    return render();
  }

  cur.view.groupSort = on;
  cur.view.order = on ? sortedByGroup() : cur.table.columns.map((c) => c.key);
  saveView();
  render();
}

function sortedByGroup() {
  const byKey = Object.fromEntries(cur.table.columns.map((c) => [c.key, c]));
  return cur.view.order.slice().sort((a, b) => {
    const ga = ORDER_GROUPS.indexOf((byKey[a] || {}).group);
    const gb = ORDER_GROUPS.indexOf((byKey[b] || {}).group);
    return (ga < 0 ? 99 : ga) - (gb < 0 ? 99 : gb);
  });
}

/** Yalnızca grup ayarlarını varsayılana döndürür; sütun gizliliğine dokunmaz. */
function onResetGroups() {
  if (!cur) return;
  cur.view.groups = false;      // varsayilan kapali (api_table._default_view)
  cur.view.rowGroupSort = false;
  cur.view.groupSort = false;
  cur.view.order = cur.table.columns.map((c) => c.key);
  saveView();
  render();
}

/* --- Cizim ---------------------------------------------------------------- */

function render() {
  $('placeholder').hidden = true;
  syncSearch();
  // Etkin durum gostergeleri: transpoze turuncu, uygulanmis filtre mavi dolar.
  $('btn-transpose').classList.toggle('on', !!cur.table.transposed);
  $('btn-cols').classList.toggle('on', filtersActive());
  renderHead();
  renderBody();
}

function renderHead() {
  const cg = $('cols'), th = $('thead');
  cg.replaceChildren();
  th.replaceChildren();

  const cols = visibleCols();
  const expander = hasExpandable();

  let total = 0;
  if (expander) {
    const c = document.createElement('col');
    c.style.width = '28px';
    cg.append(c);
    total += 28;
  }
  for (const col of cols) {
    const c = document.createElement('col');
    const w = widthOf(col);
    c.style.width = w + 'px';
    cg.append(c);
    total += w;
  }

  // Tabloya PIKSEL genislik verilmezse tarayici onu kapsayiciya sikistirir ve
  // colgroup'taki olculer tutmaz (320 px isteyen sutun 161 px'e iner). Tek
  // satirlik hucrelerde bu yalnizca erken kirpma demekti; metin sarilan
  // sutunlarda satir yuksekligi katlaniyor. Genislik burada verilince ekran,
  // ayni olculerle cizilen PNG ciktisiyla da ortusur.
  $('tbl').style.width = total + 'px';

  if (showGroups()) th.append(groupRow(cols, expander));

  const tr = document.createElement('tr');
  if (expander) {
    const h = document.createElement('th');
    h.className = 'expander-h';
    tr.append(h);
  }
  for (const col of cols) tr.append(buildTh(col));
  th.append(tr);

  // Kose dugmesi baslik yuksekligine oturur; grup satiri acikken baslik iki
  // satir olur ve dugme de o kadar uzar.
  const corner = $('tbl-corner');
  corner.hidden = false;
  corner.style.height = th.getBoundingClientRect().height + 'px';
}

function groupRow(cols, expander) {
  const tr = document.createElement('tr');
  tr.className = 'group-row';
  if (expander) {
    const h = document.createElement('th');
    h.className = 'expander-h';
    tr.append(h);
  }
  // Sutunlar surüklenebildigi icin gruplar bitisik olmayabilir; ardisik
  // aynı gruptaki sutunlar tek baslik altinda birlestirilir.
  let i = 0;
  while (i < cols.length) {
    const g = cols[i].group || G_OTHER;
    let j = i;
    while (j < cols.length && (cols[j].group || G_OTHER) === g) j++;
    // `g` ANAHTAR (`cat`), gorunen metin dilden gelir (Faz 9.2).
    const label = t('group.' + g);
    const th = document.createElement('th');
    th.colSpan = j - i;
    th.className = 'gcell g-' + ORDER_GROUPS.indexOf(g);
    th.textContent = label;
    th.title = t('ui.group_title', {name: label, n: j - i});
    tr.append(th);
    i = j;
  }
  return tr;
}

function buildTh(col) {
  const th = document.createElement('th');
  th.dataset.key = col.key;

  const inner = document.createElement('div');
  inner.className = 'th-inner';

  const label = document.createElement('span');
  label.className = 'th-label';
  label.textContent = col.label;
  inner.append(label);

  if (col.sparse) {
    const s = document.createElement('span');
    s.className = 'th-sparse';
    s.textContent = '◦';
    s.title = t('ui.sparse_hint', {present: col.present, total: col.total});
    inner.append(s);
  }

  const badge = document.createElement('span');
  badge.className = 'th-badge';
  badge.textContent = badgeText(col);
  inner.append(badge);

  const s = cur.view.sort;
  if (s && s.key === col.key) {
    const arrow = document.createElement('span');
    arrow.className = 'th-sort';
    arrow.textContent = s.dir > 0 ? '▲' : '▼';
    inner.append(arrow);
  }

  // Ayni oge hem SURUKLENIR hem TIKLANIR: surukleme esigi asilmadiysa tik
  // siralama sayilir, asildiysa yutulur (bkz. `dragJustEnded`).
  inner.addEventListener('mousedown', (e) => startColDrag(e, th));
  inner.addEventListener('click', () => {
    if (dragJustEnded) return;
    headerClick(col.key);
  });
  // 10.7.2 — duzenleme kipinde cift tik / F2 sutunun ADINI duzenler (tum
  // satirlarda). Kip kapaliyken dinleyiciler islemsiz (`headerRename` sinar).
  inner.addEventListener('dblclick', () => headerRename(label, col));
  if (editOn && !cur.table.transposed) {
    th.tabIndex = 0;
    th.addEventListener('keydown', (e) => {
      if (e.key === 'F2') { e.preventDefault(); headerRename(label, col); }
    });
  }
  if ((cur.table.cols_edited || []).includes(col.key)) {
    th.classList.add('edited');
    th.title = t('ui.unsaved');
  }
  th.append(inner);

  const rz = document.createElement('div');
  rz.className = 'resizer';
  rz.addEventListener('mousedown', (e) => startResize(e, th, col));
  // Tutamaga cift tik: YALNIZCA bu sutun icerige gore yeniden olculur.
  rz.addEventListener('dblclick', (e) => {
    e.stopPropagation();
    resetWidths([col.key]);
  });
  th.append(rz);
  return th;
}

function renderBody() {
  const tb = $('tbody');
  tb.replaceChildren();
  remoteCells = [];           // `buildTd` doldurur, sonda `loadRemoteThumbs` ister

  const cols = visibleCols();
  const idxs = cols.map((c) => cur.table.columns.indexOf(c));
  const expander = hasExpandable();
  const rows = sortRows(filterRows());
  const transposed = !!cur.table.transposed;

  let lastGroup = null;
  for (const { row, i } of rows) {
    // Transpoze modda her satir bir ALAN oldugu icin grup ayraci satir olur.
    if (transposed && cur.view.groups) {
      const g = row[0] && row[0].g;
      if (g && g !== lastGroup) {
        lastGroup = g;
        tb.append(groupSeparator(t('group.' + g), cols.length + (expander ? 1 : 0)));
      }
    }

    const tr = document.createElement('tr');
    tr.className = 'row';

    if (expander) {
      const td = document.createElement('td');
      td.className = 'expander';
      if (row.some((c) => c && c.sub)) {
        td.textContent = expanded.has(i) ? '▾' : '▸';
        td.addEventListener('click', () => {
          expanded.has(i) ? expanded.delete(i) : expanded.add(i);
          renderBody();
        });
      }
      tr.append(td);
    }

    for (let k = 0; k < cols.length; k++) {
      // Hucrenin adresi konumundan gelir (`cellSource`, js/edit.js); gizli
      // sutunlar yuzunden ekrandaki sira ile tablodaki sira ayri, bu yuzden
      // `idxs[k]` (tablodaki sutun) kullanilir.
      const td = buildTd(row[idxs[k]], cols[k], k === 0 && transposed,
                         cellSource(i, idxs[k]), hitNeedle(idxs[k], i));
      // 11.2 — kopyalama ve "bu değere göre süz" hücrenin KENDİSİNİ okur
      // (ekranda kırpılmış metni değil): tablodaki sütun ve kaynak satır.
      td.__cell = row[idxs[k]];
      td.__k = idxs[k];
      td.__i = i;
      tr.append(td);
    }
    tb.append(tr);

    if (expanded.has(i)) tb.append(buildDetailRow(row, cols, expander));
  }

  const total = cur.table.rows.length;
  const hidden = cur.view.hidden.length;
  const unit = t(transposed ? 'ui.unit_field' : 'ui.unit_row');
  const colUnit = t(transposed ? 'ui.unit_record' : 'ui.unit_column');
  // Transpoze modda ilk sutun alan adlarini tasir, kayit sayilmaz.
  const colCount = transposed ? cols.filter((c) => c.key !== '_field').length : cols.length;
  // 9.29 — transpozede arama KAYITLARI süzer: sayı "eşleşen / toplam" olur.
  // Payda aramasız görünen kayıtlar: kullanıcının gizledikleri "(n gizli)" ile
  // ayrıca sayılıyor, ikisi karışırsa toplam aramaya göre oynardı.
  const searched = (cur.view.searchHidden || []).length;
  const unsearched = cur.view.order.filter((k) => k !== '_field' && !cur.view.hidden.includes(k)).length;
  const shownCols = searched ? colCount + ' / ' + unsearched : colCount;
  setStatus(
    t('ui.status', {
      shown: rows.length === total ? total : rows.length + ' / ' + total,
      unit, cols: shownCols, colUnit,
    })
    + (hidden ? t('ui.status_hidden', {n: hidden}) : '')
    + (transposed ? t('ui.status_transposed') : '')
    // 9.6.5.1 — izin galeride verilir; satir yalnizca nerede oldugunu soyler.
    + (cur.table.images_blocked
      ? t('ui.status_absolute', {n: cur.table.images_blocked}) : '')
    // 9.29 — "0 satır"ın nedeni; sonda, sayılardan sonra okunur.
    + (search && search.missing ? t('ui.search_no_col', {name: search.q.col}) : '')
  );
  loadRemoteThumbs();         // beklemeden: tablo once metinle gorunur
}

/** Görsel hücresinin içeriği: önizleme varsa görsel, yoksa metin. */
function fillImageTd(td, cell) {
  // `embedded` bayragina bakilir, dize karsilastirmasi YAPILMAZ (Faz 9.2.2).
  td.title = cell.embedded ? t('ui.embedded_image') : cell.src;
  td.replaceChildren();
  if (cell.thumb) {
    const im = document.createElement('img');
    im.src = cell.thumb;
    im.alt = cell.d;
    im.title = t('ui.image_click', { size: `${cell.iw}×${cell.ih}`, src: td.title });
    td.append(im);
    return;
  }
  // Onizleme yok: butce doldu ya da adres gorseli henuz/hic gelmedi. Metin
  // gosterilir, galeri yine de tam listeyi verir.
  const sp = document.createElement('span');
  sp.className = 'noimg';
  sp.textContent = cell.d;
  td.append(sp);
}

/* --- Adres gorsellerinin onizlemesi (`K-32`, 9.15) ------------------------
 *
 * Tablo aga cikmadan kurulur; adres hucresi yalnizca "uzak gorsel" diye
 * isaretli gelir. Onizlemeler cizimden SONRA, galerinin kullandigi kopru
 * metoduyla (`gallery_thumbs`) parca parca istenir — ayar, https ve "yalnizca
 * bu belgedeki gorsel" kurallari orada uygulanir, burada ikinci bir yol yok.
 */
const TABLE_THUMB_PX = 96;     // Python `images.THUMB_PX` ile ayni (check_web)
const REMOTE_CHUNK = 8;        // tek istekte kac gorsel: ilkler beklemeden gorunsun
let remoteCells = [];          // son cizimde onizleme bekleyen hucreler
let remoteRun = 0;             // cizim sayaci: eski cizimin yanitlari atilir

async function loadRemoteThumbs() {
  const run = ++remoteRun;
  const pending = remoteCells;
  if (!pending.length || !sel) return;
  const docId = sel.docId;
  const paths = [...new Set(pending.map((x) => x.cell.jp))];
  for (let i = 0; i < paths.length; i += REMOTE_CHUNK) {
    const chunk = paths.slice(i, i + REMOTE_CHUNK);
    const res = await api.gallery_thumbs(docId, chunk, TABLE_THUMB_PX);
    // Tablo bu arada yeniden cizildiyse ya da belge degistiyse yanit atilir;
    // yeni cizim kendi isteklerini yapar (indirilenler onbellekte).
    if (run !== remoteRun || !sel || sel.docId !== docId) return;
    const got = new Map(((res.ok && res.thumbs) || []).map((th) => [th.json_path, th]));
    for (const { td, cell } of pending) {
      if (!chunk.includes(cell.jp) || cell.thumb) continue;
      const th = got.get(cell.jp);
      if (!th) {
        // Gelmedi (ayar kapali, adres reddedildi, indirilemedi): her cizimde
        // yeniden istenmesin. Tablo yeniden kurulunca hucre tazelenir.
        cell.failed = true;
        continue;
      }
      cell.thumb = th.uri;
      cell.iw = th.source_width || th.width;
      cell.ih = th.source_height || th.height;
      if (td.isConnected) fillImageTd(td, cell);
    }
  }
}

/** Açık tabloyu köprüden yeniden kurar; seçim, filtre ve açık satırlar kalır.
 *  Bellekteki belgeden çizilir — kaydedilmemiş değişiklikler kaybolmaz. */
async function refreshTable() {
  if (!sel) return;
  const res = await api.table(sel.docId, sel.dsId, sel.variantId || null);
  if (!res.ok) return setStatus(res.error, true);
  applyTable(res);
}

/** Düzenleme kipinde hücreyi işaretler ve olaylarını bağlar (10.5).
 *
 * Kip kapalıyken hiçbir şey yapmaz — sınıf da eklenmez, dinleyici de.
 * Düzenlenemeyen hücre nedenini ipucunda söyler; neden Python'dan gelir.
 */
function markEditable(td, cell, src) {
  // ⚠ Kaydedilmemis degisiklik isareti kipten BAGIMSIZ: kip kapatilinca
  // degisiklikler kaybolmuyor, isaret de kaybolmamali.
  if (src && editedCells().has(src.ri + ',' + src.ci)) td.classList.add('edited');
  // 10.7.2 — transpozede alan adi: sutun basligi gibi isaretlenir ve duzenlenir.
  if (src && src.field !== undefined) {
    if (cell && (cur.table.cols_edited || []).includes(cell.d)) td.classList.add('edited');
    if (editOn && cell && cell.x) {          // uretilmis sutunun adi (Anahtar, Deger...)
      td.classList.add('no-edit');
      td.dataset.tip = t('edit.why_' + cell.x);
    } else if (editOn) {
      td.classList.add('editable');
      td.tabIndex = 0;
      td.addEventListener('dblclick', () => beginColumnRename(td, src.field));
      td.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); beginColumnRename(td, src.field); }
      });
    }
    return;
  }
  if (!editOn) return;
  td.__cell = cell;
  if (!cellEditable(cell, src)) {
    if (src && cell) {
      td.classList.add('no-edit');
      td.dataset.tip = t('edit.why_' + cell.x);
    }
    return;
  }
  td.__src = src;
  td.classList.add('editable');
  td.tabIndex = 0;
  td.addEventListener('dblclick', () => beginEdit(td));
  td.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); beginEdit(td); }
  });
}

/** Köprüden dönen tabloyu ekrana uygular (düzenleme sonrası yeniden kurulum). */
function applyTable(res) {
  cur = { table: res.table, view: res.view, doc: res.doc };
  setTitle(res.table);
  setDsMeta(res);
  render();
}

/** Başlık: tablonun adı + kaydedilmemiş ad değişikliği işareti (10.6). */
function setTitle(table) {
  const h = $('ds-title');
  h.textContent = table ? table.label : '—';
  h.classList.toggle('edited', !!(table && table.name_edited));
  h.title = table && table.name_edited ? t('ui.unsaved') : '';
}

function groupSeparator(name, span) {
  const tr = document.createElement('tr');
  tr.className = 'group-sep';
  const td = document.createElement('td');
  td.colSpan = span;
  td.textContent = name;
  tr.append(td);
  return tr;
}

function buildTd(cell, col, isFieldName, src, needle = '') {
  const td = document.createElement('td');
  markEditable(td, cell, src);
  if (!cell || cell.k === 'missing') {
    td.className = 'missing';
    td.title = t('ui.cell_missing');
    return td;
  }

  if (cell.k === 'records' || cell.k === 'object') {
    const b = document.createElement('span');
    b.className = 'badge';
    b.textContent = cell.d;
    td.append(b);
    return td;
  }

  if (cell.k === 'image') {
    // Sinif ATANIR, eklenmez: duzenleme kipinin `no-edit` sinifi gorseli
    // soluklastirmasin (onizleme bir deger metni degil).
    td.className = 'cell-img';
    fillImageTd(td, cell);
    // `K-32` — adres gorseli: onizleme tablo kurulurken GELMEZ, cizimden sonra
    // istenir (`loadRemoteThumbs`). Bekleyen hucre burada toplanir.
    if (cell.remote && cell.jp && !cell.thumb && !cell.failed) remoteCells.push({ td, cell });
    return td;
  }

  if (needle) markText(td, cell.d, needle);
  else td.textContent = cell.d;
  td.title = cell.d;
  if (isFieldName) td.classList.add('field-name');
  // Sarma karari GRUBA gore degil ICERIGE gore verilir (flatten.mark_wrap):
  // "Metin" grubuna girmeyen siniflandirma/kimlik sutunlari da uzun olabiliyor.
  if (col.wrap) td.classList.add('cell-wrap');
  if (col.numeric) td.classList.add('num');
  if (cell.d === '—') td.classList.add('cell-null');
  if (cell.d === 'true' || cell.d === 'false') td.classList.add('cell-bool');
  return td;
}

function buildDetailRow(row, cols, expander) {
  const tr = document.createElement('tr');
  tr.className = 'detail';
  const td = document.createElement('td');
  td.colSpan = cols.length + (expander ? 1 : 0);

  for (let k = 0; k < cur.table.columns.length; k++) {
    const cell = row[k];
    if (!cell || !cell.sub) continue;
    const block = document.createElement('div');
    block.className = 'sub-block';
    const title = document.createElement('div');
    title.className = 'sub-title';
    title.textContent = cur.table.columns[k].label;
    block.append(title, buildSubTable(cell.sub));
    td.append(block);
  }

  tr.append(td);
  return tr;
}

function buildSubTable(sub) {
  const table = document.createElement('table');
  table.className = 'sub';
  const thead = document.createElement('thead');
  const htr = document.createElement('tr');
  for (const c of sub.columns) {
    const th = document.createElement('th');
    th.textContent = c.label;
    htr.append(th);
  }
  thead.append(htr);
  const tbody = document.createElement('tbody');
  for (const r of sub.rows) {
    const tr = document.createElement('tr');
    for (const c of r) {
      const td = document.createElement('td');
      td.textContent = c && c.k !== 'missing' ? c.d : '';
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(thead, tbody);
  return table;
}

/* --- Filtre ve siralama --------------------------------------------------- */

/* --- Arama (9.29) ---------------------------------------------------------
 * Düz metin: görünen bütün sütunlarda geçen satırlar. `@sütun:değer` yalnızca
 * o sütunda geçen, `@sütun=değer` birebir eşleşen; ad ekrandaki etiket ya da
 * anahtar, iki nokta içeren ad tırnakla yazılır (`@"a:b"=x`). `@` ön eki bilerek
 * zorunlu: düz `ad:değer` yazımı `https://` ya da `09:00` aramasını bozardı.
 *
 * Transpozede "sütun" bir ALANDIR ve süzülen KAYITLARDIR (sütunlar). Gizlenen
 * kayıtlar görünüme `searchHidden` olarak yazılır; çıktılar onu Python'da
 * okur (`_table_for_output`), ekranda aranan dışa da aranmış çıkar.
 */
let search = null;   // { q, colIdx, fieldRow, missing } — `syncSearch` kurar

/** Küçük harfe çevirir ama UZUNLUĞU KORUR: noktalı büyük I (U+0130) için
 *  `toLowerCase` iki karakter (i + birleşen nokta) döndürüyor ve vurgunun
 *  konumu kayardı. O harf elle i olur — Türkçe klavyede büyük i odur;
 *  uzunluğu değişen öteki harfler olduğu gibi kalır. */
const DOTTED_I = String.fromCharCode(0x130);   // harf kodu: çeviri denetimi metin sanmasın

function fold(s) {
  return Array.from(s, (ch) => {
    if (ch === DOTTED_I) return 'i';
    const l = ch.toLowerCase();
    return l.length === ch.length ? l : ch;
  }).join('');
}

const QUOTE = '"';   // çift tırnak: tırnakla yazılan sütun adı (bkz. quoteName)
// @ad:değer · @ad=değer · @"a:b"=değer
const QUERY_RE = /^@(?:"([^"]*)"|([^:=]*?))\s*([:=])\s*([\s\S]*)$/;

/** Arama metni → sorgu. `pending`: ad yazılıyor, henüz süzme yok. */
function parseQuery(text) {
  if (!text) return null;
  if (!text.startsWith('@')) return { text };
  const m = QUERY_RE.exec(text);
  if (!m) return { pending: text.slice(1).trim() };
  return { col: (m[1] !== undefined ? m[1] : m[2]).trim(), exact: m[3] === '=', text: m[4].trim() };
}

/** Hücre sorguya uyuyor mu. Birebirde boş değer eksik/null hücreyi bulur. */
function cellHit(cell, q) {
  const d = cell && cell.k !== 'missing' ? fold(cell.d || '') : '';
  if (q.exact) return q.text === '' ? (d === '' || d === '—') : d === q.text;
  return d.includes(q.text);
}

/** Sorguyu tabloya bağlar; transpozede gizlenecek kayıtları görünüme yazar.
 *  `render` başında çağrılır: başlık da süzülmüş sütunlarla çizilsin. */
function syncSearch() {
  const q = parseQuery(filterText);
  search = { q, colIdx: -1, fieldRow: -1, missing: false };
  const transposed = !!cur.table.transposed;
  if (q && 'col' in q) {
    if (transposed) {
      search.fieldRow = cur.table.rows.findIndex((r) => r[0] && fold(r[0].d || '') === q.col);
      search.missing = search.fieldRow < 0;
    } else {
      search.colIdx = cur.table.columns.findIndex(
        (c) => fold(c.label) === q.col || fold(c.key) === q.col);
      search.missing = search.colIdx < 0;
    }
  }
  let hide = [];
  if (transposed && q && 'col' in q) {
    const row = search.missing ? null : cur.table.rows[search.fieldRow];
    hide = cur.table.columns.filter((c, j) => j > 0 && (!row || !cellHit(row[j], q)))
      .map((c) => c.key);
  }
  const prev = cur.view.searchHidden || [];
  if (prev.join('\u0000') !== hide.join('\u0000')) {
    cur.view.searchHidden = hide;
    saveView();
  }
}

function filterRows() {
  const all = cur.table.rows.map((row, i) => ({ row, i }));
  const q = search && search.q;
  if (!q || 'pending' in q) return all;
  if ('col' in q) {
    if (cur.table.transposed) return all;          // kayıtlar sütunda süzüldü
    if (search.missing) return [];
    return all.filter(({ row }) => cellHit(row[search.colIdx], q));
  }
  const idxs = visibleCols().map((c) => cur.table.columns.indexOf(c));
  return all.filter(({ row }) => idxs.some((k) => cellHit(row[k], q)));
}

/** Hücrede vurgulanacak metin; yoksa ''. `k`: tablodaki sütun, `i`: kaynak satır. */
function hitNeedle(k, i) {
  const q = search && search.q;
  if (!q || 'pending' in q || !q.text) return '';
  if (!('col' in q)) return q.text;
  if (cur.table.transposed) return i === search.fieldRow && k > 0 ? q.text : '';
  return k === search.colIdx ? q.text : '';
}

/** Aranabilir adlar: normalde sütun etiketleri (gizliler dahil), transpozede alanlar. */
function searchNames() {
  const names = cur.table.transposed
    ? cur.table.rows.map((r) => (r[0] && r[0].d) || '')
    : cur.table.columns.map((c) => c.label);
  return [...new Set(names.filter(Boolean))];
}

/** `@` yazılırken açılan ad listesi; yazdıkça daralır, baştan eşleşen önce. */
function showSuggest() {
  const box = $('filter-suggest');
  const q = cur ? parseQuery(filterText) : null;
  let names = [];
  if (q && 'pending' in q) {
    const all = searchNames();
    const p = q.pending;
    names = [...all.filter((n) => fold(n).startsWith(p)),
             ...all.filter((n) => !fold(n).startsWith(p) && fold(n).includes(p))].slice(0, 12);
  }
  box.replaceChildren();
  names.forEach((n, j) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'menu-item' + (j === 0 ? ' on' : '');
    b.textContent = n;
    // `mousedown` + `preventDefault`: tık kutunun odağını almasın, `blur`
    // listeyi tık işlenmeden kapatırdı.
    b.addEventListener('mousedown', (e) => { e.preventDefault(); acceptSuggest(n); });
    box.append(b);
  });
  box.hidden = !names.length;
}

function acceptSuggest(name) {
  const inp = $('filter');
  inp.value = '@' + quoteName(name) + ':';
  inp.dispatchEvent(new Event('input'));
  inp.focus();
}

/** Arama kutusunun tuşları: listede gezinme, seçme; Esc önce listeyi, sonra aramayı kapatır. */
function onFilterKey(e) {
  const box = $('filter-suggest');
  const items = [...box.children];
  const at = items.findIndex((b) => b.classList.contains('on'));
  if (!box.hidden && items.length) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const next = (at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items.forEach((b, j) => b.classList.toggle('on', j === next));
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      acceptSuggest(items[Math.max(at, 0)].textContent);
      return;
    }
  }
  if (e.key !== 'Escape') return;
  e.stopPropagation();
  if (!box.hidden) { box.hidden = true; return; }
  if (e.target.value) {
    e.target.value = '';
    e.target.dispatchEvent(new Event('input'));
  } else {
    e.target.blur();
  }
}

/* --- Hücre: kopyala ve bu değere göre süz (11.2) --------------------------
 * Tık hücreyi seçer (odak; düzenleme kipindeki çerçeveyle aynı işaret),
 * Ctrl+C değerini kopyalar. Sağ tık iki maddelik menü açar. Değer ekrandaki
 * kırpılmış metin değil hücrenin tamamıdır; iç içe değer metin çıktısındaki
 * gibi alan=değer çiftleri olur (export_text.cell_text ile aynı kural).
 * ⚠ Bu bölümün yorumlarında tırnak işareti yok: çeviri denetimi yorumları da
 * tarıyor ve tırnak içindeki Türkçeyi çevrilmemiş metin sayıyor.
 */
function subText(sub) {
  // İç içe nesne anahtar-değer alt tablosu olarak gelir; sütun adları uygulamanın.
  if (sub.columns.map((c) => c.key).join() === '_key,_value') {
    return sub.rows.filter((row) => row[1] && row[1].k !== 'missing')
      .map((row) => `${row[0].d}=${row[1].d}`).join(', ');
  }
  return sub.rows.map((row) => sub.columns
    .map((c, j) => (row[j] && row[j].k !== 'missing' && row[j].d ? `${c.label}=${row[j].d}` : ''))
    .filter(Boolean).join(', ')).filter(Boolean).join(' | ');
}

function cellCopyText(cell) {
  if (!cell || cell.k === 'missing') return '';
  if (cell.sub) return subText(cell.sub);
  return cell.d === '—' ? '' : (cell.d || '');
}

/** Hücrenin sütun adı (transpozede alan adı); alan adı sütunu için `null`. */
function cellFieldName(td) {
  if (cur.table.transposed) {
    if (td.__k === 0) return null;
    const head = cur.table.rows[td.__i] && cur.table.rows[td.__i][0];
    return head ? head.d : null;
  }
  const col = cur.table.columns[td.__k];
  return col ? col.label : null;
}

/** Süzülebilir mi: ad olmalı ve değer düz metin olmalı (iç içe ya da görsel değil). */
function cellFilterable(td) {
  const c = td.__cell;
  return !!cellFieldName(td) && !(c && (c.sub || c.k === 'image' || c.k === 'records'
    || c.k === 'object'));
}

/** Sorgudaki ad: ayraç (iki nokta, eşittir) ya da tırnak içeriyorsa tırnağa
 *  alınır; içindeki tırnak düşer. Öneri listesi ve hücre menüsü ortak. */
function quoteName(name) {
  const odd = [':', '=', QUOTE].some((ch) => name.includes(ch)) || name !== name.trim();
  return odd ? QUOTE + name.split(QUOTE).join('') + QUOTE : name;
}

function filterByCell(td) {
  const f = $('filter');
  f.value = '@' + quoteName(cellFieldName(td)) + '=' + cellCopyText(td.__cell);
  f.dispatchEvent(new Event('input'));
}

async function copyCell(td) {
  await copyToClipboard(cellCopyText(td.__cell));
  setStatus(t('msg.copied'));
}

/** Hücrenin sağ tık menüsü; imlecin yanında, ekrana sığacak biçimde. */
function openCellMenu(e, td) {
  e.preventDefault();
  e.stopPropagation();
  for (const id of MENUS) $(id).hidden = true;
  td.focus();
  const m = $('cell-menu');
  m.replaceChildren();
  menuItem(m, { label: t('ui.cell_copy'), side: 'Ctrl+C', run: () => copyCell(td) });
  if (cellFilterable(td)) {
    menuItem(m, { label: t('ui.cell_filter'), run: () => filterByCell(td) });
  }
  m.hidden = false;
  const x = Math.min(e.clientX, window.innerWidth - m.offsetWidth - 8);
  const y = Math.min(e.clientY, window.innerHeight - m.offsetHeight - 8);
  m.style.left = Math.max(0, x) + 'px';
  m.style.top = Math.max(0, y) + 'px';
}

/** Tablo gövdesinin dinleyicileri — hücre başına değil, tek yerde. */
function initCellActions() {
  const tb = $('tbody');
  tb.addEventListener('mousedown', (e) => {
    const td = e.target.closest('td');
    // Odaklanabilir yapılır ki tık seçsin; düzenleme kipindeki hücrenin
    // kendi tabindex değeri (0) korunur.
    if (td && td.__cell !== undefined && !td.hasAttribute('tabindex')) td.tabIndex = -1;
  });
  tb.addEventListener('contextmenu', (e) => {
    if (/^(input|textarea)$/i.test(e.target.tagName)) return;   // düzenleyicide tarayıcının menüsü
    const td = e.target.closest('td');
    if (td && td.__cell !== undefined) openCellMenu(e, td);
  });
  tb.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'c')) return;
    const td = e.target.closest && e.target.closest('td');
    // Metin seçiliyse tarayıcının kendi kopyalaması: kullanıcı bir parça istiyor.
    if (!td || td.__cell === undefined || String(window.getSelection())) return;
    e.preventDefault();
    copyCell(td);
  });
}

/** Metni yazar, eşleşen parçaları `<mark>` ile sarar. ⚠ `innerHTML` YOK:
 *  belge metni işaretleme olarak yorumlanmaz (SECURITY.md). */
function markText(el, text, needle) {
  const low = fold(text);
  el.replaceChildren();
  let at = 0;
  for (let i = low.indexOf(needle); needle && i >= 0; i = low.indexOf(needle, at)) {
    if (i > at) el.append(text.slice(at, i));
    const m = document.createElement('mark');
    m.className = 'hit';
    m.textContent = text.slice(i, i + needle.length);
    el.append(m);
    at = i + needle.length;
  }
  el.append(text.slice(at));
}

function sortRows(rows) {
  let out = rows;

  // Transpoze modda alan satirlarini gruplarina gore dizer; boylece grup
  // ayraclari parcali kalmaz. Kararli sirala, grup ici sira korunur.
  if (cur.table.transposed && cur.view.rowGroupSort) {
    const gi = (r) => {
      const k = ORDER_GROUPS.indexOf(r.row[0] && r.row[0].g);
      return k < 0 ? ORDER_GROUPS.length : k;
    };
    out = out.slice().sort((a, b) => gi(a) - gi(b));
  }

  const s = cur.view.sort;
  if (!s) return out;
  const idx = cur.table.columns.findIndex((c) => c.key === s.key);
  if (idx < 0) return out;

  return out.slice().sort((a, b) => {
    const ca = a.row[idx], cb = b.row[idx];
    const na = ca && 'v' in ca, nb = cb && 'v' in cb;
    let r;
    if (na && nb) r = ca.v - cb.v;
    // Siralama dili ARAYUZ dilini izler: harf sirasi dile gore degisir
    // (Turkce'de `ı` `i`den sonra gelir). Once 'tr' sabiti yaziliydi.
    else r = String(ca ? ca.d : '').localeCompare(
      String(cb ? cb.d : ''), document.documentElement.lang || 'tr', { numeric: true });
    return r * s.dir;
  });
}

function toggleSort(key) {
  const s = cur.view.sort;
  cur.view.sort = !s || s.key !== key ? { key, dir: 1 } : s.dir > 0 ? { key, dir: -1 } : null;
  saveView();
  renderHead();
  renderBody();
}
