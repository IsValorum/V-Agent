

function currentThinking(){return modelCatalog?.find(m=>m.id===$('#model').value)?.thinking||{mode:'fixed',choices:[],default:'default'};}
// Spanish base phrases go through uiText like the rest of the interface.
const THINK_LABELS=new Proxy({none:'Sin pensar',think:'Pensar',minimal:'Mínimo',low:'Bajo',medium:'Medio',high:'Alto',xhigh:'Máximo',max:'Máximo',default:'Auto'},{get:(labels,key)=>typeof key==='string'&&labels[key]?uiText(labels[key]):undefined});
function syncAgentControls(){
  if(!$('#thinkingMenu'))return;
  $('#scopeLabel').textContent=uiText(pcAccess.mode==='full_pc'?'Toda la PC':'Sandbox')+' · '+uiText(S.permissionMode==='ask'?'Preguntar':S.permissionMode==='auto'?'Confirmar cambios':'Automático');
  const info=currentThinking();if(!info.choices.includes(S.effort))S.effort=info.default;
  $('#responseBtnLabel').textContent=THINK_LABELS[S.effort]||'Think';$('#responseBtn').setAttribute('aria-label',uiText('Pensamiento')+': '+$('#responseBtnLabel').textContent);$('#responseBtn').disabled=busy||!info.choices.length;
  const signature=JSON.stringify(info.choices);if($('#effort').dataset.choices!==signature){$('#effort').replaceChildren(...(info.choices.length?info.choices:['default']).map(value=>{const option=document.createElement('option');option.value=value;option.textContent=THINK_LABELS[value];return option;}));$('#effort').dataset.choices=signature;}$('#effort').value=S.effort;
  $('#searchToggle').setAttribute('aria-pressed',String(!!S.functions.search));$('#searchToggle').disabled=busy||engineBusy;
  const menu=$('#thinkingMenu');if(menu.matches(':popover-open')){for(const button of menu.children)button.setAttribute('aria-checked',String(button.textContent===THINK_LABELS[S.effort]));return;}menu.replaceChildren(...info.choices.map(value=>{const button=document.createElement('button');button.type='button';button.textContent=THINK_LABELS[value];button.setAttribute('role','menuitemradio');button.setAttribute('aria-checked',String(value===S.effort));button.onclick=()=>{S.effort=value;$('#effort').value=value;markCustomProfile();saveSettings();syncComposerLabels();window.VALMotion.hidePopover(menu);};return button;}));
  $('#searchToggle').setAttribute('aria-pressed',String(!!S.functions.search));$('#searchToggle').disabled=busy||engineBusy;
  for(const id of ['f_web','f_autobrowser']){const box=document.getElementById(id);if(box)box.disabled=busy||engineBusy||S.agentProfile==='light'||S.agentProfile==='text';}
  for(const id of ['f_files','f_sys','f_browser','f_hf']){const box=document.getElementById(id);if(box)box.disabled=busy||engineBusy||S.agentProfile==='text';}
  for(const id of ['f_shell','f_console']){const box=document.getElementById(id);if(box&&S.agentProfile==='text')box.disabled=true;}
  for(const id of ['f_admin','f_computer']){const box=document.getElementById(id);if(box)box.disabled=busy||engineBusy||S.agentProfile!=='advanced'||pcAccess.mode!=='full_pc';}
  syncAgentModeSeat();
}
function showAgentMenu(menu,anchor){
  if(menu.matches(':popover-open')&&menu.dataset.motionClosing!=='true'){window.VALMotion.hidePopover(menu);return;}
  closeChatControls(false,true);for(const other of document.querySelectorAll('.agent-small-menu'))if(other!==menu&&other.matches(':popover-open'))window.VALMotion.hidePopover(other);window.VALMotion.showPopover(menu);anchor.setAttribute('aria-expanded','true');if(menu.id==='permissionMenu'){for(const button of menu.querySelectorAll('[data-mode]'))button.setAttribute('aria-checked',String(button.dataset.mode===(S.permissionMode||'ask')));for(const button of menu.querySelectorAll('[data-scope]'))button.setAttribute('aria-checked',String(button.dataset.scope===pcAccess.mode));}
  // Always open downwards; flip up only when the composer sits at the bottom edge and there is
  // no usable room below (under 220 px). The menu fits the window and scrolls inside.
  const rect=anchor.getBoundingClientRect();menu.style.maxHeight='';menu.dataset.side='below';
  const below=innerHeight-rect.bottom-14,above=rect.top-14,natural=menu.scrollHeight+menu.offsetHeight-menu.clientHeight+2;   // (+ its border and rounding: no scrollbar for a menu that fits)
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
  for(const [scope,label,detail] of [['sandbox','Sandbox','Solo el proyecto o la carpeta del chat.'],['full_pc','Toda la PC','Rutas accesibles con los permisos de tu usuario.']]){const button=document.createElement('button');button.type='button';button.dataset.scope=scope;button.setAttribute('role','menuitemradio');button.innerHTML='<strong></strong><small></small>';button.querySelector('strong').textContent=label;button.querySelector('small').textContent=detail;button.onclick=async()=>{if(refuseWhileBusy())return;$('#pcAccess').value=scope;await $('#pcAccess').onchange();syncAgentControls();for(const item of permission.querySelectorAll('[data-scope]'))item.setAttribute('aria-checked',String(item.dataset.scope===pcAccess.mode));};permission.append(button);}
  const openSandbox=document.createElement('button');openSandbox.type='button';openSandbox.id='permissionOpenSandbox';openSandbox.textContent=uiText('Abrir carpeta del Sandbox');openSandbox.onclick=()=>{window.VALMotion.hidePopover(permission);openConversationSandbox();};permission.append(openSandbox);
  const heading=document.createElement('div');heading.className='mini permission-heading';heading.textContent='Aprobaciones';permission.append(heading);
  const modes=[['ask','Preguntar siempre','Confirmar cada herramienta o acceso a Internet.'],['auto','Confirmar cambios','Lecturas automáticas; confirmar escrituras, ejecución y acciones desconocidas.'],['run','Automático','Ejecutar las herramientas activadas sin preguntar.']];
  for(const [mode,label,detail] of modes){const button=document.createElement('button');button.type='button';button.dataset.mode=mode;button.setAttribute('role','menuitemradio');button.innerHTML='<strong></strong><small></small>';button.querySelector('strong').textContent=label;button.querySelector('small').textContent=detail;button.onclick=()=>{if(refuseWhileBusy())return;S.permissionMode=mode;saveSettings();syncAgentControls();for(const item of permission.querySelectorAll('[data-mode]'))item.setAttribute('aria-checked',String(item.dataset.mode===mode));};permission.append(button);}
  const note=document.createElement('p');note.className='mini';note.textContent='El aislamiento de comandos se comprueba antes de usarse.';permission.append(note);window.VALI18n?.observe(permission);
  const scope=$('#scopeBtn');scope.removeAttribute('data-controls');scope.setAttribute('aria-controls','permissionMenu');scope.onclick=()=>showAgentMenu(permission,scope);
  const search=document.createElement('button');search.type='button';search.id='searchToggle';search.className='composer-control icon-only';search.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17.48 9.48A7.5 7.5 0 1 0 9.74 17.5"/><path d="M2.5 10h14.9"/><path d="M10 2.5c-2.8 3.2-2.8 11.8 0 15"/><path d="M10 2.5c1.7 1.8 2.4 4.8 2.3 8.2"/><circle cx="16" cy="15.5" r="4"/><path d="M18.9 18.4 22 21.5"/></svg>';search.setAttribute('aria-label','Internet: buscar y leer con DuckDuckGo');search.onclick=()=>{$('#s_ddg').checked=!S.functions.search;$('#s_ddg').onchange();syncAgentControls();};$('#mcpBtn').before(search);
  document.addEventListener('pointerdown',event=>{for(const id of ['thinkingMenu','permissionMenu']){const menu=$('#'+id);if(menu.matches(':popover-open')&&!event.target.closest('#'+id+',#responseBtn,#scopeBtn'))window.VALMotion.hidePopover(menu);}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')for(const id of ['thinkingMenu','permissionMenu'])if($('#'+id).matches(':popover-open'))window.VALMotion.hidePopover($('#'+id));});
}
// In-app replacement for window.confirm: follows the palette, translates, and keeps focus on the
// safe choice. Resolves true only when the user presses the confirm button.
function valConfirm({title,message='',confirm='Aceptar',cancel='Cancelar',danger=false,input=null}={}){
  return new Promise(resolve=>{
    const dialog=document.createElement('dialog');dialog.className='val-confirm';
    const heading=document.createElement('h3');heading.textContent=uiText(title||'¿Continuar?');
    const body=document.createElement('p');body.textContent=uiText(message);body.hidden=!message;
    const actions=document.createElement('div');actions.className='val-confirm-actions';
    const no=document.createElement('button');no.type='button';no.className='soft-btn';no.textContent=uiText(cancel);
    const yes=document.createElement('button');yes.type='button';yes.className='soft-btn '+(danger?'danger':'primary');yes.textContent=uiText(confirm);
    let answered=false;const finish=value=>{if(answered)return;answered=true;resolve(value);dialog.close();dialog.remove();};
    // With `input`, the dialog asks for a line of text and resolves with it (false when cancelled or empty).
    let field=null;
    if(input){field=document.createElement('input');field.type='text';field.className='val-confirm-input';field.value=input.value||'';field.maxLength=input.maxLength||120;field.setAttribute('aria-label',uiText(input.label||title||''));
      field.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();yes.click();}});}
    no.onclick=()=>finish(false);yes.onclick=()=>finish(field?(field.value.trim()||false):true);
    dialog.addEventListener('cancel',event=>{event.preventDefault();finish(false);});
    dialog.addEventListener('click',event=>{if(event.target===dialog)finish(false);});
    actions.append(no,yes);dialog.append(heading,body,...(field?[field]:[]),actions);document.body.append(dialog);dialog.showModal();if(field){field.focus();field.select();}else no.focus();
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


// The agent asks something it cannot decide alone; the turn waits for this answer.
function showAgentQuestion(event){
  const dialog=document.createElement('dialog');dialog.className='tool-approval agent-question';
  const title=document.createElement('h3');title.textContent=uiText('El agente necesita tu respuesta');
  const question=document.createElement('p');question.className='agent-question-text';question.textContent=String(event.question||'');
  const options=document.createElement('div');options.className='agent-question-options';
  const field=document.createElement('textarea');field.className='agent-question-answer';field.rows=3;field.maxLength=4000;
  field.placeholder=uiText('Escribe tu respuesta…');field.setAttribute('aria-label',uiText('Tu respuesta'));
  const status=document.createElement('p');status.className='mini agent-question-status';status.setAttribute('role','status');
  const actions=document.createElement('div');
  let sent=false;
  const reply=async(answer,skip=false)=>{
    if(sent)return;if(!skip&&!String(answer||'').trim()){status.textContent=uiText('Escribe una respuesta o deja que decida el agente.');field.focus();return;}
    sent=true;for(const button of dialog.querySelectorAll('button'))button.disabled=true;
    try{await requestJSON('/api/harness/question',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:event.id,answer:skip?null:String(answer).trim(),skip})});dialog.close();dialog.remove();}
    catch(error){if(activeGeneration?.controller.signal.aborted){dialog.remove();return;}sent=false;for(const button of dialog.querySelectorAll('button'))button.disabled=false;status.textContent=error.message;}
  };
  for(const option of (Array.isArray(event.options)?event.options:[]).slice(0,4)){const button=document.createElement('button');button.type='button';button.className='soft-btn agent-question-option';button.textContent=String(option);button.onclick=()=>reply(String(option));options.append(button);}
  const decide=document.createElement('button');decide.type='button';decide.className='soft-btn';decide.textContent=uiText('Que decida el agente');decide.title=uiText('El agente seguirá con su mejor criterio y te dirá qué supuso.');decide.onclick=()=>reply(null,true);
  const send=document.createElement('button');send.type='button';send.className='soft-btn primary';send.textContent=uiText('Enviar respuesta');send.onclick=()=>reply(field.value);
  field.addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();reply(field.value);}});
  actions.append(decide,send);
  dialog.append(title,question,...(options.childElementCount?[options]:[]),field,status,actions);
  // Esc means "let the agent decide", never a silent stop of the turn.
  dialog.addEventListener('cancel',e=>{e.preventDefault();reply(null,true);});
  activeGeneration?.controller.signal.addEventListener('abort',()=>dialog.remove(),{once:true});
  document.body.append(dialog);dialog.showModal();window.VALI18n?.observe(dialog);(options.querySelector('button')||field).focus();
}
