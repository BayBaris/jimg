'use strict';

/* Duzenleme kipi ve yerinde duzenleyici (Faz 10.5).
 *
 * Kip KAPALIYKEN tablo bugunku gibi davranir: ne sinif eklenir ne dinleyici
 * calisir. Acikken duzenlenebilir hucre odaklanabilir olur, duzenlenemeyen
 * hucre soluklasir ve ipucunda NEDENI soyler (neden Python'dan gelir: hucrenin
 * `x` alani, bkz. edit_map).
 *
 * ⚠ Hucrenin adresi hucrede TASINMAZ, konumundan hesaplanir (`cellSource`):
 * transpozesiz tabloda (satir indeksi, sutun indeksi), transpozede ikisi yer
 * degistirir. Python tarafi da adresi transpozesiz kabul eder (10.1).
 */

let editOn = false;
let editingTd = null;      // su an duzenlenen hucre (ayni anda tek tane)
let askResolve = null;     // acik soru penceresinin yaniti (10.5.2)

/* --- Ortak soru penceresi ------------------------------------------------- */

/** En fazla uc dugmeli soru; secilen dugmenin anahtarini dondurur.
 *
 * Escape ve ortuye tiklama `cancel` sayilir — pencere hicbir zaman yanitsiz
 * kapanmaz, cagiran "vazgecildi" dalini islemek zorunda.
 */
function ask(title, message, buttons) {
  closeAsk();
  $('ask-title').textContent = title;
  $('ask-msg').textContent = message;
  const foot = $('ask-actions');
  foot.replaceChildren();
  for (const b of buttons) {
    const el = document.createElement('button');
    el.className = 'btn' + (b.primary ? ' primary' : '');
    el.textContent = b.label;
    el.addEventListener('click', () => answerAsk(b.key));
    foot.append(el);
  }
  $('ask-overlay').hidden = false;
  (foot.querySelector('.primary') || foot.firstElementChild).focus();
  return new Promise((resolve) => { askResolve = resolve; });
}

function answerAsk(key) {
  const resolve = askResolve;
  askResolve = null;
  $('ask-overlay').hidden = true;
  if (resolve) resolve(key);
}

/** Acik soruyu `cancel` ile kapatir (Escape, ortu, yeni soru). */
function closeAsk() { if (askResolve) answerAsk('cancel'); else $('ask-overlay').hidden = true; }

/** Son kayıttan bu yana değişen hücreler — `"ri,ci"` kümesi (köprüden). */
function editedCells() {
  return new Set(((cur && cur.table && cur.table.edited) || []).map((p) => p[0] + ',' + p[1]));
}

/** Hucrenin TRANSPOZESIZ tablodaki adresi; duzenlenemezse null. */
function cellSource(rowIndex, colIndex) {
  if (!cur || !cur.table) return null;
  if (!cur.table.transposed) return { ri: rowIndex, ci: colIndex };
  // Transpozede satir = ozgun sutun, `_r{i}` sutunu = ozgun satir.
  // Ilk sutun (`_field`) alan ADLARINI tasir: hucre degil sutun basligidir,
  // adresi ozgun sutunun indeksidir (10.7.2).
  return colIndex === 0 ? { field: rowIndex } : { ri: colIndex - 1, ci: rowIndex };
}

let sortTimer = null;   // duzenleme kipinde baslik tiklamasi: cift tika yer acar

/** Başlık tıklaması: kip kapalıyken hemen sıralar. Kipte kısa bir bekleme
 *  var — çift tık (ad düzenleme) gelirse sıralama iptal olur, yoksa sütun
 *  ad düzenlerken iki kez sıralanırdı. */
function headerClick(key) {
  if (!editOn) return toggleSort(key);
  clearTimeout(sortTimer);
  sortTimer = setTimeout(() => toggleSort(key), 300);
}

/** Başlıkta ad düzenleme (kip açık, transpozesiz tablo). */
function headerRename(label, col) {
  clearTimeout(sortTimer);
  if (!editOn || cur.table.transposed) return;
  beginColumnRename(label, cur.table.columns.indexOf(col));
}

/** Kipi acar/kapatir. Oturum icindedir, diske yazilmaz. */
function setEditMode(on) {
  editOn = on;
  closeEditor();
  $('main').classList.toggle('edit-on', on);
  // 10.6 — baslik kipte odaklanabilir: F2 / Enter tablo adini duzenler.
  $('ds-title').tabIndex = on ? 0 : -1;
  const b = $('btn-edit');
  b.classList.toggle('on', on);
  b.setAttribute('aria-pressed', String(on));
  // ⚠ Once cizim: `renderBody` durum satirini kendi ozetiyle YENIDEN yaziyor,
  // ileti once verilseydi goz acip kapayincaya kadar silinirdi.
  render();
  setStatus(t(on ? 'ui.edit_started' : 'ui.edit_stopped'));
}

function toggleEditMode() { setEditMode(!editOn); }

/** Hucre duzenlenebilir mi — kip acik, adresi var ve Python engellememis. */
function cellEditable(cell, src) {
  // `field` adresi bir sutun basligidir, deger hucresi degil (`markEditable`).
  return editOn && !!src && src.field === undefined && !!cell && !cell.x;
}

/** Duzenleyiciyi acar: hucrenin yerine kutu koyar. */
function beginEdit(td) {
  if (!editOn || !td.__src) return;
  // ⚠ Acik bir duzenleyici varsa ONCE kapatilir. "Acikken hicbir sey yapma"
  // denemesinde ikinci hucreye cift tiklamak sessizce islemsiz kaliyordu.
  if (editingTd && editingTd !== td) closeEditor(true);
  if (editingTd === td) return;
  const cell = td.__cell;
  editingTd = td;

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'cell-edit';
  // Bos hucre `—` ile gosterilir; duzenleyici BOS acilir, yoksa kullanici
  // yazmadan onaylarsa degere tire girerdi.
  input.value = cell.d === '—' ? '' : cell.d;
  // ⚠ Hucrenin icerigi DEGISTIRILMEZ: kutu hucrenin USTUNE, ayni ic boslukla
  // yerlestirilir ve alttaki metin yalnizca gorunmez olur (`td.editing`). Ilk
  // yazimda icerik kutuyla degistiriliyordu; kutunun kendi yuksekligi satiri
  // uzatiyor, metin saga ve asagi kayiyordu. Boylece satirin olcusu ve metnin
  // yeri degisemez. Ic bosluk CSS'ten degil hucrenin HESAPLANAN degerinden
  // gelir: sayi sutunu, sarilan sutun ve punto ayari ayri bosluklar veriyor.
  const cs = getComputedStyle(td);
  input.style.padding = `${cs.paddingTop} ${cs.paddingRight} ${cs.paddingBottom} ${cs.paddingLeft}`;
  input.style.textAlign = cs.textAlign;
  td.classList.add('editing');
  td.append(input);
  input.focus();
  input.select();

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitEdit(input.value); }
    else if (e.key === 'Escape') { e.preventDefault(); closeEditor(true); }
  });
  // Baska yere tiklamak onaylar (hesap tablosu aliskanligi); Escape iptal eder.
  input.addEventListener('blur', () => { if (editingTd === td) commitEdit(input.value); });
}

/** Duzenleyiciyi kapatir; `redraw` ile hucre eski haline doner. */
function closeEditor(redraw) {
  const td = editingTd;
  editingTd = null;
  if (td && redraw) renderBody();
}

async function commitEdit(text) {
  const td = editingTd;
  if (!td) return;
  editingTd = null;
  // Degismeyen metin koprüye hic gitmez: yanlislikla acilip kapanan bir
  // duzenleyici belgeyi "kaydedilmemis" gostermemeli.
  const was = td.__cell.d === '—' ? '' : td.__cell.d;
  if (text === was) return renderBody();
  const { ri, ci } = td.__src;
  const res = await api.edit_cell(sel.docId, sel.dsId, sel.variantId || null, ri, ci, text);
  if (!res.ok) {
    renderBody();               // hucre eski degerine doner
    setStatus(res.error, true); // ⚠ cizimden SONRA: `renderBody` durum satirini
    return;                     //   kendi ozetiyle yeniden yaziyor
  }
  // Kopru duzenlemeden SONRAKI tabloyu doner: veri kumesi kimligi degismis
  // olabilir (ad duzenlendiyse) ve secim onunla tasinir.
  sel = { docId: sel.docId, dsId: res.ds_id, variantId: res.variant_id };
  applyTable(res);
  refreshTree();                // agactaki kaydedilmemis isareti
}

/* --- Kaydetme, geri al, yinele (10.5.2) ---------------------------------- */

/** Ağacı köprüden yeniden okur: `dirty` işareti orada hesaplanıyor. */
async function refreshTree() {
  applyTree(await api.tree());
}

/** Açık belgeyi kaydeder. Diskte değişmişse önce sorar (KB-3). */
async function saveDoc(docId) {
  const id = docId || (sel && sel.docId);
  if (!id) return false;
  let res = await api.save_doc(id);
  if (!res.ok && res.reason === 'changed_on_disk') {
    const answer = await ask(t('ui.unsaved'), res.error,
                             [{ key: 'save', label: t('ui.save_anyway'), primary: true },
                              { key: 'cancel', label: t('ui.cancel') }]);
    if (answer !== 'save') return false;
    res = await api.save_doc(id, true);
  }
  if (!res.ok) {
    setStatus(res.error, true);
    return false;
  }
  await refreshTree();
  if (sel && sel.docId === id) await select(sel.docId, sel.dsId, sel.variantId || null);
  setStatus(res.message);
  return true;
}

async function undoEdit() { await stepEdit(api.undo_edit(sel.docId)); }
async function redoEdit() { await stepEdit(api.redo_edit(sel.docId)); }

/** Seçimi köprünün kimlik eşlemesiyle taşır (ad değişimi, geri al/yinele).
 *  Varyant kimliği veri kümesi kimliğiyle başlar (`<ds_id>#v0`), o da çevrilir. */
function movedSelection(renamed) {
  const moved = renamed || {};
  const dsId = moved[sel.dsId] || sel.dsId;
  const variantId = sel.variantId && moved[sel.dsId]
    ? dsId + sel.variantId.slice(sel.dsId.length) : sel.variantId;
  return { docId: sel.docId, dsId, variantId: variantId || null };
}

/** Geri al/yinele sonrası: seçim taşınır, tablo ve ağaç yenilenir. */
async function stepEdit(call) {
  if (!sel) return;
  const res = await call;
  if (!res.ok) return setStatus(res.error, true);
  const next = movedSelection(res.renamed);
  await select(next.docId, next.dsId, next.variantId);
  await refreshTree();
}

/* --- Tablo adı (10.6) ----------------------------------------------------- */

/** Başlıkta ya da ağaç satırında yerinde ad düzenleyici.
 *
 * Tablonun adı üst nesnedeki ANAHTARDIR; köprü onu yeniden adlandırır ve
 * görünüm durumunu yeni kimliğe taşır. Kök tablo ve şema varyantı nedenle
 * reddedilir (köprü söyler, arayüz kural tekrarlamaz).
 */
function beginRename(el, docId, dsId, variantId) {
  inlineName(el, (text) => api.rename_dataset(docId, dsId, variantId || null, text), docId);
}

/** Sütun adı (10.7.2): başlıkta ya da transpozede alan adı hücresinde.
 *  `ci` TRANSPOZESİZ tablonun sütun indeksi; ad tüm satırlarda değişir. */
function beginColumnRename(el, ci) {
  if (!sel) return;
  const { docId, dsId, variantId } = sel;
  inlineName(el, (text) => api.rename_column(docId, dsId, variantId || null, ci, text), docId);
}

/** Yerinde ad kutusu: tablo adı ve sütun adı aynı kutuyu kullanır.
 *  `commit(text)` köprü yanıtını döndürür; seçim yanıtın kimlik eşlemesiyle taşınır. */
function inlineName(el, commit, docId) {
  if (!editOn || el.querySelector('input')) return;
  const was = el.textContent;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'cell-edit name-edit';
  input.value = was;
  el.replaceChildren(input);
  input.focus();
  input.select();

  let done = false;
  const finish = async (ok) => {
    if (done) return;
    done = true;
    const text = input.value;
    if (!ok || text === was) { el.textContent = was; return; }
    const res = await commit(text);
    if (!res.ok) {
      el.textContent = was;
      setStatus(res.error, true);
      return;
    }
    // Yanit duzenlenen tabloyu tasiyor. Secili tablo oysa dogrudan uygulanir;
    // degilse (ornegin adi degisen tablonun ALTINDAYSA) secim tasinip yeniden
    // istenir.
    if (sel && sel.docId === docId) {
      const next = movedSelection(res.renamed);
      if (next.dsId === res.ds_id && next.variantId === (res.variant_id || null)) {
        sel = next;
        applyTable(res);
      } else {
        await select(next.docId, next.dsId, next.variantId);
      }
    }
    await refreshTree();
  };
  input.addEventListener('keydown', (e) => {
    e.stopPropagation();                 // agac ve belge kisayollari karismasin
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
  // Agac satirina tiklama secer/daraltir; kutunun icindeki tiklama satira gitmez.
  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('dblclick', (e) => e.stopPropagation());
}

/** Uygulamadan çıkış sorusu (10.5.3, KB-5).
 *
 * ⚠ Bu işlevi JS değil PYTHON çağırır: pencerenin kapanma olayı
 * (`app._on_closing`) kaydedilmemiş belge görünce kapanışı iptal edip
 * `evaluate_js('askQuit()')` yapar. Onaylanırsa `quit_app` bayrağı koyar ve
 * pencere yeniden kapanır — bu kez sormadan.
 */
async function askQuit() {
  const dirty = (await api.dirty_docs()).docs || [];
  if (dirty.length) {
    const names = dirty.map((d) => d.name).join(', ');
    const answer = await ask(t('ui.unsaved'), t('ui.unsaved_quit', { names }),
                             [{ key: 'save', label: t('ui.save'), primary: true },
                              { key: 'discard', label: t('ui.dont_save') },
                              { key: 'cancel', label: t('ui.cancel') }]);
    if (answer === 'cancel') return;
    // Biri kaydedilemezse cikilmaz: kullanici iletiyi gorur, belge acik kalir.
    if (answer === 'save') for (const d of dirty) if (!await saveDoc(d.id)) return;
  }
  await api.quit_app();
}

/** Kaydedilmemiş belgeyi kapatmadan önce sorar (KB-5). */
async function closeDocAsked(doc) {
  if (doc.dirty) {
    const answer = await ask(t('ui.unsaved'), t('ui.unsaved_close', { name: doc.name }),
                             [{ key: 'save', label: t('ui.save'), primary: true },
                              { key: 'discard', label: t('ui.dont_save') },
                              { key: 'cancel', label: t('ui.cancel') }]);
    if (answer === 'cancel') return;
    if (answer === 'save' && !await saveDoc(doc.id)) return;
  }
  // `applyTree` kapanan belge seciliyse tabloyu kendisi temizler.
  applyTree(await api.close_doc(doc.id));
}
