'use strict';

/* Sol paneldeki agac: klasor -> belge -> veri kumesi -> sema varyanti.
 *
 * Agacin tek gorevi SECIM uretmektir; secildikten sonrasi `table.js`'in isi
 * (`select`). Kapali dugumler `collapsed` kumesinde tutulur — Python'da degil,
 * cunku bu tamamen gorunum durumudur ve belgeyle birlikte tasinmasi gerekmez.
 */

async function runOpen(fn) {
  const res = await fn();
  if (res.cancelled) return;
  applyTree(res);
}

function applyTree(res, autoSelect) {
  if (!res || !res.ok) return setStatus((res && res.error) || t('err.unknown'), true);

  tree = { folders: res.folders || [], docs: res.docs || [] };
  renderTree();

  const msgs = [];
  if (res.message) msgs.push(res.message);
  for (const e of res.errors || []) msgs.push('⚠ ' + e);
  $('side-msg').textContent = msgs.join('  ·  ');

  // Yeni acilan belge varsa ona gec, yoksa ilk belgenin en buyuk tablosunu ac.
  const target = res.opened
    ? tree.docs.find((d) => d.id === res.opened)
    : (autoSelect && !sel ? tree.docs[0] : null);
  if (target) selectBest(target);
  else if (sel && !tree.docs.some((d) => d.id === sel.docId)) clearTable();
}

function selectBest(doc) {
  const recs = doc.datasets.filter((d) => d.kind === 'records');
  const best = recs.sort((a, b) => b.rows * b.cols - a.rows * a.cols)[0] || doc.datasets[0];
  if (best) select(doc.id, best.id, null);
}

function renderTree() {
  const box = $('tree');
  box.replaceChildren();

  for (const f of tree.folders) box.append(folderNode(f, 0));

  // Klasor agacinda yer almayan (tek tek acilmis) belgeler
  const inFolders = new Set();
  const collect = (n) => {
    if (n.type === 'file') inFolders.add(n.path);
    for (const c of n.children || []) collect(c);
  };
  tree.folders.forEach(collect);

  const loose = tree.docs.filter((d) => !inFolders.has(d.path));
  for (const d of loose) box.append(docNode(d, 0));

  if (!box.children.length) {
    const p = document.createElement('div');
    p.className = 'tree-empty';
    p.textContent = t('ui.tree_empty');
    box.append(p);
  }

  // Daraltilmis serit ayni listeden beslenir; agacin yeniden kuruldugu TEK yer
  // burasi oldugu icin iki liste ayrisamaz.
  renderRailDocs();
}

function rowEl(depth, cls) {
  const el = document.createElement('div');
  el.className = 'tnode ' + cls;
  el.style.paddingLeft = 8 + depth * 12 + 'px';
  return el;
}

function chevron(open) {
  const c = document.createElement('span');
  c.className = 'chev';
  c.textContent = open ? '▾' : '▸';
  return c;
}

function matches(text) {
  return !treeFilter || String(text).toLowerCase().includes(treeFilter);
}

/** Ağaçtaki × düğmesi. `run` bir Api çağrısı döndürür; sonucu ağaca uygulanır. */
function closeBtn(label, run) {
  const b = document.createElement('span');
  b.className = 'tclose';
  b.textContent = '×';
  b.title = label;
  b.addEventListener('click', async (e) => {
    e.stopPropagation();
    // ⚠ Kimi kapatma yolu agaci KENDISI tazeliyor (kaydedilmemis belge sorusu,
    // 10.5.2) ve bir sey dondurmuyor; donen yoksa burada ikinci kez uygulanmaz.
    const res = await run();
    if (res) applyTree(res);
  });
  return b;
}

function folderNode(node, depth) {
  const frag = document.createDocumentFragment();
  const key = 'dir:' + node.path;
  const open = !collapsed.has(key);

  const el = rowEl(depth, 'tdir');
  el.append(chevron(open));
  const name = document.createElement('span');
  name.className = 'tname';
  name.textContent = node.name;
  el.append(name);

  // Kapatma yalnizca KOK klasorde: `Api.close_folder` acilan klasor listesinden
  // siler, alt klasorler o listede yoktur.
  if (depth === 0) {
    el.append(closeBtn(t('ui.close_folder'), () => api.close_folder(node.path)));
  }

  el.title = node.path;
  el.addEventListener('click', () => {
    open ? collapsed.add(key) : collapsed.delete(key);
    renderTree();
  });

  const kids = document.createDocumentFragment();
  let any = false;
  if (open) {
    for (const c of node.children || []) {
      const sub = c.type === 'dir' ? folderNode(c, depth + 1) : fileNode(c, depth + 1);
      if (sub.childNodes.length) { kids.append(sub); any = true; }
    }
  }
  // Filtre aciksa yalnizca eslesen dal gosterilir.
  if (treeFilter && !any && !matches(node.name)) return frag;

  frag.append(el, kids);
  return frag;
}

function fileNode(node, depth) {
  const frag = document.createDocumentFragment();
  const doc = tree.docs.find((d) => d.path === node.path);

  if (treeFilter && !matches(node.name)) {
    const hit = doc && doc.datasets.some((ds) => matches(ds.label));
    if (!hit) return frag;
  }

  if (doc) { frag.append(docNode(doc, depth)); return frag; }

  const el = rowEl(depth, 'tfile');
  el.append(chevron(false));
  const name = document.createElement('span');
  name.className = 'tname';
  name.textContent = node.name;
  el.append(name);
  el.title = node.path + '\n' + t('ui.click_to_open');
  el.addEventListener('click', async () => {
    setStatus(t('ui.opening', {name: node.name}));
    applyTree(await api.open_path(node.path));
  });
  frag.append(el);
  return frag;
}

/** Kaydedilmemis degisiklik noktasi — belge, tablo ve varyant ayni isareti
 *  tasir (9.25): belge "bir yerde" der, tablo ve varyant "burada". */
function dirtyDot() {
  const dot = document.createElement('span');
  dot.className = 'tdirty';
  dot.textContent = '•';
  dot.title = t('ui.unsaved');
  return dot;
}

function docNode(doc, depth) {
  const frag = document.createDocumentFragment();
  const key = 'doc:' + doc.id;
  const open = !collapsed.has(key);

  const el = rowEl(depth, 'tdoc' + (sel && sel.docId === doc.id ? ' in-path' : ''));
  el.append(chevron(open));
  const name = document.createElement('span');
  name.className = 'tname';
  name.textContent = doc.name;
  el.append(name);

  // 10.5.2 — kaydedilmemis degisiklik: ad ile sayinin ARASINDA nokta. Renk
  // tek basina yeterli isaret degil, bu yuzden ayri bir oge.
  if (doc.dirty) el.append(dirtyDot());

  const badge = document.createElement('span');
  badge.className = 'tcount';
  badge.textContent = doc.datasets.length;
  el.append(badge);

  // 10.5.2 — kaydedilmemis degisiklik varsa once sorulur (KB-5); soru
  // penceresi agaci kendisi tazeledigi icin `closeBtn`in dondurdugu yol
  // kullanilmaz.
  el.append(closeBtn(t('ui.close_doc'), () => closeDocAsked(doc)));

  el.title = doc.path;
  el.addEventListener('click', () => {
    open ? collapsed.add(key) : collapsed.delete(key);
    renderTree();
  });
  frag.append(el);

  if (!open) return frag;
  for (const ds of doc.datasets) {
    if (treeFilter && !matches(ds.label) && !matches(doc.name)) continue;
    frag.append(dsNode(doc, ds, depth + 1));
  }
  return frag;
}

function dsNode(doc, ds, depth) {
  const frag = document.createDocumentFragment();
  const key = 'ds:' + doc.id + '|' + ds.id;
  const hasVar = ds.variants && ds.variants.length > 0;
  const open = hasVar && !collapsed.has(key);
  const active = sel && sel.docId === doc.id && sel.dsId === ds.id && !sel.variantId;

  const el = rowEl(depth, 'tds' + (active ? ' active' : ''));
  if (hasVar) {
    const c = chevron(open);
    c.addEventListener('click', (e) => {
      e.stopPropagation();
      open ? collapsed.add(key) : collapsed.delete(key);
      renderTree();
    });
    el.append(c);
  } else {
    const s = document.createElement('span');
    s.className = 'chev spacer';
    el.append(s);
  }

  const name = document.createElement('span');
  name.className = 'tname';
  name.textContent = ds.label;
  // 10.6 — adi kaydedilmeden degisti: hucrelerle ayni isaret (sol cizgi).
  if (ds.edited) {
    name.classList.add('edited');
    name.title = t('ui.unsaved');
  }
  el.append(name);
  if (ds.dirty) el.append(dirtyDot());

  const sub = document.createElement('span');
  sub.className = 'tsub';
  sub.textContent = `${ds.rows}×${ds.cols}`;
  el.append(sub);

  el.title = `${ds.kind_label} · ${ds.id}`;
  el.addEventListener('click', () => select(doc.id, ds.id, null));
  // 10.6 — duzenleme kipinde cift tik tablonun adini duzenler. Kip kapaliyken
  // dinleyici hicbir sey yapmaz (`beginRename` kipi kendisi sinar).
  el.addEventListener('dblclick', () => beginRename(name, doc.id, ds.id, null));
  frag.append(el);

  if (open) {
    for (const v of ds.variants) {
      const va = sel && sel.docId === doc.id && sel.variantId === v.id;
      const ve = rowEl(depth + 1, 'tvar' + (va ? ' active' : ''));
      const sp = document.createElement('span');
      sp.className = 'chev spacer';
      ve.append(sp);
      const vn = document.createElement('span');
      vn.className = 'tname';
      vn.textContent = v.label;
      ve.append(vn);
      if (v.dirty) ve.append(dirtyDot());
      const vs = document.createElement('span');
      vs.className = 'tsub';
      vs.textContent = `${v.rows}×${v.cols}`;
      ve.append(vs);
      ve.title = t('ui.variant_hint');
      ve.addEventListener('click', () => select(doc.id, ds.id, v.id));
      frag.append(ve);
    }
  }
  return frag;
}
