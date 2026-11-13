/* ---------- adjuntos ---------- */
function renderAttachments() {
  const box = $("#attachments"); box.innerHTML = "";
  attachments.forEach((a, i) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.innerHTML = '<span></span><button title="Quitar">×</button>';
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
    if (f.size > 400000) { note("«" + f.name + "» es demasiado grande (máx. 400 KB)."); continue; }
    try {
      const content = await f.text();
      if (content.includes("\u0000") || ["image/", "audio/", "video/", "application/pdf"].some(t => f.type.startsWith(t))) {
        note("«" + f.name + "»: adjunta un archivo de texto, código, CSV o Markdown."); continue;
      }
      attachments.push({ name: f.name, content });
    } catch { note("No se pudo leer «" + f.name + "»."); }
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
  $('#loadedTxt').textContent=known?(loadedModel?(modelNames[loadedModel]||loadedModel):'Ninguno'):'Comprobando…';
  updateControls();
  syncContextMeter();
  // The model window then shows the context the engine really runs with.
  if((changed||contextCapacity!==previousCapacity)&&typeof syncContextSelection==='function')syncContextSelection();
}
function modelIsReady(){return !preparationState?.active&&modelStateKnown&&engineOnline===true&&loadedModel&&loadedModel===$('#model').value;}
function requireModelForChat(){if(modelIsReady())return true;note(loadedModel?'Descarga el modelo en memoria y carga el seleccionado en Motor.':'Selecciona un modelo y pulsa Cargar modelo en Motor.');if(!document.querySelector('dialog[open]'))setChatControls('model');return false;}
function updateControls() {
  const blocked=engineBusy||accessChanging||draftSaving||!!preparationState?.active;
  if($('#kvCache'))$('#kvCache').disabled=busy||blocked||!(modelKV[$('#model').value]?.options?.length);
  for(const id of ['input','attach','file','model','effort','refreshModels','addModel','engineToggle','workProfile','p_rounds','mcpReconnect','pcAccess'])$('#'+id).disabled=busy||blocked||accessChanging;
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
  const compactBtn=$('#ctxCompact');
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
  $('#preparationLabel').textContent=state?.cancel_requested?uiText('Cancelando la carga…'):reading?uiText('Leyendo pesos')+' · '+Math.round(state.percent||0)+' %':state?.active?state.message||uiText('Preparando modelo…'):state?.stage==='cancelled'?uiText('Carga cancelada.'):uiText('Preparando carga…');
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
  $("#send").setAttribute("aria-label", value ? "Detener respuesta" : "Enviar mensaje");
  $("#send").innerHTML=value?STOP_ICON:SEND_ICON;
}
const SEND_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>';
const STOP_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/></svg>';
let activeGeneration=null;
function conversationForModel(history) {
  const result=[];
  history.forEach((message,messageIndex)=>{
    if(message.compacted){
      const label=message.compacted.method_label||message.compacted.method||'API';
      result.push({role:'user',content:'Contexto previo comprimido ('+label+'):\n\n'+(message.content||'')});
      result.push({role:'assistant',content:'Entendido. Continúo usando este contexto comprimido.'});
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
  if(status)status.textContent=uiText('Comprimiendo historial con el método nativo…');
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
        method:result.method||'api',
        method_label:result.method_label||result.method||'API',
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
    const label=result.method_label||result.method||'API';
    if(status)status.textContent=uiText('Comprimido · ')+originalCount+' msg · '+label;
    note(uiText('Contexto comprimido.')+' ('+label+')');
  }catch(error){
    if(status)status.textContent=uiText('Error: ')+(error?.message||String(error));
    note(error?.message||String(error));
  }finally{
    if(btn)btn.textContent=uiText('Comprimir contexto');
    setEngineBusy(false);
    updateControls();
  }
}
window.compactConversationContext=compactConversationContext;

function stopGeneration() {
  if(!activeGeneration||activeGeneration.stopped)return;
  activeGeneration.stopped=true;activeGeneration.controller.abort();$('#send').disabled=true;$('#modeNote').textContent='Deteniendo…';
}
async function waitForGenerationEnd() {
  const deadline=Date.now()+6000;
  while(Date.now()<deadline){try{const state=await requestJSON('/api/chat/status',{signal:AbortSignal.timeout(1500)});if(!state.busy)return;}catch{return;}await new Promise(resolve=>setTimeout(resolve,150));}
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
    provenance:{model:requestModel,model_name:modelNames[requestModel]||requestModel,generated_at:new Date().toISOString()}};activeGeneration=generation;
  setBusy(true);renderChat(replaceIndex??-1);
  const box=addAssistantBox(),think=box.querySelector('.think'),thinkBody=box.querySelector('.think-body'),bubble=box.querySelector('.bubble');box.dataset.index=replaceIndex??messages.length;box.dataset.generating='true';generation.box=box;const metricLabels=box.querySelectorAll('.response-metrics small');if(metricLabels[0])metricLabels[0].textContent=uiText('Generación');if(metricLabels[1])metricLabels[1].textContent=uiText('Lectura');bubble.textContent=uiText('Preparando respuesta…');
  showResponseModel(box,generation.provenance);
  let finalText='',finalReasoning='',ended=false,reader,errorText='',lastUsage=null,traceView=null,paintFrame=0,streamNote=uiText('Preparando respuesta…'),paintedReasoning='',paintedBubble='',streamComplete=false,traceDirty=false,paintTimer=0,lastPaint=0;const toolTrace=[];
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
    const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},signal:generation.controller.signal,body:JSON.stringify({model:requestModel,model_name:modelNames[requestModel]||requestModel,context_limit:contextCapacity||modelContexts[requestModel],conversation_id:currentId,messages:conversationForModel(history),resume_draft:history.findLast(m=>m.role==='user')?.resume_draft,effort:requestSettings.effort,functions,sampling:requestSettings.sampling,profile:requestSettings.profile||"custom",rounds:requestSettings.rounds,permission_mode:S.permissionMode||"ask",agent_profile:S.agentProfile||"balanced",native_stream:true})});
    if(!response.ok){let data;try{data=await response.json();}catch{}throw new Error(data?.error||'Error HTTP '+response.status);}
    if(!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw new Error('El servidor no devolvió una respuesta de chat válida.');
    generation.runId=response.headers.get('X-Strata-Run-Id');
    pollLiveContext(generation);
    generation.modelConfirmed=true;
    reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
    function consume(chunk) {
      const payload=chunk.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n').trim();
      if(!payload||payload==='[DONE]')return;let event;try{event=JSON.parse(payload);}catch{return;}
      if(event.error)throw new Error(typeof event.error==='string'?uiText(event.error):uiText(event.error.message||'El motor devolvió un error.'));
      if(event.timings)updateResponsePerformance(generation,event.timings);
      if(Array.isArray(event.choices)){
        const choice=event.choices[0]||{},delta=choice.delta||{};
        if(delta.reasoning_content){finalReasoning+=delta.reasoning_content;if(!finalText)streamNote='Razonando…';}
        if(delta.content)finalText+=delta.content;
        if(event.usage){lastUsage=event.usage;raiseGenerationUsage(generation,event.usage);}
        if(choice.finish_reason)ended=true;
        queuePaint();return;
      }
      if(event.type==='approval'){showToolApproval(event);}
      else if(event.type==='reasoning'){finalReasoning+=event.text||'';if(!finalText)streamNote='Razonando…';}
      else if(event.type==='reasoning_fixed'){finalReasoning=event.text||'';}   // el agente quito marcas de llamada crudas del razonamiento
      else if(event.type==='content'){finalText+=event.text||'';}
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
      else if(event.type==='done'){ended=true;if(!finalText&&event.content)finalText=event.content;if(!finalReasoning&&event.reasoning_content)finalReasoning=event.reasoning_content;}
      else if(event.type==='error')throw new Error(event.text?uiText(event.text):uiText('El agente encontró un error.'));queuePaint();
    }
    for(;;){const {value,done}=await reader.read();buffer+=done?decoder.decode():decoder.decode(value,{stream:true});let match;while((match=/\r?\n\r?\n/.exec(buffer))){const chunk=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);consume(chunk);}if(done){if(buffer.trim())consume(buffer);break;}}
    if(!ended)throw new Error(uiText('La conexión se interrumpió antes de completar la respuesta.'));
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
    if(generation.performance)response.performance={...generation.performance};
    if(generation.stopped)response.status='stopped';else if(errorText){response.status='error';response.error=errorText;}
    if(previous&&!finalText&&!finalReasoning&&!toolTrace.length){messages[replaceIndex]=previous;note(errorText||'Generación detenida. Se conserva la respuesta anterior.');}
    else if(previous){const variants=previous.variants?.length?previous.variants.map(responseVersion):[responseVersion(previous)];variants.push(responseVersion(response));messages[replaceIndex]={...response,variants,variantIndex:variants.length-1};}
    else messages.push(response);
    showResponseMetrics(box,response.performance);
    persistConv();activeGeneration=null;setBusy(false);
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
  }
}
