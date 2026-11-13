'use strict';

/* Cizim goruntuleyicisi: SVG'yi panele baglar, yakinlastirir, kaydirir ve
 * hover ipuclarini kurar. Uc sekme de (Tablo→Görüntü, Ağaç, Grafik) ayni
 * goruntuleyiciyi kullanir — SVG'nin ICERIGI Python'da uretilir (`vector.py`),
 * burada yalnizca gosterimi vardir.
 *
 * Tekerlek yakinlastirir, SAG TUS kaydirir: sol tus SVG ogelerinin hover/tik
 * isini bozardi. Baglam menusu bu alanda bastirilir.
 */

let zoom = 1;                 // 1 = %100
const ZOOM_MIN = 0.25, ZOOM_MAX = 4;

function hideTip() { $('tooltip').hidden = true; }

function svgNatural() {
  const svg = $('svg-wrap').querySelector('svg');
  if (!svg) return null;
  const vb = (svg.getAttribute('viewBox') || '').split(/\s+/).map(Number);
  return vb.length === 4 ? { w: vb[2], h: vb[3] } : null;
}

function applyZoom(z) {
  const svg = $('svg-wrap').querySelector('svg');
  const nat = svgNatural();
  if (!svg || !nat) return;
  zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
  svg.style.width = Math.round(nat.w * zoom) + 'px';
  $('zoom-range').value = Math.round(zoom * 100);
  $('zoom-val').textContent = '%' + Math.round(zoom * 100);
}

/** Tekerlekle yakınlaştırma ve sağ tuşla kaydırma (pan). */
function initZoomGestures() {
  const box = $('svg-wrap');

  box.addEventListener('wheel', (e) => {
    if ($('zoombar').hidden) return;      // yalnizca cizim gosterilen sekmelerde
    e.preventDefault();
    applyZoom(zoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
  }, { passive: false });

  // Sag tusla kaydirma: yakinlastirilmis cizimde en dogal gezinme. Cizim
  // alaninda baglam menusunun isi yok, bastiriliyor.
  box.addEventListener('contextmenu', (e) => e.preventDefault());
  box.addEventListener('mousedown', (e) => {
    if (e.button !== 2) return;
    e.preventDefault();
    const x0 = e.clientX, y0 = e.clientY;
    const l0 = box.scrollLeft, t0 = box.scrollTop;
    box.classList.add('panning');

    const move = (ev) => {
      box.scrollLeft = l0 - (ev.clientX - x0);
      box.scrollTop = t0 - (ev.clientY - y0);
    };
    const up = () => {
      box.classList.remove('panning');
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  });
}

/** Çizimi panelin görünür alanına sığdırır. */
function zoomFit() {
  const nat = svgNatural();
  if (!nat) return;
  const box = $('svg-wrap');
  const avail = box.clientWidth - 28;          // padding payı
  applyZoom(Math.min(1, avail / nat.w));
}

/** SVG'yi panele yerleştirir ve hover ipuçlarını bağlar; etkileşimli öğe sayısını döner. */
function mountSvg(svgText, name) {
  const box = $('svg-wrap');
  // innerHTML yerine SVG olarak ayristirilir: HTML ayristiricisina hic girmez.
  const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
  box.replaceChildren(document.importNode(doc.documentElement, true));
  box.dataset.name = name;

  const tip = $('tooltip');
  for (const el of box.querySelectorAll('.hot')) {
    el.addEventListener('mousemove', (e) => {
      tip.textContent = el.getAttribute('data-tip');
      tip.hidden = false;
      tip.style.left = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + 'px';
      tip.style.top = (e.clientY - tip.offsetHeight - 10) + 'px';
    });
    el.addEventListener('mouseleave', hideTip);
  }
  box.addEventListener('mouseleave', hideTip);
  zoomFit();
  return box.querySelectorAll('.hot').length;
}

/** Ağaç ve tablo — ikisi de sahneden üretilen etkileşimli SVG. */
async function renderVector(kind) {
  if (!sel) return;
  if (kind === 'table' && !cur) return setInfo(t('msg.pick_dataset'), true);

  setInfo(t('msg.drawing'));
  const res = await api.scene_svg(kind, sel.docId,
                                  kind === 'table' ? sel.dsId : null,
                                  kind === 'table' ? sel.variantId : null,
                                  kind === 'table' ? currentRowOrder() : null,
                                  kind === 'table' ? { expanded: currentExpanded() } : {});
  if (!res.ok) {
    $('svg-wrap').replaceChildren();
    return setInfo(res.error, 'error');
  }
  const hot = mountSvg(res.svg, res.name);
  const formats = (SAVE_FORMATS[saveKey()] || []).map((f) => f[0]).join(', ');
  setInfo(t('msg.scene_info_formats', {name: res.name, hot, formats}));
}
