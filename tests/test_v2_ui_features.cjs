const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

class FakeClassList {
  constructor(el) { this.el = el; }
  _list() { return String(this.el.className || '').split(/\s+/).filter(Boolean); }
  contains(cls) { return this._list().includes(cls); }
  add(...names) { const s = new Set(this._list()); names.forEach(n => n && s.add(n)); this.el.className = [...s].join(' '); }
  remove(...names) { const r = new Set(names); this.el.className = this._list().filter(n => !r.has(n)).join(' '); }
  toggle(cls, force) { const has = this.contains(cls); const on = force === undefined ? !has : !!force; if (on) this.add(cls); else this.remove(cls); return on; }
}

function matchSingle(node, sel) {
  sel = sel.trim();
  if (!sel) return false;
  let rest = sel;
  const openAttr = rest.includes('[open]');
  if (openAttr) rest = rest.replace('[open]', '');
  const idMatch = rest.match(/#([A-Za-z0-9_-]+)/);
  if (idMatch) {
    if (node.id !== idMatch[1]) return false;
    rest = rest.replace(idMatch[0], '');
  }
  const classes = [];
  rest = rest.replace(/\.([A-Za-z0-9_-]+)/g, (_, c) => { classes.push(c); return ''; });
  const tag = rest.trim().toUpperCase();
  if (tag && node.tagName !== tag) return false;
  if (openAttr && !node.open) return false;
  for (const c of classes) if (!node.classList.contains(c)) return false;
  return true;
}

class FakeElement {
  constructor(tag = 'div') {
    this.tagName = String(tag).toUpperCase();
    this.id = '';
    this.className = '';
    this.classList = new FakeClassList(this);
    this.dataset = {};
    this.style = {};
    this.children = [];
    this.parentElement = null;
    this.open = false;
    this._text = '';
    this._innerHTML = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.attributes = {};
    this.listeners = {};
  }
  set textContent(v) { this._text = String(v ?? ''); if (!v) this.children = []; }
  get textContent() { return this.children.length ? this.children.map(c => c.textContent).join('') : this._text; }
  set innerHTML(v) { this._innerHTML = String(v ?? ''); if (!v) this.children = []; }
  get innerHTML() { return this._innerHTML; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'open') this.open = true; if (k === 'id') this.id = String(v); }
  getAttribute(k) { return k === 'id' ? this.id : (this.attributes[k] ?? null); }
  appendChild(child) {
    if (!child) return child;
    if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(c => c !== child);
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  append(...nodes) { for (const n of nodes) if (typeof n !== 'string') this.appendChild(n); else this._text += n; }
  prepend(...nodes) { let ref = this.children[0] || null; for (const n of nodes) if (typeof n !== 'string') this.insertBefore(n, ref); else this._text = n + this._text; }
  insertBefore(child, ref) {
    if (!ref) return this.appendChild(child);
    if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(c => c !== child);
    child.parentElement = this;
    const idx = this.children.indexOf(ref);
    if (idx < 0) this.children.push(child); else this.children.splice(idx, 0, child);
    return child;
  }
  replaceChildren(...nodes) { this.children.forEach(c => { c.parentElement = null; }); this.children = []; this.append(...nodes); }
  remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(c => c !== this); this.parentElement = null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  closest(sel) { let cur = this; while (cur) { if (matchSingle(cur, sel)) return cur; cur = cur.parentElement; } return null; }
  querySelectorAll(sel) {
    const out = [];
    if (sel.startsWith(':scope > ')) {
      const sub = sel.slice(':scope > '.length);
      for (const c of this.children) if (matchSingle(c, sub)) out.push(c);
      return out;
    }
    const walk = (node) => {
      for (const c of node.children) {
        if (matchSingle(c, sel)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

// ---------------------------------------------------------------------------
// 1. Collapsible Tool Trace (chat.js)
// ---------------------------------------------------------------------------
{
  const chatSrc = fs.readFileSync(path.join(ROOT, 'agent/ui/app/chat.js'), 'utf8');
  const start = chatSrc.indexOf('function toolName(call)');
  const end = chatSrc.indexOf('function refreshChatTranslations()');
  assert(start >= 0 && end > start, 'chat.js slice anchors missing');

  const body = new FakeElement('body');
  const chatRoot = new FakeElement('div');
  chatRoot.id = 'chat';
  body.appendChild(chatRoot);

  const timers = [];
  const doc = {
    createElement: tag => new FakeElement(tag),
    querySelector: sel => sel === '#chat .tool-trace' ? chatRoot.querySelector('.tool-trace') : null,
    querySelectorAll: sel => sel === '#chat .tool-trace' ? chatRoot.querySelectorAll('.tool-trace') : [],
    getElementById: () => null,
    body,
  };
  const chatCtx = {
    window: {},
    document: doc,
    uiText: s => s,
    addEl: null,
    setInterval: fn => { timers.push(fn); return timers.length; },
    clearInterval: () => {},
    prettyJson: v => JSON.stringify(v, null, 2),
    formatTokens: n => String(n ?? 0),
    textPreview: (v, limit = 160) => String(v || '').slice(0, limit),
    shortDuration: ms => `${ms} ms`,
    fileNameFromPath: p => String(p || '').split(/[\\/]/).pop() || String(p || ''),
    compactText: s => String(s || ''),
    hasUsefulDraft: () => false,
    readableDraft: () => '',
    S: { permissionMode: 'auto' },
    busy: false,
    note() {},
    requestJSON: async () => ({}),
    downloadTextFile() {},
    renderMessageFiles() {},
    scrollDown() {},
    userNearBottom: true,
    chatFollow: true,
    console,
  };
  chatCtx.addEl = (parent, tag, cls, text) => {
    const el = doc.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    parent.appendChild(el);
    return el;
  };
  chatCtx.window = chatCtx;
  vm.createContext(chatCtx);
  vm.runInContext(chatSrc.slice(start, end), chatCtx);

  const row = new FakeElement('div');
  row.className = 'msg assistant';
  chatRoot.appendChild(row);

  const trace = [
    { id: 'c1', name: 'pc__fs_read', arguments: { path: 'notes.txt' }, status: 'running', summary: 'notes.txt' },
    { id: 'c2', name: 'pc__shell_run', arguments: { command: 'echo ok' }, status: 'error', result: 'boom', summary: 'echo ok', elapsed: 42 },
  ];
  const sec = chatCtx.renderToolTrace(row, trace);
  const group = sec.querySelector(':scope > details.tool-trace-group');
  assert(group, 'tool-trace-group should exist');
  assert.equal(group.open, false, 'tool history must be collapsed by default');

  const cards = sec.querySelectorAll('details.tool');
  assert.equal(cards.length, 2, 'each tool call has its own collapsible details.tool');
  assert.equal(cards[0].open, false, 'individual tool c1 must start collapsed');
  assert.equal(cards[1].open, false, 'individual tool c2 must start collapsed');

  const overviewLabel = sec.querySelector('.tool-overview-label');
  const overviewDetail = sec.querySelector('.tool-overview-detail');
  assert(overviewLabel, '.tool-overview-label should exist');
  assert(overviewDetail, '.tool-overview-detail should exist');
  assert(overviewLabel.textContent.includes('Ejecutando'), `expected running label, got ${overviewLabel.textContent}`);
  assert(overviewDetail.textContent.includes('Leer archivo'), `expected active tool title, got ${overviewDetail.textContent}`);

  // Simulate __valToolTicker tick: must NOT remove chevron or detail spans
  assert(timers.length > 0, '__valToolTicker should register');
  timers[0]();
  assert(sec.querySelector('.tool-overview-chevron'), 'chevron must survive ticker update');
  assert(sec.querySelector('.tool-overview-detail'), 'detail must survive ticker update');

  // Expanding group & individual card reveals parameters/result
  group.open = true;
  cards[1].open = true;
  assert.equal(group.open, true);
  assert(cards[1].querySelector('.tool-body'), 'tool body present inside details.tool');

  // Finish trace cleanly
  trace[0].status = 'ok';
  trace[0].elapsed = 15;
  trace[0].result = 'contenido de prueba';
  trace[1].status = 'ok';
  trace[1].result = 'ok';
  chatCtx.updateToolTrace(sec, trace);
  assert.equal(group.open, true, 'updating completed trace keeps user open state');
  assert(overviewLabel.textContent.includes('2 herramientas'), `expected 2 herramientas, got ${overviewLabel.textContent}`);
}

// ---------------------------------------------------------------------------
// 2. Minor updates (core-connection.js live hot-patch + events)
// ---------------------------------------------------------------------------
{
  const ccSrc = fs.readFileSync(path.join(ROOT, 'agent/ui/app/core-connection.js'), 'utf8');
  const scripts = [];
  const head = new FakeElement('head');
  const docBody = new FakeElement('body');
  const doc = {
    head,
    body: docBody,
    createElement: tag => {
      const el = new FakeElement(tag);
      scripts.push(el);
      return el;
    },
    getElementById: id => head.children.find(c => c.id === id) || docBody.children.find(c => c.id === id) || null,
    dispatchEvent: () => {},
  };
  const ccCtx = {
    window: { addEventListener() {} },
    document: doc,
    setTimeout: () => 1,
    clearTimeout: () => {},
    console,
    fetch: async () => ({ ok: true, text: async () => '/* patch */', json: async () => ({}) }),
    base: 'http://127.0.0.1:19380',
    Date,
  };
  const fnStart = ccSrc.indexOf('function loadUiPatch(');
  const fnEnd = ccSrc.indexOf('async function watchAutomaticUpdates(');
  assert(fnStart >= 0 && fnEnd > fnStart);
  vm.createContext(ccCtx);
  vm.runInContext(ccSrc.slice(fnStart, fnEnd), ccCtx);

  (async () => {
    ccCtx.loadUiPatch(false);
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    assert.equal(docBody.children.filter(c => c.id === 'uiPatchJs').length, 1, 'initial #uiPatchJs loaded');
    const createdBefore = scripts.length;
    ccCtx.loadUiPatch(false);
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    assert.equal(scripts.length, createdBefore, 'non-forced call skips duplicate #uiPatchJs');
    ccCtx.loadUiPatch(true);
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    assert.equal(scripts.length, createdBefore + 1, 'forced component update reloads #uiPatchJs cleanly');
    assert.equal(docBody.children.filter(c => c.id === 'uiPatchJs').length, 1, 'previous #uiPatchJs replaced cleanly');
  })();
}

// ---------------------------------------------------------------------------
// 3 & 4. Optional local engines + No forced install popups (shell.js, tour.js, engine-controls.js)
// ---------------------------------------------------------------------------
{
  const shellSrc = fs.readFileSync(path.join(ROOT, 'agent/ui/app/shell.js'), 'utf8');
  const sBegin = shellSrc.indexOf('  function renderUpdateStack(state){');
  const sEnd = shellSrc.indexOf('  async function pollUpdates(', sBegin);
  assert(sBegin >= 0 && sEnd > sBegin);

  const stack = new FakeElement('div');
  stack.id = 'updateStack';
  const ctx = {
    stack,
    window: { addEventListener() {} },
    document: { getElementById: id => id === 'updateStack' ? stack : null, createElement: tag => new FakeElement(tag), body: new FakeElement('body') },
    $: sel => sel === '#updateStack' ? stack : null,
    el: (tag, cls, text) => { const n = new FakeElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; },
    uiText: s => s,
    updateNoticeDismissed: () => false,
    updateButtonLabel: () => 'Actualizar',
    positionUpdateStack() {},
    requestAnimationFrame: fn => fn(),
    dismissUpdateNotice() {},
    triggerEngineAction() {},
    startEngineUpdate() {},
    openGeneralUpdates() {},
    showPanel() {},
    openAppUpdateDialog() {},
    engineActionLabel: () => 'Actualizar',
    compactReleaseSummary: s => s || '',
    noteSummaryCache: new Map(),
    dismissed: new Set(),
    latestAppUpdate: null,
    lastEngineUpdates: null,
    updateBusy: false,
    busy: false,
    loadedModel: null,
    localModelLoaded: () => false,
    UPDATE_LABELS: { 'llama-cuda': 'llama.cpp CUDA', rust: 'Strata Rust' },
    appUpdateState: { update_available: false },
    engineUpdateState: {},
    Date,
    console,
  };
  vm.createContext(ctx);
  vm.runInContext(shellSrc.slice(sBegin, sEnd), ctx);

  // Uninstalled engines with newer release available MUST NOT trigger floating update popup banner
  ctx.renderUpdateStack({
    installed: { 'llama-cuda': false, rust: false },
    releases: {
      'llama-cuda': { current: '', tag: 'b5000', available: true, asset: 'llama-cuda.zip' },
      rust: { current: '', tag: 'v0.9.0', available: true, asset: 'strata-rust.zip' },
    },
  });
  assert.equal(stack.children.length, 0, 'uninstalled engines must never trigger forced install popups');

  // An actually installed engine with a newer version SHOULD show update notice
  ctx.renderUpdateStack({
    installed: { 'llama-cuda': true, rust: false },
    releases: {
      'llama-cuda': { current: 'b4900', tag: 'b5000', available: true, asset: 'llama-cuda.zip' },
      rust: { current: '', tag: 'v0.9.0', available: true, asset: 'strata-rust.zip' },
    },
  });
  assert.equal(stack.children.length, 1, 'installed engine update should appear cleanly');

  // Verify tour.js & engine-controls.js expose optional engine choice and API header controls
  const tourSrc = fs.readFileSync(path.join(ROOT, 'agent/ui/app/tour.js'), 'utf8');
  assert(tourSrc.includes('Motor o API (opcional)'), 'tour must mark local engine/API step optional');
  assert(tourSrc.includes('tour-engine-select'), 'tour must allow choosing any local engine');

  const ecSrc = fs.readFileSync(path.join(ROOT, 'agent/ui/app/engine-controls.js'), 'utf8');
  for (const id of ['apiPreset', 'apiAuthMode', 'apiUserAgentPreset', 'apiUserAgent', 'apiSessionMode', 'apiAnthropicBeta', 'apiAzureVersion', 'apiHttpReferer', 'apiXTitle', 'apiExtraHeaders']) {
    assert(ecSrc.includes(`id="${id}"`) && ecSrc.includes(`#${id}`), `missing control ${id} in engine-controls.js`);
  }
  assert(ecSrc.includes("2023-06-01"), 'default anthropic version must be 2023-06-01');
}

console.log('V2 UI features (collapsible tool trace, live minor updates, optional engines, hardened API controls) passed.');
