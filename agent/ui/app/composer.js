/* ---------- adjuntos ---------- */
function renderAttachments() {
  const box = $("#attachments"); box.innerHTML = "";
  attachments.forEach((a, i) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.innerHTML = '<span></span><button>×</button>';
    c.querySelector("button").title = uiText("Quitar");
    c.querySelector("span").textContent = (a.image?"▧ ":"📄 ") + a.name;
    c.querySelector("button").onclick = () => { attachments.splice(i, 1); renderAttachments(); };
    box.appendChild(c);
  });
}
$("#attach").onclick = () => $("#file").click();
// One path for the + button, pasted files/screenshots and files dropped on the composer.
async function addFiles(files) {
  for (const f of files) {
    if (busy) break;
    if(/^image\/(png|jpeg|webp)$/.test(f.type)){
      try{
      if(f.size>2000000||attachments.filter(a=>a.image).length>=4){note('Máximo 4 imágenes de 2 MB.');continue;}
      const vision=await requestJSON('/api/vision/status');
      if(!vision.vision?.enabled||vision.model!==loadedModel){note(activeEngine==='api'?'Activa imágenes en la conexión API y selecciona un modelo compatible.':'Activa un mmproj compatible en Modelo y carga ese modelo antes de adjuntar imágenes.');continue;}
      const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(f);});
      attachments.push({name:f.name,image:data});
      }catch(error){note('No se pudo adjuntar la imagen: '+error.message);}
      continue;
    }
    if (f.size > 400000) { note("«" + f.name + "» " + uiText("es demasiado grande (máx. 400 KB).")); continue; }
    try {
      const content = await f.text();
      if (content.includes("\u0000") || ["image/", "audio/", "video/", "application/pdf"].some(t => f.type.startsWith(t))) {
        note("«" + f.name + "»: " + uiText("adjunta un archivo de texto, código, CSV o Markdown.")); continue;
      }
      attachments.push({ name: f.name, content });
    } catch { note(uiText("No se pudo leer") + " «" + f.name + "»."); }
  }
  renderAttachments();
}
$("#file").onchange = async (e) => { await addFiles([...e.target.files]); e.target.value = ""; };
// Ctrl+V of a screenshot or copied file attaches it; plain text keeps pasting as text.
$("#input").addEventListener("paste", event => {
  const files = [...(event.clipboardData?.files || [])];
  if (!files.length) return;
  event.preventDefault(); addFiles(files);
});
(function acceptDroppedFiles() {
  const box = $("#composerBox"); if (!box) return;
  const hasFiles = event => [...(event.dataTransfer?.types || [])].includes("Files");
  box.addEventListener("dragover", event => { if (!hasFiles(event)) return; event.preventDefault(); box.classList.add("drop-ready"); });
  box.addEventListener("dragleave", event => { if (!box.contains(event.relatedTarget)) box.classList.remove("drop-ready"); });
  box.addEventListener("drop", event => { box.classList.remove("drop-ready"); if (!hasFiles(event)) return; event.preventDefault(); addFiles([...event.dataTransfer.files]); });
})();

/* ---------- enviar ---------- */

let loadedModel=null,modelStateKnown=false,modelStateRevision=0,modelNames={};
function setLoadedModel(id,known=true,capacity=null){
  const changed=loadedModel!==(id||null)||modelStateKnown!==known;
  const previousCapacity=contextCapacity;
  if(changed || capacity!==null) contextCapacity=id?capacity:null;
  loadedModel=id||null;
  modelStateKnown=known;
  if(changed&&!engineBusy)$('#modelStatus').textContent='';
  $('#loadedTxt').textContent=known?(loadedModel?(modelNames[loadedModel]||loadedModel):uiText('Ninguno')):uiText('Comprobando…');
  if(loadedModel)window.hideModelPromptStrip?.();
  updateControls();
  syncContextMeter();
  // The model window then shows the context the engine really runs with.
  if((changed||contextCapacity!==previousCapacity)&&typeof syncContextSelection==='function')syncContextSelection();
}
// A local load still preparing (or one left over) never blocks a provider model: nothing is prepared for it.
// A local model in memory blocks engine/app updates; a provider (API) model is only a selection.
function localModelLoaded(){return !!loadedModel&&activeEngine!=='api';}
function localPreparing(){return !!preparationState?.active&&activeEngine!=='api';}
// A click that cannot act now says why (and returns true) instead of doing nothing.
function refuseWhileBusy(){const why=busy?'Espera a que termine la respuesta en curso o detenla.':engineBusy?'Espera a que termine la operación del motor.':'';if(why)note(why);return !!why;}
function modelIsReady(){return !localPreparing()&&modelStateKnown&&engineOnline===true&&loadedModel&&loadedModel===$('#model').value;}
function requireModelForChat(){if(modelIsReady())return true;if(!loadedModel&&$('#model')?.value&&typeof openModelPromptDialog==='function'){openModelPromptDialog();return false;}note(loadedModel?'Descarga el modelo en memoria y carga el seleccionado en Motor.':'Selecciona un modelo y pulsa Cargar modelo en Motor.');if(!document.querySelector('dialog[open]'))setChatControls('model');return false;}
function updateControls() {
  const blocked=engineBusy||accessChanging||draftSaving||localPreparing();
  if($('#kvCache'))$('#kvCache').disabled=busy||blocked||!(modelKV[$('#model').value]?.options?.length);
  for(const id of ['attach','file','model','effort','refreshModels','addModel','engineToggle','workProfile','p_rounds','mcpReconnect','pcAccess'])$('#'+id).disabled=busy||blocked||accessChanging;
  // Typing stays possible during a reply: Enter queues the message, Ctrl+Enter redirects the reply to it.
  $('#input').disabled=blocked||accessChanging;
  $('#draftSource').disabled=$('#draftBrowse').disabled=busy||blocked||!$('#model').value;
  $('#draftTokens').disabled=busy||blocked||!$('#draftSource').value;
  $('#draftReload').disabled=busy||blocked;
  $('#draftReload').hidden=!loadedModel||loadedModel!==$('#model').value;
  $('#ctxInput').disabled=$('#ctxApply').disabled=busy||blocked||accessChanging||!$('#model').value;
  // Moving the slider already saves it; the button is only needed to reload a loaded model with a new value.
  $('#ctxApply').hidden=!(loadedModel&&loadedModel===$('#model').value&&pendingModelContexts.has(loadedModel));
  $('#ctxApply').textContent=loadedModel===$('#model').value?uiText('Aplicar y recargar'):uiText('Guardar contexto');$('#ctxApply').title=loadedModel===$('#model').value?uiText('Recarga el modelo actual con el contexto elegido.'):uiText('Se aplicará en la próxima carga manual del modelo.');
  $('#f_shell').disabled=(pcAccess.mode!=='full_pc'&&!pcAccess.isolation?.available)||busy||blocked||accessChanging;
  $('#f_console').disabled=pcAccess.mode!=='full_pc'||busy||blocked||accessChanging;
  $('#resetComposerLayout').disabled=busy||blocked;renderComposerEditor();
  $('#send').disabled=blocked||!!activeGeneration?.stopped||(!busy&&!modelIsReady());
  $('#workProfile').disabled=busy||blocked||!profilesReady;
  $('#load').disabled=busy||blocked||!modelStateKnown||!$('#model').value||!!loadedModel;
  $('#load').title=loadedModel?uiText('Descarga primero el modelo en memoria.'):uiText('Cargar el modelo seleccionado');
  $('#unload').disabled=blocked||!modelStateKnown||!loadedModel||engineOnline===false;
  $('#unload').title=busy?uiText('Detener la respuesta y descargar el modelo'):uiText('Descargar el modelo y liberar su memoria');
  for(const id of ['engineToggle'])$('#'+id).disabled=busy||blocked||engineOnline===null;
  const compactBtn=$('#ctxCompact'),compactBox=$('#contextCompactBox');
  if(compactBox)compactBox.hidden=false;
  if(compactBtn)compactBtn.disabled=busy||blocked||accessChanging||!modelIsReady()||messages.length<2;
  syncComposerLabels();syncPreparationView();
  syncEngineCapabilities();if($('#modelFilter'))$('#modelFilter').disabled=busy||blocked||!modelCatalog.length;
}
function updatePreparation(state){
  if(state&&typeof state==='object'){
    if(loadingModelId&&state.model&&state.model!==loadingModelId)return;
    if(state.request_id&&state.request_id===preparationState?.request_id&&(state.revision||0)<(preparationState.revision||0))return;
    if(state.started_at&&preparationState?.started_at&&state.started_at<preparationState.started_at)return;
    preparationState=state;
  }
  updateControls();if(preparationState?.active)schedulePreparationPoll();
}
function syncPreparationView(){
  const active=!!preparationState?.active||!!loadingModelId,view=$('#modelPreparation');view.hidden=!active;if(!active)return;
  const state=preparationState,reading=state?.stage==='reading'&&!state.cancel_requested;
  const loadingName=state?.model?(modelNames[state.model]||String(state.model).split('--').pop()):'';
  $('#preparationLabel').title=loadingName;
  $('#preparationLabel').textContent=(loadingName&&!state?.cancel_requested?loadingName+' · ':'')+(state?.cancel_requested?uiText('Cancelando la carga…'):reading?uiText('Leyendo pesos')+' · '+Math.round(state.percent||0)+' %':state?.active?(state.message?uiText(state.message):uiText('Preparando modelo…')):state?.stage==='cancelled'?uiText('Carga cancelada.'):uiText('Preparando carga…'));
  const amount=[];
  if(state?.total_bytes&&reading)amount.push(((state.done_bytes||0)/2**30).toFixed(1)+' / '+(state.total_bytes/2**30).toFixed(1)+' GiB');
  if(state?.started_at)amount.push(Math.max(0,Math.floor(Date.now()/1000-state.started_at))+' s');
  $('#preparationAmount').textContent=amount.join(' · ');
  const progress=$('#preparationProgress');if(reading){progress.value=state.percent||0;progress.setAttribute('aria-valuetext',Math.round(state.percent||0)+' '+uiText('% de los pesos leídos'));}else{progress.removeAttribute('value');progress.setAttribute('aria-valuetext',uiText(state?.message||'Preparando motor'));}
  $('#cancelModelLoad').disabled=!state?.active||!state.request_id||!!state.cancel_requested;
  $('#cancelModelLoad').textContent=state?.cancel_requested?uiText('Cancelando…'):uiText('Cancelar carga');
}
async function cancelModelLoad(){
  const state=preparationState;if(!state?.active||!state.request_id||state.cancel_requested)return;
  $('#cancelModelLoad').disabled=true;
  try{
    const result=await requestJSON('/api/load/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:state.request_id}),signal:AbortSignal.timeout(5000)});
    updatePreparation(result);schedulePreparationPoll();
  }catch(error){note('No se pudo cancelar: '+error.message);await pollPreparation();}
}
$('#cancelModelLoad').onclick=cancelModelLoad;
function schedulePreparationPoll(){if(!preparationTimer&&!preparationPending)preparationTimer=setTimeout(pollPreparation,400);}
async function pollPreparation(){
  clearTimeout(preparationTimer);preparationTimer=null;if(preparationPending)return;preparationPending=true;
  try{const state=await requestJSON('/api/load/status',{cache:'no-store',signal:AbortSignal.timeout(4000)});updatePreparation(state);}catch{}finally{preparationPending=false;if(loadingModelId||preparationState?.active)schedulePreparationPoll();}
}

function setEngineState(online) {
  engineOnline = online;
  $("#engineStateTxt").textContent = online ? "Motor encendido" : "Motor apagado";
  for (const id of ["engineToggle"]) { $("#"+id).textContent = online ? "Apagar motor" : "Encender motor"; $("#"+id).dataset.online = String(!!online); }
  updateControls();
}
function setEngineBusy(value) { engineBusy=value; updateControls(); }
function setBusy(value) {
  busy = value; setFollow(followStream); if(value)closeChatControls(false); updateControls();
  $("#chat").setAttribute("aria-busy", String(value));
  if(!value)document.querySelectorAll('#chat [data-generating=true]').forEach(row=>{row.dataset.generating='false';});
  $("#chatwrap").dataset.generating = String(value);
  $("#modeNote").textContent = value ? uiText("Generando respuesta…") : "";
  $("#send").setAttribute("aria-label", uiText(value ? "Detener respuesta" : "Enviar mensaje"));
  $("#send").innerHTML=value?STOP_ICON:SEND_ICON;
  syncWelcomeHint();
}
const SEND_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>';
const STOP_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/></svg>';
let activeGeneration=null,activityTimer=0;
// What the turn is doing right now, above the composer: visible even when the user scrolled up to read.
function setGenerationPhase(generation,phase){if(generation.phase!==phase){generation.phase=phase;generation.phaseSince=Date.now();}}
function activityPhase(generation){
  const call=[...(generation.trace||[])].reverse().find(item=>['running','drafting','validating'].includes(item.status));
  if(call){
    const key=call.id||call;if(!generation.callSince.has(key))generation.callSince.set(key,Date.now());
    const args=call.args&&typeof call.args==='object'?call.args:{};
    const hint=String(args.path||args.url||args.query||args.command||'').split(/\r?\n/)[0].slice(0,60);
    return {text:(call.status==='drafting'?uiText('Redactando')+': ':'')+toolTitle(call)+(hint?' · '+hint:''),since:generation.callSince.get(key)};
  }
  const live=lastHardwareState?.live||{};
  if(live.state==='reading'&&!generation.phase){
    const total=Number(live.prompt_total),read=Number(live.prompt_read);
    return {text:uiText('Leyendo el prompt')+(total>0&&read>=0?' · '+Math.min(100,Math.floor(100*read/total))+' %':''),since:generation.phaseSince};
  }
  return {text:uiText(generation.phase==='writing'?'Escribiendo la respuesta':generation.phase==='thinking'?'Razonando':'Esperando al modelo'),since:generation.phaseSince};
}
function renderActivity(){
  const chip=$('#activityChip');if(!chip)return;
  const generation=activeGeneration;
  if(!generation){chip.hidden=true;clearInterval(activityTimer);activityTimer=0;return;}
  const phase=activityPhase(generation);chip.hidden=false;
  if($('#activityText').textContent!==phase.text)$('#activityText').textContent=phase.text;
  $('#activityTime').textContent=Math.max(0,Math.round((Date.now()-(phase.since||generation.startWall))/1000))+' s';
}
function startActivity(){if(!activityTimer)activityTimer=setInterval(renderActivity,500);renderActivity();}
function conversationForModel(history) {
  const result=[];
  history.forEach((message,messageIndex)=>{
    if(message.compacted){
      const label=message.compacted.method_label||message.compacted.method||'API';
      result.push({role:'user',content:'Compressed prior context ('+label+'):\n\n'+(message.content||'')});
      result.push({role:'assistant',content:'Understood. I will continue using this compressed context.'});
      return;
    }
    if(message.role==='assistant'){
      const groups=new Map();
      for(const [index,call] of (message.tool_trace||[]).entries()){
        if(!call.recovery&&(call.executed!==true||!Object.hasOwn(call,'result')))continue;
        const round=call.round??index;
        if(!groups.has(round))groups.set(round,[]);
        const file=call.recovery?fileFromDraft(call):null;
        const args=file?{path:file.filename,content:file.content}:call.args;
        if(!args||typeof args!=='object')continue;
        groups.get(round).push({id:'history_'+messageIndex+'_'+index,name:call.recovery?'pc__fs_write':call.name,args,
          text:call.recovery?.result??call.model_result??String(call.result??'')});
      }
      for(const calls of groups.values()){
        if(!calls.length)continue;
        result.push({role:'assistant',content:'',tool_calls:calls.map(call=>({
          id:call.id,type:'function',function:{name:call.name,arguments:JSON.stringify(call.args)}
        }))});
        for(const call of calls)result.push({role:'tool',tool_call_id:call.id,content:call.text});
      }
    }
    if(message.role!=='assistant'||message.content||message.reasoning_content){
      result.push({role:message.role,content:message.images?.length?[{type:'text',text:message.content||''},...message.images.map(image=>({type:'image_url',image_url:{url:image.url}}))]:message.content||'',
        ...(message.reasoning_content?{reasoning_content:message.reasoning_content}:{})});
    }
  });
  return result;
}
async function compactConversationContext() {
  if(busy||engineBusy||!modelIsReady()||messages.length<2)return;
  const btn=$('#ctxCompact'),status=$('#contextCompactStatus');
  let splitIndex=messages.length;
  if(messages.length>=4){
    for(let i=messages.length-1;i>=2;i--){
      if(messages[i]?.role==='user'){splitIndex=i;break;}
    }
  }
  const toCompact=conversationForModel(messages.slice(0,splitIndex));
  if(!toCompact.length){note(uiText('No hay mensajes suficientes para comprimir.'));return;}
  const originalCount=splitIndex;
  setEngineBusy(true);
  if(btn)btn.textContent=uiText('Comprimiendo…');
  const waitingSrc=activeEngine==='api'?'Comprimiendo historial con el método nativo…':'Comprimiendo historial con el modelo local…';
  if(status){status.dataset.uiLabel=waitingSrc;status.textContent=uiText(waitingSrc);}
  try{
    await flushSessionSaves();
    const result=await requestJSON('/api/harness/context/compact',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({conversation_id:currentId,model:loadedModel,messages:toCompact})
    });
    const checkpoint={
      role:'assistant',
      content:result.summary||'',
      compacted:{
        method:result.method||(activeEngine==='api'?'api':'local_chat_completions'),
        method_label:result.method_label||result.method||(activeEngine==='api'?'API':'Resumen con modelo local'),
        compressed_count:originalCount,
        kept_count:messages.length-splitIndex,
        created_at:new Date().toISOString()
      },
      model:loadedModel,
      model_name:modelNames[loadedModel]||loadedModel,
      ...(result.usage?{usage:{...result.usage,limit:contextCapacity||modelContexts[loadedModel]||null}}:{})
    };
    const kept=messages.slice(splitIndex).map(m=>m&&typeof m==='object'&&m.usage?{...m,pre_compaction:true}:m);
    messages=[checkpoint,...kept];
    persistConv();
    renderChat();
    syncContextMeter();
    const rawLabel=result.method_label||result.method||(activeEngine==='api'?'API':'Resumen con modelo local');
    const label=uiText(rawLabel);
    const doneSrc='Comprimido · '+originalCount+' msg · '+rawLabel;
    if(status){status.dataset.uiLabel=doneSrc;status.textContent=uiText(doneSrc);}
    note(uiText('Contexto comprimido.')+' ('+label+')');
  }catch(error){
    if(status){delete status.dataset.uiLabel;status.textContent=uiText('Error: ')+(error?.message||String(error));}
    note(error?.message||String(error));
  }finally{
    if(btn)btn.textContent=uiText('Comprimir contexto');
    setEngineBusy(false);
    updateControls();
  }
}
window.compactConversationContext=compactConversationContext;

// One message typed during a reply. Sent when the reply ends; "Send now" stops the reply and sends it at once.
let queuedFollowUp=null;
function renderQueuedMessage(){
  const box=$('#queuedMessage');if(!box)return;
  box.hidden=!queuedFollowUp;$('#queuedText').textContent=queuedFollowUp?queuedFollowUp.text.replace(/\s+/g,' '):'';
  $('#queuedText').title=queuedFollowUp?.text||'';
}
function queueFollowUp(redirect=false){
  const text=$('#input').value.trim();if(!text)return false;
  queuedFollowUp={text:queuedFollowUp?queuedFollowUp.text+'\n\n'+text:text,redirect:redirect||!!queuedFollowUp?.redirect};
  $('#input').value='';resizeInput();renderQueuedMessage();
  if(queuedFollowUp.redirect)stopGeneration(true);
  return true;
}
function flushQueuedFollowUp(){
  if(!queuedFollowUp||busy||engineBusy)return;
  const queued=queuedFollowUp;queuedFollowUp=null;renderQueuedMessage();
  const typed=$('#input').value.trim();
  $('#input').value=queued.text+(typed?'\n\n'+typed:'');resizeInput();
  // Stopped by the user (not a redirection): give the text back instead of sending it on its own.
  if(queued.held)return;
  sendMsg();
}
$('#queuedSendNow')?.addEventListener('click',()=>{if(!queuedFollowUp)return;queuedFollowUp.redirect=true;if(busy)stopGeneration(true);else flushQueuedFollowUp();});
$('#queuedRemove')?.addEventListener('click',()=>{if(!queuedFollowUp)return;const text=queuedFollowUp.text;queuedFollowUp=null;renderQueuedMessage();if(!$('#input').value.trim()){$('#input').value=text;resizeInput();}$('#input').focus();});
function stopGeneration(redirect=false) {
  if(!activeGeneration||activeGeneration.stopped)return;
  if(queuedFollowUp&&!redirect&&!queuedFollowUp.redirect)queuedFollowUp.held=true;
  activeGeneration.stopped=true;activeGeneration.controller.abort();$('#send').disabled=true;$('#modeNote').textContent=uiText('Deteniendo…');
}
async function waitForGenerationEnd() {
  const deadline=Date.now()+6000;
  while(Date.now()<deadline){try{const state=await requestJSON('/api/chat/status',{signal:AbortSignal.timeout(1500)});if(!state.busy)return;}catch{return;}await new Promise(resolve=>setTimeout(resolve,150));}
}
const DRAFT_CONTINUE_RE=/\b(?:sigue|contin[uú]a\w*|seguir|prosigue\w*|termina\w*|completa\w*|retoma\w*|borrador\w*|recupera\w*|continue\w*|resume|keep\s+going|go\s+on|go\s+ahead|finish\w*|draft\w*|recover\w*|weiter\w*|fortfahren|repren\w*|continuer)\b|drafts[\\/]/i;
function autoResumeDraftId(history,functions){
  const explicit=history.findLast(m=>m.role==='user')?.resume_draft;
  if(explicit)return explicit;
  if(!functions?.files)return undefined;
  const lastUser=String(history.findLast(m=>m.role==='user')?.content||'').trim();
  if(!lastUser)return undefined;
  const done=new Set();
  for(let i=history.length-1;i>=0;i--){
    const m=history[i];
    if(m.role!=='assistant')continue;
    for(const c of (m.tool_trace||[])){
      const completedWrite=(c.name==='pc__fs_write'||c.name==='fs_write'||c.name==='pc__fs_edit'||c.name==='fs_edit')&&c.args?.path;
      const completedCopy=(c.name==='pc__fs_copy'||c.name==='fs_copy')&&c.args?.destino;
      const donePath=completedWrite?c.args.path:completedCopy?c.args.destino:'';
      if(donePath&&c.status==='completed'&&c.ok!==false){
        done.add(String(donePath).split(/[\\/]/).pop().toLowerCase());
      }
    }
    for(let j=(m.tool_trace||[]).length-1;j>=0;j--){
      const c=m.tool_trace[j];
      const failed=c.ok===false||['error','blocked','interrupted','missing'].includes(c.status);
      if(!failed||!c.draft_id||(c.name!=='pc__fs_write'&&c.name!=='fs_write'))continue;
      const target=(c.args?.path?String(c.args.path):String(c.file_path||'').replace(/^[0-9a-f]{32}-/i,'')).split(/[\\/]/).pop().toLowerCase();
      if(target&&done.has(target))continue;
      if((target&&lastUser.toLowerCase().includes(target))||(lastUser.length<=240&&DRAFT_CONTINUE_RE.test(lastUser)))return c.draft_id;
    }
    const text=String(m.content||'');
    const re=/drafts[\\/]([0-9a-f]{32})(?:-([^\s`"'<>,;)\]]+))?/gi;
    let match;
    while((match=re.exec(text))!==null){
      const draftId=match[1],target=String(match[2]||'').replace(/[.,;:!?]+$/,'').toLowerCase();
      if(target&&done.has(target))continue;
      if((target&&lastUser.toLowerCase().includes(target))||(lastUser.length<=240&&DRAFT_CONTINUE_RE.test(lastUser)))return draftId;
    }
  }
  return undefined;
}
function cleanModelMessages(items,hasResume){
  if(!hasResume)return items;
  return items.map(m=>m.role==='assistant'&&typeof m.content==='string'
    ?{...m,content:m.content.replace(/[^\n]*(?:Ábrelo en (?:la llamada )?Guardar archivo|Open it in the Save file call)[^\n]*\n?/gi,'').trim()}
    :m);
}
async function sendMsg(resumeDraft=null) {
  const text=$('#input').value.trim();
  if((!text&&!attachments.length)||busy||engineBusy)return;
  if(!requireModelForChat())return;
  const images=attachments.filter(a=>a.image).map(a=>({name:a.name,url:a.image})),files=attachments.filter(a=>!a.image);
  let payloadText=text;if(files.length)payloadText+='\n\n[Adjuntos]\n'+files.map(a=>'--- '+a.name+' ---\n'+a.content).join('\n\n');
  messages.push({role:'user',content:payloadText,...(images.length?{images}:{}),...(typeof resumeDraft==='string'?{resume_draft:resumeDraft}:{})});attachments=[];renderAttachments();$('#input').value='';resizeInput();persistConv();setFollow(true);
  await generateResponse();
}
async function regenerateResponse(index) {
  if(busy||engineBusy||index!==messages.length-1||messages[index]?.role!=='assistant')return;
  if(!requireModelForChat())return;
  setFollow(true);await generateResponse(index);
}
async function generateResponse(replaceIndex=null) {
  if(busy||engineBusy)return;
  if(!requireModelForChat())return;
  const previous=replaceIndex===null?null:JSON.parse(JSON.stringify(messages[replaceIndex]));
  const history=replaceIndex===null?messages:messages.slice(0,replaceIndex);
  const requestModel=loadedModel;
  const requestSettings=requestModel===$('#model').value?{sampling:{...S.sampling},effort:S.effort,rounds:S.rounds,profile:S.profile}:structuredClone(modelPreferences[requestModel]||{sampling:DEF_SAMPLING,effort:'high',rounds:50,profile:'code'});
  const generation={controller:new AbortController(),stopped:false,modelConfirmed:false,
    provenance:{model:requestModel,model_name:modelNames[requestModel]||requestModel,generated_at:new Date().toISOString()},
    startWall:Date.now(),phaseSince:Date.now(),callSince:new Map()};activeGeneration=generation;
  setBusy(true);renderChat(replaceIndex??-1);
  const box=addAssistantBox(),think=box.querySelector('.think'),thinkBody=box.querySelector('.think-body'),bubble=box.querySelector('.bubble');box.dataset.index=replaceIndex??messages.length;box.dataset.generating='true';generation.box=box;const metricLabels=box.querySelectorAll('.response-metrics small');if(metricLabels[0])metricLabels[0].textContent=uiText('Generación');if(metricLabels[1])metricLabels[1].textContent=uiText('Lectura');bubble.textContent=uiText('Preparando respuesta…');
  showResponseModel(box,generation.provenance);
  let finalText='',finalReasoning='',ended=false,finishReason='',reader,errorText='',lastUsage=null,traceView=null,paintFrame=0,streamNote=uiText('Preparando respuesta…'),paintedReasoning='',paintedBubble='',streamComplete=false,traceDirty=false,paintTimer=0,lastPaint=0;const toolTrace=[];generation.trace=toolTrace;startActivity();
  function paintStream(){
    paintFrame=0;
    lastPaint=performance.now();
    if (traceDirty) {
      traceDirty = false;
      if (!traceView) {
        const holder = document.createElement('div');
        traceView = renderToolTrace(holder, toolTrace);
        bubble.before(traceView);
      } else updateToolTrace(traceView, toolTrace);
    }
    think.hidden=!finalReasoning;
    if((think.open||streamComplete)&&finalReasoning!==paintedReasoning){renderRich(thinkBody,finalReasoning,{streaming:!streamComplete});paintedReasoning=finalReasoning;}
    const nextBubble=finalText||streamNote;
    if(nextBubble!==paintedBubble){if(finalText)renderRich(bubble,finalText,{streaming:!streamComplete});else{bubble.textContent=nextBubble;richViews.delete(bubble);}paintedBubble=nextBubble;}
    scrollDown();
  }
  function queuePaint(){
    if (paintFrame || paintTimer) return;
    paintTimer = setTimeout(() => {
      paintTimer = 0;
      paintFrame = requestAnimationFrame(paintStream);
    }, Math.max(0, 48 - (performance.now() - lastPaint)));
  }
  think.addEventListener('toggle', () => { if (think.open && activeGeneration===generation) queuePaint(); });
  try {
    await flushSessionSaves();
    if(conflictedSessions.has(currentId))throw new Error('Vuelve a abrir el chat para usar la versión actual del disco. La copia en conflicto está conservada.');
    const functions=Object.fromEntries(Object.keys(DEF_FUNCS).map(key=>[key,!!S.functions[key]]));
    if(pcAccess.mode!=='full_pc'&&!pcAccess.isolation?.available)functions.shell=false;
    const resumeDraftId=autoResumeDraftId(history,functions);
    const modelMessages=cleanModelMessages(conversationForModel(history),Boolean(resumeDraftId));
    const sentAt=performance.now();
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},signal:generation.controller.signal,body:JSON.stringify({model:requestModel,model_name:modelNames[requestModel]||requestModel,context_limit:contextCapacity||modelContexts[requestModel],conversation_id:temporaryChat?null:currentId,messages:modelMessages,resume_draft:resumeDraftId,effort:requestSettings.effort,functions,sampling:requestSettings.sampling,profile:requestSettings.profile||"custom",rounds:requestSettings.rounds,permission_mode:S.permissionMode||"ask",agent_profile:S.agentProfile||"balanced",ask_user:true,native_stream:true})});
    if(!response.ok){let data;try{data=await response.json();}catch{}throw new Error(data?.error||'Error HTTP '+response.status);}
    if(!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw new Error('El servidor no devolvió una respuesta de chat válida.');
    generation.runId=response.headers.get('X-Strata-Run-Id');
    generation.startAt=generation.startAt||sentAt;
    pollLiveContext(generation);
    generation.modelConfirmed=true;
    reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
    function consume(chunk) {
      const payload=chunk.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n').trim();
      if(!payload||payload==='[DONE]')return;let event;try{event=JSON.parse(payload);}catch{return;}
      if(event.error)throw new Error(typeof event.error==='string'?uiText(event.error):uiText(event.error.message||'El motor devolvió un error.'));
      if(event.timings)updateResponsePerformance(generation,event.timings);
      // First visible output (reasoning, text or a tool call being written), as measured here.
      if(!generation.firstAt&&(event.type==='reasoning'||event.type==='content'||event.type==='tool_draft'||event.type==='tool'||event.choices?.[0]?.delta?.content||event.choices?.[0]?.delta?.reasoning_content))generation.firstAt=performance.now();
      if(Array.isArray(event.choices)){
        const choice=event.choices[0]||{},delta=choice.delta||{};
        if(delta.reasoning_content){finalReasoning+=delta.reasoning_content;if(!finalText)streamNote=uiText('Razonando…');setGenerationPhase(generation,'thinking');}
        if(delta.content){finalText+=delta.content;setGenerationPhase(generation,'writing');}
        if(event.usage){lastUsage=event.usage;raiseGenerationUsage(generation,event.usage);}
        if(choice.finish_reason){ended=true;finishReason=choice.finish_reason;}
        queuePaint();return;
      }
      if(event.type==='approval'){showToolApproval(event);notifyBackground('attention');}
      else if(event.type==='question'){showAgentQuestion(event);notifyBackground('attention');}
      else if(event.type==='reasoning'){finalReasoning+=event.text||'';if(!finalText)streamNote=uiText('Razonando…');setGenerationPhase(generation,'thinking');}
      else if(event.type==='reasoning_fixed'){finalReasoning=event.text||'';}   // el agente quito marcas de llamada crudas del razonamiento
      else if(event.type==='content'){finalText+=event.text||'';setGenerationPhase(generation,'writing');}
      else if(event.type==='content_fixed'){finalText=event.text||'';}   // reemplazo: el agente quito marcas de llamada crudas
      else if(['tool_draft','tool','tool_state','tool_result'].includes(event.type)){
        recordToolEvent(toolTrace,event);
        traceDirty = true;
        if(!finalText)streamNote=uiText(event.type==='tool_draft'?'Redactando llamada…':event.type==='tool_result'?'Preparando respuesta…':'Consultando herramienta…');
      }
      else if(event.type==='usage'){
        lastUsage=event.usage;
        raiseGenerationUsage(generation,event.usage);
      }
      else if(event.type==='done'){ended=true;if(event.finish_reason)finishReason=event.finish_reason;if(!finalText&&event.content)finalText=event.content;if(!finalReasoning&&event.reasoning_content)finalReasoning=event.reasoning_content;}
      else if(event.type==='error')throw new Error(event.text?uiText(event.text):uiText('El agente encontró un error.'));queuePaint();
    }
    for(;;){const {value,done}=await reader.read();buffer+=done?decoder.decode():decoder.decode(value,{stream:true});let match;while((match=/\r?\n\r?\n/.exec(buffer))){const chunk=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);consume(chunk);}if(done){if(buffer.trim())consume(buffer);break;}}
    if(!ended)throw new Error(uiText('La conexión se interrumpió antes de completar la respuesta.'));
    // Only thinking: say what happened (often the output limit ran out inside the reasoning), not a bare failure.
    if(!finalText.trim()&&finalReasoning.trim())throw new Error(uiText(finishReason==='length'?'El modelo agotó su límite de salida mientras razonaba y no llegó a responder. Prueba con menos esfuerzo de razonamiento o pide la tarea por partes.':'El modelo terminó de razonar sin escribir una respuesta. Puedes pedirle que continúe.'));
    if(!finalText.trim())throw new Error(uiText('El modelo terminó sin devolver texto. Puedes regenerar la respuesta.'));
  }catch(error){
    if(reader)await reader.cancel().catch(()=>{});
    if(!generation.stopped)errorText=uiText('No se pudo completar la respuesta: ')+error.message;
  }finally {
    generation.contextDone=true;clearTimeout(generation.contextTimer);
    if(paintFrame)cancelAnimationFrame(paintFrame);
    if(paintTimer)clearTimeout(paintTimer);
    const reviewingLive = chatHasSelection(box) || selectingChat;
    streamComplete = !reviewingLive;
    paintedReasoning=null;paintedBubble=null;
    paintStream();
    if(generation.stopped)await waitForGenerationEnd();
    const response={role:'assistant',content:finalText,reasoning_content:finalReasoning,run_id:generation.runId,...(generation.modelConfirmed?generation.provenance:{})};
    for(const call of toolTrace)if(['drafting','validating','running'].includes(call.status))call.status=generation.stopped?'interrupted':'missing';
    if(toolTrace.length)response.tool_trace=toolTrace;
    // A stopped reply gets no final count; keep the last live measure so the meter does not go blank.
    const finalUsage=lastUsage||(generation.usage&&Number.isFinite(generation.usage.prompt_tokens)?generation.usage:null);
    if(finalUsage)response.usage={...finalUsage,limit:contextCapacity||modelContexts[requestModel]||null};
    if(generation.performance||generation.startAt){
      response.performance={...(generation.performance||{})};
      if(generation.startAt)response.performance.detail={...(generation.detail||{rounds:0,promptNew:0,cached:0,promptMs:0,generated:0,genMs:0}),
        firstMs:generation.firstAt?Math.round(generation.firstAt-generation.startAt):null,totalMs:Math.round(performance.now()-generation.startAt),
        finish:generation.stopped?'stopped':errorText?'error':finishReason||'',tools:toolTrace.length};
    }
    if(generation.stopped)response.status='stopped';else if(errorText){response.status='error';response.error=errorText;}
    if(previous&&!finalText&&!finalReasoning&&!toolTrace.length){messages[replaceIndex]=previous;note(errorText||'Generación detenida. Se conserva la respuesta anterior.');}
    else if(previous){const variants=previous.variants?.length?previous.variants.map(responseVersion):[responseVersion(previous)];variants.push(responseVersion(response));messages[replaceIndex]={...response,variants,variantIndex:variants.length-1};}
    else messages.push(response);
    showResponseMetrics(box,response.performance);
    persistConv();activeGeneration=null;renderActivity();setBusy(false);
    if (reviewingLive) {
      const finishView = () => {
        if (box.isConnected && (chatHasSelection(box) || selectingChat)) return;
        document.removeEventListener('selectionchange', finishView);
        window.removeEventListener('pointerup', finishView);
        if (box.isConnected && !activeGeneration) renderChat();
      };
      document.addEventListener('selectionchange', finishView);
      window.addEventListener('pointerup', finishView);
      finishView();
    } else {
      renderChat();
      if (followStream && !chatHasSelection()) $('#input').focus({preventScroll:true});
    }
    if(!generation.stopped)notifyBackground(errorText?'error':'done');
    if(queuedFollowUp)setTimeout(flushQueuedFollowUp,0);
  }
}
// Notify only when the window is in the background; restore the title as soon as the user returns.
let baseDocumentTitle=document.title||'V-Agent';
function restoreDocumentTitle(){if(document.title!==baseDocumentTitle)document.title=baseDocumentTitle;}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)restoreDocumentTitle();});
window.addEventListener('focus',restoreDocumentTitle);
function notifyBackground(kind){
  if(!document.hidden)return;
  let enabled=true;try{enabled=localStorage.getItem('valNotifyOnDone')!=='0';}catch{}
  if(!enabled)return;
  const labels={done:'Respuesta lista',attention:'V-Agent necesita tu respuesta',error:'La respuesta terminó con un error'};
  const prefix=kind==='attention'?'! ':kind==='error'?'× ':'✓ ';
  const chatName=$('#chatTitle')?.textContent||'V-Agent';
  document.title=prefix+chatName+' — V-Agent';
  if(typeof Notification==='function'&&Notification.permission==='granted'){
    try{const n=new Notification(uiText(labels[kind]||labels.done),{body:chatName,tag:'v-agent-turn'});n.onclick=()=>{window.focus();n.close();};}catch{}
  }
}
