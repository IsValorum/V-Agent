function syncEngineVersions(){
  const builds=engineSnapshot?.builds||{},variant=$('#llamaVariant').value;
  if($('#strataBuildInfo'))$('#strataBuildInfo').textContent=$('#strataVariant')?.value==='custom'?(builds.strata_custom?.version?uiText('Personalizada')+': '+builds.strata_custom.version:''):'';
  if($('#rustBuildInfo'))$('#rustBuildInfo').textContent=$('#rustVariant')?.value==='custom'?(builds.rust_custom?.version?uiText('Personalizada')+': '+builds.rust_custom.version:''):'';
  const label=info=>{const version=info.version?('v'+String(info.version).replace(/^v/,'')):'Versión no declarada';return [version,info.build&&String(info.build).replace(/^v/,'')!==String(info.version||'').replace(/^v/,'')?info.build:''].filter(Boolean).join(' · ');};
  for(const key of ['strata','rust','llama','maya'])$('#engineKind').querySelector(`[value="${key}"]`).textContent=({strata:'Strata',rust:'Strata Rust',llama:'llama.cpp',maya:'Project Maya'}[key])+' · '+label(builds[key==='llama'?variant:key]||{});
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
// OpenCode plans share one backend preset: Go and Go Plus use the Go endpoint (the plan comes from the key),
// Zen (pay-as-you-go balance and free models) uses the Zen endpoint.
function apiPresetChoice(saved){return saved.provider_preset==='opencode'&&saved.base_url&&!/\/go(\/|\?|$)/i.test(String(saved.base_url))?'opencode-zen':(saved.provider_preset||'auto');}
function apiBackendPreset(){const value=$('#apiPreset').value;return value==='opencode-zen'?'opencode':value;}
function fillApiConnection(identifier){
  const saved=engineSnapshot?.connections?.find(item=>item.id===identifier)||{};
  const ua=saved.user_agent||'';
  const uaPreset=!ua?'default':(['opencode/1.0.0','claude-cli/1.0.0'].includes(ua)?ua:'custom');
  $('#apiConnection').value=saved.id||'';$('#apiName').value=saved.name||'';$('#apiPreset').value=apiPresetChoice(saved);$('#apiProtocol').value=saved.protocol||'openai';
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
  const choice=$('#apiPreset').value,preset=apiBackendPreset(),claude=$('#apiProtocol').value==='anthropic';
  const baseLower=($('#apiBase').value||'').toLowerCase();
  const isAzure=preset==='azure'||(preset==='auto'&&baseLower.includes('.openai.azure.com'));
  $('#apiBase').placeholder=claude?'https://api.anthropic.com/v1':preset==='openrouter'?'https://openrouter.ai/api/v1':choice==='opencode-zen'?'https://opencode.ai/zen/v1':preset==='opencode'?'https://opencode.ai/zen/go/v1':isAzure?'https://tu-recurso.openai.azure.com/openai/v1':'https://api.openai.com/v1';
  $('#apiOpenAIFields').hidden=claude;$('#apiClaudeFields').hidden=!claude;$('#apiAzureFields').hidden=!isAzure;
  const uaPreset=$('#apiUserAgentPreset').value;$('#apiUserAgent').hidden=uaPreset==='default';
  const help=preset==='openrouter'?'OpenRouter · HTTP-Referer y X-Title automáticos':choice==='opencode-zen'?'OpenCode Zen · saldo de la cuenta. Los modelos gratis solo funcionan dentro de la app OpenCode.':preset==='opencode'?'OpenCode Go / Go Plus · el plan lo define tu clave; sesión por conversación':isAzure?'Azure OpenAI · cabecera api-key y versión':claude?'Claude nativo · x-api-key + anthropic-version':'OpenAI compatible · Chat Completions';
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
    <div class="engine-field"><label for="engineKind">Motor</label><select id="engineKind"><option value="strata">Strata</option><option value="rust">Strata Rust</option><option value="llama">llama.cpp</option><option value="maya">Project Maya</option><option value="api">API externa</option></select></div>
    <div id="llamaOptions" class="engine-field" hidden><label for="llamaVariant">Compilación</label><select id="llamaVariant"><option value="cuda">Oficial · NVIDIA CUDA</option><option value="vulkan">Oficial · Vulkan (AMD, Intel Arc, NVIDIA)</option><option value="cpu">Oficial · CPU</option><option value="custom">Mi compilación</option></select></div><div id="strataOptions" class="engine-field" hidden><label for="strataVariant">Compilación</label><select id="strataVariant"><option value="official">Oficial · V-Agent</option><option value="custom">Mi compilación</option></select></div><div id="rustOptions" class="engine-field" hidden><label for="rustVariant">Compilación</label><select id="rustVariant"><option value="official">Oficial · V-Agent</option><option value="custom">Mi compilación</option></select></div><button id="applyEngine" type="button">Aplicar</button></div>
    <div id="strataCustom" class="path-picker engine-custom-row" hidden><input id="strataExecutable" type="text" placeholder="strata-poly.exe" aria-label="Ejecutable Strata"><button id="browseStrata" type="button">Elegir…</button><span id="strataBuildInfo" class="mini"></span></div>
    <div id="rustCustom" class="path-picker engine-custom-row" hidden><input id="rustExecutable" type="text" placeholder="strata.exe" aria-label="Ejecutable Strata Rust"><button id="browseRust" type="button">Elegir…</button><span id="rustBuildInfo" class="mini"></span></div>
    <div id="engineFileActions" class="engine-file-actions"><button id="addCustomEngine" type="button">+ Añadir mi compilación</button><button id="openBundledEngines" type="button">Motores incluidos</button><button id="openEngineUpdates" type="button">Actualizaciones</button></div><div id="engineAdvanced" class="engine-advanced" hidden><h5 class="block-title">Ajustes del motor</h5><div class="engine-advanced-body"><div id="llamaCustom" class="path-picker" hidden><input id="llamaExecutable" type="text" placeholder="llama-server.exe" aria-label="Ejecutable llama.cpp"><button id="browseLlama" type="button">Elegir…</button></div><div class="engine-inline-field"><label for="llamaLayers">Capas GPU</label><input id="llamaLayers" type="text" value="auto" aria-label="Capas GPU"><span id="engineBuild" class="mini"></span></div></div></div>
    <section id="mayaOptions" class="maya-options" hidden>
      <div class="maya-repo-bar">
        <span id="mayaVersionBadge" class="mini"></span>
        <button id="mayaQuickSetup" type="button" class="soft-btn primary">Preparar modelo con Maya</button>
      </div>
      <p id="mayaPrereqSummary" class="mini" role="status"></p>
      <p id="mayaActionStatus" class="mini" role="status"></p>
      <div id="mayaSetupProgress" class="maya-progress" hidden>
        <progress aria-label="Preparación del modelo"></progress>
        <button id="mayaCancelSetup" type="button" class="soft-btn">Cancelar</button>
      </div>
      <details id="mayaSetupLog" class="settings-group" hidden><summary>Registro de preparación</summary><pre id="mayaSetupLogText" data-user-content></pre></details>
      <div id="mayaEngineAdvanced" class="maya-disclosure-body" hidden>
      <div class="maya-setup-grid">
        <label>Carpeta de Project Maya<div class="path-picker"><input id="mayaRoot" type="text" placeholder="Automático (datos locales de V-Agent)" aria-label="Carpeta de Project Maya"><button id="browseMaya" type="button">Elegir…</button></div></label>
        <label>Binario compilado (opcional)<div class="path-picker"><input id="mayaExecutable" type="text" placeholder="maya.exe / maya-ds4.exe (si ya está compilado)" aria-label="Binario compilado de Project Maya"><button id="browseMayaExe" type="button">Elegir…</button></div></label>
        <p class="mini" id="mayaCustomHint">Si ya tienes una compilación propia, elige su carpeta o binario sin descargar ni compilar de nuevo.</p>
        <label>Backend de aceleración<select id="mayaBackend"><option value="auto">Automático (NVIDIA CUDA / AMD HIP)</option><option value="cuda">NVIDIA CUDA (SM 7.0+)</option><option value="hip">AMD HIP / ROCm (Windows)</option></select></label>
      </div>
      <div class="maya-prereq-head"><strong id="mayaPrereqTitle">Requisitos previos en este equipo</strong><button id="mayaRefreshPrereqs" type="button">Comprobar requisitos</button></div>
      <ul id="mayaPrereqsList" class="maya-prereqs-list"></ul>
      <div class="maya-repo-actions">
        <button id="mayaCheckUpdate" type="button" class="soft-btn">Comprobar versión oficial</button>
        <button id="mayaClonePull" type="button" class="soft-btn">Clonar / Actualizar</button>
        <button id="mayaUninstall" type="button" class="soft-btn">Desvincular</button>
      </div>
      </div>
    </section>
    <div id="apiOptions" hidden><div class="api-connection-row"><select id="apiConnection" aria-label="Conexión API guardada"><option value="">Nueva conexión</option></select><button id="newApiConnection" type="button" title="Añadir API">+</button></div>
      <details id="apiConnectionEditor" open><summary>Añadir o editar conexión</summary><div class="api-form-grid"><label>Proveedor / Preset<select id="apiPreset"><option value="auto">Auto (según URL)</option><option value="openai">OpenAI compatible</option><option value="anthropic">Claude · Anthropic</option><option value="openrouter">OpenRouter</option><option value="opencode">OpenCode Go / Go Plus</option><option value="opencode-zen">OpenCode Zen</option><option value="azure">Azure OpenAI</option></select></label><label>Protocolo<select id="apiProtocol"><option value="openai">OpenAI compatible</option><option value="anthropic">Claude · Anthropic</option></select></label><label class="api-wide">Nombre<input id="apiName" maxlength="100" placeholder="Mi conexión"></label><label class="api-wide">URL base<input id="apiBase" type="url" placeholder="https://api.openai.com/v1" autocomplete="off"></label><label class="api-wide">Clave API<input id="apiKey" type="password" placeholder="Clave API" autocomplete="new-password"></label></div>
      <details class="api-extra"><summary>Opciones de conexión y cabeceras</summary><div class="api-extra-grid"><label>Autenticación<select id="apiAuthMode"><option value="auto">Automático según dialecto</option><option value="bearer">Authorization: Bearer</option><option value="x-api-key">x-api-key (Anthropic)</option><option value="api-key">api-key (Azure)</option><option value="none">Sin cabecera de clave</option></select></label><label>User-Agent<select id="apiUserAgentPreset"><option value="default">Por defecto (V-Agent)</option><option value="opencode/1.0.0">opencode/1.0.0</option><option value="claude-cli/1.0.0">claude-cli/1.0.0</option><option value="custom">Personalizado</option></select><input id="apiUserAgent" hidden maxlength="200" placeholder="ej. mi-cliente/1.0" autocomplete="off"></label><label>Sesión por conversación (x-opencode-session)<select id="apiSessionMode"><option value="auto">Automático (OpenCode Go)</option><option value="always">Siempre enviar UUID v4</option><option value="off">Desactivado</option></select></label><div id="apiOpenAIFields"><label>Organización<input id="apiOrganization" autocomplete="off"></label><label>Proyecto API<input id="apiProject" autocomplete="off"></label><label class="chk"><input id="apiSampling" type="checkbox"> Personalizar temperatura y Top P</label><label class="chk"><input id="apiUsage" type="checkbox" checked> Solicitar conteo de tokens en streaming</label></div><div id="apiClaudeFields" hidden><label>Versión de la API (anthropic-version)<input id="apiVersion" value="2023-06-01" placeholder="2023-06-01"></label><label>Cabecera anthropic-beta (opcional)<input id="apiAnthropicBeta" placeholder="prompt-caching-2024-07-31" autocomplete="off"></label></div><div id="apiAzureFields" hidden><label>Versión de Azure (api-version)<input id="apiAzureVersion" placeholder="2024-10-21" autocomplete="off"></label></div><label>HTTP-Referer (OpenRouter / proxy)<input id="apiHttpReferer" placeholder="https://github.com/IsValorum/V-Agent" autocomplete="off"></label><label>X-Title (OpenRouter / proxy)<input id="apiXTitle" placeholder="V-Agent" autocomplete="off"></label><label>Cabeceras personalizadas (Nombre: Valor)<textarea id="apiExtraHeaders" rows="3" spellcheck="false" placeholder="X-Custom-Header: valor"></textarea></label><label>Espera máxima (segundos)<input id="apiTimeout" type="number" min="10" max="1800" value="180"></label><label class="chk"><input id="apiVision" type="checkbox"> Permitir imágenes si el modelo las admite</label></div><p class="mini">En streaming siempre se envían Accept: text/event-stream, Cache-Control: no-cache y Accept-Encoding: identity. Clave cifrada en este equipo.</p></details></details>
      <div class="api-connect-footer"><span id="apiConnectionHelp" class="mini"></span><button id="connectApi" type="button">Guardar y conectar</button></div></div><p id="engineHint" class="mini" role="status"></p>`;
  $('#controls-model').prepend(host);const power=$('#engineToggle').closest('.power-row');if(power)host.append(power);
  const mayaModelBox=document.createElement('section');mayaModelBox.id='mayaModelSettings';mayaModelBox.className='maya-model-settings';mayaModelBox.hidden=true;
  ($('#model-load-pane')||$('#controls-model')).prepend(mayaModelBox);
  let lastMayaStatus=null,mayaPollTimer=0;
  const syncMayaActionButtons=()=>{
    const p=lastMayaStatus?.prerequisites||lastMayaStatus||{};
    const blocked=busy||engineBusy||!!loadedModel||!!lastMayaStatus?.build?.building;
    $('#mayaClonePull').disabled=blocked;
    $('#mayaUninstall').disabled=blocked||!p.root;
    $('#mayaQuickSetup').disabled=busy||engineBusy||!!loadedModel;
    $('#mayaCancelSetup').disabled=!!engineBusy||!!lastMayaStatus?.build?.cancelled;
  };
  window.syncMayaActionButtons=syncMayaActionButtons;
  const paintMayaStatus=info=>{
    if(!info)return;lastMayaStatus=info;
    const p=info.prerequisites||info,rel=info.release||{},bld=info.build||{};
    if($('#mayaPrereqSummary')){
      $('#mayaPrereqSummary').textContent=uiText(p.note||'');
    }
    const list=$('#mayaPrereqsList');
    if(list){
      list.replaceChildren();
      for(const chk of p.checks||[]){
        const li=document.createElement('li');li.className='maya-prereq-item';li.dataset.ok=String(!!chk.ok);
        const badge=document.createElement('span');badge.className='maya-prereq-mark';badge.textContent=chk.ok?'✓':(chk.required?'✕':'!');
        const name=document.createElement('strong');name.textContent=uiText(chk.label||'');
        const detail=document.createElement('small');detail.textContent=uiText(chk.detail||'');
        li.append(badge,name,detail);list.append(li);
      }
    }
    const verBadge=$('#mayaVersionBadge');
    if(verBadge){
      const cur=p.version||'';const tag=rel.tag||'';
      verBadge.textContent=[cur?(uiText('Instalado')+': '+cur):uiText('Sin código local'),tag?(uiText('Oficial')+': '+tag):''].filter(Boolean).join(' · ');
    }
    const cloneBtn=$('#mayaClonePull');if(cloneBtn)cloneBtn.textContent=uiText(p.root?'Actualizar desde GitHub':'Clonar repositorio oficial');
    syncMayaActionButtons();
    const st=$('#mayaActionStatus');
    if(st&&!st.dataset.manual)st.textContent=uiText(bld.error||bld.operation||'');
    $('#mayaSetupProgress').hidden=!(bld.building&&bld.guided);
    $('#mayaSetupLog').hidden=!bld.guided;
    const log=$('#mayaSetupLogText');if(log.textContent!==(bld.tail||''))log.textContent=bld.tail||'';
    clearTimeout(mayaPollTimer);
    if(bld.building)mayaPollTimer=setTimeout(async()=>{
      try{
        const build=await requestJSON('/api/harness/maya/setup-status');
        paintMayaStatus({...lastMayaStatus,build});
        if(!build.building){await refreshMayaPrereqs(true);await loadModels();}
      }catch(error){if(st)st.textContent=uiText(error.message);}
    },2000);
    window.VALI18n?.observe(host);
  };
  async function refreshMayaPrereqs(fullStatus=false){
    try{
      if(fullStatus){paintMayaStatus(await requestJSON('/api/harness/maya/status'));return;}
      const data=await requestJSON('/api/harness/maya/prerequisites',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root:$('#mayaRoot')?.value.trim()||'',executable:$('#mayaExecutable')?.value.trim()||'',backend:$('#mayaBackend')?.value||'auto'})});
      paintMayaStatus({prerequisites:data,release:lastMayaStatus?.release||{},build:lastMayaStatus?.build||{},setup_models:lastMayaStatus?.setup_models||{}});
    }catch(error){if($('#mayaActionStatus'))$('#mayaActionStatus').textContent=uiText(error.message);}
  }
  const runMayaAction=async(action,extra={})=>{
    if(busy||engineBusy)return;
    const st=$('#mayaActionStatus');if(st){delete st.dataset.manual;st.textContent=uiText('Procesando…');}
    setEngineBusy(true);
    try{
      const payload={action,root:$('#mayaRoot').value.trim(),backend:$('#mayaBackend').value,...extra};
      const res=await requestJSON('/api/harness/maya/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(action==='clone_or_pull'||action==='build'?630000:120000)});
      if(res.snapshot){engineSnapshot=res.snapshot;activeEngine=engineSnapshot.active;if(engineSnapshot.maya?.root!==undefined)$('#mayaRoot').value=engineSnapshot.maya.root||'';if($('#mayaExecutable')&&engineSnapshot.maya?.executable!==undefined)$('#mayaExecutable').value=engineSnapshot.maya.executable||'';}
      await refreshMayaPrereqs(true);
      await loadModels();syncEngineVersions();syncSettingsSummary();
      if(res.release?.error)throw new Error(res.release.error);
      if(st&&!['build','cancel_setup'].includes(action)){st.dataset.manual='1';st.textContent=uiText(action==='check_update'?(res.release?.available?('Nueva versión disponible: '+res.release.tag):'Versión oficial comprobada.'):action==='clone_or_pull'?'Repositorio de Project Maya actualizado.':'Project Maya desvinculado.');}
    }catch(error){if(st){st.dataset.manual='1';st.textContent=uiText(error.message);}}
    finally{setEngineBusy(false);if(lastMayaStatus)paintMayaStatus(lastMayaStatus);}
  };
  $('#browseMaya').onclick=async()=>{try{const x=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'maya'}),signal:AbortSignal.timeout(310000)});if(x.path){$('#mayaRoot').value=x.path;form();refreshMayaPrereqs(false);}}catch(error){note(error.message);}};
  if($('#browseMayaExe'))$('#browseMayaExe').onclick=async()=>{try{const x=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'engine'}),signal:AbortSignal.timeout(310000)});if(x.path){$('#mayaExecutable').value=x.path;form();refreshMayaPrereqs(false);}}catch(error){note(error.message);}};
  $('#mayaRefreshPrereqs').onclick=()=>refreshMayaPrereqs(true);
  $('#mayaCheckUpdate').onclick=()=>runMayaAction('check_update');
  $('#mayaClonePull').onclick=async()=>{
    const hasRoot=Boolean(lastMayaStatus?.prerequisites?.root);
    if(!hasRoot&&!await valConfirm({title:uiText('¿Clonar Project Maya desde GitHub?'),message:uiText('Se descargará el código fuente oficial (mw00/project-maya) para compilarlo en este equipo. Tus pesos de modelos no se descargan automáticamente.'),confirm:uiText('Clonar')}))return;
    await runMayaAction('clone_or_pull');
  };
  $('#mayaUninstall').onclick=()=>runMayaAction('uninstall');
  window.refreshMayaStatusPanel=refreshMayaPrereqs;
  window.prepareMayaModel=async()=>{
    if(busy||engineBusy||loadedModel||document.getElementById('mayaPrepareDialog'))return;
    if($('#modelEngineOptions'))$('#modelEngineOptions').open=true;
    await refreshMayaPrereqs(true);
    if(document.getElementById('mayaPrepareDialog')||busy||engineBusy||loadedModel)return;
    if(lastMayaStatus?.build?.building){$('#mayaActionStatus').scrollIntoView({block:'nearest'});return;}
    const models=Object.entries(lastMayaStatus?.setup_models||{});
    if(!models.length||lastMayaStatus?.prerequisites?.hardware_supported===false){
      $('#mayaPrereqSummary').scrollIntoView({block:'nearest'});
      return;
    }
    const dialog=document.createElement('dialog');
    dialog.id='mayaPrepareDialog';
    dialog.className='val-confirm';
    dialog.innerHTML=`<form method="dialog"><h3>Preparar modelo con Maya</h3>
      <label class="maya-field" id="mayaCatalogField">Modelo<select id="mayaSetupModel" required></select></label>
      <p class="mini maya-setup-size" id="mayaSetupSize"></p>
      <p class="mini" id="mayaSetupHint">V-Agent descargará los archivos necesarios y preparará el modelo en este equipo.</p>
      <details class="settings-group maya-disclosure">
        <summary>Ajustes avanzados</summary>
        <div class="maya-disclosure-body">
          <label class="maya-field">Origen del modelo<select id="mayaSetupSource">
            <option value="catalog">Catálogo de Maya</option>
            <option value="custom">Otro modelo compatible</option>
            <option value="local">Archivos locales (GGUF o EXL3)</option>
            <option value="gguf">GGUF local de GLM-5.3-Flash</option>
          </select></label>
          <label class="maya-field" id="mayaSetupIdField" hidden>Identificador del modelo<input id="mayaSetupId" maxlength="96" spellcheck="false"></label>
          <label class="maya-field" id="mayaSetupSourceField" hidden>Carpeta de los archivos del modelo<input id="mayaSetupSourceDir" spellcheck="false"></label>
          <label class="maya-field">Carpeta de descarga<input id="mayaSetupDestination" placeholder="Automático" spellcheck="false"></label>
          <div class="maya-model-grid">
            <label class="maya-field">Aceleración<select id="mayaSetupBackend"><option value="auto">Automático</option><option value="cuda">NVIDIA CUDA</option><option value="hip">AMD HIP / ROCm</option></select></label>
            <label class="maya-field">GPUs (índices o vacío)<input id="mayaSetupGpus" placeholder="0 o 0,1" spellcheck="false"></label>
            <label class="maya-field">Contexto<input id="mayaSetupContext" type="number" min="8192" max="1048576" placeholder="Automático"></label>
            <label class="maya-field">Estrategia Draft / MTP<select id="mayaSetupDrafting"><option value="on">Activado</option><option value="off">Desactivado</option><option value="measure">Medir rendimiento</option></select></label>
          </div>
          <label class="chk"><input type="checkbox" id="mayaSetupVision" checked> Visión</label>
        </div>
      </details>
      <div class="val-confirm-actions"><button value="cancel" formnovalidate>Cancelar</button><button class="soft-btn primary" value="prepare">Preparar modelo</button></div></form>`;
    const field=id=>dialog.querySelector('#'+id);
    const select=field('mayaSetupModel'),source=field('mayaSetupSource');
    const modelId=field('mayaSetupId'),sourceDir=field('mayaSetupSourceDir');
    field('mayaSetupBackend').value=$('#mayaBackend').value||'auto';
    select.append(new Option(uiText('Selecciona un modelo'),''));
    for(const [id,model] of models)select.append(new Option(model.name,id));
    const updateOptions=()=>{
      const catalog=source.value==='catalog',custom=source.value==='custom';
      const local=!catalog&&!custom;
      select.required=catalog;
      modelId.required=custom;
      sourceDir.required=local;
      field('mayaCatalogField').hidden=!catalog;
      field('mayaSetupIdField').hidden=!custom;
      field('mayaSetupSourceField').hidden=!local;
      const model=catalog?lastMayaStatus.setup_models[select.value]:null;
      const amount=model?Intl.NumberFormat(window.VALI18n?.locale).format(model.gb)+' GB':'';
      field('mayaSetupSize').textContent=amount?uiText('Tamaño aproximado')+' · '+amount:'';
      field('mayaSetupHint').textContent=uiText(local
        ?'V-Agent preparará los archivos locales y descargará los componentes que falten.'
        :'V-Agent descargará los archivos necesarios y preparará el modelo en este equipo.');
    };
    source.onchange=select.onchange=updateOptions;
    dialog.addEventListener('close',()=>{
      const prepare=dialog.returnValue==='prepare';
      const mode=source.value;
      const context=field('mayaSetupContext').valueAsNumber;
      const model=mode==='catalog'?select.value:mode==='custom'?modelId.value.trim():'';
      const setup_options={
        source:mode==='custom'?'catalog':mode,source_dir:sourceDir.value.trim(),
        models_dir:field('mayaSetupDestination').value.trim(),gpus:field('mayaSetupGpus').value.trim(),
        context:Number.isFinite(context)?context:null,
        vision:field('mayaSetupVision').checked,drafting:field('mayaSetupDrafting').value,
      };
      const backend=field('mayaSetupBackend').value;
      dialog.remove();
      if(prepare)runMayaAction('build',{backend,setup_model:model,setup_options});
    },{once:true});
    document.body.append(dialog);
    window.VALI18n?.observe(dialog);
    updateOptions();
    dialog.showModal();
  };
  $('#mayaQuickSetup').onclick=()=>window.prepareMayaModel();
  $('#mayaCancelSetup').onclick=()=>runMayaAction('cancel_setup');
  const form=()=>{
    const kind=$('#engineKind').value;$('#llamaOptions').hidden=kind!=='llama';$('#strataOptions').hidden=kind!=='strata';$('#rustOptions').hidden=kind!=='rust';$('#engineAdvanced').hidden=kind!=='llama';$('#mayaOptions').hidden=kind!=='maya';$('#apiOptions').hidden=kind!=='api';$('#applyEngine').hidden=kind==='api';$('#llamaCustom').hidden=$('#llamaVariant').value!=='custom';$('#strataCustom').hidden=kind!=='strata'||$('#strataVariant').value!=='custom';$('#rustCustom').hidden=kind!=='rust'||$('#rustVariant').value!=='custom';if($('#addCustomEngine'))$('#addCustomEngine').textContent=uiText(kind==='maya'?'+ Elegir compilación Maya':kind==='strata'?'+ Añadir Strata propio':kind==='rust'?'+ Añadir Strata Rust propio':kind==='llama'?'+ Añadir llama.cpp propio':'+ Añadir mi compilación');
    $('#engineKind').closest('.engine-field').hidden=kind==='api';$('#engineFileActions').hidden=kind==='api';
    if(kind==='maya'&&!lastMayaStatus)refreshMayaPrereqs(true);
    syncEngineVersions();$('#applyEngine').disabled=busy||engineBusy||!engineFormDirty();
    $('#load').disabled=busy||engineBusy||!modelStateKnown||!$('#model').value||!!loadedModel||engineFormDirty();
    $('#engineHint').textContent=engineFormDirty()?(loadedModel?uiText(activeEngine==='api'?'Deja de usar el modelo actual antes de cambiar la conexión.':'Descarga el modelo actual antes de cambiar de motor.'):uiText('Pendiente de aplicar.')):(kind==='rust'?uiText('Strata Rust: cada versión amplía las familias de modelos que admite; si un modelo no es compatible, se indica al cargarlo.'):kind==='maya'?uiText('Project Maya: GLM-5.3, DeepSeek-V4.1, MiniMax-M3.1 y Qwen-3.8 locales.'):'');
    const power=$('#engineToggle').closest('.power-row');if(power)power.hidden=['llama','rust','maya'].includes(activeEngine)||engineFormDirty();
    $('#composerControls').dataset.source=kind==='api'?'api':'local';
  };
  $('#engineKind').onchange=form;$('#llamaVariant').onchange=()=>{if($('#llamaVariant').value==='custom')$('#engineAdvanced').open=true;form();};if($('#strataVariant'))$('#strataVariant').onchange=form;if($('#rustVariant'))$('#rustVariant').onchange=form;
  $('#mayaBackend').onchange=()=>{form();if($('#engineKind').value==='maya')refreshMayaPrereqs(false);};
  $('#mayaRoot').addEventListener('input',()=>form());
  $('#modelSourceTabs').querySelectorAll('button').forEach(button=>button.onclick=()=>{$('#engineKind').value=button.dataset.source==='api'?'api':(activeEngine==='api'?'strata':activeEngine);$('#modelEngineOptions').open=true;form();});
  for(const id of ['strataExecutable','rustExecutable','mayaExecutable','llamaLayers','llamaExecutable','apiBase','apiName','apiKey','apiOrganization','apiProject','apiVersion','apiAnthropicBeta','apiAzureVersion','apiUserAgent','apiHttpReferer','apiXTitle','apiExtraHeaders','apiTimeout','apiVision','apiUsage','apiSampling','apiAuthMode','apiSessionMode'])$('#'+id)?.addEventListener('input',()=>{syncApiProtocol();form();});
  const defaultBases={'openai':'https://api.openai.com/v1','anthropic':'https://api.anthropic.com/v1','openrouter':'https://openrouter.ai/api/v1','opencode':'https://opencode.ai/zen/go/v1','opencode-zen':'https://opencode.ai/zen/v1'};
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
  if($('#browseStrata'))$('#browseStrata').onclick=async()=>{try{const x=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'engine'}),signal:AbortSignal.timeout(310000)});if(x.path){$('#strataExecutable').value=x.path;form();}}catch(error){note(error.message);}};
  if($('#browseRust'))$('#browseRust').onclick=async()=>{try{const x=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'engine'}),signal:AbortSignal.timeout(310000)});if(x.path){$('#rustExecutable').value=x.path;form();}}catch(error){note(error.message);}};
  $('#addCustomEngine').onclick=()=>{
    const kind=$('#engineKind').value;
    if(kind==='strata'){$('#strataVariant').value='custom';form();$('#browseStrata').click();return;}
    if(kind==='rust'){$('#rustVariant').value='custom';form();$('#browseRust').click();return;}
    if(kind==='maya'){form();($('#browseMayaExe')||$('#browseMaya')).click();return;}
    $('#engineKind').value='llama';$('#llamaVariant').value='custom';$('#engineAdvanced').open=true;form();$('#browseLlama').click();
  };
  for(const [id,folder] of [['openBundledEngines','bundled'],['openEngineUpdates','updates']])$('#'+id).onclick=async()=>{try{if(!window.__TAURI__?.core?.invoke){note(uiText('Disponible en la aplicación de escritorio.'));return;}await window.__TAURI__.core.invoke('open_engine_folder',{folder});}catch(error){note(String(error));}};
  async function apply(connect=false){
    if(busy||engineBusy)return;setEngineBusy(true);
    try{
      const extraHeaders=parseExtraHeadersInput($('#apiExtraHeaders').value);
      const sessionMode=$('#apiSessionMode').value;
      const uaPreset=$('#apiUserAgentPreset').value;
      const selectedKind=$('#engineKind').value;
      const body={engine:selectedKind,variant:selectedKind==='strata'?$('#strataVariant').value:selectedKind==='rust'?$('#rustVariant').value:$('#llamaVariant').value,executable:selectedKind==='strata'?$('#strataExecutable').value:selectedKind==='rust'?$('#rustExecutable').value:$('#llamaExecutable').value,gpu_layers:$('#llamaLayers').value,maya_root:$('#mayaRoot').value.trim(),maya_executable:$('#mayaExecutable')?.value.trim()||'',maya_backend:$('#mayaBackend').value,connection_id:$('#apiConnection').value,new_connection:!$('#apiConnection').value,name:$('#apiName').value,provider_preset:apiBackendPreset(),protocol:$('#apiProtocol').value,base_url:$('#apiBase').value,api_key:$('#apiKey').value,auth_mode:$('#apiAuthMode').value,user_agent:uaPreset==='default'?'':$('#apiUserAgent').value,send_session_id:sessionMode==='auto'?null:(sessionMode==='always'),organization:$('#apiOrganization').value,project:$('#apiProject').value,api_version:$('#apiVersion').value,anthropic_beta:$('#apiAnthropicBeta').value,azure_api_version:$('#apiAzureVersion').value,http_referer:$('#apiHttpReferer').value,x_title:$('#apiXTitle').value,extra_headers:extraHeaders,timeout:Number($('#apiTimeout').value)||180,vision:$('#apiVision').checked,include_usage:$('#apiUsage').checked,send_sampling:$('#apiSampling').checked};
      engineSnapshot=await requestJSON('/api/harness/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});activeEngine=engineSnapshot.active;
      // A failed connection still leaves the UI aligned with the engine state actually saved.
      let failure=null;try{if(connect)engineSnapshot=await requestJSON('/api/harness/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(120000)});}catch(error){failure=error;}
      $('#apiKey').value='';syncApiConnections();modelStateRevision++;loadedModel=null;$('#model').replaceChildren();modelCatalog=[];if($('#modelFilter'))$('#modelFilter').value='';Object.keys(modelPreferences).forEach(key=>delete modelPreferences[key]);await loadModels();syncEngineCapabilities();form();
      if(activeEngine==='maya')refreshMayaPrereqs(true);
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
  $('#model').addEventListener('change',()=>syncMayaModelSettings());
  window.VALI18n?.onChange?.(()=>{
    if(lastMayaStatus)paintMayaStatus(lastMayaStatus);
    $('#mayaSetupModel')?.dispatchEvent(new Event('change'));
    syncMayaModelSettings();
  });
  return form;
}
function syncMayaModelSettings(){
  const host=$('#mayaModelSettings');if(!host)return;
  if(activeEngine!=='maya'){host.hidden=true;host.replaceChildren();delete host.dataset.configSignature;return;}
  host.hidden=false;
  const modelId=$('#model')?.value||'';
  const model=(typeof modelCatalog!=='undefined'?modelCatalog:[]).find(item=>item.id===modelId);
  const cfg=model?.maya_config;
  const openSections=host.dataset.modelId===modelId?[...host.querySelectorAll('details')].map(item=>item.open):[];
  host.dataset.modelId=modelId;
  const signature=JSON.stringify([modelId,cfg]);
  if(host.dataset.configSignature===signature)return;
  host.dataset.configSignature=signature;
  if(!cfg){
    host.innerHTML='<p class="mini">'+uiText('Selecciona o configura un modelo de Project Maya (maya-*.json) para editar sus opciones avanzadas por familia.')+'</p>';
    return;
  }
  const fields=new Set(cfg.schema?.fields||[]);
  const escAttr=v=>String(v??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const optionLabels={auto:'Automático',default:'Por defecto',on:'Activado',off:'Desactivado',none:'Ninguno',low:'Bajo',medium:'Medio',high:'Alto',xhigh:'Muy alto',max:'Máximo'};
  const opt=(arr,cur)=>arr.map(v=>`<option value="${escAttr(v)}"${String(cur)===String(v)?' selected':''}>${escAttr(optionLabels[v]||v.toUpperCase())}</option>`).join('');
  const row=(key,label,controlHtml)=>fields.has(key)?`<label class="maya-field" data-maya-field="${key}"><span>${uiText(label)}</span>${controlHtml}</label>`:'';
  const chk=(key,label,checked,disabled=false,title='')=>fields.has(key)?`<label class="chk maya-chk" data-maya-field="${key}"${title?` title="${escAttr(uiText(title))}"`:''}><input type="checkbox" data-maya-key="${key}"${checked?' checked':''}${disabled?' disabled':''}> ${uiText(label)}</label>`:'';
  const envText=Object.entries(cfg.env||{}).map(([k,v])=>`${k}=${v}`).join('\n');
  host.innerHTML=`<div class="maya-model-head"><strong>${uiText('Configuración de Project Maya')}</strong><span class="recommendation-badge">${escAttr(cfg.family_label||cfg.family)}</span></div>
    <details class="settings-group maya-disclosure"><summary>Ajustes avanzados de Maya</summary><div class="maya-disclosure-body">
    <div class="maya-model-grid">
      ${row('gpus','GPUs (índices o vacío)',`<input type="text" data-maya-key="gpus" value="${escAttr(cfg.gpus)}" placeholder="0 o 0,1">`)}
      ${row('parallel','Ranuras paralelas',`<input type="number" min="1" max="8" data-maya-key="parallel" value="${escAttr(cfg.parallel)}">`)}
      ${row('reserve_mib','Reserva VRAM (MiB)',`<input type="number" min="0" data-maya-key="reserve_mib" value="${escAttr(cfg.reserve_mib)}" placeholder="auto">`)}
      ${row('reserve_gb','Reserva VRAM (GB)',`<input type="number" min="0" step="0.5" data-maya-key="reserve_gb" value="${escAttr(cfg.reserve_gb)}" placeholder="auto">`)}
      ${row('cache_gb','Caché de expertos (GB)',`<input type="number" min="0" step="1" data-maya-key="cache_gb" value="${escAttr(cfg.cache_gb)}" placeholder="auto">`)}
      ${row('draft','Estrategia Draft / MTP',`<select data-maya-key="draft">${opt(cfg.schema?.draft_options||['auto','none'],cfg.draft)}</select>`)}
      ${row('dspark_conf','Umbral DSpark (0–1)',`<input type="number" min="0" max="1" step="0.05" data-maya-key="dspark_conf" value="${escAttr(cfg.dspark_conf)}" placeholder="auto">`)}
      ${row('tp','Paralelismo tensorial (TP)',`<input type="number" min="1" max="16" data-maya-key="tp" value="${escAttr(cfg.tp)}" placeholder="1">`)}
      ${row('mmap','Memoria mapeada (mmap)',`<select data-maya-key="mmap">${opt(cfg.schema?.mmap_options||['auto','on','off'],cfg.mmap)}</select>`)}
      ${row('expert_cache','Caché de expertos',`<input type="text" data-maya-key="expert_cache" value="${escAttr(cfg.expert_cache)}" placeholder="auto">`)}
      ${row('prefill','Lote de lectura (Prefill)',`<input type="text" data-maya-key="prefill" value="${escAttr(cfg.prefill)}" placeholder="auto">`)}
      ${row('prefill_chunk','Tamaño de chunk prefill',`<input type="number" min="64" step="64" data-maya-key="prefill_chunk" value="${escAttr(cfg.prefill_chunk)}" placeholder="auto">`)}
      ${row('cpu_threads','Hilos de CPU',`<input type="number" min="1" max="512" data-maya-key="cpu_threads" value="${escAttr(cfg.cpu_threads)}" placeholder="auto">`)}
      ${row('prompt_lookup','Lookup de prompt',`<input type="number" min="0" max="16" data-maya-key="prompt_lookup" value="${escAttr(cfg.prompt_lookup)}">`)}
      ${row('kv','Formato KV',`<select data-maya-key="kv">${opt(cfg.schema?.kv_options||['fp16'],cfg.kv)}</select>`)}
      ${row('kv_cache','Formato caché KV',`<select data-maya-key="kv_cache">${opt(cfg.schema?.kv_options||['fp16','int8'],cfg.kv_cache)}</select>`)}
      ${row('ram_gb','RAM para expertos (GB)',`<input type="number" min="0" step="1" data-maya-key="ram_gb" value="${escAttr(cfg.ram_gb)}" placeholder="auto">`)}
      ${row('reasoning_effort','Razonamiento por defecto',`<select data-maya-key="reasoning_effort">${opt(['default',...(cfg.schema?.effort_options||[])],cfg.reasoning_effort)}</select>`)}
      ${row('thinking_budget','Presupuesto de pensamiento (tokens)',`<input type="number" min="0" max="262144" step="256" data-maya-key="thinking_budget" value="${escAttr(cfg.thinking_budget)}">`)}
      ${row('idle_unload_s','Descarga automática en reposo (s)',`<input type="number" min="0" max="86400" step="10" data-maya-key="idle_unload_s" value="${escAttr(cfg.idle_unload_s)}">`)}
    </div>
    <div class="maya-model-checks">
      ${chk('fast_prefill','Lectura rápida de prompt (DeepSeek)',cfg.fast_prefill)}
      ${chk('kv_streaming','Streaming KV',cfg.kv_streaming,!!cfg.schema?.kv_streaming_locked,cfg.schema?.kv_streaming_locked?'GLM-5.3 744B desactiva kv_streaming por defecto':'')}
      ${row('kv_resident','Ventana KV en GPU (tokens)',`<input type="number" min="0" max="1048576" data-maya-key="kv_resident" value="${escAttr(cfg.kv_resident)}" placeholder="auto">`)}
      ${chk('images','Soporte de imágenes (Visión)',cfg.images)}
      ${chk('vision_resident','Codificador de visión residente',cfg.vision_resident)}
      ${chk('turbo','Modo Turbo (GLM-5.3)',cfg.turbo)}
      ${chk('ablate','Desactivar rechazo (Ablate)',cfg.ablate)}
    </div>
    ${fields.has('env')?`<details class="maya-env-box"><summary>${uiText('Variables de entorno de Maya (MAYA_*)')}</summary><textarea id="mayaEnvInput" rows="3" spellcheck="false" placeholder="MAYA_EXPERT_RAM_GB=64">${escAttr(envText)}</textarea></details>`:''}
    <div class="maya-model-foot"><button id="saveMayaModel" type="button" class="soft-btn primary">${uiText('Guardar configuración de Maya')}</button><span id="mayaModelStatus" class="mini" role="status"></span></div></div></details>`;
  const disclosure=host.querySelector('.maya-disclosure-body');
  const groups=[
    ['Carga y memoria',['gpus','parallel','reserve_mib','reserve_gb','cache_gb','expert_cache','ram_gb','tp','mmap','kv','kv_cache','kv_streaming','kv_resident','cpu_threads','idle_unload_s']],
    ['Generación y caché',['draft','dspark_conf','prefill','prefill_chunk','prompt_lookup','fast_prefill','reasoning_effort','thinking_budget','ablate']],
    ['Visión',['images','vision_resident']]
  ];
  for(const [title,keys] of groups){
    const controls=keys.map(key=>disclosure.querySelector(`[data-maya-field="${key}"]`)).filter(Boolean);
    if(!controls.length)continue;
    const group=document.createElement('details');group.className='settings-group maya-disclosure';
    const summary=document.createElement('summary');summary.textContent=title;
    const grid=document.createElement('div');grid.className='maya-model-grid';grid.append(...controls);
    group.append(summary,grid);
    disclosure.insertBefore(group,disclosure.querySelector('.maya-env-box,.maya-model-foot'));
  }
  disclosure.querySelector('.maya-model-grid:empty')?.remove();
  disclosure.querySelector('.maya-model-checks:empty')?.remove();
  const initialValues=new Map(Array.from(host.querySelectorAll('[data-maya-key]'),el=>[el,el.type==='checkbox'?el.checked:el.value]));
  const initialEnv=host.querySelector('#mayaEnvInput')?.value;
  host.querySelector('#saveMayaModel').onclick=async()=>{
    if(busy||engineBusy)return;
    const settings={};
    for(const el of host.querySelectorAll('[data-maya-key]')){
      if(el.disabled||(el.type==='checkbox'?el.checked:el.value)===initialValues.get(el))continue;
      const k=el.dataset.mayaKey;
      if(el.type==='checkbox')settings[k]=el.checked;
      else if(el.type==='number'&&el.value!=='')settings[k]=Number(el.value);
      else settings[k]=el.value;
    }
    if($('#mayaEnvInput')&&$('#mayaEnvInput').value!==initialEnv){
      const env={};
      for(const line of $('#mayaEnvInput').value.split(/\r?\n/)){
        const t=line.trim();if(!t||t.startsWith('#'))continue;
        const idx=t.indexOf('=');
        if(idx<=0){$('#mayaModelStatus').textContent=uiText('Cada variable debe tener el formato CLAVE=VALOR.');return;}
        env[t.slice(0,idx).trim()]=t.slice(idx+1).trim();
      }
      settings.env=env;
    }
    if(!Object.keys(settings).length)return;
    try{
      const res=await requestJSON('/api/harness/maya/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:modelId,settings})});
      const updated=res.maya_config;if(model)model.maya_config=updated;
      await loadModels();
      const status=$('#mayaModelStatus');if(status)status.textContent=uiText(res.pending_reload?'Guardado. Se aplicará al recargar.':'Configuración de Maya guardada.');
    }catch(error){$('#mayaModelStatus').textContent=uiText(error.message);}
  };
  host.querySelectorAll('details').forEach((item,i)=>item.open=!!openSections[i]);
  window.VALI18n?.observe(host);
}
async function restoreEngine(){
  engineSnapshot=await requestJSON('/api/harness/state');activeEngine=engineSnapshot.active;
  $('#engineKind').value=activeEngine;if($('#strataVariant'))$('#strataVariant').value=engineSnapshot.strata?.variant||'official';if($('#strataExecutable'))$('#strataExecutable').value=engineSnapshot.strata?.executable||'';if($('#rustVariant'))$('#rustVariant').value=engineSnapshot.rust?.variant||'official';if($('#rustExecutable'))$('#rustExecutable').value=engineSnapshot.rust?.executable||'';$('#llamaVariant').value=engineSnapshot.llama?.variant||'cuda';$('#llamaExecutable').value=engineSnapshot.llama?.executable||'';$('#llamaLayers').value=engineSnapshot.llama?.gpu_layers||'auto';if($('#mayaRoot'))$('#mayaRoot').value=engineSnapshot.maya?.root||'';if($('#mayaExecutable'))$('#mayaExecutable').value=engineSnapshot.maya?.executable||'';if($('#mayaBackend'))$('#mayaBackend').value=engineSnapshot.maya?.backend||'auto';syncApiConnections();$('#engineKind').onchange();syncEngineCapabilities();
}
function syncEngineCapabilities(){
  if(!$('#engineSettings'))return;
  syncLoadSettings();
  const remote=activeEngine==='api',strata=activeEngine==='strata',maya=activeEngine==='maya';
  $('#controls-context').hidden=remote;if($('#contextBlock'))$('#contextBlock').hidden=remote;if($('#loadAdvanced'))$('#loadAdvanced').hidden=remote||maya;if($('#modelTransfer'))$('#modelTransfer').hidden=remote;if($('#modelSectionTabs'))$('#modelSectionTabs').hidden=remote;if(remote)setModelSection('generation');$('#effort').closest('.row').hidden=false;$('#kvSettings').hidden=remote||maya;$('#draftSettings').hidden=!strata;$('#visionSettings').hidden=remote||activeEngine==='rust'||maya;
  $('#templateRow').hidden=!strata;if($('#templateSettings'))$('#templateSettings').hidden=!strata;
  const power=$('#engineToggle').closest('.power-row');if(power)power.hidden=['llama','rust','maya'].includes(activeEngine)||engineFormDirty();
  for(const id of ['p_topk','p_minp','p_rep','p_presence','p_frequency','p_seed'])if($('#'+id)?.closest('.row'))$('#'+id).closest('.row').hidden=remote;
  const claude=remote&&engineSnapshot?.api?.protocol==='anthropic',hideSampling=remote&&(!engineSnapshot?.api?.send_sampling||claude&&engineSnapshot?.api?.api_version>='2026-10-21');for(const id of ['p_temp','p_topp'])if($('#'+id)?.closest('.row'))$('#'+id).closest('.row').hidden=hideSampling;
  for(const id of ['creatorNotice','creatorReset','codeProtection'])if($('#'+id))$('#'+id).hidden=remote;
  if($('#p_temp'))$('#p_temp').closest('details').hidden=hideSampling;
  if(remote){$('#load').textContent=uiText('Usar modelo');$('#unload').textContent=uiText('Dejar de usar');$('#engineToggle').textContent=uiText(engineOnline?'Desconectar API':'Conectar API');}
  else if(!engineBusy){$('#load').textContent=uiText('Cargar modelo');$('#unload').textContent=uiText('Descargar modelo');}
  $('#engineSettings').querySelectorAll('input,select,button').forEach(el=>el.disabled=busy||engineBusy);$('#modelSourceTabs').querySelectorAll('button').forEach(el=>el.disabled=busy||engineBusy);
  window.syncMayaActionButtons?.();
  $('#applyEngine').disabled=busy||engineBusy||!engineFormDirty();if(engineFormDirty())$('#load').disabled=true;
  if(activeEngine==='llama'&&$('#visionEncoder')){$('#visionEncoder').value=uiText('Integrado en llama.cpp');$('#browseEncoder').hidden=true;}else if($('#browseEncoder'))$('#browseEncoder').hidden=false;
  const add=$('#addModel');if(add){add.hidden=remote;add.textContent=uiText(maya?'Preparar modelo con Maya':'+ Añadir');if(maya)add.disabled=busy||engineBusy||!!loadedModel;}
  if($('#modelResults'))$('#modelResults').setAttribute('aria-label',uiText(remote?'Modelos de la API':'Modelos instalados'));
  if($('#remoteModelInfo')){$('#remoteModelInfo').hidden=!remote;const usage=$('#contextUsage');if(usage){if(remote){$('#remoteModelInfo .remote-context-stats')?.after(usage);}else{$('#controls-context')?.prepend(usage);}}}
  if($('#contextCompactBox')){if(remote&&$('#remoteModelInfo'))$('#remoteModelInfo').after($('#contextCompactBox'));else if($('#contextBlock'))$('#contextBlock').after($('#contextCompactBox'));$('#contextCompactBox').hidden=false;}
  $('#composerControls').dataset.activeSource=remote?'api':'local';if($('#engineQuickSettings')){const label=$('#engineQuickSettings span')||$('#engineQuickSettings');label.textContent=uiText(remote?'Gestionar conexiones':'Cambiar motor');}
  syncMayaModelSettings();syncModelSelectionSummary();syncSettingsSummary();
}
function engineFormDirty(){
  if(!engineSnapshot||!$('#engineKind'))return false;const kind=$('#engineKind').value;if(kind!==activeEngine)return true;
  if(kind==='strata'){const s=engineSnapshot.strata||{};return ($('#strataVariant')?.value||'official')!==(s.variant||'official')||($('#strataExecutable')?.value.trim()||'')!==(s.executable||'');}
  if(kind==='rust'){const r=engineSnapshot.rust||{};return ($('#rustVariant')?.value||'official')!==(r.variant||'official')||($('#rustExecutable')?.value.trim()||'')!==(r.executable||'');}
  const saved=engineSnapshot.llama||{};
  if(kind==='maya'){
    const m=engineSnapshot.maya||{};
    return ($('#mayaRoot')?.value.trim()||'')!==(m.root||'')||($('#mayaExecutable')?.value.trim()||'')!==(m.executable||'')||($('#mayaBackend')?.value||'auto')!==(m.backend||'auto');
  }
  if(kind==='api'){
    const cfg=engineSnapshot.api||{};
    const sessionMode=cfg.send_session_id===true?'always':cfg.send_session_id===false?'off':'auto';
    const uaPreset=$('#apiUserAgentPreset').value;
    const uaVal=uaPreset==='default'?'':$('#apiUserAgent').value;
    return $('#apiConnection').value!==(cfg.id||'')||$('#apiPreset').value!==apiPresetChoice(cfg)||$('#apiProtocol').value!==(cfg.protocol||'openai')||$('#apiBase').value!==(cfg.base_url||'')||$('#apiName').value!==(cfg.name||'')||!!$('#apiKey').value||$('#apiAuthMode').value!==(cfg.auth_mode||'auto')||uaVal!==(cfg.user_agent||'')||$('#apiSessionMode').value!==sessionMode||$('#apiOrganization').value!==(cfg.organization||'')||$('#apiProject').value!==(cfg.project||'')||$('#apiVersion').value!==(cfg.api_version||'2023-06-01')||$('#apiAnthropicBeta').value!==(cfg.anthropic_beta||'')||$('#apiAzureVersion').value!==(cfg.azure_api_version||'')||$('#apiHttpReferer').value!==(cfg.http_referer||'')||$('#apiXTitle').value!==(cfg.x_title||'')||$('#apiExtraHeaders').value!==formatExtraHeaders(cfg.extra_headers)||Number($('#apiTimeout').value)!==(cfg.timeout||180)||$('#apiVision').checked!==!!cfg.vision||$('#apiUsage').checked!==(cfg.include_usage!==false)||$('#apiSampling').checked!==!!cfg.send_sampling;
  }
  return kind==='llama'&&($('#llamaVariant').value!==(saved.variant||'cuda')||$('#llamaExecutable').value!==(saved.executable||'')||$('#llamaLayers').value!==String(saved.gpu_layers||'auto'));
}
