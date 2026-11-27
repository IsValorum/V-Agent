/* Load controls are per-model. Estimates are debounced and only requested in the open model window. */
const LOAD_DEFAULTS={auto:true,parallel:1,batch:0,ubatch:0,checkpoints:1,gpu_layers:-1,cpu_moe:0,fit_target:0};
// Automatic llama.cpp keeps 8 context checkpoints (load_settings.AUTO_CHECKPOINTS): hybrid and sliding-window
// models reuse the conversation from them instead of reading it again every turn (issue #2).
const LLAMA_AUTO_CHECKPOINTS=8;
function shownCheckpoints(load){return activeEngine==='llama'&&load.auto&&load.checkpoints===LOAD_DEFAULTS.checkpoints?LLAMA_AUTO_CHECKPOINTS:load.checkpoints;}
// llama.cpp only: automatic = --fit (fit_target is its VRAM margin); manual = layers by hand.
const LOAD_LLAMA_FIELDS=new Set(['gpu_layers','cpu_moe','fit_target']);
const DRAFT_DEFAULTS={enabled:false,path:'',type:'auto',max:3,min:0};
let loadCurrent={...LOAD_DEFAULTS},draftCurrent={...DRAFT_DEFAULTS},memoryTimer=0,memoryController=null,memoryKey='',memoryLast=null,loadCapabilities=null;
function setupLoadSettings(){
  const group=document.createElement('section');group.id='modelLoadSettings';group.className='sec';group.innerHTML='<h4>Carga del motor</h4><div class="load-mode"><button type="button" data-load-auto="true">Automático</button><button type="button" data-load-auto="false">Personalizado</button></div>'+[['parallel','Slots paralelos','Un slot para un agente personal. Auto usa 1; más slots multiplican el contexto reservado.'],['batch','Tamaño de lote','Tokens máximos procesados juntos. Auto usa el valor del motor.'],['ubatch','Tamaño de microlote','Lote físico: bajarlo puede reducir memoria. No debe superar Batch.'],['checkpoints','Puntos de control del contexto','Estados reutilizables de contexto. Más checkpoints pueden consumir más memoria.'],['fit_target','Margen de VRAM (MiB)','Memoria que --fit deja libre en la GPU. Auto usa 1024 MiB.'],['gpu_layers','Capas en GPU','Cuántas capas van a la VRAM (-ngl). Escribe un número o Todas; Auto usa el ajuste del motor.'],['cpu_moe','Capas con expertos en la CPU','Capas cuyos expertos se quedan en la RAM (--n-cpu-moe). Ideal para modelos MoE en GPU pequeña.']].map(([key,label,help])=>'<div class="setting-row" data-load-field="'+key+'"><label for="load_'+key+'" title="'+help+'">'+label+' <span class="load-help" aria-hidden="true">?</span></label><input id="load_'+key+'" inputmode="numeric" autocomplete="off" placeholder="Auto" aria-label="'+label+'" title="'+help+'"></div>').join('')+'<p id="loadSettingsStatus" class="mini" role="status"></p>';
  const pane=document.getElementById('model-load-pane'),advanced=document.getElementById('loadAdvanced');if(advanced)advanced.before(group);else pane.append(group);
  const memory=document.createElement('details');memory.id='modelMemoryEstimate';memory.className='settings-group';memory.open=false;memory.innerHTML='<summary><span>Desglose de memoria</span><span id="memoryHeadline" class="mini"></span></summary><div class="memory-estimate-body"><div class="memory-total"><span id="memoryGpuLabel">GPU</span><strong id="memoryGpu">—</strong><span>Total</span><strong id="memoryTotal">—</strong></div><div id="memoryBreakdown"></div><p id="memoryShape" class="mini"></p><p id="memoryWarning" role="status"></p><p id="memoryNotes" class="mini memory-notes"></p></div>';
  const contextBlock=document.getElementById('contextBlock'),contextWarn=document.getElementById('contextMemoryWarning');
  if(contextBlock){if(contextWarn)contextWarn.before(memory);else contextBlock.append(memory);}else pane.prepend(memory);
  pane.prepend(group);
  for(const button of group.querySelectorAll('[data-load-auto]'))button.onclick=()=>{loadCurrent=button.dataset.loadAuto==='true'?{...LOAD_DEFAULTS}:{...loadCurrent,auto:false};queueModelPreferences();syncLoadSettings();};
  for(const [key,limit] of Object.entries({parallel:32,batch:65536,ubatch:8192,checkpoints:64,gpu_layers:999,cpu_moe:999,fit_target:65536})){
    const input=document.getElementById('load_'+key);
    input.onchange=()=>{const text=input.value.trim().toLowerCase(),automatic=text===''||text==='auto'||text===uiText('Auto').toLowerCase();
      const all=key==='gpu_layers'&&['todas','all',uiText('Todas').toLowerCase()].includes(text);
      const value=all?999:automatic?(key==='checkpoints'?1:key==='gpu_layers'?-1:0):Number(text);const valid=Number.isInteger(value)&&(value>=0||(key==='gpu_layers'&&value===-1))&&value<=limit;
      input.setAttribute('aria-invalid',String(!valid));if(!valid){document.getElementById('loadSettingsStatus').textContent='Escribe Auto o un número válido.';return;}
      const next={...loadCurrent,[key]:value};if(next.batch&&next.ubatch>next.batch){input.setAttribute('aria-invalid','true');document.getElementById('loadSettingsStatus').textContent='Microbatch no puede superar Batch.';return;}
      loadCurrent=next;queueModelPreferences();syncLoadSettings();};
  }
  const draft=document.createElement('div');draft.id='modelDraftSettings';draft.className='draft-speculative';
  draft.innerHTML='<h5>Modelo borrador (especulativo)</h5><label class="chk"><input id="llamaDraftEnabled" type="checkbox"> Usar modelo borrador</label>'+
    '<div class="draft-path"><input id="llamaDraftPath" type="text" readonly placeholder="Ningún GGUF draft" aria-label="Archivo draft"><button id="llamaDraftBrowse" type="button">Elegir…</button></div>'+
    '<div class="setting-row"><label for="llamaDraftType">Tipo de borrador</label><select id="llamaDraftType"><option value="auto">Automático</option><option value="draft-simple">Simple</option><option value="draft-eagle3">Eagle3</option><option value="draft-mtp">MTP</option><option value="draft-dflash">DFlash</option><option value="draft-dspark">DSpark</option></select></div>'+
    '<div class="setting-row"><label for="llamaDraftMax">Tokens propuestos (máx.)</label><input id="llamaDraftMax" type="number" min="1" max="32" inputmode="numeric"></div>'+
    '<div class="setting-row"><label for="llamaDraftMin">Tokens propuestos (mín.)</label><input id="llamaDraftMin" type="number" min="0" inputmode="numeric"></div>'+
    '<p id="llamaDraftStatus" class="mini" role="status"></p>';
  document.getElementById('loadSettingsStatus').before(draft);
  const draftChanged=()=>{draftCurrent={...draftCurrent,enabled:document.getElementById('llamaDraftEnabled').checked,type:document.getElementById('llamaDraftType').value,max:Number(document.getElementById('llamaDraftMax').value)||3,min:Number(document.getElementById('llamaDraftMin').value)||0};queueModelPreferences();syncLoadSettings();requestMemoryEstimate(true);};
  document.getElementById('llamaDraftEnabled').onchange=()=>{draftCurrent.enabled=document.getElementById('llamaDraftEnabled').checked;if(draftCurrent.enabled&&!draftCurrent.path){document.getElementById('llamaDraftBrowse').click();return;}draftChanged();};
  document.getElementById('llamaDraftType').onchange=draftChanged;
  document.getElementById('llamaDraftMax').onchange=()=>{const value=Math.max(1,Math.min(32,Math.round(Number(document.getElementById('llamaDraftMax').value)||3)));document.getElementById('llamaDraftMax').value=value;if(draftCurrent.min>value){draftCurrent.min=value;document.getElementById('llamaDraftMin').value=value;}draftChanged();};
  document.getElementById('llamaDraftMin').onchange=()=>{const max=Number(document.getElementById('llamaDraftMax').value)||3;const value=Math.max(0,Math.min(max,Math.round(Number(document.getElementById('llamaDraftMin').value)||0)));document.getElementById('llamaDraftMin').value=value;draftChanged();};
  document.getElementById('llamaDraftBrowse').onclick=async()=>{if(refuseWhileBusy())return;try{const picked=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'draft'}),signal:AbortSignal.timeout(310000)});if(picked.path){draftCurrent={...draftCurrent,path:picked.path,enabled:true};document.getElementById('llamaDraftEnabled').checked=true;queueModelPreferences();syncLoadSettings();requestMemoryEstimate(true);}}catch(error){document.getElementById('llamaDraftStatus').textContent=error.message;}};
  document.getElementById('composerControls').addEventListener('fw:open',()=>requestMemoryEstimate(true));
  document.getElementById('composerControls').addEventListener('fw:close',()=>{clearTimeout(memoryTimer);memoryController?.abort();});
  syncLoadSettings();
  if(typeof attachLoadSettingsToPanel==='function')attachLoadSettingsToPanel();
  setupEngineOptions();
}
function syncLoadSettings(estimate=true){
  const group=document.getElementById('modelLoadSettings');if(!group)return;
  const currentModel=document.getElementById('model').value;
  loadCurrent={...LOAD_DEFAULTS,...modelPreferences[currentModel]?.load};draftCurrent={...DRAFT_DEFAULTS,...modelPreferences[currentModel]?.draft};
  group.hidden=!['llama','strata'].includes(activeEngine);document.getElementById('modelMemoryEstimate').hidden=activeEngine==='api';
  const draftBox=document.getElementById('modelDraftSettings');
  if(draftBox){draftBox.hidden=activeEngine!=='llama';const enabled=document.getElementById('llamaDraftEnabled'),path=document.getElementById('llamaDraftPath'),type=document.getElementById('llamaDraftType'),max=document.getElementById('llamaDraftMax'),min=document.getElementById('llamaDraftMin');enabled.checked=!!draftCurrent.enabled;path.value=draftCurrent.path||'';type.value=draftCurrent.type||'auto';max.value=draftCurrent.max||3;min.value=draftCurrent.min||0;enabled.disabled=busy||engineBusy;for(const input of [path,type,max,min])input.disabled=busy||engineBusy||!draftCurrent.enabled;const label=type.options[type.selectedIndex]?.textContent||uiText('Automático');const status=document.getElementById('llamaDraftStatus');status.textContent=!draftCurrent.enabled?uiText('Sin draft: el modelo principal responde solo.'):!draftCurrent.path?uiText('Elige un GGUF draft compatible.'):(draftCurrent.path.split(/[\\/]/).pop()+' · '+uiText(label)+' · '+draftCurrent.max+' tokens · '+uiText('suma memoria y debe ser compatible con el modelo principal.'));}
  for(const key of ['parallel','batch','ubatch','checkpoints']){const input=document.getElementById('load_'+key);input.closest('.setting-row').hidden=activeEngine==='strata'&&key!=='checkpoints';if(document.activeElement!==input)input.value=loadCurrent.auto&&key!=='checkpoints'?uiText('Auto'):loadCurrent[key]===0&&key!=='checkpoints'?uiText('Auto'):key==='checkpoints'?shownCheckpoints(loadCurrent):loadCurrent[key];input.disabled=(loadCurrent.auto&&!(key==='checkpoints'&&activeEngine==='llama'))||busy||engineBusy||(key==='checkpoints'&&activeEngine==='llama'&&loadCapabilities?.checkpoints===false);}
  // llama.cpp: the VRAM margin belongs to automatic (--fit); layers and MoE experts to manual.
  const layers=memoryLast?.memory?.block_count,moe=memoryLast?.memory?.moe!==false;
  for(const key of LOAD_LLAMA_FIELDS){const input=document.getElementById('load_'+key),row=input.closest('.setting-row');
    row.hidden=activeEngine!=='llama'||(key==='fit_target'?!loadCurrent.auto||loadCapabilities?.fit===false:loadCurrent.auto)||(key==='cpu_moe'&&(!moe||loadCapabilities?.cpu_moe===false));
    const value=loadCurrent[key];if(document.activeElement!==input)input.value=key==='gpu_layers'?(value<0?uiText('Auto'):value>=999?uiText('Todas'):value):value?value:uiText('Auto');
    input.placeholder=key==='gpu_layers'&&layers?uiText('Auto')+' · '+layers+' '+uiText('capas'):uiText('Auto');input.disabled=busy||engineBusy;}
  for(const button of group.querySelectorAll('[data-load-auto]')){button.setAttribute('aria-pressed',String(String(loadCurrent.auto)===button.dataset.loadAuto));button.disabled=busy||engineBusy;}
  const status=document.getElementById('loadSettingsStatus');
  if(activeEngine==='llama')status.textContent=loadCurrent.auto?uiText('Automático: llama.cpp ajusta capas y contexto a tu memoria (--fit).'):uiText('Personalizado: tú eliges las capas (sin --fit). Se aplicará en la próxima carga.')+(layers?' '+uiText('El modelo tiene')+' '+layers+' '+uiText('capas')+'.':'');
  else status.textContent=loadCurrent.auto?uiText('Automático: 1 slot, lotes del motor y 1 checkpoint.'):uiText('Se aplicará en la próxima carga manual.');
  // A hybrid (SSM + attention) model with 0 or 1 checkpoint reads the whole conversation again every turn.
  if(activeEngine==='llama'&&(memoryLast?.memory?.recurrent||0)>0&&shownCheckpoints(loadCurrent)<=1)
    status.textContent+=' '+uiText('Este modelo es híbrido: con 1 checkpoint o menos vuelve a leer toda la conversación en cada turno. Usa 4 o más.');
  syncEngineOptions();
  if(estimate)requestMemoryEstimate();
}
// A memory warning goes under the context control, where it is seen; the copy inside the folded
// "Desglose de memoria" is used only when that control is missing.
function showMemoryWarning(text){
  const warning=document.getElementById('memoryWarning'),block=document.getElementById('contextBlock');
  let shown=document.getElementById('contextMemoryWarning');
  if(!shown&&block){shown=document.createElement('p');shown.id='contextMemoryWarning';shown.className='context-memory-warning';shown.setAttribute('role','status');block.append(shown);}
  if(shown){shown.textContent=text;shown.hidden=!text;}
  if(warning){warning.textContent=shown?'':text;warning.hidden=!!shown||!text;}
}
function memoryGiB(value){return typeof value==='number'?'≈ '+(value/2**30).toLocaleString(window.VALI18n?.locale||undefined,{maximumFractionDigits:2})+' GiB':uiText('No disponible');}
function paintMemory(data,resync=true){
  memoryLast=data;loadCapabilities=data.capabilities;
  if(!data.memory){
    const warning=document.getElementById('memoryWarning');
    document.getElementById('memoryHeadline').textContent=uiText('No disponible');
    for(const id of ['memoryGpu','memoryTotal'])document.getElementById(id).textContent='—';
    document.getElementById('memoryGpu').dataset.exceeds='false';
    document.getElementById('memoryGpuLabel').textContent='GPU';
    document.getElementById('memoryBreakdown').replaceChildren();
    for(const id of ['memoryShape','memoryNotes','contextMemory','contextMemoryWarning']){
      const element=document.getElementById(id);if(element)element.textContent='';
    }
    showMemoryWarning(uiText(data.reason||''));
    return;
  }
  if(resync)syncLoadSettings();const m=data.memory,h=m.hardware||{};document.getElementById('memoryHeadline').textContent=memoryGiB(m.total);{const cm=document.getElementById('contextMemory');if(cm)cm.textContent=uiText('Memoria')+' '+memoryGiB(m.total);}document.getElementById('memoryTotal').textContent=memoryGiB(m.total);
  document.getElementById('memoryGpuLabel').textContent=uiText(['strata','rust'].includes(activeEngine)?'GPU (base)':'GPU con descarga completa');document.getElementById('memoryGpu').textContent=memoryGiB(m.gpu_full_offload);
  const breakdown=document.getElementById('memoryBreakdown');breakdown.replaceChildren();for(const [label,key] of [['Pesos','weights'],['Caché KV','kv'],['Estados y checkpoints','recurrent'],['Buffers','buffers']]){const row=document.createElement('div'),title=document.createElement('span'),value=document.createElement('span');row.className='memory-detail';title.textContent=uiText(label);value.textContent=memoryGiB(m[key]);row.append(title,value);breakdown.append(row);}
  document.getElementById('memoryShape').textContent=m.kv_type+' · '+m.context_per_slot.toLocaleString(window.VALI18n?.locale||undefined)+' tokens/slot · '+m.slots+' slots';
  const warning=document.getElementById('memoryWarning'),gpu=document.getElementById('memoryGpu');const isLlama=activeEngine==='llama';const freeGpu=typeof h.gpu_effective_available==='number'?h.gpu_effective_available:h.gpu_available;const exceeds=isLlama&&typeof freeGpu==='number'&&m.gpu_full_offload>freeGpu;gpu.dataset.exceeds=String(exceeds);
  showMemoryWarning(exceeds?uiText('La descarga completa supera la VRAM libre. Automático puede dejar capas en CPU; la generación será más lenta.'):typeof h.ram_available==='number'&&m.total>h.ram_available+(freeGpu||0)?uiText('La estimación supera la memoria libre del equipo. Reduce contexto o cambia la caché KV.'):'');
  document.getElementById('memoryNotes').textContent=uiText('Estimación, no reserva de memoria.')+' '+m.notes.map(note=>uiText(note)).join(' ');
}
window.refreshLoadSettingsTranslations=()=>{syncLoadSettings(false);if(memoryLast&&document.getElementById('modelMemoryEstimate'))paintMemory(memoryLast,false);};
function requestMemoryEstimate(force=false){
  if(!document.getElementById('modelMemoryEstimate'))return;
  clearTimeout(memoryTimer);const model=document.getElementById('model')?.value;if(!model||activeEngine==='api'||!document.getElementById('modelMemoryEstimate'))return;
  if(!window.VALWindows?.isOpen('model'))return;
  const payload={model,context:Number(document.getElementById('ctxInput').value),kv:document.getElementById('kvCache').value,load:{...loadCurrent},draft:{...draftCurrent}};
  const key=JSON.stringify([activeEngine,engineSnapshot?.llama,payload]);if(!force&&key===memoryKey)return;
  memoryController?.abort();const controller=new AbortController();memoryController=controller;
  memoryTimer=setTimeout(async()=>{const warn=document.getElementById('memoryWarning');for(const id of ['memoryGpu','memoryTotal'])document.getElementById(id).textContent='—';document.getElementById('memoryBreakdown').replaceChildren();document.getElementById('memoryShape').textContent='';warn.textContent='';warn.hidden=true;document.getElementById('memoryHeadline').textContent=uiText('Calculando…');try{const result=await requestJSON('/api/harness/memory-estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});if(memoryController!==controller)return;memoryKey=key;paintMemory(result);}catch(error){if(error.name==='AbortError'||memoryController!==controller)return;paintMemory({memory:null,reason:error.message},false);}},240);
}

/* Engine options: everything else llama.cpp, Strata and Strata Rust accept (Flash Attention, threads,
   RoPE, LoRA, expert placement…). The core sends the catalog of the installed executable; an empty
   field is the engine's own default and passes nothing. Saved per model with the other preferences. */
const ENGINE_OPTION_KINDS=['llama','strata','rust','maya'];
const ENGINE_CHOICE_LABELS={auto:'Automático',on:'Activado',off:'Desactivado',none:'Ninguno',layer:'Por capas',row:'Por filas',
  tensor:'Por tensores',linear:'Lineal',yarn:'YaRN',distribute:'Distribuir',isolate:'Aislar',numactl:'numactl',dio:'DirectIO',
  cuda:'CUDA',vulkan:'Vulkan'};
let engineOptionsCatalog=null,engineCurrent={};
function engineOptionsChanged(){return Object.values(engineCurrent).filter(value=>value!==null&&value!==undefined).length;}
function setupEngineOptions(){
  if(document.getElementById('engineOptions'))return;
  const box=document.createElement('details');box.id='engineOptions';box.className='settings-group engine-options';
  box.innerHTML='<summary><span id="engineOptionsTitle"></span><span id="engineOptionsCount" class="mini"></span></summary>'+
    '<div id="engineOptionsBody" class="engine-options-body"></div><p id="engineOptionsStatus" class="mini" role="status"></p>';
  // In the Advanced tab, right after the engine's load settings, always listed (folded) for an engine that has
  // options: it used to stay hidden until the small "Advanced settings" button of the engine card was found.
  if(!placeEngineOptions(box))return;
  box.addEventListener('toggle',()=>{if(box.open)loadEngineOptions();syncEngineOptionsButton();});
  document.getElementById('composerControls')?.addEventListener('fw:open',()=>{engineOptionsCatalog=null;syncEngineOptions();});
  window.VALI18n?.onChange?.(()=>renderEngineOptions());
  syncEngineOptions();
}
const ENGINE_OPTION_NAMES={llama:'llama.cpp',strata:'Strata',rust:'Strata Rust',maya:'Project Maya'};
function placeEngineOptions(box){
  const after=document.getElementById('engineLoadGroup'),pane=document.getElementById('model-load-pane');
  if(after){if(after.nextElementSibling!==box)after.after(box);return true;}
  if(!pane)return false;
  const advanced=document.getElementById('loadAdvanced');
  if(advanced){if(advanced.previousElementSibling!==box)advanced.before(box);}else if(box.parentElement!==pane)pane.append(box);
  return true;
}
function syncEngineOptionsButton(){
  const box=document.getElementById('engineOptions'),button=document.getElementById('mayaQuickAdvanced');
  if(box&&button)button.setAttribute('aria-expanded',String(!box.hidden&&box.open));
  const badge=document.getElementById('engineOptionsBadge'),count=engineOptionsChanged();
  if(badge){badge.hidden=!count;badge.textContent=count?String(count):'';badge.title=count?uiText('Cambiadas')+': '+count:'';}
}
function toggleEngineOptions(){
  // The engine card's "Advanced settings": go to the Advanced tab and unfold the engine's options there.
  const box=document.getElementById('engineOptions');if(!box||!ENGINE_OPTION_KINDS.includes(activeEngine))return;
  placeEngineOptions(box);box.hidden=false;
  if(typeof setModelSection==='function')setModelSection('load');
  box.open=true;loadEngineOptions();syncEngineOptionsButton();
  requestAnimationFrame(()=>box.scrollIntoView({block:'start',behavior:'smooth'}));
}
function syncEngineOptions(){
  const box=document.getElementById('engineOptions');if(!box)return;
  placeEngineOptions(box);box.hidden=!ENGINE_OPTION_KINDS.includes(activeEngine);
  syncEngineOptionsButton();
  const model=document.getElementById('model')?.value;engineCurrent={...(modelPreferences[model]?.engine||{})};
  if(engineOptionsCatalog&&(engineOptionsCatalog.engine!==activeEngine||activeEngine==='maya'&&(engineOptionsCatalog.model||'')!==(model||'')))engineOptionsCatalog=null;
  // Called on every memory estimate: redraw only when something shown changed, so a value being
  // typed, its focus and an "invalid" mark are not wiped out.
  const signature=JSON.stringify([activeEngine,model,engineCurrent,!!engineOptionsCatalog,busy||engineBusy]);
  if(box.dataset.signature===signature)return;
  if(box.open&&!box.hidden)loadEngineOptions();else renderEngineOptions();
}
async function loadEngineOptions(){
  if(!ENGINE_OPTION_KINDS.includes(activeEngine))return;
  // Each Project Maya model runs its own binary, so its options are read per model.
  const model=document.getElementById('model')?.value||'';
  const forModel=activeEngine==='maya'?model:'';
  if(engineOptionsCatalog?.engine===activeEngine&&(engineOptionsCatalog.model||'')===forModel){renderEngineOptions();return;}
  const status=document.getElementById('engineOptionsStatus');status.textContent=uiText('Leyendo las opciones del motor…');
  try{engineOptionsCatalog=await requestJSON('/api/harness/engine-options'+(forModel?'?model='+encodeURIComponent(forModel):''),{cache:'no-store',signal:AbortSignal.timeout(30000)});
    engineOptionsCatalog.model=forModel;}
  catch(error){status.textContent=uiText('No se pudieron leer las opciones del motor.')+' '+error.message;return;}
  renderEngineOptions();
}
function engineOptionSet(option,value){
  engineCurrent={...engineCurrent,[option.key]:value};
  // The value is already on screen: mark it drawn so saving it does not redraw the list.
  const box=document.getElementById('engineOptions'),model=document.getElementById('model')?.value;
  box.dataset.signature=JSON.stringify([activeEngine,model,engineCurrent,!!engineOptionsCatalog,busy||engineBusy]);
  queueModelPreferences();
  const count=engineOptionsChanged();
  document.getElementById('engineOptionsCount').textContent=count?uiText('Cambiadas')+': '+count:'';syncEngineOptionsButton();
  document.getElementById('engineOptionsStatus').textContent=uiText('Se aplicará en la próxima carga del modelo.');
}
function renderEngineOptions(){
  const body=document.getElementById('engineOptionsBody');if(!body)return;
  const box=document.getElementById('engineOptions'),model=document.getElementById('model')?.value;
  box.dataset.signature=JSON.stringify([activeEngine,model,engineCurrent,!!engineOptionsCatalog,busy||engineBusy]);
  document.getElementById('engineOptionsTitle').textContent=uiText('Opciones del motor')+(ENGINE_OPTION_NAMES[activeEngine]?' · '+ENGINE_OPTION_NAMES[activeEngine]:'');
  const data=engineOptionsCatalog;body.replaceChildren();
  const status=document.getElementById('engineOptionsStatus'),count=engineOptionsChanged();
  document.getElementById('engineOptionsCount').textContent=count?uiText('Cambiadas')+': '+count:'';syncEngineOptionsButton();
  if(!data||data.engine!==activeEngine){status.textContent='';return;}
  if(!data.options.length){status.textContent=uiText(data.probed?'Este motor no ofrece más opciones.':'Instala el motor para ver sus opciones.');return;}
  status.textContent=uiText('Vacío = valor por defecto del motor. Se aplica al cargar el modelo.');
  const locked=busy||engineBusy;
  const arch=(modelKV[model]?.architecture||'').toLowerCase();
  for(const group of data.groups){
    const options=data.options.filter(option=>option.group===group.id&&(!option.archs||!arch||option.archs.includes(arch)));if(!options.length)continue;
    const heading=document.createElement('h5');heading.textContent=uiText(group.label);body.append(heading);
    for(const option of options){
      const row=document.createElement('div');row.className='setting-row engine-option';row.dataset.option=option.key;
      const id='engopt_'+option.key,label=document.createElement('label');label.htmlFor=id;label.textContent=uiText(option.label);
      const help=document.createElement('p');help.className='mini engine-option-help';help.textContent=uiText(option.help);
      const current=engineCurrent[option.key];let control;
      if(option.kind==='bool'){
        control=document.createElement('input');control.type='checkbox';control.checked=current===true;
        control.onchange=()=>engineOptionSet(option,control.checked?true:null);
      }else if(option.kind==='switch'||option.kind==='choice'){
        control=document.createElement('select');
        const values=option.kind==='switch'?[['',uiText('Por defecto')],['true',uiText('Activado')],['false',uiText('Desactivado')]]
          :[['',uiText('Por defecto')],...option.choices.map(value=>[value,uiText(option.labels?.[value]||ENGINE_CHOICE_LABELS[value]||value)])];
        for(const [value,text] of values){const item=document.createElement('option');item.value=value;item.textContent=text;control.append(item);}
        control.value=current===null||current===undefined?'':String(current);
        control.onchange=()=>engineOptionSet(option,control.value===''?null:option.kind==='switch'?control.value==='true':control.value);
      }else{
        control=document.createElement('input');control.type='text';control.spellcheck=false;
        control.placeholder=uiText('Por defecto');control.value=current===null||current===undefined?'':String(current);
        if(option.kind!=='text')control.inputMode=option.kind==='int'?'numeric':'decimal';
        control.onchange=()=>{
          let text=control.value.trim();
          if(!text){control.setAttribute('aria-invalid','false');engineOptionSet(option,null);return;}
          if(option.kind==='float')text=text.replace(',','.');
          let value=text,valid;
          if(option.kind!=='text'){value=Number(text);valid=Number.isFinite(value)&&(option.kind!=='int'||Number.isInteger(value))&&value>=option.min&&value<=option.max;}
          else valid=new RegExp('^(?:'+option.pattern+')$').test(text);
          control.setAttribute('aria-invalid',String(!valid));
          if(!valid){status.textContent=uiText('Valor no válido para')+' «'+uiText(option.label)+'»'+(option.kind==='text'?'':' ('+option.min+'–'+option.max+')');return;}
          engineOptionSet(option,value);
        };
      }
      control.id=id;control.disabled=locked;control.title=option.flag;
      row.append(label,control,help);body.append(row);
    }
  }
}
