'use strict';

/* Agent sohbet seridi (Faz 6.5, Faz 8.2'de adlandirildi).
 *
 * Disa aktarma panelinin bir sekmesi DEGIL: ana alanin yaninda duran ayri bir
 * serit. Tablo acik kalirken soru sorulabilir, yanit geldiginde tablo kapanmaz.
 * Sohbet dizisinin tek kaynagi Python'dadir (Api._chats) — gonderilen gecmis
 * ile ekranda gorunen ayni listedir.
 *
 * Arayuzde "Claude" degil "Agent" yazar: Faz 9'da saglayici secilebilir olacak
 * ve o zaman pencerenin adi degismemeli. Python kopru metotlari (`claude_ask`)
 * eski adlarini korur — onlar gercekten `claude` CLI'sini calistirir.
 */

// Alt sinir = acilis genisligi (CSS'teki `.cdock { width }` ile ayni tutulur).
// Daha darda mesajlar iki kelimelik satirlara bolunuyor, sohbet okunmaz oluyor.
const DOCK_MIN_W = 400, DOCK_MAX_W = 760;
// Serit ne kadar genislerse genislesin ana alan bu genisligin altina inmez:
// altinda arac cubugu tasar, baslik ve dosya adi gorunmez olur.
const MAIN_MIN_W = 460;
// Kenar cubugunun acik ve dar serit genislikleri — CSS'teki `#side { width }`
// ve `--rail-w` ile ayni tutulur (`check_web` CSS_PAIRS). `fitLayout`un
// esikleri bunlardan hesaplanir.
const SIDE_W = 296, RAIL_W = 64;
const COMPOSER_MAX_H = 220;   // soru kutusunun buyuyebilecegi en fazla yukseklik
// ...ve seridin en fazla bu payi (9.14.4.2). En kucuk pencerede (421 px) kutu
// 220'ye buyuseydi sohbete ~48 px kalirdi; payla ~120 kalir.
const COMPOSER_MAX_SHARE = 0.35;
let dockOpen = false;
let dockBusy = false;
let dockDocId = null;       // seride cizili olan belge
let dockInfoSeen = false;   // bilgi baloncugu ilk aciliste kendiliginden cikar
let dockActions = [];       // ornek sorular (SCHEMA.ACTIONS)
let dockModels = [];        // secilebilir modeller (api_agent.AGENT_MODELS)
let dockModel = '';         // secili modelin anahtari
let dockEfforts = [];       // caba duzeyleri (api_agent.AGENT_EFFORTS)
let dockEffort = '';        // secili caba duzeyinin anahtari
// Altbilginin VARSAYILAN satiri. Gecici mesajlar (hata, "dusunuyor…") bunu
// gecici olarak ezer; is bitince `setFoot()` argumansiz cagrilip geri gelinir.
let dockFootBase = '';

function initAgentDock() {
  $('btn-claude').addEventListener('click', toggleDock);
  $('cdock-close').addEventListener('click', () => setDock(false));
  $('cdock-info').addEventListener('click', () => toggleInfoPop());
  $('cpop-close').addEventListener('click', () => toggleInfoPop(false));
  $('cpop-schema').addEventListener('click', showSchemaMessage);
  $('cdock-new').addEventListener('click', resetChat);
  $('cdock-send').addEventListener('click', () => askAgent($('cdock-q').value));
  $('cdock-model').addEventListener('click',
    (e) => toggleMenu(e, 'model-menu', buildModelMenu));
  $('cdock-effort').addEventListener('click',
    (e) => toggleMenu(e, 'effort-menu', buildEffortMenu));

  const q = $('cdock-q');
  q.addEventListener('keydown', (e) => {
    // Enter gonderir, Shift+Enter alt satira gecer — sohbet penceresi aliskanligi.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      askAgent(q.value);
    }
  });
  q.addEventListener('input', growComposer);   // yapistirmayi da kapsar
  initDockResize();
}

function toggleDock() { setDock(!dockOpen); }

async function setDock(open) {
  // Kapali Agent hicbir yoldan acilmaz (menu, dugme, kisayol): tek kapi burasi.
  if (open && !agentOn) return;
  if (open && !sel) return setStatus(t('msg.pick_doc'), true);

  dockOpen = open;
  $('cdock').hidden = !open;
  $('btn-claude').classList.toggle('on', open);
  if (!open) sideKeep = false;
  // Dar pencerede varsayilan genislik bile fazla olabilir; acilista sinirlanir.
  // Kapanista da cagrilir: kendiliginden daraltilan panel geri gelir. Serit
  // artik gorunur, soru kutusu da burada olculur (`growComposer`).
  fitLayout();
  if (!open) return toggleInfoPop(false);

  $('cdock-q').focus();
  // Sohbet cizildikten SONRA baloncuk acilir; yoksa baloncuk bos bir seridin
  // uzerinde belirir ve neyin uzerine geldigi anlasilmaz.
  await loadChat();
  // Ilk aciliste "burasi ne ise yarar" baloncugu kendiliginden cikar; kullanici
  // arayuzde surekli duran hazir dugmelerle karsilasmaz.
  if (!dockInfoSeen) toggleInfoPop(true);
}

function toggleInfoPop(show) {
  const pop = $('cdock-pop');
  const next = show === undefined ? pop.hidden : show;
  pop.hidden = !next;
  if (next) dockInfoSeen = true;
}

/** Ornek sorular Python'daki SCHEMA.ACTIONS listesinden gelir.
 *
 * Tek yerde dururlar: BOS sohbet ekrani. Baloncuk ne yaptigini anlatir, soru
 * onermez; ikisinde birden durunca ayni liste iki kez okunuyordu.
 */
function buildChips(box) {
  box.replaceChildren();
  for (const a of dockActions) {
    const b = document.createElement('button');
    b.className = 'cchip';
    b.textContent = a.label;
    b.addEventListener('click', () => askAgent(a.question));
    box.append(b);
  }
}

/** Seçili belgenin sohbetini Python'dan alıp çizer. */
async function loadChat() {
  if (!sel) return;
  dockDocId = sel.docId;
  $('cdock-doc').textContent = cur ? cur.doc : '';

  const st = await api.agent_status();
  dockActions = st.actions || [];
  dockModels = st.models || [];
  dockModel = st.model || (dockModels[0] || {}).key || '';
  dockEfforts = st.efforts || [];
  dockEffort = st.effort || (dockEfforts[0] || {}).key || '';
  paintModel();
  paintEffort();
  $('cdock-values').hidden = !st.values;
  $('cdock-send').disabled = !st.available;
  $('cdock-q').disabled = !st.available;
  $('cdock-model').disabled = !st.available;
  $('cdock-effort').disabled = !st.available;
  // ⚠ Çaba seçicisi yalnızca çabayı GERÇEKTEN gönderen sağlayıcıda görünür
  // (`AK-16`). HTTP uçlarında karşılığı `reasoning_effort` ve her modelde
  // geçerli değil; gönderilmiyor. Seçiciyi devre dışı bırakmak değil GİZLEMEK
  // gerekiyor — devre dışı bir kutu "şimdi olmaz" der, oysa o sağlayıcıda
  // hiçbir zaman olmayacak.
  $('cdock-effort-wrap').hidden = !st.usesEffort;

  if (!st.available) {
    $('cdock-thread').replaceChildren(msgNode('err', st.error));
    return setFoot(st.error, 'error');
  }

  const res = await api.agent_thread(dockDocId);
  if (!res.ok) return setFoot(res.error, 'error');
  drawThread(res.messages);

  // Altbilgi TEK satir (Faz 8.2): daha once veri kumesi sayisi ve "hucre
  // degerleri gonderilmez" notu da buradaydi; ikincisi zaten bilgi
  // baloncugunda yaziyor ve satir sarmaya basliyordu.
  const p = await api.agent_payload(dockDocId);
  if (p.ok) {
    dockFootBase = t('agent.schema_len', {chars: fmtNum(p.chars)});
    setFoot();
  }
}

/* --- Model ve caba secicileri --------------------------------------------
 * Iki secici, tek kalip: `buildPickMenu` ikisini de ayni koddan kurar. Secim
 * Python'a bir SONRAKI soruyla gider; ayri bir cagri acilmaz.
 */

/** Secicilerin etiketi DUZ yazilir (`Opus`, `Orta`) — kod gibi degil. */
const pickLabel = (list, key) => (list.find((x) => x.key === key) || {}).label || '—';

function paintModel() { $('cdock-model').textContent = pickLabel(dockModels, dockModel); }
function paintEffort() { $('cdock-effort').textContent = pickLabel(dockEfforts, dockEffort); }

/** Secici menusu kurar. Secim Python'a bir SONRAKI soruyla gider; ayri bir
 *  cagri acilmaz — ikisi de yalnizca istek aninda anlam tasiyor.
 */
function buildPickMenu(menuId, head, items, current, onPick) {
  const m = $(menuId);
  m.className = 'menu';
  m.replaceChildren();

  const h = document.createElement('div');
  h.className = 'menu-group';
  h.textContent = head;
  m.append(h);

  for (const it of items) {
    const b = document.createElement('button');
    // Secili satir NOKTA ile degil RENK ile isaretlenir: `.menu-item .ext`
    // sutunu 52 px yer ayirtiyor ve menuyu gereksiz genisletiyordu.
    b.className = 'menu-item pick' + (it.key === current ? ' on' : '');
    const d = document.createElement('span');
    d.className = 'desc';
    d.textContent = it.label;
    if (it.note) {
      const n = document.createElement('span');
      n.className = 'mnote';
      n.textContent = it.note;
      d.append(n);
    }
    b.append(d);
    b.addEventListener('click', () => {
      m.hidden = true;
      onPick(it);
    });
    m.append(b);
  }
}

function buildModelMenu() {
  buildPickMenu('model-menu', t('menu.model'), dockModels, dockModel, (mo) => {
    dockModel = mo.key;
    paintModel();
    setFoot(t('agent.next_model', {label: mo.label}));
  });
}

function buildEffortMenu() {
  buildPickMenu('effort-menu', t('menu.effort'), dockEfforts, dockEffort, (ef) => {
    dockEffort = ef.key;
    paintEffort();
    setFoot(t('agent.next_effort',
             {label: ef.label.toLocaleLowerCase(document.documentElement.lang)}));
  });
}

/* --- Sohbet dizisi -------------------------------------------------------- */

function drawThread(messages) {
  const box = $('cdock-thread');
  box.replaceChildren();

  if (!messages.length) {
    box.append(introNode());
    return;
  }
  for (const m of messages) {
    box.append(msgNode(m.role === 'user' ? 'user' : 'bot', m.text));
  }
  box.scrollTop = box.scrollHeight;
}

/** Boş sohbet ekranı: örnek sorular yalnızca burada durur, soru sorulunca gider. */
function introNode() {
  const wrap = document.createElement('div');
  wrap.className = 'cintro';

  const mark = document.createElement('span');
  mark.className = 'big';
  mark.textContent = '✦';

  const p = document.createElement('p');
  p.textContent = t('agent.intro');

  const chips = document.createElement('div');
  chips.className = 'cchips';
  wrap.append(mark, p, chips);
  buildChips(chips);
  return wrap;
}

async function resetChat() {
  if (!dockDocId) return;
  await api.agent_reset(dockDocId);
  drawThread([]);
  setFoot(t('agent.chat_cleared'));
}

async function askAgent(text) {
  const q = (text || '').trim();
  if (!q || dockBusy || !sel) return;

  if (dockDocId !== sel.docId) await loadChat();
  toggleInfoPop(false);

  const box = $('cdock-thread');
  if (box.querySelector('.cintro')) box.replaceChildren();
  box.append(msgNode('user', q));

  const wait = msgNode('bot', '');
  wait.replaceChildren(dotsNode());
  box.append(wait);
  box.scrollTop = box.scrollHeight;

  $('cdock-q').value = '';
  growComposer();
  setBusy(true);
  setFoot(t('agent.thinking'));

  // 9.27 — ekranda açık tablo bu belgedeyse bağlamı gider; köprü onu yalnızca
  // veri gönderimi açıkken okur ve sınırları kendisi uygular.
  const ctx = sel && sel.docId === dockDocId && cur
    ? { ds: sel.dsId, variant: sel.variantId || null, rows: currentRowOrder() }
    : null;
  const res = await api.agent_ask(dockDocId, q, dockModel, dockEffort, ctx);
  setBusy(false);
  wait.remove();

  if (!res.ok) {
    box.append(msgNode('err', res.error));
    box.scrollTop = box.scrollHeight;
    return setFoot(res.error, 'error');
  }
  box.append(msgNode('bot', res.answer));
  box.scrollTop = box.scrollHeight;
  setFoot();          // altbilgi varsayilan satirina doner
}

/** Gönderilecek şemanın tamamı — sohbetin içinde bir not olarak gösterilir. */
async function showSchemaMessage() {
  toggleInfoPop(false);
  if (!dockDocId) return;

  const res = await api.agent_payload(dockDocId);
  if (!res.ok) return setFoot(res.error, 'error');

  const box = $('cdock-thread');
  if (box.querySelector('.cintro')) box.replaceChildren();

  const node = document.createElement('div');
  node.className = 'cmsg note';
  const head = document.createElement('div');
  head.textContent = t('agent.payload_head', {chars: fmtNum(res.chars)});
  const pre = document.createElement('pre');
  pre.textContent = res.text;
  node.append(head, pre);
  box.append(node);
  box.scrollTop = box.scrollHeight;
}

function setBusy(on) {
  dockBusy = on;
  $('cdock-send').disabled = on;
}

/** Altbilgi. Argumansiz cagrilirsa varsayilan satira (sema uzunlugu) doner. */
function setFoot(text, cls) {
  const el = $('cdock-foot');
  el.textContent = text === undefined ? dockFootBase : text;
  el.className = 'cfoot ' + (cls || '');
}

/** Kutuyu içeriğine göre büyütür; sınıra gelince kaydırmaya bırakır.
 *
 * Serit GIZLIYKEN cagrilmaz: gizli ogenin `scrollHeight`i 0'dir ve kutu sifir
 * yuksekligine sabitlenir. Bu yuzden olcum serit acildiginda yapilir.
 */
function growComposer() {
  const q = $('cdock-q');
  q.style.height = 'auto';                 // once kucult, sonra olc
  const need = q.scrollHeight;
  if (!need) return;
  const max = Math.min(COMPOSER_MAX_H,
    Math.floor($('cdock').clientHeight * COMPOSER_MAX_SHARE));
  q.style.height = Math.min(max, need) + 'px';
  q.style.overflowY = need > max ? 'auto' : 'hidden';
}

function dotsNode() {
  const d = document.createElement('span');
  d.className = 'cdots';
  for (let i = 0; i < 3; i++) d.append(document.createElement('i'));
  return d;
}

function msgNode(kind, text) {
  const el = document.createElement('div');
  el.className = 'cmsg ' + kind;

  if (kind === 'bot') {
    el.append(...renderMarkdown(text));
    el.append(copyBtn(text));
  } else {
    el.textContent = text;
    el.style.whiteSpace = 'pre-wrap';
  }
  return el;
}

function copyBtn(text) {
  const b = document.createElement('button');
  b.className = 'cmcopy';
  b.textContent = t('agent.copy');
  b.addEventListener('click', async () => {
    await copyToClipboard(text);
    b.textContent = t('agent.copied');
    setTimeout(() => { b.textContent = t('agent.copy'); }, 1400);
  });
  return b;
}

/* --- Seridin genisligi ---------------------------------------------------- */

/** Kenar çubuğu, şerit ve ana alan arasında yer paylaşımı (9.14.4).
 *
 * Sıra: ana alan `MAIN_MIN_W`in altına inmez. Şerit açıkken yer yetmiyorsa önce
 * kenar çubuğu kendiliğinden daralır; o da yetmezse şerit ÇEKMECE olur — ana
 * alanın üstüne biner, ana alan genişliğini korur. Kullanıcı daraltılmış paneli
 * açtıysa (`sideKeep`) panel kalır, şerit çekmeceye döner: son niyet kazanır.
 */
function fitLayout() {
  const need = DOCK_MIN_W + MAIN_MIN_W;
  const auto = dockOpen && sidebarOpen && !sideKeep && window.innerWidth - SIDE_W < need;
  if (auto !== sideAuto) {
    sideAuto = auto;
    renderSidebar();
  }
  const dock = $('cdock');
  const side = sideShown() ? SIDE_W : RAIL_W;
  const drawer = dockOpen && window.innerWidth - side < need;
  dock.classList.toggle('drawer', drawer);
  if (!dockOpen) return;
  if (drawer) {
    dock.style.flex = '';
    dock.style.width = DOCK_MIN_W + 'px';
  } else {
    setDockWidth(dock.getBoundingClientRect().width);
  }
  // Genislik satir kirilimini, yukseklik kutunun payini degistirir: olcum
  // genislik yerlestikten SONRA yapilir.
  growComposer();
}

/** Şeridin o an alabileceği en büyük genişlik — ana alan korunarak. */
function dockMaxWidth() {
  const side = $('side').getBoundingClientRect().width;
  return Math.max(DOCK_MIN_W, Math.min(DOCK_MAX_W, window.innerWidth - side - MAIN_MIN_W));
}

function setDockWidth(w) {
  const dock = $('cdock');
  const clamped = Math.max(DOCK_MIN_W, Math.min(dockMaxWidth(), w));
  dock.style.flex = `0 0 ${clamped}px`;
  dock.style.width = clamped + 'px';
}

/** Şeridin sol kenarından genişlik ayarı. */
function initDockResize() {
  const grip = $('cdock-grip');
  const dock = $('cdock');

  // Pencere kucululunce serit de kucululur; yoksa sabit genislik ana alani
  // ezer ve arac cubugu yine tasar. Esik gecilince panel daralir ya da serit
  // cekmeceye doner (`fitLayout`).
  window.addEventListener('resize', fitLayout);

  grip.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = dock.getBoundingClientRect().width;

    const move = (ev) => setDockWidth(startW - (ev.clientX - startX));
    const up = () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
    // Yakalama yalnizca bir iyilestirme; basarisiz olsa da dinleyiciler
    // document uzerinde oldugu icin surukleme calisir (bkz. panel tutamagi).
    try { grip.setPointerCapture(e.pointerId); } catch { /* zorunlu degil */ }
  });
}
