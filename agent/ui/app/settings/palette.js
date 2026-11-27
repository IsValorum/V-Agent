/* Palette, logo and appearance controls. Legacy decorative styles are ignored. */
window.VALPalette=(()=>{
  const palettes={
    // Dark-background minimalist logos (Fondo-Negro)
    gold:{name:'Dorado',surface:'dark',night:['#daaa69','#14110d','#211c14','#f2eadc','#15110c','#342a1b'],day:['#9b6e35','#f6f0e5','#fffcf6','#2e271d','#f1eadf','#eaddc4']},
    silver:{name:'Blanco',surface:'dark',night:['#e4e6ea','#111214','#1c1e22','#f1f3f5','#101113','#2c2f36'],day:['#4e5764','#f0f2f5','#fbfcfd','#222933','#e8ecf0','#dfe5ec']},
    jade:{name:'Verde',surface:'dark',night:['#52a87e','#0e1613','#17241e','#e3f0e9','#0d1612','#20392d'],day:['#357a55','#edf4ef','#f9fdf9','#21392b','#e4efe7','#d8eadf']},
    blue:{name:'Azul',surface:'dark',night:['#35aed0','#0d151a','#16222a','#e2eff5','#0c161c','#1e3542'],day:['#247896','#ecf4f8','#f8fcff','#203846','#e3eff5','#d6e8f2']},
    rose:{name:'Rosado',surface:'dark',night:['#dd9fb0','#181216','#261c22','#f4e8ec','#1b1318','#3f2934'],day:['#a2556d','#f8eef2','#fff9fb','#462a36','#f3e4ea','#ecd7e1']},
    ruby:{name:'Rojo',surface:'dark',night:['#d6655f','#191111','#281a1a','#f6e8e6','#1d1212','#402524'],day:['#a63834','#f8eeec','#fff9f8','#482927','#f2e2df','#edd6d2']},
    violet:{name:'Morado',surface:'dark',night:['#b876c7','#16111b','#231a2b','#efe6f5','#18121f','#392745'],day:['#823e92','#f3edf8','#fcf9ff','#3b2847','#ebe1f2','#e5d7f0']},
    // Light-background minimalist logos (Fondo-Blanco)
    'gold-light':{name:'Dorado',surface:'light',night:['#d5a462','#15120e','#221c15','#f2eadc','#15110c','#352b1c'],day:['#a6773c','#f7f1e6','#fffdf8','#2f271c','#f1e9dc','#eadbc2']},
    'silver-light':{name:'Plateado',surface:'light',night:['#b8bcc4','#141517','#202226','#eceef2','#131416','#2e3138'],day:['#5d646e','#f2f3f5','#fcfcfd','#262a30','#e9ebef','#e0e3e9']},
    'jade-light':{name:'Verde',surface:'light',night:['#5eb378','#0f1712','#18251d','#e5f1e8','#0e1711','#223a2b'],day:['#3a8250','#eef5f0','#fafdfb','#213a29','#e5f0e8','#d9ebde']},
    'blue-light':{name:'Azul',surface:'light',night:['#5ea7d4','#0f161e','#18232f','#e4eef7','#0f1722','#21364b'],day:['#2f78a6','#edf4fa','#f9fcff','#223a4d','#e5eff8','#d8e8f5']},
    'rose-light':{name:'Rosado',surface:'light',night:['#d98fa4','#191216','#281d23','#f5e8ed','#1c1319','#412a35'],day:['#a95b72','#f9eef2','#fffafc','#472a36','#f4e5eb','#edd8e2']},
    'ruby-light':{name:'Rojo',surface:'light',night:['#d85a56','#1a1111','#291a1a','#f6e8e7','#1e1212','#422424'],day:['#b02d2a','#f9eeed','#fffaf9','#492726','#f3e2e0','#eed6d3']},
    'violet-light':{name:'Morado',surface:'light',night:['#b468bf','#17111b','#241a2b','#efe6f5','#19121f','#3a2645'],day:['#833a8c','#f4edf8','#fdfaff','#3c2745','#ece1f3','#e6d6f0']},
    ivory:{name:'Oscuro',surface:'light',night:['#d8dce2','#111214','#1c1e21','#eff1f4','#111214','#2c2f35'],day:['#2b3036','#f5f6f8','#ffffff','#1f2328','#eceef2','#e2e5eb']}
  };
  const keys=Object.keys(palettes),defaults={style:'none',intensity:0,color:'#daaa69',palette:'gold',logo:'gold',motif:'corners',amoled:false,logoSize:216,appIcon:'follow',showGreeting:true,uiStyle:'glass',buttonStyle:'tint',version:2};
  let current={...defaults},queue=Promise.resolve(),bootIconAtStart=null,restartDialogOpen=false;
  function effectiveIcon(d){return d.appIcon==='follow'?d.logo:d.appIcon;}
  // Each interface style is a real starting point: it sets the appearance controls (transparency, blur, borders,
  // shadow, corners) for day and night, which the user can then fine-tune. Before, the style changed almost
  // nothing because those controls kept their values and overrode it.
  const STYLE_PRESETS={
    glass:{blur:24,alpha:70,composerAlpha:68,drawerAlpha:82,radius:16,border:14,shadow:45,messageRadius:12,composerRadius:18},
    soft:{blur:0,alpha:100,composerAlpha:100,drawerAlpha:100,radius:14,border:0,shadow:24,messageRadius:12,composerRadius:16},
    deco:{blur:0,alpha:100,composerAlpha:100,drawerAlpha:100,radius:3,border:30,shadow:0,messageRadius:12,composerRadius:12}};
  function applyStylePreset(style){
    const preset=STYLE_PRESETS[style];if(!preset||typeof TH!=='object')return;
    for(const mode of ['night','day'])if(TH[mode])Object.assign(TH[mode],preset);
    if(typeof applyTheme==='function')applyTheme();
    if(typeof syncThemeControls==='function')syncThemeControls();
    const status=document.getElementById('decoIconStatus');
    if(status)status.textContent=uiText('Estilo aplicado. Puedes afinar la transparencia, el desenfoque, los bordes, la sombra y la redondez en Colores y en Distribución y formas.');
  }
  function normalize(value={}){const d={...defaults,...value};delete d.background;d.style='none';d.palette=[...keys,'custom'].includes(d.palette)?d.palette:'gold';d.logo=keys.includes(d.logo)?d.logo:'gold';d.appIcon=['follow',...keys].includes(d.appIcon)?d.appIcon:'follow';d.amoled=d.amoled===true;d.showGreeting=d.showGreeting!==false;d.logoSize=Math.round(Math.max(64,Math.min(360,Number(d.logoSize)||216)));d.uiStyle=['glass','soft','deco'].includes(d.uiStyle)?d.uiStyle:'glass';d.buttonStyle=d.buttonStyle==='outline'?'outline':'tint';return d;}
  function tone(id,mode){const [accent,bg,panel,text,codeBg,userBg]=palettes[id][mode];return {accent,bg,panel,text,codeBg,userBg,g1:accent,g2:panel,g3:bg,gradient:'none',strength:0};}
  const toneFields=['accent','bg','panel','text','codeBg','userBg','g1','g2','g3','gradient','strength'];
  function rememberPalette(){
    if(!palettes[current.palette])return;
    const modes={};for(const mode of ['night','day'])modes[mode]=Object.fromEntries(toneFields.map(key=>[key,TH[mode][key]]));
    current={...current,paletteThemes:{...(current.paletteThemes||{}),[current.palette]:modes}};
  }
  function syncVisibleGroup(){
    const activeSurface=TH.mode==='day'?'light':'dark';
    for(const group of document.querySelectorAll('.palette-group-grid[data-surface]'))group.hidden=group.dataset.surface!==activeSurface;
    const amoledRow=document.getElementById('decoAmoled')?.closest('label');
    if(amoledRow)amoledRow.hidden=TH.mode==='day';
  }
  function syncRestartNotice(){
    const notice=document.getElementById('decoRestartNotice');if(!notice)return;
    const pending=bootIconAtStart!==null&&(current.logo!==bootIconAtStart.logo||effectiveIcon(current)!==bootIconAtStart.icon);
    notice.hidden=!pending;
  }
  async function restartNow(){
    try{await queue;}catch{}
    try{if(typeof flushSessionSaves==='function')await flushSessionSaves();}catch{}
    if(window.__TAURI__?.core?.invoke){
      try{await window.__TAURI__.core.invoke('restart_app');return;}catch(error){console.warn('Restart:',error);}
    }
    if(typeof location!=='undefined'&&typeof location.reload==='function')location.reload();
  }
  async function promptLogoRestart(){
    syncRestartNotice();
    if(typeof valConfirm!=='function'||restartDialogOpen)return;
    restartDialogOpen=true;
    try{
      const ok=await valConfirm({
        title:'Reiniciar para aplicar los logos',
        message:'El aspecto general ya cambió. Si no reinicias ahora, los logotipos y la pantalla de carga no se actualizarán hasta que vuelvas a abrir V-Agent.',
        confirm:'Reiniciar ahora',
        cancel:'Más tarde'
      });
      if(ok)await restartNow();
    }finally{restartDialogOpen=false;}
  }
  function apply(value){
    current=normalize(value);const d=current,root=document.documentElement,base=TH[TH.mode];const amoled=d.amoled&&TH.mode==='night';
    if(bootIconAtStart===null)bootIconAtStart={logo:d.logo,icon:effectiveIcon(d)};
    const surface=palettes[d.logo]?.surface||'dark';
    root.dataset.amoled=String(amoled);root.dataset.brandLogo=d.logo;root.dataset.bootSurface=surface;root.dataset.greeting=d.showGreeting?'on':'off';root.dataset.uiStyle=d.uiStyle;root.dataset.buttonStyle=d.buttonStyle;try{localStorage.setItem('valUiStyle',d.uiStyle+' '+d.buttonStyle);}catch{}
    for(const key of ['bg','panel','codeBg','userBg'])root.style.setProperty('--'+key,amoled?'#000000':base[key]);
    root.style.setProperty('--chat-logo-width',d.logoSize+'px');syncDesktopChrome({...base,panel:amoled?'#000000':base.panel},TH.mode);syncApplicationIcon(effectiveIcon(d));
    root.style.setProperty('--val-logo-image','url("/assets/branding/'+d.logo+'-cutout.svg")');
    const url='/assets/branding/'+d.logo+'-cutout.svg';for(const image of document.querySelectorAll('[data-val-logo]'))if(image.getAttribute('src')!==url)image.src=url;
    const rounded='/assets/branding/'+d.logo+'-icon.png';try{localStorage.setItem('valBootLogo',d.logo);}catch{}
    let icon=document.querySelector('link[rel=icon]');if(!icon){icon=document.createElement('link');icon.rel='icon';document.head.append(icon);}if(icon.getAttribute('href')!==rounded)icon.href=rounded;
    for(const [id,v] of Object.entries({decoLogo:d.logo,decoAppIcon:d.appIcon,decoUiStyle:d.uiStyle,decoButtonStyle:d.buttonStyle})){const input=document.getElementById(id);if(input&&document.activeElement!==input)input.value=v;}
    const amoledInput=document.getElementById('decoAmoled');if(amoledInput)amoledInput.checked=d.amoled;
    for(const card of document.querySelectorAll('.deco-palette-card[data-deco-palette]'))card.setAttribute('aria-pressed',String(card.dataset.decoPalette===d.palette));
    syncVisibleGroup();syncRestartNotice();
  }
  function persist(){const snapshot={...current};queue=queue.catch(()=>{}).then(async()=>{try{const saved=await requestJSON('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decoration:snapshot})});uiPreferences.decoration=saved.decoration;const el=document.getElementById('decoSaveState');if(el)el.textContent=uiText('Guardado en este equipo');}catch(error){const el=document.getElementById('decoSaveState');if(el)el.textContent=uiText('No se pudieron guardar los ajustes.');}});}
  function choose(id,interactive=false){
    if(!palettes[id])return;if(id===current.palette)return;
    const prevLogo=current.logo,prevIcon=effectiveIcon(current);
    rememberPalette();
    const isLight=palettes[id].surface==='light';
    let amoled=current.amoled;
    if(isLight){amoled=false;TH.mode='day';}
    else if(TH.mode==='day'){TH.mode='night';}
    for(const mode of ['night','day'])Object.assign(TH[mode],current.paletteThemes?.[id]?.[mode]||tone(id,mode));
    current={...current,palette:id,logo:id,amoled,color:TH[TH.mode].accent};
    applyTheme();syncThemeControls();apply(current);persist();
    if(interactive&&(current.logo!==prevLogo||effectiveIcon(current)!==prevIcon))promptLogoRestart();
  }
  function resetPalette(id){if(!palettes[id])return;rememberPalette();const saved={...(current.paletteThemes||{})};delete saved[id];current={...current,paletteThemes:saved};if(id===current.palette){for(const mode of ['night','day'])Object.assign(TH[mode],tone(id,mode));current.color=TH[TH.mode].accent;applyTheme();syncThemeControls();}apply(current);persist();}
  function setup(){
    const host=document.getElementById('settings-appearance'),section=document.createElement('section');section.id='paletteSettings';section.className='palette-settings';
    section.innerHTML='<div class="deco-collection-heading"><h4>Colores y logotipos</h4></div><div id="decoThemeMode"></div><div id="decoPaletteGrid" role="group" aria-label="Colores y logotipos"></div><div id="decoRestartNotice" class="deco-restart-notice" hidden><span>Reinicia V-Agent para aplicar los nuevos logotipos.</span><button id="decoRestartNow" type="button" class="soft-btn primary">Reiniciar ahora</button></div><div class="setting-row app-icon-setting"><label for="decoAppIcon">Icono de la aplicación</label><select id="decoAppIcon"><option value="follow">Seguir el logo elegido</option></select></div><div class="setting-row"><label for="decoUiStyle">Estilo de la interfaz</label><select id="decoUiStyle"><option value="glass">Cristal</option><option value="soft">Suave</option><option value="deco">Art Déco</option></select></div><div class="setting-row"><label for="decoButtonStyle">Botones</label><select id="decoButtonStyle"><option value="tint">Con tinte suave</option><option value="outline">Con borde</option></select></div><p id="decoIconStatus" class="mini" role="status"></p><p class="mini" id="decoSaveState" role="status"></p>';
    host.querySelector('h3').after(section);const modes=host.querySelector('.mode-toggle');if(modes)section.querySelector('#decoThemeMode').append(modes);
    const gridHost=section.querySelector('#decoPaletteGrid');
    const iconSelect=document.getElementById('decoAppIcon');
    const groups=[['dark','Fondo oscuro'],['light','Fondo claro']];
    for(const [surface,heading] of groups){
      const groupGrid=document.createElement('div');groupGrid.className='palette-group-grid';groupGrid.dataset.surface=surface;
      const optGroup=document.createElement('optgroup');optGroup.dataset.i18nLabel=heading;optGroup.label=uiText(heading);
      for(const id of keys.filter(k=>palettes[k].surface===surface)){
        const item=palettes[id],button=document.createElement('button');
        button.type='button';button.dataset.decoPalette=id;button.className='deco-palette-card';
        button.style.setProperty('--card-art',surface==='light'?item.day[0]:item.night[0]);
        button.setAttribute('aria-label',uiText(item.name)+' · '+uiText(heading));
        const image=document.createElement('img');image.src='/assets/branding/'+id+'-icon.png';image.dataset.logoChoice=id;image.alt='';image.width=64;image.height=64;image.loading='lazy';
        const label=document.createElement('span');label.textContent=item.name;
        button.append(image,label);button.onclick=()=>choose(id,true);
        const wrap=document.createElement('div');wrap.className='palette-choice';
        const reset=document.createElement('button');reset.type='button';reset.className='palette-reset';reset.textContent='↻';
        reset.setAttribute('aria-label',uiText('Restaurar paleta')+' '+uiText(item.name));reset.title=uiText('Restaurar paleta')+' '+uiText(item.name);
        reset.onclick=()=>resetPalette(id);
        wrap.append(button,reset);groupGrid.append(wrap);
        const opt=new Option(uiText(item.name),id);opt.dataset.i18nOption=item.name;optGroup.append(opt);
      }
      gridHost.append(groupGrid);
      iconSelect.append(optGroup);
    }
    window.VALI18n?.onChange?.(()=>{
      for(const og of iconSelect.querySelectorAll('optgroup[data-i18n-label]'))og.label=uiText(og.dataset.i18nLabel);
      for(const opt of iconSelect.querySelectorAll('option[data-i18n-option]'))opt.textContent=uiText(opt.dataset.i18nOption);
    });
    const amoled=document.createElement('label');amoled.className='chk amoled-setting';amoled.innerHTML='<input id="decoAmoled" type="checkbox"> Negro AMOLED';document.getElementById('decoThemeMode').append(amoled);
    document.getElementById('decoAmoled').onchange=()=>{current={...current,amoled:document.getElementById('decoAmoled').checked};if(current.amoled)TH.mode='night';applyTheme();syncThemeControls();apply(current);persist();};
    document.getElementById('decoRestartNow').onclick=()=>restartNow();
    for(const [id,key] of Object.entries({decoAppIcon:'appIcon',decoUiStyle:'uiStyle',decoButtonStyle:'buttonStyle'})){
      const input=document.getElementById(id);
      input.onchange=()=>{
        const prevIcon=effectiveIcon(current);
        apply({...current,[key]:input.value});persist();
        if(key==='uiStyle')applyStylePreset(input.value);
        if(key==='appIcon'&&effectiveIcon(current)!==prevIcon)promptLogoRestart();
      };
    }
    window.VALI18n?.observe(section);apply(uiPreferences.decoration||{});
  }
  return {setup,apply,choose,resetPalette,normalize,tone,palettes,refreshTheme:()=>apply(current)};
})();
