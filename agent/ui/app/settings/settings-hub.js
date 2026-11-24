/* Settings own application preferences; the side inspector owns per-model controls. */
let settingsCategory='general',lastHardwareState=null,uiPreferences={language:'es'};
function uiText(text){return window.VALI18n?.t(text)||text;}
// Core texts made of facts and phrases joined by " · " (GPU name, driver, a recommendation): each
// part is translated on its own; a number inside a phrase is kept ("…driver {n} or newer").
function uiParts(text){
  return String(text||'').split(' · ').map(part=>{
    const whole=uiText(part);if(whole!==part)return whole;
    const numbers=part.match(/\d+(?:[.,]\d+)?/g);if(!numbers)return part;
    const pattern=part.replace(/\d+(?:[.,]\d+)?/g,'{n}'),translated=uiText(pattern);
    if(translated===pattern)return part;let i=0;return translated.replace(/\{n\}/g,()=>numbers[i++]??'');
  }).join(' · ');
}
function uiNumber(value){return Number(value).toLocaleString(window.VALI18n?.locale||undefined);}
function setupSettingsHub(){
  const drawer=$('#drawer'),body=$('#drawer .drawer-body'),appearance=$('#settings-appearance');
  const layout=$('#settings-layout'),history=$('#settings-history');
  appearance.querySelector('[role=tablist]')?.remove();
  for(const panel of [$('#settings-look'),layout,history]){panel.hidden=false;panel.removeAttribute('role');panel.removeAttribute('aria-labelledby');}
  drawer.querySelector('h2').textContent='Configuración';
  const navigation=document.createElement('nav');navigation.className='settings-navigation';navigation.setAttribute('aria-label','Configuración');
  navigation.innerHTML='<input id="settingsSearch" type="search" placeholder="Buscar ajustes…" aria-label="Buscar ajustes…"><div id="settingsNav" role="tablist" aria-orientation="vertical"></div>';
  drawer.insertBefore(navigation,body);
  const general=document.createElement('section');general.id='settings-general';general.className='settings-page';
  general.innerHTML='<h3>General</h3><div class="setting-row"><label for="uiLanguage">Idioma de la interfaz</label><select id="uiLanguage" aria-label="Seleccionar idioma"><option value="es">Español</option><option value="en">English</option><option value="pt">Português</option><option value="fr">Français</option><option value="de">Deutsch</option><option value="ja">日本語</option><option value="zh">简体中文</option><option value="ko">한국어</option><option value="hi">हिन्दी</option><option value="id">Bahasa Indonesia</option><option value="vi">Tiếng Việt</option><option value="th">ไทย</option><option value="tr">Türkçe</option><option value="ar">العربية</option></select></div><p id="languageSaveState" class="mini" role="status">Guardado en este equipo</p><label class="chk"><input id="notifyOnDone" type="checkbox" checked> Avisar al terminar una respuesta en segundo plano</label><div class="setting-row"><span>Versión</span><span id="appBuild"></span></div><div class="settings-data settings-instructions" id="instructionsBox"><h4>Instrucciones permanentes (AGENTS.md)</h4><p class="mini">Se aplican a todos tus chats. Si un proyecto tiene su propio archivo AGENTS.md, también se carga automáticamente.</p><textarea id="globalInstructions" rows="4" placeholder="Por ejemplo: responde de forma concisa, usa Python 3.12…" aria-label="Instrucciones permanentes" data-ui-aria="Instrucciones permanentes"></textarea><div class="instructions-actions"><button id="saveGlobalInstructions" type="button">Guardar instrucciones</button><span id="instructionsSaveState" class="mini" role="status"></span></div><p id="projectInstructionsHint" class="mini" hidden></p></div><div class="settings-data"><h4>Datos locales</h4><code id="settingsDataPath"></code><button id="copyDataPath" type="button">Copiar ruta</button><a id="userGuide" href="/guide.html" target="_blank" rel="noopener">Guía de uso</a></div>';
  const notifyCheck=general.querySelector('#notifyOnDone');
  try{notifyCheck.checked=localStorage.getItem('valNotifyOnDone')!=='0';}catch{}
  notifyCheck.onchange=()=>{
    try{localStorage.setItem('valNotifyOnDone',notifyCheck.checked?'1':'0');}catch{}
    if(notifyCheck.checked&&typeof Notification==='function'&&Notification.permission==='default'){Notification.requestPermission().catch(()=>{});}
  };
  async function loadGlobalInstructions(){
    try{
      const q=currentId&&!temporaryChat?'?conversation_id='+encodeURIComponent(currentId):'';
      const data=await requestJSON('/api/harness/instructions'+q);
      const area=$('#globalInstructions'),hint=$('#projectInstructionsHint');
      if(area&&document.activeElement!==area)area.value=data.content||'';
      if(hint){hint.hidden=!data.project_active;if(data.project_active)hint.textContent=uiText('Proyecto activo con AGENTS.md')+': '+data.project_path;}
    }catch{}
  }
  window.loadGlobalInstructions=loadGlobalInstructions;
  general.querySelector('#saveGlobalInstructions').onclick=async()=>{
    const area=$('#globalInstructions'),state=$('#instructionsSaveState'),btn=$('#saveGlobalInstructions');
    if(!area||!btn)return;btn.disabled=true;if(state)state.textContent=uiText('Guardando…');
    try{
      await requestJSON('/api/harness/instructions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:area.value})});
      if(state)state.textContent=uiText('Guardado en este equipo');
    }catch(error){if(state)state.textContent=uiText(error?.message||'No se pudieron guardar las instrucciones.');}
    finally{btn.disabled=false;}
  };
  document.getElementById('drawer')?.addEventListener('fw:open',()=>loadGlobalInstructions());
  const guideLink=document.getElementById('userGuide');if(guideLink)guideLink.onclick=event=>{const invoke=window.__TAURI__?.core?.invoke;if(!invoke)return;event.preventDefault();invoke('open_guide').catch(()=>window.open('/guide.html','_blank','noopener'));};
  const uninstall=document.createElement('div');uninstall.className='settings-data';uninstall.innerHTML='<h4>Desinstalar V-Agent</h4><p class="mini">Se abrirá el desinstalador y se cerrará V-Agent. Puedes elegir si conservar tus datos.</p><button id="openUninstaller" type="button">Abrir desinstalador</button>';general.append(uninstall);
  uninstall.querySelector('button').onclick=async()=>{try{if(busy||engineBusy||preparationState?.active){note('Detén la operación actual antes de desinstalar.');return;}const invoke=window.__TAURI__?.core?.invoke;if(!invoke){note('Disponible en la aplicación de escritorio.');return;}await flushSessionSaves();await invoke('open_uninstaller');await window.__TAURI__.window.getCurrentWindow().close();}catch(error){note(String(error));}};
  const chat=document.createElement('section');chat.id='settings-chat';chat.className='settings-page';chat.innerHTML='<h3>Cuadro de mensaje</h3>';chat.append(layout);
  const visualLayout=layout.querySelector('details');if(visualLayout){visualLayout.open=false;appearance.append(visualLayout);}
  const system=document.createElement('section');system.id='settings-system';system.className='settings-page';
  system.innerHTML='<h3>Sistema y motores</h3><div class="system-metrics"><div><span>CPU</span><strong id="systemCPU">—</strong><meter id="systemCPUMeter" min="0" max="100" value="0"></meter></div><div><span>Memoria</span><strong id="systemRAM">—</strong><meter id="systemRAMMeter" min="0" max="100" value="0"></meter></div><div><span>Memoria gráfica</span><strong id="systemVRAM">—</strong><meter id="systemVRAMMeter" min="0" max="100" value="0"></meter></div><div><span>Almacenamiento</span><strong id="systemDisk">—</strong><meter id="systemDiskMeter" min="0" max="100" value="0"></meter></div></div><div id="settingsEngineHost"><button id="openModelSettings" type="button">Modelo y motor</button></div>';
  const tools=document.createElement('section');tools.id='settings-tools';tools.className='settings-page';tools.innerHTML='<h3>Tools</h3><p class="mini">Ajusta cómo funcionan las herramientas y sus conexiones MCP. Para activarlas en un chat y elegir permisos, usa la ventana de Tools.</p><button id="openToolsWindow" type="button">Abrir ventana de Tools</button><div id="settingsToolsHost"></div>';
  const historyPage=document.createElement('section');historyPage.id='settings-history-page';historyPage.className='settings-page';historyPage.innerHTML='<h3>Historial</h3>';historyPage.append(history);
  const market=document.createElement('section');market.id='settings-market';market.className='settings-page';market.innerHTML='<h3>Mercado</h3>';
  const pluginsPage=document.createElement('section');pluginsPage.id='settings-plugins';pluginsPage.className='settings-page';pluginsPage.innerHTML='<h3>Plugins</h3>';
  const pages={general,appearance,system,chat,tools,market,plugins:pluginsPage,history:historyPage};
  appearance.classList.add('settings-page');appearance.insertAdjacentHTML('afterbegin','<h3>Apariencia</h3><div class="animation-setting"><div class="setting-row"><label for="animationSpeed">Velocidad de animación</label><output id="animationSpeedValue" for="animationSpeed">620 ms</output></div><input id="animationSpeed" type="range" min="100" max="1600" step="20" value="620"><div class="animation-endpoints mini"><span>Rápidas</span><span>Pausadas</span></div><label class="chk"><input type="checkbox" id="windowAnimations" checked> Animar apertura y cierre de ventanas flotantes</label><p class="mini">La velocidad de arriba también se usa en las ventanas flotantes.</p><p id="animationSaveState" class="mini" role="status"></p></div>');
  // Export / import / reset act on the whole look, so they close the page instead of splitting groups.
  for(const element of appearance.querySelectorAll('.theme-actions,.theme-save-line'))appearance.append(element);
  body.replaceChildren(...Object.values(pages));
  // Ordered by how often people need them; names match the buttons they configure.
  const entries=[['general','General','idioma language langue Sprache dados data datos AGENTS.md memoria memory instrucciones instructions notificaciones notifications avisos'],['appearance','Apariencia','colores colors cores couleurs Farben blur theme logo'],['chat','Cuadro de mensaje','layout font fuente letra botones buttons chat composer'],['tools','Tools','tools herramientas MCP Internet buscar arquivos files search'],['market','Mercado','plugins MCP marketplace extensions extensiones'],['plugins','Plugins','plugins extensiones comandos instructions commands'],['system','Sistema y motores','CPU RAM VRAM Strata llama.cpp API engine motor memory storage hardware actualizaciones updates'],['history','Historial','export import conversations chats historial histórico']];
  for(const [id,label,keywords] of entries){
    const button=document.createElement('button');button.type='button';button.id='nav-'+id;button.dataset.category=id;button.dataset.keywords=label+' '+keywords;button.setAttribute('role','tab');button.setAttribute('aria-controls',pages[id].id);button.textContent=label;
    pages[id].setAttribute('role','tabpanel');pages[id].setAttribute('aria-labelledby',button.id);
    button.onclick=()=>selectSettingsCategory(id);$('#settingsNav').append(button);
  }
  $('#settingsNav').addEventListener('keydown',event=>{if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...$('#settingsNav').children].filter(button=>!button.hidden),index=buttons.indexOf(document.activeElement),target=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;buttons[target]?.click();buttons[target]?.focus();});
  const searchNotice=document.createElement('p');searchNotice.id='settingsNoResults';searchNotice.className='mini';searchNotice.hidden=true;searchNotice.setAttribute('role','status');searchNotice.textContent='Sin resultados';navigation.append(searchNotice);
  $('#settingsSearch').oninput=()=>{
    const query=$('#settingsSearch').value.trim().toLocaleLowerCase();const matches=[];
    for(const button of $('#settingsNav').children){if(button.dataset.sidebarOnly)continue;const page=$('#'+button.getAttribute('aria-controls'));const haystack=button.textContent+' '+button.dataset.keywords+' '+page.textContent;button.hidden=!haystack.toLocaleLowerCase().includes(query);if(!button.hidden)matches.push(button);}
    searchNotice.hidden=matches.length>0;
    if(matches.length&&!matches.some(button=>button.dataset.category===settingsCategory))selectSettingsCategory(matches[0].dataset.category);
  };
  $('#openModelSettings').onclick=()=>setChatControls('model');
  const engineOptions=document.createElement('details');engineOptions.id='modelEngineOptions';engineOptions.className='settings-group';engineOptions.innerHTML='<summary>Motor y conexión</summary>';engineOptions.append($('#engineSettings'));
  const quick=document.createElement('div');quick.className='engine-quick';quick.innerHTML='<span class="engine-quick-label">Motor</span><span id="engineQuickName"></span><button id="engineQuickSettings" type="button"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7h11l-3-3M17 17H6l3 3"/></svg><span>Cambiar motor</span></button>';
  const mayaAdvanced=document.createElement('button');
  mayaAdvanced.id='mayaQuickAdvanced';mayaAdvanced.type='button';mayaAdvanced.hidden=true;
  mayaAdvanced.className='soft-btn';
  mayaAdvanced.textContent='Ajustes avanzados';
  mayaAdvanced.setAttribute('aria-controls','mayaEngineAdvanced');
  mayaAdvanced.setAttribute('aria-expanded','false');
  quick.append(mayaAdvanced);
  const mayaDetails=engineOptions.querySelector('#mayaEngineAdvanced');
  const syncMayaShortcut=()=>mayaAdvanced.setAttribute('aria-expanded',String(engineOptions.open&&!mayaDetails.hidden));
  engineOptions.addEventListener('toggle',syncMayaShortcut);
  mayaAdvanced.onclick=()=>{
    // llama.cpp, Strata and Strata Rust: their engine options, in the same place as Maya's settings.
    if(activeEngine!=='maya'&&typeof toggleEngineOptions==='function'){toggleEngineOptions();return;}
    const open=!(engineOptions.open&&!mayaDetails.hidden);
    if(open){
      if($('#engineKind').value!=='maya'){$('#engineKind').value='maya';$('#engineKind').onchange();}
      engineOptions.open=true;
    }
    mayaDetails.hidden=!open;
    syncMayaShortcut();
    if(open){mayaDetails.scrollIntoView({block:'nearest'});mayaDetails.querySelector('input').focus({preventScroll:true});}
  };
  const powerHome=document.createElement('div');powerHome.id='modelPowerHome';powerHome.append(engineOptions.querySelector('#engineToggle').closest('.power-row'));
  const sourceTabs=engineOptions.querySelector('#modelSourceTabs');
  $('#controls-model').prepend(sourceTabs,quick,engineOptions,powerHome);$('#engineQuickSettings').onclick=()=>{engineOptions.open=!engineOptions.open;if(engineOptions.open){engineOptions.scrollIntoView({block:'nearest'});$('#engineKind').focus({preventScroll:true});}};
  const remoteInfo=$('#remoteModelInfo');if(remoteInfo)$('#controls-model .model-top').after(remoteInfo);
  const advanced=document.createElement('section');advanced.id='loadAdvanced';advanced.className='load-advanced';advanced.innerHTML='<h4 class="block-title">Opciones avanzadas</h4>';
  $('#model-load-pane').append(advanced);for(const id of ['draftSettings','visionSettings','templateSettings'])advanced.append($('#'+id));
  $('#controls-response details').open=false;
  $('#controls-tools .tool-group:last-child').append($('#p_rounds').closest('.row'));
  $('#copyDataPath').onclick=async()=>{try{await navigator.clipboard.writeText($('#settingsDataPath').textContent);note(uiText('Copiado.'));}catch{note(uiText('No se pudo copiar la ruta.'));}};
  $('#uiLanguage').onchange=async()=>{
    const next=$('#uiLanguage').value,previous=uiPreferences.language;$('#uiLanguage').disabled=true;
    try{uiPreferences=await requestJSON('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({language:next})});window.VALI18n.setLanguage(next);$('#languageSaveState').textContent=uiText('Guardado en este equipo');}
    catch(error){$('#uiLanguage').value=previous;$('#languageSaveState').textContent=uiText('No se pudo guardar el idioma.');}
    finally{$('#uiLanguage').disabled=false;}
  };
  let motionSave=0,motionQueue=Promise.resolve();
  const windowAnimations=$('#windowAnimations');
  try{windowAnimations.checked=localStorage.getItem('valWindowAnimations')!=='0';}catch{}
  windowAnimations.onchange=()=>{window.VALWindows?.setWindowAnimations(windowAnimations.checked);};
  $('#animationSpeed').oninput=()=>{const value=Number($('#animationSpeed').value);window.VALMotion?.setDuration(value);$('#animationSpeedValue').textContent=value+' ms';};
  $('#animationSpeed').onchange=()=>{const sequence=++motionSave,value=Number($('#animationSpeed').value);motionQueue=motionQueue.then(async()=>{if(sequence!==motionSave)return;try{const saved=await requestJSON('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({animation_ms:value})});if(sequence!==motionSave)return;uiPreferences.animation_ms=saved.animation_ms;$('#animationSaveState').textContent=uiText('Guardado en este equipo');}catch(error){if(sequence===motionSave)$('#animationSaveState').textContent=uiText('No se pudieron guardar los ajustes.');}});};
  setupDecoration();setupMarket();
  const backgroundGroup=document.getElementById('t_gradient')?.closest('details');if(backgroundGroup)backgroundGroup.hidden=true;
  const workspaceRow=document.getElementById('workspaceName')?.closest('.row');if(workspaceRow)workspaceRow.hidden=true;
  window.setupMCPOptions?.();
  const configureMCPs=document.createElement('button');configureMCPs.id='configureMCPs';configureMCPs.type='button';configureMCPs.className='configure-mcp-link';configureMCPs.textContent='Configurar MCPs';
  configureMCPs.onclick=()=>{setDrawer(true);selectSettingsCategory('tools');const options=$('#mcpOptions');if(options){options.scrollIntoView({block:'start'});requestAnimationFrame(()=>options.querySelector('select,input,summary')?.focus({preventScroll:true}));}};
  $('#controls-tools').prepend(configureMCPs);
  $('#controls-tools').removeAttribute('data-controls-pane');$('#controls-tools').hidden=false;
  $('#toolsHost').append($('#controls-tools'));
  $('#openToolsWindow').onclick=()=>window.VALWindows?.open('tools');
  setupComposerMenu();setupAgentControls();setupAgentProfilesAndUpdates();organizeExecutionSettings();selectSettingsCategory('general');
}
function selectSettingsCategory(category){
  settingsCategory=category;
  for(const button of $('#settingsNav').children){const active=button.dataset.category===category;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;$('#'+button.getAttribute('aria-controls')).hidden=!active;}
  $('#drawer .drawer-body').scrollTop=0;
  if(lastHardwareState)renderSystemMetrics(lastHardwareState);
  window.VALI18n?.refresh();
}
function restoreInspectorContent(){
  $('#modelPowerHome')?.append($('#engineToggle').closest('.power-row'));
}
function syncSettingsSummary(){
  if(!$('#engineQuickName')||!engineSnapshot)return;
  $('#mayaQuickAdvanced').hidden=!['maya','llama','strata','rust'].includes(activeEngine);
  $('#mayaQuickAdvanced').setAttribute('aria-controls',activeEngine==='maya'?'mayaEngineAdvanced':'engineOptions');
  // The card follows the tab and the engine chosen in the form; until it is applied it says so, instead of
  // showing the engine still in use under the other tab.
  const chosen=$('#engineKind')?.value||activeEngine,kind=chosen,builds=engineSnapshot.builds||{},info=kind==='strata'?builds.strata:kind==='rust'?builds.rust:kind==='maya'?builds.maya:builds[$('#llamaVariant')?.value||engineSnapshot.llama?.variant||'cuda'];
  const apiName=activeEngine==='api'?(engineSnapshot.api?.name||'API'):($('#apiConnection')?.selectedOptions?.[0]?.value?$('#apiConnection').selectedOptions[0].textContent:uiText('API externa'));
  const name=kind==='api'?apiName:[kind==='strata'?'Strata':kind==='rust'?'Strata Rust':kind==='maya'?'Project Maya':'llama.cpp',info?.build||info?.version||uiText('sin instalar')].join(' · ');
  const pending=chosen!==activeEngine;
  $('#engineQuickName').textContent=name+(pending?' · '+uiText('Pendiente de aplicar.'):'');
  $('#engineQuickName').dataset.pending=String(pending);
  $('#appBuild').textContent='V-Agent '+(engineSnapshot.version||'');
  $('#settingsDataPath').textContent=engineSnapshot.data_dir||'';
}
function renderSystemMetrics(stats){
  if(!stats||!$('#systemCPU'))return;
  const cpu=stats.cpu||{},ram=stats.ram||{},gpu=stats.gpu||{},disk=stats.storage||{};
  function memory(id,used,total){const known=typeof used==='number'&&total>0;$('#'+id).textContent=known?used.toFixed(1)+' / '+total.toFixed(1)+' GiB':'—';$('#'+id+'Meter').value=known?Math.min(100,used/total*100):0;}
  $('#systemCPU').textContent=typeof cpu.percent==='number'?Math.round(cpu.percent)+' %':'—';$('#systemCPUMeter').value=cpu.percent||0;
  memory('systemRAM',ram.used_gib,ram.total_gib);memory('systemVRAM',typeof gpu.vram_mib==='number'?gpu.vram_mib/1024:null,gpu.vram_total_mib/1024);memory('systemDisk',disk.used_gib,disk.total_gib);
}
