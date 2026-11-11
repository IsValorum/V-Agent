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
async function watchAutomaticUpdates({requestJSON,uiText,note,setDrawer,selectSettingsCategory}){
  let start=null,dismissed='',delay=1500;
  const notice=document.createElement('aside');notice.id='appUpdateNotice';notice.className='update-card';notice.hidden=true;notice.setAttribute('role','status');
  const title=document.createElement('strong'),detail=document.createElement('span'),open=document.createElement('button'),close=document.createElement('button');
  title.textContent=uiText('Nueva versión disponible');open.textContent=uiText('Ver actualización');close.className='update-card-close';close.textContent='×';close.setAttribute('aria-label',uiText('Descartar aviso'));
  open.onclick=()=>{setDrawer(true);selectSettingsCategory('general');document.getElementById('appUpdateBox')?.scrollIntoView({block:'nearest'});};
  close.onclick=()=>{dismissed=notice.dataset.version||'';notice.hidden=true;};notice.append(title,detail,open,close);document.body.append(notice);
  for(;;){
    await new Promise(resolve=>setTimeout(resolve,delay));
    try{
      const [componentResult,appResult]=await Promise.allSettled([requestJSON('/api/harness/components'),requestJSON('/api/harness/app-update')]);
      const c=componentResult.status==='fulfilled'?componentResult.value:null;
      const u=appResult.status==='fulfilled'?appResult.value:null;
      if(!u){delay=60000;continue;}
      if(c){
      if(start===null)start=c.revision||0;
      if((c.revision||0)>start){
        start=c.revision;loadUiPatch();
        const version=u.version||'';
        note(uiText('Actualización menor aplicada')+': '+(version?version+' ':'')+'C'+c.revision);
      }
      }
      document.dispatchEvent(new CustomEvent('v-agent-app-update',{detail:u}));
      const version=u.available?.version||'';
      notice.hidden=!version||dismissed===version;notice.dataset.version=version;
      detail.textContent=version+(u.ready?' · '+uiText('Actualización descargada y verificada.'):u.busy&&u.progress?' · '+uiText('Descargando')+' '+Math.round(u.progress.received/u.progress.total*100)+' %':'');
      delay=(c?.busy||u.busy||(c&&!c.checked_at)||!u.checked_at)?3000:60000;
    }catch{delay=60000;}
  }
}
