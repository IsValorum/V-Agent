/* ---------- modelos / contexto ---------- */
function modelFileName(model){return model.gguf_name||(model.path&&/\.gguf$/i.test(model.path)?model.path.split(/[\\/]/).pop():null)||model.display_name||model.id;}


let modelCatalog=[],catalogRevision=0,catalogController=null;
function renderModelOptions(selected){
  const query=($('#modelFilter')?.value||'').trim().toLocaleLowerCase();
  const matches=modelCatalog.filter(model=>(modelFileName(model)+' '+model.id).toLocaleLowerCase().includes(query));
  const visible=modelCatalog.filter(model=>matches.includes(model)||model.id===selected);
  $('#model').replaceChildren(...visible.map(model=>{const option=new Option(modelFileName(model)+(model.status==='unavailable'?' · No disponible':''),model.id);option.disabled=model.status==='unavailable';option.title=[modelFileName(model),model.problem].filter(Boolean).join(' · ');return option;}));
  if(!visible.length)$('#model').add(new Option(query?'Sin coincidencias':'No hay modelos instalados',''));
  if(visible.some(model=>model.id===selected))$('#model').value=selected;
  if($('#modelCount')){$('#modelCount').textContent=query?matches.length+'/'+modelCatalog.length:modelCatalog.length+' modelos';$('#modelCount').title=query&&!matches.length?'Sin coincidencias. Se conserva el modelo seleccionado.':'';}
  renderModelList(selected);
}
function renderModelList(selected){
  const box=$('#modelResults');if(!box)return;
  const query=($('#modelFilter')?.value||'').trim().toLocaleLowerCase();
  const matches=modelCatalog.filter(model=>(modelFileName(model)+' '+model.id+' '+(model.backend||'')).toLocaleLowerCase().includes(query)).sort((a,b)=>{const score=m=>m.id===loadedModel?0:m.status==='loaded'?1:m.status==='unavailable'?3:2;return score(a)-score(b)||modelFileName(a).localeCompare(modelFileName(b));});
  box.replaceChildren();box.classList.toggle('remote-models',activeEngine==='api');
  if(!matches.length){const empty=document.createElement('div');empty.className='model-empty';empty.textContent=query?'Ningún modelo coincide con «'+query+'».':activeEngine==='api'?'Conecta una API para ver sus modelos.':'No hay modelos instalados.';box.append(empty);}
  for(const model of matches){
    const row=document.createElement('button');row.type='button';row.className='model-option';row.dataset.id=model.id;row.setAttribute('role','option');row.setAttribute('aria-selected',String(model.id===selected));row.disabled=model.status==='unavailable';
    const name=document.createElement('span');name.className='model-option-name';name.textContent=modelFileName(model);
    const meta=document.createElement('span');meta.className='model-option-meta';meta.textContent=[model.backend||'',model.context?model.context.toLocaleString()+' tokens':model.remote?'Contexto no informado':'',model.quantization||''].filter(Boolean).join(' · ');
    const state=document.createElement('span');state.className='model-option-state';state.textContent=model.status==='unavailable'?'No disponible':(model.id===loadedModel?(model.remote?'En uso':'En memoria'):'');
    row.title=[modelFileName(model),model.problem].filter(Boolean).join(' · ');
    row.append(name,meta,state);
    row.onclick=()=>{const select=$('#model');select.value=model.id;select.dispatchEvent(new Event('change'));box.querySelectorAll('.model-option').forEach(item=>item.setAttribute('aria-selected',String(item.dataset.id===model.id)));syncModelSelectionSummary();};
    box.append(row);
  }
  const selectedRow=box.querySelector('.model-option[aria-selected=true]');
  if(selectedRow)box.scrollTop=Math.max(0,selectedRow.offsetTop-box.clientHeight/2+selectedRow.offsetHeight/2);
  syncModelSelectionSummary();
}
function syncModelSelectionSummary(){
  const model=modelCatalog.find(item=>item.id===$('#model')?.value);
  const name=$('#modelSelectedName'),meta=$('#modelSelectedMeta'),state=$('#modelLoadState')||$('#modelSelectedState');
  if(name)name.textContent=model?modelFileName(model):uiText('Ningún modelo seleccionado');
  if(meta)meta.textContent=model?[model.backend||'',model.context?uiNumber(model.context)+' '+uiText('tokens de contexto'):model.remote?uiText('Contexto no informado por la API'):'',model.quantization||''].filter(Boolean).join(' · '):uiText('Elige un modelo de la lista para continuar.');
  if(state){
    const loading=!!model&&loadingModelId===model.id,inMemory=!!model&&model.id===loadedModel;
    state.dataset.state=loading?'loading':inMemory?'loaded':'idle';
    state.textContent=!model?'':loading?uiText('Cargando…'):inMemory?uiText(model.remote?'En uso':'En memoria'):uiText('Sin cargar');
    state.title=loadedModel&&!inMemory?uiText('En memoria:')+' '+(modelNames[loadedModel]||loadedModel):'';
  }
  if($('#remoteContextValue')){$('#remoteContextValue').textContent=model?.context?model.context.toLocaleString()+' tokens':uiText('No informado');$('#remoteContextOrigin').textContent=model?.context_source==='manual'?uiText('Límite indicado por ti'):model?.context_source==='provider'?uiText('Declarado por la API'):uiText('La API no publica este dato');if(document.activeElement!==$('#remoteContextInput'))$('#remoteContextInput').value=model?.context||'';}
  const action=$('#modelSummaryAction');if(action){const loaded=!!model&&model.id===loadedModel;action.hidden=!model;action.textContent=model?.remote?(loaded?uiText('Dejar de usar'):uiText('Usar modelo')):(loaded?uiText('Descargar'):uiText('Cargar'));const switching=!!model&&!model.remote&&!!loadedModel&&!loaded;if(switching)action.textContent=uiText('Cambiar a este modelo');action.dataset.primary=String(!loaded);action.disabled=!model||model.status==='unavailable'||busy||engineBusy||engineFormDirty()||!!loadedModel&&!loaded&&model.remote;action.title=model?.remote?uiText('Seleccionar o dejar de usar este modelo de la API'):loaded?uiText('Descargar el modelo de memoria'):uiText('Cargar el modelo seleccionado');action.onclick=async()=>{if(switching){await unloadModel();if(!loadedModel)await loadModel();return;}const button=document.getElementById(loaded?'unload':'load');button?.click();};}
}

async function loadModels() {
  const revision=modelStateRevision,requestId=++catalogRevision;
  catalogController?.abort();catalogController=new AbortController();const controller=catalogController;
  try {
    const d = await requestJSON("/api/models", {signal:AbortSignal.any([controller.signal,AbortSignal.timeout(30000)])});
    if(revision!==modelStateRevision||requestId!==catalogRevision)return;
    baseProfiles=d.profiles || baseProfiles;
    const models = (d.data || []).filter(m => typeof m.id === "string");
    for(const m of models)if(!modelPreferences[m.id]&&m.preferences)modelPreferences[m.id]=m.preferences;
    modelProfiles=Object.fromEntries(models.map(m=>[m.id,m.agent_profiles || baseProfiles]));
    modelContexts=Object.fromEntries(models.map(m=>[m.id,m.context]));
    modelKV=Object.fromEntries(models.map(m=>[m.id,m.kv]));
    modelVision=Object.fromEntries(models.map(m=>[m.id,m.vision_settings]));
    modelDrafts=Object.fromEntries(models.map(m=>[m.id,m.draft]));
    modelNames=Object.fromEntries(models.map(model=>[model.id,modelFileName(model)]));
    updatePreparation(d.preparation);
    const available = models.filter(m => m.status !== "unavailable");
    let selected = $("#model").value || S.model || models.find(m=>m.current)?.id || d.default_model;
    // Each engine names the same GGUF differently (llama--local-…, rust--local-…): after switching
    // engine, keep the same file instead of falling back to the first model of the new list.
    if(selected&&!models.some(m=>m.id===selected)){
      const before=modelCatalog.find(m=>m.id===selected),path=String(before?.path||'').toLowerCase(),tail=selected.split('--').pop();
      const same=models.find(m=>path&&String(m.path||'').toLowerCase()===path)||models.find(m=>m.id.split('--').pop()===tail);
      if(same){selected=same.id;S.model=same.id;saveSettings();}
    }
    modelCatalog=models;$('#modelFilter').disabled=busy||engineBusy||!models.length;
    const preferred=available.some(m=>m.id===selected)?selected:(available.find(m=>m.id===d.default_model)||available[0])?.id||'';
    renderModelOptions(preferred);$('#modelStatus').textContent='';
    syncModelPicker();
    syncContextSelection();
    syncKVSettings();syncVisionSettings();syncEngineCapabilities();
    if(!draftSaving)syncDraftSettings();
    if (!profilesReady && Object.keys(baseProfiles).length) {profilesReady=true;restoreModelPreferences();}
    if (typeof d.engine_online === "boolean") {
      setEngineState(d.engine_online);
      setLoadedModel(d.engine_online?(d.loaded_model||models.find(model=>model.status==='loaded')?.id||null):null);
    }
  } catch (e) {
    if(revision!==modelStateRevision||requestId!==catalogRevision)return;
    console.warn('Model catalogue:',e);
    $("#modelStatus").textContent = "No se pudo leer la lista de modelos: " + e.message;
    if (!$("#model").options.length || !$("#model").value) $("#model").replaceChildren(new Option("No se pudo leer la lista", ""));
    syncModelPicker();
  }
}
async function powerEngine() {
  if (busy || engineBusy || preparationState?.active || engineOnline === null) return;
  const starting = !engineOnline; modelStateRevision++; setEngineBusy(true);
  const status=$("#modelStatus"); status.textContent=starting?"Iniciando el motor…":"Apagando el motor y liberando memoria…";
  syncComposerLabels();
  try {
    const d=await requestJSON(starting?"/api/engine/start":"/api/engine/stop", {
      method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(starting?{model:$("#model").value || undefined}:{})
    });
    setEngineState(d.engine_online ?? starting);
    await loadModels();
    status.textContent=starting?"Motor encendido. Pulsa Cargar modelo para preparar el modelo seleccionado.":"Motor apagado. Puedes encenderlo cuando lo necesites.";
    note(starting?"Motor encendido.":"Motor apagado y memoria del modelo liberada.");
  } catch(e) { status.textContent="No se pudo "+(starting?"encender":"apagar")+" el motor: "+e.message; note(status.textContent); }
  finally { modelStateRevision++; setEngineBusy(false); pollStats(); }
}
$("#engineToggle").onclick=powerEngine;
async function unloadModel() {
  if(engineBusy||preparationState?.active)return;
  modelStateRevision++;setEngineBusy(true);const button=$('#unload');button.textContent=uiText(busy?'Deteniendo…':'Descargando…');
  try {
    if(busy){stopGeneration();const deadline=Date.now()+9000;while(busy&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,50));if(busy)throw new Error(uiText('La respuesta todavía se está deteniendo. Inténtalo de nuevo.'));}
    button.textContent=uiText('Descargando…');
    const result=await requestJSON('/api/unload',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(130000)});
    setLoadedModel(null);if(typeof result.engine_online==='boolean')setEngineState(result.engine_online);
    await loadModels();$('#modelStatus').textContent=uiText('Modelo descargado. Selecciona otro y pulsa Cargar modelo.');note('Modelo descargado.');
  }catch(error){$('#modelStatus').textContent=uiText('No se pudo descargar:')+' '+error.message;note($('#modelStatus').textContent);await loadModels();}
  finally{modelStateRevision++;setEngineBusy(false);button.textContent=uiText('Descargar modelo');pollStats();}
}
async function loadModel() {
  if(busy||engineBusy||preparationState?.active)return;
  if(!$('#model').value){note('Selecciona un modelo disponible.');return;}
  if(loadedModel){note('Descarga primero el modelo en memoria.');return;}
  const selected=$('#model').value,name=modelNames[selected]||selected;
  await flushModelPreferences();
  const context=pendingModelContexts.get(selected)??modelPreferences[selected]?.context;
  S.model=selected;saveSettings();modelStateRevision++;loadingModelId=selected;setEngineBusy(true);schedulePreparationPoll();syncModelSelectionSummary();
  const button=$('#load');button.textContent=uiText('Cargando…');const started=Date.now();
  $('#modelStatus').textContent=uiText('Cargando')+' '+name+'…';
  const timer=setInterval(()=>{syncPreparationView();$('#modelStatus').textContent=preparationState?.cancel_requested?uiText('Cancelando la carga…'):uiText('Preparando')+' '+name+' · '+Math.floor((Date.now()-started)/1000)+' s';},1000);
  try {
    const result=await requestJSON('/api/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:selected,context}),signal:AbortSignal.timeout(910000)});
    if(result.status==='cancelled'){
      updatePreparation(result.preparation);setLoadedModel(null);setEngineState(result.engine_online===true);await loadModels();$('#modelStatus').textContent=uiText('Carga cancelada.');note('Carga cancelada.');return;
    }
    const actual=result.loaded_model||result.model?.id;
    if(actual!==selected)throw new Error(uiText('El motor no confirmó el modelo seleccionado.'));
    pendingModelContexts.delete(selected);
    updatePreparation(result.preparation);setEngineState(true);setLoadedModel(actual,true,result.context??null);await loadModels();$('#modelStatus').textContent=result.preparation?.mode==='on_demand'?uiText(result.preparation.message):uiText('Modelo listo.');note(result.preparation?.mode==='on_demand'?'Modelo cargado con lectura bajo demanda.':'Modelo listo.');
    pintarPlantilla(result.template);
    if(result.warning)note('Plantilla jinja: '+result.warning);
    else if(result.template&&result.template.reaplicacion)note('Plantilla jinja: '+result.template.reaplicacion);
  }catch(error){await loadModels();$('#modelStatus').textContent=uiText('No se pudo cargar:')+' '+error.message;note($('#modelStatus').textContent);}
  finally{clearInterval(timer);loadingModelId=null;syncModelSelectionSummary();clearTimeout(preparationTimer);preparationTimer=null;modelStateRevision++;syncModelPicker();setEngineBusy(false);button.textContent=uiText('Cargar modelo');pollStats();}
}

/* ---------- plantilla jinja del modelo cargado ---------- */
const PLANTILLA_MAL=['sin_plantilla','correccion_no_aplicada','desactualizada','error','sin_comprobacion'];
let plantillaEstado=null,plantillaConsultada='';
function pintarPlantilla(t){
  const fila=$('#templateRow'),txt=$('#templateTxt');if(!fila||!txt)return;
  if(!t){fila.hidden=true;plantillaEstado=null;return;}
  plantillaEstado=t;fila.hidden=false;
  const malo=PLANTILLA_MAL.includes(t.estado);
  // "llamadas json|xml" es lo que declara la plantilla de ESTE modelo: se lee de ella, no se
  // supone. Si alguna vez sale xml en un modelo que no lo pide, ahi se ve antes de la ronda.
  txt.textContent=(t.linea||t.estado||'')+(t.formato?' · llamadas: '+t.formato:'')+(t.reaplicacion?' · '+t.reaplicacion:'');
  txt.title=[t.repo||'sin repo registrado',t.archivo,t.sha_local?('sha '+t.sha_local):'',t.sha_repo?('repo '+t.sha_repo):'',t.revision?('revision '+t.revision):'',t.detalle||''].join(' · ');
  txt.dataset.bad=malo?'1':'';txt.dataset.ok=malo?'':'1';
  $('#templateFix').textContent=malo?'Aplicar la del repo':'Reaplicar del repo';
}
async function consultarPlantilla(modelo,aplicar){
  if(!modelo)return;
  const url=aplicar?'/api/template':'/api/template?model='+encodeURIComponent(modelo);
  try{
    const d=await requestJSON(url,{cache:'no-store',...(aplicar?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:modelo})}:{}),signal:AbortSignal.timeout(aplicar?180000:30000)});
    pintarPlantilla(d);plantillaConsultada=modelo;if(aplicar)note('Plantilla jinja: '+(d.linea||d.estado));
  }catch(error){pintarPlantilla({estado:'error',linea:'No se pudo comprobar la plantilla: '+error.message});}
}
$('#templateFix').onclick=async()=>{
  const modelo=loadedModel||$('#model').value;if(!modelo){note('Selecciona un modelo.');return;}
  const b=$('#templateFix');b.disabled=true;b.textContent='Aplicando…';
  try{await consultarPlantilla(modelo,true);}finally{b.disabled=false;pintarPlantilla(plantillaEstado);}
};

/* ---------- MTP ---------- */
function syncDraftSettings() {
  const info=modelDrafts[$('#model').value]||{};
  const select=$('#draftSource');
  const options=[new Option('Desactivado','')];
  if(info.integrated)options.push(new Option('MTP integrado','integrated'));
  for(const file of info.files||[])options.push(new Option(file.name,file.path));
  if(info.source&&!options.some(option=>option.value===info.source))options.push(new Option(info.source,info.source));
  select.replaceChildren(...options);
  select.value=info.source||'';
  $('#draftTokens').value=String(info.tokens||0);
  $('#draftStatus').textContent=info.pending?'Guardado. Se aplicará al recargar.':info.integrated?'MTP integrado':info.source?'Cabeza MTP externa':'Sin MTP integrado';
  updateControls();
}
async function saveDraftSettings(reload=false) {
  if(draftSaving||busy||engineBusy)return;
  const model=$('#model').value;
  if(!model)return;
  const source=$('#draftSource').value,tokens=Number($('#draftTokens').value);
  draftSaving=true;
  if(reload){modelStateRevision++;loadingModelId=model;setEngineBusy(true);schedulePreparationPoll();}
  updateControls();$('#draftStatus').textContent=reload?'Aplicando y recargando…':'Guardando…';
  try {
    const result=await requestJSON('/api/models/draft',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model,source,tokens,reload}),signal:AbortSignal.timeout(reload?910000:15000)
    });
    modelDrafts[model]={...result.draft,pending:result.pending};
    if($('#model').value===model)$('#draftStatus').textContent=result.cancelled?'Carga cancelada. Ajustes guardados.':result.reloaded?'Configuración aplicada.':result.pending?'Guardado. Se aplicará al recargar.':'Guardado para la próxima carga.';
    if(result.reloaded||result.cancelled)await loadModels();
  } catch(error) {$('#draftStatus').textContent='No se pudo guardar: '+error.message;}
  finally {
    draftSaving=false;
    if(reload){modelStateRevision++;loadingModelId=null;setEngineBusy(false);pollStats();}
    updateControls();
  }
}
$('#draftSource').onchange=()=>{
  $('#draftTokens').value=$('#draftSource').value?($('#draftTokens').value==='0'?'2':$('#draftTokens').value):'0';
  saveDraftSettings();
};
$('#draftTokens').onchange=()=>saveDraftSettings();
$('#draftReload').onclick=()=>saveDraftSettings(true);
$('#draftBrowse').onclick=async()=>{
  if(busy||engineBusy||draftSaving)return;
  const model=$('#model').value;
  try {
    const result=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'draft'})});
    if(result.cancelled||!result.path||$('#model').value!==model)return;
    const select=$('#draftSource');
    if(![...select.options].some(option=>option.value===result.path))select.add(new Option(result.path.split(/[\\/]/).pop(),result.path));
    select.value=result.path;$('#draftTokens').value='2';
    await saveDraftSettings();
  }catch(error){$('#draftStatus').textContent=error.message;}
};

/* ---------- contexto ---------- */
function updateContextSlider() {
  const input = $('#ctxInput');
  const label = formatTokens(input.valueAsNumber) + ' tokens';
  $('#ctxValue').textContent = label;
  input.setAttribute('aria-valuetext', label);
}
function syncContextSelection() {
  const model = $('#model').value;
  // A loaded model shows the context the engine really has (it may have been loaded from the API or
  // another window), unless the user is changing it right now.
  const running = model && model === loadedModel && contextCapacity ? contextCapacity : null;
  $('#ctxInput').value = pendingModelContexts.get(model) ?? running ?? modelPreferences[model]?.context ?? (modelContexts[model] || 16384);
  $('#ctxTarget').textContent = model ? modelNames[model] || model : 'Selecciona un modelo.';
  $('#ctxStatus').textContent = pendingModelContexts.has(model) && loadedModel!==model?'Se aplicará al cargar este modelo.':'';
  updateContextSlider();
}
$('#ctxInput').addEventListener('input', () => {
  const model=$('#model').value;
  if(model){pendingModelContexts.set(model,$('#ctxInput').valueAsNumber);queueModelPreferences();}
  if(model&&loadedModel!==model)$('#ctxStatus').textContent='Se aplicará al cargar este modelo.';
  updateContextSlider();
  if(model&&loadedModel===model)$('#ctxStatus').textContent=uiText('Pulsa Aplicar y recargar para usarlo ahora.');updateControls();
});
$('#ctxApply').onclick = async () => {
  const model = $('#model').value;
  if (busy || engineBusy || !model) return;
  const tokens = $('#ctxInput').valueAsNumber;
  const status = $('#ctxStatus');
  modelStateRevision++;
  setEngineBusy(true);
  status.textContent = loadedModel === model ? 'Aplicando y recargando el modelo…' : 'Guardando contexto…';
  try {
    queueModelPreferences();await flushModelPreferences();
    const result = await requestJSON('/api/context', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tokens, model})
    });
    pendingModelContexts.delete(model);
    if(result.reloaded)contextCapacity=result.context;
    await loadModels();
    status.textContent = result.reloaded ? 'Contexto aplicado.' : 'Guardado para la próxima carga.';
  } catch (error) {
    status.textContent = 'Error: ' + error.message;
  } finally {
    modelStateRevision++;
    setEngineBusy(false);
    pollStats();
  }
};

/* ---------- estadísticas ---------- */
let contextCapacity=null;
async function pollLiveContext(generation){
  if(activeGeneration!==generation||generation.stopped||generation.contextDone)return;
  try{
    const data=await requestJSON('/api/context/usage',{cache:'no-store',signal:AbortSignal.any([generation.controller.signal,AbortSignal.timeout(2500)])});
    const usage=data.usage;
    if(activeGeneration===generation&&!generation.contextDone&&data.run_id===generation.runId&&data.conversation_id===currentId&&data.model===generation.provenance.model&&usage&&Number.isFinite(usage.used)){
      if(usage.source==='live')generation.contextSeen=true;
      if(generation.contextSeen){generation.usage={prompt_tokens:usage.prompt_tokens,completion_tokens:usage.completion_tokens,limit:usage.limit};syncContextMeter();}
    }
  }catch{}
  finally{if(activeGeneration===generation&&!generation.stopped&&!generation.contextDone)generation.contextTimer=setTimeout(()=>pollLiveContext(generation),700);}
}
function formatTokens(value) {return Math.round(value).toLocaleString(window.VALI18n?.locale||'es-ES');}
function syncContextMeter() {
  const limit=loadedModel?(contextCapacity||modelContexts[loadedModel]||null):null;
  const previous=messages.findLast(message=>message.role==='assistant');
  const live=activeGeneration?.provenance.model===loadedModel&&activeGeneration;
  // Until the first live sample arrives, keep showing the last measure instead of "—".
  const earlier=previous?.model===loadedModel?previous.usage:null;
  const usage=live&&live.usage?live.usage:earlier;
  // The engine's own limit wins: llama.cpp --fit may size the context to the VRAM, and after
  // "Apply and reload" the chat's last measure was taken with the old limit (it was then hidden).
  const reloaded=usage&&usage.limit&&limit&&usage.limit!==limit&&!(live&&live.usage);
  const measured=usage&&!reloaded&&Number.isFinite(usage.prompt_tokens)&&Number.isFinite(usage.completion_tokens);
  updateContextMeter({limit:(live&&live.usage?.limit)||limit,used:measured?usage.prompt_tokens+usage.completion_tokens:loadedModel&&(!messages.length||reloaded)?0:null,
    prompt_tokens:measured?usage.prompt_tokens:0,completion_tokens:measured?usage.completion_tokens:0,
    source:measured?(live?'live':'last'):null});
}
function updateContextMeter(usage) {
  const limit=Number.isFinite(usage?.limit)&&usage.limit>0?usage.limit:null;
  const used=Number.isFinite(usage?.used)&&usage.used>=0?usage.used:null;
  const percent=used!==null&&limit?used*100/limit:null;
  const numbers=(used===null?'—':formatTokens(used))+' / '+(limit?formatTokens(limit):'—');
  const ratio=percent===null?'—':percent.toLocaleString('es',{maximumFractionDigits:1})+' %';
  $('#ctxLabel').textContent=numbers+' · '+ratio;
  const contextSummary='Contexto: '+numbers+' tokens · '+ratio;
  $('#ctxBtn').setAttribute('aria-label',contextSummary);
  $('#contextUsageNumbers').textContent=numbers;$('#contextUsagePercent').textContent=ratio;
  const meter=$('#contextUsageBar');meter.style.setProperty('--context-fill',percent===null?'0%':Math.min(100,percent)+'%');meter.dataset.level=percent>=95?'full':percent>=80?'high':'normal';
  if(percent===null){meter.removeAttribute('aria-valuenow');meter.setAttribute('aria-valuetext','Sin medida disponible');}
  else {meter.setAttribute('aria-valuenow',Math.min(100,percent).toFixed(1));meter.setAttribute('aria-valuetext',numbers+' tokens, '+ratio);}
  const title=used===null?'Sin medida para este chat y modelo.':!usage.source?'Chat nuevo.':(usage.source==='live'?'Petición en curso':'Última medida de este chat')+': '+formatTokens(usage.prompt_tokens||0)+' tokens de entrada + '+formatTokens(usage.completion_tokens||0)+' de salida, incluido el razonamiento. Incluye la plantilla y las herramientas activadas. No cuenta el texto aún sin enviar.';
  $('#contextUsage').title=title;
}

function renderHardwareStats(s) {
  lastHardwareState=s;renderSystemMetrics(s);
  const number=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;
  const g=s?.gpu||{}, ram=s?.ram||{}, live=s?.live||{}, last=s?.last||{}, ex=s?.expert||{}, disk=s?.disk||{};
  const active=!!s?.loaded&&['reading','generating','decoding'].includes(live.state);
  $('#engineCard').dataset.active=String(active);
  $('#st-state').textContent=!s?'Sin conexión':s.engine_online===false?'Motor apagado':!s.loaded?'Sin modelo':live.state==='reading'?'Leyendo':active?'Generando':'En reposo';
  const dec=s?.loaded?number(live.tok_s)??number(last.decode):null;
  const promptMs=number(last.prompt_ms), promptRead=number(last.prompt_read);
  const pre=s?.loaded?number(live.prefill)??number(last.prefill)??(promptMs>0&&promptRead!==null?promptRead/(promptMs/1000):null):null;
  $('#st-speed-label').textContent=active?'Generación':'Última generación';
  $('#st-prefill-label').textContent=active?'Lectura':'Última lectura';
  $('#st-speed').textContent=dec===null?'—':dec.toFixed(1);
  $('#st-prefill').textContent=pre===null?'—':Math.round(pre).toLocaleString(window.VALI18n?.locale||'es-ES');
  const liveBox=activeGeneration?.box?.isConnected?activeGeneration.box:null;
  if(liveBox&&activeGeneration?.modelConfirmed&&active&&s.model===activeGeneration.provenance.model){const liveRates={};if(number(live.tok_s)>0)liveRates.predicted_per_second=live.tok_s;if(live.state==='reading'&&number(live.prefill)>0)liveRates.prompt_per_second=live.prefill;updateResponsePerformance(activeGeneration,liveRates,true);showResponseMetrics(liveBox,activeGeneration.performance);}
  function memory(id,used,total) {
    used=number(used);total=number(total);
    const known=used!==null&&total>0, meter=$('#'+id+'-meter');
    const pct=known?Math.max(0,Math.min(100,used/total*100)):0;
    $('#'+id).textContent=known?used.toFixed(1)+' / '+total.toFixed(1)+' GB':'—';
    meter.style.setProperty('--fill',pct+'%');meter.dataset.high=String(known&&pct>=90);
    meter.setAttribute('aria-valuetext',known?$('#'+id).textContent+' · '+pct.toFixed(1)+'%':'Sin datos');
    if(known)meter.setAttribute('aria-valuenow',pct.toFixed(1));else meter.removeAttribute('aria-valuenow');
  }
  memory('st-vram',number(g.vram_mib)===null?null:g.vram_mib/1024,number(g.vram_total_mib)===null?null:g.vram_total_mib/1024);
  memory('st-ram',ram.used_gib,ram.total_gib);
  $('#st-gpu').title=g.name||uiText('No disponible en este equipo');
  $('#st-gpu').textContent=[number(g.util)===null?null:g.util+'%',number(g.temp)===null?null:g.temp+' °C',number(g.power)===null?null:Math.round(g.power)+' W'].filter(v=>v!==null).join(' · ')||'—';
  $('#st-disk').textContent=number(disk.read_mbs)===null?'—':disk.read_mbs.toFixed(1)+' MB/s';
  $('#st-cache').title=uiText('Disponible solo si el motor informa de la caché de expertos.');
  $('#st-hit').title=uiText('Disponible solo si el motor informa de la caché de expertos.');
  $('#st-cache').textContent=number(ex.slots)===null?uiText('No disponible'):ex.slots+' exp'+(number(ex.mib)===null?'':' · '+(ex.mib/1024).toFixed(1)+' GB');
  $('#st-hit').textContent=number(last.hit)===null?uiText('No disponible'):Math.round(Math.min(1,last.hit)*100)+'%';
  // Expert cache rows only mean something on engines that report them (Strata): hide them otherwise.
  for(const id of ['st-cache','st-hit']){const row=$('#'+id).closest('div');if(row)row.hidden=$('#'+id).textContent===uiText('No disponible');}
  document.title=(active&&dec!==null?Math.round(dec)+' t/s · ':'')+'V-Agent';
}

let statsPending = false;
async function pollStats() {
  if (statsPending) return; statsPending = true; const stateRevision=modelStateRevision;
  try {
    const s = await requestJSON("/api/stats", {signal:AbortSignal.timeout(20000)});
    if(stateRevision!==modelStateRevision||engineBusy)return;
    updatePreparation(s.preparation);
    $("#engineCard").classList.toggle("online", !!s.loaded);
    setEngineState(s.engine_online !== false);
    $("#connection").classList.add("online"); $("#connectionText").textContent = "Agente conectado";
    setLoadedModel(s.loaded?(s.model||loadedModel):null,true,s.context_usage?.limit??s.context??null);
    renderHardwareStats(s);
  } catch (e) {
    if(stateRevision!==modelStateRevision||engineBusy)return;
    setLoadedModel(null,false);
    $("#engineCard").classList.remove("online");
    $("#connection").classList.remove("online"); $("#connectionText").textContent = "Sin conexión";
    renderHardwareStats(null); updateContextMeter(null);
  } finally { statsPending=false; }
}
