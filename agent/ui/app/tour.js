/* First run, interactive tour and V-Agent's own signed updates.
   Texts are Spanish base phrases translated through uiText (locales.json), so the tour follows the
   language picked in the installer. */
const VAL_TOUR=(()=>{
  const STEPS=[
    {title:'Bienvenido a V-Agent',text:'Un agente de IA que funciona en tu equipo. Este recorrido te muestra dónde está cada cosa y para qué sirve. Puedes salir con Esc y repetirlo desde Configuración.'},
    {engine:true},
    {sel:'#newchat',title:'Nuevo chat',text:'Empieza una conversación. Cada chat tiene su propia carpeta de trabajo aislada, donde el agente guarda los archivos que crea.'},
    {sel:'#convs',title:'Tus conversaciones',text:'Se guardan solo en este equipo. Con ⋯ puedes archivarlas, exportarlas o borrarlas; con muchas, aparece un buscador.'},
    {sel:'#sidebarMarket',title:'Extensiones',text:'Instala plugins y servidores MCP para darle nuevas habilidades al agente.'},
    {sel:'#engineCard',title:'Rendimiento',text:'Velocidad de generación y de lectura, memoria de la GPU y del sistema mientras el modelo trabaja.'},
    {sel:'#projectBtn',title:'Proyectos',text:'Trabaja sobre una carpeta tuya en lugar de la carpeta aislada del chat.'},
    {sel:'#agentModeSegments',title:'Modo del agente',text:'Ligero, Estándar o Completo: cuánta autonomía y cuántas herramientas puede usar el agente.'},
    {sel:'#input',title:'Escribe aquí',text:'Pide lo que necesites. Enter envía y Mayús+Enter añade una línea. Puedes pegar o arrastrar archivos e imágenes.'},
    {sel:'#attach',title:'Añadir',text:'Adjunta archivos de texto, código o imágenes (si el modelo admite visión).'},
    {sel:'#modelBtn',title:'Modelo',text:'Elige o importa un modelo GGUF, cárgalo, cambia el motor (llama.cpp, Strata, Strata Rust) o conecta una API compatible con OpenAI o Claude.'},
    {sel:'#responseBtn',title:'Pensamiento',text:'Cuánto razona el modelo antes de responder. Más pensamiento es más preciso pero más lento.'},
    {sel:'#scopeBtn',title:'Acceso y permisos',text:'Decide si el agente trabaja en su carpeta aislada o en todo tu equipo, y cuándo debe pedirte permiso.'},
    {sel:'#mcpBtn',title:'Herramientas',text:'Activa lo que el agente puede usar: internet, archivos, comandos, navegador, información del equipo y más.'},
    {sel:'#ctxBtn',title:'Contexto',text:'Cuánta memoria de la conversación usa el modelo. Al llenarse, conviene empezar un chat nuevo.'},
    {sel:'#send',title:'Enviar',text:'Envía el mensaje. Mientras el modelo responde, este botón lo detiene.'},
    {sel:'#openConsole',title:'Consola',text:'Una terminal compartida con el agente cuando le das acceso a todo el equipo.'},
    {sel:'#openBrowser',title:'Navegador',text:'Un navegador integrado que tú y el agente pueden usar.'},
    {sel:'#gear',title:'Configuración',text:'Idioma, apariencia, herramientas, motores y actualizaciones. Desde General puedes repetir este recorrido.'},
    {title:'¡Listo!',text:'Ya conoces V-Agent. Carga un modelo y escribe tu primera petición.'}
  ];
  let index=0,layer=null,ring=null,card=null,steps=STEPS,resizeHandler=null;

  async function state(){try{return await requestJSON('/api/harness/state');}catch{return null;}}
  function hasEngine(snapshot){const found=snapshot?.installed_engines||{};return Object.values(found).some(Boolean)||(snapshot?.connections||[]).length>0;}

  function close(done=true){
    layer?.remove();layer=ring=card=null;removeEventListener('keydown',keys,true);if(resizeHandler)removeEventListener('resize',resizeHandler);
    if(done)requestJSON('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tour_done:true})}).catch(()=>{});
  }
  function keys(event){
    if(!layer)return;
    if(event.key==='Escape'){event.preventDefault();close();}
    else if(event.key==='ArrowRight'||event.key==='Enter'&&event.target===card.querySelector('.tour-next')){event.preventDefault();go(1);}
    else if(event.key==='ArrowLeft'){event.preventDefault();go(-1);}
  }
  function go(delta){const next=index+delta;if(next<0)return;if(next>=steps.length){close();return;}index=next;render();}

  function place(target){
    const pad=6,vw=innerWidth,vh=innerHeight;
    if(!target){ring.hidden=true;card.style.left=Math.max(16,(vw-card.offsetWidth)/2)+'px';card.style.top=Math.max(16,(vh-card.offsetHeight)/2)+'px';return;}
    const r=target.getBoundingClientRect();ring.hidden=false;
    Object.assign(ring.style,{left:r.left-pad+'px',top:r.top-pad+'px',width:r.width+pad*2+'px',height:r.height+pad*2+'px'});
    const below=vh-r.bottom,cw=card.offsetWidth,ch=card.offsetHeight;
    let top=below>ch+24?r.bottom+14:r.top-ch-14;top=Math.min(vh-ch-12,Math.max(12,top));
    let left=r.left+r.width/2-cw/2;left=Math.min(vw-cw-12,Math.max(12,left));
    card.style.left=left+'px';card.style.top=top+'px';
  }
  function render(){
    const step=steps[index],body=card.querySelector('.tour-body');
    card.querySelector('.tour-count').textContent=(index+1)+' / '+steps.length;
    card.querySelector('.tour-back').disabled=index===0;
    card.querySelector('.tour-next').textContent=uiText(index===steps.length-1?'Terminar':'Siguiente');
    body.replaceChildren();
    if(step.engine){renderEngine(body);place(null);return;}
    const h=document.createElement('h3');h.textContent=uiText(step.title);const p=document.createElement('p');p.textContent=uiText(step.text);body.append(h,p);
    const target=step.sel?document.querySelector(step.sel):null;
    const visible=target&&target.getClientRects().length&&getComputedStyle(target).visibility!=='hidden';
    if(visible)target.scrollIntoView({block:'nearest',inline:'nearest'});
    requestAnimationFrame(()=>place(visible?target:null));
    card.querySelector('.tour-next').focus({preventScroll:true});
  }

  // Engine step: recommend the official build for this hardware and install it on request.
  async function renderEngine(body){
    const h=document.createElement('h3');h.textContent=uiText('Tu motor de IA');
    const p=document.createElement('p');p.textContent=uiText('Comprobando tu equipo…');
    const status=document.createElement('p');status.className='tour-status';status.setAttribute('role','status');
    const actions=document.createElement('div');actions.className='tour-engine-actions';
    body.append(h,p,status,actions);
    const snapshot=await state();
    if(hasEngine(snapshot)){p.textContent=uiText('Ya tienes un motor instalado. Puedes cambiarlo cuando quieras desde Modelo → Cambiar motor.');return;}
    let hardware={};try{hardware=await requestJSON('/api/harness/hardware');}catch{}
    const variant=snapshot?.recommended_variant||'cpu',key='llama-'+variant;
    const label={cuda:'llama.cpp · CUDA (NVIDIA)',vulkan:'llama.cpp · Vulkan (AMD, Intel Arc, NVIDIA)',cpu:'llama.cpp · CPU'}[variant];
    p.textContent=uiText('V-Agent no incluye motores: descarga la versión oficial más reciente que mejor encaja con tu equipo.')+' '+(hardware.hardware_summary||hardware.summary||'');
    const install=document.createElement('button');install.type='button';install.className='soft-btn primary';install.textContent=uiText('Descargar e instalar')+' · '+label;
    const api=document.createElement('button');api.type='button';api.className='soft-btn';api.textContent=uiText('Prefiero conectar una API');
    api.onclick=()=>{close(false);document.querySelector('#modelBtn')?.click();setTimeout(()=>document.querySelector('#modelSourceTabs [data-source=api]')?.click(),400);};
    actions.append(install,api);
    install.onclick=async()=>{
      install.disabled=api.disabled=true;
      try{
        status.textContent=uiText('Buscando la versión oficial…');
        await requestJSON('/api/harness/updates/check',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        let release=null;
        for(let i=0;i<60&&!release;i++){await new Promise(r=>setTimeout(r,1000));const u=await requestJSON('/api/harness/updates');const item=u.releases?.[key];if(item?.asset)release=item;else if(item?.error||item?.message)throw new Error(item.error||item.message);}
        if(!release)throw new Error(uiText('No se pudo consultar GitHub. Revisa tu conexión.'));
        await requestJSON('/api/harness/updates/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine:key})});
        for(;;){
          await new Promise(r=>setTimeout(r,800));const u=await requestJSON('/api/harness/updates');const g=u.progress;
          if(g&&g.engine===key&&g.total)status.textContent=uiText({download:'Descargando',extract:'Extrayendo',verify:'Verificando'}[g.phase]||'Procesando')+' · '+Math.round(g.received/g.total*100)+' % · '+(g.total/1048576).toFixed(0)+' MB';
          if(u.error)throw new Error(u.error);
          if(!u.busy&&u.installed?.[key])break;
        }
        await requestJSON('/api/harness/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine:'llama',variant,gpu_layers:'auto'})});
        status.textContent=uiText('Motor instalado y verificado. Ahora añade o carga un modelo desde Modelo.');
      }catch(error){status.textContent=uiText('No se pudo instalar')+': '+error.message;install.disabled=api.disabled=false;}
    };
  }

  function start(){
    if(layer)return;index=0;steps=STEPS;
    layer=document.createElement('div');layer.className='tour-layer';layer.setAttribute('role','dialog');layer.setAttribute('aria-modal','true');layer.setAttribute('aria-label',uiText('Tutorial de V-Agent'));
    ring=document.createElement('div');ring.className='tour-ring';
    card=document.createElement('div');card.className='tour-card';
    card.innerHTML='<div class="tour-body"></div><div class="tour-foot"><span class="tour-count"></span><button type="button" class="soft-btn tour-skip"></button><button type="button" class="soft-btn tour-back"></button><button type="button" class="soft-btn primary tour-next"></button></div>';
    card.querySelector('.tour-skip').textContent=uiText('Saltar');card.querySelector('.tour-back').textContent=uiText('Atrás');
    card.querySelector('.tour-skip').onclick=()=>close();card.querySelector('.tour-back').onclick=()=>go(-1);card.querySelector('.tour-next').onclick=()=>go(1);
    layer.append(ring,card);document.body.append(layer);
    addEventListener('keydown',keys,true);resizeHandler=()=>render();addEventListener('resize',resizeHandler);
    render();
  }

  // V-Agent updates (signed, from the maintainer's GitHub releases) in Settings → General.
  function setupUpdates(){
    const general=document.getElementById('settings-general');if(!general||document.getElementById('appUpdateBox'))return;
    const box=document.createElement('section');box.id='appUpdateBox';box.className='app-update';
    box.innerHTML='<h4></h4><p class="mini" id="appUpdateStatus" role="status"></p><div class="app-update-actions"><button type="button" class="soft-btn" id="appUpdateCheck"></button><button type="button" class="soft-btn primary" id="appUpdateGo" hidden></button><button type="button" class="soft-btn" id="tourAgain"></button></div><p class="mini" id="componentStatus" role="status" hidden></p><div class="app-update-actions" id="componentActions" hidden><button type="button" class="soft-btn primary" id="componentApply" hidden></button><button type="button" class="soft-btn" id="componentReset" hidden></button></div>';
    box.querySelector('h4').textContent=uiText('Actualizaciones de V-Agent');
    box.querySelector('#appUpdateCheck').textContent=uiText('Buscar actualizaciones');
    box.querySelector('#tourAgain').textContent=uiText('Ver el tutorial');
    general.append(box);
    const status=box.querySelector('#appUpdateStatus'),go=box.querySelector('#appUpdateGo');
    // Minor updates never change the version number: they show as "1.0.0 C1", "1.0.0 C2"…
    let componentRevision=0,lastApp=null;
    const label=version=>version+(componentRevision?' C'+componentRevision:'');
    const paint=s=>{
      if(!s)return;lastApp=s;
      if(!s.configured){status.textContent=uiText('Versión')+' '+label(s.version)+' · '+uiText('Las actualizaciones automáticas se activarán cuando se publique el repositorio oficial.');go.hidden=true;return;}
      if(s.error){status.textContent=uiText('No se pudo comprobar')+': '+s.error;}
      else if(s.ready){status.textContent=uiText('Actualización descargada y verificada.');go.textContent=uiText('Instalar y reiniciar');go.hidden=false;go.dataset.action='launch';}
      else if(s.busy&&s.progress){status.textContent=uiText('Descargando')+' · '+Math.round(s.progress.received/s.progress.total*100)+' %';}
      else if(s.available){status.textContent=uiText('Nueva versión disponible')+': '+s.available.version+(s.available.notes?' · '+s.available.notes.slice(0,140):'');go.textContent=uiText('Descargar')+' '+s.available.version;go.hidden=false;go.dataset.action='download';}
      else status.textContent=uiText('Versión')+' '+label(s.version)+(s.checked_at?' · '+uiText('Estás al día.'):'');
    };
    const post=action=>requestJSON('/api/harness/app-update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    // Minor updates channel (MCP servers, tools): signed components for this exact version.
    const cStatus=box.querySelector('#componentStatus'),cActions=box.querySelector('#componentActions'),cApply=box.querySelector('#componentApply'),cReset=box.querySelector('#componentReset');
    cApply.textContent=uiText('Aplicar mejoras');cReset.textContent=uiText('Volver a los originales');
    const cPost=action=>requestJSON('/api/harness/components',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const paintComponents=c=>{
      if(!c||!c.configured){cStatus.hidden=cActions.hidden=true;return;}
      cStatus.hidden=cActions.hidden=false;
      const version=lastApp?.version||'';
      if(componentRevision!==(c.revision||0)){componentRevision=c.revision||0;if(lastApp)paint(lastApp);}
      let text=uiText('Actualizaciones menores')+': '+(c.revision?version+' C'+c.revision:uiText('ninguna instalada'));
      if(c.restart_needed)text+=' · '+uiText('Se aplicarán al reiniciar V-Agent.');
      else if(c.available)text+=' · '+uiText('Disponible')+': '+version+' C'+c.available.revision+(c.available.notes?' — '+c.available.notes.slice(0,140):'');
      if(c.error)text+=' · '+c.error;
      cStatus.textContent=text;cApply.hidden=!c.available||c.restart_needed;cReset.hidden=!c.revision;
    };
    cApply.onclick=async()=>{cApply.disabled=true;try{paintComponents(await cPost('apply'));}catch(e){cStatus.textContent=e.message;}finally{cApply.disabled=false;}};
    cReset.onclick=async()=>{if(!await valConfirm({title:'¿Volver a los componentes originales?',message:'Se quitarán las mejoras menores instaladas. Se aplicará al reiniciar V-Agent.',confirm:'Volver a los originales'}))return;try{paintComponents(await cPost('reset'));}catch(e){cStatus.textContent=e.message;}};
    box.querySelector('#appUpdateCheck').onclick=async()=>{status.textContent=uiText('Comprobando…');try{paint(await post('check'));paintComponents(await cPost('check'));}catch(e){status.textContent=e.message;}};
    go.onclick=async()=>{
      try{
        if(go.dataset.action==='launch'){const r=await post('launch');if(r.launched){status.textContent=uiText('Abriendo el instalador…');setTimeout(()=>window.__TAURI__?.window?.getCurrentWindow?.().close(),1200);}return;}
        paint(await post('download'));
        const timer=setInterval(async()=>{const s=await requestJSON('/api/harness/app-update');paint(s);if(!s.busy)clearInterval(timer);},800);
      }catch(e){status.textContent=e.message;}
    };
    box.querySelector('#tourAgain').onclick=()=>{window.setDrawer?.(false);document.querySelector('#gear')?.getAttribute('aria-expanded')==='true'&&document.querySelector('#gear').click();setTimeout(start,350);};
    requestJSON('/api/harness/app-update').then(paint).catch(()=>{});
    document.addEventListener('v-agent-app-update',event=>paint(event.detail));
    requestJSON('/api/harness/components').then(paintComponents).catch(()=>{});
  }

  async function boot(){
    // Settings → General is built later during start-up; attach the updates box once it exists.
    let tries=0;const wait=setInterval(()=>{if(document.getElementById('settings-general')||++tries>60){clearInterval(wait);setupUpdates();}},250);
    let prefs={};try{prefs=await requestJSON('/api/harness/preferences');}catch{}
    if(!prefs.tour_done)setTimeout(start,900);
  }
  return {start,boot,steps:STEPS};
})();
VAL_TOUR.boot();
