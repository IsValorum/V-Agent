  const coreReady=await waitForCore();
  if(coreReady){loadUiPatch();watchAutomaticUpdates();}
  if(!coreReady){
    const connection=document.getElementById('connectionText');if(connection)connection.textContent='Sin conexión local';
    const mode=document.getElementById('modeNote');if(mode)mode.textContent='El servicio local no respondió. Revisa data/logs/agent.log.';
    return;
  }
const $ = (s) => document.querySelector(s);
const LS = { set: "strataSettings", theme: "strataTheme2", convs: "strataConvs" };

const DEF_SAMPLING = { temperature: 0.6, top_p: 0.95, top_k: 20, min_p: 0, repetition_penalty: 1.0, max_tokens: 0, seed: 0, presence_penalty: 0, frequency_penalty: 0 };
const DEF_FUNCS = { search: false, visit: false, files: false, shell: false, sys: false, hf:false, date: true, browser: true, console: false, web:false, autobrowser:false, computer:false, admin:false };
let activeEngine='strata',engineSnapshot=null;
let selectedProject=null,selectedProjectChat=null,projectAssignments={},projectNames={};
let pcAccess={mode:'sandbox',root:''},accessChanging=false;
// Presupuesto del bloque de tools. Declarado aqui arriba porque en la carga se llega a el desde
// syncServerSwitches() (linea 1585 mas o menos) -> updateToolCount() -> consultarPresupuesto().
// Con el let cerca de esas funciones la variable estaba en zona muerta y el panel de MCP reventaba
// con "Cannot access 'presupuestoFirmado' before initialization"; lo pillo abriendo la UI en el
// navegador sin cabeza el 2026-11-04, el analizador estatico no lo ve.
let presupuestoTimer=null,presupuestoFirmado='',lastToolBudget=null;

const THEME_COLORS = ['accent','bg','panel','text','g1','g2','g3','codeBg','userBg'];
const THEME_RANGES = {messageRadius:[0,36],composerRadius:[0,40],lineHeight:[130,210],blur:[0,48],alpha:[40,100],composerAlpha:[40,100],drawerAlpha:[60,100],radius:[0,28],strength:[0,100],angle:[0,360],backgroundBlur:[0,100],outsideOpacity:[0,100],textShadow:[0,100],responseOpacity:[0,100],responseBlur:[0,32],responseRadius:[0,36],grain:[0,30],border:[0,35],shadow:[0,100],sidebarWidth:[200,340],chatWidth:[560,1200],fontSize:[12,20]};
const THEME_ENUMS = {gradient:['none','linear','radial','mesh'],font:['system','rounded','mono'],density:['compact','normal','airy']};
const VISUAL_DEFAULTS = {messageRadius:12,composerRadius:24,lineHeight:165,codeBg:"#141a1e",userBg:"#263a34",blur:0,alpha:100,composerAlpha:100,drawerAlpha:100,radius:12,gradient:'none',strength:0,angle:135,backgroundBlur:56,outsideOpacity:70,textShadow:0,responseOpacity:82,responseBlur:8,responseRadius:16,grain:0,border:10,shadow:10,sidebarWidth:246,chatWidth:800,fontSize:14,font:'system',density:'normal',showMark:true};
const COMPOSER_IDS=['attach','modelBtn','responseBtn','ctxBtn','mcpBtn','scopeBtn','send'];
const COMPOSER_LABELS={attach:'Añadir',modelBtn:'Modelo',responseBtn:'Respuesta',ctxBtn:'Contexto',mcpBtn:'Herramientas',scopeBtn:'Acceso',send:'Enviar'};
const DEFAULT_COMPOSER={left:COMPOSER_IDS.slice(0,-1),right:['send'],emptyRaised:true};
let draggingControl=null;
function normalizeComposer(value){
  if(!value||!Array.isArray(value.left)||!Array.isArray(value.right))return structuredClone(DEFAULT_COMPOSER);
  const seen=new Set(),result={left:[],right:[],emptyRaised:typeof value.emptyRaised==='boolean'?value.emptyRaised:true};
  for(const side of ['left','right'])for(const id of value[side])if(COMPOSER_IDS.includes(id)&&!seen.has(id)){result[side].push(id);seen.add(id);}
  for(const id of COMPOSER_IDS)if(!seen.has(id))result[id==='send'?'right':'left'].push(id);
  return result;
}
const DEF_THEME = {mode:'night',name:'V-Agent',visualVersion:2,composerLayout:structuredClone(DEFAULT_COMPOSER),
  night:{...VISUAL_DEFAULTS,codeBg:'#101716',userBg:'#29291f',accent:'#d2ad78',bg:'#101313',panel:'#191e1d',text:'#efe8dc',g1:'#453b2c',g2:'#263b36',g3:'#41322c'},
  day:{...VISUAL_DEFAULTS,outsideOpacity:82,codeBg:'#f3eee5',userBg:'#ebe0cd',accent:'#886333',bg:'#f4efe5',panel:'#fffcf5',text:'#30291f',g1:'#a9d4c5',g2:'#b6cce0',g3:'#d2e5d7',shadow:6}
};
function normalizeTheme(input) {
  const obj=input&&typeof input==='object'?input:{};
  const result={mode:obj.mode==='day'?'day':'night',name:typeof obj.name==='string'?obj.name.trim().slice(0,32)||'V-Agent':'V-Agent',visualVersion:2};
  if(['VAL'+' Harness','VAL'+' Agent'].includes(result.name))result.name='V-Agent'; // names used by older builds
  result.composerLayout=normalizeComposer(obj.composerLayout);
  for(const mode of ['night','day']) {
    const source=obj[mode]&&typeof obj[mode]==='object'?obj[mode]:{};
    result[mode]={...DEF_THEME[mode]};
    for(const key of THEME_COLORS) if(typeof source[key]==='string'&&/^#[0-9a-f]{6}$/i.test(source[key]))result[mode][key]=source[key];
    for(const [key,[min,max]] of Object.entries(THEME_RANGES)) {const value=source[key];if(value!==undefined&&value!==null&&value!==''&&Number.isFinite(Number(value)))result[mode][key]=Math.round(Math.min(max,Math.max(min,Number(value))));}
    for(const [key,values] of Object.entries(THEME_ENUMS)) if(values.includes(source[key]))result[mode][key]=source[key];
    if(typeof source.showMark==='boolean')result[mode].showMark=source.showMark;
  }
  return result;
}

function readStorage(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeStorage(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); }
  catch { if(key!==LS.theme)note("No se pudieron guardar los cambios. Revisa el espacio disponible del navegador."); }
}
let savedSettings = readStorage(LS.set, {});
if (!savedSettings || typeof savedSettings !== "object") savedSettings = {};
let S = { effort: "high", profile:"code", rounds:50, model: null, permissionMode:'ask', ...savedSettings,
  sampling: { ...DEF_SAMPLING, ...savedSettings.sampling }, functions: { ...DEF_FUNCS, ...savedSettings.functions } };
// Reset earlier automatic profile permissions once; later checkbox choices persist.
if(S.roundsVersion!==2){S.rounds=50;S.roundsVersion=2;}
if(S.functionsVersion!==2){S.functions={...DEF_FUNCS};S.functionsVersion=2;}
// Una sola vez: el limite de salida que venia de fabrica (8192) no era una eleccion del
// usuario, y cortaba las respuestas largas (el HTML de una isla, por ejemplo). 0 = sin
// limite, el hueco que quede en el contexto. Un valor elegido a mano se respeta.
if(S.samplingVersion!==1){if((S.sampling.max_tokens|0)===8192)S.sampling.max_tokens=0;S.samplingVersion=1;}
S.functions=Object.fromEntries(Object.keys(DEF_FUNCS).map(key=>[key,!!S.functions[key]]));
if (!["default","none","think","minimal","low","medium","high","xhigh"].includes(S.effort)) S.effort = "high";
let modelProfiles={},baseProfiles={},profilesReady=false;
const modelPreferences={},pendingPreferences=new Map();let preferencesTimer=null,preferencesSaving=null;
let modelContexts={},modelKV={};
let modelDrafts={},draftSaving=false;
const pendingModelContexts=new Map();
if (!S.profileVersion) {S.profile="code";S.profileVersion=1;}
const savedTheme = readStorage(LS.theme, {});
let TH = normalizeTheme(savedTheme);
if (!savedTheme?.visualVersion) for(const mode of ['night','day']) {
  const previous=savedTheme?.[mode],defaults=DEF_THEME[mode];
  if(previous&&previous.blur===0&&previous.alpha===100&&['accent','bg','panel','text'].every(key=>previous[key]===defaults[key])) {
    TH[mode].blur=defaults.blur;TH[mode].alpha=defaults.alpha;
  }
}
let convs = readStorage(LS.convs, []);
if (!Array.isArray(convs)) convs = [];
convs = convs.filter(c => c && typeof c.id === "string" && Array.isArray(c.messages));
let currentId = null, messages = [], attachments = [], busy = false, engineBusy = false, engineOnline = null;
let preparationState=null,loadingModelId=null,preparationTimer=null,preparationPending=false;
let toastTimer;
function saveSettings() { writeStorage(LS.set, S); updateToolCount(); }
function saveConvsLS() { if(!sessionsReady)writeStorage(LS.convs, convs); queueSessionSaves(); }
/* Bake ambient effects on theme/viewport changes. Hover only repaints controls,
   never live SVG filters, backdrop filters or a transformed full-screen blur. */
let ambientPaintFrame=0,ambientPaintKey='',ambientPaintRevision=0;
function paintAmbientTheme(p){
  const settings={...p},width=innerWidth,height=innerHeight;
  const key=JSON.stringify([width,height,...['bg','g1','g2','g3','gradient','angle','strength','backgroundBlur','grain','blur'].map(name=>settings[name])]);
  cancelAnimationFrame(ambientPaintFrame);
  if(key===ambientPaintKey)return;
  ambientPaintFrame=requestAnimationFrame(()=>{
    const scale=Math.min(1,1280/Math.max(width,height));
    const w=Math.max(1,Math.round(width*scale)),h=Math.max(1,Math.round(height*scale));
    const create=()=>{const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;return canvas;};
    const canvas=create(),ctx=canvas.getContext('2d',{willReadFrequently:true}),source=create(),draw=source.getContext('2d');
    if(!ctx||!draw)return;
    ctx.fillStyle=settings.bg;ctx.fillRect(0,0,w,h);
    if(settings.gradient!=='none'&&settings.strength>0){
      if(settings.gradient==='linear'){
        const angle=settings.angle*Math.PI/180,r=Math.hypot(w,h)/2;
        const gradient=draw.createLinearGradient(w/2-Math.sin(angle)*r,h/2+Math.cos(angle)*r,w/2+Math.sin(angle)*r,h/2-Math.cos(angle)*r);
        gradient.addColorStop(0,settings.g1);gradient.addColorStop(.55,settings.g2);gradient.addColorStop(1,settings.g3);draw.fillStyle=gradient;draw.fillRect(0,0,w,h);
      }else{
        draw.save();draw.scale(w,h);
        if(settings.gradient==='mesh'){
          draw.translate(.5,.5);draw.rotate((settings.angle-135)*Math.PI/180);draw.scale(1.35,1.35);draw.translate(-.5,-.5);
          for(const [x,y,color,end] of [[.16,.15,settings.g1,.62],[.86,.58,settings.g2,.64],[.45,1,settings.g3,.6]].reverse()){
            const gradient=draw.createRadialGradient(x,y,0,x,y,end);gradient.addColorStop(0,color);gradient.addColorStop(1,color+'00');draw.fillStyle=gradient;draw.fillRect(-1,-1,3,3);
          }
        }else{
          const gradient=draw.createRadialGradient(.45,.35,0,.45,.35,.8);gradient.addColorStop(0,settings.g1);gradient.addColorStop(.48,settings.g2);gradient.addColorStop(1,settings.g3);draw.fillStyle=gradient;draw.fillRect(0,0,1,1);
        }
        draw.restore();
      }
      ctx.globalAlpha=settings.strength/100;ctx.filter=`blur(${settings.backgroundBlur*scale}px)`;ctx.drawImage(source,0,0);ctx.filter='none';ctx.globalAlpha=1;
    }
    if(settings.grain>0){
      const pixels=ctx.getImageData(0,0,w,h),data=pixels.data;let seed=7341;
      for(let i=0;i<data.length;i+=4){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const noise=((seed>>>24)/255-.5)*settings.grain*.6;for(let channel=0;channel<3;channel++)data[i+channel]+=noise;}
      ctx.putImageData(pixels,0,0);
    }
    const ambient=canvas.toDataURL('image/png');
    let glass=ambient;
    if(settings.blur>0){
      const frost=create(),frostCtx=frost.getContext('2d');
      if(frostCtx){frostCtx.fillStyle=settings.bg;frostCtx.fillRect(0,0,w,h);frostCtx.filter=`blur(${settings.blur*scale}px)`;frostCtx.drawImage(canvas,0,0);glass=frost.toDataURL('image/png');}
    }
    const root=document.documentElement.style;
    root.setProperty('--ambient-image',`url("${ambient}")`);root.setProperty('--glass-image',`url("${glass}")`);
    ambientPaintKey=key;ambientPaintRevision++;$('#ambient').dataset.paintRevision=ambientPaintRevision;
  });
}
let ambientResizeTimer;
addEventListener('resize',()=>{clearTimeout(ambientResizeTimer);ambientResizeTimer=setTimeout(()=>paintAmbientTheme(TH[TH.mode]),120);});

function applyTheme(persist=true) {
  applyComposerLayout();
  const p = TH[TH.mode], r = document.documentElement.style;
  for (const k of ["accent", "bg", "panel", "text","codeBg","userBg"]) r.setProperty("--" + k, p[k]);
  r.setProperty("--message-radius",Math.max(2,p.messageRadius*Math.max(2,p.radius)/12)+"px");r.setProperty("--composer-radius",Math.max(2,p.composerRadius*Math.max(2,p.radius)/12)+"px");r.setProperty("--message-line-height",p.lineHeight/100);r.setProperty("--blur", p.blur + "px"); r.setProperty("--alpha", p.alpha / 100); r.setProperty("--radius", Math.max(2,p.radius) + "px");r.setProperty("--outside-opacity",p.outsideOpacity/100);r.setProperty("--response-opacity",p.responseOpacity/100);r.setProperty("--response-blur",p.responseBlur+"px");r.setProperty("--response-radius",p.responseRadius+"px");r.setProperty("--readability-shadow",p.textShadow?`0 1px 4px rgb(0 0 0 / ${p.textShadow/100}),0 0 12px rgb(0 0 0 / ${p.textShadow/200})`:"none");
  for(const [key,value] of Object.entries({'--composer-alpha':p.composerAlpha/100,'--drawer-alpha':p.drawerAlpha/100,'--gradient-strength':p.gradient==='none'?0:p.strength/100,'--background-blur':p.backgroundBlur+'px','--grain-opacity':p.grain/100,'--border-strength':p.border+'%','--sidebar-width':p.sidebarWidth+'px','--chat-width':p.chatWidth+'px','--chat-font':p.fontSize+'px','--message-gap':({compact:16,normal:28,airy:40})[p.density]+'px','--row-gap':({compact:10,normal:14,airy:18})[p.density]+'px'}))r.setProperty(key,value);
  r.setProperty('--ui-font',({system:"'Segoe UI',system-ui,sans-serif",rounded:"'Trebuchet MS','Segoe UI',sans-serif",mono:"Consolas,ui-monospace,monospace"})[p.font]);
  r.setProperty('--panel-shadow',`0 12px 42px rgba(0,0,0,${p.shadow/250})`);
  paintAmbientTheme(p);syncDesktopChrome(p,TH.mode);
  const solidResponses=localStorage.getItem('valSolidResponses')!=='0';document.documentElement.dataset.solidResponses=String(solidResponses);const solidBox=document.getElementById('t_solidResponses');if(solidBox)solidBox.checked=solidResponses;for(const key of ['responseOpacity','responseBlur','responseRadius']){const control=document.getElementById('t_'+key);if(control)control.disabled=solidResponses;}
  document.body.dataset.mark=p.showMark?'on':'off';document.body.dataset.density=p.density;
  const personalName=document.getElementById('personalName');if(personalName)personalName.textContent=TH.name;
  // Select readable foreground for the send button, including custom accents.
  const rgb = p.accent.match(/[a-f0-9]{2}/gi).map(h => parseInt(h,16)/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4);
  const lum = .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
  r.setProperty("--accent-ink", lum > .179 ? "#101216" : "#ffffff");
  document.documentElement.style.colorScheme = TH.mode === "night" ? "dark" : "light";
  document.body.dataset.themeMode=TH.mode;window.VALPalette?.refreshTheme();
  $("#themeBtn").innerHTML = TH.mode === "night" ? SUN_ICON : MOON_ICON;
  const label = TH.mode === "night" ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
  $("#themeBtn").title = label; $("#themeBtn").setAttribute("aria-label", label);
  document.querySelectorAll("[data-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.mode === TH.mode)));
  writeStorage(LS.theme, TH);
  if(persist)queueThemeSave();else themeRendered=structuredClone(TH);
}
const SUN_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg>';
const MOON_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.8 13A9 9 0 0 1 11 3.2 9 9 0 1 0 20.8 13Z"/></svg>';
const THEME_PENDING_KEY='strataThemePendingV1';
const themeClientId=crypto.randomUUID();
let themeSequence=0,themeSeenRevision=0,themePending=new Set(),themeInFlight=[],themeSeed=false,themeSaving=false,themeSaveTimer,themeRendered=null,themeSaveError=false;
const THEME_PATHS=['mode','name','composerLayout',...['night','day'].flatMap(mode=>[...THEME_COLORS,...Object.keys(THEME_RANGES),...Object.keys(THEME_ENUMS),'showMark'].map(field=>mode+'.'+field))];
const themePathValue=(theme,path)=>path.includes('.')?theme[path.split('.')[0]][path.split('.')[1]]:theme[path];
function setThemePath(theme,path,value){if(path.includes('.')){const [mode,field]=path.split('.');theme[mode][field]=value;}else theme[path]=value;}
function setThemeSaveState(text,error=false){const status=$('#themeSaveState');status.textContent=text;$('#retryThemeSave').hidden=!error;}
function localThemeWrite(key,value){try{localStorage.setItem(key,JSON.stringify(value));return true;}catch{return false;}}
function updateThemePendingStorage(){
  if(!themePending.size&&!themeInFlight.length&&!themeSeed){try{localStorage.removeItem(THEME_PENDING_KEY);}catch{}return;}
  localThemeWrite(THEME_PENDING_KEY,{theme:TH,pending:[...themePending],in_flight:themeInFlight,seed:themeSeed,client_id:themeClientId,sequence:themeSequence});
}
function queueThemeSave(){
  if(themeRendered)for(const path of THEME_PATHS)if(JSON.stringify(themePathValue(TH,path))!==JSON.stringify(themePathValue(themeRendered,path)))themePending.add(path);
  themeRendered=structuredClone(TH);updateThemePendingStorage();
  if(themePending.size||themeSeed){setThemeSaveState('Guardando…');clearTimeout(themeSaveTimer);themeSaveTimer=setTimeout(flushThemeSave,220);}
}
function mergeServerTheme(data){
  if(!data?.theme||Number(data.revision)<themeSeenRevision)return;
  themeSeenRevision=Number(data.revision)||0;
  const latest=normalizeTheme(data.theme);
  for(const path of themePending)setThemePath(latest,path,themePathValue(TH,path));
  TH=latest;applyTheme(false);syncThemeControls();
}
async function flushThemeSave(){
  clearTimeout(themeSaveTimer);if(themeSaving||(!themePending.size&&!themeSeed))return;
  themeSaving=true;themeSaveError=false;const paths=[...themePending];themePending.clear();themeInFlight=paths;
  const seed=themeSeed&&!paths.length;themeSequence++;updateThemePendingStorage();
  try{
    const response=await fetch('/api/ui/theme',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme:TH,changed:paths,seed,client_id:themeClientId,sequence:themeSequence}),keepalive:true,signal:AbortSignal.timeout(5000)});
    const data=await response.json();if(!response.ok||data.error)throw new Error(data.error||'No se pudo guardar.');
    themeSeed=false;themeInFlight=[];mergeServerTheme(data);setThemeSaveState(themePending.size?'Guardando…':'Guardado en este equipo');
  }catch{
    for(const path of paths)themePending.add(path);themeInFlight=[];themeSaveError=true;setThemeSaveState('Pendiente de guardar',true);
  }finally{
    themeSaving=false;updateThemePendingStorage();if(!themeSaveError&&(themePending.size||themeSeed))themeSaveTimer=setTimeout(flushThemeSave,40);
  }
}
async function restorePersistentTheme(){
  const localPending=readStorage(THEME_PENDING_KEY,null);
  let data=window.strataSavedAppearance;
  try{
    const suffix=typeof localPending?.client_id==='string'?'?client_id='+encodeURIComponent(localPending.client_id):'';
    if(!data||localPending){const response=await fetch('/api/ui/theme'+suffix,{cache:'no-store',signal:AbortSignal.timeout(2500)});data=await response.json();if(!response.ok||data.error)throw new Error('No se pudo leer el tema.');}
    if(data.theme){TH=normalizeTheme(data.theme);themeSeenRevision=Number(data.revision)||0;setThemeSaveState(data.recovered?'Aspecto recuperado':'Guardado en este equipo');}
    else setThemeSaveState('Se guarda al personalizar');
  }catch{setThemeSaveState('Copia local · sin conexión',true);themeSaveError=true;}
  if(localPending?.theme){
    const pendingTheme=normalizeTheme(localPending.theme),paths=new Set((Array.isArray(localPending.pending)?localPending.pending:[]).filter(path=>THEME_PATHS.includes(path)));
    if(!data||Number(data.last_sequence||0)<Number(localPending.sequence||0))for(const path of Array.isArray(localPending.in_flight)?localPending.in_flight:[])if(THEME_PATHS.includes(path))paths.add(path);
    for(const path of paths){setThemePath(TH,path,themePathValue(pendingTheme,path));themePending.add(path);}
    if(!data?.theme&&localPending.seed){TH=pendingTheme;themeSeed=true;}
  }
  if(!data?.theme&&!themePending.size&&!themeSeed&&savedTheme&&typeof savedTheme==='object'&&savedTheme.night&&savedTheme.day&&JSON.stringify(normalizeTheme(savedTheme))!==JSON.stringify(normalizeTheme(DEF_THEME)))themeSeed=true;
  themeRendered=structuredClone(TH);updateThemePendingStorage();
  if((themePending.size||themeSeed)&&!themeSaveError)themeSaveTimer=setTimeout(flushThemeSave,0);
}
function flushThemeOnClose(){
  clearTimeout(themeSaveTimer);const paths=[...new Set([...themeInFlight,...themePending])];if(!paths.length&&!themeSeed)return;
  const sequence=themeSequence+1,body={theme:TH,changed:paths,seed:themeSeed&&!paths.length,client_id:themeClientId,sequence};
  if(navigator.sendBeacon('/api/ui/theme',new Blob([JSON.stringify(body)],{type:'application/json'}))){themeSequence=sequence;themePending.clear();themeInFlight=paths;}
  updateThemePendingStorage();
}
window.addEventListener('pagehide',flushThemeOnClose);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')flushThemeOnClose();else if(themePending.size||themeSeed)flushThemeSave();});
window.addEventListener('online',()=>flushThemeSave());
window.addEventListener('storage',event=>{
  if(event.key!==LS.theme||!event.newValue||themeSaving)return;
  try{const next=normalizeTheme(JSON.parse(event.newValue));for(const path of themePending)setThemePath(next,path,themePathValue(TH,path));TH=next;applyTheme(false);syncThemeControls();}catch{}
});
$('#retryThemeSave').onclick=()=>{themeSaveError=false;if(!themePending.size&&!themeSeed)for(const path of THEME_PATHS)themePending.add(path);flushThemeSave();};

await restorePersistentTheme();
applyTheme(false);
async function requestJSON(url, options = {}) {
  const response = await fetch(url, options);
  let data; try { data = await response.json(); } catch { const raw="Respuesta no válida del servidor (" + response.status + ").";throw new Error(window.VALI18n?.t?.(raw)||raw); }
  if (!response.ok) {const raw=typeof data.error === "string" ? data.error : data.error?.message || "Error del servidor (" + response.status + ").";const error=new Error(window.VALI18n?.t?.(raw)||raw);error.status=response.status;throw error;}
  return data;
}
