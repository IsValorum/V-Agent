function syncEngineVersions(){
  const builds=engineSnapshot?.builds||{},variant=$('#llamaVariant').value;
  const label=info=>{const version=info.version?('v'+String(info.version).replace(/^v/,'')):'Versión no declarada';return [version,info.build&&String(info.build).replace(/^v/,'')!==String(info.version||'').replace(/^v/,'')?info.build:''].filter(Boolean).join(' · ');};
  for(const key of ['strata','rust','llama'])$('#engineKind').querySelector(`[value="${key}"]`).textContent=(key==='strata'?'Strata':key==='rust'?'Strata Rust':'llama.cpp')+' · '+label(builds[key==='llama'?variant:key]||{});
  for(const id of ['cpu','cuda','vulkan']){const info=builds[id]||{};$('#llamaVariant').querySelector(`[value="${id}"]`).textContent=({cpu:'Oficial · CPU',vulkan:'Oficial · Vulkan (AMD, Intel Arc, NVIDIA)'}[id]||'Oficial · NVIDIA CUDA '+(info.cuda||''))+(info.build?' · '+info.build:'');}
  const kind=$('#engineKind').value,info=builds[kind==='llama'?variant:kind]||{};
  $('#engineBuild').textContent=[info.cuda?'CUDA '+info.cuda:'',info.commit?'Commit '+info.commit:''].filter(Boolean).join(' · ');
  for(const button of document.querySelectorAll('#modelSourceTabs button'))button.setAttribute('aria-pressed',String((kind==='api'?'api':'local')===button.dataset.source));
}
function formatExtraHeaders(headers){
  if(!headers||typeof headers!=='object')return '';
  return Object.entries(headers).map(([k,v])=>`${k}: ${v}`).join('\n');
}
function parseExtraHeadersInput(text){
  const out={};
  for(const line of String(text||'').split(/\r?\n/)){
    const trimmed=line.trim();
    if(!trimmed||trimmed.startsWith('#'))continue;
    const idx=trimmed.indexOf(':');
    if(idx<=0)throw new Error(uiText('Cada cabecera personalizada debe tener el formato Nombre: Valor.'));
    const name=trimmed.slice(0,idx).trim(),val=trimmed.slice(idx+1).trim();
    if(!name)throw new Error(uiText('Falta el nombre de la cabecera personalizada.'));
    out[name]=val;
  }
  return out;
}
function fillApiConnection(identifier){
  const saved=engineSnapshot?.connections?.find(item=>item.id===identifier)||{};
  const ua=saved.user_agent||'';
  const uaPreset=!ua?'default':(['opencode/1.0.0','claude-cli/1.0.0'].includes(ua)?ua:'custom');
  $('#apiConnection').value=saved.id||'';$('#apiName').value=saved.name||'';$('#apiPreset').value=saved.provider_preset||'auto';$('#apiProtocol').value=saved.protocol||'openai';
  $('#apiBase').value=saved.base_url||'';$('#apiKey').value='';$('#apiKey').placeholder=saved.has_key?'Clave guardada · deja vacío para conservarla':'Clave API';
  $('#apiAuthMode').value=saved.auth_mode||'auto';$('#apiUserAgentPreset').value=uaPreset;$('#apiUserAgent').value=ua;
  $('#apiSessionMode').value=saved.send_session_id===true?'always':saved.send_session_id===false?'off':'auto';
  $('#apiOrganization').value=saved.organization||'';$('#apiProject').value=saved.project||'';$('#apiTimeout').value=saved.timeout||180;
  $('#apiVersion').value=saved.api_version||'2023-06-01';$('#apiAnthropicBeta').value=saved.anthropic_beta||'';
  $('#apiAzureVersion').value=saved.azure_api_version||'';$('#apiHttpReferer').value=saved.http_referer||'';$('#apiXTitle').value=saved.x_title||'';
  $('#apiExtraHeaders').value=formatExtraHeaders(saved.extra_headers);
  $('#apiVision').checked=!!saved.vision;$('#apiUsage').checked=saved.include_usage!==false;$('#apiSampling').checked=!!saved.send_sampling;
  $('#apiConnectionEditor').open=!saved.id;syncApiProtocol();
}
function syncApiProtocol(){
  const preset=$('#apiPreset').value,claude=$('#apiProtocol').value==='anthropic';
  const baseLower=($('#apiBase').value||'').toLowerCase();
  const isAzure=preset==='azure'||(preset==='auto'&&baseLower.includes('.openai.azure.com'));
  $('#apiBase').placeholder=claude?'https://api.anthropic.com/v1':preset==='openrouter'?'https://openrouter.ai/api/v1':preset==='opencode'?'https://opencode.ai/zen/go/v1':isAzure?'https://tu-recurso.openai.azure.com/openai/v1':'https://api.openai.com/v1';
  $('#apiOpenAIFields').hidden=claude;$('#apiClaudeFields').hidden=!claude;$('#apiAzureFields').hidden=!isAzure;
  const uaPreset=$('#apiUserAgentPreset').value;$('#apiUserAgent').hidden=uaPreset==='default';
  const help=preset==='openrouter'?'OpenRouter · HTTP-Referer y X-Title automáticos':preset==='opencode'?'OpenCode Go · sesión UUID v4 por conversación':isAzure?'Azure OpenAI · cabecera api-key y versión':claude?'Claude nativo · x-api-key + anthropic-version':'OpenAI compatible · Chat Completions';
  $('#apiConnectionHelp').textContent=uiText(help);
}
function syncApiConnections(){
  const select=$('#apiConnection'),selected=engineSnapshot?.api?.id||'';
  select.replaceChildren(new Option('Nueva conexión',''),...(engineSnapshot?.connections||[]).map(item=>new Option(item.name+' · '+(item.provider_preset&&item.provider_preset!=='auto'?item.provider_preset:(item.protocol==='anthropic'?'Claude':'OpenAI compatible')),item.id)));
  fillApiConnection(selected);
}
function setupEngineControls(){
  const host=document.createElement('section');host.id='engineSettings';
  host.innerHTML=`<div id="modelSourceTabs" class="model-source-tabs" role="group" aria-label="Origen del modelo"><button type="button" data-source="local">En este equipo</button><button type="button" data-source="api">APIs</button></div><div class="engine-bar">
    <div class="engine-field"><label for="engineKind">Motor</label><select id="engineKind"><option value="strata">Strata</option><option value="rust">Strata Rust</option><option value="llama">llama.cpp</option><option value="api">API externa</option></select></div>
    <div id="llamaOptions" class="engine-field" hidden><label for="llamaVariant">Compilación</label><select id="llamaVariant"><option value="cuda">Oficial · NVIDIA CUDA</option><option value="vulkan">Oficial · Vulkan (AMD, Intel Arc, NVIDIA)</option><option value="cpu">Oficial · CPU</option><option value="custom">Mi compilación</option></select></div><button id="applyEngine" type="button">Aplicar</button></div>
    <div id="engineFileActions" class="engine-file-actions"><button id="addCustomEngine" type="button">+ Añadir llama.cpp</button><button id="openBundledEngines" type="button">Motores incluidos</button><button id="openEngineUpdates" type="button">Actualizaciones</button></div><details id="engineAdvanced" hidden><summary>Ajustes del motor</summary><div class="engine-advanced-body"><div id="llamaCustom" class="path-picker" hidden><input id="llamaExecutable" type="text" placeholder="llama-server.exe" aria-label="Ejecutable llama.cpp"><button id="browseLlama" type="button">Elegir…</button></div><div class="engine-inline-field"><label for="llamaLayers">Capas GPU</label><input id="llamaLayers" type="text" value="auto" aria-label="Capas GPU"><span id="engineBuild" class="mini"></span></div></div></details>
    <div id="apiOptions" hidden><div class="api-connection-row"><select id="apiConnection" aria-label="Conexión API guardada"><option value="">Nueva conexión</option></select><button id="newApiConnection" type="button" title="Añadir API">+</button></div>
      <details id="apiConnectionEditor" open><summary>Añadir o editar conexión</summary><div class="api-form-grid"><label>Proveedor / Preset<select id="apiPreset"><option value="auto">Auto (según URL)</option><option value="openai">OpenAI compatible</option><option value="anthropic">Claude · Anthropic</option><option value="openrouter">OpenRouter</option><option value="opencode">OpenCode Go</option><option value="azure">Azure OpenAI</option></select></label><label>Protocolo<select id="apiProtocol"><option value="openai">OpenAI compatible</option><option value="anthropic">Claude · Anthropic</option></select></label><label class="api-wide">Nombre<input id="apiName" maxlength="100" placeholder="Mi conexión"></label><label class="api-wide">URL base<input id="apiBase" type="url" placeholder="https://api.openai.com/v1" autocomplete="off"></label><label class="api-wide">Clave API<input id="apiKey" type="password" placeholder="Clave API" autocomplete="new-password"></label></div>
      <details class="api-extra"><summary>Opciones de conexión y cabeceras</summary><div class="api-extra-grid"><label>Autenticación<select id="apiAuthMode"><option value="auto">Automático según dialecto</option><option value="bearer">Authorization: Bearer</option><option value="x-api-key">x-api-key (Anthropic)</option><option value="api-key">api-key (Azure)</option><option value="none">Sin cabecera de clave</option></select></label><label>User-Agent<select id="apiUserAgentPreset"><option value="default">Por defecto (V-Agent)</option><option value="opencode/1.0.0">opencode/1.0.0</option><option value="claude-cli/1.0.0">claude-cli/1.0.0</option><option value="custom">Personalizado</option></select><input id="apiUserAgent" hidden maxlength="200" placeholder="ej. mi-cliente/1.0" autocomplete="off"></label><label>Sesión por conversación (x-opencode-session)<select id="apiSessionMode"><option value="auto">Automático (OpenCode Go)</option><option value="always">Siempre enviar UUID v4</option><option value="off">Desactivado</option></select></label><div id="apiOpenAIFields"><label>Organización<input id="apiOrganization" autocomplete="off"></label><label>Proyecto API<input id="apiProject" autocomplete="off"></label><label class="chk"><input id="apiSampling" type="checkbox"> Personalizar temperatura y Top P</label><label class="chk"><input id="apiUsage" type="checkbox" checked> Solicitar conteo de tokens en streaming</label></div><div id="apiClaudeFields" hidden><label>Versión de la API (anthropic-version)<input id="apiVersion" value="2023-06-01" placeholder="2023-06-01"></label><label>Cabecera anthropic-beta (opcional)<input id="apiAnthropicBeta" placeholder="prompt-caching-2024-07-31" autocomplete="off"></label></div><div id="apiAzureFields" hidden><label>Versión de Azure (api-version)<input id="apiAzureVersion" placeholder="2024-10-21" autocomplete="off"></label></div><label>HTTP-Referer (OpenRouter / proxy)<input id="apiHttpReferer" placeholder="https://github.com/IsValorum/V-Agent" autocomplete="off"></label><label>X-Title (OpenRouter / proxy)<input id="apiXTitle" placeholder="V-Agent" autocomplete="off"></label><label>Cabeceras personalizadas (Nombre: Valor)<textarea id="apiExtraHeaders" rows="3" spellcheck="false" placeholder="X-Custom-Header: valor"></textarea></label><label>Espera máxima (segundos)<input id="apiTimeout" type="number" min="10" max="1800" value="180"></label><label class="chk"><input id="apiVision" type="checkbox"> Permitir imágenes si el modelo las admite</label></div><p class="mini">En streaming siempre se envían Accept: text/event-stream, Cache-Control: no-cache y Accept-Encoding: identity. Clave cifrada en este equipo.</p></details></details>
      <div class="api-connect-footer"><span id="apiConnectionHelp" class="mini"></span><button id="connectApi" type="button">Guardar y conectar</button></div></div><p id="engineHint" class="mini" role="status"></p>`;
  $('#controls-model').prepend(host);const power=$('#engineToggle').closest('.power-row');if(power)host.append(power);
  const form=()=>{
    const kind=$('#engineKind').value;$('#llamaOptions').hidden=kind!=='llama';$('#engineAdvanced').hidden=kind!=='llama';$('#apiOptions').hidden=kind!=='api';$('#applyEngine').hidden=kind==='api';$('#llamaCustom').hidden=$('#llamaVariant').value!=='custom';
    $('#engineKind').closest('.engine-field').hidden=kind==='api';$('#engineFileActions').hidden=kind==='api';
    syncEngineVersions();$('#applyEngine').disabled=busy||engineBusy||!engineFormDirty();
    $('#load').disabled=busy||engineBusy||!modelStateKnown||!$('#model').value||!!loadedModel||engineFormDirty();
    $('#engineHint').textContent=engineFormDirty()?(loadedModel?(activeEngine==='api'?'Deja de usar el modelo actual antes de cambiar la conexión.':'Descarga el modelo actual antes de cambiar de motor.'):'Pendiente de aplicar.'):(kind==='rust'?'Strata Rust: modelos Qwen3.5/3.6. Para otras familias, elige llama.cpp.':'');
    const power=$('#engineToggle').closest('.power-row');if(power)power.hidden=['llama','rust'].includes(activeEngine)||engineFormDirty();
    $('#composerControls').dataset.source=kind==='api'?'api':'local';
  };
  $('#engineKind').onchange=form;$('#llamaVariant').onchange=()=>{if($('#llamaVariant').value==='custom')$('#engineAdvanced').open=true;form();};
  $('#modelSourceTabs').querySelectorAll('button').forEach(button=>button.onclick=()=>{$('#engineKind').value=button.dataset.source==='api'?'api':(activeEngine==='api'?'strata':activeEngine);$('#modelEngineOptions').open=true;form();});
  for(const id of ['llamaLayers','llamaExecutable','apiBase','apiName','apiKey','apiOrganization','apiProject','apiVersion','apiAnthropicBeta','apiAzureVersion','apiUserAgent','apiHttpReferer','apiXTitle','apiExtraHeaders','apiTimeout','apiVision','apiUsage','apiSampling','apiAuthMode','apiSessionMode'])$('#'+id).addEventListener('input',()=>{syncApiProtocol();form();});
  const defaultBases={'openai':'https://api.openai.com/v1','anthropic':'https://api.anthropic.com/v1','openrouter':'https://openrouter.ai/api/v1','opencode':'https://opencode.ai/zen/go/v1'};
  $('#apiPreset').onchange=()=>{
    const preset=$('#apiPreset').value;
    if(preset==='anthropic')$('#apiProtocol').value='anthropic';
    else if(preset!=='auto')$('#apiProtocol').value='openai';
    const currentBase=$('#apiBase').value.trim();
    if((!currentBase||Object.values(defaultBases).includes(currentBase))&&defaultBases[preset])$('#apiBase').value=defaultBases[preset];
    syncApiProtocol();form();
  };
  $('#apiUserAgentPreset').onchange=()=>{
    const mode=$('#apiUserAgentPreset').value;
    if(mode==='default')$('#apiUserAgent').value='';
    else if(mode!=='custom')$('#apiUserAgent').value=mode;
    syncApiProtocol();form();
    if(mode==='custom')$('#apiUserAgent').focus();
  };
  $('#apiProtocol').onchange=()=>{if(!$('#apiBase').value||Object.values(defaultBases).includes($('#apiBase').value.trim()))$('#apiBase').value=$('#apiProtocol').value==='anthropic'?defaultBases.anthropic:defaultBases.openai;syncApiProtocol();form();};
  $('#apiConnection').onchange=()=>{fillApiConnection($('#apiConnection').value);form();};$('#newApiConnection').onclick=()=>{fillApiConnection('');$('#apiConnectionEditor').open=true;$('#apiName').focus();form();};
  $('#browseLlama').onclick=async()=>{try{const x=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'engine'}),signal:AbortSignal.timeout(310000)});if(x.path){$('#llamaExecutable').value=x.path;form();}}catch(error){note(error.message);}};
  $('#addCustomEngine').onclick=()=>{$('#engineKind').value='llama';$('#llamaVariant').value='custom';$('#engineAdvanced').open=true;form();$('#browseLlama').click();};
  for(const [id,folder] of [['openBundledEngines','bundled'],['openEngineUpdates','updates']])$('#'+id).onclick=async()=>{try{if(!window.__TAURI__?.core?.invoke){note(uiText('Disponible en la aplicación de escritorio.'));return;}await window.__TAURI__.core.invoke('open_engine_folder',{folder});}catch(error){note(String(error));}};
  async function apply(connect=false){
    if(busy||engineBusy)return;setEngineBusy(true);
    try{
      const extraHeaders=parseExtraHeadersInput($('#apiExtraHeaders').value);
      const sessionMode=$('#apiSessionMode').value;
      const uaPreset=$('#apiUserAgentPreset').value;
      const body={engine:$('#engineKind').value,variant:$('#llamaVariant').value,executable:$('#llamaExecutable').value,gpu_layers:$('#llamaLayers').value,connection_id:$('#apiConnection').value,new_connection:!$('#apiConnection').value,name:$('#apiName').value,provider_preset:$('#apiPreset').value,protocol:$('#apiProtocol').value,base_url:$('#apiBase').value,api_key:$('#apiKey').value,auth_mode:$('#apiAuthMode').value,user_agent:uaPreset==='default'?'':$('#apiUserAgent').value,send_session_id:sessionMode==='auto'?null:(sessionMode==='always'),organization:$('#apiOrganization').value,project:$('#apiProject').value,api_version:$('#apiVersion').value,anthropic_beta:$('#apiAnthropicBeta').value,azure_api_version:$('#apiAzureVersion').value,http_referer:$('#apiHttpReferer').value,x_title:$('#apiXTitle').value,extra_headers:extraHeaders,timeout:Number($('#apiTimeout').value)||180,vision:$('#apiVision').checked,include_usage:$('#apiUsage').checked,send_sampling:$('#apiSampling').checked};
      engineSnapshot=await requestJSON('/api/harness/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});activeEngine=engineSnapshot.active;
      // A failed connection still leaves the UI aligned with the engine state actually saved.
      let failure=null;try{if(connect)engineSnapshot=await requestJSON('/api/harness/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(120000)});}catch(error){failure=error;}
      $('#apiKey').value='';syncApiConnections();modelStateRevision++;loadedModel=null;$('#model').replaceChildren();modelCatalog=[];if($('#modelFilter'))$('#modelFilter').value='';Object.keys(modelPreferences).forEach(key=>delete modelPreferences[key]);await loadModels();syncEngineCapabilities();form();
      if(failure)throw failure;$('#engineHint').textContent=connect?'Conectado · '+engineSnapshot.models.length+' modelos disponibles':'';
    }catch(error){
      // Refused (e.g. a model is loaded): the selector goes back to the engine that is really active.
      if(!connect&&$('#engineKind').value!==activeEngine){$('#engineKind').value=activeEngine;$('#engineKind').onchange?.();}
      $('#engineHint').textContent=error.message;
    }finally{setEngineBusy(false);pollStats();}
  }
  $('#applyEngine').onclick=()=>apply();$('#connectApi').onclick=()=>apply(true);
  const remote=document.createElement('section');remote.id='remoteModelInfo';remote.hidden=true;remote.innerHTML='<div class="remote-context-stats"><span>Contexto permitido</span><strong id="remoteContextValue">No informado</strong><small id="remoteContextOrigin"></small></div><details><summary>Configurar límite de contexto</summary><p class="mini">Solo informa al agente del límite. No amplía el contexto del proveedor.</p><label>Tokens<input id="remoteContextInput" type="number" min="1" max="100000000" placeholder="No informado"></label><button type="button" id="saveRemoteContext">Guardar límite</button><button type="button" id="resetRemoteContext">Usar dato de la API</button></details>';
  $('#controls-model').append(remote);
  const saveContext=async reset=>{if(busy||engineBusy)return;if(!reset&&!(Number($('#remoteContextInput').value)>0)){note('Escribe un límite de contexto positivo.');return;}try{await requestJSON('/api/harness/model-context',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('#model').value,context:reset?null:Number($('#remoteContextInput').value)})});await loadModels();}catch(error){note(error.message);}};
  $('#saveRemoteContext').onclick=()=>saveContext(false);$('#resetRemoteContext').onclick=()=>saveContext(true);
  return form;
}
async function restoreEngine(){
  engineSnapshot=await requestJSON('/api/harness/state');activeEngine=engineSnapshot.active;
  $('#engineKind').value=activeEngine;$('#llamaVariant').value=engineSnapshot.llama?.variant||'cuda';$('#llamaExecutable').value=engineSnapshot.llama?.executable||'';$('#llamaLayers').value=engineSnapshot.llama?.gpu_layers||'auto';syncApiConnections();$('#engineKind').onchange();syncEngineCapabilities();
}
function syncEngineCapabilities(){
  if(!$('#engineSettings'))return;
  syncLoadSettings();
  const remote=activeEngine==='api',strata=activeEngine==='strata';
  $('#controls-context').hidden=remote;if($('#contextBlock'))$('#contextBlock').hidden=remote;if($('#loadAdvanced'))$('#loadAdvanced').hidden=remote;if($('#modelSectionTabs'))$('#modelSectionTabs').hidden=remote;if(remote)setModelSection('generation');$('#effort').closest('.row').hidden=false;$('#kvSettings').hidden=remote;$('#draftSettings').hidden=!strata;$('#visionSettings').hidden=remote||activeEngine==='rust';
  $('#templateRow').hidden=!strata;if($('#templateSettings'))$('#templateSettings').hidden=!strata;
  const power=$('#engineToggle').closest('.power-row');if(power)power.hidden=['llama','rust'].includes(activeEngine)||engineFormDirty();
  for(const id of ['p_topk','p_minp','p_rep','p_presence','p_frequency','p_seed'])if($('#'+id)?.closest('.row'))$('#'+id).closest('.row').hidden=remote;
  const claude=remote&&engineSnapshot?.api?.protocol==='anthropic',hideSampling=remote&&(!engineSnapshot?.api?.send_sampling||claude&&engineSnapshot?.api?.api_version>='2026-10-21');for(const id of ['p_temp','p_topp'])if($('#'+id)?.closest('.row'))$('#'+id).closest('.row').hidden=hideSampling;
  for(const id of ['creatorNotice','creatorReset','codeProtection'])if($('#'+id))$('#'+id).hidden=remote;
  if($('#p_temp'))$('#p_temp').closest('details').hidden=hideSampling;
  if(remote){$('#load').textContent='Usar modelo';$('#unload').textContent='Dejar de usar';$('#engineToggle').textContent=engineOnline?'Desconectar API':'Conectar API';}
  else if(!engineBusy){$('#load').textContent='Cargar modelo';$('#unload').textContent='Descargar modelo';}
  $('#engineSettings').querySelectorAll('input,select,button').forEach(el=>el.disabled=busy||engineBusy);$('#modelSourceTabs').querySelectorAll('button').forEach(el=>el.disabled=busy||engineBusy);
  $('#applyEngine').disabled=busy||engineBusy||!engineFormDirty();if(engineFormDirty())$('#load').disabled=true;
  if(activeEngine==='llama'&&$('#visionEncoder')){$('#visionEncoder').value='Integrado en llama.cpp';$('#browseEncoder').hidden=true;}else if($('#browseEncoder'))$('#browseEncoder').hidden=false;
  const add=$('#addModel');if(add){add.hidden=remote;}
  if($('#modelResults'))$('#modelResults').setAttribute('aria-label',remote?'Modelos de la API':'Modelos instalados');
  if($('#remoteModelInfo')){$('#remoteModelInfo').hidden=!remote;const usage=$('#contextUsage');if(usage){if(remote){$('#remoteModelInfo .remote-context-stats')?.after(usage);}else{$('#controls-context')?.prepend(usage);}}}
  if($('#contextCompactBox')){if(remote&&$('#remoteModelInfo'))$('#remoteModelInfo').after($('#contextCompactBox'));else if($('#contextBlock'))$('#contextBlock').after($('#contextCompactBox'));$('#contextCompactBox').hidden=false;}
  $('#composerControls').dataset.activeSource=remote?'api':'local';if($('#engineQuickSettings')){const label=$('#engineQuickSettings span')||$('#engineQuickSettings');label.textContent=uiText(remote?'Gestionar conexiones':'Cambiar motor');}
  syncModelSelectionSummary();syncSettingsSummary();
}
function engineFormDirty(){
  if(!engineSnapshot||!$('#engineKind'))return false;const kind=$('#engineKind').value;if(kind!==activeEngine)return true;
  const saved=engineSnapshot.llama||{};
  if(kind==='api'){
    const cfg=engineSnapshot.api||{};
    const sessionMode=cfg.send_session_id===true?'always':cfg.send_session_id===false?'off':'auto';
    const uaPreset=$('#apiUserAgentPreset').value;
    const uaVal=uaPreset==='default'?'':$('#apiUserAgent').value;
    return $('#apiConnection').value!==(cfg.id||'')||$('#apiPreset').value!==(cfg.provider_preset||'auto')||$('#apiProtocol').value!==(cfg.protocol||'openai')||$('#apiBase').value!==(cfg.base_url||'')||$('#apiName').value!==(cfg.name||'')||!!$('#apiKey').value||$('#apiAuthMode').value!==(cfg.auth_mode||'auto')||uaVal!==(cfg.user_agent||'')||$('#apiSessionMode').value!==sessionMode||$('#apiOrganization').value!==(cfg.organization||'')||$('#apiProject').value!==(cfg.project||'')||$('#apiVersion').value!==(cfg.api_version||'2023-06-01')||$('#apiAnthropicBeta').value!==(cfg.anthropic_beta||'')||$('#apiAzureVersion').value!==(cfg.azure_api_version||'')||$('#apiHttpReferer').value!==(cfg.http_referer||'')||$('#apiXTitle').value!==(cfg.x_title||'')||$('#apiExtraHeaders').value!==formatExtraHeaders(cfg.extra_headers)||Number($('#apiTimeout').value)!==(cfg.timeout||180)||$('#apiVision').checked!==!!cfg.vision||$('#apiUsage').checked!==(cfg.include_usage!==false)||$('#apiSampling').checked!==!!cfg.send_sampling;
  }
  return kind==='llama'&&($('#llamaVariant').value!==(saved.variant||'cuda')||$('#llamaExecutable').value!==(saved.executable||'')||$('#llamaLayers').value!==String(saved.gpu_layers||'auto'));
}
