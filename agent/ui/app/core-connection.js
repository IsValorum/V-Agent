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
function loadUiPatch(){
  const base=window.VAL_CORE_BASE||'',stamp=Date.now();
  let style=document.getElementById('uiPatchCss');
  if(!style){style=document.createElement('link');style.rel='stylesheet';style.id='uiPatchCss';document.head.append(style);}
  style.href=base+'/assets/ui-patch.css?t='+stamp;
  if(document.getElementById('uiPatchJs'))return;
  fetch('/assets/ui-patch.js',{cache:'no-store'}).then(response=>response.ok?response.text():'').then(code=>{
    if(!code.trim()||document.getElementById('uiPatchJs'))return;const script=document.createElement('script');script.id='uiPatchJs';script.src=base+'/assets/ui-patch.js?t='+stamp;document.body.append(script);
  }).catch(()=>{});
}
// V-Agent applies signed minor updates by itself shortly after starting (see desktop_runtime): when one
// lands while the window is open, its interface patch is loaded at once; a downloaded installer is announced.
async function watchAutomaticUpdates({requestJSON,uiText,note,setDrawer,selectSettingsCategory,showReleaseNotes}){
  let start=null,dismissed='',delay=1500,lastApp=null,lastMinor=null;
  const compactNotes=(notes,limit=160)=>{
    const clean=String(notes||'').replace(/\[([^\]]+)\]\([^)]+\)/g,'$1').replace(/^\s*(?:#{1,6}\s*|[-*+]\s+|\d+\.\s+)/gm,'').replace(/[`*_>~]+/g,'').replace(/\s+/g,' ').trim();
    return !clean?'':clean.length<=limit?clean:clean.slice(0,limit-1).trimEnd()+'…';
  };
  const notice=document.createElement('aside');notice.id='appUpdateNotice';notice.className='update-card';notice.hidden=true;notice.setAttribute('role','status');
  const title=document.createElement('strong'),detail=document.createElement('span'),open=document.createElement('button'),close=document.createElement('button'),notesEl=document.createElement('p'),notesBtn=document.createElement('button');
  notesEl.className='update-card-notes';notesEl.hidden=true;
  notesBtn.type='button';notesBtn.className='update-notes-btn';notesBtn.hidden=true;
  open.type='button';close.type='button';close.className='update-card-close';close.textContent='×';
  const openReleaseDialog=payload=>{
    if(typeof showReleaseNotes==='function')showReleaseNotes(payload);
    else if(typeof CustomEvent==='function')document.dispatchEvent(new CustomEvent('v-agent-show-notes',{detail:payload}));
  };
  const openSettings=()=>{setDrawer(true);selectSettingsCategory('general');document.getElementById('appUpdateBox')?.scrollIntoView({block:'nearest'});};
  open.onclick=openSettings;
  close.onclick=()=>{dismissed=notice.dataset.version||'';notice.hidden=true;};
  const renderNotice=()=>{
    close.setAttribute('aria-label',uiText('Descartar aviso'));
    open.textContent=uiText('Ver actualización');
    notesBtn.textContent=uiText('Notas de versión');
    const u=lastApp,version=u?.available?.version||'';
    if(version&&dismissed!==version){
      title.textContent=uiText('Nueva versión disponible');
      detail.textContent=version+(u.ready?' · '+uiText('Actualización descargada y verificada.'):u.busy&&u.progress?.total?' · '+uiText('Descargando')+' '+Math.min(100,Math.round(u.progress.received/u.progress.total*100))+' %':'');
      const fullNotes=String(u.available?.notes||'').trim();
      const snippet=compactNotes(fullNotes);
      notesEl.textContent=snippet;notesEl.hidden=!snippet;
      notesBtn.hidden=!fullNotes&&!u.available?.release_url;
      notesBtn.onclick=()=>openReleaseDialog({tag:'V-Agent '+version,notes:fullNotes,url:u.available?.release_url||u.available?.url||''});
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
      notice.hidden=false;notice.dataset.version='minor:'+m.revision;
      return;
    }
    notice.hidden=true;
  };
  renderNotice();
  notice.append(title,detail,open,close,notesEl,notesBtn);document.body.append(notice);
  if(typeof window!=='undefined'){window.VALI18n?.onChange?.(renderNotice);window.VALI18n?.observe?.(notice);}
  for(;;){
    await new Promise(resolve=>setTimeout(resolve,delay));
    try{
      const [componentResult,appResult]=await Promise.allSettled([requestJSON('/api/harness/components'),requestJSON('/api/harness/app-update')]);
      const c=componentResult.status==='fulfilled'?componentResult.value:null;
      const u=appResult.status==='fulfilled'?appResult.value:null;
      if(!u){delay=60000;continue;}
      lastApp=u;
      if(c){
        if(start===null)start=c.revision||0;
        if((c.revision||0)>start){
          start=c.revision;loadUiPatch();
          const version=u.version||'';
          const tag=(version?version+' ':'')+'C'+c.revision;
          const snippet=compactNotes(c.notes||'');
          lastMinor={revision:c.revision,version,notes:c.notes||'',restart:!!c.restart_needed};
          note(uiText('Actualización menor aplicada')+': '+tag+(snippet?' — '+snippet:''));
        }
      }
      document.dispatchEvent(new CustomEvent('v-agent-app-update',{detail:u}));
      renderNotice();
      delay=(c?.busy||u.busy||(c&&!c.checked_at)||!u.checked_at)?3000:60000;
    }catch{delay=60000;}
  }
}
