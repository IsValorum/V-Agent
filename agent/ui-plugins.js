/* Local plugin bundles: instructions and commands. MCP servers stay in Mercado. */
let pluginItems = [], pluginRootPath = '', pluginBusy = false, pluginLoading = false;
const PLUGIN_EXAMPLE = {
  name: 'Mi plugin',
  version: '1.0.0',
  description: 'Instrucciones y comandos para este agente.',
  instructions: 'Cuando la tarea lo requiera, sigue estas instrucciones del plugin.',
  commands: [
    { name: 'Revisar', prompt: 'Revisa el cambio actual y señala riesgos concretos antes de responder.' }
  ]
};

function pluginIcon(kind) {
  if (kind === 'market') return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h16l-1 11H5L4 9Zm2 0V6a6 6 0 0 1 12 0v3"/><path d="M9 13h6"/></svg>';
  return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4h6v3a2 2 0 1 0 3 2v2h-3a2 2 0 1 0-2 3H9v-3a2 2 0 1 0-2-2V7h3a2 2 0 1 0 2-3Z"/><path d="M5 16h14v4H5z"/></svg>';
}

function setupPluginManager() {
  const convs = document.getElementById('convs');
  if (convs && !document.getElementById('sidebarExtras')) {
    const extras = document.createElement('section');
    extras.id = 'sidebarExtras';
    extras.className = 'sidebar-extras';
    // One entry instead of two: the Market and Plugins pages sit next to each other in Settings.
    extras.innerHTML = '<button id="sidebarMarket" type="button" class="sidebar-extra" title="Mercado y plugins">' + pluginIcon('plugin') +
      '<span class="extra-text"><strong>Extensiones</strong></span><span id="sidebarPluginBadge" class="extra-count" title="Plugins activos">0</span></button>';
    const conversationsHead = document.querySelector('#sidebar > .side-head');
    if (conversationsHead) conversationsHead.before(extras); else convs.before(extras);
    document.getElementById('sidebarMarket').onclick = () => openPluginPage('market');
  }
  const page = document.getElementById('settings-plugins');
  if (page && page.dataset.ready !== '1') {
    page.dataset.ready = '1';
    page.innerHTML = '<h3>Plugins</h3>' +
      '<p class="mini">Plugins locales de instrucciones y comandos. Los servidores MCP se gestionan desde Mercado.</p>' +
      '<div class="plugin-toolbar"><button id="pluginInstallFolder" type="button">Instalar desde carpeta</button>' +
      '<button id="pluginRefresh" type="button">Actualizar</button></div>' +
      '<details class="settings-group" id="pluginJsonBox"><summary>Instalar desde JSON</summary><div class="group-body">' +
      '<textarea id="pluginManifest" rows="9" spellcheck="false" aria-label="Manifiesto del plugin"></textarea>' +
      '<div class="plugin-json-actions"><button id="pluginTemplate" type="button" class="text-btn">Usar ejemplo</button>' +
      '<button id="pluginInstallJson" type="button">Instalar</button></div>' +
      '<p class="mini">plugin.json admite name, version, description, instructions o instructions_file y commands. Las instrucciones se añaden al agente; el plugin no ejecuta JavaScript.</p></div></details>' +
      '<p id="pluginStatus" class="mini" role="status"></p><div id="pluginList"></div><p id="pluginRoot" class="mini"></p>';
    document.getElementById('pluginRefresh').onclick = () => pluginLoad();
    document.getElementById('pluginInstallFolder').onclick = () => pluginInstallFolder();
    document.getElementById('pluginInstallJson').onclick = () => pluginInstallJson();
    document.getElementById('pluginTemplate').onclick = () => {
      document.getElementById('pluginManifest').value = JSON.stringify(PLUGIN_EXAMPLE, null, 2);
      document.getElementById('pluginJsonBox').open = true;
    };
    pluginLoad();
  }
}

function openPluginPage(category) {
  if (typeof setDrawer === 'function') setDrawer(true);
  if (typeof selectSettingsCategory === 'function') selectSettingsCategory(category);
  if (category === 'plugins') pluginLoad();
}

function pluginSetStatus(message, error) {
  const node = document.getElementById('pluginStatus');
  if (node) {
    node.textContent = message || '';
    node.dataset.error = error ? '1' : '';
  }
}

function pluginSetBusy(value) {
  pluginBusy = Boolean(value);
  for (const id of ['pluginInstallFolder', 'pluginInstallJson', 'pluginRefresh']) {
    const button = document.getElementById(id);
    if (button) button.disabled = pluginBusy;
  }
}

async function pluginAction(body) {
  return requestJSON('/api/harness/plugins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

async function pluginLoad() {
  if (pluginLoading) return;
  pluginLoading = true;
  pluginSetBusy(true);
  try {
    const data = await requestJSON('/api/harness/plugins', { cache: 'no-store' });
    pluginItems = Array.isArray(data.plugins) ? data.plugins : [];
    pluginRootPath = data.root || '';
    pluginRender();
    pluginSetStatus('');
  } catch (error) {
    pluginSetStatus(error.message, true);
  } finally {
    pluginLoading = false;
    pluginSetBusy(false);
  }
}

function pluginRender() {
  const list = document.getElementById('pluginList');
  if (!list) return;
  list.replaceChildren();
  const badge = document.getElementById('sidebarPluginBadge');
  if (badge) badge.textContent = String(pluginItems.filter(item => item.enabled).length);
  if (!pluginItems.length) {
    const empty = document.createElement('p');
    empty.className = 'mini plugin-empty';
    empty.textContent = uiText('No hay plugins instalados.');
    list.append(empty);
  }
  for (const item of pluginItems) {
    const card = document.createElement('article');
    card.className = 'plugin-card';
    card.dataset.plugin = item.id;
    const head = document.createElement('div');
    head.className = 'plugin-head';
    const title = document.createElement('strong');
    title.textContent = item.name;
    const version = document.createElement('small');
    version.className = 'plugin-version';
    version.textContent = 'v' + (item.version || '1.0');
    const toggle = document.createElement('label');
    toggle.className = 'chk plugin-toggle';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = Boolean(item.enabled);
    check.setAttribute('aria-label', uiText('Activar plugin') + ': ' + item.name);
    check.disabled = pluginBusy;
    check.onchange = async () => {
      check.disabled = true;
      try {
        await pluginAction({ action: 'toggle', id: item.id, enabled: check.checked });
        await pluginLoad();
      } catch (error) {
        check.checked = !check.checked;
        pluginSetStatus(error.message, true);
      } finally {
        check.disabled = pluginBusy;
      }
    };
    toggle.append(check, document.createTextNode(uiText('Activo')));
    head.append(title, version, toggle);
    const description = document.createElement('p');
    description.className = 'mini';
    description.textContent = item.description || uiText('Sin descripción.');
    const meta = document.createElement('div');
    meta.className = 'plugin-meta';
    const size = item.instruction_chars ? (item.instruction_chars / 1024).toFixed(1) + ' KB' : uiText('Sin instrucciones');
    meta.textContent = size + ' · ' + (item.commands ? item.commands.length : 0) + ' ' + uiText('comandos');
    card.append(head, description, meta);
    if (item.commands && item.commands.length) {
      const commands = document.createElement('div');
      commands.className = 'plugin-commands';
      for (const command of item.commands) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'plugin-command';
        button.textContent = command.name;
        button.setAttribute('aria-label', uiText('Usar comando') + ': ' + command.name);
        button.onclick = () => {
          const input = document.getElementById('input');
          if (!input) return;
          input.value = command.prompt;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          if (typeof setDrawer === 'function') setDrawer(false);
          input.focus();
        };
        commands.append(button);
      }
      card.append(commands);
    }
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'text-btn plugin-remove';
    remove.textContent = uiText('Quitar');
    remove.onclick = async () => {
      if (!await valConfirm({ title: '¿Quitar este plugin?', message: 'Podrás volver a instalarlo desde el Mercado.', confirm: 'Quitar' })) return;
      try {
        await pluginAction({ action: 'remove', id: item.id });
        await pluginLoad();
      } catch (error) {
        pluginSetStatus(error.message, true);
      }
    };
    card.append(remove);
    list.append(card);
  }
  const root = document.getElementById('pluginRoot');
  if (root) root.textContent = pluginRootPath ? uiText('Carpeta de plugins') + ': ' + pluginRootPath : '';
}

async function pluginInstallFolder() {
  if (pluginBusy) return;
  pluginSetBusy(true);
  try {
    const picked = await requestJSON('/api/models/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: 'plugin' }),
      signal: AbortSignal.timeout(310000)
    });
    if (!picked.path) return;
    await pluginAction({ action: 'install_path', path: picked.path });
    pluginSetStatus(uiText('Plugin instalado.'));
    await pluginLoad();
  } catch (error) {
    pluginSetStatus(error.message, true);
  } finally {
    pluginSetBusy(false);
  }
}

async function pluginInstallJson() {
  if (pluginBusy) return;
  let manifest;
  try {
    manifest = JSON.parse(document.getElementById('pluginManifest').value || '{}');
  } catch {
    pluginSetStatus(uiText('El JSON del plugin no es válido.'), true);
    return;
  }
  pluginSetBusy(true);
  try {
    await pluginAction({ action: 'install_manifest', manifest });
    document.getElementById('pluginManifest').value = '';
    document.getElementById('pluginJsonBox').open = false;
    pluginSetStatus(uiText('Plugin instalado.'));
    await pluginLoad();
  } catch (error) {
    pluginSetStatus(error.message, true);
  } finally {
    pluginSetBusy(false);
  }
}
