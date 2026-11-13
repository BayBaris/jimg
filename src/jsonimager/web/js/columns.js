'use strict';

/* Sutunun OLCUSU ve SIRASI: genislik hesabi, surukle-birak, boyutlandirma ve
 * filtre menusu. `table.js` "ne cizilir"i bilir, bu dosya "nasil olculur"u.
 *
 * `autoWidth` arayuzun tek basina verdigi bir karar DEGILDIR: `export_img`
 * icindeki `auto_width` ile ayni formulu kullanir, yoksa PNG ciktisi ekrandan
 * farkli cikar. Iki taraf `check.py --> CONST_PAIRS` ile eslesik tutulur.
 */

const colByKey = (k) => cur.table.columns.find((c) => c.key === k);
// 9.29 — `searchHidden`: transpozede aramanın süzdüğü kayıtlar. Kullanıcının
// gizlediklerinden (`hidden`) AYRI tutulur: filtre menüsünde görünmez, arama
// temizlenince kendiliğinden boşalır.
const visibleKeys = () => cur.view.order.filter(
  (k) => !cur.view.hidden.includes(k) && !(cur.view.searchHidden || []).includes(k));
const visibleCols = () => visibleKeys().map(colByKey).filter(Boolean);

/** Basliktaki tip rozetinin metni (`js/table.js` ile AYNI kural). */
function badgeText(col) {
  if (col.kind === 'records') return '{}';
  if (col.kind === 'list') return '[]';
  return col.dtype || '';
}

/** Sutunun varsayilan genisligi.
 *
 * ⚠ Baslik HER ZAMAN taban olusturur: bir sutun kendi adindan dar olamaz.
 * Once yalnizca `max(etiket, veri) * 7 + 30` hesaplaniyordu ve basliktaki
 * **tip rozeti** (`str`, `float`, `object`) hic sayilmiyordu — sonucta sifirlanmis
 * bir tabloda bile `category` → `catego…`, `price` → `pr…` diye kirpiliyordu.
 * Rozet hucre metninde yok, yalnizca baslikta var; bu yuzden veri genisligiyle
 * ayni formulden cikarilamaz.
 */
function autoWidth(col) {
  const cw = charW();
  const head = col.label.length * cw + badgeText(col).length * badgeCharW() + PAD_X;

  let body;
  if (col.kind === 'records' || col.kind === 'object') body = 96;
  else if (col.kind === 'image') body = 120;            // onizleme sigsin
  // Sarilan sutun MAX_W'ye sikistirilmaz: dar sutunda satir sayisi patlar.
  // Isaret Python'dan gelir (flatten.mark_wrap), olcu tek yerde durur.
  else if (col.wrap) body = TEXT_COL_W;
  else {
    const idx = cur.table.columns.indexOf(col);
    let max = 0;                    // etiket artik `head`te hesaplaniyor
    const n = Math.min(cur.table.rows.length, 60);
    for (let i = 0; i < n; i++) {
      const d = cur.table.rows[i][idx];
      if (d && d.d) max = Math.max(max, d.d.length);
    }
    body = max * cw + PAD_X;
  }
  return Math.min(MAX_W, Math.max(MIN_W, head, body));
}

const widthOf = (col) => cur.view.widths[col.key] || autoWidth(col);

/** Sütun genişliklerini varsayılana döndürür. `keys` yoksa tablonun tamamı. */
function resetWidths(keys) {
  if (!cur) return;
  if (keys) {
    for (const k of keys) delete cur.view.widths[k];
  } else {
    cur.view.widths = {};
  }
  saveView();
  render();
  setStatus(t(keys ? 'msg.width_reset_one' : 'msg.width_reset_all'));
}
const hasExpandable = () => cur.table.rows.some((r) => r.some((c) => c && c.sub));
const showGroups = () => !!cur.view.groups && !cur.table.transposed;

/* --- Sutun sirasi (surukle-birak) -----------------------------------------
 * Native HTML5 surukle-birak KULLANILMAZ. DnD suresince imleci isletim
 * sistemi devralir ve CSS `cursor` yok sayilir: ozel imlec ailesi (Faz 8.1)
 * yerine Windows'un kendi surukleme oku cikiyordu. Isaretci olaylariyla
 * yapilan surukleme hem imleci bize birakir hem `startResize` ile ayni
 * kalibi kullanir.
 */

let dragKey = null;
// Bu kadar piksel gecilmeden surukleme BASLAMAZ; yoksa siralama icin yapilan
// her tik minicik bir surukleme sayilir ve sutunlar kazara yer degistirirdi.
const DRAG_SLOP = 4;
// Surukleme bittiginde olusan `click` siralamayi tetiklemesin.
let dragJustEnded = false;

function startColDrag(e, th) {
  if (e.button !== 0) return;
  e.preventDefault();          // metin secimini ve native surukleyiciyi kes
  // Bayrak her basista sifirlanir: surukleme sonrasi `render()` basliklari
  // yeniden kurdugu icin beklenen `click` bazen hic gelmez ve bayrak asili
  // kalirdi — sonraki tik sessizce yutulurdu.
  dragJustEnded = false;

  const startX = e.clientX;
  const key = th.dataset.key;
  let active = false;

  const move = (ev) => {
    if (!active) {
      if (Math.abs(ev.clientX - startX) < DRAG_SLOP) return;
      active = true;
      dragKey = key;
      th.classList.add('dragging');
      document.body.classList.add('col-dragging');
    }
    markDropTarget(ev.clientX);
  };

  const up = (ev) => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    if (!active) return;                     // esik asilmadi: tik siralamadir
    dragJustEnded = true;
    document.body.classList.remove('col-dragging');
    th.classList.remove('dragging');
    dropColumn(ev.clientX);
  };

  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}

/** Isaretcinin altindaki baslik ve hangi yanina birakilacagi. */
function dropTarget(x) {
  for (const th of $('thead').querySelectorAll('th[data-key]')) {
    const r = th.getBoundingClientRect();
    if (x >= r.left && x <= r.right) {
      return { th, after: x > r.left + r.width / 2 };
    }
  }
  return null;
}

function markDropTarget(x) {
  clearDropMarks();
  const hit = dropTarget(x);
  if (!hit || hit.th.dataset.key === dragKey) return;
  hit.th.classList.add(hit.after ? 'drop-right' : 'drop-left');
}

function clearDropMarks() {
  for (const th of $('thead').querySelectorAll('th')) {
    th.classList.remove('drop-left', 'drop-right');
  }
}

function dropColumn(x) {
  const hit = dropTarget(x);
  const targetKey = hit && hit.th.dataset.key;
  clearDropMarks();

  if (!dragKey || !targetKey || dragKey === targetKey) {
    dragKey = null;
    return;
  }

  // Gizli sutunlar da sirada durdugu icin islem tam `order` uzerinde yapilir.
  const order = cur.view.order.slice();
  order.splice(order.indexOf(dragKey), 1);
  order.splice(order.indexOf(targetKey) + (hit.after ? 1 : 0), 0, dragKey);
  cur.view.order = order;

  dragKey = null;
  saveView();
  render();
}

/* --- Sutun genisligi ------------------------------------------------------ */

function startResize(e, th, col) {
  e.preventDefault();
  e.stopPropagation();                        // sutun suruklemesini baslatma
  const startX = e.clientX;
  const startW = widthOf(col);
  const cg = $('cols');
  const offset = hasExpandable() ? 1 : 0;
  const ci = visibleCols().indexOf(col) + offset;

  // Sarilan sutun DARALTILAMAZ, yalnizca genisletilebilir: daraltmak metni
  // y ekseninde buyutur, satir yuksekligi katlanir ve tablo okunmaz olur.
  // Alt sinir, metnin uc satira sigdigi genisliktir (flatten.TEXT_COL_W).
  const minW = col.wrap ? TEXT_COL_W : MIN_W;

  const move = (ev) => {
    const w = Math.min(MAX_W * 3, Math.max(minW, startW + ev.clientX - startX));
    cur.view.widths[col.key] = w;
    cg.children[ci].style.width = w + 'px';
  };
  const up = () => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    saveView();
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}

/* --- Sutun menusu --------------------------------------------------------- */

function buildColMenu() {
  const m = $('col-menu');
  m.replaceChildren();

  // Grup denetimleri ayri dugme degil, bu menunun ilk bolumu.
  m.append(menuHead(t('menu.groups')));
  m.append(menuCheck(
    t(cur.table.transposed ? 'menu.show_group_seps' : 'menu.show_group_heads'),
    !!cur.view.groups,
    (on) => { cur.view.groups = on; saveView(); render(); buildColMenu(); }));
  m.append(menuCheck(
    t(cur.table.transposed ? 'menu.sort_fields_by_group' : 'menu.sort_cols_by_group'),
    groupSorted(),
    (on) => { onGroupSort(on); buildColMenu(); }));

  m.append(menuHead(t('menu.columns')));

  // Menu sutunlari HER ZAMAN gruplarina gore listeler, tablodaki sirayi izlemez.
  // Izleseydi sutunlar gruplu dizili olmadiginda ayni baslik birkac kez
  // tekrarlanirdi ("Sınıflandırma" iki yerde). Menunun isi sutun BULMAK;
  // tablonun duzenini yansitmak degil.
  const byGroup = new Map();
  for (const key of cur.view.order) {
    const col = colByKey(key);
    if (!col) continue;
    const g = col.group || G_OTHER;
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push({ key, col });
  }

  const groups = [...byGroup.keys()].sort((a, b) => {
    const ia = ORDER_GROUPS.indexOf(a), ib = ORDER_GROUPS.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });

  for (const g of groups) {
    // Transpoze modda sutunlar KAYITTIR, grubu olmaz; duz liste gosterilir.
    if (!cur.table.transposed) m.append(menuHead(t('group.' + g), true));
    for (const { key, col } of byGroup.get(g)) {
      m.append(menuCheck(col.label, !cur.view.hidden.includes(key), (on) => {
        const h = new Set(cur.view.hidden);
        on ? h.delete(key) : h.add(key);
        cur.view.hidden = [...h];
        // Kullanici sutunlara elle dokundu: otomatik gizleme bildirimleri
        // gecersiz kaldi. Uyari YENIDEN CIZILMEZ — her filtre degisiminde
        // yeniden belirip bes saniye daha durmasin.
        cur.view.autoHidden = [];
        cur.view.longHidden = [];
        hideNotes();
        saveView();
        render();
      }));
    }
  }
}

/** Filtre menüsünden UYGULANMIŞ bir şey var mı? (Araç çubuğu göstergesi.)
 *
 * ⚠ **Otomatik gizlenenler SAYILMAZ.** Seyrek ve uzun metin sütunları aracın
 * kendi varsayılanıdır, kullanıcının uyguladığı bir filtre değil; sayılsaydı
 * düğme neredeyse her belgede yanar ve "ben bir şey mi değiştirdim" sorusunu
 * boşuna doğururdu. Gösterge yalnızca kullanıcının eli değdiğinde yanar.
 */
function filtersActive() {
  if (!cur) return false;
  const v = cur.view || {};
  // ⚠ Gruba göre dizilim `groupSorted()` ile sorulur, `v.rowGroupSort` ile
  // DEĞİL: anahtar eksene göre değişiyor (`rowGroupSort` transpozede,
  // `groupSort` normalde — bkz. `onGroupSort`). Doğrudan alan okunduğunda
  // normal yönde gösterge hiç yanmıyordu.
  if (v.groups || groupSorted()) return true;
  const auto = new Set([...(v.autoHidden || []), ...(v.longHidden || [])]);
  return (v.hidden || []).some((k) => !auto.has(k));
}

/** Sıfırlama menüsü: tümü mü, yalnızca gruplar mı. */
function buildResetMenu() {
  const m = $('reset-menu');
  m.replaceChildren();
  const items = [
    [t('menu.reset_all'), t('menu.reset_all_desc'), onReset],
    [t('menu.reset_groups'), t('menu.reset_groups_desc'), onResetGroups],
  ];
  for (const [label, side, run] of items) menuItem(m, { label, side, run });
}

async function onReset() {
  if (!sel) return;
  const res = await api.reset_view(sel.docId, sel.dsId, sel.variantId);
  if (!res.ok) return setStatus(res.error, true);
  cur = { table: res.table, view: res.view, doc: res.doc };
  filterText = '';
  $('filter').value = '';
  expanded = new Set();
  renderNotes();
  render();
}
