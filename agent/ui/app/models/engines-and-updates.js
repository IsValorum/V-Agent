function setupAgentProfilesAndUpdates(){
  const profile=document.createElement('div');profile.innerHTML='<div class="agent-profile-row"><label for="agentProfile">Modo del agente</label><select id="agentProfile"><option value="text">Chat</option><option value="light">Agente ligero</option><option value="balanced">Agente estándar</option><option value="advanced">Agente completo</option></select></div><p id="agentProfileHint" class="mini"></p>';
  $('#controls-tools').prepend(profile);
  function hint(){if($('#agentProfileHint'))$('#agentProfileHint').textContent=uiText(AGENT_MODES[agentModeKey()].desc);}
  $('#agentProfile').value=agentModeKey();$('#agentProfile').addEventListener('val-profile-restored',hint);hint();
  $('#agentProfile').onchange=async()=>{const wanted=$('#agentProfile').value;const changed=await setAgentMode(wanted);if(!changed)$('#agentProfile').value=agentModeKey();hint();};
  setupAgentModeSeat();
  const updates=document.createElement('section');updates.id='engineUpdates';updates.innerHTML='<div id="engineHardware" class="engine-hardware"><div class="engine-hardware-head"><h4>Hardware y motores recomendados</h4><div class="engine-hardware-actions"><button id="checkEngineUpdates" type="button">Comprobar actualizaciones</button><button id="copyHardware" type="button">Copiar informe</button></div></div><div id="hwChips" class="hardware-chips"></div><p id="hwSummary" class="mini"></p><p id="engineUpdateStatus" class="mini" role="status"></p><div id="engineRecommendations" class="engine-recommendations"></div></div><div id="engineUpdateList" hidden></div>';
  $('#settings-system').append(updates);
  const stack=document.createElement('div');stack.id='updateStack';stack.className='update-stack';stack.hidden=true;document.body.append(stack);
  const dismissed=new Set();
  async function action(which,body={}){
    const btn=$('#checkEngineUpdates');if(btn)btn.disabled=true;
    try{const state=await requestJSON('/api/harness/updates/'+which,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});paintUpdates(state);clearTimeout(updatePollTimer);updatePollTimer=setTimeout(pollUpdates,state.installing?400:10000);}
    catch(error){const msg=uiText(error.message);$('#engineUpdateStatus').textContent=msg;note(msg);if(btn)btn.disabled=false;}
  }
  $('#checkEngineUpdates').onclick=()=>action('check');
  let hardwareSignature='';
  function hardwareChip(label,value,title=''){
    const chip=document.createElement('span');chip.className='hardware-chip';chip.title=title;
    const small=document.createElement('small');small.textContent=label;const strong=document.createElement('strong');strong.textContent=value||'—';
    chip.append(small,strong);return chip;
  }
  function paintHardware(state){
    const profile=state.hardware||{},rows=state.recommendations||[];
    const mayaDiskInstalled=Boolean(engineSnapshot?.builds?.maya?.root);
    const signature=JSON.stringify({profile,rows,summary:state.hardware_summary,busy:state.busy,loaded:localModelLoaded(),releases:state.releases,installed:state.installed,previous:state.previous,mayaDiskInstalled,lang:window.VALI18n?.language||'es'});
    if(signature===hardwareSignature)return;hardwareSignature=signature;
    const chips=$('#hwChips');if(!chips)return;chips.replaceChildren();
    const gpu=profile.primary_gpu||{};
    chips.append(hardwareChip(uiText('CPU'),profile.cpu?.name||'—',profile.cpu?.name||''));
    chips.append(hardwareChip(uiText('GPU'),gpu.name||uiText('Sin GPU NVIDIA'),gpu.name?`${gpu.vendor||''} ${gpu.driver||''} ${gpu.cuda_capability?('CC '+gpu.cuda_capability):''}`.trim():''));
    chips.append(hardwareChip('VRAM',gpu.vram_mib?uiNumber(Math.round(gpu.vram_mib/1024))+' GB':'—'));
    chips.append(hardwareChip('RAM',profile.ram?.total_gib?uiNumber(profile.ram.total_gib)+' GB':'—'));
    chips.append(hardwareChip(uiText('Disco libre'),profile.disk?.free_gib?uiNumber(profile.disk.free_gib)+' GB':'—'));
    chips.append(hardwareChip(uiText('Sistema'),[profile.os?.product,profile.os?.display].filter(Boolean).join(' · ')||'—'));
    const summary=$('#hwSummary');if(summary)summary.textContent=uiParts(state.hardware_summary||'');
    const box=$('#engineRecommendations');if(!box)return;box.replaceChildren();
    const seen=new Set();
    for(const row of rows){
      seen.add(row.key);
      const release=(state.releases||{})[row.key]||{};
      const managedInstalled=Object.hasOwn(state.installed||{},row.key);
      const mayaInstalled=row.key==='maya'&&Boolean(release.current||mayaDiskInstalled);
      const installedHere=Boolean(row.status==='installed'||release.current||managedInstalled||mayaInstalled);
      const card=document.createElement('article');card.className='engine-recommendation';card.dataset.engine=row.key;
      const head=document.createElement('div');head.className='engine-recommendation-head';
      const name=document.createElement('strong');name.textContent=row.name;
      const badge=document.createElement('span');badge.className='recommendation-badge';badge.textContent=uiText(row.recommended?'Recomendado':'Opcional');head.append(name,badge);
      const reason=document.createElement('p');reason.className='mini';reason.textContent=uiParts(row.reason);
      const asset=document.createElement('div');asset.className='engine-asset';
      const tag=document.createElement('code');tag.textContent=row.tag||release.tag||uiText('Sin versión publicada');asset.append(tag);
      if(row.asset||release.asset){const filename=document.createElement('code');filename.textContent=row.asset||release.asset;asset.append(filename);}
      if(row.dependencies?.length){const extra=document.createElement('small');extra.textContent='+ '+row.dependencies.join(' + ');asset.append(extra);}
      const actions=document.createElement('div');actions.className='engine-recommendation-actions';
      const status=document.createElement('span');status.className='engine-recommendation-status';
      const optionalSource=row.status==='optional';
      status.textContent=release.error?uiText(release.error):installedHere&&release.available?uiText('Actualización disponible'):installedHere?uiText('Instalado'):row.status==='available'?uiText('Actualización disponible'):optionalSource?uiText('Compilación local opcional'):(row.asset||release.asset)?uiText('Disponible'):uiText('Comprueba las versiones');
      status.dataset.state=row.status;
      actions.append(status);
      if(release.url){
        const notesLink=document.createElement('a');notesLink.href=release.url;notesLink.className='engine-notes-link';notesLink.textContent=uiText('Notas de versión');
        notesLink.onclick=event=>{event.preventDefault();showReleaseNotes({...release,key:row.key});};
        actions.append(notesLink);
      }
      if(row.key==='maya'){
        if(installedHere&&release.available){
          const updateBtn=document.createElement('button');updateBtn.type='button';updateBtn.textContent=uiText('Actualizar');updateBtn.disabled=!!state.busy||busy||localModelLoaded();
          updateBtn.onclick=async()=>{
            updateBtn.disabled=true;
            try{
              const res=await requestJSON('/api/harness/maya/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'update',tag:release.tag||''})});
              if(res.snapshot){engineSnapshot=res.snapshot;syncEngineVersions();syncSettingsSummary();}
              note(uiText('Copia de Project Maya actualizada. Compila si hubo cambios en C++.'));
              action('check',{force:true});
            }catch(error){note(uiText(error.message));updateBtn.disabled=false;}
          };
          actions.append(updateBtn);
        }
        const manage=document.createElement('button');manage.type='button';manage.textContent=uiText('Gestionar en Motor');
        manage.onclick=()=>{setDrawer(false);setChatControls('model');window.openEngineConfigWindow?.(false);};
        actions.append(manage);
        if(installedHere){
          const remove=document.createElement('button');remove.type='button';remove.className='soft-btn danger';remove.textContent=uiText('Eliminar');remove.disabled=!!state.busy||busy||localModelLoaded();
          remove.onclick=async()=>{if(!await valConfirm({title:uiText('¿Desvincular Project Maya?'),message:uiText('La carpeta de Maya y sus modelos se conservan en el disco.'),confirm:uiText('Desvincular')}))return;await action('uninstall',{engine:'maya'});requestJSON('/api/harness/state').then(snapshot=>{engineSnapshot=snapshot;syncEngineVersions();syncSettingsSummary();}).catch(()=>{});};
          actions.append(remove);
        }
      }else{
        if((row.asset||release.asset)&&(release.available||!installedHere)){
          const install=document.createElement('button');install.type='button';install.textContent=uiText(installedHere?'Actualizar':'Instalar');install.disabled=!!state.busy||busy||localModelLoaded();install.onclick=()=>action('install',{engine:row.key});actions.append(install);
        }else if(!installedHere&&row.status!=='missing'){
          const check=document.createElement('button');check.type='button';check.textContent=uiText('Comprobar');check.disabled=!!state.busy;check.onclick=()=>action('check');actions.append(check);
        }
        if(Object.hasOwn(state.previous||{},row.key)){
          const rollback=document.createElement('button');rollback.type='button';rollback.textContent=uiText('Restaurar anterior');rollback.disabled=!!state.busy||busy||localModelLoaded();rollback.onclick=()=>action('rollback',{engine:row.key});actions.append(rollback);
        }
        if(managedInstalled){
          const remove=document.createElement('button');remove.type='button';remove.className='soft-btn danger';remove.textContent=uiText('Eliminar');remove.disabled=!!state.busy||busy||localModelLoaded();
          remove.onclick=async()=>{if(!await valConfirm({title:uiText('¿Eliminar este motor?'),message:uiText('Se borrarán los archivos descargados del motor. Podrás volver a instalarlo cuando quieras.'),confirm:uiText('Eliminar'),danger:true}))return;action('uninstall',{engine:row.key});};
          actions.append(remove);
        }
      }
      card.append(head,reason,asset,actions);box.append(card);
    }
    window.VALI18n?.observe(updates);
    return seen;
  }
  $('#copyHardware').onclick=async()=>{try{const data=await requestJSON('/api/harness/hardware');await navigator.clipboard.writeText(JSON.stringify({hardware:data.hardware,recommendations:data.recommendations,summary:data.hardware_summary},null,2));note(uiText('Informe copiado.'));}catch(error){note(error.message);}};
  let signature='',installedSignature='',lastUpdateState=null;
  const noteSummaryCache=new Map();
  const compactReleaseSummary=(notes,limit=160)=>{
    // HTML tags first: llama.cpp's notes start with "<details open>", which showed as "<details open".
    const clean=String(notes||'').replace(/<\/?[a-z][^>]*>/gi,' ').replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/^\s*(?:#{1,6}\s*|[-*+]\s+|\d+\.\s+)/gm,'').replace(/[`*_>~]+/g,'').replace(/\s+/g,' ').trim();
    return !clean?'':clean.length<=limit?clean:clean.slice(0,limit-1).trimEnd()+'…';
  };
  function paintStackProgress(progress){
    const card=stack.querySelector(':scope > .update-card');if(!card)return;
    let box=card.querySelector('.update-progress');
    if(!progress||progress.phase==='complete'||progress.phase==='error'){box?.remove();return;}
    const percent=progress.total?Math.min(100,progress.received/progress.total*100):0;
    if(!box){
      box=document.createElement('div');box.className='update-progress';
      const label=document.createElement('span');const bar=document.createElement('progress');bar.max=100;
      box.append(label,bar);const actions=card.querySelector('.update-actions');if(actions)actions.before(box);else card.append(box);
    }
    const label=box.querySelector('span'),bar=box.querySelector('progress');
    label.textContent=uiText({download:'Descargando',link:'Vinculando',extract:'Extrayendo',verify:'Verificando',complete:'Completado',error:'Error'}[progress.phase]||'Procesando')+' · '+percent.toFixed(1)+' % · '+(progress.received/1048576).toFixed(1)+' / '+(progress.total/1048576).toFixed(1)+' MB';
    bar.value=percent;
  }
  function paintUpdates(state){
    lastUpdateState=state;
    // Progress ticks must not rebuild the card: that made the notification blink.
    const lang=window.VALI18n?.language||'es';
    const progress=state.progress?{engine:state.progress.engine,phase:state.progress.phase,total:state.progress.total||0}:null;
    const mayaDiskInstalled=Boolean(engineSnapshot?.builds?.maya?.root);
    const current=JSON.stringify({...state,progress,lang,mayaDiskInstalled});if(current===signature){lastUpdateInstalling=!!state.installing;paintDownloadProgress(state.progress);paintStackProgress(state.progress);return;}signature=current;
    const installed=JSON.stringify(state.installed||{});if((installed!==installedSignature||(lastUpdateInstalling&&!state.installing))&&!state.busy){installedSignature=installed;requestJSON('/api/harness/state').then(snapshot=>{engineSnapshot=snapshot;syncEngineVersions();syncSettingsSummary();}).catch(()=>{});}
    $('#engineUpdateStatus').textContent=(state.error?uiText(state.error):'')||(state.operation?uiText(state.operation):'')||(state.busy?uiText('Comprobando…'):'');$('#checkEngineUpdates').disabled=state.busy;
    lastUpdateInstalling=!!state.installing;paintDownloadProgress(state.progress);
    const renderedKeys=paintHardware(state)||new Set((state.recommendations||[]).map(r=>r.key));
    const list=$('#engineUpdateList');list.replaceChildren();
    const names={'llama-cpu':'llama.cpp · CPU','llama-cuda':'llama.cpp · CUDA 12.4','llama-vulkan':'llama.cpp · Vulkan',strata:'Strata · PolyStrata',rust:'Strata Rust',maya:'Project Maya'};
    const releaseEntries=Object.entries(state.releases||{}).filter(([key])=>!renderedKeys.has(key));
    if(mayaDiskInstalled&&!state.releases?.maya&&!renderedKeys.has('maya'))releaseEntries.push(['maya',{tag:'',current:engineSnapshot?.builds?.maya?.build||engineSnapshot?.builds?.maya?.version||'',source_only:true,url:'https://github.com/mw00/project-maya/releases',repository:'mw00/project-maya'}]);
    list.hidden=!releaseEntries.length;
    for(const [key,release] of releaseEntries){
      const managedInstalled=Object.hasOwn(state.installed||{},key);
      const mayaInstalled=key==='maya'&&Boolean(release.current||mayaDiskInstalled);
      const installedHere=Boolean(release.current||managedInstalled||mayaInstalled);
      const row=document.createElement('div');row.className='engine-update-row';const name=document.createElement('strong');name.textContent=names[key]||key;const details=document.createElement('small');
      let detailText=release.error||(release.message?uiText(release.message):'')||'';
      if(!detailText){
        const stateLabel=key==='maya'
          ?(installedHere?(release.available?uiText('Disponible'):uiText('Actualizado')):uiText('Compilación local opcional'))
          :(installedHere?(release.available?uiText('Disponible'):uiText('Actualizado')):uiText('No instalado'));
        detailText=(release.tag?release.tag+' · ':'')+stateLabel+(release.development?' · '+uiText('Desarrollo oficial'):'');
      }
      details.textContent=detailText;row.append(name,details);
      if(release.url){const link=document.createElement('a');link.href=release.url;link.onclick=event=>{event.preventDefault();showReleaseNotes({...release,key});};link.textContent=uiText('Notas de versión');row.append(link);}
      const actions=document.createElement('div');actions.className='engine-update-actions';
      if(key==='maya'){
        if(installedHere&&release.available){
          const updateBtn=document.createElement('button');updateBtn.textContent=uiText('Actualizar');updateBtn.disabled=state.busy||busy||localModelLoaded();
          updateBtn.onclick=async()=>{
            try{
              const res=await requestJSON('/api/harness/maya/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'update',tag:release.tag||''})});
              if(res.snapshot){engineSnapshot=res.snapshot;syncEngineVersions();syncSettingsSummary();}
              note(uiText('Copia de Project Maya actualizada. Compila si hubo cambios en C++.'));
              action('check',{force:true});
            }catch(error){note(uiText(error.message));}
          };
          actions.append(updateBtn);
        }
        const openBtn=document.createElement('button');openBtn.textContent=uiText('Gestionar en Motor');
        openBtn.onclick=()=>{setDrawer(false);setChatControls('model');window.openEngineConfigWindow?.(false);};
        actions.append(openBtn);
        if(installedHere){
          const remove=document.createElement('button');remove.className='soft-btn danger';remove.textContent=uiText('Eliminar');remove.disabled=state.busy||busy||localModelLoaded();
          remove.onclick=async()=>{if(!await valConfirm({title:uiText('¿Desvincular Project Maya?'),message:uiText('La carpeta de Maya y sus modelos se conservan en el disco.'),confirm:uiText('Desvincular')}))return;await action('uninstall',{engine:'maya'});requestJSON('/api/harness/state').then(snapshot=>{engineSnapshot=snapshot;syncEngineVersions();syncSettingsSummary();}).catch(()=>{});};
          actions.append(remove);
        }
      }else{
        if(release.asset&&(release.available||!installedHere)){const button=document.createElement('button');button.textContent=uiText(installedHere?'Actualizar':'Instalar');button.disabled=state.busy||busy||localModelLoaded();button.onclick=()=>action('install',{engine:key});actions.append(button);}
        if(Object.hasOwn(state.previous||{},key)){const rollback=document.createElement('button');rollback.textContent=uiText('Restaurar anterior');rollback.disabled=state.busy||busy||localModelLoaded();rollback.onclick=()=>action('rollback',{engine:key});actions.append(rollback);}
        if(managedInstalled){const remove=document.createElement('button');remove.className='soft-btn danger';remove.textContent=uiText('Eliminar');remove.disabled=state.busy||busy||localModelLoaded();remove.onclick=async()=>{if(!await valConfirm({title:uiText('¿Eliminar este motor?'),message:uiText('Se borrarán los archivos descargados del motor. Podrás volver a instalarlo cuando quieras.'),confirm:uiText('Eliminar'),danger:true}))return;action('uninstall',{engine:key});};actions.append(remove);}
      }
      if(actions.children.length)row.append(actions);
      list.append(row);
    }
    renderUpdateStack(state);
    window.VALI18n?.observe(updates);window.VALI18n?.observe(stack);
  }
  window.VALI18n?.onChange?.(()=>{if(lastUpdateState){hardwareSignature='';signature='';delete stack.dataset.signature;paintUpdates(lastUpdateState);positionUpdateStack();}});
  function positionUpdateStack(){
    if(stack.hidden)return;
    const composer=document.getElementById('composerBox'),measured=composer&&composer.getBoundingClientRect();
    // While the composer glides to its new place, measure where it will land (minus its running transform).
    const shift=composer?new DOMMatrixReadOnly(getComputedStyle(composer).transform==='none'?undefined:getComputedStyle(composer).transform).m42:0;
    const rect=measured&&{top:measured.top-shift,bottom:measured.bottom-shift};
    const available=rect?Math.max(0,innerHeight-rect.bottom-16):0;
    const height=stack.scrollHeight||stack.offsetHeight||0;
    const bottom=rect&&height>available?Math.round(innerHeight-rect.top+12):16;
    stack.style.setProperty('--update-bottom',Math.max(16,bottom)+'px');
  }
  function renderUpdateStack(state){
    // Settings → System is marked while an installed engine has a newer release, dismissed card or not.
    window.markUpdateBadge?.('engine',Object.entries(state.releases||{}).some(([key,release])=>(Boolean(release.current)||Boolean(state.installed?.[key]))&&release.available&&(Boolean(release.asset)||key==='maya')));
    const names={'llama-cpu':'llama.cpp · CPU','llama-cuda':'llama.cpp · CUDA 12.4','llama-vulkan':'llama.cpp · Vulkan',strata:'Strata · PolyStrata',rust:'Strata Rust',maya:'Project Maya'};
    // Only notify about newer releases for engines the user actually installed (never push uninstalled engines).
    let available=Object.entries(state.releases||{}).filter(([key,release])=>(Boolean(release.current)||Boolean(state.installed?.[key]))&&release.available&&(Boolean(release.asset)||key==='maya')&&!dismissed.has(key+':'+release.tag));
    const variant=document.getElementById('llamaVariant')?.value||'cuda';
    const preferred='llama-'+(['cpu','vulkan'].includes(variant)?variant:'cuda');
    const llama=available.find(([key])=>key===preferred);
    available=available.filter(([key])=>!key.startsWith('llama-'));
    if(llama)available.unshift(llama);
    const shown=available.slice(0,1),remaining=available.length-shown.length;
    const deferred=Date.now()/1000<=(state.deferred_until||0);
    if(!available.length||deferred){stack.hidden=true;stack.replaceChildren();delete stack.dataset.signature;return;}
    // Progress polls arrive every 400 ms while installing. Rebuilding the card each time replayed its
    // entrance animation (the window "blinked"); rebuild only when what is shown changes.
    const progressFor=key=>state.progress&&state.progress.engine===key&&state.progress.phase!=='complete'&&state.progress.phase!=='error'?state.progress:null;
    const progressText=progress=>{const percent=progress.total?Math.min(100,progress.received/progress.total*100):0;return [percent,uiText({download:'Descargando',link:'Vinculando',extract:'Extrayendo',verify:'Verificando',complete:'Completado',error:'Error'}[progress.phase]||'Procesando')+' · '+percent.toFixed(1)+' % · '+(progress.received/1048576).toFixed(1)+' / '+(progress.total/1048576).toFixed(1)+' MB'];};
    const installDisabled=!!state.busy||busy||localModelLoaded();
    const lang=window.VALI18n?.language||'es';
    const cardError=state.error||'';
    const signature=JSON.stringify([shown.map(([key,release])=>{const p=progressFor(key);return [key,release.tag,release.current,release.summary||'',p?p.phase:''];}),remaining,lang,cardError]);
    if(stack.dataset.signature===signature&&stack.children.length){
      for(const [key] of shown){
        const card=stack.querySelector('.update-card'),progress=progressFor(key);if(!card)continue;
        if(progress){const [percent,text]=progressText(progress);const label=card.querySelector('.update-progress span'),bar=card.querySelector('.update-progress progress');if(label&&label.textContent!==text)label.textContent=text;if(bar)bar.value=percent;}
        else{card.querySelector('.update-progress')?.remove();}
        const install=card.querySelector('.update-install');if(install){install.disabled=installDisabled;install.title=localModelLoaded()?uiText('Descarga el modelo antes de actualizar.'):'';}
      }
      return;
    }
    stack.dataset.signature=signature;
    stack.hidden=false;stack.replaceChildren();
    for(const [key,release] of shown){
      const cacheKey=key+':'+(release.tag||'');
      const card=document.createElement('article');card.className='update-card';
      const close=document.createElement('button');close.type='button';close.className='update-card-close';close.setAttribute('aria-label',uiText('Descartar aviso'));close.textContent='×';
      close.onclick=()=>{dismissed.add(cacheKey);delete stack.dataset.signature;renderUpdateStack(state);};
      const head=document.createElement('div');head.className='update-card-head';
      const icon=document.createElement('span');icon.className='update-card-icon';icon.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M5 21h14"/></svg>';
      const text=document.createElement('div');text.className='update-card-text';
      const title=document.createElement('h4');const titlePrefix=document.createElement('span');titlePrefix.textContent=uiText('Nueva versión de');title.append(titlePrefix,' '+(names[key]||key));
      const version=document.createElement('p');version.className='update-card-version';version.textContent=(release.current?String(release.current)+' → ':'')+(release.tag||'');
      text.append(title,version);head.append(icon,text);card.append(close,head);
      const summaryText=release.summary||compactReleaseSummary(release.notes)||noteSummaryCache.get(cacheKey)||'';
      const notesPreview=document.createElement('p');notesPreview.className='update-card-notes';notesPreview.textContent=summaryText;notesPreview.hidden=!summaryText;
      card.append(notesPreview);
      if(!summaryText&&release.url&&!noteSummaryCache.has(cacheKey)){
        noteSummaryCache.set(cacheKey,'');
        requestJSON('/api/harness/updates/notes?engine='+encodeURIComponent(key)).then(data=>{
          const fetched=compactReleaseSummary(data?.notes);
          noteSummaryCache.set(cacheKey,fetched);
          if(fetched&&notesPreview.isConnected){notesPreview.textContent=fetched;notesPreview.hidden=false;requestAnimationFrame(positionUpdateStack);}
        }).catch(()=>{});
      }
      const activeProgress=progressFor(key);
      if(activeProgress){
        const [percent,labelText]=progressText(activeProgress);
        const box=document.createElement('div');box.className='update-progress';
        const label=document.createElement('span');label.textContent=labelText;
        const bar=document.createElement('progress');bar.max=100;bar.value=percent;
        box.append(label,bar);card.append(box);
      }
      if(cardError&&(!state.progress||state.progress.engine===key)){const err=document.createElement('p');err.className='update-card-error';err.textContent=uiText(cardError);card.append(err);}
      const actions=document.createElement('div');actions.className='update-actions';
      if(release.url||release.summary||release.notes){
        const notesBtn=document.createElement('button');notesBtn.type='button';notesBtn.className='update-notes-btn';notesBtn.textContent=uiText('Notas de versión');
        notesBtn.onclick=()=>showReleaseNotes({...release,key});
        actions.append(notesBtn);
      }
      const install=document.createElement('button');install.type='button';install.className='update-install';install.textContent=uiText('Actualizar');
      install.disabled=installDisabled;
      if(localModelLoaded())install.title=uiText('Descarga el modelo antes de actualizar.');
      if(key==='maya'){
        install.onclick=async()=>{
          install.disabled=true;
          try{
            const res=await requestJSON('/api/harness/maya/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'update',tag:release.tag||''})});
            if(res.snapshot){engineSnapshot=res.snapshot;syncEngineVersions();syncSettingsSummary();}
            note(uiText('Copia de Project Maya actualizada. Compila si hubo cambios en C++.'));
            action('check',{force:true});
          }catch(error){note(uiText(error.message));install.disabled=false;}
        };
      }else{
        install.onclick=()=>action('install',{engine:key});
      }
      actions.append(install);card.append(actions);
      stack.append(card);
    }
    if(remaining>0){
      const row=document.createElement('div');row.className='update-more-row';
      const text=document.createElement('span');text.textContent=uiText(remaining===1?'{n} actualización más del runtime':'{n} actualizaciones más del runtime').replace('{n}',remaining);
      const button=document.createElement('button');button.type='button';button.textContent=uiText('Ver en Ajustes');
      button.onclick=()=>{setDrawer(true);selectSettingsCategory('system');requestAnimationFrame(()=>updates.scrollIntoView({block:'start',behavior:'smooth'}));};
      row.append(text,button);stack.append(row);
    }
    requestAnimationFrame(positionUpdateStack);
  }
  let lastUpdateInstalling=false,updatePollTimer,paintedUpdates=false;
  window.addEventListener('resize',positionUpdateStack);
  if(window.ResizeObserver&&document.getElementById('composerBox'))new ResizeObserver(positionUpdateStack).observe(document.getElementById('composerBox'));
  // The composer moves from the centre to the bottom without resizing; follow it so the notice
  // never covers the send button (once now, once after the move animation).
  const chatwrap=document.getElementById('chatwrap');
  if(chatwrap&&window.MutationObserver)new MutationObserver(()=>{
    requestAnimationFrame(positionUpdateStack);
    const duration=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--motion-duration'))||620;
    setTimeout(positionUpdateStack,duration+60);
  }).observe(chatwrap,{attributes:true,attributeFilter:['data-empty']});
  async function pollUpdates(){if(!document.hidden||!paintedUpdates)try{paintUpdates(await requestJSON('/api/harness/updates'));paintedUpdates=true;positionUpdateStack();}catch{}updatePollTimer=setTimeout(pollUpdates,(lastUpdateInstalling||lastUpdateState?.busy)?400:10000);}
  pollUpdates();
}

async function showReleaseNotes(release){
  if(!release.notes&&release.key){try{release={...release,notes:(await requestJSON('/api/harness/updates/notes?engine='+encodeURIComponent(release.key))).notes};}catch{}}
  let dialog=document.getElementById('releaseNotesDialog');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='releaseNotesDialog';dialog.innerHTML='<header><strong></strong><button type="button" aria-label="Cerrar">×</button></header><div class="release-notes-content"></div><p></p>';document.body.append(dialog);dialog.querySelector('button').onclick=()=>dialog.close();dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});window.VALI18n?.observe(dialog);}
  dialog.querySelector('button').setAttribute('aria-label',uiText('Cerrar'));
  dialog.querySelector('strong').textContent=uiText('Notas de versión')+' · '+release.tag;
  const notes=release.notes||uiText('Las notas de esta versión todavía no están en la caché. Pulsa «Comprobar actualizaciones» para obtenerlas.');
  dialog.querySelector('.release-notes-content').innerHTML=mdHTML(notes.replace(/<\/?(?:details|summary)\b[^>]*>/gi,'').replace(/\n{3,}/g,'\n\n').replace(/<(https?:\/\/[^<>\s]+)>/g,'[$1]($1)'));
  dialog.querySelector('p').textContent=release.url||'';
  dialog.showModal();
}
document.addEventListener('v-agent-show-notes',event=>{if(event.detail)showReleaseNotes(event.detail);});
function paintDownloadProgress(progress){
  let box=document.getElementById('engineDownloadProgress');
  if(!box){box=document.createElement('div');box.id='engineDownloadProgress';box.setAttribute('role','status');box.innerHTML='<label></label><progress max="100"></progress>';document.getElementById('engineUpdateStatus').after(box);}
  const active=Boolean(progress&&progress.phase!=='complete'&&progress.phase!=='error');
  box.hidden=!active;if(!active)return;
  const percent=progress.total?Math.min(100,progress.received/progress.total*100):0;
  const phaseLabel={download:'Descargando',link:'Vinculando',extract:'Extrayendo',verify:'Verificando',complete:'Completado',error:'Error'}[progress.phase]||'Procesando';
  box.querySelector('label').textContent=progress.engine+' · '+uiText(phaseLabel)+' · '+percent.toFixed(1)+' % · '+(progress.received/1048576).toFixed(1)+' / '+(progress.total/1048576).toFixed(1)+' MB';
  box.querySelector('progress').value=percent;
}
