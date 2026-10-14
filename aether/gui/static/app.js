/* Aether Desktop — application shell.
 * Menu, ribbon, project tree, property grid, dialogs, viewport wiring,
 * message manager, progress, scripting console and report windows. */
'use strict';

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const c of kids.flat()) {
    if (c == null || c === false) continue;
    n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
};
const icon = (id, cls) => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  if (cls) s.setAttribute('class', cls);
  const u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  u.setAttribute('href', '#' + id);
  s.appendChild(u);
  return s;
};
const fmtHz = f => f >= 1e9 ? (f / 1e9).toPrecision(6).replace(/\.?0+$/, '') + ' GHz'
  : f >= 1e6 ? (f / 1e6).toPrecision(6).replace(/\.?0+$/, '') + ' MHz'
  : f.toPrecision(4) + ' Hz';
const fmtLen = (m, u) => {
  const k = { m: 1, cm: 1e-2, mm: 1e-3, um: 1e-6, mil: 2.54e-5, in: 2.54e-2 }[u] || 1e-3;
  return String(Number((m / k).toPrecision(9))) + u;
};

/* ------------------------------------------------------------------ rpc */
let STATE = null;
let BUSY = false;
let ACTION_ERRORS = 0;

/* Every reply carries a full state snapshot, which is what keeps the tree,
   the property grid and the status bar honest. But a reply is a picture of
   the moment its request was *served*, and a selection made while it was in
   flight is newer than that picture. Stamping the selection lets a late reply
   refresh everything else without quietly undoing the click you just made. */
let SEL_EPOCH = 0;

async function rpc(method, params = {}) {
  const epoch = SEL_EPOCH;
  const r = await fetch('/api/rpc?token=' + encodeURIComponent(window.AETHER_TOKEN), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json',
      'X-Aether-Token': window.AETHER_TOKEN },
    body: JSON.stringify({ method, params })
  });
  const j = await r.json();
  if (j.state) {
    if (SEL_EPOCH !== epoch && STATE) j.state.selection = STATE.selection;
    STATE = j.state;
    renderAll();
  }
  if (!j.ok) throw new Error(j.error || 'command failed');
  return j.result;
}
async function guard(fn) {
  try { BUSY = true; setStatus('Working…', 'busy'); return await fn(); }
  catch (e) { ACTION_ERRORS++; toastError(e.message); return false; }
  finally { BUSY = false; refreshStatus(); }
}
function toastError(m) {
  setStatus(m, 'err');
  selectBottom('messages');
}

/* --------------------------------------------------------------- dialogs */
/* Dialogs are a stack, not a single panel.
   A dialog that opens another one -- Import CAD opening the file browser, and
   every Browse... button after it -- used to overwrite the one shared panel,
   so the parent was destroyed while it waited: picking a file left nothing to
   pick it into and the import quietly did nothing. Each dialog now owns its
   own element, the one on top is the only one that takes Escape or a backdrop
   click, and closing it reveals the parent exactly as it was left. */
const DIALOG_STACK = [];
let DIALOG_SEQ = 0;

function dialog({ title, body, width, ok = 'OK', cancel = 'Cancel', onOk,
                 buttons, onClose }) {
  const back = $('#modal-back');
  const id = ++DIALOG_SEQ;
  const d = el('div', { class: 'dialog' + (width === 'wide' ? ' wide' : '') });
  d.appendChild(el('h3', {}, title));
  const b = el('div', { class: 'body' });
  b.appendChild(body);
  d.appendChild(b);
  const foot = el('div', { class: 'foot' });
  // An explicit button set, for the questions that are not yes/no. "Save this
  // before it is discarded?" has three answers, and offering only two of them
  // is how unsaved work gets thrown away by someone who meant to keep it.
  if (buttons) {
    for (const spec of buttons)
      foot.appendChild(el('button', { class: spec.primary ? 'pri' : '',
        onclick: () => { const f = spec.onClick; close(spec.value); if (f) f(); } },
        spec.label));
    d.appendChild(foot);
    DIALOG_STACK.forEach(x => { x.node.hidden = true; });
    back.appendChild(d);
    back.classList.add('on');
    const entry0 = { id, node: d, close };
    DIALOG_STACK.push(entry0);
    setTimeout(() => { const p = d.querySelector('.foot .pri') ||
      d.querySelector('.foot button'); p && p.focus(); }, 30);
    let closed = false;
    function close(value) {
      const i = DIALOG_STACK.indexOf(entry0);
      if (i < 0) return;
      DIALOG_STACK.splice(i, 1);
      d.remove();
      const top = DIALOG_STACK[DIALOG_STACK.length - 1];
      if (top) top.node.hidden = false;
      else back.classList.remove('on');
      if (!closed) { closed = true; onClose && onClose(value); }
    }
    return { close, id, node: d };
  }
  if (cancel) foot.appendChild(el('button', { onclick: () => close() }, cancel));
  let btn = null;
  if (ok) {
    btn = el('button', { class: 'pri', onclick: async () => {
      if (btn.disabled) return;
      btn.disabled = true;                 // an async action must not re-enter
      try { const errorsBefore = ACTION_ERRORS; const r = onOk ? await onOk() : true; if (r !== false && errorsBefore === ACTION_ERRORS) close(); }
      catch (e) { toastError(e.message); }
      finally { if (btn) btn.disabled = false; }
    } }, ok);
    foot.appendChild(btn);
    setTimeout(() => btn && btn.focus(), 30);
  }
  d.appendChild(foot);

  // Only the top of the stack is interactive; the ones below stay in the DOM
  // (and keep their field values) but are hidden behind it.
  DIALOG_STACK.forEach(x => { x.node.hidden = true; });
  back.appendChild(d);
  back.classList.add('on');
  const entry = { id, node: d, close };
  DIALOG_STACK.push(entry);

  function close() {
    const i = DIALOG_STACK.indexOf(entry);
    if (i < 0) return;                     // already closed; a late async
    DIALOG_STACK.splice(i, 1);             // handler must not close twice
    d.remove();
    const top = DIALOG_STACK[DIALOG_STACK.length - 1];
    if (top) top.node.hidden = false;
    else back.classList.remove('on');
    onClose && onClose();
  }
  return { close, id, node: d };
}

function closeTopDialog() {
  const top = DIALOG_STACK[DIALOG_STACK.length - 1];
  if (top) top.close();
}
function closeAllDialogs() {
  while (DIALOG_STACK.length) closeTopDialog();
}

// One handler for the whole stack, installed once.
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && DIALOG_STACK.length) {
    e.stopPropagation();
    closeTopDialog();
  }
}, true);
$('#modal-back').addEventListener('click', e => {
  if (e.target === $('#modal-back')) closeTopDialog();
});

function field(label, input) {
  return el('div', { class: 'field' }, el('label', {}, label), input);
}
function inp(id, value = '', type = 'text', attrs = {}) {
  return el('input', Object.assign({ id, value, type }, attrs));
}
function sel(id, options, value) {
  const s = el('select', { id });
  for (const o of options) {
    const v = Array.isArray(o) ? o[0] : o;
    const t = Array.isArray(o) ? o[1] : o;
    const op = el('option', { value: v }, t);
    if (String(v) === String(value)) op.selected = true;
    s.appendChild(op);
  }
  return s;
}
function xyz(prefix, vals, unit) {
  return el('div', { class: 'row3' },
    inp(prefix + 'x', vals[0], 'text', { placeholder: 'X' }),
    inp(prefix + 'y', vals[1], 'text', { placeholder: 'Y' }),
    inp(prefix + 'z', vals[2], 'text', { placeholder: 'Z' }));
}
const g3 = p => [$('#' + p + 'x').value, $('#' + p + 'y').value, $('#' + p + 'z').value];
const gv = id => $('#' + id).value;
const gn = id => parseFloat($('#' + id).value);


/* ---------------------------------------------------------- file picker */
/* A real browse-and-select dialog. It lists the machine the solver runs on,
   which is the machine that will actually read or write the file — typing a
   path by hand is never required. The OS's own dialog is one click away for
   anyone who prefers it. */
const FP_STATE = { path: '', showHidden: false, history: [], last: {} };

function fmtSize(n) {
  if (n < 1024) return n + ' B';
  const u = ['KB', 'MB', 'GB', 'TB'];
  let v = n / 1024, i = 0;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return v.toFixed(1) + ' ' + u[i];
}
const fmtDate = t => t ? new Date(t * 1000).toLocaleString([], {
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit' }) : '';

async function filePicker(opt) {
  const mode = opt.mode || 'open';
  const kind = opt.kind || 'any';
  // Reopening the browser lands where you were last time, per file kind --
  // a CAD library and a project folder are rarely the same place.
  let dir = opt.path || FP_STATE.last[kind]
    || (await rpc('files.defaultDir', { hint: opt.hint || '' })).path;
  let selected = null;
  let listing = null;

  const places = el('div', { class: 'fp-places' });
  const crumbs = el('div', { class: 'fp-crumbs' });
  const list = el('div', { class: 'fp-list' });
  const back = el('button', { class: 'nav', title: 'Back',
    onclick: () => { const p = FP_STATE.history.pop(); if (p) go(p, true); } },
    icon('i-back'));
  const up = el('button', { class: 'nav', title: 'Parent folder',
    onclick: () => listing && listing.parent && go(listing.parent) }, icon('i-up'));
  // Editable in both modes: a full path can be typed or pasted, which is how
  // anyone who already knows where the file is gets there in one step.
  const nameIn = el('input', { id: 'fp-name', value: opt.filename || '',
    placeholder: mode === 'save' ? 'file name' : 'file name, or paste a full path' });
  const filterSel = el('select', { id: 'fp-filter' });
  const note = el('span', {});
  const sysBtn = el('button', {
    onclick: async () => {
      const r = await rpc('files.native', { mode, kind, title: opt.title || '',
        path: dir, filename: nameIn.value });
      if (r.ok && r.path) { finish(r.path); }
      else if (!r.ok) { note.className = 'err'; note.textContent = r.error; }
    } }, 'System dialog…');

  const body = el('div', {},
    el('div', { class: 'fp' }, places,
      el('div', { class: 'fp-main' },
        el('div', { class: 'fp-bar' }, back, up, crumbs), list)),
    el('div', { class: 'fp-foot' },
      el('label', {}, mode === 'save' ? 'Save as' : 'File'),
      nameIn, filterSel),
    el('div', { class: 'fp-note' }, note, sysBtn));

  let picked = false;
  const dlg = dialog({
    title: opt.title || (mode === 'save' ? 'Save As' : 'Open'),
    body, width: 'wide',
    ok: mode === 'save' ? 'Save' : 'Open',
    onOk: () => accept(),
    // Backing out of the browser is an answer too: a caller that has to save
    // before it can go on needs to hear "no file was chosen".
    onClose: () => { if (!picked) opt.onCancel && opt.onCancel(); }
  });

  function finish(path) {
    FP_STATE.last[kind] = dir;
    picked = true;
    dlg.close();
    opt.onPick && opt.onPick(path);
  }

  async function accept() {
    note.className = ''; note.textContent = '';
    const typed = nameIn.value.trim();
    if (mode === 'save') {
      if (!typed) { note.className = 'err'; note.textContent = 'Enter a file name.'; return false; }
      const r = await rpc('files.resolveSave',
        { directory: dir, filename: typed, kind });
      if (!r.ok) { note.className = 'err'; note.textContent = r.error; return false; }
      if (r.exists && !confirm(`${r.path}\n\nThis file already exists. Replace it?`))
        return false;
      finish(r.path);
      return false;
    }
    if (typed && (typed.includes('/') || typed.includes('\\'))) {
      // A pasted path: a folder is navigated to, a file is accepted directly.
      const r = await rpc('files.browse', { path: typed, kind,
        filter: parseInt(filterSel.value || '0', 10),
        showHidden: FP_STATE.showHidden });
      if (r.isFile) { dir = r.path; finish(r.filePath); return false; }
      if (r.error) { note.className = 'err'; note.textContent = r.error; return false; }
      FP_STATE.history.push(dir);
      listing = r; dir = r.path; selected = null; nameIn.value = '';
      render();
      return false;
    }
    if (!selected) { note.className = 'err'; note.textContent = 'Select a file.'; return false; }
    finish(selected);
    return false;
  }

  async function go(next, isBack) {
    if (!isBack && listing) FP_STATE.history.push(listing.path);
    listing = await rpc('files.browse',
      { path: next, kind, filter: parseInt(filterSel.value || '0', 10),
        showHidden: FP_STATE.showHidden });
    dir = listing.path;
    selected = null;
    if (mode !== 'save') nameIn.value = '';
    render();
  }

  function render() {
    back.disabled = !FP_STATE.history.length;
    up.disabled = !listing.parent;

    places.innerHTML = '';
    for (const p of listing.places) {
      const ic = p.kind === 'home' ? 'i-home' : p.kind === 'drive'
        ? 'i-drive' : 'i-folder';
      places.appendChild(el('button', {
        class: p.path === listing.path ? 'on' : '',
        title: p.path, onclick: () => go(p.path) }, icon(ic), p.name));
    }

    crumbs.innerHTML = '';
    listing.crumbs.forEach((c, i) => {
      if (i) crumbs.appendChild(el('span', { class: 'sep' }, '›'));
      crumbs.appendChild(el('button', { title: c.path,
        onclick: () => go(c.path) }, c.name));
    });

    list.innerHTML = '';
    list.appendChild(el('div', { class: 'fp-head' },
      el('span', {}, 'Name'), el('span', { style: 'text-align:right' }, 'Size'),
      el('span', { style: 'text-align:right' }, 'Modified')));
    if (listing.error) {
      list.appendChild(el('div', { class: 'fp-empty' },
        el('span', { style: 'color:var(--err)' }, listing.error)));
      return;
    }
    const rows = listing.dirs.concat(listing.files);
    if (!rows.length)
      list.appendChild(el('div', { class: 'fp-empty' },
        'No matching files in this folder.'));
    for (const r of rows) {
      const row = el('div', { class: 'fp-row', title: r.path },
        el('span', { class: 'nm' }, icon(r.dir ? 'i-folder' : 'i-file'), r.name),
        el('span', { class: 'sz' }, r.dir ? '' : fmtSize(r.size)),
        el('span', { class: 'dt' }, fmtDate(r.mtime)));
      row.onclick = () => {
        if (r.dir) return;
        selected = r.path;
        nameIn.value = r.name;
        list.querySelectorAll('.fp-row.sel').forEach(x => x.classList.remove('sel'));
        row.classList.add('sel');
      };
      row.ondblclick = () => r.dir ? go(r.path) : (selected = r.path, accept());
      list.appendChild(row);
    }
  }

  const first = await rpc('files.browse', { path: dir, kind,
    showHidden: false });
  listing = first;
  dir = first.path;
  filterSel.innerHTML = '';
  first.filters.forEach((f, i) => filterSel.appendChild(
    el('option', { value: String(i) }, f.label)));
  filterSel.value = '0';
  filterSel.onchange = () => go(dir, true);
  if (!first.native) sysBtn.style.display = 'none';
  nameIn.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); accept(); }
  });
  render();
  if (mode === 'save') setTimeout(() => { nameIn.focus(); nameIn.select(); }, 40);
}

/* ------------------------------------------------------------ modelling */
/* Names are proposed by the server, which knows the real model — including
   objects created from the console or loaded from a project file. The field
   is pre-filled so you can just press Create; clearing it is also fine, the
   server names the object either way. */
async function suggestName(kind, what, setup) {
  try {
    const r = await rpc('naming.suggest', { kind, what, setup: setup || '' });
    return r.name;
  } catch (e) { return ''; }
}
function autoName(inputId, kind, what, setup) {
  suggestName(kind, what, setup).then(n => {
    const f = $('#' + inputId);
    if (f && !f.value) { f.value = n; f.placeholder = n; }
  });
}

const U = () => (STATE?.design?.units) || 'mm';

async function dlgDraw(kind, picked) {
  if (!await ensureDesign()) return;
  const u = U();
  const mats = (window.MATERIALS || []).map(m => m.name);
  const body = el('div');
  // Values from two clicked points, when the draw started that way.
  const P = picked ? pickedGeometry(kind, picked, u) : null;
  const nameI = inp('d-name', '', 'text', { placeholder: 'auto' });
  const matI = sel('d-mat', mats.length ? mats : ['vacuum'], 'vacuum');
  body.appendChild(field('Name', nameI));
  autoName('d-name', 'shape', kind);
  body.appendChild(field('Material', matI));
  if (kind === 'box') {
    body.appendChild(field('Position', xyz('p', P ? P.position
      : ['0' + u, '0' + u, '0' + u])));
    body.appendChild(field('X / Y / Z size', xyz('s', P ? P.size
      : ['10' + u, '5' + u, '1' + u])));
  } else if (kind === 'cylinder' || kind === 'cone') {
    body.appendChild(field('Center', xyz('p', P ? P.position
      : ['0' + u, '0' + u, '0' + u])));
    body.appendChild(field('Axis', sel('d-axis', [['z', 'Z'], ['x', 'X'], ['y', 'Y']], 'z')));
    if (kind === 'cylinder') body.appendChild(field('Radius', inp('d-r', '2' + u)));
    else {
      body.appendChild(field('Bottom radius', inp('d-r1', '3' + u)));
      body.appendChild(field('Top radius', inp('d-r2', '0' + u)));
    }
    body.appendChild(field('Height', inp('d-h', '10' + u)));
  } else if (kind === 'sphere') {
    body.appendChild(field('Center', xyz('p', ['0' + u, '0' + u, '0' + u])));
    body.appendChild(field('Radius', inp('d-r', '5' + u)));
  } else if (kind === 'torus') {
    body.appendChild(field('Center', xyz('p', ['0' + u, '0' + u, '0' + u])));
    body.appendChild(field('Axis', sel('d-axis', [['z', 'Z'], ['x', 'X'], ['y', 'Y']], 'z')));
    body.appendChild(field('Major radius', inp('d-r1', '8' + u)));
    body.appendChild(field('Minor radius', inp('d-r2', '2' + u)));
  } else if (kind === 'rectangle') {
    body.appendChild(field('Position', xyz('p', P ? P.position
      : ['0' + u, '0' + u, '0' + u])));
    body.appendChild(field('Plane', sel('d-plane',
      [['xy', 'XY'], ['yz', 'YZ'], ['xz', 'XZ']], (P && P.plane) || 'xy')));
    body.appendChild(field('Width / Height', el('div', { class: 'row3' },
      inp('d-w', P ? P.width : '10' + u),
      inp('d-hh', P ? P.height : '5' + u))));
  }
  if (kind === 'cylinder' && P) {
    setTimeout(() => {
      const r = $('#d-r'), h = $('#d-h');
      if (r) r.value = P.radius;
      if (h) h.value = P.depth;
    }, 0);
  }
  if (P) body.appendChild(el('div', { class: 'hint' },
    'Filled in from the two points you clicked — correct any of them here.'));
  body.appendChild(el('div', { class: 'hint' },
    'Values accept units: 10mm, 0.4in, 25mil, 1.2e-3m.'));
  const axisVec = a => ({ x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }[a] || [0, 0, 1]);

  dialog({
    title: 'Create ' + kind.charAt(0).toUpperCase() + kind.slice(1),
    body, ok: 'Create',
    onOk: async () => {
      const p = {};
      if (kind === 'box') { p.position = g3('p'); p.size = g3('s'); }
      else if (kind === 'sphere') { p.center = g3('p'); p.radius = gv('d-r'); }
      else if (kind === 'cylinder') {
        p.center = g3('p'); p.radius = gv('d-r'); p.height = gv('d-h');
        p.axis = axisVec(gv('d-axis'));
      } else if (kind === 'cone') {
        p.center = g3('p'); p.r1 = gv('d-r1'); p.r2 = gv('d-r2');
        p.height = gv('d-h'); p.axis = axisVec(gv('d-axis'));
      } else if (kind === 'torus') {
        p.center = g3('p'); p.rMajor = gv('d-r1'); p.rMinor = gv('d-r2');
        p.axis = axisVec(gv('d-axis'));
      } else if (kind === 'rectangle') {
        p.position = g3('p'); p.plane = gv('d-plane');
        p.size = [gv('d-w'), gv('d-hh')];
      }
      await guard(() => rpc('modeler.draw',
        { shape: kind, name: gv('d-name'), material: gv('d-mat'), params: p }));
      await refreshGeometry(true);
    }
  });
}

/* Two clicked points into the numbers a shape needs. The second point is the
   opposite corner, so a box gets a depth of its own: an outline drawn flat on
   a plane has none, and a zero-height box is not a body. */
function pickedGeometry(kind, pick, u) {
  const a = pick.from, b = pick.to;
  const lo = [0, 1, 2].map(k => Math.min(a[k], b[k]));
  const hi = [0, 1, 2].map(k => Math.max(a[k], b[k]));
  const size = [0, 1, 2].map(k => hi[k] - lo[k]);
  const flat = size.map(v => v < 1e-12);
  const span = Math.max(size[0], size[1], size[2], 1e-6);
  const depth = span * 0.1;
  const val = v => fmtLen(v, u);
  const out = {
    position: lo.map(val),
    size: size.map((v, k) => val(flat[k] ? depth : v)),
    width: val(size[0] || depth),
    height: val(size[1] || depth),
    depth: val(size[2] || depth),
    radius: val(Math.hypot(b[0] - a[0], b[1] - a[1]) || depth),
    plane: flat[2] ? 'xy' : flat[0] ? 'yz' : flat[1] ? 'xz' : 'xy'
  };
  if (kind === 'cylinder' || kind === 'cone' || kind === 'sphere')
    out.position = a.map(val);           // these are centred, not cornered
  return out;
}

function dlgBoolean() {
  const objs = (STATE.design?.objects || []).map(o => o.name);
  if (objs.length < 2) return toastError('Two or more objects are required');
  const body = el('div');
  body.appendChild(field('Operation', sel('b-op',
    [['subtract', 'Subtract'], ['unite', 'Unite'], ['intersect', 'Intersect']],
    'subtract')));
  body.appendChild(field('Blank part', sel('b-blank', objs, STATE.selection[0] || objs[0])));
  const list = el('select', { id: 'b-tools', multiple: 'multiple', size: Math.min(8, objs.length) });
  objs.forEach(o => list.appendChild(el('option', { value: o }, o)));
  body.appendChild(field('Tool parts', list));
  body.appendChild(el('div', { class: 'check' },
    el('input', { type: 'checkbox', id: 'b-keep' }),
    el('label', { for: 'b-keep' }, 'Clone (keep) tool objects')));
  dialog({ title: 'Boolean', body, ok: 'Apply', onOk: async () => {
    const tools = Array.from($('#b-tools').selectedOptions).map(o => o.value)
      .filter(t => t !== gv('b-blank'));
    if (!tools.length) throw new Error('select at least one tool part');
    await guard(() => rpc('modeler.boolean', { op: gv('b-op'),
      blank: gv('b-blank'), tools, keep: $('#b-keep').checked }));
    await refreshGeometry(true);
  }});
}

/* --------------------------------------------------- edit / arrange ops */
/* Every operation here works on the current selection, the way a modeller
   does: pick objects in the viewport or the tree, then act. The dialog still
   shows the full object list so nothing is a dead end when the selection is
   empty, and every one of them is a single undo step. */

const objNames = () => (STATE?.design?.objects || []).map(o => o.name);

function objectList(id, preset) {
  const objs = objNames();
  const chosen = new Set((preset && preset.length ? preset : STATE.selection) || []);
  const list = el('select', { id, multiple: 'multiple',
    size: Math.min(8, Math.max(3, objs.length)) });
  objs.forEach(o => {
    const op = el('option', { value: o }, o);
    if (chosen.has(o)) op.selected = true;
    list.appendChild(op);
  });
  return list;
}
const picked = id => Array.from($('#' + id).selectedOptions).map(o => o.value);

function dlgTransform(op0) {
  if (!objNames().length) return toastError('No objects to transform');
  const u = U();
  const body = el('div');
  body.appendChild(field('Objects', objectList('t-objs')));
  body.appendChild(field('Operation', sel('t-op',
    [['move', 'Move'], ['rotate', 'Rotate'], ['scale', 'Scale'],
     ['mirror', 'Mirror']], op0 || 'move')));
  const dyn = el('div', { id: 't-dyn' });
  body.appendChild(dyn);
  const build = () => {
    dyn.innerHTML = '';
    const op = gv('t-op');
    if (op === 'move') {
      dyn.appendChild(field('Translation vector',
        xyz('t', ['0' + u, '0' + u, '0' + u])));
    } else if (op === 'rotate') {
      dyn.appendChild(field('Axis', sel('t-axis',
        [['z', 'Z'], ['x', 'X'], ['y', 'Y']], 'z')));
      dyn.appendChild(field('Angle', inp('t-ang', '90deg')));
      dyn.appendChild(field('Axis point', xyz('to', ['0' + u, '0' + u, '0' + u])));
    } else if (op === 'scale') {
      dyn.appendChild(field('Scale X / Y / Z', xyz('t', ['1', '1', '1'])));
    } else {
      dyn.appendChild(field('Mirror plane normal', xyz('t', ['0', '0', '1'])));
      dyn.appendChild(field('Plane point', xyz('to', ['0' + u, '0' + u, '0' + u])));
    }
  };
  setTimeout(() => { $('#t-op').onchange = build; build(); }, 0);
  dialog({ title: 'Arrange', body, ok: 'Apply', onOk: async () => {
    const names = picked('t-objs');
    if (!names.length) throw new Error('select at least one object');
    const op = gv('t-op'); const p = {};
    if (op === 'move') { const v = g3('t'); p.dx = v[0]; p.dy = v[1]; p.dz = v[2]; }
    else if (op === 'rotate') {
      p.axis = gv('t-axis'); p.angle = gv('t-ang'); p.origin = g3('to');
    } else if (op === 'scale') {
      const v = g3('t').map(Number); p.sx = v[0]; p.sy = v[1]; p.sz = v[2];
    } else { p.normal = g3('t').map(Number); p.origin = g3('to'); }
    await guard(() => rpc('modeler.transform', { names, op, params: p }));
    await refreshGeometry(false);
  }});
}

/* Duplicate — the three patterns HFSS offers: along a line, around an axis,
   and mirrored. `count` is the total including the original, so 4 around a
   full circle means quadrants. */
function dlgDuplicate(mode0) {
  if (!objNames().length) return toastError('No objects to duplicate');
  const u = U();
  const body = el('div');
  body.appendChild(field('Objects', objectList('q-objs')));
  body.appendChild(field('Pattern', sel('q-mode',
    [['line', 'Along Line'], ['axis', 'Around Axis'], ['mirror', 'Mirror']],
    mode0 || 'line')));
  const dyn = el('div', { id: 'q-dyn' });
  body.appendChild(dyn);
  const build = () => {
    dyn.innerHTML = '';
    const m = gv('q-mode');
    if (m === 'line') {
      dyn.appendChild(field('Step vector', xyz('q', ['10' + u, '0' + u, '0' + u])));
      dyn.appendChild(field('Total number', inp('q-n', '2', 'number',
        { min: '2', step: '1' })));
    } else if (m === 'axis') {
      dyn.appendChild(field('Axis', sel('q-axis',
        [['z', 'Z'], ['x', 'X'], ['y', 'Y']], 'z')));
      dyn.appendChild(field('Axis point', xyz('qo', ['0' + u, '0' + u, '0' + u])));
      dyn.appendChild(field('Total number', inp('q-n', '4', 'number',
        { min: '2', step: '1' })));
      dyn.appendChild(field('Angle', inp('q-ang', '360deg')));
      dyn.appendChild(el('div', { class: 'check' },
        el('input', { type: 'checkbox', id: 'q-full', checked: 'checked' }),
        el('label', { for: 'q-full' },
          'Angle spans the whole pattern (unchecked: angle per step)')));
    } else {
      dyn.appendChild(field('Mirror plane normal', xyz('q', ['0', '0', '1'])));
      dyn.appendChild(field('Plane point', xyz('qo', ['0' + u, '0' + u, '0' + u])));
    }
    dyn.appendChild(el('div', { class: 'check' },
      el('input', { type: 'checkbox', id: 'q-attach' }),
      el('label', { for: 'q-attach' },
        'Attach copies to the original (unite into one object)')));
  };
  setTimeout(() => { $('#q-mode').onchange = build; build(); }, 0);
  dialog({ title: 'Duplicate', body, ok: 'Create', onOk: async () => {
    const names = picked('q-objs');
    if (!names.length) throw new Error('select at least one object');
    const mode = gv('q-mode'); const p = {};
    let count = 2;
    if (mode === 'line') { p.vector = g3('q'); count = parseInt(gv('q-n'), 10) || 2; }
    else if (mode === 'axis') {
      p.axis = gv('q-axis'); p.origin = g3('qo'); p.angle = gv('q-ang');
      p.fullCircle = $('#q-full').checked;
      count = parseInt(gv('q-n'), 10) || 2;
    } else { p.normal = g3('q').map(Number); p.origin = g3('qo'); }
    await guard(() => rpc('modeler.duplicate', { names, mode, count, params: p,
      attach: $('#q-attach').checked }));
    await refreshGeometry(false);
  }});
}

/* Face modelling. Pick a face (F), then give it a distance: sweeping adds
   material along the face normal, moving drags the face itself, and a
   negative distance cuts into the body. */
function dlgFaceOp(op) {
  if (!FACE_PICKS.length)
    return toastError('Pick a face first: press F, then click a face');
  const u = U();
  const objs = [...new Set(FACE_PICKS.map(f => f.object))];
  if (objs.length > 1)
    return toastError('Pick faces on one object at a time');
  const body = el('div');
  const a = FACE_PICKS.reduce((t, f) => t + (f.area || 0), 0);
  body.appendChild(field('Faces', el('div', { class: 'hint',
    style: 'margin:0' },
    `${FACE_PICKS.length} face(s) on ${objs[0]} — `
    + `${(a * 1e6).toPrecision(5)} mm²`)));
  body.appendChild(field('Distance along normal', inp('fo-d', '1' + u)));
  if (op === 'sweep') {
    body.appendChild(field('New object name',
      inp('fo-name', '', 'text', { placeholder: objs[0] + '_Sweep' })));
  }
  body.appendChild(el('div', { class: 'hint' }, op === 'sweep'
    ? 'Sweeps the face along its own normal into a NEW object, and leaves the '
      + 'body the face belongs to exactly as it is — so the face can be given '
      + 'its own material, boundary or port. To grow the body itself, use '
      + 'Move Faces.'
    : 'Moves the face along its own normal: the body grows to follow it, and '
      + 'a negative distance trims the body back instead. Nothing new is '
      + 'created — use Sweep Face Along Normal for that.'));
  dialog({ title: op === 'sweep' ? 'Sweep Face Along Normal' : 'Move Faces',
    body, ok: 'Apply', onOk: async () => {
      await guard(() => rpc('modeler.faceOperation',
        { op, distance: gv('fo-d'), faces: FACE_PICKS,
          newName: op === 'sweep' ? gv('fo-name') : '' }));
      FACE_PICKS = [];
      VP.setFaceSelection([]);
      await refreshGeometry(false);
      refreshStatus();
    } });
}

/* --------------------------------------------------------- clipboard ops */
async function editCopy(cut) {
  const names = STATE.selection || [];
  if (!names.length) return toastError('Select an object first');
  await guard(() => rpc('modeler.copy', { names, cut }));
  if (cut) await refreshGeometry(false);
}
async function editPaste() {
  if (!STATE.history?.clipboard) return toastError('The clipboard is empty');
  await guard(() => rpc('modeler.paste', {}));
  await refreshGeometry(false);
}
function dlgPasteOffset() {
  if (!STATE.history?.clipboard) return toastError('The clipboard is empty');
  const u = U();
  const body = el('div');
  body.appendChild(field('Paste offset', xyz('pv', ['10' + u, '0' + u, '0' + u])));
  body.appendChild(el('div', { class: 'hint' },
    STATE.history.clipboard + ' object(s) on the clipboard.'));
  dialog({ title: 'Paste at Offset', body, ok: 'Paste', onOk: async () => {
    await guard(() => rpc('modeler.paste', { offset: g3('pv') }));
    await refreshGeometry(false);
  }});
}
async function editUndo() {
  if (!STATE.history?.canUndo) return;
  await guard(() => rpc('edit.undo'));
  await refreshGeometry(false);
}
async function editRedo() {
  if (!STATE.history?.canRedo) return;
  await guard(() => rpc('edit.redo'));
  await refreshGeometry(false);
}

/* --------------------------------------------------- selector sub-dialog */
function selectorFields(prefix, opts = {}) {
  const u = U();
  const wrap = el('fieldset', {}, el('legend', {}, 'Geometry selection'));
  const kinds = [['faces', `Picked faces (${FACE_PICKS.length} selected)`],
                 ['plane', 'Plane (X/Y/Z = value)'],
                 ['bboxface', 'Bounding-box face'],
                 ['box', 'Box region'],
                 ['object', 'Faces of an object'],
                 ['outer', 'All outer faces'],
                 ['outerExceptPorts', 'All outer faces except ports']];
  // Faces picked in the viewport are the natural target when there are any,
  // which is how an assignment normally starts: pick, then assign.
  wrap.appendChild(field('Assign to', sel(prefix + 'kind',
    opts.only ? kinds.filter(k => opts.only.includes(k[0])) : kinds,
    FACE_PICKS.length ? 'faces' : (opts.default || 'plane'))));
  const dyn = el('div', { id: prefix + 'dyn' });
  wrap.appendChild(dyn);
  const objs = (STATE.design?.objects || []).map(o => o.name);
  const build = () => {
    dyn.innerHTML = '';
    const k = gv(prefix + 'kind');
    if (k === 'plane') {
      dyn.appendChild(field('Axis', sel(prefix + 'axis',
        [['x', 'X'], ['y', 'Y'], ['z', 'Z']], 'z')));
      dyn.appendChild(field('Value', inp(prefix + 'val', '0' + u)));
    } else if (k === 'bboxface') {
      dyn.appendChild(field('Face', sel(prefix + 'face',
        ['+x', '-x', '+y', '-y', '+z', '-z'], '+z')));
    } else if (k === 'box') {
      dyn.appendChild(field('Corner 1', xyz(prefix + 'lo', ['0' + u, '0' + u, '0' + u])));
      dyn.appendChild(field('Corner 2', xyz(prefix + 'hi', ['10' + u, '10' + u, '10' + u])));
    } else if (k === 'object') {
      dyn.appendChild(field('Object', sel(prefix + 'obj', objs.length ? objs : ['—'],
        STATE.selection[0])));
    } else if (k === 'faces') {
      if (!FACE_PICKS.length) {
        dyn.appendChild(el('div', { class: 'hint err' },
          'No face is picked. Switch to face mode (F) and click a face.'));
      } else {
        const a = FACE_PICKS.reduce((t, f) => t + (f.area || 0), 0);
        dyn.appendChild(el('div', { class: 'hint' },
          FACE_PICKS.map(f => f.object).filter((v, i, x) => x.indexOf(v) === i)
            .join(', ') + ` — ${FACE_PICKS.length} face(s), `
          + `${(a * 1e6).toPrecision(5)} mm² total`));
      }
    }
  };
  setTimeout(() => { $('#' + prefix + 'kind').onchange = build; build(); }, 0);
  wrap.read = () => {
    const k = gv(prefix + 'kind');
    if (k === 'plane') return { kind: 'plane', axis: gv(prefix + 'axis'), value: gv(prefix + 'val') };
    if (k === 'bboxface') return { kind: 'bboxface', face: gv(prefix + 'face') };
    if (k === 'box') return { kind: 'box', lo: g3(prefix + 'lo'), hi: g3(prefix + 'hi') };
    if (k === 'object') return { kind: 'object', objects: [gv(prefix + 'obj')] };
    if (k === 'faces') {
      if (!FACE_PICKS.length)
        throw new Error('pick a face first: press F, then click one');
      return { kind: 'faces', faces: FACE_PICKS };
    }
    return { kind: k };
  };
  return wrap;
}

function dlgBoundary() {
  const body = el('div');
  body.appendChild(field('Name', inp('bn-name', '', 'text',
    { placeholder: 'auto' })));
  body.appendChild(field('Type', sel('bn-type', [
    ['pec', 'Perfect E (PEC)'], ['pmc', 'Perfect H (PMC)'],
    ['radiation', 'Radiation'], ['finite_cond', 'Finite Conductivity'],
    ['impedance', 'Impedance'], ['lumped_rlc', 'Lumped RLC'],
    ['symmetry_e', 'Symmetry — Perfect E'], ['symmetry_h', 'Symmetry — Perfect H']],
    'pec')));
  const s = selectorFields('bs-', { default: 'outerExceptPorts' });
  body.appendChild(s);
  const extra = el('div', { id: 'bn-extra' });
  body.appendChild(extra);
  let autoNamed = '';
  const build = () => {
    extra.innerHTML = '';
    const t = gv('bn-type');
    // keep the suggested name in step with the chosen type, but never
    // overwrite a name the user typed
    suggestName('boundary', t).then(n => {
      const f = $('#bn-name');
      if (f && (!f.value || f.value === autoNamed)) { f.value = n; autoNamed = n; }
    });
    if (t === 'finite_cond') {
      const mats = (window.MATERIALS || []).filter(m => m.kind === 'conductor')
        .map(m => m.name);
      extra.appendChild(field('Conductor', sel('bn-mat', mats.length ? mats : ['copper'], 'copper')));
      extra.appendChild(field('Thickness', inp('bn-th', '')));
      extra.appendChild(field('Roughness', inp('bn-ro', '0' + U())));
    } else if (t === 'impedance') {
      extra.appendChild(field('Resistance [Ω/sq]', inp('bn-R', '377')));
      extra.appendChild(field('Reactance [Ω/sq]', inp('bn-X', '0')));
    } else if (t === 'lumped_rlc') {
      extra.appendChild(field('R [Ω]', inp('bn-R', '50')));
      extra.appendChild(field('L [H]', inp('bn-L', '0')));
      extra.appendChild(field('C [F]', inp('bn-C', '0')));
      extra.appendChild(el('div', { class: 'check' },
        el('input', { type: 'checkbox', id: 'bn-par', checked: 'checked' }),
        el('label', { for: 'bn-par' }, 'Parallel combination')));
    }
  };
  setTimeout(() => { $('#bn-type').onchange = build; build(); }, 0);
  dialog({ title: 'Assign Boundary', body, ok: 'Assign', onOk: async () => {
    const t = gv('bn-type'); const p = {};
    if (t === 'finite_cond') {
      p.material = gv('bn-mat');
      if (gv('bn-th')) p.thickness = gv('bn-th');
      p.roughness = gv('bn-ro') || 0;
    } else if (t === 'impedance') { p.R = gn('bn-R'); p.X = gn('bn-X'); }
    else if (t === 'lumped_rlc') {
      p.R = gn('bn-R'); p.L = gn('bn-L'); p.C = gn('bn-C');
      p.parallel = $('#bn-par').checked;
    }
    await guard(() => rpc('boundary.assign',
      { type: t, name: gv('bn-name'), selector: s.read(), params: p }));
    await refreshAssignments();
  }});
}

function dlgExcitation(kind) {
  const u = U();
  const body = el('div');
  body.appendChild(field('Name', inp('ex-name', '', 'text',
    { placeholder: 'auto' })));
  autoName('ex-name', 'port', kind);
  const s = selectorFields('xs-', { default: 'plane' });
  body.appendChild(s);
  if (kind === 'wave') {
    body.appendChild(field('Number of modes', inp('ex-modes', '1', 'number',
      { min: 1, max: 8 })));
    body.appendChild(field('De-embed distance', inp('ex-de', '0' + u)));
    body.appendChild(field('Renormalise to [Ω]', inp('ex-renorm', '',
      'text', { placeholder: 'blank = keep modal Z' })));
  } else {
    body.appendChild(field('Impedance [Ω]', inp('ex-z', '50')));
    body.appendChild(field('Field direction', xyz('exd', ['0', '0', '1'])));
  }
  const useLine = el('input', { type: 'checkbox', id: 'ex-useline' });
  body.appendChild(el('div', { class: 'check' }, useLine,
    el('label', { for: 'ex-useline' }, 'Define an integration line')));
  const lineBox = el('div', { id: 'ex-linebox' });
  body.appendChild(lineBox);
  useLine.onchange = () => {
    lineBox.innerHTML = '';
    if (useLine.checked) {
      lineBox.appendChild(field('Line start', xyz('exs', ['0' + u, '0' + u, '0' + u])));
      lineBox.appendChild(field('Line end', xyz('exe', ['0' + u, '0' + u, '1' + u])));
    }
  };
  body.appendChild(el('div', { class: 'hint' },
    kind === 'wave'
      ? 'A wave port solves the 2-D modes of its cross-section. The integration line turns the modal wave impedance into the line impedance V²/2P — needed for TEM lines such as coax or microstrip.'
      : 'A lumped port drives a uniform field along the given direction and terminates in the stated impedance.'));
  dialog({ title: kind === 'wave' ? 'Assign Wave Port' : 'Assign Lumped Port',
    body, ok: 'Assign', onOk: async () => {
      const p = {};
      if (kind === 'wave') {
        p.modes = parseInt(gv('ex-modes')) || 1;
        p.deembed = gv('ex-de') || 0;
        if (gv('ex-renorm')) p.renorm = parseFloat(gv('ex-renorm'));
      } else {
        p.impedance = parseFloat(gv('ex-z'));
        p.direction = g3('exd').map(Number);
      }
      if ($('#ex-useline').checked) p.line = [g3('exs'), g3('exe')];
      await guard(() => rpc('excitation.assign',
        { kind, name: gv('ex-name'), selector: s.read(), params: p }));
      await refreshAssignments();
    }});
}

function dlgSetup() {
  const eigen = STATE.design?.solutionType === 'eigenmode';
  const body = el('div');
  body.appendChild(field('Name', inp('su-name', '', 'text',
    { placeholder: 'auto' })));
  autoName('su-name', 'setup');
  if (eigen) {
    body.appendChild(el('fieldset', {}, el('legend', {}, 'Eigenmode search'),
      field('Number of modes', inp('su-nm', '3', 'number', { min: 1, max: 50 })),
      field('Minimum frequency', inp('su-fmin', '0Hz')),
      field('Maximum Δf per pass', inp('su-df', '0.02', 'number',
        { step: '0.001' }))));
    body.appendChild(field('Mesh seed frequency', inp('su-f', '10GHz')));
    body.appendChild(el('fieldset', {}, el('legend', {}, 'Adaptive solutions'),
      field('Maximum passes', inp('su-mp', '6', 'number', { min: 1, max: 30 })),
      field('Basis order', sel('su-bo', [[1, '1st order (Whitney, 6 DOF/tet)'],
        [2, '2nd order (20 DOF/tet)']], 2))));
    body.appendChild(el('div', { class: 'hint' },
      'Finds the lowest resonances above the minimum frequency (0 = from the ' +
      'bottom) and their Q. Passes refine the mesh until no mode moves by more ' +
      'than Δf. Open (radiation) boundaries are not supported here.'));
    return dialog({ title: 'Add Eigenmode Setup', body, ok: 'OK', onOk: () =>
      guard(() => rpc('analysis.addSetup', { name: gv('su-name'),
        frequency: gv('su-f'), maxPasses: gn('su-mp'), deltaS: 0.02,
        basisOrder: parseInt(gv('su-bo')), nModes: gn('su-nm'),
        minFrequency: gv('su-fmin'), deltaF: gn('su-df') })) });
  }
  body.appendChild(field('Solution frequency', inp('su-f', '10GHz')));
  body.appendChild(el('fieldset', {}, el('legend', {}, 'Adaptive solutions'),
    field('Maximum passes', inp('su-mp', '6', 'number', { min: 1, max: 30 })),
    field('Maximum ΔS', inp('su-ds', '0.02', 'number', { step: '0.001' })),
    field('Basis order', sel('su-bo', [[1, '1st order (Whitney, 6 DOF/tet)'],
      [2, '2nd order (20 DOF/tet)']], 1))));
  body.appendChild(el('div', { class: 'hint' },
    'Adaptive passes refine where the tangential-H jump is largest and stop when max|ΔS| between passes falls below the target.'));
  dialog({ title: 'Add Solution Setup', body, ok: 'OK', onOk: () =>
    guard(() => rpc('analysis.addSetup', { name: gv('su-name'),
      frequency: gv('su-f'), maxPasses: gn('su-mp'), deltaS: gn('su-ds'),
      basisOrder: parseInt(gv('su-bo')) })) });
}

function dlgSweep(setupName) {
  if (STATE.design?.solutionType === 'eigenmode')
    return toastError('An eigenmode setup has no frequency sweep — it solves for the resonances');
  const setups = (STATE.design?.setups || []).map(s => s.name);
  if (!setups.length) return toastError('Add a solution setup first');
  const body = el('div');
  body.appendChild(field('Setup', sel('sw-setup', setups, setupName || setups[0])));
  body.appendChild(field('Name', inp('sw-name', '', 'text',
    { placeholder: 'auto' })));
  const reName = () => suggestName('sweep', '', gv('sw-setup')).then(n => {
    const f = $('#sw-name'); if (f) { f.value = n; f.placeholder = n; }
  });
  setTimeout(() => { reName(); $('#sw-setup').onchange = reName; }, 0);
  body.appendChild(field('Sweep type', sel('sw-kind',
    [['discrete', 'Discrete'], ['interpolating', 'Interpolating'], ['fast', 'Fast']],
    'discrete')));
  body.appendChild(field('Start', inp('sw-a', '8GHz')));
  body.appendChild(field('Stop', inp('sw-b', '12GHz')));
  body.appendChild(field('Spacing', sel('sw-sp',
    [['linear', 'Linear count'], ['log', 'Logarithmic'], ['single', 'Single point']], 'linear')));
  body.appendChild(field('Points', inp('sw-n', '41', 'number', { min: 1 })));
  // Interpolating / Fast solve only some frequencies and reconstruct the rest;
  // these two say how closely and how many full solves that may take.
  const adv = el('div', { id: 'sw-adv' });
  adv.appendChild(field('Error tolerance (|ΔS|)', inp('sw-tol', '0.001', 'number',
    { min: 0, max: 1, step: 'any' })));
  adv.appendChild(field('Max solutions', inp('sw-max', '100', 'number', { min: 4 })));
  adv.appendChild(el('div', { class: 'hint' },
    'Interpolating fits a rational model through adaptively chosen solves; ' +
    'Fast projects the full operator onto a reduced basis. Sweeps shorter ' +
    'than 7 points are always solved point by point.'));
  body.appendChild(adv);
  const showAdv = () => { adv.style.display = gv('sw-kind') === 'discrete' ? 'none' : ''; };
  setTimeout(() => { showAdv(); $('#sw-kind').onchange = showAdv; }, 0);
  dialog({ title: 'Add Frequency Sweep', body, ok: 'OK', onOk: () =>
    guard(() => rpc('analysis.addSweep', { setup: gv('sw-setup'),
      name: gv('sw-name'), kind: gv('sw-kind'), start: gv('sw-a'),
      stop: gv('sw-b'), count: gn('sw-n'), spacing: gv('sw-sp'),
      tolerance: gv('sw-kind') === 'discrete' ? null : gv('sw-tol'),
      maxPoints: gv('sw-kind') === 'discrete' ? null : gv('sw-max') })) });
}

async function dlgValidate() {
  const r = await rpc('analysis.validate');
  const body = el('div');
  for (const c of r.checks) {
    body.appendChild(el('div', { class: 'valid-row' },
      el('span', { class: 'st ' + (c.ok ? 'ok' : 'no') }, c.ok ? '✓' : '✕'),
      el('span', {}, c.name), el('span', { class: 'd' }, c.detail)));
  }
  if (r.errors.length)
    body.appendChild(el('div', { class: 'hint', style: 'color:var(--err);margin-top:10px' },
      r.errors.join(' · ')));
  dialog({ title: 'Validation Check', body, ok: null, cancel: 'Close' });
}

function dlgAnalyze() {
  const setups = (STATE.design?.setups || []).map(s => s.name);
  if (!setups.length) return toastError('Add a solution setup first');
  const body = el('div');
  body.appendChild(field('Setup', sel('an-setup', setups, setups[0])));
  body.appendChild(el('div', { class: 'check' },
    el('input', { type: 'checkbox', id: 'an-adapt', checked: 'checked' }),
    el('label', { for: 'an-adapt' }, 'Run adaptive passes')));
  // A far field is computed from the saved near field on the radiation
  // boundary, so a model that has one almost always wants the fields kept.
  const hasRad = (STATE.design?.boundaries || []).some(b => b.type === 'radiation');
  const fieldsBox = el('input', { type: 'checkbox', id: 'an-fields' });
  if (hasRad || STATE.design?.solutionType === 'eigenmode') fieldsBox.checked = true;
  body.appendChild(el('div', { class: 'check' }, fieldsBox,
    el('label', { for: 'an-fields' },
      'Save fields (enables field overlay' + (hasRad ? ' and far-field patterns' : '') + ')')));
  dialog({ title: 'Analyze', body, ok: 'Start', onOk: async () => {
    selectBottom('progress');
    await rpc('analysis.analyze', { setup: gv('an-setup'),
      adaptive: $('#an-adapt').checked, save_fields: $('#an-fields').checked });
    pollJob();
  }});
}

/* Saving, as a promise that resolves to whether the file was actually
   written. Everything that has to save *before* doing something else — the
   Save button in the unsaved-changes prompt, most of all — needs to know
   whether the user went through with it or backed out of the file browser. */
function saveProject(force) {
  const cur = STATE.project.path || '';
  if (cur && !force) {                    // Ctrl+S on a project with a file
    return guard(() => rpc('project.save', { path: cur }))
      .then(r => r !== false);
  }
  return saveProjectAs();
}

function saveProjectAs() {
  return new Promise(resolve => {
    let done = false;
    const cur = STATE.project.path || '';
    filePicker({
      mode: 'save', kind: 'project', title: 'Save Project As',
      hint: cur,
      path: cur ? cur.replace(/[\\/][^\\/]*$/, '') : '',
      filename: cur.split(/[\\/]/).pop()
        || ((STATE.project.name || 'Project1') + '.aedt'),
      onPick: async (path) => {
        done = true;
        const ok = await guard(() => rpc('project.save', { path }));
        resolve(ok !== false);
      },
      onCancel: () => { if (!done) resolve(false); }
    });
  });
}

/* The question every desktop application asks before it throws work away.
   Three answers, not two: save it, drop it, or stay where you are. The old
   prompt offered only "discard or cancel", so keeping the work meant
   cancelling, saving by hand and starting the command again. */
function askSaveChanges(what) {
  return new Promise(resolve => {
    const name = STATE?.project?.name || 'this project';
    const body = el('div', {},
      el('p', { style: 'margin-top:0' },
        `Save changes to ${name} before ${what}?`),
      el('div', { class: 'hint' },
        STATE?.project?.path
          ? STATE.project.path
          : 'This project has never been saved — Save will ask where to put it.'));
    dialog({
      title: 'Aether Desktop', body, ok: null, cancel: null,
      buttons: [
        { label: 'Cancel', value: 'cancel' },
        { label: "Don't Save", value: 'discard' },
        { label: 'Save', value: 'save', primary: true }],
      onClose: (v) => resolve(v || 'cancel')
    });
  });
}

/* True when the caller may go ahead and replace the current document. */
async function confirmDiscard(what) {
  if (!STATE?.project?.dirty) return true;
  const answer = await askSaveChanges(what);
  if (answer === 'cancel') return false;
  if (answer === 'discard') return true;
  return await saveProject(false);
}

/* File ▸ Exit. Asks the same question Close does, then actually stops the
   server — leaving a Python process on the port after "Exit" is not exiting. */
async function exitApp() {
  if (!await confirmDiscard('leaving')) return;
  // Confirm even with nothing to save: exiting ends the session, and an
  // unsaved solution or a running solve dies with it.
  const go = await new Promise(resolve => dialog({
    title: 'Exit Aether Desktop',
    body: el('div', {}, el('p', { style: 'margin-top:0' },
      'Close the workspace and stop the solver session?'),
      el('div', { class: 'hint' },
        'Any solution that has not been exported is lost.')),
    ok: null, cancel: null,
    buttons: [{ label: 'Cancel', value: false },
              { label: 'Exit', value: true, primary: true }],
    onClose: v => resolve(v === true)
  }));
  if (!go) return;
  SHUTTING_DOWN = true;
  try { await rpc('app.exit'); } catch (e) { /* the socket dies with it */ }
  document.body.innerHTML =
    '<div style="padding:40px;font:14px system-ui">Aether Desktop has shut '
    + 'down. You can close this tab.</div>';
  setTimeout(() => { try { window.close(); } catch (e) {} }, 200);
}
let SHUTTING_DOWN = false;

async function closeProject() {
  if (!STATE?.project?.open) return;
  if (!await confirmDiscard('closing it')) return;
  await guard(async () => {
    await rpc('project.close');
    resetDocumentViews();
  });
}

/* Everything the browser holds that belongs to the document that just went
   away: picks, kept dimensions, cached display buffers, report tabs. */
function resetDocumentViews() {
  // The vertex blobs belong to the document that is going away; keeping them
  // grows the tab's memory with every project opened in a session.
  BLOB_CACHE.clear();
  clearLocalPicks();
  clearKeptMeasurements();
  closeReportPages();
  if (VP) {
    VP.gridStep = null;
    VP.setObjects([], null);
    VP.setAssignments([]);
    VP.setWire(null);
  }
  fieldOn = false;
  MISSING_GEOMETRY = [];
  currentBuffers = [];
  updateOverlay();
}

function closeReportPages() {
  for (const p of pages.filter(x => x.closable)) closePage(p.id);
}

function dlgOpenSave(mode) {
  if (mode === 'save') return saveProjectAs();
  return openProjectDialog();
}

async function openProjectDialog() {
  if (!await confirmDiscard('opening another one')) return;
  const cur = STATE.project.path || '';
  filePicker({
    mode: 'open',
    kind: 'project',
    title: 'Open Project',
    hint: cur,
    path: cur ? cur.replace(/[\\/][^\\/]*$/, '') : '',
    filename: '',
    onPick: (path) => openProjectFile(path)
  });
}

/* Reading a project is the one command that regularly takes long enough to
   look like a hang. The server publishes what it is doing while it works and
   the poller renders it, so this only has to make sure the overlay is up
   before the request goes out and that the viewport is rebuilt after. */
async function openProjectFile(path) {
  showBusyOverlay('Opening ' + baseName(path), true);
  try {
    // The read itself is the only step allowed to abort the open. Everything
    // after it is secondary, and a failure in one of them must not cost the
    // model: an unreadable entry in the material library used to throw
    // between "project loaded" and "draw it", which left the workspace
    // holding a complete model and showing an empty viewport.
    const ok = await guard(() => rpc('project.open', { path }));
    if (ok === false) return;
    resetDocumentViews();
    try { await loadMaterials(); }
    catch (e) { toastError('Materials: ' + e.message); }
    try { await refreshGeometry(true); }
    catch (e) { toastError('Display: ' + e.message); }
    try {
      const status = await rpc('project.importStatus');
      if (status.errors.length) setTimeout(() => dlgImportStatus(status), 0);
    } catch (e) { /* the import report is not worth failing the open for */ }
    try { await checkDisplayAfterOpen(); } catch (e) { /* likewise */ }
  } finally { hideBusyOverlay(true); }
}

const baseName = p => String(p || '').split(/[\\/]/).pop() || String(p || '');

/* Modelling commands need somewhere to put what they make.
   With no project open — after Close, or on a workspace that has not opened
   one yet — every draw and every import answered "no design is open, use
   Project > Insert Design", which is a puzzle rather than an answer. The
   commands now make the document they need and say so. */
async function ensureDesign() {
  if (STATE?.design) return true;
  try {
    if (STATE?.project?.open === false) {
      await rpc('project.new');
      setStatus('Created a project to hold the new geometry', '');
    } else {
      await rpc('project.insertDesign');
      setStatus('Inserted a design to hold the new geometry', '');
    }
    resetDocumentViews();
    await loadMaterials().catch(() => {});
    await refreshGeometry(false);
    return !!STATE?.design;
  } catch (e) {
    toastError(e.message);
    return false;
  }
}

async function dlgTemplate() {
  if (!await confirmDiscard('starting a new one')) return;
  const body = el('div');
  body.appendChild(field('Template', sel('tp-name', [
    ['waveguide', 'WR-90 rectangular waveguide (wave ports)'],
    ['coax', '50 Ω coaxial line (TEM, integration lines)'],
    ['microstrip', 'Parallel-plate line (lumped ports)']], 'waveguide')));
  body.appendChild(el('div', { class: 'hint' },
    'Each template is a complete, solvable model with geometry, boundaries, excitations and a sweep already defined.'));
  dialog({ title: 'New Project from Template', body, ok: 'Create', onOk: async () => {
    await rpc('project.template', { template: gv('tp-name') });
    resetDocumentViews();
    await refreshGeometry(true);
    fitView();
  }});
}

function dlgMaterial() {
  const body = el('div');
  body.appendChild(field('Name', inp('m-name', 'MyMaterial')));
  body.appendChild(field('Relative permittivity', inp('m-eps', '4.4')));
  body.appendChild(field('Dielectric loss tangent', inp('m-td', '0.02')));
  body.appendChild(field('Relative permeability', inp('m-mu', '1')));
  body.appendChild(field('Bulk conductivity [S/m]', inp('m-sig', '0')));
  dialog({ title: 'Add Material', body, ok: 'Add', onOk: async () => {
    await guard(() => rpc('materials.add', { name: gv('m-name'),
      epsR: gn('m-eps'), tanD: gn('m-td'), muR: gn('m-mu'), sigma: gn('m-sig') }));
    await loadMaterials();
  }});
}

function dlgExport() {
  const body = el('div');
  body.appendChild(field('Format', sel('e-fmt', [
    ['touchstone', 'Touchstone (.sNp)'], ['csv', 'CSV table'],
    ['html', 'HTML report'], ['vtk', 'Field data (.vtu)']], 'touchstone')));
  const pathI = inp('e-path', 'results');
  // A bare relative name landed the file in whatever directory the server
  // happened to start in, which is nowhere the user can find. Browse to a
  // real folder, exactly as every other file field here does.
  const browse = el('button', { class: 'nav',
    style: 'padding:4px 12px;border:1px solid var(--border);border-radius:4px;'
      + 'background:var(--panel-alt);cursor:pointer',
    onclick: () => filePicker({ mode: 'save', kind: 'any',
      title: 'Export Solution Data', filename: pathI.value || 'results',
      onPick: (p) => { pathI.value = p; } }) }, 'Browse…');
  body.appendChild(field('File',
    el('div', { style: 'display:flex;gap:6px' }, pathI, browse)));
  body.appendChild(el('div', { class: 'hint' },
    'The extension is added to match the format when it is missing.'));
  dialog({ title: 'Export Solution Data', body, ok: 'Export', onOk: async () => {
    const r = await guard(() => rpc('results.export',
      { format: gv('e-fmt'), path: gv('e-path') }));
    if (r && r.path) setStatus('Exported to ' + r.path, '');
  }});
}

/* A local mesh refinement, stated the way a modeller states it: these
   objects or these picked faces, no element longer than this. */
function dlgMeshOp() {
  const u = U();
  const body = el('div');
  body.appendChild(field('Name', inp('mo-name', '', 'text',
    { placeholder: 'auto' })));
  autoName('mo-name', 'meshop', 'Length');
  const kinds = [];
  if (FACE_PICKS.length) kinds.push(['faces',
    `Picked faces (${FACE_PICKS.length})`]);
  kinds.push(['objects', 'Objects']);
  body.appendChild(field('Apply to', sel('mo-kind', kinds, kinds[0][0])));
  const dyn = el('div', { id: 'mo-dyn' });
  body.appendChild(dyn);
  const build = () => {
    dyn.innerHTML = '';
    if (gv('mo-kind') === 'objects') {
      dyn.appendChild(field('Objects', objectList('mo-objs')));
    } else {
      const a = FACE_PICKS.reduce((t, f) => t + (f.area || 0), 0);
      dyn.appendChild(el('div', { class: 'hint' },
        `${FACE_PICKS.length} face(s), ${(a * 1e6).toPrecision(5)} mm² total`));
    }
  };
  setTimeout(() => { $('#mo-kind').onchange = build; build(); }, 0);
  body.appendChild(field('Max element length', inp('mo-len', '1' + u)));
  body.appendChild(el('div', { class: 'hint' },
    'Refines the initial mesh before the first adaptive pass — use it where '
    + 'you already know resolution is needed: a narrow feed, a coupling gap, '
    + 'the rim of a patch.'));
  dialog({ title: 'Add Mesh Operation', body, ok: 'Add', onOk: async () => {
    const p = { name: gv('mo-name'), maxLength: gv('mo-len') };
    if (gv('mo-kind') === 'objects') {
      p.objects = picked('mo-objs');
      if (!p.objects.length) throw new Error('select at least one object');
    } else {
      p.selector = { kind: 'faces', faces: FACE_PICKS };
    }
    await guard(() => rpc('mesh.addOperation', p));
  }});
}

function dlgMesh() {
  const body = el('div');
  body.appendChild(field('Element size (blank = auto)', inp('me-size', '',
    'text', { placeholder: 'metres, e.g. 0.003' })));
  body.appendChild(el('div', { class: 'hint' },
    'The automatic seed targets λ/4 in each material at the solution frequency, tightened by surface curvature.'));
  dialog({ title: 'Generate Initial Mesh', body, ok: 'Generate', onOk: async () => {
    const s = gv('me-size');
    await guard(() => rpc('analysis.generateMesh', s ? { size: parseFloat(s) } : {}));
    await showMesh(true);
  }});
}

/* ------------------------------------------------------- menus & ribbon */
const MENUS = [
  ['File', [
    ['New Project', newProject, 'Ctrl+N'],
    ['New from Template…', dlgTemplate],
    ['Open Project…', () => dlgOpenSave('open'), 'Ctrl+O'],
    ['Save Project', () => saveProject(false), 'Ctrl+S',
      () => !!STATE?.project?.open],
    ['Save Project As…', () => saveProjectAs(), 'Ctrl+Shift+S',
      () => !!STATE?.project?.open],
    null,
    ['Close Project', closeProject, 'Ctrl+W', () => !!STATE?.project?.open],
    null,
    ['Export CAD Geometry…', dlgCadExport, '', () => !!STATE?.project?.open],
    ['Export Solution Data…', dlgExport, '', () => !!STATE?.project?.open],
    null,
    ['Exit', exitApp]]],
  ['Edit', [
    [() => 'Undo' + (STATE?.history?.undo ? ' ' + STATE.history.undo : ''),
      editUndo, 'Ctrl+Z', () => !!STATE?.history?.canUndo],
    [() => 'Redo' + (STATE?.history?.redo ? ' ' + STATE.history.redo : ''),
      editRedo, 'Ctrl+Y', () => !!STATE?.history?.canRedo],
    null,
    ['Cut', () => editCopy(true), 'Ctrl+X', () => (STATE?.selection || []).length > 0],
    ['Copy', () => editCopy(false), 'Ctrl+C', () => (STATE?.selection || []).length > 0],
    ['Paste', editPaste, 'Ctrl+V', () => !!STATE?.history?.clipboard],
    ['Paste at Offset\u2026', dlgPasteOffset, '', () => !!STATE?.history?.clipboard],
    null,
    ['Duplicate \u25b8 Along Line\u2026', () => dlgDuplicate('line')],
    ['Duplicate \u25b8 Around Axis\u2026', () => dlgDuplicate('axis')],
    ['Duplicate \u25b8 Mirror\u2026', () => dlgDuplicate('mirror')],
    null,
    ['Sweep Face Along Normal\u2026', () => dlgFaceOp('sweep')],
    ['Move Faces\u2026', () => dlgFaceOp('move')],
    null,
    ['Move by Two Points\u2026', () => startInteractiveMove(), 'Ctrl+M',
      () => (STATE?.selection || []).length > 0],
    ['Arrange \u25b8 Move\u2026', () => dlgTransform('move')],
    ['Arrange \u25b8 Rotate\u2026', () => dlgTransform('rotate')],
    ['Arrange \u25b8 Mirror\u2026', () => dlgTransform('mirror')],
    ['Arrange \u25b8 Scale\u2026', () => dlgTransform('scale')],
    null,
    ['Measure / Dimensions…', dlgMeasure, 'M'],
    ['Measure by clicking ▸ Distance', () => startMeasurePick('distance')],
    ['Measure by clicking ▸ Angle', () => startMeasurePick('angle')],
    ['Measure by clicking ▸ Circle', () => startMeasurePick('circle')],
    ['Resize to Dimensions…', dlgResize],
    ['Edit Dimensions / Expressions…', dlgPrimitive],
    ['HFSS Import Status…', dlgImportStatus],
    ['Design Variables…', dlgVariables],
    ['Box Select (Ctrl+drag)', armBandSelect],
    ['Select All', () => setSelection(objNames())],
    ['Clear Selection', () => setSelection([])],
    ['Delete Selected', deleteSelection, 'Del',
      () => (STATE?.selection || []).length > 0]]],
  ['View', [
    ['Fit All', fitView, 'Ctrl+D'],
    ['Fit Selection', () => fitSelection(), 'Ctrl+Shift+D',
      () => (STATE?.selection || []).length > 0],
    null,
    ['Isometric', () => VP.view('iso')],
    ['Top (XY)', () => VP.view('top')],
    ['Front (XZ)', () => VP.view('front')],
    ['Right (YZ)', () => VP.view('right')],
    null,
    ['Shaded', () => setViewMode('shaded')],
    ['Shaded + Edges', () => setViewMode('shadedEdges')],
    ['Wireframe', () => setViewMode('wireframe')],
    null,
    [() => 'Solid Display' + (VP && VP.opaque ? '  ✓' : ''), toggleOpaque],
    ['Display Diagnostics…', () => dlgDisplayReport()],
    null,
    ['Toggle Dark Theme', toggleTheme]]],
  ['Project', [
    ['Insert HFSS Design', () => guard(() => rpc('project.insertDesign')
      .then(() => refreshGeometry(true)))],
    ['Insert HFSS Eigenmode Design', () => guard(() => rpc('project.insertDesign',
      { solutionType: 'eigenmode' }).then(() => refreshGeometry(true)))],
    ['Rename Design…', () => STATE?.design && dlgRenameDesign(STATE.design.name),
      '', () => !!STATE?.design],
    ['Delete Design', () => guard(async () => {
      await rpc('project.deleteDesign', { name: STATE.design.name });
      resetDocumentViews();
      await refreshGeometry(true);
    }), '', () => (STATE?.project?.designs || []).length > 1],
    null,
    ['Add Material…', dlgMaterial]]],
  ['Draw', [
    ['Box', () => dlgDraw('box')], ['Cylinder', () => dlgDraw('cylinder')],
    ['Sphere', () => dlgDraw('sphere')], ['Cone', () => dlgDraw('cone')],
    ['Torus', () => dlgDraw('torus')], ['Rectangle (sheet)', () => dlgDraw('rectangle')],
    null,
    ['Draw Box by Points', () => startPointDraw('box')],
    ['Draw Rectangle by Points', () => startPointDraw('rectangle')],
    ['Draw Cylinder by Points', () => startPointDraw('cylinder')],
    null, ['Import CAD…', dlgImportCad]]],
  ['Modeler', [
    ['Boolean\u2026', dlgBoolean],
    ['Replace CAD Source\u2026', dlgReplaceCad],
    ['Arrange\u2026', () => dlgTransform('move')],
    ['Duplicate\u2026', () => dlgDuplicate('line')],
    null,
    ['Sweep Face Along Normal\u2026', () => dlgFaceOp('sweep')],
    ['Move Faces\u2026', () => dlgFaceOp('move')],
    null, ['Delete Selected', deleteSelection]]],
  ['Simulation', [
    ['Assign Boundary…', dlgBoundary],
    ['Assign Wave Port…', () => dlgExcitation('wave')],
    ['Assign Lumped Port…', () => dlgExcitation('lumped')],
    null,
    ['Add Solution Setup…', dlgSetup],
    ['Add Frequency Sweep…', () => dlgSweep()],
    null,
    ['Add Mesh Operation…', dlgMeshOp],
    ['Generate Mesh…', dlgMesh],
    ['Validation Check', dlgValidate, 'F5'],
    ['Analyze All', dlgAnalyze, 'F9']]],
  ['Results', [
    ['Create Modal S-Parameter Report', () => openReport('sparam')],
    ['Port Modes Table', () => openReport('modes')],
    ['Eigenmode Data', () => openReport('eigen')],
    ['Far Field Radiation Pattern…', () => openReport('farfield')],
    ['3D Radiation Pattern', () => showPattern(true)],
    ['Convergence Table', () => openReport('convergence')],
    null,
    ['Show Boundaries and Ports', toggleAssignments],
    ['S-Parameter Metrics…', dlgMetrics],
    ['Parameter Study Results…', dlgStudyResults],
    ['Plot Field Overlay', () => showField(true)],
    ['Export…', dlgExport]]],
  ['Tools', [
    ['Design Variables…', dlgVariables],
    ['Solver and Mesh Controls…', dlgControls],
    ['Engineering Diagnostics…', dlgDiagnostics],
    ['Parameter Study…', dlgStudy],
    ['Parameter Study Results…', dlgStudyResults],
    ['Cancel Running Analysis', () => guard(() => rpc('analysis.cancel'))],
    ['Scripting Console', () => selectBottom('console')],
    ['Clear Messages', clearMessages]]],
  ['Help', [['About Aether Desktop', dlgAbout]]]
];

const RIBBON = {
  Home: [
    ['Project', [['i-new', 'New', newProject],
      ['i-open', 'Open', () => dlgOpenSave('open')],
      ['i-save', 'Save', () => saveProject(false)],
      ['i-file', 'Close', closeProject],
      ['i-mat', 'Template', dlgTemplate]]],
    ['Draw', [['i-box', 'Box', () => dlgDraw('box')],
      ['i-cyl', 'Cylinder', () => dlgDraw('cylinder')],
      ['i-sph', 'Sphere', () => dlgDraw('sphere')]]],
    ['Simulation', [['i-bnd', 'Boundary', dlgBoundary],
      ['i-port', 'Port (pick)', () => startPortPick('lumped')],
      ['i-port', 'Wave Port', () => dlgExcitation('wave')],
      ['i-setup', 'Setup', dlgSetup], ['i-sweep', 'Sweep', () => dlgSweep()]]],
    ['Analyze', [['i-check', 'Validate', dlgValidate],
      ['i-run', 'Analyze', dlgAnalyze, 'primary']]],
    ['Results', [['i-report', 'Report', () => openReport('sparam')],
      ['i-export', 'Export', dlgExport]]]
  ],
  Draw: [
    ['Primitives', [['i-box', 'Box', () => dlgDraw('box')],
      ['i-cyl', 'Cylinder', () => dlgDraw('cylinder')],
      ['i-sph', 'Sphere', () => dlgDraw('sphere')],
      ['i-cone', 'Cone', () => dlgDraw('cone')],
      ['i-torus', 'Torus', () => dlgDraw('torus')],
      ['i-rect', 'Rectangle', () => dlgDraw('rectangle')]]],
    ['By points', [['i-box', 'Box by points', () => startPointDraw('box')],
      ['i-rect', 'Rect by points', () => startPointDraw('rectangle')],
      ['i-cyl', 'Cyl by points', () => startPointDraw('cylinder')]]],
    ['CAD', [['i-import', 'Import', dlgImportCad],
      ['i-import', 'Repair Bodies', dlgRepairBodies]]]
  ],
  Modeler: [
    ['History', [['i-undo', 'Undo', editUndo], ['i-redo', 'Redo', editRedo]]],
    ['Clipboard', [['i-copy', 'Copy', () => editCopy(false)],
      ['i-copy', 'Cut', () => editCopy(true)],
      ['i-paste', 'Paste', editPaste]]],
    ['Edit', [['i-bool', 'Boolean', dlgBoolean],
      ['i-move', 'Move by points', () => startInteractiveMove()],
      ['i-move', 'Arrange', () => dlgTransform('move')],
      ['i-dup', 'Duplicate', () => dlgDuplicate('line')]]],
    ['Dimensions', [['i-rect', 'Measure', dlgMeasure], ['i-box', 'Resize', dlgResize], ['i-setup', 'Parameters', dlgPrimitive]]],
    ['Parametric', [['i-setup', 'Variables', dlgVariables], ['i-export', 'Export CAD', dlgCadExport]]],
    ['Faces', [['i-import', 'Sweep Face', () => dlgFaceOp('sweep')],
      ['i-move', 'Move Faces', () => dlgFaceOp('move')]]],
    ['Materials', [['i-mat', 'Add Material', dlgMaterial]]],
    ['Object', [['i-box', 'Delete', deleteSelection]]]
  ],
  Simulation: [
    ['Engineering', [['i-check','Diagnostics',dlgDiagnostics],['i-setup','Controls',dlgControls],['i-box','Air Region',dlgAirRegion]]],
    ['Studies', [['i-sweep','Parameter Study',dlgStudy],['i-report','Study Results',dlgStudyResults],['i-run','Cancel',()=>guard(()=>rpc('analysis.cancel'))]]],
    ['Boundaries', [['i-bnd', 'Assign', dlgBoundary]]],
    ['Excitations', [['i-port', 'Lumped Port (pick)', () => startPortPick('lumped')],
      ['i-port', 'Wave Port (pick)', () => startPortPick('wave')],
      ['i-port', 'Wave Port…', () => dlgExcitation('wave')],
      ['i-port', 'Lumped Port…', () => dlgExcitation('lumped')]]],
    ['Analysis', [['i-setup', 'Add Setup', dlgSetup],
      ['i-sweep', 'Add Sweep', () => dlgSweep()],
      ['i-mesh', 'Mesh Operation', dlgMeshOp],
      ['i-mesh', 'Generate Mesh', dlgMesh],
      ['i-check', 'Validate', dlgValidate],
      ['i-run', 'Analyze All', dlgAnalyze, 'primary']]]
  ],
  Results: [
    ['Reports', [['i-report', 'S-Parameters', () => openReport('sparam')],
      ['i-report', 'Port Modes', () => openReport('modes')],
      ['i-report', 'Eigenmodes', () => openReport('eigen')],
      ['i-report', 'Radiation', () => openReport('farfield')],
      ['i-report', 'Convergence', () => openReport('convergence')]]],
    ['Fields', [['i-field', 'Field Overlay', () => showField(true)],
      ['i-field', '3D Pattern', () => showPattern(true)],
      ['i-mesh', 'Mesh View', () => showMesh(true)]]],
    ['Data', [['i-export', 'Export', dlgExport], ['i-report','Metrics',dlgMetrics]]]
  ],
  View: [
    ['Camera', [['i-fit', 'Fit All', fitView],
      ['i-fit', 'Fit Selection', () => fitSelection()]]],
    ['Orientation', [['i-box', 'Iso', () => VP.view('iso')],
      ['i-box', 'Top', () => VP.view('top')],
      ['i-box', 'Front', () => VP.view('front')],
      ['i-box', 'Right', () => VP.view('right')]]],
    ['Style', [['i-box', 'Shaded', () => setViewMode('shaded')],
      ['i-mesh', 'Edges', () => setViewMode('shadedEdges')],
      ['i-mesh', 'Wireframe', () => setViewMode('wireframe')],
      ['i-mat', 'Solid', toggleOpaque]]],
    ['Diagnostics', [['i-check', 'Why blank?', () => dlgDisplayReport()]]]
  ]
};

/* Import CAD.
   The unit is the whole game with STEP and IGES: the file stores bare numbers
   and a declared unit, so a 20 mm part read as metres becomes 20 m, the camera
   fits to it, and the rest of the model turns into an invisible speck — which
   is exactly what "nothing appears" looks like. The file is inspected before
   the import so what is inside it, and the size it will land at, is on screen
   before anything is committed. */
async function dlgImportCad() {
  if (!await ensureDesign()) return;
  const body = el('div');
  const pathI = inp('ic-path', '', 'text', { placeholder: 'choose a file…',
    readonly: 'readonly' });
  const info = el('div', { class: 'hint', id: 'ic-info' },
    'No file chosen yet.');

  const refresh = async () => {
    if (!pathI.value) { info.textContent = 'No file chosen yet.'; return; }
    info.textContent = 'Reading…';
    try {
      const r = await rpc('modeler.inspectCad',
        { path: pathI.value, unit: gv('ic-unit') });
      if (r.error) { info.className = 'hint err'; info.textContent = r.error; return; }
      const [lo, hi] = r.bbox;
      const ext = [0, 1, 2].map(k => ((hi[k] - lo[k]) * 1e3).toPrecision(5))
        .join(' × ') + ' mm';
      info.className = 'hint';
      const bodies = r.bodies || (r.solids || r.surfaces);
      info.textContent = `${r.format.toUpperCase()} — `
        + (r.format === 'dxf'
            ? `${r.entities} entit(y/ies), ${r.surfaces} closed outline(s)`
            : `${r.solids} solid(s), ${r.surfaces} face(s)`)
        + (bodies > 1 ? `, ${bodies} separate bodies` : '')
        + `; extent ${ext}; unit ${r.appliedUnit}`
        + (r.declaredUnit ? ` (file declares ${r.declaredUnit})` : ' (not declared)')
        + (r.format === 'dxf'
            ? ' — closed outlines become sheets; open paths remain reference drawings'
            : (r.solids ? '' : ' — surfaces only, no closed solid to mesh'));
      const sep = $('#ic-sep-row');
      if (sep) sep.style.display = bodies > 1 ? 'block' : 'none';
    } catch (e) { info.className = 'hint err'; info.textContent = e.message; }
  };

  const browse = el('button', { class: 'nav',
    style: 'padding:4px 12px;border:1px solid var(--border);border-radius:4px;'
      + 'background:var(--panel-alt);cursor:pointer',
    onclick: () => filePicker({ mode: 'open', kind: 'cad',
      title: 'Import CAD file', onPick: (p) => {
        pathI.value = p;
        const stem = p.split(/[\\/]/).pop().replace(/\.[^.]*$/, '');
        if (!gv('ic-name')) $('#ic-name').value =
          stem.replace(/[^0-9A-Za-z_]+/g, '_').replace(/^_+|_+$/g, '');
        refresh();
      } }) }, 'Browse…');

  body.appendChild(field('CAD file',
    el('div', { style: 'display:flex;gap:6px' }, pathI, browse)));
  body.appendChild(field('Name', inp('ic-name', '', 'text',
    { placeholder: 'from the file name' })));
  body.appendChild(field('Material', sel('ic-mat',
    (window.MATERIALS || [{ name: 'vacuum' }]).map(m => m.name), 'vacuum')));
  body.appendChild(field('Model units', sel('ic-unit',
    [['auto', 'Auto — as declared in the file'], ['mm', 'Millimetre'],
     ['cm', 'Centimetre'], ['m', 'Metre'], ['um', 'Micrometre'],
     ['in', 'Inch'], ['mil', 'Mil (0.001 in)'], ['ft', 'Foot']], 'auto')));
  body.appendChild(el('div', { class: 'check', id: 'ic-sep-row',
    style: 'display:none' },
    el('input', { type: 'checkbox', id: 'ic-sep', checked: 'checked' }),
    el('label', { for: 'ic-sep' },
      'Import each body as a separate object')));
  body.appendChild(info);
  body.appendChild(el('div', { class: 'hint' },
    'STEP, IGES, BREP, STL and AutoCAD DXF are read directly. '
    + 'Auto uses declared units; unitless DXF/STL/OBJ default to millimetres. '
    + 'Closed DXF outlines become sheets with OCC; open paths remain visible '
    + 'reference drawings excluded from the EM mesh. ACIS .sat is not readable — export STEP instead.'));
  setTimeout(() => { const u = $('#ic-unit'); if (u) u.onchange = refresh; }, 0);

  dialog({ title: 'Import CAD', body, ok: 'Import', onOk: async () => {
    if (!pathI.value) throw new Error('choose a CAD file first');
    const sepBox = $('#ic-sep');
    showBusyOverlay('Importing ' + baseName(pathI.value), true);
    try {
      await guard(() => rpc('modeler.importCad', { path: pathI.value,
        name: gv('ic-name'), material: gv('ic-mat'), unit: gv('ic-unit'),
        separate: sepBox ? sepBox.checked : true }));
      await refreshGeometry(true);
    } finally { hideBusyOverlay(true); }
  }});
}

/* Repointing an imported body at another file, or at another revision of the
   same one. The object survives the swap: name, material, transforms and the
   boundaries and ports assigned to it all stay. */
/* One STEP export, forty placeholder bodies.
   An HFSS project whose parts are ACIS/Parasolid attachments arrives with
   every name, material, boundary and port intact and no geometry at all.
   Repairing that one dialog at a time is not a workflow, so the file is read
   once and the bodies are matched to the placeholders in a single table the
   user can correct before anything changes. */
async function dlgRepairBodies() {
  const broken = (STATE.design?.objects || [])
    .filter(o => o.missingGeometry).map(o => o.name);
  if (!broken.length)
    return toastError('Every body in this design already has geometry');
  const body = el('div');
  const pathI = inp('rb-path', '', 'text',
    { placeholder: 'STEP / IGES / BREP export of the same parts',
      readonly: 'readonly' });
  const table = el('div', { id: 'rb-table', class: 'hint' },
    `${broken.length} body/bodies have no geometry: ` + broken.join(', '));
  const load = async (p) => {
    pathI.value = p;
    table.textContent = 'Reading ' + p.split(/[\\/]/).pop() + '…';
    try {
      const r = await rpc('modeler.repairBodies', { path: p });
      table.innerHTML = '';
      const grid = el('div', { class: 'dgrid',
        style: 'grid-template-columns:1fr 1fr' });
      grid.appendChild(el('span', { class: 'hd' }, 'Body without geometry'));
      grid.appendChild(el('span', { class: 'hd' }, 'Body in ' + r.file));
      for (const nm of r.broken) {
        grid.appendChild(el('label', {}, nm));
        const opts = [['', '— leave unrepaired —']].concat(r.bodies.map(b =>
          [String(b.index), `#${b.index + 1} ${b.name || 'solid'} — `
            + b.size.map(v => (v * 1e3).toPrecision(3)).join(' × ') + ' mm']));
        grid.appendChild(sel('rb-m-' + cssId(nm), opts,
          r.mapping[nm] === undefined ? '' : String(r.mapping[nm])));
      }
      table.appendChild(grid);
      table.appendChild(el('div', { class: 'hint' },
        'Sizes are the true extent of each body in the file, so a part can be '
        + 'identified by its dimensions when the export carries no names.'));
    } catch (e) { table.textContent = String(e.message || e); }
  };
  const browse = el('button', { class: 'nav',
    style: 'padding:4px 12px;border:1px solid var(--border);border-radius:4px;'
      + 'background:var(--panel-alt);cursor:pointer',
    onclick: () => filePicker({ mode: 'open', kind: 'cad',
      title: 'CAD export to repair from', onPick: load }) }, 'Browse…');
  body.appendChild(field('CAD file',
    el('div', { style: 'display:flex;gap:6px' }, pathI, browse)));
  body.appendChild(field('Model units', sel('rb-unit',
    [['auto', 'Auto — as declared in the file'], ['mm', 'Millimetre'],
     ['cm', 'Centimetre'], ['m', 'Metre'], ['um', 'Micrometre'],
     ['in', 'Inch'], ['mil', 'Mil']], 'auto')));
  body.appendChild(table);
  dialog({ title: 'Repair Imported Bodies', body, width: 'wide', ok: 'Repair',
    onOk: async () => {
      if (!pathI.value) throw new Error('choose the CAD file first');
      const mapping = {};
      for (const nm of broken) {
        const f = $('#rb-m-' + cssId(nm));
        if (f && f.value !== '') mapping[nm] = parseInt(f.value);
      }
      if (!Object.keys(mapping).length)
        throw new Error('map at least one body to a body in the file');
      await guard(() => rpc('modeler.repairBodies',
        { path: pathI.value, unit: gv('rb-unit'), mapping, apply: true }));
      await refreshGeometry(true);
      await refreshAssignments();
    }});
}

const cssId = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, '_');

function dlgReplaceCad() {
  const imported = (STATE.design?.objects || []);
  if (!imported.length)
    return toastError('This design has no imported CAD bodies');
  const body = el('div');
  const names = imported.map(o => o.name);
  body.appendChild(field('Imported body', sel('rc-obj', names,
    names.find(n => (STATE.selection || []).includes(n)) || names[0])));
  const pathI = inp('rc-path', '', 'text',
    { placeholder: 'leave empty to keep the current file', readonly: 'readonly' });
  const browse = el('button', { class: 'nav',
    style: 'padding:4px 12px;border:1px solid var(--border);border-radius:4px;'
      + 'background:var(--panel-alt);cursor:pointer',
    onclick: () => filePicker({ mode: 'open', kind: 'cad',
      title: 'Replace CAD source', onPick: (p) => { pathI.value = p; } }) },
    'Browse…');
  body.appendChild(field('New source file',
    el('div', { style: 'display:flex;gap:6px' }, pathI, browse)));
  body.appendChild(field('Model units', sel('rc-unit',
    [['', 'Keep current'], ['auto', 'Auto — as declared in the file'],
     ['mm', 'Millimetre'], ['cm', 'Centimetre'], ['m', 'Metre'],
     ['um', 'Micrometre'], ['in', 'Inch'], ['mil', 'Mil'], ['ft', 'Foot']], '')));
  const cur = el('div', { class: 'hint' });
  const show = () => {
    const o = imported.find(x => x.name === gv('rc-obj'));
    cur.textContent = o?.cad ? `Currently ${o.cad.file} at unit ${o.cad.unit}`
      + (o.cad.exists ? '.' : ' — that file is missing.') : 'Choose a single-solid final STEP export in world coordinates. This replaces the current shape.';
  };
  body.appendChild(cur);
  setTimeout(() => { $('#rc-obj').onchange = show; show(); }, 0);
  dialog({ title: 'Replace CAD Source', body, ok: 'Apply', onOk: async () => {
    const p = { name: gv('rc-obj') };
    if (pathI.value) p.path = pathI.value;
    if (gv('rc-unit')) p.unit = gv('rc-unit');
    if (!p.path && !p.unit) throw new Error('choose a file or a unit to change');
    await guard(() => rpc('modeler.replaceCad', p));
    await refreshGeometry(true);
  }});
}

function dlgAbout() {
  const body = el('div', { html:
    '<p style="margin-top:0"><b>Aether Desktop</b> — graphical workspace for the ' +
    'Aether-EM 3-D full-wave finite-element solver.</p>' +
    '<p>Frequency-domain Maxwell solver on tetrahedra with curl-conforming ' +
    '(Nédélec) vector basis functions, modal wave ports, adaptive refinement ' +
    'and HFSS <code>.aedt</code> interoperability.</p>' +
    '<p class="hint">Independent software. Not affiliated with, endorsed by or ' +
    'sponsored by ANSYS, Inc. “HFSS”, “AEDT” and “Ansys” are trademarks of ' +
    'ANSYS, Inc., used here only to describe file-format compatibility.</p>' });
  dialog({ title: 'About', body, ok: null, cancel: 'Close' });
}

function buildMenus() {
  const bar = $('#menubar');
  bar.innerHTML = '';
  for (const [name, items] of MENUS) {
    const m = el('div', { class: 'menu' });
    const btn = el('button', {}, name);
    const pop = el('div', { class: 'menu-pop' });
    // Rebuilt every time the menu opens: labels such as "Undo Move" and the
    // enabled state of Paste depend on the live session state.
    const fill = () => {
      pop.innerHTML = '';
      for (const it of items) {
        if (!it) { pop.appendChild(el('hr')); continue; }
        const [label, fn, sc, enabled] = it;
        const on = enabled ? !!enabled() : true;
        const b = el('button', { onclick: () => { closeMenus(); if (on) fn(); } },
          typeof label === 'function' ? label() : label,
          sc ? el('span', { class: 'sc' }, sc) : null);
        if (!on) b.disabled = true;
        pop.appendChild(b);
      }
    };
    btn.onclick = e => {
      e.stopPropagation();
      const open = m.classList.contains('open');
      closeMenus();
      if (!open) { fill(); m.classList.add('open'); }
    };
    m.append(btn, pop);
    bar.appendChild(m);
  }
  document.addEventListener('click', closeMenus);
}
const closeMenus = () => $$('.menu.open').forEach(m => m.classList.remove('open'));

let ribbonTab = 'Home';
function buildRibbon() {
  const tabs = $('#ribbon-tabs'), body = $('#ribbon-body');
  tabs.innerHTML = ''; body.innerHTML = '';
  for (const name of Object.keys(RIBBON)) {
    tabs.appendChild(el('button', {
      class: name === ribbonTab ? 'active' : '',
      onclick: () => { ribbonTab = name; buildRibbon(); }
    }, name));
  }
  for (const [group, items] of RIBBON[ribbonTab]) {
    const g = el('div', { class: 'rgroup' });
    const row = el('div', { class: 'items' });
    for (const [ic, label, fn, cls] of items)
      row.appendChild(el('button', { class: 'rbtn ' + (cls || ''), onclick: fn },
        icon(ic), el('span', {}, label)));
    g.append(row, el('div', { class: 'glabel' }, group));
    body.appendChild(g);
  }
}

/* ------------------------------------------------------------- the tree */
const TREE_ICON = {
  project: 'i-new', design: 'i-box', modeler: 'i-box', object: 'i-box',
  sheet: 'i-rect', boundary: 'i-bnd', port: 'i-port', setup: 'i-setup',
  sweep: 'i-sweep', results: 'i-report', mesh: 'i-mesh',
  meshop: 'i-mesh', material: 'i-mat'
};
const collapsed = new Set();

function renderTree() {
  const t = $('#tree');
  t.innerHTML = '';
  const d = STATE.design;
  if (STATE.project.open === false) {
    // The state between documents. Saying so — and offering the two ways out
    // — beats an empty panel that looks like a failure to load.
    t.appendChild(el('div', { class: 'empty-doc' },
      el('p', {}, 'No project is open.'),
      el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
        onclick: newProject }, 'New Project'),
      el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
        onclick: () => dlgOpenSave('open') }, 'Open Project…')));
    return;
  }
  const add = (depth, key, label, type, opts = {}) => {
    const kids = opts.kids || 0;
    const open = !collapsed.has(key);
    const n = el('div', {
      class: 'node' + (opts.sel ? ' sel' : '') + (opts.dim ? ' dim' : ''),
      style: `padding-left:${4 + depth * 13}px`,
      title: opts.title || label,
      onclick: e => { e.stopPropagation(); opts.onclick && opts.onclick(); },
      ondblclick: e => { e.stopPropagation(); opts.ondblclick && opts.ondblclick(); },
      oncontextmenu: e => treeContext(e, type, opts.ctxName || label, opts)
    });
    n.appendChild(el('span', { class: 'tw',
      onclick: e => { e.stopPropagation();
        if (!kids) return;
        collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key);
        renderTree(); } }, kids ? (open ? '▾' : '▸') : ''));
    n.appendChild(icon(TREE_ICON[type] || 'i-box', 'ic'));
    n.appendChild(el('span', { class: 'lbl' }, label));
    if (opts.tag) n.appendChild(el('span', { class: 'tag' }, opts.tag));
    t.appendChild(n);
    return open;
  };

  const pOpen = add(0, 'proj', STATE.project.name +
    (STATE.project.dirty ? ' *' : ''), 'project',
    { kids: 1, onclick: () => showProps('project') });
  if (!pOpen) return;
  for (const dn of STATE.project.designs) {
    const isCur = d && d.name === dn;
    const dOpen = add(1, 'd:' + dn, dn, 'design', { kids: 1, sel: isCur,
      tag: isCur ? d.solutionType.replace('_', ' ') : '',
      onclick: () => guard(() => rpc('project.setDesign', { name: dn })
        .then(() => {clearKeptMeasurements();VP.gridStep=null;return refreshGeometry(true);})) });
    if (!isCur || !dOpen) continue;

    if (add(2, 'mod', 'Modeler', 'modeler',
      { kids: 1, tag: String(d.objects.length + d.sheets.length) })) {
      for (const o of d.objects) {
        const noGeom = !!(o.cad && o.cad.unreadable);
        add(3, 'o:' + o.name, o.name, 'object', {
          dim: noGeom || o.visible === false,
          tag: noGeom ? 'no geometry' : o.material,
          sel: STATE.selection.includes(o.name),
          title: noGeom ? `${o.name} — ${o.cad.unreadable}`
            : `${o.name} — ${o.kind}, material ${o.material}`
              + (o.isPec ? ' (not solved inside)' : ''),
          onclick: () => setSelection([o.name]),
          ondblclick: () => showProps('object', o.name) });
      }
      for (const s of d.sheets)
        add(3, 's:' + s.name, s.name, 'sheet', { tag: 'sheet',
          sel: STATE.selection.includes(s.name),
          onclick: () => setSelection([s.name]) });
    }
    if (add(2, 'bnd', 'Boundaries', 'boundary',
      { kids: 1, tag: String(d.boundaries.length) })) {
      for (const b of d.boundaries)
        add(3, 'b:' + b.name, b.name, 'boundary', { tag: b.type,
          title: b.selector.label,
          onclick: () => showProps('boundary', b.name) });
    }
    if (add(2, 'exc', 'Excitations', 'port',
      { kids: 1, tag: String(d.ports.length) })) {
      for (const p of d.ports)
        add(3, 'p:' + p.name, p.name, 'port',
          { tag: p.kind === 'wave' ? `${p.modes} mode${p.modes > 1 ? 's' : ''}` : 'lumped',
            title: p.selector.label,
            onclick: () => showProps('port', p.name) });
    }
    if (add(2, 'ana', 'Analysis', 'setup',
      { kids: 1, tag: String(d.setups.length) })) {
      for (const st of d.setups) {
        const o = add(3, 'st:' + st.name, st.name, 'setup',
          { kids: st.sweeps.length, tag: fmtHz(st.frequency),
            onclick: () => showProps('setup', st.name) });
        if (o) for (const sw of st.sweeps)
          add(4, 'sw:' + st.name + sw.name, sw.name, 'sweep',
            { tag: `${sw.points} pts`,
              title: `${sw.kind}, ${fmtHz(sw.start)} – ${fmtHz(sw.stop)}`,
              onclick: () => { propTarget = { type: 'sweep', name: sw.name,
                setup: st.name }; renderProps(); } });
      }
    }
    const mops = d.meshOps || [];
    const mOpen = add(2, 'msh', 'Mesh', 'mesh', { kids: mops.length,
      dim: !d.meshed && !mops.length,
      tag: d.meshStats ? `${d.meshStats.tets.toLocaleString()} tets` : 'not generated',
      onclick: () => d.meshed ? showMesh(true) : dlgMesh() });
    if (mOpen) {
      for (const m of mops)
        add(3, 'mop:' + m.name, m.name, 'meshop', {
          tag: fmtLen(m.maxLength, U()),
          dim: !m.enabled,
          title: `${m.where} — max element ${fmtLen(m.maxLength, U())}`,
          onclick: () => showProps('meshop', m.name) });
    }
    add(2, 'res', 'Results', 'results', { dim: !STATE.hasSolution,
      tag: STATE.hasSolution ? 'solved' : 'no solution',
      onclick: () => STATE.hasSolution ? openReport('sparam') : null });
  }
}

/* -------------------------------------------------------- property grid */
let propTarget = { type: 'project' };
function showProps(type, name) { propTarget = { type, name }; renderProps(); }

/* Colour, transparency and visibility, per object.
   They default to the material's, and an object that overrides them keeps a
   Reset next to it -- a red patch on a red substrate is a modelling problem,
   not a material one, and it should be fixable without inventing a material. */
function displayProps(row, o) {
  const set = (prop, value) => guard(async () => {
    await rpc('modeler.setProperty', { name: o.name, prop, value });
    await refreshGeometry(false);
  });

  const sw = el('input', { type: 'color', value: o.color,
    style: 'width:44px;height:19px;padding:0;border:1px solid var(--border);'
      + 'background:none;cursor:pointer' });
  sw.onchange = () => set('color', sw.value);
  const reset = el('button', { class: 'lnk', title: 'Use the material colour',
    onclick: () => set('color', '') }, 'reset');
  row('Colour', el('div', { style: 'display:flex;gap:8px;align-items:center' },
    sw, o.colorOverridden ? reset : null,
    el('span', { class: 'hint', style: 'margin:0' },
      o.colorOverridden ? '' : 'from material')));

  const tr = el('input', { type: 'range', min: '0', max: '1', step: '0.05',
    value: String(o.transparency), style: 'width:110px' });
  const trv = el('span', {}, o.transparency.toFixed(2));
  tr.oninput = () => { trv.textContent = Number(tr.value).toFixed(2); };
  tr.onchange = () => set('transparency', parseFloat(tr.value));
  row('Transparency', el('div',
    { style: 'display:flex;gap:8px;align-items:center' }, tr, trv,
    o.transparencyOverridden
      ? el('button', { class: 'lnk', title: 'Use the material transparency',
          onclick: () => set('transparency', '') }, 'reset')
      : null));

  const vis = el('input', { type: 'checkbox' });
  vis.checked = o.visible !== false;
  vis.onchange = () => set('visible', vis.checked);
  row('Visible', vis);
}

/* An imported body keeps its provenance, and both halves of it are editable:
   the unit its numbers are read in, and the file they come from. Changing
   either edits the object in place, so the name, material, transforms and
   every boundary and port pointing at it survive. */
function cadProps(row, o) {
  const c = o.cad;
  row('CAD source', el('span', { title: c.path,
    style: (c.exists && !c.unreadable) ? '' : 'color:var(--err)' },
    c.file + (c.exists ? '' : ' — file missing')));
  if (c.unreadable)
    row('', el('div', { class: 'hint err', style: 'margin:0' }, c.unreadable));
  const us = sel('', [['auto', 'Auto (as declared)'], ['mm', 'mm'], ['cm', 'cm'],
    ['m', 'm'], ['um', 'µm'], ['in', 'inch'], ['mil', 'mil'], ['ft', 'ft']],
    c.unit || 'auto');
  us.onchange = () => guard(async () => {
    await rpc('modeler.replaceCad', { name: o.name, unit: us.value });
    await refreshGeometry(true);
  });
  row('Model units', us);
  row('', el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
    onclick: () => filePicker({ mode: 'open', kind: 'cad',
      title: 'Replace CAD source for ' + o.name,
      onPick: (path) => guard(async () => {
        await rpc('modeler.replaceCad', { name: o.name, path });
        await refreshGeometry(true);
      }) }) }, c.exists ? 'Replace source…' : 'Locate file…'));
}

function renderProps() {
  const p = $('#props-body');
  p.innerHTML = '';
  const d = STATE.design;
  const tbl = el('table', { class: 'props' });
  const row = (k, v) => tbl.appendChild(el('tr', {},
    el('td', { class: 'k' }, k), el('td', { class: 'v' },
      typeof v === 'string' || typeof v === 'number' ? String(v) : v)));

  const t = propTarget.type;
  if (t === 'object' && d) {
    const o = d.objects.find(x => x.name === propTarget.name);
    if (o) {
      const ni = inp('', o.name);
      ni.onchange = () => guard(async () => {
        await rpc('modeler.setProperty',
          { name: o.name, prop: 'name', value: ni.value });
        await refreshGeometry(false);
      });
      row('Name', ni);
      row('Type', o.kind);
      if(['box','cylinder','sphere','cone','torus','rectangle'].includes(o.kind)) row('Dimensions',el('button',{onclick:dlgPrimitive},'Edit dimensions / expressions…'));
      const ms = sel('pm', (window.MATERIALS || []).map(m => m.name), o.material);
      ms.onchange = () => guard(() => rpc('modeler.setProperty',
        { name: o.name, prop: 'material', value: ms.value })
        .then(() => refreshGeometry(false)));
      row('Material', ms);
      const si = el('input', { type: 'checkbox' });
      si.checked = o.solveInside;
      si.onchange = () => guard(() => rpc('modeler.setProperty',
        { name: o.name, prop: 'solveInside', value: si.checked }));
      row('Solve inside', si);
      displayProps(row, o);
      if (o.cad) cadProps(row, o);
    }
  } else if (t === 'meshop' && d) {
    const m = (d.meshOps || []).find(x => x.name === propTarget.name);
    if (m) {
      row('Name', m.name);
      row('Type', 'Length based');
      row('Applies to', m.where);
      const li = inp('', fmtLen(m.maxLength, U()));
      li.onchange = () => guard(() => rpc('mesh.setOperation',
        { name: m.name, maxLength: li.value }));
      row('Max element length', li);
      const en = el('input', { type: 'checkbox' });
      en.checked = m.enabled;
      en.onchange = () => guard(() => rpc('mesh.setOperation',
        { name: m.name, enabled: en.checked }));
      row('Enabled', en);
      tbl.appendChild(el('tr', {}, el('td', { colspan: 2 },
        el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
          onclick: () => guard(() => rpc('mesh.deleteOperation',
            { name: m.name })) }, 'Delete mesh operation'))));
    }
  } else if (t === 'boundary' && d) {
    const b = d.boundaries.find(x => x.name === propTarget.name);
    if (b) {
      row('Name', b.name); row('Type', b.type);
      row('Assignment', b.selector.label);
      for (const [k, v] of Object.entries(b.params || {}))
        row(k, Array.isArray(v) ? v.join(', ') : String(v));
      tbl.appendChild(el('tr', {}, el('td', { colspan: 2 },
        el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
          onclick: () => guard(() => rpc('boundary.delete', { name: b.name })
            .then(refreshAssignments)) },
          'Delete boundary'))));
    }
  } else if (t === 'port' && d) {
    const x = d.ports.find(y => y.name === propTarget.name);
    if (x) {
      row('Name', x.name); row('Type', x.kind === 'wave' ? 'Wave Port' : 'Lumped Port');
      row('Assignment', x.selector.label);
      if (x.kind === 'wave') {
        row('Modes', x.modes);
        row('De-embed', fmtLen(x.deembed, U()));
        row('Renormalise', x.renorm == null ? 'modal Z' : x.renorm + ' Ω');
      } else {
        row('Impedance', Array.isArray(x.impedance)
          ? x.impedance[0].toFixed(3) + ' Ω' : x.impedance);
      }
      row('Integration line', x.hasLine ? 'defined' : 'none');
      tbl.appendChild(el('tr', {}, el('td', { colspan: 2 },
        el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
          onclick: () => guard(() => rpc('excitation.delete', { name: x.name })
            .then(refreshAssignments)) },
          'Delete excitation'))));
    }
  } else if (t === 'setup' && d) {
    const st = d.setups.find(x => x.name === propTarget.name);
    if (st) {
      const f = inp('', fmtHz(st.frequency));
      f.onchange = () => guard(() => rpc('analysis.editSetup',
        { name: st.name, frequency: f.value }));
      row(d.solutionType === 'eigenmode' ? 'Mesh seed frequency'
        : 'Solution frequency', f);
      if (d.solutionType === 'eigenmode') {
        const nm = inp('', st.nModes, 'number', { min: 1, max: 50 });
        nm.onchange = () => guard(() => rpc('analysis.editSetup',
          { name: st.name, nModes: nm.value }));
        row('Number of modes', nm);
        const fm = inp('', fmtHz(st.minFrequency));
        fm.onchange = () => guard(() => rpc('analysis.editSetup',
          { name: st.name, minFrequency: fm.value }));
        row('Minimum frequency', fm);
        const df = inp('', st.deltaF, 'number', { step: '0.001' });
        df.onchange = () => guard(() => rpc('analysis.editSetup',
          { name: st.name, deltaF: df.value }));
        row('Maximum Δf', df);
      }
      const mp = inp('', st.maxPasses, 'number');
      mp.onchange = () => guard(() => rpc('analysis.editSetup',
        { name: st.name, maxPasses: mp.value }));
      row('Maximum passes', mp);
      const ds = inp('', st.deltaS, 'number', { step: '0.001' });
      ds.onchange = () => guard(() => rpc('analysis.editSetup',
        { name: st.name, deltaS: ds.value }));
      row('Maximum ΔS', ds);
      const bo = sel('', [[1, '1st order'], [2, '2nd order']], st.basisOrder);
      bo.onchange = () => guard(() => rpc('analysis.editSetup',
        { name: st.name, basisOrder: bo.value }));
      row('Basis order', bo);
      row('Sweeps', st.sweeps.length);
      tbl.appendChild(el('tr', {}, el('td', { colspan: 2 },
        el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
          onclick: () => dlgSweep(st.name) }, 'Add frequency sweep…'),
        el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
          onclick: () => guard(() => rpc('analysis.deleteSetup',
            { name: st.name })) }, 'Delete setup'))));
    }
  } else if (t === 'sweep' && d) {
    const st = d.setups.find(x => x.name === propTarget.setup);
    const sw = st && st.sweeps.find(x => x.name === propTarget.name);
    if (sw) {
      row('Name', sw.name);
      row('Type', sw.kind);
      row('Range', `${fmtHz(sw.start)} – ${fmtHz(sw.stop)}`);
      row('Spacing', sw.spacing);
      row('Points', sw.points);
      tbl.appendChild(el('tr', {}, el('td', { colspan: 2 },
        el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
          onclick: () => guard(() => rpc('analysis.deleteSweep',
            { setup: st.name, name: sw.name })) }, 'Delete sweep'))));
    }
  } else {
    row('Project', STATE.project.name);
    row('File', STATE.project.path || '(unsaved)');
    row('Designs', STATE.project.designs.length);
    if (d) {
      row('Design', d.name);
      row('Solution type', d.solutionType.replace('_', ' '));
      const us = sel('', ['mm', 'cm', 'm', 'um', 'mil', 'in'], d.units);
      us.onchange = () => { d.units = us.value; renderAll(); };
      row('Model units', us);
      row('Objects', d.objects.length);
      row('Excitations', d.excitations.length);
      const [lo, hi] = d.bbox;
      row('Extent', ['X', 'Y', 'Z'].map((a, i) =>
        `${a}: ${fmtLen(hi[i] - lo[i], d.units)}`).join('  '));
    }
  }
  p.appendChild(tbl);
}

/* ------------------------------------------------------------- viewport */
let VP = null;
let currentBuffers = [];
let MISSING_GEOMETRY = [];

function initViewport() {
  try { VP = window.VP = new Viewport($('#gl')); }
  catch (e) { $('#viewport').innerHTML =
    `<div style="padding:30px;color:#c02626">3-D viewport unavailable: ${e.message}</div>`;
    return; }
  const tools = $('#vp-tools');
  const mk = (title, ic, fn, id) => {
    const b = el('button', { title, onclick: fn, id }, icon(ic));
    tools.appendChild(b); return b;
  };
  VP.onContext = viewportContext;
  let lastHover=0;
  VP.onHover = (px, py) => {
    const now=performance.now();if(now-lastHover<32)return;lastHover=now;
    if (MEASURE_PICK) measurePickHover(px, py);
    else if (DRAW) drawPickHover(px, py);
    else if (MOVE) movePickHover(px, py);
    else previewSelection(px, py);
  };
  VP.onPickAt = (px, py) => MEASURE_PICK ? measurePickClick(px, py)
    : DRAW ? drawPickClick(px, py)
    : MOVE ? movePickClick(px, py) : false;
  VP.onPick = (hit, ev) => {
    const add = !!(ev && (ev.ctrlKey || ev.metaKey || ev.shiftKey));
    if (!hit) return clearPicks();
    if (SEL_MODE === 'face') return pickFace(hit, add);
    if (SEL_MODE === 'edge') return pickEdge(hit, add);
    if (SEL_MODE === 'point') return pickVertex(hit, add);
    const cur = new Set(add ? (STATE.selection || []) : []);
    if(add && cur.has(hit.name))cur.delete(hit.name);else cur.add(hit.name);
    setSelection([...cur]);
  };
  /* Rubber-band selection: Ctrl+drag, or the toolbar's box-select button.
     Picking one face at a time is fine for a box and hopeless for a coil. */
  VP.onBandUpdate = (box) => {
    let n = $('#vp-band');
    if (!box) { if (n) n.style.display = 'none'; return; }
    if (!n) { n = el('div', { id: 'vp-band' }); $('#viewport').appendChild(n); }
    n.style.left = Math.min(box.x0, box.x1) + 'px';
    n.style.top = Math.min(box.y0, box.y1) + 'px';
    n.style.width = Math.abs(box.x1 - box.x0) + 'px';
    n.style.height = Math.abs(box.y1 - box.y0) + 'px';
    n.style.display = 'block';
  };
  VP.onBand = (box, ev) => applyBandSelection(box, !!(ev && ev.shiftKey));
  VP.onDoublePick=(hit,ev)=>{
    if(DRAW||MOVE||MEASURE_PICK||SEL_MODE==='point'||!hit)return;
    setSelectMode('object');
    const names=new Set(ev.ctrlKey||ev.metaKey?(STATE.selection||[]):[]);names.add(hit.name);setSelection([...names]);
  };
  VP.onLeave=()=>{$('#vp-hint').textContent='double-click object · drag rotate · wheel zoom · Ctrl+D fit';
    const xyz=$('#status-xyz'); if(xyz) xyz.textContent='';};
  // Selection mode buttons, and the O / F / E keys that go with them --
  // picking a face is how a boundary, a port or a mesh operation gets told
  // *where*, so the mode lives in the viewport toolbar, not in a menu.
  for (const [m, ic, label] of [['object', 'i-box', 'Select objects (O)'],
                                ['face', 'i-rect', 'Select faces (F)'],
                                ['edge', 'i-sweep', 'Select edges (E)'], ['point','i-rect','Select vertices (V)']]) {
    const b = mk(label, ic, () => setSelectMode(m), 'vt-sel-' + m);
    b.classList.toggle('on', SEL_MODE === m);
  }
  mk('Box select — drag a rectangle (Ctrl+drag)', 'i-rect', armBandSelect,
    'vt-band');
  tools.appendChild(el('span', { class: 'vt-sep' }));
  mk('Move selection by two points', 'i-move', () => startInteractiveMove(),
    'vt-move');
  mk('Measure / Dimensions (M)', 'i-rect', dlgMeasure, 'vt-measure');
  mk('Keep current measurement', 'i-rect',keepMeasurement,'vt-keep-measure');
  mk('Show / hide measurements','i-rect',toggleMeasurements,'vt-show-measure');
  mk('Click two points to measure', 'i-sweep', () => startMeasurePick('distance'), 'vt-measure-pick');
  mk('Fit all (Ctrl+D)', 'i-fit', fitView);
  mk('Isometric', 'i-box', () => VP.view('iso'));
  mk('Shaded / edges / wireframe', 'i-mesh', cycleViewMode, 'vt-mode');
  mk('Solid display — ignore material transparency', 'i-mat', toggleOpaque,
    'vt-solid');
  mk('Why is the viewport blank?', 'i-check', () => dlgDisplayReport(),
    'vt-diag');
  mk('Boundaries and ports', 'i-bnd', toggleAssignments, 'vt-assign')
    .classList.add('on');
  mk('Mesh overlay', 'i-mesh', () => showMesh(!VP.wire), 'vt-mesh');
  mk('Field overlay', 'i-field', () => showField(!fieldOn), 'vt-field');
  mk('3D radiation pattern', 'i-field', () => showPattern(!patternOn), 'vt-pattern');
}

function setViewMode(m) { VP.mode = m; $('#vp-info') && updateOverlay(); }

// the label sits over the span it measures, so it has to follow the camera
setInterval(() => { if (MEASURE) placeMeasureLabel();renderKeptMeasurements(); }, 90);
function cycleViewMode() {
  VP.mode = { shaded: 'shadedEdges', shadedEdges: 'wireframe',
    wireframe: 'shaded' }[VP.mode];
  updateOverlay();
}
function fitView() { VP && VP.fit(); }

/* Fit the camera to what is selected.
   A patch inside a radiation box is a thousandth of the box: Fit All frames
   the box and leaves the patch invisible. This frames the object instead, and
   is the answer to "the model is there but I cannot see it". */
function fitSelection(names) {
  if (!VP) return;
  const want = names || STATE?.selection || [];
  if (!want.length) return toastError('Select an object first');
  const box = VP.boundsOf(want);
  if (!box) return toastError('That object has nothing drawn to zoom to');
  VP.fit(box);
}

/* Vertex data arrives as raw float32 rather than as JSON numbers.
   A mid-sized imported assembly is tens of millions of coordinates; as JSON
   text that is hundreds of megabytes to serialise, transfer and parse, and
   the parse alone froze the tab. The arrays are content-addressed, so a body
   that did not change is never fetched twice. */
const BLOB_CACHE = new Map();
const BLOB_CACHE_LIMIT = 400;

async function fetchBlob(ref) {
  const hit = BLOB_CACHE.get(ref.blob);
  if (hit) { BLOB_CACHE.delete(ref.blob); BLOB_CACHE.set(ref.blob, hit); return hit; }
  const r = await fetch('/api/blob?id=' + encodeURIComponent(ref.blob) +
    '&token=' + encodeURIComponent(window.AETHER_TOKEN));
  if (!r.ok) throw new Error('display buffer expired — redrawing');
  const buf = await r.arrayBuffer();
  const arr = ref.type === 'i32' ? new Int32Array(buf) : new Float32Array(buf);
  BLOB_CACHE.set(ref.blob, arr);
  while (BLOB_CACHE.size > BLOB_CACHE_LIMIT)
    BLOB_CACHE.delete(BLOB_CACHE.keys().next().value);
  return arr;
}

async function hydrateBuffers(objects) {
  const jobs = [];
  for (const o of objects) {
    if (!o.blobs) continue;
    for (const [field, ref] of Object.entries(o.blobs))
      jobs.push(fetchBlob(ref).then(a => { o[field] = a; }));
  }
  if (jobs.length) await Promise.all(jobs);
}

/* What the viewport already holds, so the server can skip re-sending it.
   Read off the live GPU objects rather than a parallel bookkeeping map: the
   field and mesh overlays replace the object list wholesale, and a stale map
   would claim buffers that are no longer there. */
function heldGeometry() {
  const have = {};
  for (const o of (VP && VP.objects) || []) if (o.digest) have[o.name] = o.digest;
  return have;
}

async function refreshGeometry(fit) {
  if (!VP) return;
  let g;
  try {
    g = await rpc('view.geometry', { have: heldGeometry(), binary: true });
    await hydrateBuffers(g.objects || []);
  } catch (e) {
    // A dropped blob (server restarted, cache evicted) is recoverable: ask
    // again for everything, in full.
    g = await rpc('view.geometry', { binary: true });
    await hydrateBuffers(g.objects || []);
  }
  MISSING_GEOMETRY = g.missing || [];
  currentBuffers = g.objects || [];
  window.currentBuffersLen = currentBuffers.length;
  clearLocalPicks();
  VP.setObjects(currentBuffers, g.bbox);
  VP.setSelection(STATE.selection);
  VP.setWire(null); fieldOn = false;
  if (fit) VP.fit();
  await refreshAssignments();
  updateOverlay();
}

/* Boundaries and ports drawn on the faces they cover, with a legend naming
   them. An assignment that landed on the wrong face is then obvious at the
   moment it is made, instead of at the end of a solve. */
let ASSIGN_ITEMS = [];

async function refreshAssignments() {
  if (!VP) return;
  try {
    const r = await rpc('view.assignments', {});
    ASSIGN_ITEMS = r.items || [];
  } catch (e) { ASSIGN_ITEMS = []; }
  VP.setAssignments(ASSIGN_ITEMS);
  renderAssignLegend();
}

function renderAssignLegend() {
  const box = $('#vp-assign');
  if (!box) return;
  box.innerHTML = '';
  if (!VP.showAssignments || !ASSIGN_ITEMS.length) {
    box.style.display = 'none';
    return;
  }
  box.style.display = 'block';
  for (const it of ASSIGN_ITEMS) {
    box.appendChild(el('div', { class: 'row',
      title: `${it.name} — ${it.type}, ${it.count} triangles`,
      onclick: () => showProps(it.kind === 'boundary' ? 'boundary' : 'port',
        it.name) },
      el('span', { class: 'sw', style: `background:${it.color}` }),
      `${it.name} · ${it.type}`));
  }
}

function toggleAssignments() {
  VP.showAssignments = !VP.showAssignments;
  $('#vt-assign') &&
    $('#vt-assign').classList.toggle('on', VP.showAssignments);
  renderAssignLegend();
}

async function showMesh(on) {
  if (!on) { VP.setWire(null); $('#vt-mesh').classList.remove('on'); return; }
  await guard(async () => {
    const m = await rpc('view.mesh');
    VP.setWire(m.wire);
    $('#vt-mesh').classList.add('on');
    setStatus(`Mesh: ${m.stats.nodes.toLocaleString()} nodes, ` +
      `${m.stats.tets.toLocaleString()} tetrahedra`, '');
  });
}

let fieldOn = false;
async function showField(on, opts) {
  if (!on) {
    fieldOn = false; $('#vt-field').classList.remove('on');
    $('#legend').classList.remove('on'); $('#legend-labels').classList.remove('on');
    await refreshGeometry(false);
    return;
  }
  await guard(async () => {
    const f = await rpc('view.field', opts || {});
    f.name = '__field__'; f.color = '#888888'; f.transparency = 0;
    VP.setObjects([f], VP.bbox);
    fieldOn = true;
    $('#vt-field').classList.add('on');
    const lg = $('#legend');
    lg.style.background =
      'linear-gradient(to top, #30123b, #4145ab, #1ba0d1, #46f884, #d5e11a, #f6883a, #900c00)';
    lg.classList.add('on');
    const lab = $('#legend-labels');
    lab.innerHTML = '';
    for (let i = 4; i >= 0; i--) {
      const v = f.range[0] + (f.range[1] - f.range[0]) * i / 4;
      lab.appendChild(el('span', {}, v.toPrecision(3)));
    }
    lab.classList.add('on');
    lab.insertBefore(el('span', { style: 'font-weight:600' }, '|E| V/m'), lab.firstChild);
  });
}

/* Air, vacuum and PML regions carry a material transparency near 1. A project
   whose readable bodies are all regions of that kind renders as an almost
   empty window, which reads as "the import failed" rather than "you are
   looking at air". Solid Display ignores material transparency. */
function toggleOpaque() {
  if (!VP) return;
  VP.opaque = !VP.opaque;
  const b = $('#vt-solid');
  if (b) b.classList.toggle('on', VP.opaque);
  setStatus('Solid display ' + (VP.opaque ? 'on' : 'off'), '');
}

/* "It loaded and nothing appeared" has several different causes. Rather than
   leave you to guess, this says which one it is, per object. */
async function dlgDisplayReport(report) {
  await guard(async () => {
    const r = report || await rpc('view.displayReport');
    const body = el('div');
    body.appendChild(el('p', { style: 'margin-top:0' }, r.summary));
    const t = el('table', { class: 'grid' });
    t.appendChild(el('tr', {}, ...['Object', 'State', 'Material', 'Transp.',
      'Extent (' + U() + ')', 'Detail'].map(h => el('th', {}, h))));
    for (const row of r.rows) {
      const tr = el('tr', {},
        el('td', {}, row.name),
        el('td', {}, row.state),
        el('td', {}, row.material || (row.isSheet ? 'sheet' : '')),
        el('td', { class: 'num' }, row.transparency.toFixed(2)),
        el('td', { class: 'num' },
          row.extent.map(v => Number((v / (UNIT_SCALE[U()] || 1e-3))
            .toPrecision(4))).join(' × ')),
        el('td', {}, row.detail || ''));
      if (row.state !== 'displayed')
        tr.style.color = 'var(--err)';
      tr.onclick = () => { setSelection([row.name]); };
      tr.style.cursor = 'pointer';
      t.appendChild(tr);
    }
    body.appendChild(t);
    body.appendChild(el('div', { class: 'hint' },
      'Click a row to select that object. "no geometry" means the project '
      + 'stores the body in a format this kernel cannot read — export it to '
      + 'STEP and use Replace CAD Source. A body that is 0.9 transparent is '
      + 'drawn, but you are looking through it: try View ▸ Solid Display.'));
    body.appendChild(el('div', { style: 'margin-top:10px;display:flex;gap:8px' },
      el('button', { onclick: () => { toggleOpaque(); } },
        'Toggle Solid Display'),
      el('button', { onclick: fitView }, 'Fit All'),
      el('button', { onclick: () => fitSelection() }, 'Fit Selection'),
      el('button', { onclick: () => {
        const rows = [['Object', 'State', 'Material', 'Transparency',
                       'ExtentX', 'ExtentY', 'ExtentZ', 'Detail']];
        for (const x of r.rows)
          rows.push([x.name, x.state, x.material, x.transparency,
                     x.extent[0], x.extent[1], x.extent[2], x.detail]);
        exportCsvFile('aether-display-report.csv', rows);
      } }, 'Export CSV')));
    dialog({ title: 'Display Diagnostics — ' + (r.design || '(no design)'),
      body, width: 'wide', ok: null, cancel: 'Close' });
  });
}

/* Run after a project is opened. If every body that can be drawn is nearly
   transparent, the honest thing is to make them solid and say so, rather than
   present an empty window and let the user conclude the import failed. */
async function checkDisplayAfterOpen() {
  try {
    const r = await rpc('view.displayReport');
    const drawn = r.rows.filter(x => x.state === 'displayed');
    if (drawn.length && r.faint.length === drawn.length && VP && !VP.opaque) {
      toggleOpaque();
      setStatus('All bodies are near-transparent regions — Solid Display '
        + 'turned on (View ▸ Solid Display to undo)', '');
    }
    if (r.rows.some(x => x.state !== 'displayed') || !drawn.length)
      setTimeout(() => dlgDisplayReport(r), 0);
  } catch (e) { /* diagnostics must never block opening a project */ }
}

function updateOverlay() {
  const d = STATE?.design;
  const info = $('#vp-info');
  if (!info) return;
  const drawn = (VP && VP.objects) ? VP.objects.length : 0;
  const boxed = currentBuffers.filter(o => o.placeholder).length;
  info.innerHTML = d ? `${d.name}<br>${drawn} of ${d.objects.length + d.sheets.length}`
    + ` object(s) drawn · ${VP.mode}<br>units ${d.units}`
    + (VP && VP.opaque ? '<br>solid display' : '')
    + (MISSING_GEOMETRY.length
      ? `<br><span style="color:var(--err)">${MISSING_GEOMETRY.length}` +
        ' object(s) have no readable geometry</span>'
      : '')
    + (boxed
      ? `<br><span style="color:var(--warn)">${boxed} shown as extent box`
        + ' only</span>' : '')
    + ((MISSING_GEOMETRY.length || boxed)
      ? '<br><span style="color:var(--err)">View ▸ Display Diagnostics</span>'
      : '') : '';
  const btn = $('#vt-mode');
  if (btn) btn.classList.toggle('on', VP.mode !== 'shaded');
  const sb = $('#vt-solid');
  if (sb) sb.classList.toggle('on', !!(VP && VP.opaque));
}

/* ------------------------------------------------------- drawing by point */
/* Draw with the mouse; correct with the keyboard.
   The old flow clicked two points and then threw a modal dialog over the
   viewport — over the very thing being drawn — and asked for the numbers
   again. The numbers now live in a panel beside the model: they follow the
   cursor while you drag, every one of them is editable, and typing an exact
   value and pressing Enter is the same action as clicking. Nothing is
   committed until Create, and Esc backs out of one step at a time. */

let DRAW = null;
/* {
     kind, stage: 'p1'|'p2'|'h'|'ready',
     p1, p2, height,        // metres, world coordinates
     plane, snap, name, material
   } */

const SNAP_DIVISIONS = 20;
const DRAW_TITLE = { box: 'Box by points', rectangle: 'Rectangle by points',
                     cylinder: 'Cylinder by points' };
const DRAW_STEP = {
  box: { p1: 'click the first base corner', p2: 'click the opposite corner',
         h: 'move to set the height, click to place', ready: 'ready — Create' },
  rectangle: { p1: 'click the first corner', p2: 'click the opposite corner',
               ready: 'ready — Create' },
  cylinder: { p1: 'click the centre', p2: 'click to set the radius',
              h: 'move to set the height, click to place',
              ready: 'ready — Create' }
};

function snapStep() {
  if (!VP) return 1e-3;
  const [lo, hi] = VP.bbox;
  const span = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], 1e-6);
  return niceSnapStep(span / SNAP_DIVISIONS);
}
function snapPoint(p) {
  if (!DRAW || !DRAW.snap || !VP) return p;
  const step = snapStep();
  return p.map(v => Math.round(v / step) * step);
}
function snapScalar(v) {
  if (!DRAW || !DRAW.snap) return v;
  const step = snapStep();
  return Math.round(v / step) * step;
}
function niceSnapStep(x) {
  const e = Math.pow(10, Math.floor(Math.log10(Math.max(x, 1e-12))));
  const m = x / e;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * e;
}

/* metres -> the number shown in the panel, and back. The panel works in the
   design's own units, which is what the model is dimensioned in. */
const toU = m => Number((m / (UNIT_SCALE[U()] || 1e-3)).toPrecision(9));
const fromU = v => parseFloat(v) * (UNIT_SCALE[U()] || 1e-3);

async function startPointDraw(kind) {
  if (!VP) return toastError('3-D viewport is unavailable.');
  if (!await ensureDesign()) return;
  if (MEASURE_PICK) cancelMeasurePick();
  if (MOVE) cancelInteractiveMove();
  clearPicks();
  const z = (VP.bbox && VP.bbox[0]) ? VP.bbox[0][2] : 0;
  DRAW = {
    kind, stage: 'p1',
    p1: null, p2: null, height: 0,
    plane: { normal: [0, 0, 1], point: [0, 0, z] },
    snap: true, name: '', material: 'vacuum'
  };
  buildDrawPanel();
  suggestName('shape', kind).then(n => {
    const f = $('#dw-name');
    if (DRAW && f && !f.value) { f.value = n; f.placeholder = n; DRAW.name = n; }
  });
  updateDrawPanel();
  setStatus(`${DRAW_TITLE[kind] || kind}: ${DRAW_STEP[kind].p1}`, 'busy');
  $('#vp-hint').textContent =
    'click to place · type a value and press Enter · S snap · Esc back';
}

function cancelPointDraw() {
  DRAW = null;
  VP && VP.setDraft(null);
  const box = $('#vp-draw');
  if (box) { box.classList.remove('on'); box.innerHTML = ''; }
  const lab = $('#vp-dim');
  if (lab) lab.style.display = 'none';
  $('#vp-hint').textContent = 'click select · LMB rotate · Shift+LMB / MMB pan'
    + ' · wheel zoom · dbl-click fit';
  refreshStatus();
}

/* Esc steps back through the draw rather than abandoning it: one mis-clicked
   corner should not cost the whole operation. */
function drawStepBack() {
  if (!DRAW) return;
  if (DRAW.stage === 'ready' || DRAW.stage === 'h') {
    DRAW.stage = 'p2'; DRAW.p2 = null; DRAW.height = 0;
  } else if (DRAW.stage === 'p2') {
    DRAW.stage = 'p1'; DRAW.p1 = null;
  } else {
    cancelPointDraw();
    return;
  }
  updateDrawPanel();
}

/* ------------------------------------------------------------- the panel */
function buildDrawPanel() {
  const box = $('#vp-draw');
  if (!box) return;
  box.innerHTML = '';
  const kind = DRAW.kind;
  const u = U();
  box.appendChild(el('h4', {}, DRAW_TITLE[kind] || kind,
    el('span', { class: 'step', id: 'dw-step' }, '')));

  const grid = el('div', { class: 'dgrid' });
  grid.appendChild(el('span', {}));
  for (const a of ['X', 'Y', 'Z']) grid.appendChild(el('span', { class: 'hd' }, a));
  const row = (label, prefix, readonly) => {
    grid.appendChild(el('label', {}, label));
    for (let k = 0; k < 3; k++) {
      const i = el('input', { id: `${prefix}${k}`, type: 'text',
        spellcheck: 'false' });
      if (readonly) i.readOnly = true;
      else {
        // 'input', not 'change': the preview should follow the keystrokes,
        // not wait for the field to lose focus.
        i.addEventListener('input', () => drawFieldEdited(prefix, k));
        i.addEventListener('keydown', e => {
          if (e.key === 'Enter') { e.preventDefault(); drawFieldEdited(prefix, k, true); }
        });
      }
      grid.appendChild(i);
    }
  };
  row('Cursor', 'dw-c', true);
  row(kind === 'cylinder' ? 'Centre' : 'Corner 1', 'dw-a', false);
  row(kind === 'cylinder' ? 'Rim' : 'Corner 2', 'dw-b', false);
  if (kind !== 'cylinder') row('Size', 'dw-s', false);
  box.appendChild(grid);

  if (kind === 'cylinder') {
    const r = el('div', { class: 'row' }, el('label', {}, 'Radius'),
      el('input', { id: 'dw-r', type: 'text', spellcheck: 'false' }));
    r.querySelector('input').addEventListener('input', () => drawRadiusEdited());
    r.querySelector('input').addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); drawRadiusEdited(true); } });
    box.appendChild(r);
  }
  if (kind !== 'rectangle') {
    const h = el('div', { class: 'row' }, el('label', {}, 'Height'),
      el('input', { id: 'dw-h', type: 'text', spellcheck: 'false' }));
    h.querySelector('input').addEventListener('input', () => drawHeightEdited());
    h.querySelector('input').addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); drawHeightEdited(true); } });
    box.appendChild(h);
  }

  box.appendChild(el('div', { class: 'row' }, el('label', {}, 'Name'),
    inp('dw-name', '', 'text', { placeholder: 'auto', spellcheck: 'false' })));
  const mats = (window.MATERIALS || []).map(m => m.name);
  box.appendChild(el('div', { class: 'row' }, el('label', {}, 'Material'),
    sel('dw-mat', mats.length ? mats : ['vacuum'], DRAW.material)));

  const snap = el('input', { type: 'checkbox', id: 'dw-snap',
    style: 'width:auto' });
  snap.checked = DRAW.snap;
  snap.onchange = () => { DRAW.snap = snap.checked; updateDrawPanel(); };
  box.appendChild(el('div', { class: 'row' },
    el('label', { for: 'dw-snap' }, 'Snap'), snap,
    el('span', { class: 'note', id: 'dw-snapstep', style: 'margin:0' }, '')));

  box.appendChild(el('div', { class: 'note', id: 'dw-warn' }, ''));
  box.appendChild(el('div', { class: 'note' },
    `Values are in ${u}. Click to place a point, or type the numbers and press `
    + 'Enter. Esc steps back one point.'));
  const create = el('button', { class: 'pri', id: 'dw-create',
    onclick: () => commitDraw() }, 'Create');
  box.appendChild(el('div', { class: 'acts' },
    el('button', { onclick: () => cancelPointDraw() }, 'Cancel'), create));
  box.classList.add('on');
}

function setXYZ(prefix, p) {
  for (let k = 0; k < 3; k++) {
    const f = $('#' + prefix + k);
    if (!f) continue;
    if (document.activeElement === f) continue;    // never fight the typist
    f.value = p ? String(toU(p[k])) : '';
  }
}

function updateDrawPanel(cursor) {
  if (!DRAW) return;
  const kind = DRAW.kind;
  const step = $('#dw-step');
  if (step) step.textContent = (DRAW_STEP[kind] || {})[DRAW.stage] || '';
  if (cursor) setXYZ('dw-c', cursor);
  setXYZ('dw-a', DRAW.p1);
  setXYZ('dw-b', DRAW.p2);
  if (kind !== 'cylinder') {
    const size = (DRAW.p1 && DRAW.p2)
      ? [0, 1, 2].map(k => DRAW.p2[k] - DRAW.p1[k]) : null;
    setXYZ('dw-s', size);
  }
  const rf = $('#dw-r');
  if (rf && document.activeElement !== rf)
    rf.value = (DRAW.p1 && DRAW.p2) ? String(toU(drawRadius())) : '';
  const hf = $('#dw-h');
  if (hf && document.activeElement !== hf)
    hf.value = DRAW.height ? String(toU(DRAW.height)) : (hf.value || '');
  const ss = $('#dw-snapstep');
  if (ss) ss.textContent = DRAW.snap ? fmtLen(snapStep(), U()) : 'off';
  const create = $('#dw-create');
  if (create) {
    create.disabled = !drawIsComplete();
    create.title = create.disabled ? drawBlocker() : 'Create this object';
  }
  const warn = $('#dw-warn');
  if (warn) {
    const why = drawIsComplete() ? '' : drawBlocker();
    warn.textContent = (DRAW.p1 && DRAW.p2) ? why : '';
    warn.style.color = why ? 'var(--warn)' : '';
  }
  updateDrawPreview();
}

const drawRadius = () => DRAW && DRAW.p1 && DRAW.p2
  ? Math.hypot(DRAW.p2[0] - DRAW.p1[0], DRAW.p2[1] - DRAW.p1[1],
               DRAW.p2[2] - DRAW.p1[2]) : 0;

/* Why Create is greyed out, in the words of the thing that is wrong.
   A box drawn edge-on to the camera, or two clicks that snap to the same
   grid line, gives a zero-width body — which cannot be made, and previously
   just left a dead button with no explanation. Every one of these is fixable
   by typing the missing number into the panel. */
function drawBlocker() {
  if (!DRAW) return '';
  if (!DRAW.p1) return 'Place the first point.';
  if (!DRAW.p2) return DRAW.kind === 'cylinder'
    ? 'Set the radius.' : 'Place the opposite corner.';
  const d = [0, 1, 2].map(k => Math.abs(DRAW.p2[k] - DRAW.p1[k]));
  if (DRAW.kind === 'cylinder') {
    if (drawRadius() <= 1e-12) return 'The radius is zero.';
    if (Math.abs(DRAW.height) <= 1e-12) return 'The height is zero.';
    return '';
  }
  if (DRAW.kind === 'rectangle') {
    if (d.filter(v => v > 1e-12).length < 2)
      return 'The rectangle is a line — give it width and height.';
    return '';
  }
  const zero = ['X', 'Y'].filter((_, k) => d[k] <= 1e-12);
  if (zero.length)
    return `${zero.join(' and ')} size is zero — drag further, or type it above.`;
  if (Math.abs(DRAW.height) <= 1e-12) return 'The height is zero.';
  return '';
}

function drawIsComplete() {
  if (!DRAW || !DRAW.p1 || !DRAW.p2) return false;
  if (DRAW.kind === 'rectangle') {
    const d = [0, 1, 2].map(k => Math.abs(DRAW.p2[k] - DRAW.p1[k]));
    return d.filter(v => v > 1e-12).length >= 2;
  }
  if (DRAW.kind === 'cylinder') return drawRadius() > 1e-12 && Math.abs(DRAW.height) > 1e-12;
  const d = [0, 1, 2].map(k => Math.abs(DRAW.p2[k] - DRAW.p1[k]));
  return d[0] > 1e-12 && d[1] > 1e-12 && Math.abs(DRAW.height) > 1e-12;
}

/* A field edited by hand is as good as a click: it fills the value in and,
   when the step it belongs to was the one being waited on, moves on. */
function drawFieldEdited(prefix, k, advance) {
  if (!DRAW) return;
  const v = fromU($('#' + prefix + k).value);
  if (!Number.isFinite(v)) return updateDrawPanel();
  const base = DRAW.plane.point;
  if (prefix === 'dw-a') {
    DRAW.p1 = (DRAW.p1 || base.slice()).slice();
    DRAW.p1[k] = v;
    if (DRAW.stage === 'p1' && advance) {
      DRAW.stage = 'p2';
      DRAW.plane = { normal: [0, 0, 1], point: DRAW.p1.slice() };
    }
  } else if (prefix === 'dw-b') {
    DRAW.p2 = (DRAW.p2 || (DRAW.p1 || base).slice()).slice();
    DRAW.p2[k] = v;
    if (DRAW.stage === 'p2' && advance)
      DRAW.stage = DRAW.kind === 'rectangle' ? 'ready' : 'h';
  } else if (prefix === 'dw-s') {
    if (!DRAW.p1) DRAW.p1 = base.slice();
    DRAW.p2 = (DRAW.p2 || DRAW.p1).slice();
    DRAW.p2[k] = DRAW.p1[k] + v;
    if (DRAW.stage === 'p2' && advance)
      DRAW.stage = DRAW.kind === 'rectangle' ? 'ready' : 'h';
  }
  updateDrawPanel();
  if (advance && DRAW.stage === 'ready' && drawIsComplete()) commitDraw();
}

function drawRadiusEdited(advance) {
  if (!DRAW || !DRAW.p1) return;
  const r = fromU($('#dw-r').value);
  if (!Number.isFinite(r) || r <= 0) return;
  const cur = drawRadius();
  const dir = cur > 1e-12
    ? [0, 1, 2].map(k => (DRAW.p2[k] - DRAW.p1[k]) / cur) : [1, 0, 0];
  DRAW.p2 = [0, 1, 2].map(k => DRAW.p1[k] + dir[k] * r);
  if (DRAW.stage === 'p2' && advance) DRAW.stage = 'h';
  updateDrawPanel();
  if (advance && DRAW.stage === 'ready' && drawIsComplete()) commitDraw();
}

function drawHeightEdited(advance) {
  if (!DRAW) return;
  const h = fromU($('#dw-h').value);
  if (!Number.isFinite(h)) return;
  DRAW.height = h;
  if (DRAW.stage === 'h') DRAW.stage = 'ready';
  updateDrawPanel();
  if (advance && drawIsComplete()) commitDraw();
}

/* ------------------------------------------------------------- the picks */
function drawPickHover(px, py) {
  if (!DRAW) return;
  updateCursorReadout(px, py);
  if (DRAW.stage === 'h') {
    const h = heightFromCursor(px, py);
    if (h !== null) { DRAW.height = snapScalar(h); updateDrawPanel(); }
    return;
  }
  const hit = VP.planePoint(px, py, DRAW.plane);
  if (!hit) return;
  const p = snapPoint(hit.point);
  if (DRAW.stage === 'p1') DRAW.p1 = p;
  else if (DRAW.stage === 'p2') DRAW.p2 = p;
  updateDrawPanel(p);
}

function drawPickClick(px, py) {
  if (!DRAW) return false;
  if (DRAW.stage === 'h') {
    const h = heightFromCursor(px, py);
    if (h !== null) DRAW.height = snapScalar(h);
    DRAW.stage = 'ready';
    updateDrawPanel();
    if (drawIsComplete()) commitDraw();
    return true;
  }
  const hit = VP.planePoint(px, py, DRAW.plane);
  if (!hit) return true;
  const p = snapPoint(hit.point);
  if (DRAW.stage === 'p1') {
    DRAW.p1 = p;
    // the plane the first point landed on carries the rest of the draw
    DRAW.plane = { normal: [0, 0, 1], point: p.slice() };
    DRAW.stage = 'p2';
  } else if (DRAW.stage === 'p2') {
    DRAW.p2 = p;
    if (DRAW.kind === 'rectangle') {
      DRAW.stage = 'ready';
      updateDrawPanel();
      if (drawIsComplete()) commitDraw();
      return true;
    }
    DRAW.stage = 'h';
    if (!DRAW.height) DRAW.height = snapStep();
  }
  setStatus(`${DRAW_TITLE[DRAW.kind]}: ${DRAW_STEP[DRAW.kind][DRAW.stage]}`,
    'busy');
  updateDrawPanel();
  return true;
}

/* The height step. The cursor is off the base plane by then, so the ray is
   closed against the vertical line through the second corner — the point on
   that line nearest the ray is the height the cursor is pointing at.

   With the line P(t) = a + t n and the ray Q(s) = o + s d, minimising
   |P - Q|^2 gives t = (n·w0 - (d·n)(d·w0)) / (1 - (d·n)^2), where w0 = o - a.
   The sign of that had been inverted, so the box grew downwards when the
   cursor went up and the preview ran away from the mouse. */
function heightFromCursor(px, py) {
  if (!DRAW || !DRAW.p2 || !VP.ray) return null;
  const r = VP.ray(px, py);
  if (!r) return null;
  const o = r.origin, d = r.dir, a = DRAW.p2, n = [0, 0, 1];
  const w0 = [o[0] - a[0], o[1] - a[1], o[2] - a[2]];
  const b = d[0] * n[0] + d[1] * n[1] + d[2] * n[2];
  const dw = d[0] * w0[0] + d[1] * w0[1] + d[2] * w0[2];
  const nw = n[0] * w0[0] + n[1] * w0[1] + n[2] * w0[2];
  const den = 1 - b * b;                       // both directions are unit
  if (Math.abs(den) < 1e-9) return null;
  return (nw - b * dw) / den;
}

/* ------------------------------------------------------------ the preview */
function updateDrawPreview() {
  if (!DRAW || !VP) return;
  const lab = $('#vp-dim');
  const a = DRAW.p1, b = DRAW.p2;
  if (!a) { VP.setDraft(null); if (lab) lab.style.display = 'none'; return; }
  if (!b) { VP.setDraft(null); if (lab) lab.style.display = 'none'; return; }

  let strip;
  let text;
  if (DRAW.kind === 'cylinder') {
    strip = circleStrip(a, drawRadius(), DRAW.height);
    text = `r ${fmtLen(drawRadius(), U())}`
      + (DRAW.height ? ` × h ${fmtLen(Math.abs(DRAW.height), U())}` : '');
  } else if (DRAW.kind === 'rectangle' || !DRAW.height) {
    strip = [a, [b[0], a[1], a[2]], b, [a[0], b[1], b[2]], a];
    text = [0, 1].map(k => fmtLen(Math.abs(b[k] - a[k]), U())).join(' × ');
  } else {
    strip = boxStrip(a, b, DRAW.height);
    text = [0, 1].map(k => fmtLen(Math.abs(b[k] - a[k]), U())).join(' × ')
      + ' × ' + fmtLen(Math.abs(DRAW.height), U());
  }
  VP.setDraft(strip);
  const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2,
               (a[2] + b[2]) / 2 + DRAW.height / 2];
  const s = VP.project(mid);
  if (lab && s) {
    lab.textContent = text;
    lab.style.left = Math.round(s.x) + 'px';
    lab.style.top = Math.round(s.y) + 'px';
    lab.style.display = 'block';
  }
}

/* All twelve edges of a box as one line strip (the viewport draws the draft
   as a single strip, so the path revisits corners rather than lifting). */
function boxStrip(a, b, h) {
  const z0 = a[2], z1 = a[2] + h;
  const c = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
  const lo = c.map(p => [p[0], p[1], z0]);
  const hi = c.map(p => [p[0], p[1], z1]);
  return [lo[0], lo[1], lo[2], lo[3], lo[0],
          hi[0], hi[1], lo[1], hi[1], hi[2], lo[2], hi[2], hi[3], lo[3],
          hi[3], hi[0]];
}

function circleStrip(centre, r, h, n = 48) {
  const ring = z => {
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const t = 2 * Math.PI * i / n;
      pts.push([centre[0] + r * Math.cos(t), centre[1] + r * Math.sin(t), z]);
    }
    return pts;
  };
  const lo = ring(centre[2]);
  if (!h) return lo;
  const hi = ring(centre[2] + h);
  return lo.concat([hi[0]], hi, [lo[n]]);
}

/* -------------------------------------------------------------- commit */
async function commitDraw() {
  if (!DRAW || !drawIsComplete()) return;
  const d = DRAW;
  const name = ($('#dw-name') && $('#dw-name').value) || '';
  const material = ($('#dw-mat') && $('#dw-mat').value) || 'vacuum';
  const m = v => String(v) + 'm';
  const lo = [0, 1, 2].map(k => Math.min(d.p1[k], d.p2[k]));
  const p = {};
  let shape = d.kind;
  if (d.kind === 'rectangle') {
    const size = [0, 1, 2].map(k => Math.abs(d.p2[k] - d.p1[k]));
    const flat = size.map(v => v <= 1e-12);
    p.position = lo.map(m);
    p.plane = flat[2] ? 'xy' : flat[0] ? 'yz' : 'xz';
    const axes = { xy: [0, 1], yz: [1, 2], xz: [0, 2] }[p.plane];
    p.size = [m(size[axes[0]]), m(size[axes[1]])];
  } else if (d.kind === 'cylinder') {
    p.center = d.p1.map(m);
    p.radius = m(drawRadius());
    p.height = m(Math.abs(d.height));
    p.axis = [0, 0, d.height < 0 ? -1 : 1];
    if (d.height < 0) p.center = [d.p1[0], d.p1[1], d.p1[2]].map(m);
  } else {
    const size = [Math.abs(d.p2[0] - d.p1[0]), Math.abs(d.p2[1] - d.p1[1]),
                  Math.abs(d.height)];
    p.position = [lo[0], lo[1], Math.min(d.p1[2], d.p1[2] + d.height)].map(m);
    p.size = size.map(m);
  }
  cancelPointDraw();
  await guard(() => rpc('modeler.draw',
    { shape, name, material, params: p }));
  await refreshGeometry(false);
}


/* ------------------------------------------------------- moving by points */
/* Point at where it should go, or type how far.
   Arrange > Move asked for a translation vector in a modal, which means
   knowing the numbers before you start. A modeller lets you say "from this
   corner to that one" with the mouse and correct the numbers afterwards, in
   the same panel, without the model being hidden behind a dialog. */
let MOVE = null;   // { names, stage: 'p1'|'p2'|'ready', p1, p2, plane, snap }

function startInteractiveMove(names) {
  if (!VP) return toastError('3-D viewport is unavailable.');
  const want = (names && names.length) ? names : (STATE?.selection || []);
  if (!want.length)
    return toastError('Select the object(s) to move first');
  if (DRAW) cancelPointDraw();
  if (MEASURE_PICK) cancelMeasurePick();
  const box = VP.boundsOf(want);
  const start = box
    ? [(box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2, box[0][2]]
    : [0, 0, 0];
  MOVE = {
    names: want.slice(), stage: 'p1', p1: null, p2: null, snap: true,
    plane: { normal: [0, 0, 1], point: start.slice() }, box
  };
  buildMovePanel();
  updateMovePanel();
  setStatus(`Move ${want.join(', ')}: click the point to move from`, 'busy');
  $('#vp-hint').textContent =
    'click a base point, then the destination · or type ΔX/ΔY/ΔZ · Esc backs out';
}

function cancelInteractiveMove() {
  MOVE = null;
  VP && VP.setDraft(null);
  const box = $('#vp-draw');
  if (box) { box.classList.remove('on'); box.innerHTML = ''; }
  const lab = $('#vp-dim');
  if (lab) lab.style.display = 'none';
  $('#vp-hint').textContent = 'click select · LMB rotate · Shift+LMB / MMB pan'
    + ' · wheel zoom · dbl-click fit';
  refreshStatus();
}

function moveStepBack() {
  if (!MOVE) return;
  if (MOVE.stage === 'ready' || MOVE.stage === 'p2') {
    MOVE.stage = 'p1'; MOVE.p1 = null; MOVE.p2 = null;
    updateMovePanel();
  } else {
    cancelInteractiveMove();
  }
}

function buildMovePanel() {
  const box = $('#vp-draw');
  if (!box) return;
  box.innerHTML = '';
  box.appendChild(el('h4', {}, 'Move ' +
    (MOVE.names.length > 1 ? MOVE.names.length + ' objects' : MOVE.names[0]),
    el('span', { class: 'step', id: 'mv-step' }, '')));

  const grid = el('div', { class: 'dgrid' });
  grid.appendChild(el('span', {}));
  for (const a of ['X', 'Y', 'Z']) grid.appendChild(el('span', { class: 'hd' }, a));
  const row = (label, prefix, readonly) => {
    grid.appendChild(el('label', {}, label));
    for (let k = 0; k < 3; k++) {
      const i = el('input', { id: `${prefix}${k}`, type: 'text',
        spellcheck: 'false' });
      if (readonly) i.readOnly = true;
      else {
        i.addEventListener('input', () => moveFieldEdited(prefix, k));
        i.addEventListener('keydown', e => {
          if (e.key === 'Enter') { e.preventDefault(); moveFieldEdited(prefix, k, true); }
        });
      }
      grid.appendChild(i);
    }
  };
  row('Cursor', 'mv-c', true);
  row('From', 'mv-a', false);
  row('To', 'mv-b', false);
  row('Delta', 'mv-d', false);
  box.appendChild(grid);

  const dist = el('div', { class: 'row' }, el('label', {}, 'Distance'),
    el('input', { id: 'mv-len', type: 'text', spellcheck: 'false' }));
  dist.querySelector('input').addEventListener('input', () => moveLengthEdited());
  dist.querySelector('input').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); moveLengthEdited(true); } });
  box.appendChild(dist);

  const copy = el('input', { type: 'checkbox', id: 'mv-copy',
    style: 'width:auto' });
  box.appendChild(el('div', { class: 'row' },
    el('label', { for: 'mv-copy' }, 'Copy'), copy,
    el('span', { class: 'note', style: 'margin:0' },
      'leave a duplicate behind')));

  const snap = el('input', { type: 'checkbox', id: 'mv-snap',
    style: 'width:auto' });
  snap.checked = MOVE.snap;
  snap.onchange = () => { MOVE.snap = snap.checked; updateMovePanel(); };
  box.appendChild(el('div', { class: 'row' },
    el('label', { for: 'mv-snap' }, 'Snap'), snap,
    el('span', { class: 'note', id: 'mv-snapstep', style: 'margin:0' }, '')));

  box.appendChild(el('div', { class: 'note' },
    `Values are in ${U()}. Click a base point then the destination, or type `
    + 'the delta and press Enter. Esc backs out one step.'));
  box.appendChild(el('div', { class: 'acts' },
    el('button', { onclick: () => cancelInteractiveMove() }, 'Cancel'),
    el('button', { class: 'pri', id: 'mv-apply',
      onclick: () => commitMove() }, 'Apply')));
  box.classList.add('on');
}

const moveDelta = () => (MOVE && MOVE.p1 && MOVE.p2)
  ? [0, 1, 2].map(k => MOVE.p2[k] - MOVE.p1[k]) : null;

function moveIsReady() {
  const d = moveDelta();
  return !!d && d.some(v => Math.abs(v) > 1e-12);
}

function updateMovePanel(cursor) {
  if (!MOVE) return;
  const step = $('#mv-step');
  if (step) step.textContent = MOVE.stage === 'p1' ? 'click the base point'
    : MOVE.stage === 'p2' ? 'click the destination' : 'ready — Apply';
  if (cursor) setXYZ('mv-c', cursor);
  setXYZ('mv-a', MOVE.p1);
  setXYZ('mv-b', MOVE.p2);
  const d = moveDelta();
  setXYZ('mv-d', d);
  const lf = $('#mv-len');
  if (lf && document.activeElement !== lf)
    lf.value = d ? String(toU(Math.hypot(d[0], d[1], d[2]))) : '';
  const ss = $('#mv-snapstep');
  if (ss) ss.textContent = MOVE.snap ? fmtLen(snapStep(), U()) : 'off';
  const ok = $('#mv-apply');
  if (ok) ok.disabled = !moveIsReady();
  updateMovePreview();
}

function moveFieldEdited(prefix, k, advance) {
  if (!MOVE) return;
  const v = fromU($('#' + prefix + k).value);
  if (!Number.isFinite(v)) return updateMovePanel();
  const base = MOVE.plane.point;
  if (prefix === 'mv-a') {
    MOVE.p1 = (MOVE.p1 || base.slice()).slice();
    MOVE.p1[k] = v;
    if (MOVE.stage === 'p1' && advance) {
      MOVE.stage = 'p2';
      MOVE.plane = { normal: [0, 0, 1], point: MOVE.p1.slice() };
    }
  } else if (prefix === 'mv-b') {
    MOVE.p2 = (MOVE.p2 || (MOVE.p1 || base).slice()).slice();
    MOVE.p2[k] = v;
    if (MOVE.stage !== 'ready' && advance) MOVE.stage = 'ready';
  } else if (prefix === 'mv-d') {
    if (!MOVE.p1) MOVE.p1 = base.slice();
    MOVE.p2 = (MOVE.p2 || MOVE.p1).slice();
    MOVE.p2[k] = MOVE.p1[k] + v;
    if (MOVE.stage !== 'ready' && advance) MOVE.stage = 'ready';
  }
  updateMovePanel();
  if (advance && MOVE.stage === 'ready' && moveIsReady()) commitMove();
}

/* Typing a distance keeps the direction and changes how far — which is the
   normal way to place something a known distance along a chosen line. */
function moveLengthEdited(advance) {
  if (!MOVE) return;
  const want = fromU($('#mv-len').value);
  const d = moveDelta();
  if (!Number.isFinite(want) || !d) return;
  const len = Math.hypot(d[0], d[1], d[2]);
  if (len <= 1e-15) return;
  MOVE.p2 = [0, 1, 2].map(k => MOVE.p1[k] + d[k] / len * want);
  if (MOVE.stage !== 'ready') MOVE.stage = 'ready';
  updateMovePanel();
  if (advance && moveIsReady()) commitMove();
}

function movePickHover(px, py) {
  if (!MOVE) return;
  updateCursorReadout(px, py);
  const hit = VP.planePoint(px, py, MOVE.stage === 'p1' ? null : MOVE.plane);
  if (!hit) return;
  const p = MOVE.snap && MOVE.stage !== 'p1' ? snapPointFor(MOVE, hit.point)
    : hit.point;
  if (MOVE.stage === 'p1') MOVE.p1 = p;
  else if (MOVE.stage === 'p2') MOVE.p2 = p;
  updateMovePanel(p);
}

function movePickClick(px, py) {
  if (!MOVE) return false;
  const hit = VP.planePoint(px, py, MOVE.stage === 'p1' ? null : MOVE.plane);
  if (!hit) return true;
  const p = MOVE.snap && MOVE.stage !== 'p1' ? snapPointFor(MOVE, hit.point)
    : hit.point;
  if (MOVE.stage === 'p1') {
    MOVE.p1 = p;
    MOVE.plane = { normal: [0, 0, 1], point: p.slice() };
    MOVE.stage = 'p2';
    setStatus('Move: click the destination (or type the delta)', 'busy');
  } else {
    MOVE.p2 = p;
    MOVE.stage = 'ready';
    updateMovePanel();
    if (moveIsReady()) commitMove();
    return true;
  }
  updateMovePanel();
  return true;
}

/* the snap grid, shared with the draw tool but keyed off whichever is live */
function snapPointFor(state, p) {
  if (!state || !state.snap || !VP) return p;
  const step = snapStep();
  return p.map(v => Math.round(v / step) * step);
}

function updateMovePreview() {
  if (!MOVE || !VP) return;
  const lab = $('#vp-dim');
  const d = moveDelta();
  if (!MOVE.p1 || !d) { VP.setDraft(null); if (lab) lab.style.display = 'none'; return; }
  const strip = [MOVE.p1, MOVE.p2];
  const box = MOVE.box;
  if (box) {
    // the selection's own extent, drawn where it would land
    const lo = [0, 1, 2].map(k => box[0][k] + d[k]);
    const hi = [0, 1, 2].map(k => box[1][k] + d[k]);
    strip.push(...ghostBox(lo, hi));
  }
  VP.setDraft(strip);
  const mid = [0, 1, 2].map(k => (MOVE.p1[k] + MOVE.p2[k]) / 2);
  const sp = VP.project(mid);
  if (lab && sp) {
    lab.textContent = fmtLen(Math.hypot(d[0], d[1], d[2]), U()) + '  ('
      + d.map(v => fmtLen(v, U())).join(', ') + ')';
    lab.style.left = Math.round(sp.x) + 'px';
    lab.style.top = Math.round(sp.y) + 'px';
    lab.style.display = 'block';
  }
}

function ghostBox(lo, hi) {
  const c = [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]];
  const a = c.map(p => [p[0], p[1], lo[2]]);
  const b = c.map(p => [p[0], p[1], hi[2]]);
  return [a[0], a[1], a[2], a[3], a[0], b[0], b[1], a[1], b[1], b[2], a[2],
          b[2], b[3], a[3], b[3], b[0]];
}

async function commitMove() {
  if (!MOVE || !moveIsReady()) return;
  const d = moveDelta();
  const names = MOVE.names.slice();
  const copy = !!($('#mv-copy') && $('#mv-copy').checked);
  cancelInteractiveMove();
  const m = v => String(v) + 'm';
  await guard(async () => {
    if (copy) {
      await rpc('modeler.duplicate', { names, mode: 'line', count: 2,
        params: { vector: d.map(m) }, attach: false });
    } else {
      await rpc('modeler.transform', { names, op: 'move',
        params: { dx: m(d[0]), dy: m(d[1]), dz: m(d[2]) } });
    }
    await refreshGeometry(false);
  });
}

/* -------------------------------------------------- ports, by picking */
/* "This conductor against that ground."
   A port is a statement about two pieces of metal, and that is how an
   engineer says it at the screen: click the signal, click the return. The
   dialog form -- a plane, a value, a window -- asks for the answer in
   coordinates the user would have to look up first, and it is why assigning
   a port on an imported board was the slowest thing in the program. The
   picks stay on screen in port colours while the panel shows what will be
   built, and nothing is created until Apply. */
let PORTPICK = null;   // { kind, stage:'signal'|'gnd', signal:[], gnd:[] }

async function startPortPick(kind) {
  if (!VP) return toastError('3-D viewport is unavailable.');
  if (!await ensureDesign()) return;
  if (DRAW) cancelPointDraw();
  if (MOVE) cancelInteractiveMove();
  if (MEASURE_PICK) cancelMeasurePick();
  clearPicks();
  setSelectMode('face');
  PORTPICK = { kind, stage: 'signal', signal: [], gnd: [] };
  buildPortPanel();
  updatePortPanel();
  setStatus(kind === 'wave'
    ? 'Wave port: click the port cross-section face'
    : 'Lumped port: click the signal conductor face', 'busy');
  $('#vp-hint').textContent =
    'click the signal face, then the ground face · Ctrl+click adds faces · '
    + 'Esc cancels';
}

function cancelPortPick() {
  PORTPICK = null;
  const box = $('#vp-draw');
  if (box) { box.classList.remove('on'); box.innerHTML = ''; }
  VP && VP.setFaceSelection(FACE_PICKS);
  $('#vp-hint').textContent = 'click select · LMB rotate · Shift+LMB / MMB pan'
    + ' · wheel zoom · dbl-click fit';
  refreshStatus();
}

/* a face click while the flow is live lands in whichever row is armed */
function portPickFace(rec, add) {
  if (!PORTPICK) return false;
  const list = PORTPICK.stage === 'gnd' ? PORTPICK.gnd : PORTPICK.signal;
  const same = (a, b) => a.object === b.object && a.face === b.face;
  const i = list.findIndex(f => same(f, rec));
  if (i >= 0) list.splice(i, 1);
  else if (add) list.push(rec);
  else { list.length = 0; list.push(rec); }
  if (!add && PORTPICK.stage === 'signal' && PORTPICK.kind !== 'wave')
    PORTPICK.stage = 'gnd';               // straight on to the return path
  VP.setFaceSelection(PORTPICK.signal.concat(PORTPICK.gnd));
  updatePortPanel();
  return true;
}

function buildPortPanel() {
  const box = $('#vp-draw');
  if (!box) return;
  const wave = PORTPICK.kind === 'wave';
  box.innerHTML = '';
  box.appendChild(el('h4', {}, wave ? 'Wave Port' : 'Lumped Port',
    el('span', { class: 'step', id: 'pp-step' }, '')));

  const row = (id, label, hint) => {
    const b = el('button', { id: 'pp-btn-' + id, class: 'nav',
      style: 'flex:1;text-align:left;padding:4px 8px;border:1px solid '
        + 'var(--border);border-radius:4px;background:var(--panel-alt);'
        + 'cursor:pointer',
      onclick: () => { PORTPICK.stage = id; updatePortPanel(); } }, label);
    box.appendChild(el('div', { class: 'row' }, b,
      el('span', { class: 'note', id: 'pp-' + id, style: 'margin:0' }, hint)));
  };
  row('signal', wave ? 'Port face' : 'Signal', 'none picked');
  if (!wave || true) row('gnd', wave ? 'Reference (optional)' : 'Ground',
    'none picked');

  if (wave) {
    box.appendChild(el('div', { class: 'row' }, el('label', {}, 'Modes'),
      el('input', { id: 'pp-modes', type: 'number', value: '1', min: '1',
        max: '8' })));
    box.appendChild(el('div', { class: 'note' },
      'The port is assigned to the picked face. A reference pick adds the '
      + 'integration line that turns the modal impedance into V²/2P — pick it '
      + 'for coax, microstrip and any other TEM line.'));
  } else {
    box.appendChild(el('div', { class: 'row' }, el('label', {}, 'Impedance [Ω]'),
      el('input', { id: 'pp-z', type: 'text', value: '50' })));
    box.appendChild(el('div', { class: 'note' },
      'A sheet is created across the gap between the two picks and the port '
      + 'is assigned to it, with the integration line running ground → '
      + 'signal.'));
  }
  box.appendChild(el('div', { class: 'acts' },
    el('button', { onclick: () => cancelPortPick() }, 'Cancel'),
    el('button', { class: 'pri', id: 'pp-apply',
      onclick: () => commitPortPick() }, 'Apply')));
  box.classList.add('on');
}

function updatePortPanel() {
  if (!PORTPICK) return;
  const wave = PORTPICK.kind === 'wave';
  const describe = (list) => list.length
    ? `${list.length} face(s) on ` +
      [...new Set(list.map(f => f.object))].join(', ')
    : 'none picked';
  for (const id of ['signal', 'gnd']) {
    const lab = $('#pp-' + id);
    if (lab) lab.textContent = describe(PORTPICK[id === 'gnd' ? 'gnd' : 'signal']);
    const btn = $('#pp-btn-' + id);
    if (btn) btn.style.outline = PORTPICK.stage === id
      ? '2px solid var(--accent)' : 'none';
  }
  const step = $('#pp-step');
  if (step) step.textContent = PORTPICK.stage === 'signal'
    ? (wave ? 'click the port face' : 'click the signal face')
    : 'click the ground face';
  const ok = $('#pp-apply');
  if (ok) ok.disabled = !PORTPICK.signal.length
    || (!wave && !PORTPICK.gnd.length);
}

async function commitPortPick() {
  if (!PORTPICK) return;
  const { kind, signal, gnd } = PORTPICK;
  const params = kind === 'wave'
    ? { modes: parseInt(($('#pp-modes') || {}).value) || 1 }
    : { impedance: parseFloat(($('#pp-z') || {}).value) || 50 };
  cancelPortPick();
  clearPicks();
  await guard(async () => {
    await rpc('excitation.assignBetween',
      { kind, signal, ground: gnd, params });
    await refreshAssignments();
    await refreshGeometry(false);
  });
}

/* ------------------------------------------------------- context menus */
/* Right-click, where a modeller puts the commands that act on what is under
   the cursor: the pick modes, the assignments, the edit operations and
   Properties. Nothing here is new functionality — it is the same commands the
   menus run, reachable where the hand already is. */
let CTX = null;

function closeContext() {
  if (CTX) { CTX.remove(); CTX = null; }
}
document.addEventListener('click', closeContext);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeContext(); });

function contextMenu(x, y, items) {
  closeContext();
  const m = el('div', { class: 'ctx' });
  for (const it of items) {
    if (!it) { m.appendChild(el('hr')); continue; }
    const [label, fn, enabled] = it;
    const on = enabled === undefined ? true : !!enabled;
    const b = el('button', { onclick: (ev) => {
      ev.stopPropagation();
      closeContext();
      if (on) fn();
    } }, label);
    if (!on) b.disabled = true;
    m.appendChild(b);
  }
  m.style.left = '0px';
  m.style.top = '0px';
  document.body.appendChild(m);
  // keep it on screen
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, window.innerWidth - r.width - 6) + 'px';
  m.style.top = Math.min(y, window.innerHeight - r.height - 6) + 'px';
  m.addEventListener('contextmenu', e => e.preventDefault());
  CTX = m;
  return m;
}

/* The viewport menu depends on what was hit and on the pick mode. */
function viewportContext(hit, ev) {
  const name = hit && hit.name;
  if (name && !(STATE.selection || []).includes(name) && SEL_MODE === 'object')
    setSelection([name]);
  if (name && SEL_MODE === 'face' && hit.face >= 0 && hit.meta
      && !FACE_PICKS.some(f => f.object === name && f.face === hit.face))
    pickFace(hit, false);

  const hasFaces = FACE_PICKS.length > 0;
  const hasSel = (STATE.selection || []).length > 0;
  const items = [
    ['Select Objects' + (SEL_MODE === 'object' ? '  ✓' : ''),
      () => setSelectMode('object')],
    ['Select Faces' + (SEL_MODE === 'face' ? '  ✓' : ''),
      () => setSelectMode('face')],
    ['Select Point'+(SEL_MODE==='point'?'  ✓':''),()=>setSelectMode('point')],
    ['Measure Point to Point',()=>startMeasurePick('distance')],
    ['Keep Measurement',()=>keepMeasurement(),!!MEASURE],
    ['Show / Hide Measurements',()=>toggleMeasurements()],
    ['Clear Kept Measurements',()=>clearKeptMeasurements()],
    ['Select Edges' + (SEL_MODE === 'edge' ? '  ✓' : ''),
      () => setSelectMode('edge')],
    ['Box Select (Ctrl+drag)', armBandSelect],
    null,
    ['Assign Boundary…', dlgBoundary, hasFaces || hasSel],
    ['Port by Picking ▸ Lumped (signal, ground)',
      () => startPortPick('lumped')],
    ['Port by Picking ▸ Wave', () => startPortPick('wave')],
    ['Assign Wave Port…', () => dlgExcitation('wave'), hasFaces || hasSel],
    ['Assign Lumped Port…', () => dlgExcitation('lumped'), hasFaces || hasSel],
    ['Add Mesh Operation…', dlgMeshOp, hasFaces || hasSel],
    null,
    ['Sweep Face Along Normal…', () => dlgFaceOp('sweep'), hasFaces],
    ['Move Faces…', () => dlgFaceOp('move'), hasFaces],
    null,
    ['Move by Two Points…', () => startInteractiveMove(), hasSel],
    ['Arrange ▸ Move…', () => dlgTransform('move'), hasSel],
    ['Arrange ▸ Rotate…', () => dlgTransform('rotate'), hasSel],
    ['Duplicate ▸ Along Line…', () => dlgDuplicate('line'), hasSel],
    ['Boolean…', dlgBoolean, hasSel],
    null,
    ['Copy', () => editCopy(false), hasSel],
    ['Paste', editPaste, !!STATE.history?.clipboard],
    ['Delete', deleteSelection, hasSel],
    null,
    ['Fit All', fitView],
    ['View ▸ Isometric', () => VP.view('iso')],
    null,
    ['Properties…', () => name && showProps('object', name), !!name]
  ];
  contextMenu(ev.clientX, ev.clientY, items);
}

/* The project tree menu: what applies to the node that was right-clicked. */
function treeContext(ev, type, name, extra) {
  ev.preventDefault();
  ev.stopPropagation();
  const items = [];
  if (type === 'object') {
    if (!(STATE.selection || []).includes(name)) setSelection([name]);
    items.push(
      ['Properties…', () => showProps('object', name)],
      ['Zoom to Object', () => fitSelection([name])],
      ['Rename…', () => dlgRename(name)],
      null,
      ['Move by Two Points…', () => startInteractiveMove([name])],
      ['Arrange ▸ Move…', () => dlgTransform('move')],
      ['Duplicate ▸ Along Line…', () => dlgDuplicate('line')],
      ['Boolean…', dlgBoolean],
      null,
      ['Assign Boundary…', dlgBoundary],
      ['Add Mesh Operation…', dlgMeshOp],
      null,
      ['Hide', () => guard(async () => {
        await rpc('modeler.setProperty',
          { name, prop: 'visible', value: false });
        await refreshGeometry(false);
      })],
      ['Show All', () => guard(async () => {
        for (const o of STATE.design.objects)
          if (o.visible === false)
            await rpc('modeler.setProperty',
              { name: o.name, prop: 'visible', value: true });
        await refreshGeometry(false);
      })],
      null,
      ['Delete', () => guard(() => rpc('modeler.delete', { names: [name] })
        .then(() => refreshGeometry(false)))]);
  } else if (type === 'boundary') {
    items.push(['Properties…', () => showProps('boundary', name)],
      ['Delete', () => guard(() => rpc('boundary.delete', { name })
        .then(refreshAssignments))]);
  } else if (type === 'port') {
    items.push(['Properties…', () => showProps('port', name)],
      ['Delete', () => guard(() => rpc('excitation.delete', { name })
        .then(refreshAssignments))]);
  } else if (type === 'setup') {
    items.push(['Properties…', () => showProps('setup', name)],
      ['Add Frequency Sweep…', () => dlgSweep(name)],
      ['Analyze', dlgAnalyze],
      null,
      ['Delete', () => guard(() => rpc('analysis.deleteSetup', { name }))]);
  } else if (type === 'mesh') {
    items.push(['Add Mesh Operation…', dlgMeshOp],
      ['Generate Mesh…', dlgMesh],
      ['Show Mesh', () => showMesh(true)]);
  } else if (type === 'meshop') {
    items.push(['Properties…', () => showProps('meshop', name)],
      ['Delete', () => guard(() => rpc('mesh.deleteOperation', { name }))]);
  } else if (type === 'design') {
    items.push(
      ['Set as Active Design', () => guard(() => rpc('project.setDesign',
        { name }).then(() => { resetDocumentViews();
          return refreshGeometry(true); }))],
      ['Rename Design…', () => dlgRenameDesign(name)],
      null,
      ['Insert Design', () => guard(() => rpc('project.insertDesign')
        .then(() => refreshGeometry(true)))],
      ['Delete Design', () => guard(async () => {
        await rpc('project.deleteDesign', { name });
        resetDocumentViews();
        await refreshGeometry(true);
      }), (STATE?.project?.designs || []).length > 1]);
  } else if (type === 'project') {
    items.push(
      ['Save Project', () => saveProject(false)],
      ['Save Project As…', () => saveProjectAs()],
      null,
      ['Insert Design', () => guard(() => rpc('project.insertDesign')
        .then(() => refreshGeometry(true)))],
      null,
      ['Close Project', closeProject]);
  } else if (type === 'modeler') {
    items.push(['Box…', () => dlgDraw('box')],
      ['Cylinder…', () => dlgDraw('cylinder')],
      ['Sphere…', () => dlgDraw('sphere')],
      null, ['Import CAD…', dlgImportCad],
      null, ['Select All', () => setSelection(objNames())]);
  } else {
    items.push(['Properties…', () => showProps(type, name)]);
  }
  contextMenu(ev.clientX, ev.clientY, items);
}

function dlgRenameDesign(name) {
  const body = el('div');
  body.appendChild(field('Design name', inp('rd-name', name)));
  dialog({ title: 'Rename Design', body, ok: 'Rename', onOk: () =>
    guard(() => rpc('project.renameDesign',
      { name, newName: gv('rd-name') })) });
}

function dlgRename(name) {
  const body = el('div');
  body.appendChild(field('Name', inp('rn-name', name)));
  dialog({ title: 'Rename', body, ok: 'Rename', onOk: async () => {
    await guard(async () => {
      await rpc('modeler.setProperty',
        { name, prop: 'name', value: gv('rn-name') });
      await refreshGeometry(false);
    });
  }});
}

/* ------------------------------------------------------- selection modes */
/* Object, face and edge picking, as in any modeller: the mode decides what a
   click means, and what an assignment dialog will offer as its target. */
let SEL_MODE = 'object';
let FACE_PICKS = [];
let EDGE_PICKS = [];
let POINT_PICKS = [];

/* Measurement.
   Every pick answers the question you had when you clicked: how long is that
   line, how big is that face, how far apart are those two things. The number
   is asked for from the server (which has the real geometry) and shown in the
   viewport next to the measured span, with the span itself drawn in 3-D. */
let MEASURE = null;
let POINT_MEASURE_PINNED=false, MEASURE_REVISION=0;

async function refreshMeasure() {
  if(POINT_MEASURE_PINNED || MEASURE_PICK)return;
  const revision=++MEASURE_REVISION;
  const box = $('#vp-measure');
  const nothing = !FACE_PICKS.length && !EDGE_PICKS.length
    && !(STATE?.selection || []).length;
  if (nothing) {
    MEASURE = null;
    VP && VP.setMeasure(null);
    if (box) box.style.display = 'none';
    placeMeasureLabel();
    return;
  }
  try {
    const result = await rpc('modeler.measure', {});
    if(revision!==MEASURE_REVISION || POINT_MEASURE_PINNED || MEASURE_PICK)return;
    MEASURE=result;
  } catch (e) { if(revision!==MEASURE_REVISION || POINT_MEASURE_PINNED || MEASURE_PICK)return; MEASURE = null; }
  VP && VP.setMeasure(MEASURE && MEASURE.line);
  if (box) {
    box.textContent = MEASURE ? MEASURE.text + (MEASURE.accuracy ? ' — ' + MEASURE.accuracy : '') : '';
    box.style.display = MEASURE && MEASURE.text ? 'block' : 'none';
  }
  placeMeasureLabel();
}

/* The distance is labelled at the midpoint of the span it measures, projected
   to the screen — a number floating over the gap it belongs to, which is what
   a dimension is. */
function placeMeasureLabel() {
  const lab = $('#vp-dim');
  if (!lab) return;
  if (!MEASUREMENTS_VISIBLE || !MEASURE || !MEASURE.line || MEASURE.distance == null || !VP) {
    lab.style.display = 'none';
    return;
  }
  const a = MEASURE.line[0], b = MEASURE.line[1];
  const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2];
  const p = VP.project(mid);
  if (!p) { lab.style.display = 'none'; return; }
  lab.textContent = fmtLen(MEASURE.distance, U());
  lab.style.left = Math.round(p.x) + 'px';
  lab.style.top = Math.round(p.y) + 'px';
  lab.style.display = 'block';
}

function setSelectMode(m) {
  POINT_MEASURE_PINNED=false;++MEASURE_REVISION;
  SEL_MODE = m;
  if(VP){VP.selectMode=m;VP.setHover(null);}
  POINT_PICKS=[];VP && VP.setPointSelection([]);
  if (m !== 'face') { FACE_PICKS = []; VP && VP.setFaceSelection([]); }
  if (m !== 'edge') { EDGE_PICKS = []; VP && VP.setEdgeSelection([]); }
  refreshMeasure();
  ['object', 'face', 'edge', 'point'].forEach(k => {
    const b = $('#vt-sel-' + k);
    if (b) b.classList.toggle('on', k === m);
  });
  rpc('modeler.selectMode', { mode: m }).catch(() => {});
  refreshStatus();
}

/* What a rubber band selected, in whichever pick mode is active.
   Shift keeps the existing selection; without it the band replaces it. */
function applyBandSelection(box, add) {
  const got = VP.selectInBox(box, SEL_MODE);
  const btn = $('#vt-band');
  if (btn) btn.classList.remove('on');
  if (SEL_MODE === 'object') {
    const set = new Set(add ? (STATE.selection || []) : []);
    got.objects.forEach(n => set.add(n));
    if (!set.size) return setSelection([]);
    setSelection([...set]);
  } else if (SEL_MODE === 'face') {
    const same = (a, b) => a.object === b.object && a.face === b.face;
    const next = add ? FACE_PICKS.slice() : [];
    for (const f of got.faces) if (!next.some(x => same(x, f))) next.push(f);
    FACE_PICKS = next;
    VP.setFaceSelection(FACE_PICKS);
    rpc('modeler.select', { faces: FACE_PICKS, names: [] })
      .then(refreshMeasure).catch(() => {});
  } else if (SEL_MODE === 'edge') {
    EDGE_PICKS = add ? EDGE_PICKS.concat(got.edges) : got.edges;
    VP.setEdgeSelection(EDGE_PICKS);
    rpc('modeler.select', { edges: EDGE_PICKS, names: [] })
      .then(refreshMeasure).catch(() => {});
  } else if (SEL_MODE === 'point') {
    POINT_PICKS = add ? POINT_PICKS.concat(got.points) : got.points;
    VP.setPointSelection(POINT_PICKS);
    summarisePoints();
  }
  const n = got.objects.length + got.faces.length + got.edges.length
    + got.points.length;
  setStatus(n ? `Selected ${n} ${SEL_MODE}(s) in the box`
    : 'Nothing of that kind inside the box', n ? '' : 'err');
  refreshStatus();
}

/* What a set of picked vertices is worth knowing: how many, how far apart at
   the extremes, and the box they span. Two points still measure the distance
   between them, which is the common case. */
function summarisePoints() {
  const box = $('#vp-measure');
  if (!box) return;
  const pts = POINT_PICKS || [];
  if (pts.length < 2) { box.style.display = 'none'; return; }
  if (pts.length === 2) return showPointMeasurement('distance', pts);
  const lo = [0, 1, 2].map(k => Math.min(...pts.map(p => p[k])));
  const hi = [0, 1, 2].map(k => Math.max(...pts.map(p => p[k])));
  let far = 0, pair = null;
  const step = Math.max(1, Math.floor(pts.length / 60));
  for (let i = 0; i < pts.length; i += step)
    for (let j = i + 1; j < pts.length; j += step) {
      const d = Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1],
                           pts[i][2] - pts[j][2]);
      if (d > far) { far = d; pair = [pts[i], pts[j]]; }
    }
  POINT_MEASURE_PINNED = true;
  MEASURE = { kind: 'points', text:
    `${pts.length} points · widest span ${fmtLen(far, U())}\n`
    + 'bounding box ' + [0, 1, 2].map(k => fmtLen(hi[k] - lo[k], U())).join(' × '),
    distance: far, line: pair };
  VP.setMeasure(pair);
  box.textContent = MEASURE.text;
  box.style.display = 'block';
  placeMeasureLabel();
}

function armBandSelect() {
  if (!VP) return;
  VP.bandArmed = !VP.bandArmed;
  const b = $('#vt-band');
  if (b) b.classList.toggle('on', VP.bandArmed);
  setStatus(VP.bandArmed
    ? 'Box select: drag a rectangle over the model (Ctrl+drag does this too)'
    : 'Ready', VP.bandArmed ? 'busy' : '');
}

function pickFace(hit, add) {
  if (hit.face < 0 || !hit.meta) return;
  const rec = Object.assign({ object: hit.name, face: hit.face }, hit.meta);
  if (PORTPICK) return void portPickFace(rec, add);
  const same = (a, b) => a.object === b.object && a.face === b.face;
  if (add) {
    const i = FACE_PICKS.findIndex(f => same(f, rec));
    i >= 0 ? FACE_PICKS.splice(i, 1) : FACE_PICKS.push(rec);
  } else {
    FACE_PICKS = [rec];
  }
  VP.setFaceSelection(FACE_PICKS);
  rpc('modeler.select', { faces: FACE_PICKS, names: [] })
    .then(refreshMeasure).catch(() => {});
  refreshStatus();
}

function pickEdge(hit, add) {
  const e = hit.edge;
  if (!e) return;
  const rec = { object: hit.name, face: e.face, a: e.a, b: e.b,
                length: e.length, segments:e.segments };
  EDGE_PICKS = add ? EDGE_PICKS.concat([rec]) : [rec];
  VP.setEdgeSelection(EDGE_PICKS);
  rpc('modeler.select', { edges: EDGE_PICKS, names: [] })
    .then(refreshMeasure).catch(() => {});
  refreshStatus();
}

function clearPicks() {
  POINT_MEASURE_PINNED=false;++MEASURE_REVISION;
  POINT_PICKS=[];VP && VP.setPointSelection([]);VP && VP.setHover(null);
  FACE_PICKS = []; EDGE_PICKS = [];
  VP && VP.setFaceSelection([]);
  VP && VP.setEdgeSelection([]);
  setSelection([]);
}

function setSelection(names) {
  SEL_EPOCH++;
  STATE.selection = names;
  VP && VP.setSelection(names);
  renderTree();
  if (names.length === 1) showProps('object', names[0]);
  refreshStatus();
  rpc('modeler.select', { names }).then(refreshMeasure).catch(() => {});
}
function deleteSelection() {
  if (!STATE.selection.length) return toastError('Nothing selected');
  guard(() => rpc('modeler.delete', { names: STATE.selection })
    .then(() => refreshGeometry(false)));
}

/* -------------------------------------------------------- document tabs */
const pages = [{ id: 'modeler', title: '3D Modeler', closable: false }];
let activePage = 'modeler';

function renderTabs() {
  const t = $('#doctabs');
  t.innerHTML = '';
  for (const p of pages) {
    const b = el('button', { class: p.id === activePage ? 'active' : '',
      onclick: () => selectPage(p.id) }, p.title);
    if (p.closable) b.appendChild(el('span', { class: 'x',
      onclick: e => { e.stopPropagation(); closePage(p.id); } }, '×'));
    t.appendChild(b);
  }
}
function selectPage(id) {
  activePage = id;
  $$('.doc-page').forEach(p => p.classList.toggle('active',
    p.dataset.page === id));
  renderTabs();
}
function closePage(id) {
  const i = pages.findIndex(p => p.id === id);
  if (i < 0) return;
  pages.splice(i, 1);
  const n = document.querySelector(`.doc-page[data-page="${id}"]`);
  n && n.remove();
  selectPage('modeler');
}
function ensurePage(id, title) {
  let p = pages.find(x => x.id === id);
  if (!p) { pages.push({ id, title, closable: true }); }
  let n = document.querySelector(`.doc-page[data-page="${id}"]`);
  if (!n) { n = el('div', { class: 'doc-page' }); n.dataset.page = id;
    $('#docs').appendChild(n); }
  n.innerHTML = '';
  selectPage(id);
  return n;
}

/* ------------------------------------------------------------- reports */
async function openReport(kind) {
  if (!STATE.hasSolution) return toastError('No solution — run Analyze first');
  if (kind === 'eigen' || (STATE.design?.solutionType === 'eigenmode' &&
      (kind === 'sparam' || kind === 'modes'))) return reportEigen();
  if (kind === 'farfield') return reportFarField();
  if (kind === 'sparam') return reportSParam();
  if (kind === 'modes') return reportModes();
  if (kind === 'convergence') return reportConvergence();
}

let reportForm = 'db';
let reportTraces = null;

async function reportSParam() {
  const page = ensurePage('rep-s', 'S-Parameter Plot');
  const wrap = el('div', { class: 'report' });
  const bar = el('div', { class: 'report-toolbar' });
  const body = el('div', { class: 'report-body' });
  wrap.append(bar, body);
  page.appendChild(wrap);

  const data = await rpc('results.report',
    { form: reportForm, traces: reportTraces });
  const n = data.nPort;
  bar.appendChild(el('label', {}, 'Y axis'));
  const fs = sel('rp-form', [['db', 'dB(S)'], ['mag', '|S|'],
    ['deg', 'Phase [deg]'], ['vswr', 'VSWR'],
    ['groupdelay', 'Group delay [ns]']], reportForm);
  fs.onchange = () => { reportForm = fs.value; reportSParam(); };
  bar.appendChild(fs);
  bar.appendChild(el('label', {}, 'Traces'));
  const chips = el('div', { class: 'trace-chips' });
  const cur = new Set((data.traces || []).map(t => t.i + ',' + t.j));
  for (let i = 1; i <= n; i++) for (let j = 1; j <= n; j++) {
    const key = i + ',' + j;
    const cb = el('input', { type: 'checkbox' });
    cb.checked = cur.has(key);
    const lab = el('label', { class: cb.checked ? 'on' : '' }, cb,
      `S(${data.portNames[i-1]},${data.portNames[j-1]})`);
    cb.onchange = () => {
      const picked = Array.from(chips.querySelectorAll('input'))
        .map((c, k) => c.checked ? k : -1).filter(k => k >= 0);
      const allPairs = [];
      for (let a = 1; a <= n; a++) for (let b2 = 1; b2 <= n; b2++)
        allPairs.push({ i: a, j: b2 });
      reportTraces = picked.map(k => allPairs[k]);
      if (!reportTraces.length) { cb.checked = true; return; }
      reportSParam();
    };
    chips.appendChild(lab);
  }
  bar.appendChild(chips);
  bar.appendChild(el('span', { style: 'flex:1' }));
  bar.appendChild(el('span', { class: 'hint', style: 'margin:0' },
    `${data.nPort} ports · Z₀ = ${data.z0.map(z => z.toFixed(1)).join(', ')} Ω · ` +
    `${data.passive ? 'passive' : 'NOT passive'} · ` +
    `${data.reciprocal ? 'reciprocal' : 'non-reciprocal'}`));

  body.appendChild(el('div', { class: 'chart-wrap' },
    chart(data.freq.map(f => f / 1e9), data.traces.map(t => ({
      label: t.label, y: t.y })), 'Frequency [GHz]',
      { db: 'Magnitude [dB]', mag: '|S|', deg: 'Phase [deg]',
        vswr: 'VSWR', groupdelay: 'Group delay [ns]' }[data.form])));

  const tbl = el('table', { class: 'grid', style: 'margin-top:12px' });
  const head = el('tr', {}, el('th', {}, 'Freq [GHz]'),
    ...data.traces.map(t => el('th', {}, t.label)));
  tbl.appendChild(head);
  const step = Math.max(1, Math.ceil(data.freq.length / 25));
  for (let k = 0; k < data.freq.length; k += step) {
    tbl.appendChild(el('tr', {},
      el('td', { class: 'num' }, (data.freq[k] / 1e9).toFixed(5)),
      ...data.traces.map(t => el('td', { class: 'num' }, t.y[k].toFixed(4)))));
  }
  body.appendChild(el('div', { style: 'margin-top:12px' }, tbl));
}

async function reportEigen() {
  const page = ensurePage('rep-e', 'Eigenmode Data');
  const d = await rpc('results.eigenModes');
  const wrap = el('div', { class: 'report' });
  const body = el('div', { class: 'report-body' });
  wrap.append(el('div', { class: 'report-toolbar' },
    el('span', {}, `${d.rows.length} resonance(s) · ` +
      `${d.passes.length} adaptive pass(es)`)), body);
  page.appendChild(wrap);
  const t = el('table', { class: 'grid' });
  t.appendChild(el('tr', {}, ...['Mode', 'Frequency [GHz]', 'Q',
    'Im f [MHz]', 'Converged', 'Field'].map(h => el('th', {}, h))));
  for (const r of d.rows)
    t.appendChild(el('tr', {}, el('td', { class: 'num' }, r.mode),
      el('td', { class: 'num' }, (r.freq / 1e9).toFixed(6)),
      el('td', { class: 'num' }, r.q == null ? '∞ (lossless)' : r.q.toPrecision(5)),
      el('td', { class: 'num' }, (r.fimag / 1e6).toExponential(3)),
      el('td', { style: r.converged ? '' : 'color:var(--err)' },
        r.converged ? 'yes' : 'no (residual ' + r.residual.toExponential(1) + ')'),
      el('td', {}, el('button', { class: 'rbtn',
        style: 'flex-direction:row;gap:6px',
        onclick: () => { selectPage('modeler');
          showField(true, { excitation: r.mode - 1, freq: r.freq }); } },
        '|E| overlay'))));
  body.appendChild(t);
  const ds = d.passes.filter(c => c.delta_f != null);
  if (d.passes.length) {
    const c = el('table', { class: 'grid', style: 'margin-top:14px' });
    c.appendChild(el('tr', {}, ...['Pass', 'Tetrahedra', 'DOF',
      'f₁ [GHz]', 'max Δf'].map(h => el('th', {}, h))));
    for (const p of d.passes)
      c.appendChild(el('tr', {}, el('td', { class: 'num' }, p.pass),
        el('td', { class: 'num' }, p.tets.toLocaleString()),
        el('td', { class: 'num' }, p.dof.toLocaleString()),
        el('td', { class: 'num' }, (p.f0 / 1e9).toFixed(6)),
        el('td', { class: 'num' }, p.delta_f == null ? '—' : p.delta_f.toExponential(2))));
    body.appendChild(c);
  }
  if (ds.length > 1)
    body.appendChild(el('div', { class: 'chart-wrap', style: 'margin-top:12px' },
      chart(ds.map(c => c.pass), [{ label: 'max Δf', y: ds.map(c => c.delta_f) }],
        'Adaptive pass', 'max relative Δf')));
}

let ffState = { excitation: 0, freq: null, mode: 'polar', comp: 'total' };

async function reportFarField() {
  const page = ensurePage('rep-ff', 'Radiation Pattern');
  const wrap = el('div', { class: 'report' });
  const bar = el('div', { class: 'report-toolbar' });
  const body = el('div', { class: 'report-body' });
  wrap.append(bar, body);
  page.appendChild(wrap);
  let d;
  try {
    d = await rpc('results.farField', { excitation: ffState.excitation,
      freq: ffState.freq, cuts: [0, 90] });
  } catch (e) {
    body.appendChild(el('p', { class: 'hint', style: 'color:var(--err)' },
      String(e.message || e)));
    return;
  }
  ffState.freq = d.freq;
  const again = () => reportFarField();
  if (d.excitations.length > 1) {
    bar.appendChild(el('label', {}, 'Excitation'));
    const se = sel('ff-ex', d.excitations.map((n, i) => [i, n]), ffState.excitation);
    se.onchange = () => { ffState.excitation = parseInt(se.value); again(); };
    bar.appendChild(se);
  }
  if (d.freqs.length > 1) {
    bar.appendChild(el('label', {}, 'Frequency'));
    const sf = sel('ff-f', d.freqs.map(f => [f, fmtHz(f)]), d.freq);
    sf.onchange = () => { ffState.freq = parseFloat(sf.value); again(); };
    bar.appendChild(sf);
  }
  bar.appendChild(el('label', {}, 'Plot'));
  const sm = sel('ff-mode', [['polar', 'Polar'], ['rect', 'Rectangular']], ffState.mode);
  sm.onchange = () => { ffState.mode = sm.value; again(); };
  bar.appendChild(sm);
  bar.appendChild(el('label', {}, 'Quantity'));
  const sc = sel('ff-comp', [['total', 'Gain (total)'], ['theta', 'Gain (θ)'],
    ['phi_pol', 'Gain (φ)'], ['directivity', 'Directivity']], ffState.comp);
  sc.onchange = () => { ffState.comp = sc.value; again(); };
  bar.appendChild(sc);
  bar.appendChild(el('span', { style: 'flex:1' }));
  bar.appendChild(el('button', { class: 'rbtn', style: 'flex-direction:row;gap:6px',
    onclick: () => { selectPage('modeler'); showPattern(true, ffState); } },
    '3D pattern'));

  for (const w of d.warnings)
    body.appendChild(el('div', { class: 'hint',
      style: 'color:var(--err);margin-bottom:10px' }, '⚠ ' + w));
  const series = d.cuts.map(c => ({ label: `φ = ${c.phi.toFixed(0)}° / ${
    ((c.phi + 180) % 360).toFixed(0)}°`, y: c[ffState.comp],
    opp: c.opposite[ffState.comp] }));
  const ylab = ffState.comp === 'directivity' ? 'Directivity [dBi]' : 'Gain [dBi]';
  body.appendChild(el('div', { class: 'chart-wrap' },
    ffState.mode === 'polar' ? polarChart(d.theta, series, ylab)
      : chart(d.theta, series, 'Theta [deg]', ylab)));

  const m = d.summary;
  const t = el('table', { class: 'grid', style: 'margin-top:14px' });
  const row = (k, v) => t.appendChild(el('tr', {}, el('td', {}, k),
    el('td', { class: 'num' }, v)));
  t.appendChild(el('tr', {}, el('th', {}, 'Antenna parameter'), el('th', {}, 'Value')));
  row('Peak directivity', m.peakDirectivityDbi.toFixed(2) + ' dBi');
  row('Peak gain', m.peakGainDbi.toFixed(2) + ' dBi');
  if (m.peakRealizedGainDbi != null)
    row('Peak realized gain (with mismatch)', m.peakRealizedGainDbi.toFixed(2) + ' dBi');
  row('Direction of peak (θ, φ)', `${m.peakTheta.toFixed(0)}°, ${m.peakPhi.toFixed(0)}°`);
  row('Radiation efficiency', (100 * m.efficiency).toFixed(1) + ' %');
  if (m.mismatchEfficiency != null)
    row('Mismatch efficiency (1 − |S|²)', (100 * m.mismatchEfficiency).toFixed(1) + ' %');
  row('Front-to-back ratio', m.frontToBackDb.toFixed(2) + ' dB');
  row('Axial ratio at peak', m.axialRatioAtPeak > 100 ? '> 40 dB (linear)'
    : (20 * Math.log10(m.axialRatioAtPeak)).toFixed(2) + ' dB');
  row('Max radiation intensity', m.maxIntensity.toPrecision(4) + ' W/sr per W accepted');
  if (m.boundaryToFarFieldPower != null)
    row('Boundary / far-field power (domain check)',
        m.boundaryToFarFieldPower.toFixed(2) + '  (≈ 1 when the air region is adequate)');
  body.appendChild(el('div', { style: 'margin-top:12px' }, t));
}

/* Polar plot of dB values against theta, φ cuts mirrored across the axis the
   way an antenna engineer reads a pattern: 0° up, a cut drawn as the φ and
   φ+180° half-planes joined. */
function polarChart(thetaDeg, series, ylabel, w = 560, h = 560) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('width', '100%');
  svg.style.maxWidth = '640px';
  svg.style.font = '11px var(--mono, monospace)';
  const add = (tag, at, txt) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(at)) n.setAttribute(k, v);
    if (txt != null) n.textContent = txt;
    svg.appendChild(n); return n;
  };
  const cx = w / 2, cy = h / 2 + 8, R = Math.min(w, h) / 2 - 56;
  const all = series.flatMap(s => s.y).filter(Number.isFinite);
  const top = Math.ceil(Math.max(...all) / 5) * 5, span = 40, floor = top - span;
  const rad = v => R * Math.max(0, Math.min(1, (v - floor) / span));
  for (let i = 1; i <= 4; i++) {
    add('circle', { cx, cy, r: R * i / 4, fill: 'none', stroke: 'var(--border-soft)' });
    add('text', { x: cx + 4, y: cy - R * i / 4 - 2, fill: 'var(--text-dim)' },
      (floor + span * i / 4).toFixed(0));
  }
  for (let a = 0; a < 360; a += 30) {
    const t = a * Math.PI / 180;
    add('line', { x1: cx, y1: cy, x2: cx + R * Math.sin(t), y2: cy - R * Math.cos(t),
      stroke: 'var(--border-soft)' });
    add('text', { x: cx + (R + 16) * Math.sin(t), y: cy - (R + 16) * Math.cos(t) + 4,
      'text-anchor': 'middle', fill: 'var(--text-dim)' }, a + '°');
  }
  series.forEach((s, i) => {
    // right half-plane: the cut at φ; left half-plane: the cut at φ + 180°,
    // so the two together are the whole great circle through the pole
    const half = (ys, sign) => thetaDeg.map((td, k) => {
      const t = td * Math.PI / 180, r = rad(ys[k]);
      return `${(cx + sign * r * Math.sin(t)).toFixed(1)},${(cy - r * Math.cos(t)).toFixed(1)}`;
    });
    const right = half(s.y, 1);
    const left = s.opp ? half(s.opp, -1).reverse() : [];
    add('polyline', { points: left.concat(right).join(' '), fill: 'none',
      stroke: PALETTE[i % PALETTE.length], 'stroke-width': 1.9 });
    add('rect', { x: 20 + i * 120, y: 14, width: 16, height: 3,
      fill: PALETTE[i % PALETTE.length] });
    add('text', { x: 42 + i * 120, y: 20, fill: 'var(--text)' }, s.label);
  });
  add('text', { x: w / 2, y: h - 10, 'text-anchor': 'middle', fill: 'var(--text)' },
    ylabel + ' (θ from +z; right = φ, left = φ+180°)');
  return svg;
}

let patternOn = false;
async function showPattern(on, opts) {
  if (!on) {
    patternOn = false;
    const vb = $('#vt-pattern'); if (vb) vb.classList.remove('on');
    $('#legend').classList.remove('on'); $('#legend-labels').classList.remove('on');
    await refreshGeometry(false);
    return;
  }
  await guard(async () => {
    const f = await rpc('view.pattern', { excitation: (opts || {}).excitation || 0,
      freq: (opts || {}).freq });
    f.name = '__pattern__'; f.color = '#888888'; f.transparency = 0;
    VP.setObjects([f], VP.bbox);
    patternOn = true;
    const vb = $('#vt-pattern'); if (vb) vb.classList.add('on');
    const lg = $('#legend');
    lg.style.background =
      'linear-gradient(to top, #30123b, #4145ab, #1ba0d1, #46f884, #d5e11a, #f6883a, #900c00)';
    lg.classList.add('on');
    const lab = $('#legend-labels');
    lab.innerHTML = '';
    for (let i = 4; i >= 0; i--) {
      const v = f.range[0] + (f.range[1] - f.range[0]) * i / 4;
      lab.appendChild(el('span', {}, v.toFixed(1)));
    }
    lab.classList.add('on');
    lab.insertBefore(el('span', { style: 'font-weight:600' }, 'Gain dBi'), lab.firstChild);
  });
}

async function reportModes() {
  const page = ensurePage('rep-m', 'Port Modes');
  const d = await rpc('results.portModes');
  const wrap = el('div', { class: 'report' });
  const body = el('div', { class: 'report-body' });
  wrap.append(el('div', { class: 'report-toolbar' },
    el('span', {}, 'Modal solution at ' + fmtHz(d.freq))), body);
  page.appendChild(wrap);
  const t = el('table', { class: 'grid' });
  t.appendChild(el('tr', {}, ...['Port', 'Mode', 'Type', 'β [rad/m]',
    'α [Np/m]', 'f_c [GHz]', 'Z_wave [Ω]', 'Z_port [Ω]', 'Propagating']
    .map(h => el('th', {}, h))));
  for (const r of d.rows) {
    t.appendChild(el('tr', {}, el('td', {}, r.port),
      el('td', { class: 'num' }, r.mode), el('td', {}, r.type),
      el('td', { class: 'num' }, r.beta.toFixed(4)),
      el('td', { class: 'num' }, r.alpha.toFixed(4)),
      el('td', { class: 'num' }, (r.fc / 1e9).toFixed(5)),
      el('td', { class: 'num' }, r.zwave[0].toFixed(3)),
      el('td', { class: 'num' }, r.zport[0].toFixed(3)),
      el('td', {}, r.propagating ? 'yes' : 'evanescent')));
  }
  body.appendChild(t);
}

async function reportConvergence() {
  const page = ensurePage('rep-c', 'Convergence');
  const d = await rpc('results.convergence');
  const wrap = el('div', { class: 'report' });
  const body = el('div', { class: 'report-body' });
  wrap.append(el('div', { class: 'report-toolbar' },
    el('span', {}, 'Adaptive pass history')), body);
  page.appendChild(wrap);
  const t = el('table', { class: 'grid' });
  t.appendChild(el('tr', {}, ...['Pass', 'Tetrahedra', 'DOF', 'ΔS']
    .map(h => el('th', {}, h))));
  for (const c of d.passes)
    t.appendChild(el('tr', {}, el('td', { class: 'num' }, c.pass),
      el('td', { class: 'num' }, c.tets.toLocaleString()),
      el('td', { class: 'num' }, c.dof.toLocaleString()),
      el('td', { class: 'num' }, c.delta_s == null ? '—' : c.delta_s.toFixed(5))));
  body.appendChild(t);
  const ds = d.passes.filter(c => c.delta_s != null);
  if (ds.length > 1)
    body.appendChild(el('div', { class: 'chart-wrap', style: 'margin-top:12px' },
      chart(ds.map(c => c.pass), [{ label: 'ΔS', y: ds.map(c => c.delta_s) }],
        'Adaptive pass', 'max |ΔS|')));
}

/* SVG line chart */
const PALETTE = ['#2b6cb0', '#c53030', '#2f855a', '#6b46c1', '#b7791f',
  '#0987a0', '#97266d', '#4a5568'];
function chart(x, series, xlabel, ylabel, w = 900, h = 380) {
  const L = 68, R = 24, T = 22, B = 46;
  const W = w - L - R, H = h - T - B;
  const ys = series.flatMap(s => s.y).filter(Number.isFinite);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (!(y1 > y0)) { y0 -= 1; y1 += 1; }
  const padY = (y1 - y0) * 0.07; y0 -= padY; y1 += padY;
  const x0 = Math.min(...x), x1 = Math.max(...x);
  const X = v => L + (v - x0) / ((x1 - x0) || 1) * W;
  const Y = v => T + (y1 - v) / ((y1 - y0) || 1) * H;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('width', '100%');
  svg.style.font = '11px var(--mono, monospace)';
  const add = (tag, at, txt) => {
    const n = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(at)) n.setAttribute(k, v);
    if (txt != null) n.textContent = txt;
    svg.appendChild(n); return n;
  };
  add('rect', { x: L, y: T, width: W, height: H, fill: 'var(--bg)',
    stroke: 'var(--border)' });
  for (let i = 0; i <= 5; i++) {
    const v = y0 + (y1 - y0) * i / 5, yy = Y(v);
    add('line', { x1: L, y1: yy, x2: L + W, y2: yy, stroke: 'var(--border-soft)' });
    add('text', { x: L - 7, y: yy + 4, 'text-anchor': 'end',
      fill: 'var(--text-dim)' }, fmtTick(v));
  }
  for (let i = 0; i <= 6; i++) {
    const v = x0 + (x1 - x0) * i / 6, xx = X(v);
    add('line', { x1: xx, y1: T, x2: xx, y2: T + H, stroke: 'var(--border-soft)' });
    add('text', { x: xx, y: T + H + 17, 'text-anchor': 'middle',
      fill: 'var(--text-dim)' }, fmtTick(v));
  }
  series.forEach((s, i) => {
    const pts = s.y.map((v, k) => Number.isFinite(v)
      ? `${X(x[k]).toFixed(2)},${Y(v).toFixed(2)}` : null)
      .filter(Boolean).join(' ');
    add('polyline', { points: pts, fill: 'none',
      stroke: PALETTE[i % PALETTE.length], 'stroke-width': 1.9,
      'stroke-linejoin': 'round' });
    add('rect', { x: L + 10 + i * 128, y: T - 15, width: 16, height: 3,
      fill: PALETTE[i % PALETTE.length] });
    add('text', { x: L + 30 + i * 128, y: T - 10,
      fill: 'var(--text)' }, s.label);
  });
  add('text', { x: L + W / 2, y: h - 8, 'text-anchor': 'middle',
    fill: 'var(--text)' }, xlabel);
  add('text', { x: 14, y: T + H / 2, 'text-anchor': 'middle',
    fill: 'var(--text)', transform: `rotate(-90 14 ${T + H / 2})` }, ylabel);
  return svg;
}
const fmtTick = v => Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0)
  ? v.toExponential(2) : (Math.round(v * 1000) / 1000).toString();

/* ------------------------------------------------- messages & progress */
/* A long command has to say what it is doing.
   Opening a project, importing an assembly and rebuilding the display buffers
   all take real time on a real model, and until now they took it silently:
   the window sat there with no cursor, no bar and no stage, which is
   indistinguishable from a crash. The server publishes its stage on a channel
   that is answered by a separate request — so it keeps updating even while the
   command holds the session lock — and this is what draws it. */
let BUSY_OVERLAY = null;
let LAST_TASK = null;
//: nonzero while a caller (not the poller) owns the overlay, so the gap
//: between two server-side stages does not flash it off and on again.
let BUSY_STICKY = 0;

function showBusyOverlay(label, sticky) {
  if (sticky) BUSY_STICKY++;
  _busyOverlay(label);
}

function _busyOverlay(label) {
  if (!BUSY_OVERLAY) {
    BUSY_OVERLAY = el('div', { id: 'busy-overlay' },
      el('div', { class: 'busy-card' },
        el('div', { class: 'busy-title' }, label || 'Working…'),
        el('div', { class: 'busy-stage' }, 'starting…'),
        el('div', { class: 'pbar' }, el('div', { class: 'fill' })),
        el('div', { class: 'busy-detail' }, '')));
    document.body.appendChild(BUSY_OVERLAY);
  }
  BUSY_OVERLAY.querySelector('.busy-title').textContent = label || 'Working…';
  BUSY_OVERLAY.classList.add('on');
  selectBottom('progress');
}

function hideBusyOverlay(sticky) {
  if (sticky && BUSY_STICKY > 0) BUSY_STICKY--;
  if (BUSY_STICKY > 0) return;
  if (BUSY_OVERLAY) BUSY_OVERLAY.classList.remove('on');
}

function renderTask(task) {
  LAST_TASK = task;
  const box = $('#progress');
  if (task.active) {
    _busyOverlay(task.label);
    const stage = BUSY_OVERLAY.querySelector('.busy-stage');
    const fill = BUSY_OVERLAY.querySelector('.pbar .fill');
    const det = BUSY_OVERLAY.querySelector('.busy-detail');
    stage.textContent = (task.stage || 'working') +
      (task.total ? ` — ${task.done} / ${task.total}` : '') +
      `  ·  ${task.elapsed.toFixed(1)} s`;
    // An indeterminate stage animates rather than pretending to know a
    // percentage it does not have.
    fill.classList.toggle('indeterminate', !task.total);
    fill.style.width = task.total
      ? Math.round(task.fraction * 100) + '%' : '35%';
    det.textContent = task.detail || '';
    if (box && !STATE?.job?.running) {
      box.innerHTML = '';
      box.appendChild(el('div', { style: 'font-weight:600;margin-bottom:2px' },
        task.label));
      const bar = el('div', { class: 'pbar' });
      bar.appendChild(el('div',
        { style: `width:${task.total ? Math.round(task.fraction * 100) : 35}%` }));
      box.appendChild(bar);
      const g = el('div', { class: 'pgrid' });
      const kv = (k, v) => { g.appendChild(el('span', { class: 'k' }, k));
        g.appendChild(el('span', { class: 'v' }, String(v))); };
      kv('Stage', task.stage || '—');
      kv('Item', task.detail || '—');
      kv('Progress', task.total ? `${task.done} / ${task.total}` : 'working…');
      kv('Elapsed', task.elapsed.toFixed(1) + ' s');
      box.appendChild(g);
    }
    setStatus(`${task.label} — ${task.stage || 'working'}`, 'busy');
  } else {
    hideBusyOverlay();
    if (task.error) toastError(task.error);
  }
}

let msgSeq = 0;
async function pollMessages() {
  let interval = 700;
  try {
    const r = await fetch(`/api/messages?since=${msgSeq}&token=` +
      encodeURIComponent(window.AETHER_TOKEN));
    const j = await r.json();
    if (j.task) {
      // Only redraw when something moved, and poll faster while it is moving.
      if (j.task.active || (LAST_TASK && LAST_TASK.active)) {
        if (!LAST_TASK || LAST_TASK.seq !== j.task.seq || !j.task.active)
          renderTask(j.task);
        else LAST_TASK = j.task;
      }
      if (j.task.active) interval = 200;
    }
    if (j.messages && j.messages.length) {
      const box = $('#messages');
      const atEnd = box.parentElement.scrollTop + box.parentElement.clientHeight
        >= box.parentElement.scrollHeight - 30;
      for (const m of j.messages) {
        box.appendChild(el('div', { class: 'msg ' + m.severity },
          el('span', { class: 't' }, m.t),
          el('span', { class: 'src' }, '[' + (m.source || 'aether') + ']'),
          el('span', { class: 'm' }, m.text)));
        msgSeq = m.id;
      }
      while (box.childElementCount > 1200) box.removeChild(box.firstChild);
      if (atEnd) box.parentElement.scrollTop = box.parentElement.scrollHeight;
    }
    if (j.job && !(j.task && j.task.active)) renderProgress(j.job);
  } catch (e) { /* server not up yet */ }
  setTimeout(pollMessages, interval);
}

function renderProgress(job) {
  const p = $('#progress');
  const total = Math.max(job.totalPasses || 1, 1);
  let frac = 0;
  if (job.stage === 'meshing') frac = 0.05;
  else if (job.stage === 'adaptive') frac = 0.1 + 0.6 * (job.pass / total);
  else if (job.stage === 'sweep')
    frac = 0.72 + 0.27 * (job.freqDone / Math.max(job.freqTotal, 1));
  else if (job.done && !job.error) frac = 1;
  p.innerHTML = '';
  p.appendChild(el('div', { style: 'font-weight:600;margin-bottom:2px' },
    job.running ? `Solving — ${job.setup}` :
      job.error ? 'Analysis failed' :
      job.done ? `Analysis complete — ${job.setup}` : 'Idle'));
  const bar = el('div', { class: 'pbar' });
  bar.appendChild(el('div', { style: `width:${Math.round(frac * 100)}%` }));
  p.appendChild(bar);
  const g = el('div', { class: 'pgrid' });
  const kv = (k, v) => { g.appendChild(el('span', { class: 'k' }, k));
    g.appendChild(el('span', { class: 'v' }, String(v))); };
  kv('Stage', job.stage || '—');
  kv('Adaptive pass', job.totalPasses ? `${job.pass} / ${job.totalPasses}` : '—');
  kv('Frequency points', job.freqTotal ? `${job.freqDone} / ${job.freqTotal}` : '—');
  kv('Elapsed', job.elapsed.toFixed(1) + ' s');
  if (job.error) kv('Error', job.error);
  p.appendChild(g);
  const dot = $('#status-dot');
  dot.className = 'dot' + (job.running ? ' busy' : job.error ? ' err' : '');
  if (job.running) setStatus(`Solving ${job.setup} — ${job.stage}`, 'busy');
}

let jobWatch = null;
function pollJob() {
  clearInterval(jobWatch);
  jobWatch = setInterval(async () => {
    const r = await fetch('/api/state?token=' +
      encodeURIComponent(window.AETHER_TOKEN));
    const s = await r.json();
    const wasRunning = STATE.job.running;
    STATE = s; renderAll();
    if (!s.job.running) {
      clearInterval(jobWatch);
      if (wasRunning && !s.job.error && s.hasSolution) {
        setStatus('Analysis complete', '');
        openReport('sparam');
      }
    }
  }, 900);
}

/* -------------------------------------------------------------- console */
function initConsole() {
  const src = $('#console-src'), out = $('#console-out');
  src.addEventListener('keydown', async e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      const code = src.value;
      if (!code.trim()) return;
      out.textContent += '\n>>> ' + code.replace(/\n/g, '\n... ') + '\n';
      try {
        const r = await rpc('script.run', { code });
        out.textContent += r.output || (r.ok ? '' : 'error');
        if (r.ok) { await refreshGeometry(false); }
      } catch (err) { out.textContent += String(err) + '\n'; }
      out.scrollTop = out.scrollHeight;
      src.value = '';
    }
  });
}

/* ------------------------------------------------------------ chrome */
function clearMessages() {
  $('#messages').innerHTML = '';
  rpc('messages.clear').catch(() => {});
}

/* ----------------------------------------------------------- dock sizing */
/* Every dock edge is a splitter.
   The message panel was a fixed 178 px, which is one and a half lines of an
   import report — the exact panel you need tall when a project comes in with
   problems. Drag an edge to resize, double-click it to restore the default,
   and the sizes are remembered between runs. */
const DOCK_DEFAULTS = { left: 268, props: 232, bottom: 178 };
const DOCK_KEY = 'aether.docks.v1';
let DOCKS = Object.assign({}, DOCK_DEFAULTS);

function loadDocks() {
  try {
    const raw = localStorage.getItem(DOCK_KEY);
    if (raw) Object.assign(DOCKS, JSON.parse(raw));
  } catch (e) { /* private window, or storage disabled — defaults are fine */ }
}
function saveDocks() {
  try { localStorage.setItem(DOCK_KEY, JSON.stringify(DOCKS)); }
  catch (e) { /* not worth telling anyone about */ }
}
function applyDocks() {
  const clampTo = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  DOCKS.left = clampTo(DOCKS.left, 170, Math.max(200, window.innerWidth - 420));
  DOCKS.bottom = clampTo(DOCKS.bottom, 26, Math.max(60, window.innerHeight - 260));
  DOCKS.props = clampTo(DOCKS.props, 60, Math.max(80, window.innerHeight - 320));
  $('#leftdock').style.width = DOCKS.left + 'px';
  $('#props').style.height = DOCKS.props + 'px';
  $('#bottomdock').style.height = DOCKS.bottom + 'px';
}

function initDocks() {
  loadDocks();
  applyDocks();
  // `sign` is +1 when the dock grows in the direction of the drag and -1 when
  // it grows against it — the props and message docks are anchored at the
  // bottom, so pulling their top edge down makes them smaller.
  const drag = (id, axis, key, sign) => {
    const el0 = $(id);
    if (!el0) return;
    el0.addEventListener('pointerdown', e => {
      e.preventDefault();
      const start = axis === 'x' ? e.clientX : e.clientY;
      const from = DOCKS[key];
      el0.setPointerCapture(e.pointerId);
      el0.classList.add('dragging');
      document.body.classList.add('resizing');
      const move = ev => {
        const now = axis === 'x' ? ev.clientX : ev.clientY;
        DOCKS[key] = from + sign * (now - start);
        applyDocks();
      };
      const up = () => {
        el0.removeEventListener('pointermove', move);
        el0.removeEventListener('pointerup', up);
        el0.classList.remove('dragging');
        document.body.classList.remove('resizing');
        saveDocks();
      };
      el0.addEventListener('pointermove', move);
      el0.addEventListener('pointerup', up);
    });
  };
  drag('#split-left', 'x', 'left', 1);
  drag('#split-props', 'y', 'props', -1);
  drag('#split-bottom', 'y', 'bottom', -1);
  const reset = (id, key) => {
    const n = $(id);
    n && n.addEventListener('dblclick', () => {
      DOCKS[key] = DOCK_DEFAULTS[key]; applyDocks(); saveDocks();
    });
  };
  reset('#split-left', 'left');
  reset('#split-props', 'props');
  reset('#split-bottom', 'bottom');

  const maxBtn = $('#btn-dock-max');
  if (maxBtn) maxBtn.onclick = () => {
    const big = Math.round(window.innerHeight * 0.62);
    const collapsed = DOCKS.bottom <= 30;
    DOCKS.bottom = DOCKS.bottom >= big - 4 ? DOCK_DEFAULTS.bottom
      : (collapsed ? DOCK_DEFAULTS.bottom : big);
    maxBtn.textContent = DOCKS.bottom >= big - 4 ? '▼' : '▲';
    applyDocks(); saveDocks();
  };
  // a double-click on the tab strip collapses the dock to its tabs and back
  $('#bottomtabs').addEventListener('dblclick', e => {
    if (e.target.closest('button')) return;
    DOCKS.bottom = DOCKS.bottom <= 30 ? DOCK_DEFAULTS.bottom : 26;
    applyDocks(); saveDocks();
  });
  window.addEventListener('resize', applyDocks);
}

function selectBottom(name) {
  $$('#bottomtabs button[data-b]').forEach(b =>
    b.classList.toggle('active', b.dataset.b === name));
  $$('.bottom-page').forEach(p => p.classList.toggle('active', p.dataset.b === name));
}
function setStatus(text, cls) {
  $('#status-text').textContent = text;
  $('#status-dot').className = 'dot' + (cls ? ' ' + cls : '');
}
/* What the status bar says about the pick. A face pick shows its area and a
   line pick its length, because that is the number you are checking when you
   click one -- "did I get the whole patch, or only half of it?" */
function selectionSummary() {
  const mode = SEL_MODE.charAt(0).toUpperCase() + SEL_MODE.slice(1);
  if (SEL_MODE === 'face' && FACE_PICKS.length) {
    const a = FACE_PICKS.reduce((t, f) => t + (f.area || 0), 0);
    const objs = [...new Set(FACE_PICKS.map(f => f.object))];
    return `${mode}: ${FACE_PICKS.length} face(s) on ${objs.join(', ')}`
      + ` — ${Number((a / (UNIT_SCALE[U()] ** 2)).toPrecision(7))} ${U()}²`;
  }
  if (SEL_MODE === 'edge' && EDGE_PICKS.length) {
    const l = EDGE_PICKS.reduce((t, e) => t + (e.length || 0), 0);
    return `${mode}: ${EDGE_PICKS.length} edge(s) — `
      + fmtLen(l, U());
  }
  if (STATE?.selection?.length)
    return `${mode}: ${STATE.selection.join(', ')}`;
  return mode + ': nothing selected';
}

function refreshStatus() {
  const d = STATE?.design;
  $('#status-sel').textContent = selectionSummary();
  $('#status-mesh').textContent = d?.meshStats
    ? `Mesh: ${d.meshStats.tets.toLocaleString()} tets`
    : 'Mesh: none';
  $('#status-units').textContent = 'Units: ' + (d?.units || 'mm');
  if (!STATE?.job?.running && !$('#status-dot').classList.contains('err')) setStatus(
    STATE?.hasSolution ? 'Solution available' : 'Ready', '');
}
function toggleTheme() {
  const r = document.documentElement;
  r.dataset.theme = r.dataset.theme === 'dark' ? 'light' : 'dark';
}

function renderAll() {
  if (!STATE) return;
  $('#title-doc').textContent = STATE.project.open === false
    ? 'No project open'
    : STATE.project.name +
      (STATE.design ? ' — ' + STATE.design.name : '') +
      (STATE.project.dirty ? ' *' : '');
  renderTree(); renderProps(); renderTabs(); refreshStatus();
  VP && VP.setSelection(STATE.selection);
  updateOverlay();
}

async function loadMaterials() {
  const m = await rpc('materials.list');
  window.MATERIALS = m.materials;
  for (const x of window.MATERIALS)
    if (x.sigma == null) x.sigma = Infinity;      /* PEC comes back as null */
}

/* Expose the pieces automation and the scripting console may want to reach.
   Top-level `let` bindings are not properties of `window` in a classic
   script, so they are published explicitly. */
Object.assign(window, { rpc, guard, showMesh, showField, showPattern, fitView,
  refreshGeometry, openReport, setSelection, setViewMode, toggleTheme,
  filePicker, saveProject, saveProjectAs, dlgOpenSave, openProjectFile,
  startInteractiveMove, armBandSelect, applyBandSelection, ensureDesign,
  startPointDraw, fitSelection, startPortPick, cancelPortPick,
  commitPortPick, dlgRepairBodies, setSelectMode,
  get PORTPICK() { return PORTPICK; },
  get FACE_PICKS() { return FACE_PICKS; },
  closeProject, confirmDiscard, askSaveChanges, suggestName, clearMessages,
  showBusyOverlay, hideBusyOverlay,
  get STATE() { return STATE; } });

/* ----------------------------------------------------------------- boot */
async function boot() {
  buildMenus(); buildRibbon(); initDocks(); initViewport(); initConsole();
  $$('#bottomtabs button[data-b]').forEach(b =>
    b.onclick = () => selectBottom(b.dataset.b));
  $('#btn-clear-msgs').onclick = clearMessages;
  document.addEventListener('keydown', e => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT' || e.target.isContentEditable || DIALOG_STACK.length) return;
    if (MEASURE_PICK && e.key === 'Escape') { cancelMeasurePick(); return; }
    if (PORTPICK) {
      if (e.key === 'Escape') { cancelPortPick(); return; }
      if (e.key === 'Enter') { e.preventDefault(); commitPortPick(); return; }
      if (e.key === 'g' || e.key === 'G') { PORTPICK.stage = 'gnd'; updatePortPanel(); return; }
      if (e.key === 's' || e.key === 'S') { PORTPICK.stage = 'signal'; updatePortPanel(); return; }
    }
    if (!e.ctrlKey && !e.metaKey && e.key.toLowerCase() === 'm') { e.preventDefault(); dlgMeasure(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') { e.preventDefault(); newProject(); return; }
    if (MOVE) {
      if (e.key === 'Escape') { moveStepBack(); return; }
      if (e.key === 's' || e.key === 'S') {
        MOVE.snap = !MOVE.snap;
        const cb = $('#mv-snap');
        if (cb) cb.checked = MOVE.snap;
        updateMovePanel();
        return;
      }
      if (e.key === 'Enter' && moveIsReady()) { e.preventDefault(); commitMove(); }
      return;
    }
    if (DRAW) {
      // Esc steps back one point rather than throwing the whole draw away.
      if (e.key === 'Escape') { drawStepBack(); return; }
      if (e.key === 's' || e.key === 'S') {
        DRAW.snap = !DRAW.snap;
        const cb = $('#dw-snap');
        if (cb) cb.checked = DRAW.snap;
        updateDrawPanel();
        return;
      }
      if (e.key === 'Enter' && drawIsComplete()) { e.preventDefault(); commitDraw(); return; }
      return;                      // the draw owns the keyboard while it runs
    }
    // O / F / E pick modes and Ctrl+D to fit, as in the modeller this
    // follows; V is left free until vertex picking exists.
    if (!e.ctrlKey && !e.metaKey) {
      const k = e.key.toLowerCase();
      if (k === 'o') setSelectMode('object');
      else if (k === 'f') setSelectMode('face');
      else if (k === 'e') setSelectMode('edge');
      else if (k === 'v') setSelectMode('point');
    }
    if (e.key === 'Delete') deleteSelection();
    if (e.key === 'F5') { e.preventDefault(); dlgValidate(); }
    if (e.key === 'F9') { e.preventDefault(); dlgAnalyze(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      e.shiftKey ? saveProjectAs() : saveProject(false);
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'w') {
      e.preventDefault(); closeProject();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'm') {
      e.preventDefault(); startInteractiveMove();
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'o') { e.preventDefault(); dlgOpenSave('open'); }
    if (e.ctrlKey || e.metaKey) {
      const k = e.key.toLowerCase();
      if (k === 'z') { e.preventDefault(); e.shiftKey ? editRedo() : editUndo(); }
      else if (k === 'y') { e.preventDefault(); editRedo(); }
      else if (k === 'x') { e.preventDefault(); editCopy(true); }
      else if (k === 'c') { e.preventDefault(); editCopy(false); }
      else if (k === 'v') { e.preventDefault(); editPaste(); }
      else if (k === 'd') { e.preventDefault();
        e.shiftKey ? fitSelection() : fitView(); }
    }
  });
  const r = await fetch('/api/state?token=' +
    encodeURIComponent(window.AETHER_TOKEN));
  STATE = await r.json();
  try { await loadMaterials(); }
  catch (e) { window.MATERIALS = [{ name: 'vacuum' }]; toastError(e.message); }
  renderAll();
  await refreshGeometry(true);
  pollMessages();
  window.__aetherReady = true;
}
boot();


/* Dimensions workbench: explicit units, reusable picks and exportable results. */
const UNIT_SCALE = {m:1, cm:.01, mm:.001, um:1e-6, mil:2.54e-5, in:.0254};
function clearLocalPicks() {
  POINT_MEASURE_PINNED=false;++MEASURE_REVISION;
  FACE_PICKS = []; EDGE_PICKS = []; POINT_PICKS=[]; MEASURE = null;
  VP && VP.setMeasure(null);
  const box = $('#vp-measure'); if (box) box.style.display = 'none';
  placeMeasureLabel();
}
async function newProject() {
  if (!await confirmDiscard('starting a new one')) return;
  await guard(async () => {
    await rpc('project.new');
    resetDocumentViews();
    await refreshGeometry(true);
    fitView();
  });
}
window.addEventListener('beforeunload', e => {
  if (!SHUTTING_DOWN && STATE?.project?.dirty) {
    e.preventDefault(); e.returnValue = '';
  }
});

function downloadMeasurement(result) {
  const csv = [['Field', 'Value', 'Units'],
    ['Summary', result.text, ''], ['Accuracy', result.accuracy || '', ''],
    ...Object.entries(result).filter(([k]) => !['text','accuracy','units'].includes(k))
      .map(([k,v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v),
        k === 'angle' ? 'degree' : 'SI (length m, area m2, volume m3)'])]
    .map(row => row.map(v => '"'+String(v).replace(/"/g,'""')+'"').join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\uFEFF'+csv], {type:'text/csv;charset=utf-8'}));
  const a = el('a', {href:url, download:'aether-measurement.csv'});
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function dlgMeasure() {
  const body = el('div');
  const mode = sel('dim-mode', [['selection','Selected objects / edges / faces'],
    ['distance','Two-point distance + ΔX / ΔY / ΔZ'], ['angle','Three-point angle (vertex B)'],
    ['circle','Circle through three points: radius / diameter']], 'selection');
  const unit = sel('dim-unit', Object.keys(UNIT_SCALE), U());
  body.appendChild(field('Measurement', mode)); body.appendChild(field('Coordinate units', unit));
  const coordinates = el('div');
  for (let i=0; i<3; i++) {
    const row = el('div', {class:'dim-xyz'});
    for (let j=0; j<3; j++) row.appendChild(field('ABC'[i]+' · '+'XYZ'[j],
      inp(`dim-${i}-${j}`, i===j ? '1' : '0', 'text')));
    coordinates.appendChild(row);
  }
  body.appendChild(coordinates);
  body.appendChild(el('div', {class:'hint'}, 'Bare numbers use the chosen unit. Explicit values such as 2.5mm are accepted. Circle points must lie on the circumference. Curved-edge and face picks use tessellation.'));
  const picks = el('button', {onclick: () => {
    const pts = EDGE_PICKS.length ? EDGE_PICKS.flatMap(e=>[e.a,e.b]) : FACE_PICKS.map(f=>f.point);
    if (!pts.length) { output.textContent = 'Pick an edge or face in the viewport first, then reopen Measure.'; return; }
    pts.slice(0,3).forEach((p,i)=>p.forEach((x,j)=>$('#dim-'+i+'-'+j).value=String(Number((x/UNIT_SCALE[unit.value]).toPrecision(12)))));
  }}, 'Use picked endpoints / face points');
  body.appendChild(picks);
  const output = el('pre', {class:'dim-result', id:'dim-result'}, 'Choose a measurement and press Calculate.');
  const exportBtn = el('button', {disabled:'disabled'}, 'Export CSV');
  const calculate = el('button', {class:'pri', id:'dim-calculate', onclick: async () => {
    calculate.disabled = true;
    try {
      const n = mode.value === 'distance' ? 2 : 3;
      const points = Array.from({length:n},(_,i)=>[0,1,2].map(j=>gv('dim-'+i+'-'+j)));
      const result = await rpc('modeler.measure', {mode:mode.value, units:unit.value, points});
      output.textContent = result.text + '\n\n' + (result.accuracy || '');
      if (result.size) output.textContent += '\nXYZ size: ' + result.size.map(x=>fmtLen(x,result.units)).join(' × ');
      if (result.center) output.textContent += '\nCenter: ' + result.center.map(x=>fmtLen(x,result.units)).join(', ');
      if (result.diagonal != null) output.textContent += '\nBounding-box diagonal: ' + fmtLen(result.diagonal,result.units);
      if (result.primitive) for (const [key,value] of Object.entries(result.primitive)) {
        const power=key==='volume'?3:key==='area'?2:1;
        const suffix=power===3?'³':power===2?'²':'';
        output.textContent+='\n'+key+': '+(value/UNIT_SCALE[result.units]**power).toPrecision(8)+' '+result.units+suffix;
      }
      exportBtn.disabled = false; exportBtn.onclick = ()=>downloadMeasurement(result);
      MEASURE = result; VP && VP.setMeasure(result.line || null); placeMeasureLabel();
    } catch(e) { output.textContent = e.message; exportBtn.disabled = true; }
    finally { calculate.disabled = false; }
  }}, 'Calculate');
  body.appendChild(el('div', {class:'dim-actions'}, calculate, exportBtn)); body.appendChild(output);
  const toggle = () => {
    coordinates.hidden = mode.value === 'selection';
    coordinates.lastChild.hidden = mode.value === 'distance';
    picks.hidden = mode.value === 'selection';
  };
  mode.addEventListener('change', toggle); toggle();
  dialog({title:'Measure / Dimensions',body,ok:null,cancel:'Close'});
}
async function dlgResize() {
  if (STATE?.selection?.length !== 1) return toastError('Select exactly one object to resize.');
  const name = STATE.selection[0];
  await guard(async () => {
    const r = await rpc('modeler.measure');
    if (!r.size || r.kind !== 'object') throw new Error('Switch to object selection and select one object.');
    const body = el('div');
    for (let i=0;i<3;i++) body.appendChild(field('XYZ'[i]+' size ('+U()+')', inp('resize-'+i, String(r.size[i]/UNIT_SCALE[U()]))));
    body.appendChild(field('Keep fixed', sel('resize-anchor',[['center','Bounding-box center'],['min','Minimum XYZ corner']],'center')));
    body.appendChild(el('div',{class:'hint'},'Changes the world-axis bounding-box dimensions by scaling. Unequal XYZ factors can turn circles into ellipses. Use primitive properties to change a radius directly. Zero-thickness sheets require Sweep Face.'));
    dialog({title:'Resize '+name,body,ok:'Apply',onOk:async()=>{
      await rpc('modeler.resize',{name, size:[0,1,2].map(i=>gv('resize-'+i)+U()),anchor:gv('resize-anchor')});
      clearLocalPicks(); await refreshGeometry(false);
    }});
  });
}


let MEASURE_PICK = null;
function startMeasurePick(mode) {
  if (!VP) return toastError('3-D viewport is unavailable.');
  if (DRAW) cancelPointDraw();
  clearPicks();
  MEASURE_PICK = {mode, points:[]};
  $('#vp-hint').textContent = 'Measure '+mode+': click '+(mode==='distance'?'2':'3')+' points · vertex snap within 12 px · Esc cancels';
}
function cancelMeasurePick() {
  MEASURE_PICK=null; VP && VP.setDraft(null);VP && VP.setHover(null);
  $('#vp-hint').textContent='click select · drag rotate · wheel zoom';
}
function measurementHit(px,py) {
  const hit=VP.pickFeature(px,py,'point');
  VP.setHover(hit,'point');
  if(hit){$('#vp-hint').textContent=hit.name+' · '+hit.snapKind+' · '+hit.point.map(x=>fmtLen(x,U())).join(', ');return hit.point;}
  $('#vp-hint').textContent='Move within 12 px of a visible vertex/edge sample · Esc cancels';
  return null;
}
function measurePickHover(px,py) {
  if (!MEASURE_PICK) return;
  const point=measurementHit(px,py);
  if (point && MEASURE_PICK.points.length) VP.setDraft([...MEASURE_PICK.points,point]);
}
function measurePickClick(px,py) {
  const point=measurementHit(px,py); if (!point) return true;
  if(MEASURE_PICK.points.some(p=>Math.hypot(...p.map((v,i)=>v-point[i]))<1e-12)){toastError('Choose a different point.');return true;}
  MEASURE_PICK.points.push(point);VP.setPointSelection(MEASURE_PICK.points);
  const n=MEASURE_PICK.mode==='distance'?2:3;
  if (MEASURE_PICK.points.length<n) {
    VP.setDraft(MEASURE_PICK.points);
    $('#vp-hint').textContent='Measure: '+MEASURE_PICK.points.length+'/'+n+' points selected · Esc cancels';
    return true;
  }
  const {mode,points}=MEASURE_PICK;cancelMeasurePick();
  showPointMeasurement(mode,points);

  return true;
}


/* Where the cursor is, in model coordinates, at all times.
   A modeller without a coordinate readout leaves you guessing what a click is
   about to mean. It reads the point under the cursor when there is geometry
   there, and the work plane when there is not. */
function updateCursorReadout(px, py) {
  const box = $('#status-xyz');
  if (!box || !VP) return;
  let p = null;
  try {
    const hit = VP.planePoint(px, py, null);
    if (hit) p = hit.point;
  } catch (e) { p = null; }
  box.textContent = p
    ? ['X', 'Y', 'Z'].map((a, k) => `${a} ${fmtLen(p[k], U())}`).join('  ')
    : '';
}

function previewSelection(px,py) {
  updateCursorReadout(px, py);
  const hit=VP.pickFeature(px,py,SEL_MODE);VP.setHover(hit,SEL_MODE);
  $('#vp-hint').textContent=hit?SEL_MODE+' · '+hit.name+(hit.vertex?' · '+hit.snapKind:''):'double-click object · O/F/E/V selection · Ctrl+D fit';
}
function pickVertex(hit,add) {
  if(!hit.vertex)return;
  POINT_PICKS=POINT_PICKS.length===1?POINT_PICKS.concat([hit.point]):[hit.point];
  VP.setPointSelection(POINT_PICKS);
  $('#vp-hint').textContent='Point: '+hit.point.map(x=>fmtLen(x,U())).join(', ')+' · click second point to measure';
  if(POINT_PICKS.length===2)showPointMeasurement('distance',POINT_PICKS);
}
async function showPointMeasurement(mode,points) {
  POINT_MEASURE_PINNED=true;const revision=++MEASURE_REVISION;
  await guard(async()=>{
    const result=await rpc('modeler.measure',{mode,points:points.map(p=>p.map(x=>x+'m')),units:U()});
    if(revision!==MEASURE_REVISION)return;
    result.text += '\n'+points.map((p,i)=>'P'+(i+1)+' (X, Y, Z): '+p.map(x=>fmtLen(x,U())).join(', ')).join('\n');
    if(points.length===2)result.text+='\nΔX, ΔY, ΔZ: '+points[1].map((x,i)=>fmtLen(x-points[0][i],U())).join(', ');
    MEASURE=result;VP.setMeasure(result.line||null);VP.setPointSelection(points);
    $('#vp-measure').textContent=result.text;$('#vp-measure').style.display='block';placeMeasureLabel();
    const body=el('div',{},el('pre',{class:'dim-result'},result.text),el('div',{class:'hint'},'Measured between selected displayed vertices. Curved edge samples are tessellated; inspect coordinates for precision work.'),el('button',{onclick:()=>downloadMeasurement(result)},'Export CSV'),el('button',{onclick:()=>keepMeasurement()},'Keep on screen'),el('button',{onclick:()=>toggleMeasurements()},'Show / Hide'));
    dialog({title:'Picked-point measurement',body,ok:null,cancel:'Close'});
  });
}

async function dlgImportStatus(status) {
  await guard(async()=>{
    const r=status||await rpc('project.importStatus');
    const body=el('div',{},el('p',{},r.errors.length?'Import is incomplete. Solve is blocked until these items are repaired.':'No unresolved import blockers recorded.'),
      el('p',{class:'hint'},'Native Parasolid bodies cannot be decoded by this OCC importer. Export the affected bodies from HFSS to STEP, then select each matching object and use Replace CAD Source. Reassign unknown materials and review ports, boundaries and PML.'),
      ...r.errors.map(e=>el('p',{class:'eng-error'},e)),
      el('button',{onclick:()=>exportCsvFile('aether-import-status.csv',[['Design','Issue'],...r.errors.map(e=>[r.design,e])])},'Export issue list CSV'));
    dialog({title:'HFSS Import Status — '+r.design,body,width:'wide',ok:null,cancel:'Close'});
  });
}

// Kept annotations are world-coordinate snapshots, scoped to this open document.
let KEPT_MEASUREMENTS=[], MEASUREMENTS_VISIBLE=true;
function keepMeasurement(){if(!MEASURE)return;KEPT_MEASUREMENTS.push(JSON.parse(JSON.stringify(MEASURE)));renderKeptMeasurements();}
function clearKeptMeasurements(){KEPT_MEASUREMENTS=[];renderKeptMeasurements();}
function toggleMeasurements(){MEASUREMENTS_VISIBLE=!MEASUREMENTS_VISIBLE;if(VP)VP.measureVisible=MEASUREMENTS_VISIBLE;$('#vp-measure').style.visibility=MEASUREMENTS_VISIBLE?'visible':'hidden';placeMeasureLabel();renderKeptMeasurements();}
function renderKeptMeasurements(){
  if(!VP)return;let panel=$('#kept-measurements');
  if(!panel){panel=el('div',{id:'kept-measurements',style:'position:absolute;right:12px;top:55px;max-width:360px;max-height:45%;overflow:auto;z-index:4;background:#202a35e8;color:#d2f6ff;padding:8px;font-size:12px;white-space:pre-wrap'});$('#viewport').appendChild(panel);}
  panel.style.display=MEASUREMENTS_VISIBLE&&KEPT_MEASUREMENTS.length?'block':'none';panel.replaceChildren();
  KEPT_MEASUREMENTS.forEach((m,i)=>panel.appendChild(el('div',{},el('button',{onclick:()=>{KEPT_MEASUREMENTS.splice(i,1);renderKeptMeasurements();}},'×'), ' '+(i+1)+'. '+m.text+'\n')));
}
