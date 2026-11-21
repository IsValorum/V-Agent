/* ---------- buscador rápido, búsqueda en chat, plantillas, telemetría de uso y atajos ---------- */
function setupPolishUI() {
  const showSheet = el => {
    for (const other of document.querySelectorAll('.val-sheet:popover-open')) if (other !== el) other.hidePopover();
    try { el.showPopover(); } catch { el.hidden = false; }
  };
  const hideSheet = el => {
    try { if (el.matches(':popover-open')) el.hidePopover(); } catch { el.hidden = true; }
  };
  const isSheetOpen = el => {
    try { return el.matches(':popover-open'); } catch { return !el.hidden; }
  };

  // 1. V-Agent Quick Switcher (non-modal popover anchored below the topbar, with category tabs)
  const palette = document.createElement('div');
  palette.id = 'commandPalette';
  palette.className = 'val-sheet val-switcher';
  palette.setAttribute('popover', 'manual');
  palette.setAttribute('role', 'dialog');
  palette.setAttribute('aria-label', uiText('Paleta de comandos'));
  palette.innerHTML = '<div class="cmd-head"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input id="cmdInput" type="search" autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div><div id="cmdTabs" class="cmd-tabs" role="tablist"></div><div id="cmdList" class="cmd-list" role="listbox"></div>';
  document.body.append(palette);
  const cmdInput = palette.querySelector('#cmdInput'), cmdTabs = palette.querySelector('#cmdTabs'), cmdList = palette.querySelector('#cmdList');
  let cmdItems = [], cmdActive = 0, cmdFilter = 'all';

  function renderSwitcherTabs() {
    const tabs = [['all', 'Todo'], ['actions', 'Acciones'], ['chats', 'Conversaciones'], ['models', 'Modelos']];
    cmdTabs.replaceChildren(...tabs.map(([id, label]) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'cmd-tab';
      b.dataset.tab = id;
      b.setAttribute('role', 'tab');
      b.setAttribute('aria-selected', String(cmdFilter === id));
      b.textContent = uiText(label);
      b.onclick = () => { cmdFilter = id; cmdActive = 0; renderSwitcherTabs(); renderPalette(); cmdInput.focus(); };
      return b;
    }));
  }

  function buildCommands(rawQuery) {
    const fold = s => String(s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase();
    const q = fold(rawQuery.trim());
    const actions = [
      { kind: 'actions', group: 'Acciones', label: 'Nuevo chat', hint: '', run: () => newConv() },
      { kind: 'actions', group: 'Acciones', label: 'Chat temporal', hint: '', run: () => newTempConv() },
      { kind: 'actions', group: 'Acciones', label: 'Buscar en la conversación', hint: 'Ctrl+F', run: () => openChatFind() },
      { kind: 'actions', group: 'Acciones', label: 'Biblioteca de prompts', hint: '', run: () => openPromptLibrary() },
      { kind: 'actions', group: 'Acciones', label: 'Estadísticas de uso', hint: '', run: () => { setDrawer(true); selectSettingsCategory('usage'); } },
      { kind: 'actions', group: 'Acciones', label: 'Atajos de teclado', hint: 'Ctrl+/', run: () => openShortcutsDialog() },
      { kind: 'actions', group: 'Acciones', label: 'Instrucciones permanentes (AGENTS.md)', hint: '', run: () => { setDrawer(true); selectSettingsCategory('general'); requestAnimationFrame(() => $('#globalInstructions')?.focus()); } },
      { kind: 'actions', group: 'Acciones', label: 'Cambiar tema claro/oscuro', hint: '', run: () => $('#themeBtn')?.click() },
      { kind: 'actions', group: 'Acciones', label: 'Modelo y motor', hint: '', run: () => setChatControls('model') },
      { kind: 'actions', group: 'Acciones', label: 'Abrir consola', hint: '', run: () => $('#openConsole')?.click() },
      { kind: 'actions', group: 'Acciones', label: 'Abrir navegador', hint: '', run: () => $('#openBrowser')?.click() },
      { kind: 'actions', group: 'Acciones', label: 'Configuración', hint: '', run: () => setDrawer(true) },
    ].map(item => ({ ...item, text: uiText(item.label), groupLabel: uiText(item.group) }));

    const chats = [...(convs || [])]
      .filter(c => !c.archived)
      .sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || (b.ts || 0) - (a.ts || 0))
      .slice(0, 20)
      .map(c => ({
        kind: 'chats',
        groupLabel: uiText('Conversaciones'),
        text: (c.pinned ? '★ ' : '') + (c.title === 'Nuevo chat' ? uiText('Nuevo chat') : (c.title || uiText('Sin título'))),
        hint: c.id === currentId ? uiText('Actual') : '',
        run: () => openConv(c.id),
      }));

    const models = (modelCatalog || [])
      .filter(m => m.status !== 'unavailable')
      .slice(0, 15)
      .map(m => ({
        kind: 'models',
        groupLabel: uiText('Modelos'),
        text: modelFileName(m),
        hint: m.id === loadedModel ? uiText('En memoria') : '',
        run: () => {
          const sel = $('#model');
          if (sel) { sel.value = m.id; sel.dispatchEvent(new Event('change')); }
          setChatControls('model');
        },
      }));

    const pool = cmdFilter === 'actions' ? actions : cmdFilter === 'chats' ? chats : cmdFilter === 'models' ? models : [...actions, ...chats, ...models];
    return q ? pool.filter(item => fold(item.text + ' ' + item.groupLabel + ' ' + item.hint).includes(q)) : pool.slice(0, 18);
  }

  function renderPalette() {
    cmdItems = buildCommands(cmdInput.value);
    cmdActive = Math.min(cmdActive, Math.max(0, cmdItems.length - 1));
    cmdList.replaceChildren();
    if (!cmdItems.length) {
      const empty = document.createElement('div');
      empty.className = 'cmd-empty';
      empty.textContent = uiText('Sin resultados');
      cmdList.append(empty);
      return;
    }
    let lastGroup = '';
    cmdItems.forEach((item, index) => {
      if (cmdFilter === 'all' && item.groupLabel !== lastGroup) {
        lastGroup = item.groupLabel;
        const heading = document.createElement('div');
        heading.className = 'cmd-group';
        heading.textContent = lastGroup;
        cmdList.append(heading);
      }
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cmd-item' + (index === cmdActive ? ' active' : '');
      btn.setAttribute('role', 'option');
      btn.setAttribute('aria-selected', String(index === cmdActive));
      const span = document.createElement('span');
      span.className = 'cmd-label';
      span.textContent = item.text;
      btn.append(span);
      if (item.hint) {
        const hint = document.createElement('kbd');
        hint.textContent = item.hint;
        btn.append(hint);
      }
      btn.onmouseenter = () => { cmdActive = index; syncPaletteActive(); };
      btn.onclick = () => { closeCommandPalette(); item.run(); };
      cmdList.append(btn);
    });
  }

  function syncPaletteActive() {
    const buttons = [...cmdList.querySelectorAll('.cmd-item')];
    buttons.forEach((b, i) => {
      b.classList.toggle('active', i === cmdActive);
      b.setAttribute('aria-selected', String(i === cmdActive));
    });
    buttons[cmdActive]?.scrollIntoView({ block: 'nearest' });
  }

  function openCommandPalette() {
    cmdInput.placeholder = uiText('Buscar acciones, chats o modelos…');
    cmdInput.setAttribute('aria-label', uiText('Buscar acciones, chats o modelos…'));
    palette.setAttribute('aria-label', uiText('Paleta de comandos'));
    cmdInput.value = '';
    cmdFilter = 'all';
    cmdActive = 0;
    renderSwitcherTabs();
    renderPalette();
    showSheet(palette);
    cmdInput.focus();
  }
  function closeCommandPalette() { hideSheet(palette); }
  window.openCommandPalette = openCommandPalette;

  cmdInput.addEventListener('input', () => { cmdActive = 0; renderPalette(); });
  cmdInput.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); if (cmdItems.length) { cmdActive = (cmdActive + 1) % cmdItems.length; syncPaletteActive(); } }
    else if (event.key === 'ArrowUp') { event.preventDefault(); if (cmdItems.length) { cmdActive = (cmdActive - 1 + cmdItems.length) % cmdItems.length; syncPaletteActive(); } }
    else if (event.key === 'Enter' && cmdItems[cmdActive]) { event.preventDefault(); const fn = cmdItems[cmdActive].run; closeCommandPalette(); fn(); }
    else if (event.key === 'Escape') { event.preventDefault(); closeCommandPalette(); }
  });

  // 2. Find in conversation (Ctrl+F) — lightweight inline bar inside #chatwrap
  const findBar = document.createElement('div');
  findBar.id = 'chatFindBar';
  findBar.className = 'chat-find-bar';
  findBar.hidden = true;
  findBar.setAttribute('role', 'search');
  findBar.innerHTML = '<input id="chatFindInput" type="search" autocomplete="off"><span id="chatFindCount" class="chat-find-count">0 / 0</span><button id="chatFindPrev" type="button">‹</button><button id="chatFindNext" type="button">›</button><button id="chatFindClose" type="button">×</button>';
  $('#chatwrap')?.append(findBar);
  const findInput = findBar.querySelector('#chatFindInput'), findCount = findBar.querySelector('#chatFindCount');
  let findMatches = [], findCursor = 0;

  function clearFindHighlights() {
    for (const el of document.querySelectorAll('#chat .msg-find-hit, #chat .msg-find-active')) {
      el.classList.remove('msg-find-hit', 'msg-find-active');
    }
  }
  function updateChatFind() {
    clearFindHighlights();
    const fold = s => String(s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase();
    const q = fold(findInput.value.trim());
    findMatches = [];
    if (q) {
      for (const msg of document.querySelectorAll('#chat > .msg')) {
        if (fold(msg.textContent).includes(q)) {
          msg.classList.add('msg-find-hit');
          findMatches.push(msg);
        }
      }
    }
    findCursor = 0;
    syncChatFindCursor();
  }
  function syncChatFindCursor() {
    for (const el of document.querySelectorAll('#chat .msg-find-active')) el.classList.remove('msg-find-active');
    const prev = findBar.querySelector('#chatFindPrev'), next = findBar.querySelector('#chatFindNext');
    if (!findMatches.length) {
      findCount.textContent = '0 / 0';
      prev.disabled = next.disabled = true;
      return;
    }
    findCursor = (findCursor + findMatches.length) % findMatches.length;
    const active = findMatches[findCursor];
    active.classList.add('msg-find-active');
    setFollow(false);
    active.scrollIntoView({ behavior: 'smooth', block: 'center' });
    findCount.textContent = (findCursor + 1) + ' / ' + findMatches.length;
    prev.disabled = next.disabled = findMatches.length < 2;
  }
  function openChatFind() {
    findInput.placeholder = uiText('Buscar en esta conversación…');
    findInput.setAttribute('aria-label', uiText('Buscar en esta conversación…'));
    findBar.querySelector('#chatFindPrev').setAttribute('aria-label', uiText('Resultado anterior'));
    findBar.querySelector('#chatFindNext').setAttribute('aria-label', uiText('Resultado siguiente'));
    findBar.querySelector('#chatFindClose').setAttribute('aria-label', uiText('Cerrar búsqueda'));
    findBar.hidden = false;
    findInput.focus();
    findInput.select();
    updateChatFind();
  }
  function closeChatFind() {
    if (findBar.hidden) return;
    findBar.hidden = true;
    findInput.value = '';
    findMatches = [];
    clearFindHighlights();
  }
  window.openChatFind = openChatFind;
  findInput.addEventListener('input', updateChatFind);
  findInput.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeChatFind(); }
    else if (event.key === 'Enter') { event.preventDefault(); findCursor += event.shiftKey ? -1 : 1; syncChatFindCursor(); }
  });
  findBar.querySelector('#chatFindPrev').onclick = () => { findCursor--; syncChatFindCursor(); };
  findBar.querySelector('#chatFindNext').onclick = () => { findCursor++; syncChatFindCursor(); };
  findBar.querySelector('#chatFindClose').onclick = closeChatFind;

  // 3. Prompt Library — non-modal V-Agent side sheet anchored to the top-right (can save current composer draft)
  const PROMPT_KEY = 'valPromptLibraryV1';
  const DEFAULT_PROMPTS = [
    { id: 'summary', title: 'Resumir puntos clave', text: 'Resume lo siguiente en 5 puntos claros y accionables:' },
    { id: 'review', title: 'Revisar y mejorar texto', text: 'Revisa este texto para mejorar claridad, tono y precisión sin cambiar su significado:' },
    { id: 'plan', title: 'Plan paso a paso', text: 'Ayúdame a dividir este objetivo en pasos concretos, indicando riesgos y orden recomendado:' },
  ];
  function loadPrompts() {
    try {
      const raw = localStorage.getItem(PROMPT_KEY);
      if (!raw) return DEFAULT_PROMPTS.map(p => ({ ...p, title: uiText(p.title), text: uiText(p.text) }));
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch { return []; }
  }
  function savePrompts(list) { try { localStorage.setItem(PROMPT_KEY, JSON.stringify(list)); } catch {} }

  const promptDlg = document.createElement('div');
  promptDlg.id = 'promptLibraryDialog';
  promptDlg.className = 'val-sheet val-prompts-sheet';
  promptDlg.setAttribute('popover', 'manual');
  promptDlg.setAttribute('role', 'dialog');
  promptDlg.innerHTML = '<div class="fw-head"><h2 id="promptLibTitle"></h2><button id="promptLibClose" class="icon-btn" type="button">×</button></div><div class="prompt-lib-body"><div class="prompt-lib-bar"><input id="promptLibSearch" type="search" autocomplete="off"><button id="promptLibNew" type="button" class="soft-btn primary"></button></div><form id="promptLibForm" class="prompt-lib-form" hidden><input id="promptFormTitle" type="text" maxlength="80" required><textarea id="promptFormText" rows="4" required></textarea><div class="prompt-form-actions"><button id="promptFormCancel" type="button" class="soft-btn"></button><button type="submit" class="soft-btn primary" id="promptFormSave"></button></div></form><div id="promptLibList" class="prompt-lib-list"></div></div>';
  document.body.append(promptDlg);
  const promptSearch = promptDlg.querySelector('#promptLibSearch'), promptList = promptDlg.querySelector('#promptLibList'), promptForm = promptDlg.querySelector('#promptLibForm');

  function renderPromptLibrary() {
    const fold = s => String(s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase();
    const q = fold(promptSearch.value.trim());
    const items = loadPrompts().filter(p => !q || fold(p.title + ' ' + p.text).includes(q));
    promptList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'mini';
      empty.textContent = uiText('No hay plantillas que coincidan.');
      promptList.append(empty);
      return;
    }
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'prompt-row';
      const main = document.createElement('button');
      main.type = 'button';
      main.className = 'prompt-use';
      const title = document.createElement('strong');
      title.textContent = item.title;
      const preview = document.createElement('small');
      preview.textContent = item.text.replace(/\s+/g, ' ').trim();
      main.append(title, preview);
      main.onclick = () => {
        const input = $('#input');
        if (input) {
          const suffix = item.text.endsWith(':') ? '\n\n' : '';
          input.value = (input.value ? input.value + '\n\n' : '') + item.text + suffix;
          resizeInput();
          hideSheet(promptDlg);
          input.focus();
        }
      };
      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'prompt-del';
      del.textContent = '×';
      del.setAttribute('aria-label', uiText('Borrar'));
      del.title = uiText('Borrar');
      del.onclick = event => {
        event.stopPropagation();
        savePrompts(loadPrompts().filter(p => p.id !== item.id));
        renderPromptLibrary();
      };
      row.append(main, del);
      promptList.append(row);
    }
  }
  function openPromptLibrary() {
    promptDlg.querySelector('#promptLibTitle').textContent = uiText('Biblioteca de prompts');
    promptDlg.setAttribute('aria-label', uiText('Biblioteca de prompts'));
    promptDlg.querySelector('#promptLibClose').setAttribute('aria-label', uiText('Cerrar'));
    promptSearch.placeholder = uiText('Buscar plantillas…');
    promptSearch.setAttribute('aria-label', uiText('Buscar plantillas…'));
    const draft = $('#input')?.value.trim() || '';
    promptDlg.querySelector('#promptLibNew').textContent = uiText(draft ? 'Guardar texto actual' : '+ Nueva plantilla');
    promptDlg.querySelector('#promptFormTitle').placeholder = uiText('Nombre de la plantilla');
    promptDlg.querySelector('#promptFormText').placeholder = uiText('Texto del prompt…');
    promptDlg.querySelector('#promptFormCancel').textContent = uiText('Cancelar');
    promptDlg.querySelector('#promptFormSave').textContent = uiText('Guardar');
    promptForm.hidden = true;
    promptSearch.value = '';
    renderPromptLibrary();
    showSheet(promptDlg);
    promptSearch.focus();
  }
  window.openPromptLibrary = openPromptLibrary;
  promptDlg.querySelector('#promptLibClose').onclick = () => hideSheet(promptDlg);
  promptSearch.addEventListener('input', renderPromptLibrary);
  promptDlg.querySelector('#promptLibNew').onclick = () => {
    promptForm.hidden = !promptForm.hidden;
    if (!promptForm.hidden) {
      promptDlg.querySelector('#promptFormTitle').value = '';
      promptDlg.querySelector('#promptFormText').value = $('#input')?.value.trim() || '';
      promptDlg.querySelector('#promptFormTitle').focus();
    }
  };
  promptDlg.querySelector('#promptFormCancel').onclick = () => { promptForm.hidden = true; };
  promptForm.onsubmit = event => {
    event.preventDefault();
    const title = promptDlg.querySelector('#promptFormTitle').value.trim();
    const text = promptDlg.querySelector('#promptFormText').value.trim();
    if (!title || !text) return;
    const list = loadPrompts();
    list.unshift({ id: 'p-' + Date.now().toString(36), title, text });
    savePrompts(list);
    promptForm.hidden = true;
    renderPromptLibrary();
  };

  // 4. Local Usage Telemetry in Settings (matching V-Agent's instrument/telemetry aesthetic)
  function computeLocalUsageStats(conversations) {
    let chats = 0, pinned = 0, archived = 0, userMsgs = 0, assistantMsgs = 0, generatedTokens = 0, decodeSum = 0, decodeCount = 0;
    const byModel = new Map();
    for (const chat of (conversations || [])) {
      chats++;
      if (chat.pinned) pinned++;
      if (chat.archived) archived++;
      for (const msg of (chat.messages || [])) {
        if (msg.role === 'user') userMsgs++;
        else if (msg.role === 'assistant') {
          assistantMsgs++;
          const gen = Number(msg.performance?.detail?.generated ?? msg.usage?.completion_tokens ?? 0);
          if (Number.isFinite(gen) && gen > 0) generatedTokens += gen;
          const dec = Number(msg.performance?.decode);
          if (Number.isFinite(dec) && dec > 0 && dec < 1e6) { decodeSum += dec; decodeCount++; }
          const mName = msg.model_name || (msg.model && (modelNames[msg.model] || msg.model)) || '';
          if (mName) byModel.set(mName, (byModel.get(mName) || 0) + 1);
        }
      }
    }
    const topModels = [...byModel.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    return { chats, pinned, archived, userMsgs, assistantMsgs, generatedTokens, avgDecode: decodeCount ? decodeSum / decodeCount : null, topModels };
  }
  window.computeLocalUsageStats = computeLocalUsageStats;

  const drawerBody = $('#drawer .drawer-body'), nav = $('#settingsNav');
  if (drawerBody && nav) {
    const usagePage = document.createElement('section');
    usagePage.id = 'settings-usage';
    usagePage.className = 'settings-page';
    usagePage.setAttribute('role', 'tabpanel');
    usagePage.setAttribute('aria-labelledby', 'nav-usage');
    usagePage.hidden = true;
    usagePage.innerHTML = '<h3></h3><p class="mini" id="usageSubtitle"></p><div id="usageCards" class="usage-strip"></div><div id="usageModels" class="usage-models"></div>';
    drawerBody.append(usagePage);

    const navBtn = document.createElement('button');
    navBtn.type = 'button';
    navBtn.id = 'nav-usage';
    navBtn.dataset.category = 'usage';
    navBtn.dataset.keywords = 'Uso Estadísticas stats usage tokens models modelos actividad';
    navBtn.setAttribute('role', 'tab');
    navBtn.setAttribute('aria-controls', 'settings-usage');
    navBtn.textContent = uiText('Uso');
    navBtn.onclick = () => selectSettingsCategory('usage');
    const histBtn = nav.querySelector('#nav-history');
    if (histBtn) nav.insertBefore(navBtn, histBtn); else nav.append(navBtn);

    function renderUsageStats() {
      const s = computeLocalUsageStats(convs);
      const locale = window.VALI18n?.locale || 'es-ES';
      const fmt = n => Math.round(n).toLocaleString(locale);
      usagePage.querySelector('h3').textContent = uiText('Estadísticas de uso');
      usagePage.querySelector('#usageSubtitle').textContent = uiText('Calculadas solo en este equipo a partir de tu historial guardado. Nunca se envían fuera.');
      const strip = usagePage.querySelector('#usageCards');
      const items = [
        [uiText('Conversaciones'), fmt(s.chats), s.pinned ? fmt(s.pinned) + ' ' + uiText('fijadas') : ''],
        [uiText('Mensajes enviados'), fmt(s.userMsgs), s.assistantMsgs ? fmt(s.assistantMsgs) + ' ' + uiText('respuestas') : ''],
        [uiText('Tokens generados'), s.generatedTokens ? fmt(s.generatedTokens) : '—', uiText('solo cifras reales')],
        [uiText('Velocidad media'), s.avgDecode ? s.avgDecode.toLocaleString(locale, { maximumFractionDigits: 1 }) + ' tok/s' : '—', uiText('generación')],
      ];
      strip.replaceChildren(...items.map(([label, val, sub]) => {
        const cell = document.createElement('div');
        cell.className = 'usage-card';
        cell.innerHTML = '<span class="usage-label"></span><strong class="usage-value"></strong><small class="usage-sub"></small>';
        cell.querySelector('.usage-label').textContent = label;
        cell.querySelector('.usage-value').textContent = val;
        cell.querySelector('.usage-sub').textContent = sub;
        return cell;
      }));
      const modelsBox = usagePage.querySelector('#usageModels');
      modelsBox.replaceChildren();
      if (s.topModels.length) {
        const h4 = document.createElement('h4');
        h4.textContent = uiText('Modelos más usados');
        modelsBox.append(h4);
        const max = s.topModels[0][1] || 1;
        for (const [name, count] of s.topModels) {
          const row = document.createElement('div');
          row.className = 'usage-bar-row';
          row.innerHTML = '<div class="usage-bar-head"><span class="usage-bar-name"></span><span class="usage-bar-count"></span></div><div class="usage-bar-track"><div class="usage-bar-fill"></div></div>';
          row.querySelector('.usage-bar-name').textContent = name;
          row.querySelector('.usage-bar-count').textContent = fmt(count);
          row.querySelector('.usage-bar-fill').style.width = Math.max(4, Math.round(100 * count / max)) + '%';
          modelsBox.append(row);
        }
      }
    }
    window.renderUsageStats = renderUsageStats;
    document.getElementById('drawer')?.addEventListener('fw:open', renderUsageStats);
    navBtn.addEventListener('click', renderUsageStats);
  }

  // 5. Keyboard Shortcuts — non-modal corner reference card (Ctrl+/)
  const shortcutsDlg = document.createElement('div');
  shortcutsDlg.id = 'shortcutsDialog';
  shortcutsDlg.className = 'val-sheet val-shortcuts-sheet';
  shortcutsDlg.setAttribute('popover', 'manual');
  shortcutsDlg.setAttribute('role', 'dialog');
  shortcutsDlg.innerHTML = '<div class="fw-head"><h2 id="shortcutsTitle"></h2><button id="shortcutsClose" class="icon-btn" type="button">×</button></div><div id="shortcutsBody" class="shortcuts-body"></div>';
  document.body.append(shortcutsDlg);
  function openShortcutsDialog() {
    shortcutsDlg.querySelector('#shortcutsTitle').textContent = uiText('Atajos de teclado');
    shortcutsDlg.setAttribute('aria-label', uiText('Atajos de teclado'));
    shortcutsDlg.querySelector('#shortcutsClose').setAttribute('aria-label', uiText('Cerrar'));
    const rows = [
      ['Ctrl + K', 'Paleta de comandos'],
      ['Ctrl + F', 'Buscar en la conversación'],
      ['Enter', 'Enviar mensaje (o encolar durante una respuesta)'],
      ['Shift + Enter', 'Salto de línea'],
      ['Ctrl + Enter', 'Redirigir la respuesta en curso'],
      ['Alt + ↑ / ↓', 'Navegar entre turnos'],
      ['Ctrl + /', 'Ver atajos de teclado'],
      ['Escape', 'Cerrar ventana, menú o búsqueda'],
    ];
    const body = shortcutsDlg.querySelector('#shortcutsBody');
    body.replaceChildren(...rows.map(([keys, desc]) => {
      const row = document.createElement('div');
      row.className = 'shortcut-row';
      const label = document.createElement('span');
      label.textContent = uiText(desc);
      const kbd = document.createElement('kbd');
      kbd.textContent = keys;
      row.append(label, kbd);
      return row;
    }));
    showSheet(shortcutsDlg);
  }
  window.openShortcutsDialog = openShortcutsDialog;
  shortcutsDlg.querySelector('#shortcutsClose').onclick = () => hideSheet(shortcutsDlg);

  // 6. Inline "No model loaded" composer strip (non-blocking, native to V-Agent's composer)
  const composeInner = $('#composerBox .compose-inner');
  const modelStrip = document.createElement('div');
  modelStrip.id = 'modelPromptStrip';
  modelStrip.className = 'model-prompt-strip';
  modelStrip.hidden = true;
  modelStrip.setAttribute('role', 'status');
  modelStrip.innerHTML = '<span id="mpBody" class="mp-body"></span><div class="mp-actions"><button id="mpLoad" type="button" class="queued-action mp-primary"></button><button id="mpChoose" type="button" class="queued-action"></button><button id="mpDismiss" type="button" class="queued-remove">×</button></div>';
  const surface = composeInner?.querySelector('.compose-surface');
  if (composeInner && surface) composeInner.insertBefore(modelStrip, surface);

  function openModelPromptDialog() {
    const selectedId = $('#model')?.value;
    if (!selectedId) { setChatControls('model'); return; }
    const name = modelNames[selectedId] || selectedId;
    modelStrip.querySelector('#mpBody').textContent = uiText('Ningún modelo cargado') + ' · ' + name;
    modelStrip.querySelector('#mpLoad').textContent = uiText('Cargar modelo');
    modelStrip.querySelector('#mpChoose').textContent = uiText('Elegir otro modelo');
    modelStrip.querySelector('#mpDismiss').setAttribute('aria-label', uiText('Cerrar'));
    modelStrip.hidden = false;
    modelStrip.querySelector('#mpLoad').focus();
  }
  modelStrip.querySelector('#mpLoad').onclick = () => { modelStrip.hidden = true; loadModel(); };
  modelStrip.querySelector('#mpChoose').onclick = () => { modelStrip.hidden = true; setChatControls('model'); };
  modelStrip.querySelector('#mpDismiss').onclick = () => { modelStrip.hidden = true; $('#input')?.focus(); };
  window.openModelPromptDialog = openModelPromptDialog;
  window.hideModelPromptStrip = () => { modelStrip.hidden = true; };

  // Dismiss any open non-modal sheet on outside click or Escape
  document.addEventListener('pointerdown', event => {
    if (event.target.closest?.('.val-sheet, #openCommandPalette, #openPromptLibrary')) return;
    for (const open of document.querySelectorAll('.val-sheet:popover-open')) hideSheet(open);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      const open = [...document.querySelectorAll('.val-sheet:popover-open')];
      if (open.length) { event.preventDefault(); open.forEach(hideSheet); }
      else if (!modelStrip.hidden) { event.preventDefault(); modelStrip.hidden = true; }
    }
  });

  // Topbar triggers & global shortcuts
  const openPaletteBtn = $('#openCommandPalette');
  if (openPaletteBtn) openPaletteBtn.onclick = () => isSheetOpen(palette) ? closeCommandPalette() : openCommandPalette();
  const openPromptsBtn = $('#openPromptLibrary');
  if (openPromptsBtn) openPromptsBtn.onclick = () => isSheetOpen(promptDlg) ? hideSheet(promptDlg) : openPromptLibrary();

  document.addEventListener('keydown', event => {
    const mod = event.ctrlKey || event.metaKey;
    if (!mod || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key === 'k') { event.preventDefault(); isSheetOpen(palette) ? closeCommandPalette() : openCommandPalette(); }
    else if (key === 'f' && !event.shiftKey && messages.length > 0 && !document.querySelector('dialog[open]')) { event.preventDefault(); openChatFind(); }
    else if (event.key === '/' && !event.shiftKey) { event.preventDefault(); isSheetOpen(shortcutsDlg) ? hideSheet(shortcutsDlg) : openShortcutsDialog(); }
  });
}
setupPolishUI();
