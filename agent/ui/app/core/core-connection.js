(()=>{
  const base=window.__TAURI__?'http://127.0.0.1:19380':'';
  window.VAL_CORE_BASE=base;
  if(!base)return;
  const nativeFetch=window.fetch.bind(window);
  window.fetch=(input,init)=>{if(typeof input==='string'&&input.startsWith('/'))input=base+input;return nativeFetch(input,init);};
  const nativeBeacon=navigator.sendBeacon.bind(navigator);
  navigator.sendBeacon=(url,data)=>{if(typeof url==='string'&&url.startsWith('/'))url=base+url;return nativeBeacon(url,data);};
})();
async function waitForCore(){
  for(let attempt=0;attempt<120;attempt++){
    try{const response=await fetch('/api/harness/state',{cache:'no-store',signal:AbortSignal.timeout(2500)});if(response.ok)return true;}catch{}
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  return false;
}
// Interface fixes published through the signed minor-updates channel: a stylesheet and a script
// served by the core (empty when no update is applied), loaded on top of the bundled interface.
function loadUiPatch(force=false){
  const base=window.VAL_CORE_BASE||'',stamp=Date.now();
  let style=document.getElementById('uiPatchCss');
  if(!style){style=document.createElement('link');style.rel='stylesheet';style.id='uiPatchCss';document.head.append(style);}
  style.href=base+'/assets/ui-patch.css?t='+stamp;
  const existing=document.getElementById('uiPatchJs');
  if(existing&&!force)return;
  fetch('/assets/ui-patch.js?t='+stamp,{cache:'no-store'}).then(response=>response.ok?response.text():'').then(code=>{
    if(existing&&force)existing.remove();
    if(!code.trim()||(!force&&document.getElementById('uiPatchJs')))return;
    const script=document.createElement('script');script.id='uiPatchJs';script.src=base+'/assets/ui-patch.js?t='+stamp;document.body.append(script);
  }).catch(()=>{});
}
// V-Agent applies signed minor updates by itself shortly after starting (see desktop_runtime): when one
// lands while the window is open, its interface patch is loaded at once; a downloaded installer is announced.
async function watchAutomaticUpdates({requestJSON,uiText,note,setDrawer,selectSettingsCategory,showReleaseNotes}){
  const DISMISS_KEY='valDismissedAppUpdate';
  const readDismissed=()=>{try{return typeof localStorage!=='undefined'?(localStorage.getItem(DISMISS_KEY)||''):'';}catch{return '';}};
  const writeDismissed=v=>{try{if(typeof localStorage!=='undefined')localStorage.setItem(DISMISS_KEY,v);}catch{}};
  let start=null,dismissed=readDismissed(),delay=1500,lastApp=null,lastMinor=null,pollTimer=0,pollWake=null;
  const wakePoll=(nextDelay=600)=>{delay=nextDelay;if(pollWake){clearTimeout(pollTimer);const fn=pollWake;pollWake=null;fn();}};
  const compactNotes=(notes,limit=160)=>{
    const clean=String(notes||'').replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/^\s*(?:#{1,6}\s*|[-*+]\s+|\d+\.\s+)/gm,'').replace(/[`*_>~]+/g,'').replace(/\s+/g,' ').trim();
    return !clean?'':clean.length<=limit?clean:clean.slice(0,limit-1).trimEnd()+'…';
  };
  const notice=document.createElement('aside');notice.id='appUpdateNotice';notice.className='update-card';notice.hidden=true;notice.setAttribute('role','status');
  const title=document.createElement('strong'),detail=document.createElement('span'),open=document.createElement('button'),close=document.createElement('button'),notesEl=document.createElement('p'),notesBtn=document.createElement('button'),downloadBtn=document.createElement('button'),laterBtn=document.createElement('button');
  // What only the notice could show before had to be found in Settings: the progress, a failed download
  // and, once the installer is verified, the button that installs it.
  const progressBox=document.createElement('div'),progressBar=document.createElement('progress'),errorEl=document.createElement('p'),installBtn=document.createElement('button');
  progressBox.className='update-progress';progressBox.hidden=true;progressBar.max=100;progressBox.append(progressBar);
  errorEl.className='update-card-error';errorEl.hidden=true;
  installBtn.type='button';installBtn.className='update-install';installBtn.hidden=true;
  installBtn.onclick=()=>{installBtn.disabled=true;document.dispatchEvent(new CustomEvent('v-agent-app-install'));setTimeout(()=>{installBtn.disabled=false;},4000);};
  notesEl.className='update-card-notes';notesEl.hidden=true;
  notesBtn.type='button';notesBtn.className='update-notes-btn';notesBtn.hidden=true;
  downloadBtn.type='button';downloadBtn.className='update-install';downloadBtn.hidden=true;
  laterBtn.type='button';laterBtn.className='update-notes-btn';laterBtn.hidden=true;
  open.type='button';close.type='button';close.className='update-card-close';close.textContent='×';
  const openReleaseDialog=payload=>{
    if(typeof showReleaseNotes==='function')showReleaseNotes(payload);
    else if(typeof CustomEvent==='function')document.dispatchEvent(new CustomEvent('v-agent-show-notes',{detail:payload}));
  };
  const openSettings=()=>{setDrawer(true);selectSettingsCategory('general');document.getElementById('appUpdateBox')?.scrollIntoView({block:'nearest'});};
  const dismissNotice=()=>{dismissed=notice.dataset.version||'';writeDismissed(dismissed);notice.hidden=true;};
  open.onclick=openSettings;
  close.onclick=dismissNotice;
  laterBtn.onclick=dismissNotice;
  downloadBtn.onclick=async()=>{
    downloadBtn.disabled=true;
    try{
      const updated=await requestJSON('/api/harness/app-update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'download',language:typeof window!=='undefined'?(window.VALI18n?.language||'en'):'en'})});
      lastApp=updated;wakePoll(600);
      document.dispatchEvent(new CustomEvent('v-agent-app-update',{detail:updated}));
      renderNotice();
    }catch(error){note(uiText(error?.message||String(error)));downloadBtn.disabled=false;}
  };
  const renderNotice=()=>{
    close.setAttribute('aria-label',uiText('Descartar aviso'));
    open.textContent=uiText('Ver actualización');
    notesBtn.textContent=uiText('Notas de versión');
    laterBtn.textContent=uiText('Más tarde');
    installBtn.textContent=uiText('Instalar y reiniciar');
    const u=lastApp,version=u?.available?.version||'';
    // Settings is reachable from anywhere: the badge stays while an update waits, even after "Later".
    if(typeof markUpdateBadge==='function')markUpdateBadge('app',Boolean(version));
    notice.classList?.toggle('update-card-major',Boolean(version));
    if(version&&dismissed!==version){
      title.textContent=uiText('Nueva versión de V-Agent disponible');
      const downloading=Boolean(u.busy&&u.progress?.total&&!u.ready);
      const percent=downloading?Math.min(100,Math.round(u.progress.received/u.progress.total*100)):0;
      const mbText=downloading?' ('+(u.progress.received/1048576).toFixed(1)+' / '+(u.progress.total/1048576).toFixed(1)+' MB)':'';detail.textContent=(u.version?u.version+' → ':'')+version+(u.ready?' · '+uiText('Actualización descargada y verificada.'):downloading?' · '+uiText('Descargando')+' '+percent+' %'+mbText:'');
      progressBox.hidden=!downloading;progressBar.value=percent;
      errorEl.textContent=u.error&&!downloading?uiText(u.error):'';errorEl.hidden=!errorEl.textContent;
      installBtn.hidden=!u.ready;
      const fullNotes=String(u.available?.notes||'').trim();
      const snippet=compactNotes(fullNotes);
      notesEl.textContent=snippet;notesEl.hidden=!snippet;
      notesBtn.hidden=!fullNotes&&!u.available?.release_url;
      notesBtn.onclick=()=>openReleaseDialog({tag:'V-Agent '+version,notes:fullNotes,url:u.available?.release_url||u.available?.url||''});
      downloadBtn.textContent=uiText('Descargar versión')+' '+version;
      downloadBtn.hidden=Boolean(u.ready||u.busy);
      downloadBtn.disabled=Boolean(u.busy);
      if(u.error&&!u.ready&&!u.busy)downloadBtn.textContent=uiText('Reintentar descarga');
      laterBtn.hidden=false;
      notice.hidden=false;notice.dataset.version=version;
      return;
    }
    const m=lastMinor;
    if(m&&dismissed!==('minor:'+m.revision)){
      const tag=(m.version?m.version+' ':'')+'C'+m.revision;
      title.textContent=uiText('Actualización menor aplicada');
      detail.textContent=tag+(m.restart?' · '+uiText('Se aplicarán al reiniciar V-Agent.'):'');
      const fullNotes=String(m.notes||'').trim();
      const snippet=compactNotes(fullNotes);
      notesEl.textContent=snippet;notesEl.hidden=!snippet;
      notesBtn.hidden=!fullNotes;
      notesBtn.onclick=()=>openReleaseDialog({tag:'V-Agent '+tag,notes:fullNotes,url:''});
      downloadBtn.hidden=true;laterBtn.hidden=false;installBtn.hidden=true;progressBox.hidden=true;errorEl.hidden=true;
      notice.hidden=false;notice.dataset.version='minor:'+m.revision;
      return;
    }
    notice.hidden=true;
  };
  renderNotice();
  notice.append(title,detail,open,close,notesEl,notesBtn,downloadBtn,laterBtn,progressBox,errorEl,installBtn);document.body.append(notice);   // placed on screen by CSS order
  if(typeof document!=='undefined'&&typeof document.addEventListener==='function')document.addEventListener('v-agent-app-state',event=>{if(!event.detail)return;lastApp=event.detail;renderNotice();if(lastApp.busy)wakePoll(800);});if(typeof window!=='undefined'){window.VALI18n?.onChange?.(renderNotice);window.VALI18n?.observe?.(notice);}
  for(;;){
    await new Promise(resolve=>{pollWake=resolve;pollTimer=setTimeout(()=>{pollWake=null;resolve();},delay);});
    try{
      const [componentResult,appResult]=await Promise.allSettled([requestJSON('/api/harness/components'),requestJSON('/api/harness/app-update')]);
      const c=componentResult.status==='fulfilled'?componentResult.value:null;
      const u=appResult.status==='fulfilled'?appResult.value:null;
      if(!u){delay=60000;continue;}
      lastApp=u;
      if(c){
        if(start===null)start=c.revision||0;
        if((c.revision||0)>start){
          start=c.revision;loadUiPatch(true);
          const version=u.version||'';
          const tag=(version?version+' ':'')+'C'+c.revision;
          const snippet=compactNotes(c.notes||'');
          lastMinor={revision:c.revision,version,notes:c.notes||'',restart:!!c.restart_needed};
          note(uiText('Actualización menor aplicada')+': '+tag+(snippet?' — '+snippet:''));
        }
        document.dispatchEvent(new CustomEvent('v-agent-components-update',{detail:c}));
      }
      document.dispatchEvent(new CustomEvent('v-agent-app-update',{detail:u}));
      renderNotice();
      delay=u.busy?800:(c?.busy||(c&&!c.checked_at)||!u.checked_at||(c&&c.error&&!c.revision))?3000:60000;
    }catch{delay=60000;}
  }
}

// Pending updates marked where Settings opens, with words and not just a dot: a V-Agent release (most
// important, accent) or an engine update for an installed engine (quieter). Each tab says what waits there.
const updateBadges={app:false,engine:false};
// this file's own uiText lives inside watchAutomaticUpdates; the badge uses the global translator
const badgeText=text=>(typeof window!=='undefined'&&window.VALI18n?.t?.(text))||text;
function markUpdateBadge(kind,on){
  if(typeof document==='undefined'||typeof document.querySelector!=='function')return;
  if(updateBadges[kind]===Boolean(on)&&document.querySelector('#gear .update-pill')?.dataset.lang===(window.VALI18n?.language||'es'))return;
  updateBadges[kind]=Boolean(on);
  const gear=document.getElementById('gear');if(!gear)return;
  const any=updateBadges.app||updateBadges.engine;
  let pill=gear.querySelector('.update-pill');
  if(any&&!pill){pill=document.createElement('span');pill.className='update-pill';gear.append(pill);}
  if(pill){
    pill.hidden=!any;pill.dataset.level=updateBadges.app?'app':'engine';pill.dataset.lang=window.VALI18n?.language||'es';
    pill.textContent=badgeText(updateBadges.app?'Nueva versión':'Actualización');
  }
  gear.classList.toggle('has-update',any);
  for(const [category,kindFor] of [['general','app'],['system','engine']]){
    const tab=document.querySelector('#settingsNav [data-category="'+category+'"]');if(!tab)continue;
    let dot=tab.querySelector('.update-tab-pill');
    if(updateBadges[kindFor]&&!dot){dot=document.createElement('span');dot.className='update-tab-pill';tab.append(dot);}
    if(dot){dot.hidden=!updateBadges[kindFor];dot.dataset.level=kindFor;dot.textContent=badgeText(kindFor==='app'?'Nueva versión':'Actualización');}
  }
}
if(typeof window!=='undefined'){window.markUpdateBadge=markUpdateBadge;window.VALI18n?.onChange?.(()=>{markUpdateBadge('app',updateBadges.app);markUpdateBadge('engine',updateBadges.engine);});}
