/* Yerlesim matrisi (9.14.5) — gelistirme sunucusunda /__matrix.
 *
 * Uygulama her boyutta ayri bir iframe'de acilir ve icinden olculur. Onizleme
 * bolmesinin boyut taklidi ~780 px altina inmiyor ve bolme genislik degistirince
 * sessizce sifirlaniyor; iframe bu ikisinden de bagimsiz.
 *
 * Her boyutta: ana gorunum · Agent seridi acik · her kaplama penceresinin her
 * sekmesi. Olculen: sayfada yatay tasma, arac cubugunda kirpilma, ana alan en
 * az genisliginde mi (cekmece degilse), pencere ekranin icinde mi, altbilgi
 * dugmeleri `elementFromPoint` ile TIKLANABILIR mi, sekme govdesinde yatay tasma.
 *
 * `check.py --> check_web` bu dosyayi okur: SIZES en kucuk pencerenin icerik
 * boyutunu tasimali, OVERLAYS index.html'deki her `*-overlay`i tasimali.
 * Uygulamanin durumunu DEGISTIRMEZ: ayar yazan hicbir islev cagrilmaz
 * (gelistirme sunucusu gercek ayar dosyasina yaziyor).
 */

// Icerik boyutlari (CSS px). Pencere dis boyutundan cerceve payi (16x39) dusulur.
const SIZES = [
  [784, 421, 'en küçük pencere (800×460)'],
  [894, 425, 'hedef ekran, normal pencere'],
  [910, 433, 'hedef ekran, tam ekran'],
  [1350, 689, '1366×768 %100'],
  [1904, 1001, '1920×1080 %100'],
];

// Kaplama → acma, sekmeler, kapatma. Sekmesiz pencere tek durum olculur.
const OVERLAYS = {
  'settings-overlay': {
    open: async (W) => { await W.openSettings(); },
    tabs: (D) => [...D.querySelectorAll('#settings-overlay .set-tab')],
    body: '#settings-overlay .set-panes',
    close: (W) => W.closeSettings(),
  },
  'about-overlay': {
    open: async (W) => { await W.openAbout(); },
    tabs: () => [null],
    body: '#about-overlay .dlg-body',
    close: (W) => W.closeAbout(),
  },
  'ask-overlay': {
    // Yaniti beklenmez: pencere olculdukten sonra `close` ile kapatilir.
    open: async (W) => { W.ask('Soru', 'Olcum', [{ key: 'ok', label: 'Tamam', primary: true }]); },
    tabs: () => [null],
    body: '#ask-overlay .dlg-body',
    close: (W) => W.closeAsk(),
  },
  'export-overlay': {
    open: async (W, D) => { D.getElementById('btn-export').click(); },
    tabs: (D) => [...D.querySelectorAll('#export-overlay button.tab')],
    body: null,
    close: (W) => W.closeExport(),
  },
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = [];
let failures = 0;
// ⚠ Uygulamanin ust duzey `const`/`let`i pencere ozelligi DEGIL ve CSP
// (`script-src 'self'`) iframe'de `eval`e izin vermiyor — sabit kaynaktan okunur.
let MAIN_MIN_W = 0;

function report(size, scene, problems) {
  const line = `${size[0]}×${size[1]}  ${scene}: ${problems.length ? problems.join(' · ') : 'tamam'}`;
  log.push([line, problems.length > 0]);
  failures += problems.length;
  render();
}

function render() {
  document.getElementById('log').innerHTML = log
    .map(([l, bad]) => `<span class="${bad ? 'bad' : 'ok'}">${l.replace(/</g, '&lt;')}</span>`)
    .join('\n');
}

function hittable(D, el) {
  const r = el.getBoundingClientRect();
  if (!r.width || !r.height) return false;
  const hit = D.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
  return !!hit && (hit === el || el.contains(hit));
}

/** Ana gorunum: sayfa tasmasi, arac cubugu, ana alan, serit. */
function measureShell(W, D) {
  const out = [];
  if (D.documentElement.scrollWidth > W.innerWidth) out.push('sayfa yatay taşıyor');
  const tb = D.getElementById('toolbar');
  const tr = tb.getBoundingClientRect();
  const clipped = [...tb.querySelectorAll('*')]
    .filter((e) => e.offsetParent && !e.children.length)
    .filter((e) => { const b = e.getBoundingClientRect(); return b.width && b.right > tr.right + 0.5; });
  if (clipped.length) out.push(`araç çubuğunda ${clipped.length} öğe kırpık`);
  const dock = D.getElementById('cdock');
  const main = D.getElementById('main').getBoundingClientRect().width;
  if (!dock.hidden && !dock.classList.contains('drawer') && main < MAIN_MIN_W) {
    out.push(`ana alan ${Math.round(main)} px`);
  }
  if (!dock.hidden) {
    for (const id of ['cdock-send', 'cdock-close']) {
      if (!hittable(D, D.getElementById(id))) out.push(`${id} tıklanamıyor`);
    }
  }
  return out;
}

/** Acik kaplama penceresi: ekran icinde mi, altbilgi tiklanabilir mi. */
function measureDialog(W, D, id, bodySel) {
  const out = [];
  const panel = D.querySelector(`#${id} > .tpanel`);
  const p = panel.getBoundingClientRect();
  if (p.top < 0 || p.left < 0 || p.bottom > W.innerHeight + 0.5 || p.right > W.innerWidth + 0.5) {
    out.push(`pencere ekran dışında (${[p.left, p.top, p.right, p.bottom].map(Math.round)})`);
  }
  // Altbilgi KABINDAN secilir: "alt kenara yakin dugme" olcutu kayan govdede
  // altbilginin arkasina dusen satir dugmelerini de sayiyordu.
  const foot = [...panel.querySelectorAll('.tpanel-foot button')].filter((b) => b.offsetParent);
  if (!foot.length) out.push('altbilgi düğmesi yok');
  for (const b of foot) if (!hittable(D, b)) out.push(`"${b.textContent.trim().slice(0, 16)}" tıklanamıyor`);
  const body = bodySel && D.querySelector(bodySel);
  if (body && body.scrollWidth > body.clientWidth + 1) out.push('gövde yatay taşıyor');
  return out;
}

async function loadApp(w, h) {
  const stage = document.getElementById('stage');
  stage.textContent = '';
  const f = document.createElement('iframe');
  f.width = w; f.height = h; f.src = '/';
  stage.append(f);
  await new Promise((r) => { f.onload = r; });
  const W = f.contentWindow, D = f.contentDocument;
  // Belge secilip tablo cizilene kadar bekle (`sel`e disaridan erisilemez).
  for (let i = 0; i < 50 && !D.querySelector('#table-area tbody tr'); i++) await sleep(100);
  await sleep(300);
  return [W, D];
}

async function run() {
  const src = await (await fetch('/js/agent.js')).text();
  MAIN_MIN_W = Number((src.match(/^const MAIN_MIN_W = (\d+);/m) || [])[1]);
  if (!MAIN_MIN_W) throw new Error("agent.js'te MAIN_MIN_W okunamadı");
  for (const size of SIZES) {
    const [W, D] = await loadApp(size[0], size[1]);
    report(size, 'ana görünüm', measureShell(W, D));

    await W.setDock(true);
    await sleep(300);
    report(size, 'Agent şeridi açık' + (D.getElementById('cdock').classList.contains('drawer')
      ? ' (çekmece)' : ''), measureShell(W, D));
    await W.setDock(false);

    for (const [id, o] of Object.entries(OVERLAYS)) {
      await o.open(W, D);
      await sleep(600);
      if (D.getElementById(id).hidden) { report(size, id, ['açılmadı']); continue; }
      for (const tab of o.tabs(D)) {
        if (tab) { tab.click(); await sleep(id === 'export-overlay' ? 1200 : 150); }
        const name = tab ? `${id} / ${tab.getAttribute('aria-label') || tab.textContent.trim()}` : id;
        report(size, name, measureDialog(W, D, id, o.body));
      }
      o.close(W);
      await sleep(100);
    }
  }
  document.title = failures ? `MATRİS: ${failures} SORUN` : 'MATRİS: TAMAM';
  log.push([`\n${SIZES.length} boyut · ${log.length} durum · ${failures} sorun`, failures > 0]);
  render();
}

run().catch((e) => {
  document.title = 'MATRİS: HATA';
  log.push([`hata: ${e}`, true]);
  render();
});
