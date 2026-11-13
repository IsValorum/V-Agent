/* Palette, logo and appearance controls. Legacy decorative styles are ignored. */
window.VALPalette=(()=>{
  const palettes={
    gold:{name:'Dorado',night:['#d2ad78','#19140f','#272016','#f1e8d9','#19130e','#382d1c'],day:['#896231','#f5efe4','#fffcf5','#30291f','#f1eadf','#eaddc4']},
    silver:{name:'Plateado',night:['#c6c6c6','#151515','#222222','#ededed','#141414','#303030'],day:['#526575','#eef2f5','#fafcfe','#253441','#e6edf2','#dfe7ee']},
    jade:{name:'Verde',night:['#83c49b','#101916','#192720','#e4efe7','#101b15','#233d2c'],day:['#376e4d','#eef4ec','#fafdf7','#243c2a','#e6efe3','#dcebdc']},
    blue:{name:'Azul',night:['#80b6df','#101720','#192431','#e4edf7','#101a26','#22384d'],day:['#356b94','#edf3f9','#f9fcff','#273d52','#e6eef6','#dce8f4']},
    rose:{name:'Rosado',night:['#d79aaa','#1b1318','#2a1e25','#f4e6ec','#20151c','#432a36'],day:['#9a536c','#f8edf2','#fff9fb','#482b38','#f4e4ec','#eed8e3']},
    ruby:{name:'Rojo',night:['#d98077','#1c1313','#2b1d1c','#f6e9e5','#221514','#432926'],day:['#9d403d','#f8efeb','#fffaf5','#492c29','#f1e2dc','#eed8d0']},
    violet:{name:'Morado',night:['#c29bd4','#18131f','#251e2e','#eee5f4','#1b1422','#3b2a46'],day:['#7c4b92','#f2edf8','#fcf9ff','#3c2b49','#eae2f2','#e8dcef']},
    ivory:{name:'Claro',night:['#ddd9cf','#111211','#1c1e1b','#f0ede5','#121411','#30332d'],day:['#292c27','#f6f5ef','#ffffff','#222620','#efeee7','#e4e6dc']}
  };
  const keys=Object.keys(palettes),defaults={style:'none',intensity:0,color:'#d2ad78',palette:'gold',logo:'gold',motif:'corners',amoled:false,logoSize:216,appIcon:'follow',showGreeting:true,uiStyle:'glass',buttonStyle:'tint',version:2};
  let current={...defaults},queue=Promise.resolve();
  function normalize(value={}){const d={...defaults,...value};delete d.background;d.style='none';d.palette=[...keys,'custom'].includes(d.palette)?d.palette:'gold';d.logo=keys.includes(d.logo)?d.logo:'gold';d.appIcon=['follow',...keys].includes(d.appIcon)?d.appIcon:'follow';d.amoled=d.amoled===true;d.showGreeting=d.showGreeting!==false;d.logoSize=Math.round(Math.max(64,Math.min(360,Number(d.logoSize)||216)));d.uiStyle=['glass','soft','deco'].includes(d.uiStyle)?d.uiStyle:'glass';d.buttonStyle=d.buttonStyle==='outline'?'outline':'tint';return d;}
  function tone(id,mode){const [accent,bg,panel,text,codeBg,userBg]=palettes[id][mode];return {accent,bg,panel,text,codeBg,userBg,g1:accent,g2:panel,g3:bg,gradient:'none',strength:0};}
  const toneFields=['accent','bg','panel','text','codeBg','userBg','g1','g2','g3','gradient','strength'];
  function rememberPalette(){
    if(!palettes[current.palette])return;
    const modes={};for(const mode of ['night','day'])modes[mode]=Object.fromEntries(toneFields.map(key=>[key,TH[mode][key]]));
    current={...current,paletteThemes:{...(current.paletteThemes||{}),[current.palette]:modes}};
  }
  function apply(value){
    current=normalize(value);const d=current,root=document.documentElement,base=TH[TH.mode];const amoled=d.amoled&&TH.mode==='night';
    root.dataset.amoled=String(amoled);root.dataset.brandLogo=d.logo;root.dataset.greeting=d.showGreeting?'on':'off';root.dataset.uiStyle=d.uiStyle;root.dataset.buttonStyle=d.buttonStyle;try{localStorage.setItem('valUiStyle',d.uiStyle+' '+d.buttonStyle);}catch{}
    for(const key of ['bg','panel','codeBg','userBg'])root.style.setProperty('--'+key,amoled?'#000000':base[key]);
    root.style.setProperty('--chat-logo-width',d.logoSize+'px');syncDesktopChrome({...base,panel:amoled?'#000000':base.panel},TH.mode);syncApplicationIcon(d.appIcon==='follow'?d.logo:d.appIcon);
    root.style.setProperty('--val-logo-image','url("/assets/branding/'+d.logo+'-cutout.svg")');
    const url='/assets/branding/'+d.logo+'-cutout.svg';for(const image of document.querySelectorAll('[data-val-logo]'))if(image.getAttribute('src')!==url)image.src=url;
    const rounded='/assets/branding/'+d.logo+'-icon.png';try{localStorage.setItem('valBootLogo',d.logo);}catch{}
    let icon=document.querySelector('link[rel=icon]');if(!icon){icon=document.createElement('link');icon.rel='icon';document.head.append(icon);}if(icon.getAttribute('href')!==rounded)icon.href=rounded;
    for(const [id,v] of Object.entries({decoLogo:d.logo,decoAppIcon:d.appIcon,decoUiStyle:d.uiStyle,decoButtonStyle:d.buttonStyle})){const input=document.getElementById(id);if(input&&document.activeElement!==input)input.value=v;}
    const amoledInput=document.getElementById('decoAmoled');if(amoledInput)amoledInput.checked=d.amoled;
    for(const card of document.querySelectorAll('.deco-palette-card[data-deco-palette]'))card.setAttribute('aria-pressed',String(card.dataset.decoPalette===d.palette));
  }
  function persist(){const snapshot={...current};queue=queue.catch(()=>{}).then(async()=>{try{const saved=await requestJSON('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decoration:snapshot})});uiPreferences.decoration=saved.decoration;const el=document.getElementById('decoSaveState');if(el)el.textContent=uiText('Guardado en este equipo');}catch(error){const el=document.getElementById('decoSaveState');if(el)el.textContent=uiText('No se pudieron guardar los ajustes.');}});}
  function choose(id){if(!palettes[id])return;if(id===current.palette)return;rememberPalette();if(id==='ivory'&&!current.amoled)TH.mode='day';for(const mode of ['night','day'])Object.assign(TH[mode],current.paletteThemes?.[id]?.[mode]||tone(id,mode));current={...current,palette:id,logo:id,color:TH[TH.mode].accent};applyTheme();syncThemeControls();apply(current);persist();}
  function resetPalette(id){if(!palettes[id])return;rememberPalette();const saved={...(current.paletteThemes||{})};delete saved[id];current={...current,paletteThemes:saved};if(id===current.palette){for(const mode of ['night','day'])Object.assign(TH[mode],tone(id,mode));current.color=TH[TH.mode].accent;applyTheme();syncThemeControls();}apply(current);persist();}
  function setup(){
    const host=document.getElementById('settings-appearance'),section=document.createElement('section');section.id='paletteSettings';section.className='palette-settings';
    section.innerHTML='<div class="deco-collection-heading"><h4>Colores y logotipos</h4></div><div id="decoThemeMode"></div><div id="decoPaletteGrid" role="group" aria-label="Colores y logotipos"></div><div class="setting-row app-icon-setting"><label for="decoAppIcon">Icono de la aplicación</label><select id="decoAppIcon"><option value="follow">Seguir el logo elegido</option></select></div><div class="setting-row"><label for="decoUiStyle">Estilo de la interfaz</label><select id="decoUiStyle"><option value="glass">Cristal</option><option value="soft">Suave</option><option value="deco">Art Déco</option></select></div><div class="setting-row"><label for="decoButtonStyle">Botones</label><select id="decoButtonStyle"><option value="tint">Con tinte suave</option><option value="outline">Con borde</option></select></div><p id="decoIconStatus" class="mini" role="status"></p><p class="mini" id="decoSaveState" role="status"></p>';
    host.querySelector('h3').after(section);const modes=host.querySelector('.mode-toggle');if(modes)section.querySelector('#decoThemeMode').append(modes);
    for(const id of keys){const item=palettes[id],button=document.createElement('button');button.type='button';button.dataset.decoPalette=id;button.className='deco-palette-card';button.style.setProperty('--card-art',item.night[0]);button.setAttribute('aria-label',item.name);const image=document.createElement('img');image.src='/assets/branding/'+id+'-icon.png';image.dataset.logoChoice=id;image.alt='';image.width=64;image.height=64;image.loading='lazy';const label=document.createElement('span');label.textContent=item.name;button.append(image,label);button.onclick=()=>choose(id);const wrap=document.createElement('div');wrap.className='palette-choice';const reset=document.createElement('button');reset.type='button';reset.className='palette-reset';reset.textContent='↻';reset.setAttribute('aria-label',uiText('Restaurar paleta')+' '+item.name);reset.title=uiText('Restaurar paleta')+' '+item.name;reset.onclick=()=>resetPalette(id);wrap.append(button,reset);section.querySelector('#decoPaletteGrid').append(wrap);document.getElementById('decoAppIcon').add(new Option(item.name,id));}
    const amoled=document.createElement('label');amoled.className='chk amoled-setting';amoled.innerHTML='<input id="decoAmoled" type="checkbox"> Negro AMOLED';document.getElementById('decoThemeMode').append(amoled);
    document.getElementById('decoAmoled').onchange=()=>{current={...current,amoled:document.getElementById('decoAmoled').checked};if(current.amoled)TH.mode='night';applyTheme();syncThemeControls();apply(current);persist();};
    for(const [id,key] of Object.entries({decoAppIcon:'appIcon',decoUiStyle:'uiStyle',decoButtonStyle:'buttonStyle'})){const input=document.getElementById(id);input.onchange=()=>{apply({...current,[key]:input.value});persist();};}
    window.VALI18n?.observe(section);apply(uiPreferences.decoration||{});
  }
  return {setup,apply,choose,resetPalette,normalize,tone,palettes,refreshTheme:()=>apply(current)};
})();
