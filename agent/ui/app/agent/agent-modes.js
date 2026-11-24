

const AGENT_MODES={
  text:{name:'Chat',short:'Chat',desc:'Conversación con búsqueda web opcional (botón del mundo). Sin carpeta de trabajo, permisos ni otras herramientas.'},
  light:{name:'Agente ligero',short:'Ligero',desc:'Herramientas esenciales y comandos con aprobación. El acceso y las aprobaciones se eligen por separado.'},
  balanced:{name:'Agente estándar',short:'Estándar',desc:'Herramientas de archivos, web, consola y Hugging Face seleccionadas. El acceso y las aprobaciones se eligen por separado.'},
  advanced:{name:'Agente completo',short:'Completo',desc:'Herramientas adicionales de escritorio y administrador cuando se activan. El acceso y las aprobaciones se eligen por separado.'}
};
const AGENT_MODE_ORDER=['text','light','balanced','advanced'];
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
  // Chat mode works with no folder, no access level and no tools but web search: those controls are locked
  // (and their menus closed) so the globe button is the only switch left, with the reason in their title.
  const chat=key==='text';
  for(const id of ['openToolsMenu','openProjectMenu']){const item=document.getElementById(id);if(item){item.disabled=chat;item.classList.toggle('locked-by-mode',chat);}}
  for(const id of ['projectBtn','scopeBtn','mcpBtn']){
    const control=document.getElementById(id);if(!control)continue;
    control.disabled=chat;control.classList.toggle('locked-by-mode',chat);
    if(chat){if(!control.dataset.modeTitle)control.dataset.savedTitle=control.title||'';control.dataset.modeTitle='1';control.title=uiText('Modo Chat: sin carpeta de trabajo, permisos ni otras herramientas.');control.setAttribute('aria-disabled','true');}
    else if(control.dataset.modeTitle){control.title=control.dataset.savedTitle||'';delete control.dataset.modeTitle;delete control.dataset.savedTitle;control.removeAttribute('aria-disabled');}
  }
  if(chat){
    for(const id of ['permissionMenu']){const menu=document.getElementById(id);if(menu?.matches?.(':popover-open'))window.VALMotion?.hidePopover(menu);}
    if(document.getElementById('scopeBtn')?.getAttribute('aria-expanded')==='true'||document.getElementById('mcpBtn')?.getAttribute('aria-expanded')==='true')window.closeChatControls?.(false,true);
  }
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
  if(typeof updateControls==='function')updateControls();   // shell/console switches follow the new mode at once
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
  syncAgentModeSeat();window.VALSegmented?.scan();   // drawn with its chosen mode and pill from the first frame
  const tip=document.createElement('div');tip.id='agentModeTooltip';tip.setAttribute('role','tooltip');tip.setAttribute('popover','manual');document.body.append(tip);
  let tipAnchor=null;
  const dismissTip=()=>{if(tipAnchor){tipAnchor.removeAttribute('aria-describedby');tipAnchor=null;}if(tip.matches(':popover-open')){if(window.VALMotion)window.VALMotion.hidePopover(tip,()=>{},true);else tip.hidePopover();}};
  const showTip=(anchor,text,{compact=false,center=false}={})=>{
    tipAnchor=anchor;tip.dataset.compact=compact?'true':'false';tip.textContent=text;
    anchor.setAttribute('aria-describedby',tip.id);if(window.VALMotion)window.VALMotion.showPopover(tip);else tip.showPopover();
    const r=anchor.getBoundingClientRect();
    const desiredLeft=center?(r.left+r.width/2-tip.offsetWidth/2):r.left;
    tip.style.left=Math.max(10,Math.min(innerWidth-tip.offsetWidth-10,desiredLeft))+'px';
    const aboveTop=r.top-tip.offsetHeight-(compact?8:10);
    const top=aboveTop>=10?aboveTop:Math.min(innerHeight-tip.offsetHeight-10,r.bottom+(compact?8:10));
    tip.style.top=Math.max(10,top)+'px';
  };
  for(const option of segments.children){option.addEventListener('pointerenter',()=>showTip(option,uiText(option.dataset.modeDescription)));option.addEventListener('focus',()=>showTip(option,uiText(option.dataset.modeDescription)));option.addEventListener('pointerleave',dismissTip);option.addEventListener('blur',dismissTip);option.addEventListener('click',dismissTip);}
  const searchBtn=document.getElementById('searchToggle');
  if(searchBtn&&!searchBtn.dataset.tipBound){
    searchBtn.dataset.tipBound='1';
    const showSearchTip=()=>showTip(searchBtn,'WebSearch/WebVisit',{compact:true,center:true});
    searchBtn.addEventListener('pointerenter',showSearchTip);searchBtn.addEventListener('focus',showSearchTip);searchBtn.addEventListener('pointerleave',dismissTip);searchBtn.addEventListener('blur',dismissTip);
  }
  // Every icon-only button says what it does on hover or keyboard focus (its translated name), like the mode buttons.
  const iconOnly=target=>{const b=target?.closest?.('button');return b&&!b.dataset.tipBound&&!b.closest('#agentModeSegments')&&!b.title&&b.getAttribute('aria-label')&&!b.innerText.trim()?b:null;};
  document.addEventListener('pointerover',event=>{const b=iconOnly(event.target);if(!b||b===tipAnchor)return;showTip(b,uiText(b.getAttribute('aria-label')),{compact:true,center:true});b.addEventListener('pointerleave',dismissTip,{once:true});});
  document.addEventListener('focusin',event=>{const b=iconOnly(event.target);if(b&&b.matches(':focus-visible')){showTip(b,uiText(b.getAttribute('aria-label')),{compact:true,center:true});b.addEventListener('blur',dismissTip,{once:true});}});
  addEventListener('resize',dismissTip);document.addEventListener('scroll',dismissTip,true);document.addEventListener('pointerdown',e=>{if(!e.target.closest?.('#searchToggle,#agentModeSegments button'))dismissTip();});document.addEventListener('keydown',e=>{if(e.key==='Escape')dismissTip();});

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
