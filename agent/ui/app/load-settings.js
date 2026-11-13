/* Load controls are per-model. Estimates are debounced and only requested in the open model window. */
const LOAD_DEFAULTS={auto:true,parallel:1,batch:0,ubatch:0,checkpoints:1,gpu_layers:-1,cpu_moe:0,fit_target:0};
// llama.cpp only: automatic = --fit (fit_target is its VRAM margin); manual = layers by hand.
const LOAD_LLAMA_FIELDS=new Set(['gpu_layers','cpu_moe','fit_target']);
const DRAFT_DEFAULTS={enabled:false,path:'',type:'auto',max:3,min:0};
let loadCurrent={...LOAD_DEFAULTS},draftCurrent={...DRAFT_DEFAULTS},memoryTimer=0,memoryController=null,memoryKey='',memoryLast=null,loadCapabilities=null;
function setupLoadSettings(){
  const group=document.createElement('section');group.id='modelLoadSettings';group.className='sec';group.innerHTML='<h4>Carga del motor</h4><div class="load-mode"><button type="button" data-load-auto="true">Automático</button><button type="button" data-load-auto="false">Personalizado</button></div>'+[['parallel','Slots paralelos','Un slot para un agente personal. Auto usa 1; más slots multiplican el contexto reservado.'],['batch','Batch size','Tokens máximos procesados juntos. Auto usa el valor del motor.'],['ubatch','Microbatch size','Lote físico: bajarlo puede reducir memoria. No debe superar Batch.'],['checkpoints','Context checkpoints','Estados reutilizables de contexto. Más checkpoints pueden consumir más memoria.'],['fit_target','Margen de VRAM (MiB)','Memoria que --fit deja libre en la GPU. Auto usa 1024 MiB.'],['gpu_layers','Capas en GPU','Cuántas capas van a la VRAM (-ngl). Escribe un número o Todas; Auto usa el ajuste del motor.'],['cpu_moe','Expertos MoE en CPU','Capas cuyos expertos se quedan en la RAM (--n-cpu-moe). Ideal para modelos MoE en GPU pequeña.']].map(([key,label,help])=>'<div class="setting-row" data-load-field="'+key+'"><label for="load_'+key+'" title="'+help+'">'+label+' <span class="load-help" aria-hidden="true">?</span></label><input id="load_'+key+'" inputmode="numeric" autocomplete="off" placeholder="Auto" aria-label="'+label+'" title="'+help+'"></div>').join('')+'<p id="loadSettingsStatus" class="mini" role="status"></p>';
  const pane=document.getElementById('model-load-pane'),advanced=document.getElementById('loadAdvanced');if(advanced)advanced.before(group);else pane.append(group);
  const memory=document.createElement('details');memory.id='modelMemoryEstimate';memory.className='settings-group';memory.open=false;memory.innerHTML='<summary>Memoria estimada <span id="memoryHeadline" class="mini"></span></summary><div class="memory-estimate-body"><div class="memory-total"><span id="memoryGpuLabel">GPU</span><strong id="memoryGpu">—</strong><span>Total</span><strong id="memoryTotal">—</strong></div><div id="memoryBreakdown"></div><p id="memoryShape" class="mini"></p><p id="memoryWarning" role="status"></p><details><summary>Cómo se calcula</summary><p id="memoryNotes" class="mini"></p></details></div>';
  pane.prepend(memory);memory.after(group);
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
  draft.innerHTML='<h5>Draft especulativo</h5><label class="chk"><input id="llamaDraftEnabled" type="checkbox"> Usar modelo draft</label>'+
    '<div class="draft-path"><input id="llamaDraftPath" type="text" readonly placeholder="Ningún GGUF draft" aria-label="Archivo draft"><button id="llamaDraftBrowse" type="button">Elegir…</button></div>'+
    '<div class="setting-row"><label for="llamaDraftType">Tipo de draft</label><select id="llamaDraftType"><option value="auto">Automático</option><option value="draft-simple">Simple</option><option value="draft-eagle3">Eagle3</option><option value="draft-mtp">MTP</option><option value="draft-dflash">DFlash</option><option value="draft-dspark">DSpark</option></select></div>'+
    '<div class="setting-row"><label for="llamaDraftMax">Tokens máximos</label><input id="llamaDraftMax" type="number" min="1" max="32" inputmode="numeric"></div>'+
    '<div class="setting-row"><label for="llamaDraftMin">Tokens mínimos</label><input id="llamaDraftMin" type="number" min="0" inputmode="numeric"></div>'+
    '<p id="llamaDraftStatus" class="mini" role="status"></p>';
  document.getElementById('loadSettingsStatus').before(draft);
  const draftChanged=()=>{draftCurrent={...draftCurrent,enabled:document.getElementById('llamaDraftEnabled').checked,type:document.getElementById('llamaDraftType').value,max:Number(document.getElementById('llamaDraftMax').value)||3,min:Number(document.getElementById('llamaDraftMin').value)||0};queueModelPreferences();syncLoadSettings();requestMemoryEstimate(true);};
  document.getElementById('llamaDraftEnabled').onchange=()=>{draftCurrent.enabled=document.getElementById('llamaDraftEnabled').checked;if(draftCurrent.enabled&&!draftCurrent.path){document.getElementById('llamaDraftBrowse').click();return;}draftChanged();};
  document.getElementById('llamaDraftType').onchange=draftChanged;
  document.getElementById('llamaDraftMax').onchange=()=>{const value=Math.max(1,Math.min(32,Math.round(Number(document.getElementById('llamaDraftMax').value)||3)));document.getElementById('llamaDraftMax').value=value;if(draftCurrent.min>value){draftCurrent.min=value;document.getElementById('llamaDraftMin').value=value;}draftChanged();};
  document.getElementById('llamaDraftMin').onchange=()=>{const max=Number(document.getElementById('llamaDraftMax').value)||3;const value=Math.max(0,Math.min(max,Math.round(Number(document.getElementById('llamaDraftMin').value)||0)));document.getElementById('llamaDraftMin').value=value;draftChanged();};
  document.getElementById('llamaDraftBrowse').onclick=async()=>{if(busy||engineBusy)return;try{const picked=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'draft'}),signal:AbortSignal.timeout(310000)});if(picked.path){draftCurrent={...draftCurrent,path:picked.path,enabled:true};document.getElementById('llamaDraftEnabled').checked=true;queueModelPreferences();syncLoadSettings();requestMemoryEstimate(true);}}catch(error){document.getElementById('llamaDraftStatus').textContent=error.message;}};
  document.getElementById('composerControls').addEventListener('fw:open',()=>requestMemoryEstimate(true));
  document.getElementById('composerControls').addEventListener('fw:close',()=>{clearTimeout(memoryTimer);memoryController?.abort();});
  syncLoadSettings();
  if(typeof attachLoadSettingsToPanel==='function')attachLoadSettingsToPanel();
}
function syncLoadSettings(){
  const group=document.getElementById('modelLoadSettings');if(!group)return;
  const currentModel=document.getElementById('model').value;
  loadCurrent={...LOAD_DEFAULTS,...modelPreferences[currentModel]?.load};draftCurrent={...DRAFT_DEFAULTS,...modelPreferences[currentModel]?.draft};
  group.hidden=!['llama','strata'].includes(activeEngine);document.getElementById('modelMemoryEstimate').hidden=activeEngine==='api';
  const draftBox=document.getElementById('modelDraftSettings');
  if(draftBox){draftBox.hidden=activeEngine!=='llama';const enabled=document.getElementById('llamaDraftEnabled'),path=document.getElementById('llamaDraftPath'),type=document.getElementById('llamaDraftType'),max=document.getElementById('llamaDraftMax'),min=document.getElementById('llamaDraftMin');enabled.checked=!!draftCurrent.enabled;path.value=draftCurrent.path||'';type.value=draftCurrent.type||'auto';max.value=draftCurrent.max||3;min.value=draftCurrent.min||0;enabled.disabled=busy||engineBusy;for(const input of [path,type,max,min])input.disabled=busy||engineBusy||!draftCurrent.enabled;const label=type.options[type.selectedIndex]?.textContent||'Automático';const status=document.getElementById('llamaDraftStatus');status.textContent=!draftCurrent.enabled?'Sin draft: el modelo principal responde solo.':!draftCurrent.path?'Elige un GGUF draft compatible.':(draftCurrent.path.split(/[\\/]/).pop()+' · '+label+' · '+draftCurrent.max+' tokens · suma memoria y debe ser compatible con el modelo principal.');}
  for(const key of ['parallel','batch','ubatch','checkpoints']){const input=document.getElementById('load_'+key);input.closest('.setting-row').hidden=activeEngine==='strata'&&key!=='checkpoints';if(document.activeElement!==input)input.value=loadCurrent.auto&&key!=='checkpoints'?'Auto':loadCurrent[key]===0&&key!=='checkpoints'?'Auto':loadCurrent[key];input.disabled=loadCurrent.auto||busy||engineBusy||(key==='checkpoints'&&activeEngine==='llama'&&loadCapabilities?.checkpoints===false);}
  // llama.cpp: the VRAM margin belongs to automatic (--fit); layers and MoE experts to manual.
  const layers=memoryLast?.memory?.block_count,moe=memoryLast?.memory?.moe!==false;
  for(const key of LOAD_LLAMA_FIELDS){const input=document.getElementById('load_'+key),row=input.closest('.setting-row');
    row.hidden=activeEngine!=='llama'||(key==='fit_target'?!loadCurrent.auto||loadCapabilities?.fit===false:loadCurrent.auto)||(key==='cpu_moe'&&(!moe||loadCapabilities?.cpu_moe===false));
    const value=loadCurrent[key];if(document.activeElement!==input)input.value=key==='gpu_layers'?(value<0?uiText('Auto'):value>=999?uiText('Todas'):value):value?value:uiText('Auto');
    input.placeholder=key==='gpu_layers'&&layers?uiText('Auto')+' · '+layers+' '+uiText('capas'):uiText('Auto');input.disabled=busy||engineBusy;}
  for(const button of group.querySelectorAll('[data-load-auto]')){button.setAttribute('aria-pressed',String(String(loadCurrent.auto)===button.dataset.loadAuto));button.disabled=busy||engineBusy;}
  const status=document.getElementById('loadSettingsStatus');
  if(activeEngine==='llama')status.textContent=loadCurrent.auto?uiText('Automático: llama.cpp ajusta capas y contexto a tu memoria (--fit).'):uiText('Personalizado: tú eliges las capas (sin --fit). Se aplicará en la próxima carga.')+(layers?' '+uiText('El modelo tiene')+' '+layers+' '+uiText('capas')+'.':'');
  else status.textContent=loadCurrent.auto?'Automático: 1 slot, lotes del motor y 1 checkpoint.':'Se aplicará en la próxima carga manual.';
  requestMemoryEstimate();
}
function memoryGiB(value){return typeof value==='number'?'≈ '+(value/2**30).toLocaleString(undefined,{maximumFractionDigits:2})+' GiB':'No disponible';}
function paintMemory(data){
  memoryLast=data;loadCapabilities=data.capabilities;syncLoadSettings();const m=data.memory,h=m.hardware||{};document.getElementById('memoryHeadline').textContent=memoryGiB(m.total);{const cm=document.getElementById('contextMemory');if(cm)cm.textContent=uiText('Memoria')+' '+memoryGiB(m.total);}document.getElementById('memoryTotal').textContent=memoryGiB(m.total);
  document.getElementById('memoryGpuLabel').textContent=activeEngine==='strata'?'GPU (base)':'GPU con descarga completa';document.getElementById('memoryGpu').textContent=memoryGiB(m.gpu_full_offload);
  const breakdown=document.getElementById('memoryBreakdown');breakdown.replaceChildren();for(const [label,key] of [['Pesos','weights'],['Caché KV','kv'],['Estados y checkpoints','recurrent'],['Buffers','buffers']]){const row=document.createElement('div'),title=document.createElement('span'),value=document.createElement('span');row.className='memory-detail';title.textContent=uiText(label);value.textContent=memoryGiB(m[key]);row.append(title,value);breakdown.append(row);}
  document.getElementById('memoryShape').textContent=m.kv_type+' · '+m.context_per_slot.toLocaleString()+' tokens/slot · '+m.slots+' slots';
  const warning=document.getElementById('memoryWarning'),gpu=document.getElementById('memoryGpu');const exceeds=typeof h.gpu_available==='number'&&m.gpu_full_offload>h.gpu_available;gpu.dataset.exceeds=String(exceeds);
  warning.textContent=exceeds?'La descarga completa supera la VRAM libre. Automático puede dejar capas en CPU; la generación será más lenta.':typeof h.ram_available==='number'&&m.total>h.ram_available+(h.gpu_available||0)?'La estimación supera la memoria libre del equipo. Reduce contexto o cambia la caché KV.':'';
  // The warning lived only inside the folded "Estimated memory": shown again under the context control.
  let shown=document.getElementById('contextMemoryWarning');const block=document.getElementById('contextBlock');
  if(!shown&&block){shown=document.createElement('p');shown.id='contextMemoryWarning';shown.className='context-memory-warning';shown.setAttribute('role','status');block.append(shown);}
  if(shown){shown.textContent=warning.textContent?uiText(warning.textContent):'';shown.hidden=!warning.textContent;}
  document.getElementById('memoryNotes').textContent=uiText('Estimación, no reserva de memoria.')+' '+m.notes.map(note=>uiText(note)).join(' ');
}
function requestMemoryEstimate(force=false){
  if(!document.getElementById('modelMemoryEstimate'))return;
  clearTimeout(memoryTimer);const model=document.getElementById('model')?.value;if(!model||activeEngine==='api'||!document.getElementById('modelMemoryEstimate'))return;
  if(!window.VALWindows?.isOpen('model'))return;
  const payload={model,context:Number(document.getElementById('ctxInput').value),kv:document.getElementById('kvCache').value,load:{...loadCurrent},draft:{...draftCurrent}};
  const key=JSON.stringify([activeEngine,engineSnapshot?.llama,payload]);if(!force&&key===memoryKey)return;
  memoryController?.abort();const controller=new AbortController();memoryController=controller;
  memoryTimer=setTimeout(async()=>{for(const id of ['memoryGpu','memoryTotal'])document.getElementById(id).textContent='—';document.getElementById('memoryBreakdown').replaceChildren();document.getElementById('memoryShape').textContent='';document.getElementById('memoryWarning').textContent='';document.getElementById('memoryHeadline').textContent=uiText('Calculando…');try{const result=await requestJSON('/api/harness/memory-estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});if(memoryController!==controller)return;memoryKey=key;paintMemory(result);}catch(error){if(error.name==='AbortError')return;document.getElementById('memoryHeadline').textContent=uiText('No disponible');document.getElementById('memoryWarning').textContent=error.message;}},240);
}
