/* Local console and integrated browser with its agent bridge. */
(()=>{
  const tauri=(command,args)=>{const api=window.__TAURI__&&window.__TAURI__.core;return api&&api.invoke?api.invoke(command,args):Promise.reject(new Error('La aplicación de escritorio no está disponible.'));};
  const hasTauri=()=>!!(window.__TAURI__&&window.__TAURI__.core&&window.__TAURI__.core.invoke);
  window.__VAL_BRIDGE={polls:0,took:0,last:'',error:'',tauri:hasTauri()};
  const nextFrame=()=>new Promise(resolve=>requestAnimationFrame(()=>resolve()));

  const consoleWindow=document.getElementById('consoleWindow');
  const openConsole=document.getElementById('openConsole');
  if(openConsole)openConsole.onclick=()=>window.VALWindows?.open('console');
  if(consoleWindow){
    const output=document.getElementById('consoleOutput');
    const history=[];let historyIndex=0;
    let polling=0,running=false,lastKey='';
    const state=text=>{document.getElementById('consoleState').textContent=text;};
    function paint(snapshot){
      if(!snapshot)return;
      const key=(snapshot.id||'')+'|'+(snapshot.session||'')+'|'+snapshot.offset+'|'+(snapshot.text||'').length+'|'+snapshot.running+'|'+snapshot.exit_code;
      if(key===lastKey)return;lastKey=key;
      const nearBottom=output.scrollHeight-output.scrollTop-output.clientHeight<40;
      output.textContent=snapshot.text||'';
      if(nearBottom||snapshot.running)output.scrollTop=output.scrollHeight;
      running=!!snapshot.running;
      state(running?'Ejecutando':'Inactiva');
      document.getElementById('consoleStop').disabled=!running;
      document.getElementById('consoleRun').disabled=running;
      const bits=[];
      if(snapshot.shell)bits.push(snapshot.shell==='cmd'?'CMD':'PowerShell');
      if(snapshot.cwd)bits.push(snapshot.cwd);
      bits.push(running?'Ejecutando':snapshot.id?('Finalizado'+(snapshot.exit_code!==null&&snapshot.exit_code!==undefined?' · código '+snapshot.exit_code:'')):'Sin ejecuciones en esta sesión');
      if(snapshot.offset)bits.push(snapshot.offset+' caracteres anteriores omitidos');
      document.getElementById('consoleMeta').textContent=bits.join(' · ');
    }
    async function poll(){
      clearTimeout(polling);
      try{const response=await fetch('/api/harness/console',{cache:'no-store'});if(response.ok)paint(await response.json());}catch{}
      if(!consoleWindow.hidden)polling=setTimeout(poll,running?600:1500);
    }
    async function run(){
      const command=document.getElementById('consoleCommand').value;
      if(!command.trim()||running)return;
      if(pcAccess.mode!=='full_pc'){document.getElementById('consoleHint').textContent='Activa Acceso completo en la ventana de Herramientas antes de ejecutar comandos.';return;}
      if(history[history.length-1]!==command)history.push(command);
      historyIndex=history.length;
      document.getElementById('consoleRun').disabled=true;state('Iniciando');
      try{
        const response=await fetch('/api/harness/console',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'run',command,shell:document.getElementById('consoleShell').value,conversation_id:currentId||undefined})});
        const data=await response.json();
        if(!response.ok)throw new Error(data.error||'No se pudo ejecutar el comando.');
        lastKey='';paint(data);
        if(!consoleWindow.hidden){clearTimeout(polling);polling=setTimeout(poll,400);}
      }catch(error){document.getElementById('consoleHint').textContent=error.message;document.getElementById('consoleRun').disabled=false;state('Error');}
    }
    async function stop(){
      document.getElementById('consoleStop').disabled=true;
      try{const response=await fetch('/api/harness/console',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop'})});if(response.ok)paint(await response.json());}catch{}
      clearTimeout(polling);polling=setTimeout(poll,300);
    }
    document.getElementById('consoleRun').onclick=run;
    document.getElementById('consoleStop').onclick=stop;
    const commandInput=document.getElementById('consoleCommand');
    commandInput.addEventListener('keydown',event=>{
      if(event.key==='Enter'){event.preventDefault();run();return;}
      if(event.key==='ArrowUp'&&history.length){event.preventDefault();historyIndex=Math.max(0,historyIndex-1);commandInput.value=history[historyIndex]||'';return;}
      if(event.key==='ArrowDown'&&history.length){event.preventDefault();historyIndex=Math.min(history.length,historyIndex+1);commandInput.value=history[historyIndex]||'';}
    });
    document.getElementById('consoleCopy').onclick=async()=>{try{await navigator.clipboard.writeText(output.textContent);note('Salida copiada.');}catch{note('No se pudo copiar la salida.');}};
    document.getElementById('consoleClear').onclick=async()=>{
      try{
        const response=await fetch('/api/harness/console',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'clear'})});
        const data=await response.json();
        if(!response.ok)throw new Error(data.error||'No se pudo limpiar.');
        lastKey='';paint(data);
      }catch(error){document.getElementById('consoleHint').textContent=error.message;}
    };
    consoleWindow.addEventListener('fw:open',()=>{poll();commandInput.focus({preventScroll:true});});
    consoleWindow.addEventListener('fw:close',()=>clearTimeout(polling));
    poll();
  }

  const dock=document.getElementById('browserDock');
  if(dock){
    const page=document.getElementById('browserPage');
    const start=document.getElementById('browserStart');
    const listView=document.getElementById('browserListView');
    const tabsBar=document.getElementById('browserTabs');
    const urlInput=document.getElementById('browserUrl');
    const status=document.getElementById('browserStatus');
    const stateLabel=document.getElementById('browserState');
    const recent=document.getElementById('browserRecentList');
    const agentUse=document.getElementById('browserAgentUse');
    const HISTORY_KEY='valBrowserHistoryV1',BOOKMARKS_KEY='valBrowserBookmarksV1',COUNTER_KEY='valBrowserCounterV1',WIDTH_KEY='valBrowserWidthV1';
    const tabs=[];let activeId=null,nextId=1,listMode='',open=false,boundsTimer=0,pollTimer=0,refreshing=false,bridgeActive=false;
    function read(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}}
    function write(key,value){try{localStorage.setItem(key,JSON.stringify(value))}catch{}}
    let history=read(HISTORY_KEY,[]);let bookmarks=read(BOOKMARKS_KEY,[]);
    nextId=Math.max(1,Number(localStorage.getItem(COUNTER_KEY)||1)||1);
    const active=()=>tabs.find(tab=>tab.id===activeId)||null;
    const setState=text=>{stateLabel.textContent=text;};
    const setStatus=text=>{status.textContent=text;};
    function normalUrl(value){
      let text=String(value||'').trim();if(!text)return '';
      if(!/^[a-z][a-z0-9+.-]*:\/\//i.test(text)){
        if(/^(localhost|127\.|\[::1\])(?::\d+)?(?:\/|$)/i.test(text))text='http://'+text;
        else if(!text.includes('.')||/\s/.test(text))return 'https://duckduckgo.com/?q='+encodeURIComponent(text);
        else text='https://'+text;
      }
      try{const url=new URL(text);return ['http:','https:'].includes(url.protocol)?url.href:'';}catch{return '';}
    }
    function hostOf(url){try{return new URL(url).hostname.replace(/^www\./,'')||url}catch{return 'Nueva pestaña'}}
    function maxWidth(){
      if(innerWidth<=760)return innerWidth-2;
      const sidebar=document.getElementById('sidebar');
      const sidebarWidth=sidebar?Math.round(sidebar.getBoundingClientRect().width)||246:246;
      return Math.max(360,innerWidth-sidebarWidth-CHAT_MIN-12);
    }
    // Below this the composer's controls fall apart into a column (seen at 800 px: the chat was 194 px).
    const CHAT_MIN=520;
    function sidebarSpace(){const sidebar=document.getElementById('sidebar');return sidebar&&sidebar.offsetParent?Math.round(sidebar.getBoundingClientRect().width):0;}
    function currentWidth(){return Math.min(maxWidth(),Math.max(360,Number(localStorage.getItem(WIDTH_KEY)||520)||520));}
    function applyWidth(){
      const width=currentWidth();
      // Not enough room for a usable chat beside the browser: the browser floats over the chat
      // instead of squeezing it (the chat keeps its full width underneath).
      document.body.classList.toggle('browser-overlay',innerWidth>760&&innerWidth-sidebarSpace()-width<CHAT_MIN);
      document.documentElement.style.setProperty('--browser-width',width+'px');
      dock.style.width=width+'px';
    }
    async function syncBounds(){
      const tab=active();
      if(!open||!tab||!tab.view||!hasTauri())return;
      const rect=page.getBoundingClientRect();
      if(rect.width<40||rect.height<40)return;
      try{await tauri('browser_tab_bounds',{label:tab.label,x:rect.left,y:rect.top,w:rect.width,h:rect.height});}catch{}
    }
    function syncSoon(){clearTimeout(boundsTimer);boundsTimer=setTimeout(syncBounds,70);}
    function renderTabs(){
      tabsBar.replaceChildren();
      for(const tab of tabs){
        const item=document.createElement('div');item.className='browser-tab';item.dataset.tab=tab.id;item.setAttribute('role','tab');item.tabIndex=tab.id===activeId?0:-1;item.setAttribute('aria-selected',String(tab.id===activeId));
        const title=document.createElement('span');title.className='browser-tab-title';title.textContent=tab.title||hostOf(tab.url)||'Nueva pestaña';
        const close=document.createElement('button');close.type='button';close.className='browser-tab-close';close.setAttribute('aria-label','Cerrar pestaña');close.textContent='×';
        close.onclick=event=>{event.stopPropagation();closeTab(tab.id);};
        item.onclick=()=>activateTab(tab.id);
        item.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();activateTab(tab.id);}};
        item.append(title,close);tabsBar.append(item);
      }
    }
    function renderInput(){
      const tab=active();
      if(tab&&tab.url&&document.activeElement!==urlInput)urlInput.value=tab.url;
      if(!tab||!tab.url)urlInput.value='';
      renderBookmark();
    }
    function renderBookmark(){
      const tab=active();const bookmarked=!!tab&&!!tab.url&&bookmarks.some(item=>item.url===tab.url);
      const button=document.getElementById('browserBookmark');
      button.textContent=bookmarked?'★':'☆';
      button.title=bookmarked?'Quitar marcador':'Guardar marcador';
      button.disabled=!tab||!tab.url;
    }
    function renderRecent(){
      recent.replaceChildren();
      const items=history.slice(0,4);
      if(!items.length){const empty=document.createElement('span');empty.className='browser-list-empty';empty.textContent='Aún no hay páginas visitadas.';recent.append(empty);return;}
      for(const entry of items){
        const button=document.createElement('button');button.type='button';button.className='browser-recent-item';
        const title=document.createElement('span');title.textContent=entry.title||hostOf(entry.url);
        const small=document.createElement('small');small.textContent=entry.url;
        button.append(title,small);button.onclick=()=>navigateTab(active(),entry.url);recent.append(button);
      }
    }
    function renderListItems(){
      const items=document.getElementById('browserListItems');items.replaceChildren();
      if(listMode==='downloads'){
        const note=document.createElement('p');note.className='browser-list-empty';note.textContent='Las descargas del navegador integrado se gestionan en Windows. Los archivos se guardan en tu carpeta de descargas.';
        items.append(note);return;
      }
      const source=listMode==='bookmarks'?bookmarks:history;
      if(!source.length){const note=document.createElement('p');note.className='browser-list-empty';note.textContent=listMode==='bookmarks'?'No hay marcadores guardados.':'No hay páginas en el historial.';items.append(note);return;}
      for(const entry of source){
        const button=document.createElement('button');button.type='button';button.className='browser-list-item';
        const title=document.createElement('span');title.textContent=entry.title||hostOf(entry.url);
        const small=document.createElement('small');small.textContent=entry.url;
        button.append(title,small);button.onclick=()=>{hideList();navigateTab(active(),entry.url);};items.append(button);
      }
    }
    function showStart(){
      start.hidden=false;listView.hidden=true;listMode='';
      renderRecent();
    }
    function showList(kind){
      listMode=kind;start.hidden=true;listView.hidden=false;
      document.getElementById('browserListTitle').textContent=kind==='bookmarks'?'Marcadores':kind==='history'?'Historial':'Descargas';
      renderListItems();
      const tab=active();if(tab&&tab.view)tauri('browser_tab_hide',{label:tab.label}).catch(()=>{});
    }
    function hideList(){
      listView.hidden=true;listMode='';
      const tab=active();
      if(tab&&tab.view){start.hidden=true;tauri('browser_tab_show',{label:tab.label}).then(syncBounds).catch(()=>{});}
      else showStart();
    }
    function newTab(url=''){
      const tab={id:'tab'+nextId,label:'browser'+nextId,url:'',title:'Nueva pestaña',view:false};
      nextId+=1;localStorage.setItem(COUNTER_KEY,String(nextId));tabs.push(tab);activeId=tab.id;
      renderTabs();renderInput();
      if(url)navigateTab(tab,url);else{activateTab(tab.id);showStart();}
      return tab;
    }
    function activateTab(id){
      const tab=tabs.find(item=>item.id===id);if(!tab)return;
      activeId=id;listMode='';
      for(const other of tabs){if(other.view&&other.label!==tab.label)tauri('browser_tab_hide',{label:other.label}).catch(()=>{});}
      renderTabs();renderInput();
      if(tab.view){
        start.hidden=true;listView.hidden=true;
        tauri('browser_tab_show',{label:tab.label}).then(syncBounds).catch(()=>{tab.view=false;showStart();});
        setState('Abierta');
      }else{
        showStart();setState('Abierta');
      }
    }
    function closeTab(id){
      const tab=tabs.find(item=>item.id===id);if(!tab)return;
      if(tab.view)tauri('browser_tab_close',{label:tab.label}).catch(()=>{});
      const index=tabs.indexOf(tab);tabs.splice(index,1);
      if(activeId===id){
        const next=tabs[index]||tabs[index-1]||null;
        if(next){activeId=next.id;activateTab(next.id);}
        else{activeId=null;newTab();}
      }
      renderTabs();renderInput();
      window.VALWindows?.arrange();
    }
    async function waitReady(tab){
      for(let i=0;i<40;i++){
        try{
          const value=await tauri('browser_tab_dom',{label:tab.label,action:'eval',script:'location.href + "|" + document.readyState',selector:null,text:null,key:null,max_chars:null});
          if(value&&value.ok&&String(value.value).endsWith('|complete')&&!String(value.value).startsWith('about:blank'))return true;
        }catch{return false;}
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      return false;
    }
    async function refreshTab(tab){
      if(!tab||!tab.view||refreshing)return;
      refreshing=true;
      try{
        const value=await tauri('browser_tab_dom',{label:tab.label,action:'eval',script:'({title:document.title,url:location.href})',selector:null,text:null,key:null,max_chars:null});
        if(value&&value.ok&&value.value){
          const url=String(value.value.url||tab.url);const title=String(value.value.title||hostOf(url));
          tab.url=url;tab.title=title;
          if(tab.id===activeId)renderInput();
          renderTabs();record(url,title);
        }
      }catch{}finally{refreshing=false;}
    }
    function record(url,title){
      if(!url||!/^https?:/i.test(url))return;
      history=[{url,title:title||hostOf(url),ts:Date.now()},...history.filter(entry=>entry.url!==url)].slice(0,60);
      write(HISTORY_KEY,history);
      renderRecent();
    }
    function toggleBookmark(){
      const tab=active();if(!tab||!tab.url)return;
      const exists=bookmarks.some(item=>item.url===tab.url);
      bookmarks=exists?bookmarks.filter(item=>item.url!==tab.url):[{url:tab.url,title:tab.title||hostOf(tab.url)},...bookmarks].slice(0,80);
      write(BOOKMARKS_KEY,bookmarks);renderBookmark();
    }
    async function navigateTab(tab,value){
      const url=normalUrl(value);
      if(!url){setStatus('Escribe una dirección http o https válida.');return false;}
      if(!open)openDock();
      tab=tab||active()||newTab();
      activeId=tab.id;listMode='';tab.url=url;tab.title=hostOf(url);
      renderTabs();renderInput();start.hidden=true;listView.hidden=true;setStatus('Cargando '+hostOf(url)+'…');
      const rect=page.getBoundingClientRect();
      try{
        if(tab.view)await tauri('browser_tab_navigate',{label:tab.label,url});
        else{await tauri('browser_tab_open',{label:tab.label,url,x:rect.left,y:rect.top,w:rect.width,h:rect.height});tab.view=true;}
        await waitReady(tab);await refreshTab(tab);record(tab.url,tab.title);setStatus('');setState('Abierta');syncBounds();
        return true;
      }catch(error){
        tab.view=false;setStatus(String(error&&error.message||error));showStart();setState('Abierta');
        return false;
      }
    }
    function navigateActive(value){const tab=active()||newTab();navigateTab(tab,value);}
    async function historyAction(kind){
      const tab=active();if(!tab||!tab.view)return;
      try{await tauri('browser_tab_'+kind,{label:tab.label});await new Promise(resolve=>setTimeout(resolve,350));await waitReady(tab);await refreshTab(tab);syncBounds();}catch(error){setStatus(String(error&&error.message||error));}
    }
    function openDock(){
      if(open)return;
      open=true;dock.hidden=false;document.body.classList.add('browser-open');applyWidth();setState('Abierta');
      if(!tabs.length)newTab();else activateTab(activeId||tabs[0].id);
      setTimeout(()=>{syncBounds();window.VALWindows?.arrange();},30);
      clearInterval(pollTimer);pollTimer=setInterval(()=>{const tab=active();if(tab&&tab.view&&listView.hidden&&!bridgeActive)refreshTab(tab);},1400);
    }
    function closeDock(){
      if(!open)return;
      open=false;dock.hidden=true;document.body.classList.remove('browser-open');setState('Cerrado');
      const tab=active();if(tab&&tab.view)tauri('browser_tab_hide',{label:tab.label}).catch(()=>{});
      clearInterval(pollTimer);pollTimer=0;
      window.VALWindows?.arrange();
    }
    function toggleDock(){open?closeDock():openDock();}
    window.VALBrowser={open:url=>{openDock();navigateActive(url);},navigate:navigateActive,toggle:toggleDock,close:closeDock};
    document.addEventListener('click',event=>{
      if(!hasTauri())return;
      const link=event.target.closest('a[href]');if(!link||link.hasAttribute('download'))return;
      const href=link.getAttribute('href')||'';if(!/^https?:\/\//i.test(href))return;
      event.preventDefault();window.VALBrowser.open(href);
    });
    document.getElementById('openBrowser').onclick=toggleDock;
    document.getElementById('browserDockClose').onclick=closeDock;
    document.getElementById('browserNewTab').onclick=()=>{if(!open)openDock();newTab();};
    document.getElementById('browserGo').onclick=()=>navigateActive(urlInput.value);
    document.getElementById('browserBack').onclick=()=>historyAction('back');
    document.getElementById('browserForward').onclick=()=>historyAction('forward');
    document.getElementById('browserReload').onclick=()=>historyAction('reload');
    document.getElementById('browserBookmark').onclick=toggleBookmark;
    document.getElementById('browserBookmarksCard').onclick=()=>showList('bookmarks');
    document.getElementById('browserHistoryCard').onclick=()=>showList('history');
    document.getElementById('browserDownloadsCard').onclick=()=>showList('downloads');
    document.getElementById('browserListClose').onclick=hideList;
    urlInput.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();navigateActive(urlInput.value);}});
    agentUse.checked=typeof S!=='undefined'&&!!S.functions?.browser;
    agentUse.onchange=()=>{
      S.functions.browser=agentUse.checked;
      const checkbox=document.getElementById('f_browser');if(checkbox)checkbox.checked=agentUse.checked;
      syncServerSwitches();saveSettings();
      setStatus(agentUse.checked?'El agente puede usar este navegador.':'El agente no puede usar este navegador.');
    };
    document.getElementById('f_browser')?.addEventListener('change',()=>{agentUse.checked=!!S.functions.browser;});
    const resize=document.getElementById('browserDockResize');
    resize.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;event.preventDefault();
      const startX=event.clientX,startWidth=currentWidth();document.body.classList.add('browser-resizing');
      resize.setPointerCapture(event.pointerId);
      const move=moveEvent=>{const width=Math.min(maxWidth(),Math.max(360,startWidth+(startX-moveEvent.clientX)));localStorage.setItem(WIDTH_KEY,String(Math.round(width)));applyWidth();syncSoon();};
      const finish=()=>{resize.removeEventListener('pointermove',move);resize.removeEventListener('pointerup',finish);resize.removeEventListener('pointercancel',finish);document.body.classList.remove('browser-resizing');try{resize.releasePointerCapture(event.pointerId);}catch{}window.VALWindows?.arrange();syncSoon();};
      resize.addEventListener('pointermove',move);resize.addEventListener('pointerup',finish);resize.addEventListener('pointercancel',finish);
    });
    const observer=new ResizeObserver(()=>syncSoon());observer.observe(page);
    window.addEventListener('resize',()=>{applyWidth();syncSoon();window.VALWindows?.arrange();});
    applyWidth();renderTabs();renderRecent();renderInput();
    if(typeof S!=='undefined'&&S.functions)agentUse.checked=!!S.functions.browser;

    window.__VAL_BRIDGE.tauri=hasTauri();
    async function bridgeCommand(item){
      let result=null,error=null;const action=item.action,args=item.args||{};
      bridgeActive=true;
      try{
        if(!S.functions.browser)throw new Error('El uso del navegador por el agente está desactivado.');
        if(!hasTauri())throw new Error('La ventana de escritorio no está disponible.');
        if(action==='open'||action==='navigate'){
          openDock();setState('Agente');
          const tab=active()||newTab();
          const ok=await navigateTab(tab,String(args.url||''));
          if(!ok)throw new Error(status.textContent||'No se pudo abrir la página.');
          result={open:true,url:tab.url};
          setState('Abierta');
        }else if(action==='close'){
          closeDock();result={open:false,url:''};
        }else{
          if(!open)openDock();
          const tab=active();
          if(!tab||!tab.view)throw new Error('No hay una página abierta en el navegador integrado.');
          setState('Agente');
          if(action==='snapshot'||action==='text'||action==='click'||action==='fill'||action==='press'||action==='eval'){
            const prevUrl=tab.url||'';
            result=await tauri('browser_tab_dom',{label:tab.label,action,selector:args.selector??null,text:args.text??null,key:args.key??null,script:args.script??null,max_chars:args.max_chars??null});
            if(action==='click'||(action==='press'&&(!args.key||args.key==='Enter'))){
              await new Promise(resolve=>setTimeout(resolve,350));await waitReady(tab);await refreshTab(tab);
              if(result&&typeof result==='object'&&tab.url&&tab.url!==prevUrl){
                result.navigated=true;result.url=tab.url;
                if(action==='press')result.submitted=true;
              }
            }
          }else if(action==='back'||action==='forward'||action==='reload'){
            await tauri('browser_tab_'+action,{label:tab.label});await new Promise(resolve=>setTimeout(resolve,350));await waitReady(tab);await refreshTab(tab);syncBounds();
            result={open:true,url:tab.url};
          }else throw new Error('Acción de navegador no admitida.');
          setState('Abierta');
        }
      }catch(caught){error=String(caught&&caught.message||caught);setState('Abierta');}finally{bridgeActive=false;}
      try{await fetch('/api/harness/browser/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:item.id,result,error})});}catch{}
      if(error)setStatus(error);
    }
    async function pollBridge(){
      window.__VAL_BRIDGE.polls++;window.__VAL_BRIDGE.tauri=hasTauri();
      try{
        const response=await fetch('/api/harness/browser/pending',{cache:'no-store'});
        if(response.ok){const data=await response.json();for(const item of data.items||[]){window.__VAL_BRIDGE.took++;window.__VAL_BRIDGE.last=item.action;await bridgeCommand(item);}}
      }catch(error){window.__VAL_BRIDGE.error=String(error&&error.message||error);}
      setTimeout(pollBridge,400);
    }
    if(hasTauri())setTimeout(pollBridge,800);
  }
})();
