/* Settings own application preferences; the side inspector owns per-model controls. */
let settingsCategory='general',lastHardwareState=null,uiPreferences={language:'es'};
function uiText(text){return window.VALI18n?.t(text)||text;}
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
  general.innerHTML='<h3>General</h3><div class="setting-row"><label for="uiLanguage">Idioma de la interfaz</label><select id="uiLanguage" aria-label="Seleccionar idioma"><option value="es">Español</option><option value="en">English</option><option value="pt">Português</option><option value="fr">Français</option><option value="de">Deutsch</option></select></div><p id="languageSaveState" class="mini" role="status">Guardado en este equipo</p><div class="setting-row"><span>Versión</span><span id="appBuild"></span></div><div class="settings-data"><h4>Datos locales</h4><code id="settingsDataPath"></code><button id="copyDataPath" type="button">Copiar ruta</button><a id="userGuide" href="/guide.html" target="_blank" rel="noopener">Guía de uso</a></div>';
  const guideLink=document.getElementById('userGuide');if(guideLink)guideLink.onclick=event=>{const invoke=window.__TAURI__?.core?.invoke;if(!invoke)return;event.preventDefault();invoke('open_guide').catch(()=>window.open('/guide.html','_blank','noopener'));};
  const chat=document.createElement('section');chat.id='settings-chat';chat.className='settings-page';chat.innerHTML='<h3>Cuadro de mensaje</h3>';chat.append(layout);
  const visualLayout=layout.querySelector('details');if(visualLayout){visualLayout.open=false;appearance.append(visualLayout);}
  const system=document.createElement('section');system.id='settings-system';system.className='settings-page';
  system.innerHTML='<h3>Sistema y motores</h3><div class="system-metrics"><div><span>CPU</span><strong id="systemCPU">—</strong><meter id="systemCPUMeter" min="0" max="100" value="0"></meter></div><div><span>Memoria</span><strong id="systemRAM">—</strong><meter id="systemRAMMeter" min="0" max="100" value="0"></meter></div><div><span>Memoria gráfica</span><strong id="systemVRAM">—</strong><meter id="systemVRAMMeter" min="0" max="100" value="0"></meter></div><div><span>Almacenamiento</span><strong id="systemDisk">—</strong><meter id="systemDiskMeter" min="0" max="100" value="0"></meter></div></div><div id="settingsEngineHost"><button id="openModelSettings" type="button">Modelo y motor</button></div>';
  const tools=document.createElement('section');tools.id='settings-tools';tools.className='settings-page';tools.innerHTML='<h3>Herramientas</h3><p class="mini">Ajusta cómo funcionan las herramientas y sus conexiones MCP. Para activarlas en un chat y elegir permisos, usa la ventana de Herramientas.</p><button id="openToolsWindow" type="button">Abrir ventana de herramientas</button><div id="settingsToolsHost"></div>';
  const historyPage=document.createElement('section');historyPage.id='settings-history-page';historyPage.className='settings-page';historyPage.innerHTML='<h3>Historial</h3>';historyPage.append(history);
  const market=document.createElement('section');market.id='settings-market';market.className='settings-page';market.innerHTML='<h3>Mercado</h3>';
  const pluginsPage=document.createElement('section');pluginsPage.id='settings-plugins';pluginsPage.className='settings-page';pluginsPage.innerHTML='<h3>Plugins</h3>';
  const pages={general,appearance,system,chat,tools,market,plugins:pluginsPage,history:historyPage};
  appearance.classList.add('settings-page');appearance.insertAdjacentHTML('afterbegin','<h3>Apariencia</h3><div class="animation-setting"><div class="setting-row"><label for="animationSpeed">Velocidad de animación</label><output id="animationSpeedValue" for="animationSpeed">620 ms</output></div><input id="animationSpeed" type="range" min="100" max="1600" step="20" value="620"><div class="animation-endpoints mini"><span>Rápidas</span><span>Pausadas</span></div><label class="chk"><input type="checkbox" id="windowAnimations" checked> Animar apertura y cierre de ventanas flotantes</label><p class="mini">La velocidad de arriba también se usa en las ventanas flotantes.</p><p id="animationSaveState" class="mini" role="status"></p></div>');
  // Export / import / reset act on the whole look, so they close the page instead of splitting groups.
  for(const element of appearance.querySelectorAll('.theme-actions,.theme-save-line'))appearance.append(element);
  body.replaceChildren(...Object.values(pages));
  // Ordered by how often people need them; names match the buttons they configure.
  const entries=[['general','General','idioma language langue Sprache dados data datos'],['appearance','Apariencia','colores colors cores couleurs Farben blur theme logo'],['chat','Cuadro de mensaje','layout font fuente letra botones buttons chat composer'],['tools','Herramientas','tools MCP Internet buscar arquivos files search'],['market','Mercado','plugins MCP marketplace extensions extensiones'],['plugins','Plugins','plugins extensiones comandos instructions commands'],['system','Sistema y motores','CPU RAM VRAM Strata llama.cpp API engine motor memory storage hardware actualizaciones updates'],['history','Historial','export import conversations chats historial histórico']];
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
  const powerHome=document.createElement('div');powerHome.id='modelPowerHome';powerHome.append(engineOptions.querySelector('#engineToggle').closest('.power-row'));
  const sourceTabs=engineOptions.querySelector('#modelSourceTabs');
  $('#controls-model').prepend(sourceTabs,quick,engineOptions,powerHome);$('#engineQuickSettings').onclick=()=>{engineOptions.open=!engineOptions.open;if(engineOptions.open){engineOptions.scrollIntoView({block:'nearest'});$('#engineKind').focus({preventScroll:true});}};
  const remoteInfo=$('#remoteModelInfo');if(remoteInfo)$('#controls-model .model-top').after(remoteInfo);
  const advanced=document.createElement('details');advanced.id='loadAdvanced';advanced.className='settings-group';advanced.innerHTML='<summary>Opciones avanzadas</summary>';
  $('#model-load-pane').append(advanced);for(const id of ['kvSettings','draftSettings','visionSettings','templateSettings'])advanced.append($('#'+id));
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
  configureMCPs.onclick=()=>{setDrawer(true);selectSettingsCategory('tools');const options=$('#mcpOptions');if(options){options.open=true;requestAnimationFrame(()=>options.querySelector('summary').focus({preventScroll:true}));}};
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
  const kind=activeEngine,builds=engineSnapshot.builds||{},info=kind==='strata'?builds.strata:kind==='rust'?builds.rust:builds[engineSnapshot.llama?.variant||'cuda'];
  $('#engineQuickName').textContent=kind==='api'?(engineSnapshot.api?.name||'API'):(kind==='strata'?'Strata':kind==='rust'?'Strata Rust':'llama.cpp')+' · '+(info?.build||info?.version||'');
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
function setupComposerMenu(){
  const menu=document.createElement('div');menu.id='composerAddMenu';menu.setAttribute('popover','manual');menu.setAttribute('role','menu');
  menu.innerHTML='<button id="addFilesMenu" type="button" role="menuitem"><span aria-hidden="true">＋</span><span>Adjuntar archivos</span></button><button id="webSearchMenu" type="button" role="menuitemcheckbox" aria-checked="false"><span aria-hidden="true">◎</span><span>Buscar en la web</span><i aria-hidden="true"></i></button><button id="openToolsMenu" type="button" role="menuitem"><span aria-hidden="true">⌘</span><span>Herramientas</span></button><button id="openProjectMenu" type="button" role="menuitem"><span aria-hidden="true">▱</span><span>Proyecto</span></button>';
  document.body.append(menu);$('#attach').innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';$('#attach').setAttribute('aria-label','Añadir');$('#attach').setAttribute('aria-haspopup','menu');$('#attach').setAttribute('aria-controls',menu.id);
  $('#attach').onclick=()=>{if(menu.matches(':popover-open')&&menu.dataset.motionClosing!=='true'){closeComposerMenu();return;}syncComposerMenu();if(window.VALMotion)window.VALMotion.showPopover(menu);else menu.showPopover();const rect=$('#attach').getBoundingClientRect(),height=menu.offsetHeight;menu.style.left=Math.min(innerWidth-menu.offsetWidth-12,Math.max(12,rect.left))+'px';menu.style.top=(innerHeight-rect.bottom-12>=height?rect.bottom+8:Math.max(12,rect.top-height-8))+'px';$('#attach').setAttribute('aria-expanded','true');$('#addFilesMenu').focus();};
  $('#addFilesMenu').onclick=()=>{closeComposerMenu();$('#file').click();};
  $('#webSearchMenu').onclick=()=>{const active=!!S.functions.search&&!!S.functions.visit;$('#s_ddg').checked=!active;$('#s_ddg').onchange();syncComposerMenu();};
  $('#openToolsMenu').onclick=()=>{closeComposerMenu();setChatControls('tools');};
  $('#openProjectMenu').onclick=()=>{closeComposerMenu();$('#projectBtn').click();};
  document.addEventListener('pointerdown',event=>{if(menu.matches(':popover-open')&&!event.target.closest('#composerAddMenu,#attach'))closeComposerMenu(false);});
  menu.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeComposerMenu();return;}if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...menu.querySelectorAll('button')],index=buttons.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();});
}
function closeComposerMenu(focus=true){const menu=$('#composerAddMenu');if(menu?.matches(':popover-open')){if(window.VALMotion)window.VALMotion.hidePopover(menu);else menu.hidePopover();}$('#attach').setAttribute('aria-expanded','false');if(focus)$('#attach').focus({preventScroll:true});}
function syncComposerMenu(){if($('#webSearchMenu')){$('#webSearchMenu').setAttribute('aria-checked',String(!!S.functions.search&&!!S.functions.visit));$('#webSearchMenu').disabled=busy||engineBusy;}}
async function restoreClientPreferences(){
  try{uiPreferences=await requestJSON('/api/harness/preferences');}catch{try{uiPreferences.language=localStorage.getItem('valLanguage')||'es';}catch{}}
  try{pcAccess=await requestJSON('/api/access');}catch{}
  S.agentProfile=uiPreferences.agent_profile||S.agentProfile||'balanced';if($('#agentProfile')){$('#agentProfile').value=S.agentProfile;$('#agentProfile').dispatchEvent(new Event('val-profile-restored'));}syncAgentModeSeat();
  if(!['ask','auto','run'].includes(S.permissionMode)){S.permissionMode='ask';saveSettings();}
  syncFunctionControls();if(typeof syncAccessControls==='function')syncAccessControls();
  applyDecoration(uiPreferences.decoration);
  const duration=uiPreferences.animation_ms??620;window.VALMotion?.setDuration(duration);$('#animationSpeed').value=duration;$('#animationSpeedValue').textContent=duration+' ms';
  if(!window.VALI18n){$('#uiLanguage').disabled=true;return;}
  try{await window.VALI18n.init(uiPreferences.language);}catch{uiPreferences.language='es';window.VALI18n.setLanguage('es');$('#uiLanguage').disabled=true;$('#languageSaveState').textContent='No se pudieron cargar las traducciones.';}uiPreferences.language=window.VALI18n.language;$('#uiLanguage').value=uiPreferences.language;
  const selectors=['#thinkingMenu','#permissionMenu','#searchToggle','#mobileMenu','.top-actions','#drawer','#composerControls','#composerAddMenu','#helpCard','#addModelDialog','#projectDialog','#viewer .dlg-head','#editMessageDialog','#engineCard','#gear','#newchat','.side-head','.sidebar-local','#sidebarExtras','#sidebarResizer','#sidebarReopen','#sidebar .sidebar-chrome','#agentModeBtn','#agentModeMenu','#agentModeSegments','#agentModeWarning','#convMenu','#projectMenu','#updateStack','#browserDock','#consoleWindow','#toolsWindow','#viewer','#vframe','#scopeBtn','#responseBtn','#modelBtn','#mcpBtn','#ctxBtn','#input','#attach','#projectBtn','#send','#themeBtn','#followBtn','.help-trigger','#chatActions','#attachments','#st-ram-meter','#st-vram-meter','#preparationProgress','#modelPreparation','#browserTabs','#browserNewTab','#browserDockClose','#browserBack','#browserUrl','#browserBookmark','#browserListClose','#toast','#dismissToast','#editMessageInput','.welcome','.history-empty','#toastText'];
  for(const selector of selectors)document.querySelectorAll(selector).forEach(el=>window.VALI18n.observe(el));
  window.VALI18n.onChange(()=>{document.querySelectorAll('.welcome,.history-empty').forEach(el=>window.VALI18n.observe(el));syncComposerLabels();syncContextMeter();if(lastToolBudget)pintarPresupuesto(lastToolBudget);if(!currentId)$('#chatTitle').textContent=uiText('Nuevo chat');for(const el of document.querySelectorAll('[data-ui-label]'))el.textContent=uiText(el.dataset.uiLabel);window.VALI18n.refresh();});
  syncSettingsSummary();window.VALI18n.refresh();
}

function cancelPendingEngineEdits(){
  if(!engineSnapshot||engineBusy||!engineFormDirty())return;
  const cfg=engineSnapshot.llama||{};$('#engineKind').value=activeEngine;$('#llamaVariant').value=cfg.variant||'cuda';$('#llamaExecutable').value=cfg.executable||'';$('#llamaLayers').value=cfg.gpu_layers||'auto';syncApiConnections();$('#engineKind').onchange();syncEngineCapabilities();
}


function currentThinking(){return modelCatalog?.find(m=>m.id===$('#model').value)?.thinking||{mode:'fixed',choices:[],default:'default'};}
// Spanish base phrases go through uiText like the rest of the interface.
const THINK_LABELS=new Proxy({none:'Sin pensar',think:'Pensar',minimal:'Mínimo',low:'Bajo',medium:'Medio',high:'Alto',xhigh:'Máximo',default:'Auto'},{get:(labels,key)=>typeof key==='string'&&labels[key]?uiText(labels[key]):undefined});
function syncAgentControls(){
  if(!$('#thinkingMenu'))return;
  $('#scopeLabel').textContent=uiText(pcAccess.mode==='full_pc'?'Toda la PC':'Sandbox')+' · '+uiText(S.permissionMode==='ask'?'Preguntar':S.permissionMode==='auto'?'Confirmar cambios':'Automático');
  const info=currentThinking();if(!info.choices.includes(S.effort))S.effort=info.default;
  $('#responseBtnLabel').textContent=THINK_LABELS[S.effort]||'Think';$('#responseBtn').setAttribute('aria-label',uiText('Pensamiento')+': '+$('#responseBtnLabel').textContent);$('#responseBtn').disabled=busy||!info.choices.length;
  const signature=JSON.stringify(info.choices);if($('#effort').dataset.choices!==signature){$('#effort').replaceChildren(...(info.choices.length?info.choices:['default']).map(value=>{const option=document.createElement('option');option.value=value;option.textContent=THINK_LABELS[value];return option;}));$('#effort').dataset.choices=signature;}$('#effort').value=S.effort;
  $('#searchToggle').setAttribute('aria-pressed',String(!!S.functions.search));$('#searchToggle').disabled=busy||engineBusy;
  const menu=$('#thinkingMenu');if(menu.matches(':popover-open')){for(const button of menu.children)button.setAttribute('aria-checked',String(button.textContent===THINK_LABELS[S.effort]));return;}menu.replaceChildren(...info.choices.map(value=>{const button=document.createElement('button');button.type='button';button.textContent=THINK_LABELS[value];button.setAttribute('role','menuitemradio');button.setAttribute('aria-checked',String(value===S.effort));button.onclick=()=>{S.effort=value;$('#effort').value=value;markCustomProfile();saveSettings();syncComposerLabels();window.VALMotion.hidePopover(menu);};return button;}));
  $('#searchToggle').setAttribute('aria-pressed',String(!!S.functions.search));$('#searchToggle').disabled=busy||engineBusy;
  for(const id of ['f_web','f_autobrowser']){const box=document.getElementById(id);if(box)box.disabled=busy||engineBusy||S.agentProfile==='light';}
  for(const id of ['f_admin','f_computer']){const box=document.getElementById(id);if(box)box.disabled=busy||engineBusy||S.agentProfile!=='advanced'||pcAccess.mode!=='full_pc';}
  syncAgentModeSeat();
}
function showAgentMenu(menu,anchor){
  if(menu.matches(':popover-open')&&menu.dataset.motionClosing!=='true'){window.VALMotion.hidePopover(menu);return;}
  closeChatControls(false,true);for(const other of document.querySelectorAll('.agent-small-menu'))if(other!==menu&&other.matches(':popover-open'))window.VALMotion.hidePopover(other);window.VALMotion.showPopover(menu);anchor.setAttribute('aria-expanded','true');if(menu.id==='permissionMenu'){for(const button of menu.querySelectorAll('[data-mode]'))button.setAttribute('aria-checked',String(button.dataset.mode===(S.permissionMode||'ask')));for(const button of menu.querySelectorAll('[data-scope]'))button.setAttribute('aria-checked',String(button.dataset.scope===pcAccess.mode));}
  // Always open downwards; flip up only when the composer sits at the bottom edge and there is
  // no usable room below (under 220 px). The menu fits the window and scrolls inside.
  const rect=anchor.getBoundingClientRect();menu.style.maxHeight='';menu.dataset.side='below';
  const below=innerHeight-rect.bottom-14,above=rect.top-14,natural=menu.scrollHeight;
  const up=below<Math.min(natural,220)&&above>below;menu.dataset.side=up?'above':'below';
  const room=Math.max(160,up?above:below);menu.style.maxHeight=Math.min(natural,room)+'px';
  menu.style.left=Math.min(innerWidth-menu.offsetWidth-12,Math.max(12,rect.left))+'px';
  menu.style.top=(up?Math.max(8,rect.top-Math.min(natural,room)-6):rect.bottom+6)+'px';
  menu.querySelector('button,select')?.focus({preventScroll:true});
}
function setupAgentControls(){
  for(const id of ['thinkingMenu','permissionMenu']){const menu=document.createElement('div');menu.id=id;menu.className='agent-small-menu';menu.setAttribute('popover','manual');menu.setAttribute('role','menu');menu.addEventListener('toggle',()=>{const button=id==='thinkingMenu'?$('#responseBtn'):$('#scopeBtn');button.setAttribute('aria-expanded',String(menu.matches(':popover-open')));});document.body.append(menu);}
  const thought=$('#responseBtn');thought.removeAttribute('data-controls');thought.setAttribute('aria-controls','thinkingMenu');thought.onclick=()=>{syncAgentControls();showAgentMenu($('#thinkingMenu'),thought);};
  const permission=$('#permissionMenu');permission.innerHTML='<div class="mini">Acceso a archivos</div>';
  for(const [scope,label,detail] of [['sandbox','Sandbox','Solo el proyecto o la carpeta del chat.'],['full_pc','Toda la PC','Rutas accesibles con los permisos de tu usuario.']]){const button=document.createElement('button');button.type='button';button.dataset.scope=scope;button.setAttribute('role','menuitemradio');button.innerHTML='<strong></strong><small></small>';button.querySelector('strong').textContent=label;button.querySelector('small').textContent=detail;button.onclick=async()=>{if(busy||engineBusy)return;$('#pcAccess').value=scope;await $('#pcAccess').onchange();syncAgentControls();for(const item of permission.querySelectorAll('[data-scope]'))item.setAttribute('aria-checked',String(item.dataset.scope===pcAccess.mode));};permission.append(button);}
  const openSandbox=document.createElement('button');openSandbox.type='button';openSandbox.id='permissionOpenSandbox';openSandbox.textContent=uiText('Abrir carpeta del Sandbox');openSandbox.onclick=()=>{window.VALMotion.hidePopover(permission);openConversationSandbox();};permission.append(openSandbox);
  const heading=document.createElement('div');heading.className='mini permission-heading';heading.textContent='Aprobaciones';permission.append(heading);
  const modes=[['ask','Preguntar siempre','Confirmar cada herramienta o acceso a Internet.'],['auto','Confirmar cambios','Lecturas automáticas; confirmar escrituras, ejecución y acciones desconocidas.'],['run','Automático','Ejecutar las herramientas activadas sin preguntar.']];
  for(const [mode,label,detail] of modes){const button=document.createElement('button');button.type='button';button.dataset.mode=mode;button.setAttribute('role','menuitemradio');button.innerHTML='<strong></strong><small></small>';button.querySelector('strong').textContent=label;button.querySelector('small').textContent=detail;button.onclick=()=>{if(busy||engineBusy)return;S.permissionMode=mode;saveSettings();syncAgentControls();for(const item of permission.querySelectorAll('[data-mode]'))item.setAttribute('aria-checked',String(item.dataset.mode===mode));};permission.append(button);}
  const note=document.createElement('p');note.className='mini';note.textContent='El aislamiento de comandos se comprueba antes de usarse.';permission.append(note);window.VALI18n?.observe(permission);
  const scope=$('#scopeBtn');scope.removeAttribute('data-controls');scope.setAttribute('aria-controls','permissionMenu');scope.onclick=()=>showAgentMenu(permission,scope);
  const search=document.createElement('button');search.type='button';search.id='searchToggle';search.className='composer-control icon-only';search.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/></svg>';search.setAttribute('aria-label','Internet: buscar y leer con DuckDuckGo');search.onclick=()=>{$('#s_ddg').checked=!S.functions.search;$('#s_ddg').onchange();syncAgentControls();};$('#mcpBtn').before(search);
  document.addEventListener('pointerdown',event=>{for(const id of ['thinkingMenu','permissionMenu']){const menu=$('#'+id);if(menu.matches(':popover-open')&&!event.target.closest('#'+id+',#responseBtn,#scopeBtn'))window.VALMotion.hidePopover(menu);}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const id of ['thinkingMenu','permissionMenu'])if($('#'+id).matches(':popover-open'))window.VALMotion.hidePopover($('#'+id));});
}
// In-app replacement for window.confirm: follows the palette, translates, and keeps focus on the
// safe choice. Resolves true only when the user presses the confirm button.
function valConfirm({title,message='',confirm='Aceptar',cancel='Cancelar',danger=false}={}){
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.className='val-confirm';
    const heading=document.createElement('h3');heading.textContent=uiText(title||'¿Continuar?');
    const body=document.createElement('p');body.textContent=uiText(message);body.hidden=!message;
    const actions=document.createElement('div');actions.className='val-confirm-actions';
    const no=document.createElement('button');no.type='button';no.className='soft-btn';no.textContent=uiText(cancel);
    const yes=document.createElement('button');yes.type='button';yes.className='soft-btn '+(danger?'danger':'primary');yes.textContent=uiText(confirm);
    let answered=false;const finish=value=>{if(answered)return;answered=true;resolve(value);dialog.close();dialog.remove();};
    no.onclick=()=>finish(false);yes.onclick=()=>finish(true);
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false);});
    dialog.addEventListener('click',event=>{if(event.target===dialog)finish(false);});
    actions.append(no,yes);dialog.append(heading,body,actions);document.body.append(dialog);dialog.showModal();no.focus();
  });
}
window.valConfirm=valConfirm;
function showToolApproval(event){
  // Plain language first (what and where), readable content second, raw call folded for experts.
  const dialog=document.createElement('dialog');dialog.className='tool-approval';const title=document.createElement('h3');title.textContent='Autorizar herramienta';
  const input=event.args&&typeof event.args==='object'?event.args:{};
  const target=String(input.path||input.url||input.query||input.command||input.desde||'');
  const name=document.createElement('strong');name.textContent=toolTitle(event)+(target&&!input.command?' · '+target:'');
  const body=typeof input.content==='string'?input.content:typeof input.command==='string'?input.command:typeof input.new_text==='string'?input.new_text:'';
  const args=document.createElement('pre');args.textContent=body||JSON.stringify(input,null,2);
  const raw=document.createElement('details');raw.className='tool-approval-raw';const rawSummary=document.createElement('summary');rawSummary.textContent=uiText('Detalles técnicos');const rawText=document.createElement('pre');rawText.textContent=event.name+'\n'+JSON.stringify(input,null,2);raw.append(rawSummary,rawText);
  const actions=document.createElement('div');
  const reply=async(allowed,remember=false)=>{try{await requestJSON('/api/harness/approval',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:event.id,allowed,remember})});dialog.close();dialog.remove();}catch(error){if(activeGeneration?.controller.signal.aborted){dialog.remove();return;}name.textContent=error.message;}};
  const choices=[['Denegar',false,false],...(event.rememberable?[['Permitir siempre en este chat',true,true]]:[]),['Permitir una vez',true,false]];
  for(const [label,allowed,remember] of choices){const button=document.createElement('button');button.type='button';button.textContent=uiText(label);if(remember)button.title=uiText('No volverá a preguntar por esta herramienta en esta conversación hasta que cierres V-Agent.');button.className='soft-btn'+(label==='Permitir una vez'?' primary':'');button.onclick=()=>reply(allowed,remember);actions.append(button);}
  // A bare {path}/{url}/{query} is already in the title; showing it again as JSON adds nothing.
  const onlyTarget=!body&&Object.keys(input).every(key=>['path','url','query'].includes(key));
  dialog.append(title,name,...(onlyTarget?[]:[args]),...(body?[raw]:[]),actions);dialog.addEventListener('cancel',e=>{e.preventDefault();reply(false);});activeGeneration?.controller.signal.addEventListener('abort',()=>dialog.remove(),{once:true});document.body.append(dialog);dialog.showModal();window.VALI18n?.observe(dialog);
}


const AGENT_MODES={
  light:{name:'Agente ligero',short:'Ligero',desc:'Herramientas esenciales y comandos con aprobación. El acceso y las aprobaciones se eligen por separado.'},
  balanced:{name:'Agente estándar',short:'Estándar',desc:'Herramientas de archivos, web, consola y Hugging Face seleccionadas. El acceso y las aprobaciones se eligen por separado.'},
  advanced:{name:'Agente completo',short:'Completo',desc:'Herramientas adicionales de escritorio y administrador cuando se activan. El acceso y las aprobaciones se eligen por separado.'}
};
const AGENT_MODE_ORDER=['light','balanced','advanced'];
function agentModeKey(){return AGENT_MODES[S.agentProfile]?S.agentProfile:'balanced';}
function syncFunctionControls(){
  for(const key of Object.keys(DEF_FUNCS)){const box=document.getElementById('f_'+key);if(box)box.checked=!!S.functions[key];}
  const dock=document.getElementById('browserAgentUse');if(dock)dock.checked=!!S.functions.browser;
  const search=document.getElementById('s_ddg');if(search){const count=['search','visit'].filter(key=>S.functions[key]).length;search.checked=count===2;search.indeterminate=count===1;}
  const pc=document.getElementById('s_pc');if(pc){const keys=pcAccess.mode==='full_pc'?['files','shell','sys']:['files','sys'];const count=keys.filter(key=>S.functions[key]).length;pc.checked=count===keys.length;pc.indeterminate=count>0&&count<keys.length;}
}
function syncAgentModeSeat(){
  const key=agentModeKey(),meta=AGENT_MODES[key],button=document.getElementById('agentModeBtn');
  if(button){const label=document.getElementById('agentModeLabel');if(label)label.textContent=uiText(meta.name);button.dataset.mode=key;button.title=uiText(meta.desc);button.disabled=!!(busy||engineBusy);button.setAttribute('aria-label',uiText('Modo del agente')+': '+uiText(meta.name)+'. '+uiText('Cambiar modo'));}
  const menu=document.getElementById('agentModeMenu');
  if(menu)for(const item of menu.querySelectorAll('[data-mode]'))item.setAttribute('aria-checked',String(item.dataset.mode===key));
  const select=document.getElementById('agentProfile');if(select&&select.value!==key){select.value=key;select.dispatchEvent(new Event('val-profile-restored'));}
  for(const option of document.querySelectorAll('#agentModeSegments button')){option.setAttribute('aria-pressed',String(option.dataset.agentMode===key));option.disabled=!!(busy||engineBusy);}
}
function showAgentModeWarning(){
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.id='agentModeWarning';dialog.className='tool-approval agent-mode-warning';
    dialog.innerHTML='<h3>Activar Agente completo</h3><p>Habilita las herramientas avanzadas que selecciones. El alcance y las aprobaciones no cambian.</p><p class="mini">El administrador elevado solo se usa si activas su herramienta; Windows solicitará UAC.</p><div><button type="button" data-cancel>Cancelar</button><button type="button" class="danger" data-confirm>Activar de todos modos</button></div>';
    const finish=value=>{if(!dialog.open&&!dialog.isConnected)return;if(dialog.open)dialog.close();dialog.remove();resolve(value==='activate');};
    dialog.querySelector('[data-cancel]').onclick=()=>finish('cancel');
    dialog.querySelector('[data-confirm]').onclick=()=>finish('activate');
    dialog.oncancel=event=>{event.preventDefault();finish('cancel');};
    document.body.append(dialog);window.VALI18n?.observe(dialog);dialog.showModal();dialog.querySelector('[data-cancel]').focus();
  });
}
async function setAgentMode(key,options={}){
  if(!AGENT_MODES[key]||busy||engineBusy)return false;
  if(key==='advanced'&&!options.silent&&!await showAgentModeWarning())return false;
  S.agentProfile=key;
  saveSettings();syncFunctionControls();syncServerSwitches();syncAgentControls();syncAgentModeSeat();
  if(typeof syncAccessControls==='function')syncAccessControls();
  presupuestoFirmado='';if(typeof consultarPresupuesto==='function')consultarPresupuesto();
  try{await requestJSON('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_profile:key})});}
  catch(error){note(error.message);}
  if(key!=='advanced'){
    requestJSON('/api/harness/admin/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(10000)}).catch(()=>{});
  }
  return true;
}
function setupAgentModeSeat(){
  if(document.getElementById('agentModeBtn'))return;
  const strip=document.querySelector('.project-strip');if(!strip)return;
  const button=document.createElement('button');button.id='agentModeBtn';button.type='button';button.className='composer-control agent-mode-seat';
  button.setAttribute('aria-haspopup','menu');button.setAttribute('aria-expanded','false');
  button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 7v5c0 5 8 9 8 9s8-4 8-9V7l-8-4Z"/><path d="M9 12h6M12 9v6"/></svg><span id="agentModeLabel">Agente estándar</span><span class="control-chevron" aria-hidden="true">⌄</span>';
  strip.append(button);
  const segments=document.createElement('div');segments.id='agentModeSegments';segments.setAttribute('role','group');segments.setAttribute('aria-label','Modo del agente');
  for(const key of AGENT_MODE_ORDER){const option=document.createElement('button');option.type='button';option.dataset.agentMode=key;option.textContent=uiText(AGENT_MODES[key].short);option.dataset.modeDescription=uiText(AGENT_MODES[key].desc);option.setAttribute('aria-label',uiText(AGENT_MODES[key].name));option.onclick=()=>setAgentMode(key);segments.append(option);}
  strip.append(segments);button.hidden=true;window.VALI18n?.observe(segments);
  const tip=document.createElement('div');tip.id='agentModeTooltip';tip.setAttribute('role','tooltip');tip.setAttribute('popover','manual');document.body.append(tip);
  const dismissTip=()=>{if(tip.matches(':popover-open'))window.VALMotion.hidePopover(tip,()=>{},true);};
  const showTip=option=>{tip.textContent=uiText(option.dataset.modeDescription);option.setAttribute('aria-describedby',tip.id);window.VALMotion.showPopover(tip);const r=option.getBoundingClientRect();tip.style.left=Math.max(10,Math.min(innerWidth-tip.offsetWidth-10,r.left))+'px';tip.style.top=Math.max(10,r.top-tip.offsetHeight-10)+'px';};
  for(const option of segments.children){option.addEventListener('pointerenter',()=>showTip(option));option.addEventListener('focus',()=>showTip(option));option.addEventListener('pointerleave',dismissTip);option.addEventListener('blur',dismissTip);option.addEventListener('click',dismissTip);}
  addEventListener('resize',dismissTip);document.addEventListener('scroll',dismissTip,true);document.addEventListener('keydown',e=>{if(e.key==='Escape')dismissTip();});

  const menu=document.createElement('div');menu.id='agentModeMenu';menu.className='agent-small-menu agent-mode-menu';menu.setAttribute('popover','manual');menu.setAttribute('role','menu');menu.setAttribute('aria-label',uiText('Modo del agente'));
  for(const key of AGENT_MODE_ORDER){
    const meta=AGENT_MODES[key],item=document.createElement('button');item.type='button';item.dataset.mode=key;item.setAttribute('role','menuitemradio');
    const strong=document.createElement('strong');strong.textContent=uiText(meta.name);const small=document.createElement('small');small.textContent=uiText(meta.desc);const check=document.createElement('span');check.className='mode-check';check.setAttribute('aria-hidden','true');check.textContent='✓';
    item.append(strong,check,small);
    item.onclick=async()=>{const changed=await setAgentMode(key);if(changed&&menu.matches(':popover-open'))window.VALMotion.hidePopover(menu);};
    menu.append(item);
  }
  document.body.append(menu);
  button.onclick=()=>{
    if(menu.matches(':popover-open')){window.VALMotion.hidePopover(menu);return;}
    closeChatControls(false,true);showAgentMenu(menu,button);
  };
  document.addEventListener('pointerdown',event=>{if(menu.matches(':popover-open')&&!event.target.closest('#agentModeMenu,#agentModeBtn'))window.VALMotion.hidePopover(menu);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&menu.matches(':popover-open'))window.VALMotion.hidePopover(menu);});
  syncAgentModeSeat();
}
function setupAgentProfilesAndUpdates(){
  const profile=document.createElement('div');profile.innerHTML='<div class="agent-profile-row"><label for="agentProfile">Modo del agente</label><select id="agentProfile"><option value="light">Agente ligero</option><option value="balanced">Agente estándar</option><option value="advanced">Agente completo</option></select></div><p id="agentProfileHint" class="mini"></p>';
  $('#controls-tools').prepend(profile);
  function hint(){if($('#agentProfileHint'))$('#agentProfileHint').textContent=uiText(AGENT_MODES[agentModeKey()].desc);}
  $('#agentProfile').value=agentModeKey();$('#agentProfile').addEventListener('val-profile-restored',hint);hint();
  $('#agentProfile').onchange=async()=>{const wanted=$('#agentProfile').value;const changed=await setAgentMode(wanted);if(!changed)$('#agentProfile').value=agentModeKey();hint();};
  setupAgentModeSeat();
  const updates=document.createElement('section');updates.id='engineUpdates';updates.innerHTML='<div id="engineHardware" class="engine-hardware"><div class="engine-hardware-head"><h4>Hardware y motores recomendados</h4><button id="copyHardware" type="button">Copiar informe</button></div><div id="hwChips" class="hardware-chips"></div><p id="hwSummary" class="mini"></p><div id="engineRecommendations" class="engine-recommendations"></div></div><h4>Actualizaciones oficiales</h4><button id="checkEngineUpdates" type="button">Comprobar actualizaciones</button><p id="engineUpdateStatus" class="mini" role="status"></p><div id="engineUpdateList"></div>';
  $('#settings-system').append(updates);
  const stack=document.createElement('div');stack.id='updateStack';stack.className='update-stack';stack.hidden=true;document.body.append(stack);
  const dismissed=new Set();
  async function action(which,body={}){try{const state=await requestJSON('/api/harness/updates/'+which,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});paintUpdates(state);clearTimeout(updatePollTimer);updatePollTimer=setTimeout(pollUpdates,state.installing?400:10000);}catch(error){$('#engineUpdateStatus').textContent=error.message;}}
  $('#checkEngineUpdates').onclick=()=>action('check');
  let hardwareSignature='';
  function hardwareChip(label,value,title=''){
    const chip=document.createElement('span');chip.className='hardware-chip';chip.title=title;
    const small=document.createElement('small');small.textContent=label;const strong=document.createElement('strong');strong.textContent=value||'—';
    chip.append(small,strong);return chip;
  }
  function paintHardware(state){
    const profile=state.hardware||{},rows=state.recommendations||[];
    const signature=JSON.stringify({profile,rows,summary:state.hardware_summary,busy:state.busy,loaded:!!loadedModel});
    if(signature===hardwareSignature)return;hardwareSignature=signature;
    const chips=$('#hwChips');if(!chips)return;chips.replaceChildren();
    const gpu=profile.primary_gpu||{};
    chips.append(hardwareChip(uiText('CPU'),profile.cpu?.name||'—',profile.cpu?.name||''));
    chips.append(hardwareChip(uiText('GPU'),gpu.name||uiText('Sin GPU NVIDIA'),gpu.name?`${gpu.vendor||''} ${gpu.driver||''} ${gpu.cuda_capability?('CC '+gpu.cuda_capability):''}`.trim():''));
    chips.append(hardwareChip('VRAM',gpu.vram_mib?uiNumber(Math.round(gpu.vram_mib/1024))+' GB':'—'));
    chips.append(hardwareChip('RAM',profile.ram?.total_gib?uiNumber(profile.ram.total_gib)+' GB':'—'));
    chips.append(hardwareChip(uiText('Disco libre'),profile.disk?.free_gib?uiNumber(profile.disk.free_gib)+' GB':'—'));
    chips.append(hardwareChip(uiText('Sistema'),[profile.os?.product,profile.os?.display].filter(Boolean).join(' · ')||'—'));
    const summary=$('#hwSummary');if(summary)summary.textContent=state.hardware_summary||'';
    const box=$('#engineRecommendations');if(!box)return;box.replaceChildren();
    const visible=rows.filter(row=>row.recommended);
    for(const row of visible){
      const card=document.createElement('article');card.className='engine-recommendation';card.dataset.engine=row.key;
      const head=document.createElement('div');head.className='engine-recommendation-head';
      const name=document.createElement('strong');name.textContent=row.name;
      const badge=document.createElement('span');badge.className='recommendation-badge';badge.textContent=uiText('Recomendado');head.append(name,badge);
      const reason=document.createElement('p');reason.className='mini';reason.textContent=row.reason;
      const asset=document.createElement('div');asset.className='engine-asset';
      const tag=document.createElement('code');tag.textContent=row.tag||uiText('Sin versión publicada');asset.append(tag);
      if(row.asset){const filename=document.createElement('code');filename.textContent=row.asset;asset.append(filename);}
      if(row.dependencies?.length){const extra=document.createElement('small');extra.textContent='+ '+row.dependencies.join(' + ');asset.append(extra);}
      const actions=document.createElement('div');actions.className='engine-recommendation-actions';
      const status=document.createElement('span');status.className='engine-recommendation-status';
      const installed=row.status==='installed';
      status.textContent=installed?uiText('Instalado'):row.status==='available'?uiText('Actualización disponible'):row.asset?uiText('Disponible'):uiText('Comprueba las versiones');
      status.dataset.state=row.status;
      actions.append(status);
      if(installed||row.status==='missing'){/* nothing to install */}
      else if(row.asset){const install=document.createElement('button');install.type='button';install.textContent=uiText('Instalar');install.disabled=!!state.busy||!!loadedModel;install.onclick=()=>action('install',{engine:row.key});actions.append(install);}
      else {const check=document.createElement('button');check.type='button';check.textContent=uiText('Comprobar');check.disabled=!!state.busy;check.onclick=()=>action('check');actions.append(check);}
      card.append(head,reason,asset,actions);box.append(card);
    }
    window.VALI18n?.observe(updates);
  }
  $('#copyHardware').onclick=async()=>{try{const data=await requestJSON('/api/harness/hardware');await navigator.clipboard.writeText(JSON.stringify({hardware:data.hardware,recommendations:data.recommendations,summary:data.hardware_summary},null,2));note(uiText('Informe copiado.'));}catch(error){note(error.message);}};
  let signature='',installedSignature='';
  function paintStackProgress(progress){
    const card=stack.querySelector(':scope > .update-card');if(!card)return;
    let box=card.querySelector('.update-progress');
    if(!progress){box?.remove();return;}
    const percent=progress.total?Math.min(100,progress.received/progress.total*100):0;
    if(!box){
      box=document.createElement('div');box.className='update-progress';
      const label=document.createElement('span');const bar=document.createElement('progress');bar.max=100;
      box.append(label,bar);const actions=card.querySelector('.update-actions');if(actions)actions.before(box);else card.append(box);
    }
    const label=box.querySelector('span'),bar=box.querySelector('progress');
    label.textContent=uiText({download:'Descargando',extract:'Extrayendo',verify:'Verificando',complete:'Completado',error:'Error'}[progress.phase]||'Procesando')+' · '+percent.toFixed(1)+' % · '+(progress.received/1048576).toFixed(1)+' / '+(progress.total/1048576).toFixed(1)+' MB';
    bar.value=percent;
  }
  function paintUpdates(state){
    // Progress ticks must not rebuild the card: that made the notification blink.
    const progress=state.progress?{engine:state.progress.engine,phase:state.progress.phase,total:state.progress.total||0}:null;
    const current=JSON.stringify({...state,progress});if(current===signature){lastUpdateInstalling=!!state.installing;paintDownloadProgress(state.progress);paintStackProgress(state.progress);return;}signature=current;
    const installed=JSON.stringify(state.installed||{});if(installed!==installedSignature&&!state.busy){installedSignature=installed;requestJSON('/api/harness/state').then(snapshot=>{engineSnapshot=snapshot;syncEngineVersions();syncSettingsSummary();}).catch(()=>{});}
    $('#engineUpdateStatus').textContent=state.error||state.operation||(state.busy?uiText('Comprobando…'):'');$('#checkEngineUpdates').disabled=state.busy;
    lastUpdateInstalling=!!state.installing;paintDownloadProgress(state.progress);paintHardware(state);
    const list=$('#engineUpdateList');list.replaceChildren();
    const names={'llama-cpu':'llama.cpp · CPU','llama-cuda':'llama.cpp · CUDA 12.4','llama-vulkan':'llama.cpp · Vulkan',strata:'Strata · PolyStrata',rust:'Strata Rust'};
    for(const [key,release] of Object.entries(state.releases||{})){
      const row=document.createElement('div');row.className='engine-update-row';const name=document.createElement('strong');name.textContent=names[key]||key;const details=document.createElement('small');details.textContent=release.error||release.message||(release.tag+' · '+(release.available?uiText('Disponible'):uiText('Actualizado'))+(release.development?' · '+uiText('Desarrollo oficial'):''));row.append(name,details);
      if(release.url){const link=document.createElement('a');link.href=release.url;link.onclick=event=>{event.preventDefault();showReleaseNotes(release);};link.textContent=uiText('Notas de versión');row.append(link);}
      if(release.asset&&release.available){const button=document.createElement('button');button.textContent=uiText('Actualizar');button.disabled=state.busy||busy||!!loadedModel;button.onclick=()=>action('install',{engine:key});const actions=document.createElement('div');actions.className='engine-update-actions';actions.append(button);row.append(actions);}
      if(Object.hasOwn(state.previous||{},key)){const rollback=document.createElement('button');rollback.textContent=uiText('Restaurar anterior');rollback.disabled=state.busy||!!loadedModel;rollback.onclick=()=>action('rollback',{engine:key});row.append(rollback);}
      list.append(row);
    }
    const available=Object.entries(state.releases||{}).filter(([,r])=>r.available).map(([k,r])=>k+':'+r.tag).join('|');
    renderUpdateStack(state);
    window.VALI18n?.observe(updates);window.VALI18n?.observe(stack);
  }
  function positionUpdateStack(){
    if(stack.hidden)return;
    const composer=document.getElementById('composerBox'),measured=composer&&composer.getBoundingClientRect();
    // While the composer glides to its new place, measure where it will land (minus its running transform).
    const shift=composer?new DOMMatrixReadOnly(getComputedStyle(composer).transform==='none'?undefined:getComputedStyle(composer).transform).m42:0;
    const rect=measured&&{top:measured.top-shift,bottom:measured.bottom-shift};
    const available=rect?Math.max(0,innerHeight-rect.bottom-16):0;
    const height=stack.scrollHeight||stack.offsetHeight||0;
    const bottom=rect&&height>available?Math.round(innerHeight-rect.top+12):16;
    stack.style.setProperty('--update-bottom',Math.max(16,bottom)+'px');
  }
  function renderUpdateStack(state){
    const names={'llama-cpu':'llama.cpp · CPU','llama-cuda':'llama.cpp · CUDA 12.4','llama-vulkan':'llama.cpp · Vulkan',strata:'Strata · PolyStrata',rust:'Strata Rust'};
    let available=Object.entries(state.releases||{}).filter(([key,release])=>release.available&&release.asset&&!dismissed.has(key+':'+release.tag));
    const variant=document.getElementById('llamaVariant')?.value||'cuda';
    const preferred='llama-'+(['cpu','vulkan'].includes(variant)?variant:'cuda');
    const llama=available.find(([key])=>key===preferred);
    available=available.filter(([key])=>!key.startsWith('llama-'));
    if(llama)available.unshift(llama);
    const shown=available.slice(0,1),remaining=available.length-shown.length;
    const deferred=Date.now()/1000<=(state.deferred_until||0);
    if(!available.length||deferred){stack.hidden=true;stack.replaceChildren();delete stack.dataset.signature;return;}
    // Progress polls arrive every 400 ms while installing. Rebuilding the card each time replayed its
    // entrance animation (the window "blinked"); rebuild only when what is shown changes.
    const progressFor=key=>state.progress&&state.progress.engine===key?state.progress:null;
    const progressText=progress=>{const percent=progress.total?Math.min(100,progress.received/progress.total*100):0;return [percent,uiText({download:'Descargando',extract:'Extrayendo',verify:'Verificando',complete:'Completado',error:'Error'}[progress.phase]||'Procesando')+' · '+percent.toFixed(1)+' % · '+(progress.received/1048576).toFixed(1)+' / '+(progress.total/1048576).toFixed(1)+' MB'];};
    const installDisabled=!!state.busy||busy||!!loadedModel;
    const signature=JSON.stringify([shown.map(([key,release])=>[key,release.tag,release.current,!!progressFor(key)]),remaining]);
    if(stack.dataset.signature===signature&&stack.children.length){
      for(const [key] of shown){
        const card=stack.querySelector('.update-card'),progress=progressFor(key);if(!card)continue;
        if(progress){const [percent,text]=progressText(progress);const label=card.querySelector('.update-progress span'),bar=card.querySelector('.update-progress progress');if(label&&label.textContent!==text)label.textContent=text;if(bar)bar.value=percent;}
        const install=card.querySelector('.update-install');if(install){install.disabled=installDisabled;install.title=loadedModel?uiText('Descarga el modelo antes de actualizar.'):'';}
      }
      return;
    }
    stack.dataset.signature=signature;
    stack.hidden=false;stack.replaceChildren();
    for(const [key,release] of shown){
      const card=document.createElement('article');card.className='update-card';
      const close=document.createElement('button');close.type='button';close.className='update-card-close';close.setAttribute('aria-label',uiText('Descartar aviso'));close.textContent='×';
      close.onclick=()=>{dismissed.add(key+':'+release.tag);card.remove();if(!stack.children.length)stack.hidden=true;};
      const head=document.createElement('div');head.className='update-card-head';
      const icon=document.createElement('span');icon.className='update-card-icon';icon.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M5 21h14"/></svg>';
      const text=document.createElement('div');text.className='update-card-text';
      const title=document.createElement('h4');title.textContent=uiText('Nueva versión de')+' '+(names[key]||key);
      const version=document.createElement('p');version.className='update-card-version';version.textContent=(release.current?String(release.current)+' → ':'')+(release.tag||'');
      text.append(title,version);head.append(icon,text);card.append(close,head);
      if(state.progress&&state.progress.engine===key){
        const [percent,labelText]=progressText(state.progress);
        const box=document.createElement('div');box.className='update-progress';
        const label=document.createElement('span');label.textContent=labelText;
        const bar=document.createElement('progress');bar.max=100;bar.value=percent;
        box.append(label,bar);card.append(box);
      }
      const actions=document.createElement('div');actions.className='update-actions';
      const install=document.createElement('button');install.type='button';install.className='update-install';install.textContent=uiText('Actualizar');
      install.disabled=installDisabled;
      if(loadedModel)install.title=uiText('Descarga el modelo antes de actualizar.');
      install.onclick=()=>action('install',{engine:key});
      actions.append(install);card.append(actions);
      stack.append(card);
    }
    if(remaining>0){
      const row=document.createElement('div');row.className='update-more-row';
      const text=document.createElement('span');text.textContent=uiText(remaining===1?'{n} actualización más del runtime':'{n} actualizaciones más del runtime').replace('{n}',remaining);
      const button=document.createElement('button');button.type='button';button.textContent=uiText('Ver en Ajustes');
      button.onclick=()=>{setDrawer(true);selectSettingsCategory('system');requestAnimationFrame(()=>updates.scrollIntoView({block:'start',behavior:'smooth'}));};
      row.append(text,button);stack.append(row);
    }
    requestAnimationFrame(positionUpdateStack);
  }
  let lastUpdateInstalling=false,updatePollTimer,paintedUpdates=false;
  window.addEventListener('resize',positionUpdateStack);
  if(window.ResizeObserver&&document.getElementById('composerBox'))new ResizeObserver(positionUpdateStack).observe(document.getElementById('composerBox'));
  // The composer moves from the centre to the bottom without resizing; follow it so the notice
  // never covers the send button (once now, once after the move animation).
  const chatwrap=document.getElementById('chatwrap');
  if(chatwrap&&window.MutationObserver)new MutationObserver(()=>{
    requestAnimationFrame(positionUpdateStack);
    const duration=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--motion-duration'))||620;
    setTimeout(positionUpdateStack,duration+60);
  }).observe(chatwrap,{attributes:true,attributeFilter:['data-empty']});
  async function pollUpdates(){if(!document.hidden||!paintedUpdates)try{paintUpdates(await requestJSON('/api/harness/updates'));paintedUpdates=true;positionUpdateStack();}catch{}updatePollTimer=setTimeout(pollUpdates,lastUpdateInstalling?400:10000);}
  pollUpdates();
}

function showReleaseNotes(release){
  let dialog=document.getElementById('releaseNotesDialog');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='releaseNotesDialog';dialog.innerHTML='<header><strong></strong><button type="button" aria-label="Cerrar">×</button></header><div class="release-notes-content"></div><p></p>';document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});}
  dialog.querySelector('strong').textContent=uiText('Notas de versión')+' · '+release.tag;
  const notes=release.notes||'Las notas de esta versión todavía no están en la caché. Pulsa «Comprobar actualizaciones» para obtenerlas.';
  dialog.querySelector('.release-notes-content').innerHTML=mdHTML(notes.replace(/<\/?(?:details|summary)\b[^>]*>/gi,'').replace(/\n{3,}/g,'\n\n').replace(/<(https?:\/\/[^<>\s]+)>/g,'[$1]($1)'));
  dialog.querySelector('p').textContent=release.url||'';
  dialog.showModal();
}
function paintDownloadProgress(progress){
  let box=document.getElementById('engineDownloadProgress');
  if(!box){box=document.createElement('div');box.id='engineDownloadProgress';box.setAttribute('role','status');box.innerHTML='<label></label><progress max="100"></progress>';document.getElementById('engineUpdateStatus').after(box);}
  box.hidden=!progress;if(!progress)return;
  const percent=progress.total?Math.min(100,progress.received/progress.total*100):0;
  box.querySelector('label').textContent=progress.engine+' · '+({download:'Descargando',extract:'Extrayendo',verify:'Verificando',complete:'Completado',error:'Error'}[progress.phase]||'')+' · '+percent.toFixed(1)+' % · '+(progress.received/1048576).toFixed(1)+' / '+(progress.total/1048576).toFixed(1)+' MB';
  box.querySelector('progress').value=percent;
}
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
  document.getElementById('marketRefresh').onclick=async()=>{try{await action({action:'refresh'});await load();}catch(error){status(error.message);}};
  document.getElementById('addCustomMCP').onclick=async()=>{try{await action({action:'register',manifest:JSON.parse(document.getElementById('customMCPJson').value)});await load();status(uiText('Añadido y desactivado. Actívalo cuando lo necesites.'));}catch(error){status(error.message);}};
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
  for(const element of document.querySelectorAll('.topbar,.topbar .breadcrumb,.topbar .spacer,#sidebar .sidebar-chrome'))element.setAttribute('data-tauri-drag-region','');
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
  const scan=()=>document.querySelectorAll(groups).forEach(attach);
  scan();new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});
  // A group measured while its window was closed has no pill once the window opens; catch up any
  // visible group whose pill is hidden or out of step (reads only; writes on mismatch).
  setInterval(()=>{for(const group of document.querySelectorAll('[data-segmented]')){
    if(!group.offsetWidth)continue;const pill=group.querySelector(':scope>.seg-pill');
    const active=[...group.children].find(el=>el.tagName==='BUTTON'&&(el.getAttribute('aria-pressed')==='true'||el.getAttribute('aria-selected')==='true'));
    if(pill&&active&&active.offsetWidth&&(pill.style.opacity!=='1'||pill.style.width!==active.offsetWidth+'px'||pill.style.transform!=='translate('+active.offsetLeft+'px,'+active.offsetTop+'px)'))place(group);
  }},600);
}
setupSegmentedSliders();
