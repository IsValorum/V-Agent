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
async function watchAutomaticUpdates(){
  let start=null,announced=false;
  for(let attempt=0;attempt<40;attempt++){
    await new Promise(resolve=>setTimeout(resolve,attempt?3000:1500));
    try{
      const c=await requestJSON('/api/harness/components');
      if(start===null)start=c.revision||0;
      if((c.revision||0)>start){
        start=c.revision;loadUiPatch();
        const version=(await requestJSON('/api/harness/app-update').catch(()=>({}))).version||'';
        note(uiText('Actualización menor aplicada')+': '+(version?version+' ':'')+'C'+c.revision);
      }
      const u=await requestJSON('/api/harness/app-update');
      if(u.ready&&!announced){announced=true;note(uiText('Nueva versión lista para instalar')+': '+(u.available?.version||'')+' · '+uiText('Configuración → General'));}
      if(!c.busy&&c.checked_at&&!u.busy&&u.checked_at&&attempt>3)break;
    }catch{}
  }
}
