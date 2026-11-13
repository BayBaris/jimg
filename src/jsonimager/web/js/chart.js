'use strict';

/* Grafik sekmesi: once soru, sonra secici (Faz 7.4).
 *
 * Sutunlar Python'da ROLE ayrilir (`chart_roles`) ve arayuz yalnizca uygun
 * olani listeler — belgeye ozel tek satir kod yoktur. Iki mod var:
 *   distribution — "Bu sutunda ne var?"  tek secici
 *   compare      — "X'e gore Y ne kadar?" kirilim + olcu + islem
 *
 * Dagilim modunda olcum secici GIZLENIR: kategorikte `count` tek anlamli
 * cevaptir. Oneri kartlari da moda gore ayri listelerdir.
 */

// Grafik turleri — ikon `<option>` icine konamadigi icin acilir menu elle
// kurulur (`chart-type-menu`). Ikonlar satir ici SVG yollari.
const CHART_TYPES = [
  ['bar', 'chart.bar', 'M2 15.6h14V17H2zM4.4 8h2.8v6.4H4.4zm4.2-4h2.8v10.4H8.6zm4.2 6.4h2.8v4h-2.8z'],
  ['pie', 'chart.pie', 'M9.3 2.2v7.5h7.5A7.5 7.5 0 0 1 9.3 17 7.5 7.5 0 0 1 9.3 2.2zm1.4 0A7.5 7.5 0 0 1 16.8 8.3h-6.1z'],
  ['line', 'chart.line', 'M2 15.6h14V17H2zM3.4 12.3l3.4-4.1 3 2.6 4.6-6 1.1.9-5.5 7.2-3-2.6-2.5 3z'],
];
let chartType = 'bar';

let chartMode = 'distribution';
let chartRoles = { breakdown: [], measure: [] };
let chartCards = { distribution: [], compare: [] };
let chartAggNotes = {};      // olcum anahtari -> ne ise yaradigi (Python'dan)
let chartPick = '';          // dagilim modunda secili sutun anahtari
let chartHintSeen = false;   // sekme ilk acilista kisa bir bilgi baloncugu gosterir

const isMeasure = (key) => chartRoles.measure.some((m) => m.key === key);

function chartOptions() {
  if (chartMode === 'distribution') {
    // Sayisal sutun secildiyse KIRILIM YOK: sutunun kendi dagilimi cizilir.
    return isMeasure(chartPick)
      ? { category: null, numeric: chartPick, agg: 'sum', chart: chartType }
      : { category: chartPick, numeric: null, agg: 'count', chart: chartType };
  }
  return { category: $('chart-cat').value, numeric: $('chart-num').value,
           chart: chartType, agg: $('chart-agg').value };
}

/* --- Secici ve aciklamalar ------------------------------------------------ */

/** Sütun rollerini ve önerileri Python'dan alır; seçicileri role göre süzer. */
async function fillChartColumns() {
  const res = await api.chart_columns(sel.docId, sel.dsId, sel.variantId);
  if (!res.ok) return false;

  chartRoles = { breakdown: res.breakdown, measure: res.measure };
  chartCards = res.suggestions || { distribution: [], compare: [] };

  // Dagilim modunda tek liste: once kirilimlar, sonra olculer. Ikisi de
  // "bu sutunda ne var" sorusuna cevap verir, ama farkli cizilir.
  const usable = [...res.breakdown, ...res.measure];
  if (!usable.length) return false;
  if (!usable.some((c) => c.key === chartPick)) chartPick = usable[0].key;

  if (chartMode === 'distribution') {
    fillSelect($('chart-cat'), usable, chartPick);
    $('chart-cat').value = chartPick;
  } else {
    fillSelect($('chart-cat'), res.breakdown, $('chart-cat').value);
    fillSelect($('chart-num'), res.measure, $('chart-num').value);
    fillSelect($('chart-agg'), res.aggs, $('chart-agg').value || 'sum');
    chartAggNotes = Object.fromEntries((res.aggs || []).map((a) => [a.key, a.note]));
  }

  paintChartMode(res);
  // Karsilastirma her zaman bir olcu sutunu ister: `Adet` artik listede yok,
  // kayit saymak Dagilim modunun isi.
  return chartMode === 'distribution'
    ? true
    : res.breakdown.length > 0 && res.measure.length > 0;
}

/** Moda göre hangi seçicinin görüneceğini ve açıklamayı ayarlar. */
function paintChartMode(res) {
  const isDist = chartMode === 'distribution';
  for (const b of $('chart-modes').querySelectorAll('.segbtn')) {
    b.classList.toggle('on', b.dataset.mode === chartMode);
    b.disabled = b.dataset.mode === 'compare'
      && !(chartRoles.breakdown.length && chartRoles.measure.length);
  }

  // Etiket metni AYRI bir span'da: `<label>` icinde `<select>` de var ve
  // dogrudan `textContent` yazmak onu silerdi.
  $('lbl-cat').querySelector('.lbl-txt').textContent =
    isDist ? t('ui.lbl_column') : t('ui.lbl_breakdown');
  $('lbl-agg').hidden = isDist;
  $('lbl-num').hidden = isDist;

  const excluded = (res && res.excluded) || [];
  const notes = [];
  if (isDist) {
    notes.push(isMeasure(chartPick)
      ? t('chart.dist_numeric', {how: t(res && res.rows > res.row_bar_limit
          ? 'chart.dist_bins' : 'chart.dist_rows')})
      : t('chart.dist_categorical'));
  } else {
    notes.push(t('chart.compare_note'));
  }
  if (excluded.length) {
    notes.push(t('chart.excluded', {n: excluded.length}));
  }
  $('note-chart').textContent = notes.join(' ');

  // Secili olcumun ne ise yaradigi KENDI satirinda; ustteki aciklamayi ezmez.
  const aggNote = isDist ? '' : (chartAggNotes[$('chart-agg').value] || '');
  $('note-agg').textContent = aggNote;
  $('note-agg').hidden = !aggNote;
}

/* --- Oneri kartlari -------------------------------------------------------
 * Kartlar `i` dugmesinin ICINDE durur, serit halinde degil: serit fazla yer
 * kapliyor ve kullaniciyi secicilerden once kendine cekiyordu.
 */

/** Öneri kartları — tablodan otomatik türetilir, SEÇİLİ MODA göre süzülür. */
function buildChartCards() {
  const box = $('chart-cards');
  box.className = 'menu chart-cards';
  box.replaceChildren();

  const head = document.createElement('div');
  head.className = 'menu-group';
  head.textContent = t(chartMode === 'distribution'
    ? 'chart.cards_dist' : 'chart.cards_compare');
  box.append(head);

  const list = (chartCards[chartMode] || []);
  if (!list.length) {
    const empty = document.createElement('div');
    empty.className = 'card-empty';
    empty.textContent = t('chart.cards_empty');
    box.append(empty);
    return;
  }

  for (const s of list) {
    const b = document.createElement('button');
    b.className = 'chart-card';
    // ⚠ Yerel degisken `t` OLAMAZ: global `t()` cevirici islevini golgeler.
    const title = document.createElement('b');
    title.textContent = s.title;
    const n = document.createElement('span');
    n.textContent = s.note;
    b.append(chartIcon(CHART_TYPES.find((c) => c[0] === s.chart)[2]), title, n);
    b.addEventListener('click', () => {
      box.hidden = true;
      applySuggestion(s);
    });
    box.append(b);
  }
}

function applySuggestion(s) {
  chartMode = s.mode;
  chartType = s.chart;
  if (s.mode === 'distribution') {
    chartPick = s.cat || s.numeric;
  } else {
    $('chart-cat').value = s.cat;
    $('chart-num').value = s.numeric;
    $('chart-agg').value = s.agg;
  }
  renderChart();
}

/* --- Tur secici ve cizim -------------------------------------------------- */

function chartIcon(path) {
  return svgIcon(path, { viewBox: '0 0 20 20' });
}

/** Tür düğmesini seçili türe göre yeniler. */
function paintChartType() {
  const [, label, path] = CHART_TYPES.find((t) => t[0] === chartType) || CHART_TYPES[0];
  const b = $('chart-type-btn');
  b.replaceChildren(chartIcon(path));
  b.dataset.tip = t(label);
  const caret = document.createElement('span');
  caret.className = 'caret';
  caret.textContent = '▾';
  b.append(caret);
}

function buildChartTypeMenu() {
  const m = $('chart-type-menu');
  m.replaceChildren();
  for (const [key, label, path] of CHART_TYPES) {
    const b = document.createElement('button');
    b.className = 'menu-item ctype-item' + (key === chartType ? ' on' : '');
    const txt = document.createElement('span');
    txt.textContent = t(label);
    b.append(chartIcon(path), txt);
    b.addEventListener('click', () => {
      m.hidden = true;
      chartType = key;
      paintChartType();
      renderChart();
    });
    m.append(b);
  }
}

async function renderChart() {
  if (!sel || !cur) return;
  const box = $('svg-wrap');
  paintChartType();

  if (!await fillChartColumns()) {
    box.replaceChildren();
    return setInfo(t('chart.no_columns'), 'error');
  }

  setInfo(t('msg.drawing'));
  const res = await api.chart_svg(sel.docId, sel.dsId, sel.variantId,
                                  currentRowOrder(), chartOptions());
  if (!res.ok) {
    box.replaceChildren();
    return setInfo(res.error, 'error');
  }

  const hot = mountSvg(res.svg, res.name);
  setInfo(t('msg.scene_info', {name: res.name, hot}));

  // Sekme ilk acildiginda onerilerin nerede oldugunu bir kez soyle.
  if (!chartHintSeen) {
    chartHintSeen = true;
    toggleMenu({ stopPropagation() {} }, 'chart-cards', buildChartCards);
  }
}
