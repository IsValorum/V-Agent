
let drawerFocus=null,chatControlsFocus=null;
const CONTROL_LABELS={model:'Modelo y generación',response:'Modelo y generación',context:'Modelo y generación',tools:'Herramientas'};
function chatControlsOpen(pane){return pane==='tools'?!!window.VALWindows?.isOpen('tools'):!!window.VALWindows?.isOpen('model');}
function syncControlButtons(){
  for(const button of document.querySelectorAll('[data-controls]'))button.setAttribute('aria-expanded','false');
  if(window.VALWindows?.isOpen('model'))for(const button of document.querySelectorAll('[data-controls="model"],[data-controls="response"],[data-controls="context"]'))button.setAttribute('aria-expanded','true');
  if(window.VALWindows?.isOpen('tools'))for(const button of document.querySelectorAll('[data-controls="tools"]'))button.setAttribute('aria-expanded','true');
}
/** Legacy call sites keep working; floating windows stay open unless their own control closes them. */
function closeChatControls(){}
function setChatControls(pane,toggle=false){
  const requested=pane;
  if(pane==='response'||pane==='context')pane='model';
  if(!CONTROL_LABELS[pane])return;
  if(pane==='tools'){
    closeComposerMenu(false);
    if(toggle&&window.VALWindows?.isOpen('tools'))window.VALWindows.close('tools');
    else window.VALWindows?.open('tools');
    syncControlButtons();
    return;
  }
  restoreInspectorContent();
  // The technical tab is never the landing page; the context block is always visible above the tabs.
  setModelSection('generation');
  if(requested==='context')requestAnimationFrame(()=>(activeEngine==='api'?document.getElementById('remoteModelInfo'):document.getElementById('contextBlock'))?.scrollIntoView({block:'nearest'}));
  const origin=document.querySelector('[data-controls="'+requested+'"]');
  if(toggle&&window.VALWindows?.isOpen('model')&&chatControlsFocus===origin){window.VALWindows?.close('model');syncControlButtons();return;}
  chatControlsFocus=origin;hideHelp();
  if(activeEngine==='strata'&&loadedModel&&plantillaConsultada!==loadedModel&&!preparationState?.active)consultarPlantilla(loadedModel,false);
  $('#composerControlsTitle').textContent='Modelo y generación';
  window.VALWindows?.open('model');
  syncControlButtons();
  const field=$(({model:'#model',response:'#workProfile',context:'#ctxInput'})[requested]);
  (field&&!field.disabled?field:$('#closeControls')).focus({preventScroll:true});
  if(requested==='context')$('#controls-context')?.scrollIntoView({block:'start'});
}
function syncComposerLabels(){
  const select=$('#model'),name=modelNames[select.value]||select.selectedOptions[0]?.textContent||'Modelo';
  $('#modelBtnLabel').textContent=select.value?name:uiText('Modelo');
  const limited=preparationState?.model===loadedModel&&preparationState?.mode==='on_demand';
  const state=preparationState?.active||loadingModelId?'preparing':engineOnline===null||!modelStateKnown?'unknown':engineOnline===false?'off':!loadedModel?'empty':loadedModel===select.value?(limited?'limited':'ready'):'different';
  const modelButton=$('#modelBtn');modelButton.dataset.state=state;syncWelcomeHint();
  modelButton.setAttribute('aria-label',uiText('Modelo')+': '+name+'. '+uiText(({unknown:'Comprobando estado',off:'Motor apagado',empty:'Sin modelo cargado',ready:'Cargado y listo',limited:'Cargado con lectura bajo demanda',preparing:'Preparando modelo',different:'Hay otro modelo en memoria'})[state]));
  $('#responseBtnLabel').textContent=({none:'Sin razonar',low:'Rápido',medium:'Equilibrado',high:'Profundo'})[S.effort]||uiText('Respuesta');
  $('#responseBtn').setAttribute('aria-label',uiText('Configurar respuesta')+': '+$('#responseBtnLabel').textContent);
  syncAgentControls();
  $('#modelHint').textContent=state==='different'?uiText('Hay otro modelo cargado. Descárgalo antes de cambiar.'):state==='limited'?uiText('Pesos con lectura bajo demanda.'):'';
  syncModelSelectionSummary();
}
document.querySelectorAll('[data-controls]').forEach(button=>button.onclick=()=>{
  setChatControls(button.dataset.controls,button.id!=='scopeBtn'||chatControlsFocus===button);
});
$('#closeControls').onclick=()=>{window.VALWindows?.close('model');syncControlButtons();};
document.getElementById('drawer')?.addEventListener('fw:close',()=>{
  $('#gear').setAttribute('aria-expanded','false');document.body.classList.remove('appearance-open');
  restoreInspectorContent();cancelPendingEngineEdits();
  if(drawerFocus?.isConnected)drawerFocus.focus({preventScroll:true});
});
document.getElementById('composerControls')?.addEventListener('fw:close',syncControlButtons);
document.getElementById('toolsWindow')?.addEventListener('fw:close',syncControlButtons);

function setDrawer(open) {
  closeComposerMenu(false);hideHelp();
  if(open){drawerFocus=document.activeElement;window.VALWindows?.open('settings');document.body.classList.add('appearance-open');if($('#settingsNav'))selectSettingsCategory(settingsCategory);}
  else{window.VALWindows?.close('settings');document.body.classList.remove('appearance-open');drawerFocus?.isConnected&&drawerFocus.focus({preventScroll:true});}
  $('#gear').setAttribute('aria-expanded',String(open));
}
$('#gear').onclick=()=>setDrawer(!window.VALWindows?.isOpen('settings'));
$('#closeDrawer').onclick=()=>setDrawer(false);

function setSidebar(open) { document.body.classList.toggle("sidebar-open",open); $("#mobileMenu").setAttribute("aria-expanded",String(open)); }
$("#mobileMenu").onclick=()=>setSidebar(!document.body.classList.contains("sidebar-open")); $("#sidebarScrim").onclick=()=>setSidebar(false);
document.addEventListener("keydown",e=>{
  if(e.key==="Escape"&&!document.querySelector("dialog[open]")&&!document.querySelector(':popover-open')){
    if(window.VALWindows?.closeTop()){e.preventDefault();return;}
  }
  if(e.key==="Escape")setSidebar(false);
  if (e.ctrlKey && e.altKey && e.key.toLowerCase()==="n") { e.preventDefault(); newConv(); }
});
function resizeInput() { const el=$("#input"); el.style.height="auto"; el.style.height=Math.min(el.scrollHeight,190)+"px"; }
$("#input").addEventListener("input",resizeInput);
