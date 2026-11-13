'use strict';

/* Hicbir bolume ait olmayan yardimcilar: kisayollar, menu parcalari, pano ve
 * markdown cizici. Buradaki hicbir sey tabloyu, agaci ya da paneli BILMEZ —
 * bilseydi bagimlilik ters yone akar ve dosya bolmenin anlami kalmazdi.
 */

const $ = (id) => document.getElementById(id);

/** Durum cubugu (pencerenin alt seridi). */
/** Modal kaplamada odagin DISARI cikmasini engeller (odak tuzagi).
 *
 * ⚠ Olculdu (`9.4.6`): ayarlar penceresi acikken son dugmeden sonra `Tab`,
 * kaplamanin ARKASINDAKI uygulama menusune atliyordu — kullanici modal
 * acikken erisemedigini sandigi bir dugmeye odaklanabiliyordu.
 *
 * Oncelik `Escape` ile AYNI: ekranda ust uste binme sirasi. Odak disaridayken
 * ilk `Tab` iceri girer, yani pencere acilirken odagi zorla tasimaya gerek
 * yok — acilista hicbir kutu kendiliginden vurgulanmiyor.
 */
const FOCUSABLE = 'button, select, input, textarea, a[href], [tabindex]:not([tabindex="-1"])';

function focusTrap(e, ids) {
  if (e.key !== 'Tab') return;
  const ov = ids.map((id) => $(id)).find((el) => el && !el.hidden);
  if (!ov) return;
  const items = [...ov.querySelectorAll(FOCUSABLE)]
    .filter((el) => !el.disabled && el.offsetParent !== null);
  if (!items.length) return;

  const first = items[0], last = items[items.length - 1], cur = document.activeElement;
  if (!ov.contains(cur)) first.focus();
  else if (e.shiftKey && cur === first) last.focus();
  else if (!e.shiftKey && cur === last) first.focus();
  else return;
  e.preventDefault();
}

function setStatus(text, isError) {
  const s = $('status');
  s.textContent = text;
  s.classList.toggle('error', !!isError);
}

/** Sayıyı arayüz diline göre biçimlendirir (binlik ayracı).
 *
 * Dil `<html lang>` uzerinden okunur — `loadStrings` orayi secili dile
 * ayarliyor, yani tek kaynak yine sozlukten geliyor. Once her cagri yerine
 * `toLocaleString('tr')` sabiti yaziliydi ve Ingilizce arayuzde de Turkce
 * ayrac cikiyordu.
 */
function fmtNum(n) {
  return Number(n).toLocaleString(document.documentElement.lang || 'tr');
}

/* --- Menuler --------------------------------------------------------------
 * Her acilir menunun kimligi burada kayitli: biri acilinca digerleri kapanir
 * ve belge tiklamasi hepsini kapatir. Yeni bir menu eklenirse bu diziye de
 * yazilmali, yoksa ust uste iki menu acik kalir.
 */

const MENUS = ['app-menu', 'col-menu', 'reset-menu', 'save-menu', 'chart-type-menu',
               'chart-cards', 'model-menu', 'effort-menu', 'rail-pop', 'cell-menu'];

/** Açılır menüyü açar; diğerlerini kapatır.
 *
 * Tiklama `stopPropagation` ile durduruluyor (yoksa belge dinleyicisi menuyu
 * hemen kapatir), bu yuzden komsu menuyu burada elle kapatmak gerekir.
 */
function toggleMenu(e, id, build) {
  e.stopPropagation();
  const m = $(id);
  const show = m.hidden;
  for (const other of MENUS) $(other).hidden = true;
  m.hidden = !show;
  if (show) build();
}

function menuHead(text, sub) {
  const h = document.createElement('div');
  h.className = 'menu-group' + (sub ? ' sub' : '');
  h.textContent = text;
  return h;
}

/** Menü içinde onay kutulu satır. */
function menuCheck(text, checked, onChange) {
  const label = document.createElement('label');
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = checked;
  cb.addEventListener('change', () => onChange(cb.checked));
  const span = document.createElement('span');
  span.textContent = text;
  label.append(cb, span);
  return label;
}

/** Menüde eyleme bağlı satır: solda etiket, sağda ikinci bir metin.
 *
 * Uc menu de (`buildResetMenu`, `buildSaveMenu`, `buildAppMenu`) ayni kalibi
 * kuruyordu; satir bicimi ya da "tikla-kapan" davranisi degisince uc dosyanin
 * birden duzenlenmesi gerekiyordu.
 *
 * `side` bos birakilabilir (sagda bir sey yok). `sideClass` sag parcanin
 * sinifidir: `desc` aciklama, `menu-key` kisayol. Etiket `ext` sutunundadir —
 * genisligi `wide` ile acilir.
 */
function menuItem(menu, { label, labelClass = 'ext wide', side = '', sideClass = 'desc', run }) {
  const b = document.createElement('button');
  b.className = 'menu-item';
  const e = document.createElement('span');
  e.className = labelClass;
  e.textContent = label;
  b.append(e);
  if (side) {
    const s = document.createElement('span');
    s.className = sideClass;
    s.textContent = side;
    b.append(s);
  }
  b.addEventListener('click', () => { menu.hidden = true; run(); });
  menu.append(b);
  return b;
}

/** Satır içi SVG ikon kurucusu.
 *
 * `innerHTML` yok (`K-05` ile ayni gerekce: metin hicbir kosulda isaretleme
 * olarak yorumlanmasin) ve SVG dogru ad alaninda kurulmali — `createElement`
 * calismaz. Ayni kalip once `chartIcon` ve `jsonIcon` icinde iki kez yaziliydi.
 */
function svgIcon(paths, { viewBox = '0 0 16 16', cls = 'ico' } = {}) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', viewBox);
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  for (const d of [].concat(paths)) {
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', d);
    svg.append(p);
  }
  return svg;
}

/** `<select>` doldurur; onceki secim listede duruyorsa korunur. */
function fillSelect(el, list, keep) {
  el.replaceChildren();
  for (const c of list) {
    const o = document.createElement('option');
    o.value = c.key;
    o.textContent = c.label;
    el.append(o);
  }
  if (keep && list.some((c) => c.key === keep)) el.value = keep;
}

/* --- Pano ----------------------------------------------------------------- */

/** Metni panoya kopyalar. Metin panelinden de sohbet baloncugundan da çağrılır. */
async function copyToClipboard(text) {
  // file:// kaynagi guvenli baglam sayilmayabilir; execCommand yedegi sart.
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  const tmp = document.createElement('textarea');
  tmp.value = text;
  tmp.style.position = 'fixed';
  tmp.style.opacity = '0';
  document.body.append(tmp);
  tmp.select();
  document.execCommand('copy');
  tmp.remove();
  window.getSelection().removeAllRanges();
}

/* --- Markdown ------------------------------------------------------------- */

/** Sade markdown çizici: başlık, madde, kalın ve `kod`.
 *
 * Kütüphane yok (`K-05`) ve `innerHTML` yok: her düğüm elle kurulur, böylece
 * yanıt metni hiçbir koşulda HTML olarak yorumlanmaz.
 */
function renderMarkdown(text) {
  const out = [];
  let list = null;

  const flush = () => { if (list) { out.push(list); list = null; } };

  for (const raw of (text || '').split('\n')) {
    const line = raw.trimEnd();
    if (!line.trim()) { flush(); continue; }

    const head = line.match(/^#{1,6}\s+(.*)$/);
    if (head) {
      flush();
      const h = document.createElement('h4');
      h.append(...inlineNodes(head[1]));
      out.push(h);
      continue;
    }

    const item = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (item) {
      if (!list) list = document.createElement('ul');
      const li = document.createElement('li');
      li.append(...inlineNodes(item[1]));
      list.append(li);
      continue;
    }

    flush();
    const p = document.createElement('p');
    p.append(...inlineNodes(line));
    out.push(p);
  }
  flush();
  return out.length ? out : [document.createTextNode(text || '')];
}

/** Satır içi `**kalın**` ve `` `kod` `` işaretlerini düğüme çevirir. */
function inlineNodes(text) {
  const nodes = [];
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0, m;

  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(document.createTextNode(text.slice(last, m.index)));
    const el = document.createElement(m[1] ? 'b' : 'code');
    el.textContent = m[1] || m[2];
    nodes.push(el);
    last = re.lastIndex;
  }
  if (last < text.length) nodes.push(document.createTextNode(text.slice(last)));
  return nodes;
}
