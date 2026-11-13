/* ---------- ajustes ---------- */
function markCustomProfile() { queueModelPreferences(); S.profile="custom"; $("#workProfile").value="custom"; $("#profileNote").textContent="Tus valores personalizados."; }
function bindSampling(id, out, key, fmt) {
  const el = $("#p_" + id), o = $("#o_" + out);
  el.value = S.sampling[key];
  o.textContent = fmt ? fmt(el.value) : el.value;
  el.oninput = () => { S.sampling[key] = Number(el.value); markCustomProfile(); o.textContent = fmt ? fmt(el.value) : el.value; saveSettings(); };
}
bindSampling("temp", "temp", "temperature", (v) => Number(v).toFixed(2));
bindSampling("topp", "topp", "top_p", (v) => Number(v).toFixed(2));
bindSampling("topk", "topk", "top_k");
bindSampling("minp", "minp", "min_p", (v) => Number(v).toFixed(2));
bindSampling("rep", "rep", "repetition_penalty", (v) => Number(v).toFixed(2));
bindSampling("presence", "presence", "presence_penalty", v=>Number(v).toFixed(1));
bindSampling("frequency", "frequency", "frequency_penalty", v=>Number(v).toFixed(1));
$("#p_max").value = S.sampling.max_tokens;
$("#p_max").oninput = () => { S.sampling.max_tokens = Number($("#p_max").value) || 0; markCustomProfile(); saveSettings(); };
$("#p_seed").value = S.sampling.seed;
$("#p_seed").oninput = () => { S.sampling.seed = Number($("#p_seed").value) || 0; markCustomProfile(); saveSettings(); };
$("#effort").value = S.effort;
$("#effort").onchange = () => { S.effort = $("#effort").value; markCustomProfile(); saveSettings(); syncComposerLabels(); };

for (const k of Object.keys(DEF_FUNCS)) {
  const el = $("#f_" + k);
  el.checked = !!S.functions[k];
  el.onchange = () => { S.functions[k] = el.checked; if(k==='admin'&&!el.checked)requestJSON('/api/harness/admin/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(10000)}).catch(()=>{}); syncServerSwitches(); saveSettings(); };
}
function syncServerSwitches() {
  syncComposerMenu();
  $('#f_shell').checked=!!S.functions.shell&&(pcAccess.mode==='full_pc'||!!pcAccess.isolation?.available);
  $('#f_console').checked=pcAccess.mode==='full_pc'&&!!S.functions.console;
  updateToolCount();
  for(const [id,keys] of [['s_ddg',['search','visit']],['s_pc',pcAccess.mode==='full_pc'?['files','shell','sys']:['files','sys']]]) {
    const count=keys.filter(key=>S.functions[key]).length;$('#'+id).checked=count===keys.length;$('#'+id).indeterminate=count>0&&count<keys.length;
  }
}
$("#s_ddg").onchange = () => {
  S.functions.search = S.functions.visit = $("#s_ddg").checked;
  $("#f_search").checked = $("#f_visit").checked = $("#s_ddg").checked;
  syncServerSwitches();saveSettings();
};
$("#s_pc").onchange = () => {
  const on = $("#s_pc").checked;
  S.functions.files = S.functions.sys = on;S.functions.shell = on&&(pcAccess.mode==='full_pc'||!!pcAccess.isolation?.available);
  $("#f_files").checked = $("#f_sys").checked = on;$("#f_shell").checked=S.functions.shell;
  syncServerSwitches();saveSettings();
};
syncServerSwitches();
function syncModelPicker() { updateControls(); }
$("#model").onchange = () => { S.model = $("#model").value; syncContextSelection(); syncDraftSettings(); $("#modelStatus").textContent=""; syncModelPicker(); restoreModelPreferences(); saveSettings(); updateControls(); };
$("#refreshModels").onclick=async()=>{if(busy||engineBusy)return;if(activeEngine!=='api'){await loadModels();return;}setEngineBusy(true);try{engineSnapshot=await requestJSON('/api/harness/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(120000)});await loadModels();}catch(error){note(error.message);}finally{setEngineBusy(false);}};
function syncProfileControls() {
  for (const [id,key,digits] of [["temp","temperature",2],["topp","top_p",2],["topk","top_k",0],["minp","min_p",2],["rep","repetition_penalty",2],["presence","presence_penalty",1],["frequency","frequency_penalty",1]]) {
    $("#p_"+id).value=S.sampling[key]; $("#o_"+id).textContent=Number(S.sampling[key]).toFixed(digits);
  }
  $("#p_max").value=S.sampling.max_tokens;$("#p_seed").value=S.sampling.seed;$("#p_rounds").value=S.rounds;$("#effort").value=S.effort;
  $("#workProfile").value=S.profile;
  for(const k of Object.keys(DEF_FUNCS)) $("#f_"+k).checked=!!S.functions[k];
  syncServerSwitches();syncComposerLabels();
}
function applyWorkProfile(profile,changeTools=true) {
  S.profile=["code","agent","research","custom"].includes(profile)?profile:"code";
  if(S.profile!=="custom") {
    const entry=(modelProfiles[$("#model").value] || baseProfiles)[S.profile];
    if(entry){ S.sampling={...DEF_SAMPLING,...entry.sampling};S.effort=entry.effort;S.rounds=entry.rounds; }
  }
  $("#profileNote").textContent=S.profile==="custom"?"Tus valores personalizados.":"Perfil adaptado al modelo. Puedes ajustar cualquier valor; las herramientas del equipo se controlan por separado.";
  syncProfileControls();saveSettings();
}
$("#workProfile").onchange=()=>{applyWorkProfile($("#workProfile").value,true);queueModelPreferences();};
$("#p_rounds").value=S.rounds;
$("#p_rounds").onchange=()=>{S.rounds=Math.min(100,Math.max(2,Number($("#p_rounds").value)||50));markCustomProfile();saveSettings();};
async function pollMCP() {
  const health = $('#mcpHealth');
  try {
    const selection=herramientasActivas(),profile=S.agentProfile||'balanced';const data = await requestJSON('/api/mcp?on=' + encodeURIComponent(selection)+'&agent_profile='+encodeURIComponent(profile));
    if(selection!==herramientasActivas()||profile!==(S.agentProfile||'balanced'))return;
    if (data.access && !accessChanging && (!S.pcAccessMode || data.access.mode === S.pcAccessMode)) {
      pcAccess = {...data.access,isolation:data.access.isolation||pcAccess.isolation};
      syncAccessControls();
    } else if (data.access?.isolation) {
      pcAccess.isolation = data.access.isolation;
    }
    health.replaceChildren(...(data.servers || []).map(server => {
      const row = document.createElement('div');
      row.className = 'mcp-server-row';
      row.dataset.state = server.error ? 'error' : server.status;
      const dot = document.createElement('span');
      dot.className = 'status-dot';
      dot.setAttribute('aria-hidden', 'true');
      const name = document.createElement('span');
      name.textContent = {pc: 'Equipo local', duckduckgo: 'Internet',hf:'Hugging Face'}[server.name] || server.name;
      const state = document.createElement('small');
      state.textContent = server.status === 'ready' ? 'Conectado · ' + (server.tools?.length || 0) + ' herramientas'
        : server.error ? 'Error' : 'Sin conexión';
      row.append(dot, name, state);
      if (server.error) {
        const details = document.createElement('p');
        details.textContent = server.error;
        row.append(details);
      }
      return row;
    }));
    if (!health.children.length) health.textContent = 'Sin servidores configurados.';
    if($('#connectionsCount'))$('#connectionsCount').textContent=(data.servers||[]).filter(server=>server.status==='ready').length+'/'+(data.servers||[]).length;
    if((data.servers||[]).some(server=>server.error)&&$('#mcpConnections'))$('#mcpConnections').open=true;
    pintarPresupuesto(data.presupuesto);
  } catch {
    health.textContent = 'No se pudo comprobar la conexión con los servidores.';
  }
}
$("#mcpReconnect").onclick=async()=>{if(busy||engineBusy)return;setEngineBusy(true);$("#mcpHealth").textContent="Reconectando…";try{await requestJSON("/api/mcp/reconnect",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});await pollMCP();}catch(e){$("#mcpHealth").textContent=e.message;}finally{setEngineBusy(false);}};
pollMCP();
function syncAccessControls(){
  $('#pcAccess').value=pcAccess.mode;
  syncWorkspacePath();
  $('#accessStatus').textContent=pcAccess.mode==='sandbox'?(pcAccess.isolation?.available?'Archivos en la carpeta de trabajo. CMD aislado disponible; sin red.':'Archivos en la carpeta de trabajo. Comandos aislados no disponibles.'):'Acceso a toda la PC habilitado.';
  $('#f_shell').checked=!!S.functions.shell&&(pcAccess.mode==='full_pc'||!!pcAccess.isolation?.available);
  $('#f_console').checked=pcAccess.mode==='full_pc'&&!!S.functions.console;
  updateControls();syncServerSwitches();
  $('#scopeLabel').textContent=uiText(pcAccess.mode==='full_pc'?'Toda la PC':'Sandbox')+' · '+uiText(S.permissionMode==='ask'?'Preguntar':S.permissionMode==='auto'?'Confirmar cambios':'Automático');
  $('#scopeBtn').dataset.scope=pcAccess.mode;
  $('#scopeBtn').setAttribute('aria-label','Acceso del agente: '+$('#scopeLabel').textContent+'. Cambiar acceso');
}
$('#pcAccess').onchange=async()=>{
  const mode=$('#pcAccess').value;if(busy||engineBusy||accessChanging){syncAccessControls();return;}
  accessChanging=true;updateControls();
  try{pcAccess=await requestJSON('/api/access',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});S.pcAccessMode=pcAccess.mode;saveSettings();}
  catch(error){note(error.message);}
  finally{accessChanging=false;syncAccessControls();pollMCP();}
};
syncAccessControls();
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')pollMCP();});

function updateToolCount() {
  // El numero tiene que ser el de verdad: el grupo "Archivos" son 6 (listar, leer, escribir,
  // editar por bloque, copiar/pegar por linea y comprobar en navegador). Si la cuenta no cuadra
  // con la linea de presupuesto de abajo, esta de mas y confunde.
  const CUENTA = {files:11, search:1, visit:1, sys:1, shell:pcAccess.mode==='full_pc'?5:1,hf:3,browser:1,console:1,web:2,autobrowser:16,computer:9,admin:4};
  const profile = S.agentProfile || 'balanced';
  $("#toolCount").textContent = Object.entries(S.functions).filter(([k,v]) =>
    k !== "date" && v &&
    (k!=='shell'||pcAccess.mode==='full_pc'||pcAccess.isolation?.available) &&
    (k!=='console'||pcAccess.mode==='full_pc') &&
    ((k!=='web'&&k!=='autobrowser')||profile!=='light') &&
    ((k!=='computer'&&k!=='admin')||(profile==='advanced'&&pcAccess.mode==='full_pc'))
  ).reduce((n,[k]) => n + (CUENTA[k]||1),0);
  consultarPresupuesto();
}
function herramientasActivas(){return Object.entries(S.functions).filter(([k,v])=>k!=='date'&&v&&(k!=='shell'||pcAccess.mode==='full_pc'||pcAccess.isolation?.available)&&(k!=='console'||pcAccess.mode==='full_pc')).map(([k])=>k).sort().join(',');}
async function consultarPresupuesto(){
  const activo=herramientasActivas(),profile=S.agentProfile||'balanced',signature=activo+'|'+profile+'|'+pcAccess.mode;
  if(signature===presupuestoFirmado){if(lastToolBudget&&typeof lastToolBudget.tools==='number')$('#toolCount').textContent=String(lastToolBudget.tools);return;}            // same set: no volver a medir por cada ajuste de muestreo
  presupuestoFirmado=signature;lastToolBudget=null;$('#mcpTokens').textContent=uiText(activo?'Calculando herramientas…':'Sin herramientas activas: no se inyecta bloque de tools.');
  clearTimeout(presupuestoTimer);presupuestoTimer=setTimeout(async()=>{
    try{const d=await requestJSON('/api/mcp?on='+encodeURIComponent(activo)+'&agent_profile='+encodeURIComponent(profile),{cache:'no-store',signal:AbortSignal.timeout(60000)});if(activo===herramientasActivas()&&profile===(S.agentProfile||'balanced'))pintarPresupuesto(d.presupuesto);}catch{}},500);
}
function pintarPresupuesto(p){
  lastToolBudget=p;
  const el=$('#mcpTokens');if(!el)return;
  if(!p||p.error){el.textContent=p&&p.error?('No se pudo medir el coste de las herramientas: '+p.error):'';el.dataset.bad=p&&p.error?'1':'';return;}
  const total=p.tools||0;$('#toolCount').textContent=String(total);const tokens=p.token_despues||p.token_antes||0,limite=p.limite||1000;
  if(!total){el.textContent='Sin herramientas activas: no se inyecta bloque de tools.';el.dataset.bad='';return;}
  const partes=[`${total} ${uiText(total===1?'Herramienta':'herramientas').toLocaleLowerCase()} · ${formatTokens(tokens)} / ${formatTokens(limite)} tokens${p.aproximado?' ('+uiText('estimado')+')':''}`];
  if(p.nivel)partes.push(uiText('Nivel')+' '+p.nivel);
  if((p.fuera||[]).length)partes.push(uiText('Sin enviar')+': '+p.fuera.join(', '));
  el.textContent=partes.join(' · ');
  el.title=`${limite} tokens es el objetivo del bloque de herramientas; se conservan sus funciones e instrucciones esenciales. ${p.recortes||''}`;
  // The limit is a soft target (tools are compacted, never removed), so only tools that were
  // actually left out deserve the warning colour.
  el.dataset.bad=(p.fuera||[]).length?'1':'';
}
function themeUnit(key) {return ['alpha','composerAlpha','drawerAlpha','outsideOpacity','textShadow','responseOpacity','strength','grain','border','shadow','lineHeight'].includes(key)?'%':key==='angle'?'°':'px';}
function applyComposerLayout(){
  const layout=TH.composerLayout;
  for(const side of ['left','right']){
    const group=$(side==='left'?'#composerLeft':'#composerRight');
    layout[side].forEach((id,index)=>{const button=$('#'+id);if(button&&group.children[index]!==button)group.insertBefore(button,group.children[index]||null);});
  }
  if($('#searchToggle'))$('#mcpBtn').before($('#searchToggle'));
  $('#chatwrap').dataset.raised=String(layout.emptyRaised);
  $('#emptyComposerRaised').checked=layout.emptyRaised;
  renderComposerEditor();
}
function changeComposerControl(id,side,before=null){
  if(busy||engineBusy||!COMPOSER_IDS.includes(id)||!['left','right'].includes(side)||id===before)return;
  const next=structuredClone(TH.composerLayout);
  for(const key of ['left','right'])next[key]=next[key].filter(value=>value!==id);
  const index=before?next[side].indexOf(before):-1;
  next[side].splice(index<0?next[side].length:index,0,id);
  TH.composerLayout=next;applyTheme();
}
function renderComposerEditor(){
  const editor=$('#composerLayoutEditor'),layout=TH.composerLayout,signature=JSON.stringify(layout)+'|'+busy+'|'+engineBusy;
  if(editor.dataset.signature===signature)return;
  editor.dataset.signature=signature;editor.replaceChildren();
  for(const side of ['left','right']){
    const title=document.createElement('div');title.className='layout-divider';title.textContent=side==='left'?'Izquierda':'Derecha';editor.append(title);
    layout[side].forEach((id,index)=>{
      const row=document.createElement('div');row.className='layout-item';row.dataset.control=id;
      const name=document.createElement('span');name.className='layout-label';name.textContent=COMPOSER_LABELS[id];
      const select=document.createElement('select');select.setAttribute('aria-label','Lado de '+COMPOSER_LABELS[id]);select.add(new Option('Izquierda','left'));select.add(new Option('Derecha','right'));select.value=side;
      select.disabled=busy||engineBusy;select.onchange=()=>{changeComposerControl(id,select.value);editor.querySelector('[data-control="'+id+'"] select')?.focus({preventScroll:true});};row.append(name,select);
      for(const [symbol,label,delta] of [['↑','Subir',-1],['↓','Bajar',1]]){
        const button=document.createElement('button');button.type='button';button.textContent=symbol;button.setAttribute('aria-label',label+' '+COMPOSER_LABELS[id]);button.disabled=busy||engineBusy||(delta<0?index===0:index===layout[side].length-1);
        button.onclick=()=>{const before=layout[side][index+(delta<0?-1:2)]||null;changeComposerControl(id,side,before);editor.querySelector('[data-control="'+id+'"] button[aria-label="'+label+' '+COMPOSER_LABELS[id]+'"]')?.focus({preventScroll:true});};row.append(button);
      }
      editor.append(row);
    });
  }
}
function finishComposerDrag(){draggingControl=null;$('.composer-tools').classList.remove('dragging');document.querySelectorAll('.drag-target').forEach(node=>node.classList.remove('drag-target'));}
for(const id of COMPOSER_IDS){
  const button=$('#'+id);button.draggable=true;
  button.addEventListener('dragstart',event=>{if(busy||engineBusy){event.preventDefault();return;}draggingControl=id;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',id);$('.composer-tools').classList.add('dragging');});
  button.addEventListener('dragend',finishComposerDrag);
}
for(const group of document.querySelectorAll('[data-composer-side]')){
  group.addEventListener('dragover',event=>{if(!draggingControl)return;event.preventDefault();event.dataTransfer.dropEffect='move';document.querySelectorAll('.drag-target').forEach(node=>node.classList.remove('drag-target'));event.target.closest('button')?.classList.add('drag-target');});
  group.addEventListener('drop',event=>{if(!draggingControl)return;event.preventDefault();const target=event.target.closest('button'),id=draggingControl;let before=null;if(target&&target.id!==id){const box=target.getBoundingClientRect();before=event.clientX<box.x+box.width/2?target.id:target.nextElementSibling?.id||null;}if(!target||target.id!==id)changeComposerControl(id,group.dataset.composerSide,before);finishComposerDrag();});
}
$('#emptyComposerRaised').onchange=()=>{TH.composerLayout={...TH.composerLayout,emptyRaised:$('#emptyComposerRaised').checked};applyTheme();};
$('#resetComposerLayout').onclick=()=>{TH.composerLayout=structuredClone(DEFAULT_COMPOSER);applyTheme();};
function syncThemeControls() {
  const p=TH[TH.mode];
  for(const key of [...THEME_COLORS,...Object.keys(THEME_RANGES),...Object.keys(THEME_ENUMS)]) {
    $('#t_'+key).value=p[key];const out=$('#o_'+key);if(out)out.textContent=p[key]+themeUnit(key);
  }
  $('#workspaceName').value=TH.name;
  const flat=p.gradient==='none';
  for(const key of ['g1','g2','g3','strength','backgroundBlur'])$('#t_'+key).disabled=flat;
  $('#t_angle').disabled=flat||p.gradient==='radial';
}
for(const key of [...THEME_COLORS,...Object.keys(THEME_RANGES)]) {
  $('#t_'+key).oninput=()=>{const el=$('#t_'+key);TH[TH.mode][key]=THEME_COLORS.includes(key)?el.value:Number(el.value);applyTheme();const o=$('#o_'+key);if(o)o.textContent=el.value+themeUnit(key);};
}
for(const key of Object.keys(THEME_ENUMS))$('#t_'+key).onchange=()=>{TH[TH.mode][key]=$('#t_'+key).value;applyTheme();syncThemeControls();};
$('#t_solidResponses').onchange=()=>{localStorage.setItem('valSolidResponses',$('#t_solidResponses').checked?'1':'0');applyTheme();};
$('#workspaceName').oninput=()=>{TH.name=$('#workspaceName').value.trim().slice(0,32)||'V-Agent';applyTheme();};
function setMode(mode){TH.mode=mode;applyTheme();syncThemeControls();}
$('#themeBtn').onclick=()=>setMode(TH.mode==='night'?'day':'night');
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$('#resetTheme').onclick=()=>{TH[TH.mode]={...DEF_THEME[TH.mode]};applyTheme();syncThemeControls();};
$('#exportTheme').onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify({type:'strata-theme',version:2,theme:TH},null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='V-Agent-tema.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('#importTheme').onclick=()=>$('#themeFile').click();
$('#themeFile').onchange=async e=>{
  try {const file=e.target.files[0];if(!file)return;if(file.size>100000)throw new Error('El archivo es demasiado grande.');const data=JSON.parse(await file.text()),candidate=data.theme||data;
    if(!candidate||typeof candidate!=='object'||!candidate.night||!candidate.day)throw new Error('No es un tema de V-Agent.');
    TH=normalizeTheme(candidate);applyTheme();syncThemeControls();note('Tema importado.');
  }catch(error){note('No se pudo importar: '+error.message);}finally{e.target.value='';}
};
syncThemeControls();


/* ---------- panel ---------- */

let modelVision={},visionDirty=false,projectRequest=0;
function setupVisionSettings(container){
  const section=document.createElement('details');section.id='visionSettings';
  section.innerHTML='<summary>Visión · mmproj</summary><label class="chk"><input type="checkbox" id="visionEnabled"> Activar al cargar el modelo</label><div class="vision-path"><input id="visionPath" type="text" placeholder="Proyector mmproj.gguf" aria-label="Archivo mmproj"><button id="browseVision" type="button">Elegir…</button></div><details><summary>Codificador</summary><div class="vision-path"><input id="visionEncoder" type="text" aria-label="Codificador strata-vision"><button id="browseEncoder" type="button">Elegir…</button></div></details><p id="visionStatus" role="status"></p><button id="saveVision" type="button">Guardar para próxima carga</button>';
  container.append(section);
  HELP.visionConfig=['Visión y mmproj','El mmproj convierte imágenes para el modelo y debe ser compatible con él. Se guarda por modelo. Activarlo se aplica en la próxima carga manual; elegir un archivo no carga nada. El codificador trabaja en CPU cuando adjuntas una imagen.'];
  const help=helpButton('visionConfig');section.querySelector('summary').append(help);help.onclick=event=>{event.preventDefault();event.stopPropagation();if(helpPinned&&helpAnchor===help)hideHelp();else showHelp(help,true);};
  for(const id of ['visionEnabled','visionPath','visionEncoder'])$('#'+id).addEventListener('input',()=>visionDirty=true);
  for(const [button,kind,input] of [['browseVision','mmproj','visionPath'],['browseEncoder','encoder','visionEncoder']])$('#'+button).onclick=async()=>{
    const model=$('#model').value;$('#'+button).disabled=true;
    try{const result=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind}),signal:AbortSignal.timeout(310000)});if(result.path&&model===$('#model').value){$('#'+input).value=result.path;visionDirty=true;}}
    catch(error){$('#visionStatus').textContent=error.message;}finally{$('#'+button).disabled=false;}
  };
  $('#saveVision').onclick=async()=>{
    if(busy||engineBusy)return;const model=$('#model').value;$('#saveVision').disabled=true;
    try{const result=await requestJSON('/api/models/vision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model,enabled:$('#visionEnabled').checked,mmproj:$('#visionPath').value,encoder:$('#visionEncoder').value})});modelVision[model]=result.vision;visionDirty=false;syncVisionSettings();$('#visionStatus').textContent='Guardado por modelo. Se aplicará en la próxima carga manual.';}
    catch(error){$('#visionStatus').textContent=error.message;}finally{$('#saveVision').disabled=false;}
  };
}
function syncVisionSettings(){
  if(!$('#visionSettings'))return;
  const model=$('#model').value,section=$('#visionSettings');
  if(section.dataset.model!==model){visionDirty=false;section.dataset.model=model;}
  if(visionDirty)return;
  const v=modelVision[model]||{};
  $('#visionEnabled').checked=!!v.enabled;$('#visionPath').value=v.mmproj||'';$('#visionEncoder').value=v.encoder||'';
  $('#visionEnabled').disabled=!v.supported;$('#saveVision').disabled=busy||engineBusy||!model;
  $('#visionStatus').textContent=!v.supported?'Visión no verificada para esta arquitectura.':!v.encoder_available?'Falta strata-vision. Puedes guardar el mmproj y seleccionar el codificador cuando lo instales.':'Usa un mmproj compatible con este modelo. Codificación en CPU, bajo demanda; elegir archivos no carga nada.';
}
async function syncProjectButton(){
  const request=++projectRequest,chat=currentId;
  try{
    const data=await requestJSON('/api/projects'+(chat?'?conversation_id='+encodeURIComponent(chat):''));
    if(request!==projectRequest||chat!==currentId)return;
    const project=data.projects.find(item=>item.id===data.selected);selectedProject=project||null;selectedProjectChat=chat;syncWorkspacePath();
    if(chat){const before=projectAssignments[chat]||null,now=project?.id||null;projectAssignments[chat]=now;projectNames=Object.fromEntries((data.projects||[]).map(item=>[item.id,item]));if(before!==now)renderConvs();}
    $('#projectBtn span').textContent=project?.name||uiText('Sin proyecto');$('#projectBtn').dataset.selected=String(!!project);
    $('#projectBtn').title=project?project.path:uiText('Carpeta independiente de esta conversación');
    if(pcAccess.mode==='sandbox')$('#accessStatus').textContent=pcAccess.isolation?.available?uiText('Archivos en la carpeta de trabajo. CMD aislado disponible; sin red.'):uiText('Archivos en la carpeta de trabajo. Comandos aislados no disponibles.');
    return data;
  }catch(error){if(request===projectRequest)$('#projectBtn').title=error.message;}
}
function setupProjectControl(){
  const dialog=document.createElement('section');dialog.id='projectDialog';dialog.hidden=true;dialog.setAttribute('role','dialog');
  dialog.innerHTML='<div class="fw-head"><h2>Proyecto</h2><button id="closeProject" class="icon-btn" type="button" data-fw-close aria-label="Cerrar">×</button></div><div class="fw-body"><div id="projectList" class="project-list"></div><div class="project-path"><input id="projectPath" type="text" placeholder="Carpeta del proyecto" aria-label="Ruta del proyecto"><button id="browseProject" type="button">Elegir carpeta…</button></div><p class="mini" id="projectStatus" role="status">Los MCP usarán esta carpeta. Los comandos siguen requiriendo Acceso completo.</p><button id="useProjectPath" type="button">Usar carpeta</button></div>';
  document.body.append(dialog);window.VALWindows?.register('project',dialog);
  const closeProject=()=>window.VALWindows?.close('project');
  const choose=async value=>{
    if(busy||engineBusy)return;
    $('#projectStatus').textContent='Guardando…';
    const previousId=currentId;
    if(!currentId){currentId=crypto.randomUUID();convs.push({id:currentId,title:'Nuevo chat',ts:Date.now(),messages:[]});}
    try{
      await requestJSON('/api/projects/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:currentId,...value})});
      saveConvsLS();renderConvs();await syncProjectButton();closeProject();
    }catch(error){if(!previousId){convs=convs.filter(c=>c.id!==currentId);currentId=null;}$('#projectStatus').textContent=error.message;}
  };
  $('#projectBtn').onclick=async()=>{
    if(busy||engineBusy){note('Detén la generación antes de cambiar de proyecto.');return;}
    const data=await syncProjectButton();if(!data)return;
    closeComposerMenu(false);$('#projectList').replaceChildren();
    for(const item of [{id:null,name:'Sin proyecto',path:'Carpeta independiente para este chat'},...data.projects]){
      const button=document.createElement('button');button.className='project-item';button.type='button';button.setAttribute('aria-pressed',String((data.selected||null)===item.id));
      const name=document.createElement('span'),path=document.createElement('small');name.textContent=item.name;path.textContent=item.path;button.append(name,path);button.onclick=()=>choose({project_id:item.id});
      const row=document.createElement('div');row.className='project-item-row';row.append(button);
      if(item.id){const remove=document.createElement('button');remove.type='button';remove.className='project-remove';remove.textContent=uiText('Quitar');remove.setAttribute('aria-label',uiText('Quitar proyecto'));remove.onclick=()=>removeProject(item);row.append(remove);}
      $('#projectList').append(row);
    }
    $('#projectStatus').textContent='Los MCP usarán esta carpeta. Los comandos siguen requiriendo Acceso completo.';window.VALWindows?.open('project');
  };
  $('#closeProject').onclick=closeProject;
  window.__chooseProject=choose;
  const addProject=document.getElementById('addProject');
  if(addProject)addProject.onclick=async()=>{
    if(busy||engineBusy){note(uiText('Detén la generación antes de cambiar de proyecto.'));return;}
    addProject.disabled=true;
    try{
      const picked=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'project'}),signal:AbortSignal.timeout(310000)});
      if(!picked.path)return;
      const data=await requestJSON('/api/projects/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:picked.path})});
      projectAssignments=data.conversations||{};projectNames=Object.fromEntries((data.projects||[]).map(item=>[item.id,item]));
      renderConvs();const entry=document.querySelector('#projectsNav details[data-project="'+data.added.id+'"]');if(entry)entry.open=true;
      note(uiText('Proyecto añadido.'));
    }catch(error){note(error.message);}finally{addProject.disabled=false;}
  };
  $('#useProjectPath').onclick=()=>{if($('#projectPath').value.trim())choose({path:$('#projectPath').value.trim()});};
  $('#browseProject').onclick=async()=>{
    $('#browseProject').disabled=true;
    try{const result=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'project'}),signal:AbortSignal.timeout(310000)});if(result.path){$('#projectPath').value=result.path;await choose({path:result.path});}}
    catch(error){$('#projectStatus').textContent=error.message;}finally{$('#browseProject').disabled=false;}
  };
}
