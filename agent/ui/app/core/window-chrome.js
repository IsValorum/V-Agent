function applyDecoration(d={}){window.VALPalette.apply(d);}
function setupDecoration(){window.VALPalette.setup();}

function setupMarket(){
  const page=document.getElementById('settings-market');
  page.innerHTML+='<p class="mini">Catálogos públicos · actualización diaria. Tú eliges qué añadir y activar.</p><div class="market-toolbar"><input id="marketSearch" type="search" placeholder="Buscar plugins y MCPs…"><select id="marketSource"><option value="">Todos</option><option value="mcp">MCP Registry</option><option value="claude">Claude oficial</option></select><button id="marketFind" type="button">Buscar</button><button id="marketRefresh" type="button">Actualizar</button></div><p id="marketStatus" class="mini" role="status"></p><details class="settings-group"><summary>Añadir MCP personalizado / plugin MCP</summary><p class="mini">Pega su configuración mcpServers. Se guarda desactivado. Transportes: stdio y Streamable HTTP. Los MCPs externos requieren Acceso completo; no están aislados por V-Agent.</p><textarea id="customMCPJson" rows="7" spellcheck="false" aria-label="Configuración MCP" placeholder="mcpServers JSON"></textarea><button id="addCustomMCP" type="button">Añadir</button></details><h4>Mis MCPs</h4><div id="installedMCPs"></div><h4>Catálogo</h4><div id="marketItems"></div>';
  let items=[];
  const status=text=>document.getElementById('marketStatus').textContent=text;
  async function action(body){return requestJSON('/api/harness/market',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
  function paint(){const query=document.getElementById('marketSearch').value.toLowerCase(),source=document.getElementById('marketSource').value,box=document.getElementById('marketItems');box.replaceChildren();const matches=items.filter(i=>(!source||source===i.source)&&(i.name+' '+i.description).toLowerCase().includes(query));for(const item of matches.slice(0,100)){const row=document.createElement('article');row.className='market-item';const name=document.createElement('strong');name.textContent=item.name;const description=document.createElement('p');description.className='mini';description.textContent=item.description;const type=document.createElement('small');type.textContent=item.source+' · '+item.compatibility;const button=document.createElement('button');button.type='button';button.textContent=uiText('Revisar configuración');button.onclick=async()=>{button.disabled=true;try{const result=await action({action:'prepare',item:{name:item.name,source:item.source}});document.getElementById('customMCPJson').value=JSON.stringify(result.manifest,null,2);document.getElementById('customMCPJson').closest('details').open=true;document.getElementById('customMCPJson').scrollIntoView({block:'center',behavior:'smooth'});status(result.message);}catch(error){status(error.message);}finally{button.disabled=false;}};row.append(name,type,description,button);box.append(row);}if(!matches.length)box.textContent=uiText('Sin resultados en este catálogo.');}
  async function load(){try{const data=await requestJSON('/api/harness/market');items=data.catalog.items||[];status(data.catalog.busy?uiText('Actualizando catálogo…'):data.catalog.errors?.join(' · ')||items.length+' '+uiText('entradas')+' · '+new Date(data.catalog.checked_at*1000).toLocaleString(window.VALI18n?.locale||undefined));paint();const installed=document.getElementById('installedMCPs');installed.replaceChildren();for(const entry of data.installed){const row=document.createElement('label');row.className='market-installed';const input=document.createElement('input');input.type='checkbox';input.checked=entry.enabled;input.disabled=busy;const label=document.createElement('span');const health=data.health.servers?.find(s=>s.name===entry.name);label.textContent=entry.name+' · '+(entry.enabled?(health?.status||'iniciando'):uiText('Desactivado'))+' · '+entry.transport;input.onchange=async()=>{input.disabled=true;try{await action({action:'toggle',name:entry.name,enabled:input.checked});presupuestoFirmado='';consultarPresupuesto();await load();}catch(error){input.checked=entry.enabled;input.disabled=false;status(error.message);}};row.append(input,label);installed.append(row);}if(!data.installed.length)installed.textContent=uiText('Ningún MCP personalizado.');if(data.catalog.busy)setTimeout(load,2000);}catch(error){status(error.message);}}
  document.getElementById('marketFind').onclick=async()=>{const button=document.getElementById('marketFind');button.disabled=true;try{const data=await action({action:'search',query:document.getElementById('marketSearch').value});items=[...items.filter(i=>i.source!=='mcp'),...data.items];paint();status(data.items.length+' '+uiText('MCPs encontrados en el registro.'));}catch(error){status(error.message);}finally{button.disabled=false;}};
  document.getElementById('marketSearch').onkeydown=e=>{if(e.key==='Enter')document.getElementById('marketFind').click();};
  document.getElementById('marketSearch').oninput=paint;document.getElementById('marketSource').onchange=paint;
  document.getElementById('marketRefresh').onclick=async()=>{const btn=document.getElementById('marketRefresh');btn.disabled=true;try{await action({action:'refresh'});await load();}catch(error){status(error.message);}finally{btn.disabled=false;}};
  document.getElementById('addCustomMCP').onclick=async()=>{const btn=document.getElementById('addCustomMCP');btn.disabled=true;try{await action({action:'register',manifest:JSON.parse(document.getElementById('customMCPJson').value)});await load();status(uiText('Añadido y desactivado. Actívalo cuando lo necesites.'));}catch(error){status(error.message);}finally{btn.disabled=false;}};
  const quick=document.createElement('button');quick.type='button';quick.className='configure-mcp-link';quick.textContent=uiText('Mercado de plugins y MCPs');quick.onclick=()=>{setDrawer(true);selectSettingsCategory('market');};document.getElementById('controls-tools').prepend(quick);
  load();setInterval(()=>{if(!document.hidden&&settingsCategory==='market')load();},60000);
}
function organizeExecutionSettings(){
  const profile=document.getElementById('agentProfile').closest('.agent-profile-row').parentElement;
  profile.id='executionSettings';profile.classList.add('execution-settings');
  const title=document.createElement('h3');title.textContent='Agente y permisos';profile.prepend(title);
  profile.append(document.getElementById('pcAccess').closest('.row'),document.getElementById('sandboxPath'),document.getElementById('openSandbox'),document.getElementById('accessStatus'));
  const limits=document.createElement('details');limits.className='settings-group';limits.id='executionLimits';limits.innerHTML='<summary>Límites de ejecución</summary>';limits.append(document.getElementById('p_rounds').closest('.row'));profile.append(limits);
}

/* Appearance work is deduplicated and runs only when appearance or the viewport changes. */
function syncDesktopChrome(p,mode){
  if(!window.__TAURI__?.core?.invoke)return;
  const args={dark:mode!=='day',background:p.panel,radius:Math.max(2,p.radius)};
  const signature=JSON.stringify(args);if(syncDesktopChrome.signature===signature)return;
  clearTimeout(syncDesktopChrome.timer);syncDesktopChrome.signature=signature;syncDesktopChrome.timer=setTimeout(()=>{
    window.__TAURI__.core.invoke('window_appearance',args).catch(error=>{if(syncDesktopChrome.signature===signature)syncDesktopChrome.signature='';console.warn('Window appearance:',error);});
  },70);
}
function syncApplicationIcon(logo){
  if(!window.__TAURI__?.core?.invoke||syncApplicationIcon.selected===logo)return;
  syncApplicationIcon.selected=logo;
  window.__TAURI__.core.invoke('window_brand_icon',{logo}).then(()=>{const status=document.getElementById('decoIconStatus');if(status)status.textContent='';}).catch(error=>{if(syncApplicationIcon.selected===logo)syncApplicationIcon.selected='';const status=document.getElementById('decoIconStatus');if(status){status.textContent=uiText('No se pudo actualizar el icono de Windows. Vuelve a elegirlo.');status.title=String(error);}console.warn('Application icon:',error);});
}

// Desktop window frame: the native Windows title bar left an empty band above the sidebar. In the
// desktop app the frame is drawn here instead: drag from the header, double-click to maximize, and
// minimize / maximize / close buttons that follow the palette. Browsers never see any of this.
function setupWindowFrame(){
  const api=window.__TAURI__?.window;if(!api?.getCurrentWindow||document.getElementById('windowControls'))return;
  const win=api.getCurrentWindow();document.body.classList.add('desktop-frame');
  for(const element of document.querySelectorAll('.topbar,.topbar .breadcrumb,.topbar .breadcrumb span,.topbar .spacer,#sidebar .sidebar-chrome,#sidebar .chrome-status'))element.setAttribute('data-tauri-drag-region','');
  const icons={minimize:'<path d="M6 12h12"/>',maximize:'<rect x="6" y="6" width="12" height="12" rx="1.5"/>',restore:'<rect x="8" y="5" width="11" height="11" rx="1.5"/><path d="M5 9v8.5A1.5 1.5 0 0 0 6.5 19H15"/>',close:'<path d="m7 7 10 10M17 7 7 17"/>'};
  const bar=document.createElement('div');bar.id='windowControls';bar.setAttribute('data-tauri-drag-region','');bar.setAttribute('role','group');bar.setAttribute('aria-label',uiText('Ventana'));
  const make=(id,label,run)=>{const button=document.createElement('button');button.type='button';button.className='window-control';button.dataset.control=id;button.setAttribute('aria-label',uiText(label));button.title=uiText(label);button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true">'+icons[id]+'</svg>';button.onclick=()=>run().catch(error=>console.warn('Window control:',error));bar.append(button);return button;};
  make('minimize','Minimizar',()=>win.minimize());
  const maximize=make('maximize','Maximizar',()=>win.toggleMaximize());
  make('close','Cerrar',()=>win.close());
  document.body.append(bar);
  const sync=async()=>{try{const max=await win.isMaximized();maximize.querySelector('svg').innerHTML=max?icons.restore:icons.maximize;const label=uiText(max?'Restaurar':'Maximizar');maximize.setAttribute('aria-label',label);maximize.title=label;document.body.classList.toggle('window-maximized',max);}catch{}};
  sync();win.onResized?.(()=>sync());
}
setupWindowFrame();

// Segmented controls (pick one of a few): a pill slides to the chosen option, iOS style. One helper
// for every group so they all look and move the same; it follows aria-pressed / aria-selected.
function setupSegmentedSliders(){
  const groups='#agentModeSegments,.model-source-tabs,.section-tabs,.load-mode,.mode-toggle';
  const place=group=>{
    const pill=group.querySelector(':scope>.seg-pill');if(!pill)return;
    const active=[...group.children].find(el=>el.tagName==='BUTTON'&&(el.getAttribute('aria-pressed')==='true'||el.getAttribute('aria-selected')==='true'));
    if(!active||!active.offsetWidth){pill.style.opacity='0';return;}
    pill.style.opacity='1';pill.style.width=active.offsetWidth+'px';pill.style.height=active.offsetHeight+'px';
    pill.style.transform='translate('+active.offsetLeft+'px,'+active.offsetTop+'px)';
  };
  const attach=group=>{
    if(group.dataset.segmented)return;group.dataset.segmented='1';
    const pill=document.createElement('span');pill.className='seg-pill';pill.setAttribute('aria-hidden','true');group.prepend(pill);
    new MutationObserver(()=>place(group)).observe(group,{subtree:true,attributes:true,attributeFilter:['aria-pressed','aria-selected']});
    if(window.ResizeObserver)new ResizeObserver(()=>place(group)).observe(group);
    // First placement without a slide from the left edge.
    pill.classList.add('seg-instant');place(group);requestAnimationFrame(()=>requestAnimationFrame(()=>pill.classList.remove('seg-instant')));
  };
  const syncAll=()=>{for(const group of document.querySelectorAll('[data-segmented]'))if(group.offsetWidth)place(group);};
  const scan=()=>{document.querySelectorAll(groups).forEach(attach);syncAll();};
  scan();
  // Groups made after this first scan (the agent mode selector is built once the core answers) attach
  // themselves through this; without it their pill only appeared after some window opened.
  window.VALSegmented={scan};
  // The web font changes every button's width once it loads: place the pills again then.
  document.fonts?.ready?.then(()=>requestAnimationFrame(syncAll));
  // Event-driven refresh when windows/sections open or the viewport changes (no global MutationObserver or polling timer).
  document.addEventListener('fw:open',()=>requestAnimationFrame(scan),true);
  document.addEventListener('toggle',()=>requestAnimationFrame(syncAll),true);
  window.addEventListener('resize',()=>requestAnimationFrame(syncAll));
}
setupSegmentedSliders();
// Screen-reader names of the page regions (sidebar, chat, composer): set here because the chat region is
// deliberately not observed by the translator (its content is the conversation).
function translateRegionLabels(){for(const el of document.querySelectorAll('[data-ui-aria]'))el.setAttribute('aria-label',uiText(el.dataset.uiAria));}
