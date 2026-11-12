/* Floating, non-modal panels: automatic tiling, persisted sizes and motion. */
(()=>{
  const MIN_WIDTH=220,MIN_HEIGHT=160,EDGE=12,GAP=12,TOP=64;
  const DEFAULTS={settings:{width:780,height:640},model:{width:400,height:640},tools:{width:400,height:560},project:{width:360,height:380},import:{width:430,height:520},console:{width:620,height:420},browser:{width:520,height:700},models:{width:1040,height:700}};
  const entries=new Map(),sizes={},dirtySizes=new Set(),animationsMap=new WeakMap(),layoutAnims=new WeakMap(),reduce=matchMedia('(prefers-reduced-motion: reduce)');
  let layer=null,stack=75,saveTimer=0,saving=false,saveAgain=false,prefsLoaded=false,needsSave=false,retried=false,orderCounter=0,layoutTimer=0;
  let animateWindows=true;
  try{animateWindows=localStorage.getItem('valWindowAnimations')!=='0';}catch{}
  function clamp(value,min,max){return Math.max(min,Math.min(max,value));}
  function ensureLayer(){
    if(layer&&layer.isConnected)return layer;
    layer=document.getElementById('floatLayer');
    if(!layer){layer=document.createElement('div');layer.id='floatLayer';document.body.append(layer);}
    return layer;
  }
  function startLeft(){
    const sidebar=document.getElementById('sidebar');
    if(innerWidth>760&&sidebar){
      const box=sidebar.getBoundingClientRect();
      if(box.width>0&&box.right>0)return Math.round(box.right+GAP);
    }
    return EDGE;
  }
  function startTop(){return innerWidth<=760?56:TOP;}
  function dockLeft(){
    if(!document.body.classList.contains('browser-open'))return null;
    const dock=document.getElementById('browserDock');
    if(!dock||dock.hidden)return null;
    const box=dock.getBoundingClientRect();
    return box.width>0?box.left-GAP:null;
  }
  function area(){
    const left=startLeft(),top=startTop(),right=dockLeft()||(innerWidth-EDGE),bottom=innerHeight-EDGE;
    return {left,top,right:Math.max(left+MIN_WIDTH,right),bottom:Math.max(top+MIN_HEIGHT,bottom)};
  }
  function sizeFor(id){
    const box=sizes[id]||DEFAULTS[id]||{width:360,height:420};
    return {width:clamp(Math.round(box.width),MIN_WIDTH,Math.max(MIN_WIDTH,innerWidth-EDGE*2)),height:clamp(Math.round(box.height),MIN_HEIGHT,Math.max(MIN_HEIGHT,innerHeight-EDGE*2))};
  }
  function motionDuration(){
    const raw=getComputedStyle(document.documentElement).getPropertyValue('--motion-duration').trim();
    const value=parseFloat(raw);
    return Number.isFinite(value)?Math.max(0,value):620;
  }
  function cancelAnim(el){
    const animation=animationsMap.get(el);
    if(animation){try{animation.cancel();}catch{}animationsMap.delete(el);}
    el.style.opacity='';el.style.transform='';
  }
  // While a glass window moves or fades it is drawn without live blur (data-motion): blurring every
  // frame halved the frame rate and made windows blink on hybrid-GPU laptops. Blur fades back in after.
  function track(el,animation){
    el.dataset.motion='1';
    const done=()=>{if(!animationsMap.has(el)&&!layoutAnims.has(el))delete el.dataset.motion;};
    const later=()=>setTimeout(done,0);
    if(typeof animation.addEventListener==='function'){animation.addEventListener('finish',later);animation.addEventListener('cancel',later);}else animation.finished?.then?.(later,later);
  }
  function animateIn(el){
    if(!animateWindows||reduce.matches||!el.animate)return;
    cancelAnim(el);
    const animation=el.animate([{opacity:0,transform:'translateY(8px) scale(.985)'},{opacity:1,transform:'none'}],
      {duration:motionDuration(),easing:'cubic-bezier(.2,.8,.2,1)'});
    animationsMap.set(el,animation);
    animation.onfinish=()=>{if(animationsMap.get(el)===animation)animationsMap.delete(el);};
    track(el,animation);
  }
  function animateOut(el,finished){
    if(!animateWindows||reduce.matches||!el.animate){finished();return;}
    cancelAnim(el);
    const animation=el.animate([{opacity:1,transform:'none'},{opacity:0,transform:'translateY(8px) scale(.985)'}],
      {duration:motionDuration(),easing:'cubic-bezier(.4,0,.2,1)'});
    animationsMap.set(el,animation);
    animation.onfinish=()=>{if(animationsMap.get(el)!==animation)return;animationsMap.delete(el);finished();};
    track(el,animation);
  }
  function cancelLayout(el){
    const animation=layoutAnims.get(el);
    if(animation){try{animation.cancel();}catch{}layoutAnims.delete(el);}
  }
  function animateLayout(el,from,to){
    if(!animateWindows||reduce.matches||!el.animate)return;
    const duration=motionDuration();
    if(duration<10)return;
    if(Math.abs(from.left-to.left)<1&&Math.abs(from.top-to.top)<1&&Math.abs(from.width-to.width)<1&&Math.abs(from.height-to.height)<1)return;
    cancelLayout(el);
    const animation=el.animate([
      {left:from.left+'px',top:from.top+'px',width:from.width+'px',height:from.height+'px'},
      {left:to.left+'px',top:to.top+'px',width:to.width+'px',height:to.height+'px'}
    ],{duration,easing:'cubic-bezier(.2,.8,.2,1)'});
    layoutAnims.set(el,animation);
    animation.onfinish=()=>{if(layoutAnims.get(el)===animation)layoutAnims.delete(el);};
    track(el,animation);
  }
  function freezeLayout(item){
    const animation=layoutAnims.get(item.el);
    if(!animation)return;
    const rect=item.el.getBoundingClientRect();
    animation.cancel();layoutAnims.delete(item.el);
    item.el.style.left=rect.left+'px';item.el.style.top=rect.top+'px';
    item.el.style.width=rect.width+'px';item.el.style.height=rect.height+'px';
  }
  function arrange(){
    const open=[...entries.values()].filter(item=>!item.el.hidden&&!item.closing);
    if(!open.length)return;
    open.sort((a,b)=>(a.order||0)-(b.order||0));
    const box=area(),width=Math.max(MIN_WIDTH,box.right-box.left),height=Math.max(MIN_HEIGHT,box.bottom-box.top);
    const rows=[];let row=null,used=0;
    for(const item of open){
      const desired=sizeFor(item.id);
      if(row&&used+GAP+desired.width>width){rows.push(row);row=null;used=0;}
      if(!row)row={items:[],widths:[],heights:[],total:0};
      const itemWidth=Math.min(desired.width,width);
      if(row.items.length)used+=GAP;
      used+=itemWidth;
      row.items.push(item);row.widths.push(itemWidth);row.heights.push(desired.height);row.total+=itemWidth;
    }
    if(row)rows.push(row);
    const gaps=(rows.length-1)*GAP;
    const maxHeights=rows.map(current=>Math.max(...current.heights));
    const desiredTotal=maxHeights.reduce((sum,value)=>sum+value,0)+gaps;
    const heightScale=desiredTotal>height?Math.max(0.28,(height-gaps)/Math.max(1,desiredTotal-gaps)):1;
    const before=new Map();
    for(const current of rows)for(const item of current.items){
      if(item.entering)continue;
      const rect=item.el.getBoundingClientRect();
      if(rect.width>0&&rect.height>0)before.set(item,{left:rect.left,top:rect.top,width:rect.width,height:rect.height});
    }
    let y=box.top;
    for(let index=0;index<rows.length;index++){
      const current=rows[index];
      const rowGaps=(current.items.length-1)*GAP;
      let widths=current.widths.slice();
      const sum=widths.reduce((total,value)=>total+value,0)+rowGaps;
      if(sum>width){
        const factor=(width-rowGaps)/Math.max(1,sum-rowGaps);
        widths=widths.map(value=>Math.max(160,Math.floor(value*factor)));
      }
      const rowHeight=Math.max(MIN_HEIGHT,Math.min(maxHeights[index],Math.floor(maxHeights[index]*heightScale)));
      let x=box.left;
      for(let position=0;position<current.items.length;position++){
        const item=current.items[position];
        const itemHeight=Math.max(MIN_HEIGHT,Math.min(current.heights[position],rowHeight));
        item.el.style.width=widths[position]+'px';
        item.el.style.height=itemHeight+'px';
        item.el.style.left=x+'px';
        item.el.style.top=y+'px';
        item.el.style.right='auto';item.el.style.bottom='auto';
        item.el.style.maxWidth='none';item.el.style.maxHeight='none';
        if(before.has(item))animateLayout(item.el,before.get(item),{left:x,top:y,width:widths[position],height:itemHeight});
        x+=widths[position]+GAP;
      }
      y+=rowHeight+GAP;
    }
  }
  function scheduleArrange(){
    clearTimeout(layoutTimer);
    layoutTimer=setTimeout(()=>arrange(),60);
  }
  function raise(item){item.el.style.zIndex=String(++stack);}
  function beginDrag(item,event,handle){
    if(event.button!==0)return;
    if(event.target.closest('button,input,select,textarea,a,summary,label'))return;
    raise(item);
    const rect=item.el.getBoundingClientRect(),startX=event.clientX,startY=event.clientY;
    freezeLayout(item);
    const limits=area();
    const move=moveEvent=>{
      const x=clamp(rect.left+moveEvent.clientX-startX,limits.left-80,limits.right-80);
      const y=clamp(rect.top+moveEvent.clientY-startY,0,innerHeight-56);
      item.el.style.left=x+'px';item.el.style.top=y+'px';
    };
    const finish=()=>{
      handle.removeEventListener('pointermove',move);
      handle.removeEventListener('pointerup',finish);
      handle.removeEventListener('pointercancel',finish);
      item.el.classList.remove('fw-dragging');
      try{handle.releasePointerCapture(event.pointerId);}catch{}
    };
    item.el.classList.add('fw-dragging');
    try{handle.setPointerCapture(event.pointerId);}catch{}
    handle.addEventListener('pointermove',move);
    handle.addEventListener('pointerup',finish);
    handle.addEventListener('pointercancel',finish);
    event.preventDefault();
  }
  function beginResize(item,event,handle){
    if(event.button!==0)return;
    event.preventDefault();event.stopPropagation();raise(item);
    const rect=item.el.getBoundingClientRect(),startX=event.clientX,startY=event.clientY,limits=area();
    freezeLayout(item);
    item.userSized=true;
    const move=moveEvent=>{
      const width=clamp(rect.width+moveEvent.clientX-startX,MIN_WIDTH,Math.max(MIN_WIDTH,limits.right-rect.left-EDGE));
      const height=clamp(rect.height+moveEvent.clientY-startY,MIN_HEIGHT,Math.max(MIN_HEIGHT,innerHeight-rect.top-EDGE));
      item.el.style.width=width+'px';item.el.style.height=height+'px';
    };
    const finish=()=>{
      handle.removeEventListener('pointermove',move);
      handle.removeEventListener('pointerup',finish);
      handle.removeEventListener('pointercancel',finish);
      try{handle.releasePointerCapture(event.pointerId);}catch{}
      const box=item.el.getBoundingClientRect();
      sizes[item.id]={width:Math.round(box.width),height:Math.round(box.height)};
      item.el.classList.remove('fw-resizing');
      queueSave(item.id);
    };
    item.el.classList.add('fw-resizing');
    try{handle.setPointerCapture(event.pointerId);}catch{}
    handle.addEventListener('pointermove',move);
    handle.addEventListener('pointerup',finish);
    handle.addEventListener('pointercancel',finish);
  }
  function register(id,el,options={}){
    if(!el)return null;
    if(entries.has(id))return entries.get(id);
    ensureLayer();
    el.classList.add('fw');
    el.dataset.windowId=id;
    el.style.right='auto';el.style.bottom='auto';el.style.margin='0';
    if(el.parentElement!==layer)layer.append(el);
    el.hidden=true;
    const item={id,el,options,placed:false,userSized:false,closing:false,order:0};
    const header=options.header?el.querySelector(options.header):el.querySelector('.fw-head,.drawer-head,.controls-head,.dlg-head');
    if(header){header.classList.add('fw-drag');header.addEventListener('pointerdown',event=>beginDrag(item,event,header));}
    let grip=el.querySelector('.fw-resize');
    if(!grip){grip=document.createElement('span');grip.className='fw-resize';grip.title='Redimensionar';grip.setAttribute('aria-hidden','true');el.append(grip);}
    grip.addEventListener('pointerdown',event=>beginResize(item,event,grip));
    el.querySelectorAll('[data-fw-close]').forEach(button=>button.addEventListener('click',()=>close(id)));
    el.addEventListener('pointerdown',()=>raise(item),true);
    el.addEventListener('focusin',()=>raise(item));
    entries.set(id,item);
    return item;
  }
  function open(id){
    const item=entries.get(id);
    if(!item)return false;
    const wasOpen=!item.el.hidden&&!item.closing;
    if(!wasOpen){
      cancelAnim(item.el);
      item.closing=false;item.entering=true;item.el.hidden=false;item.order=++orderCounter;
      raise(item);
      arrange();
      item.entering=false;
      animateIn(item.el);
      item.options.onOpen?.();
      item.el.dispatchEvent(new CustomEvent('fw:open'));
    }else raise(item);
    return true;
  }
  function close(id){
    const item=entries.get(id);
    if(!item||item.el.hidden||item.closing)return false;
    if(item.el.contains(document.activeElement))document.activeElement.blur();
    freezeLayout(item);
    item.closing=true;item.options.onClose?.();
    item.el.dispatchEvent(new CustomEvent('fw:close'));
    arrange();
    animateOut(item.el,()=>{
      if(!item.closing)return;
      item.el.hidden=true;item.closing=false;
    });
    return true;
  }
  function toggle(id){
    const item=entries.get(id);
    if(!item)return false;
    return item.el.hidden||item.closing?open(id):close(id);
  }
  function isOpen(id){return !!entries.get(id)&&!entries.get(id).el.hidden&&!entries.get(id).closing;}
  function closeTop(){
    let best=null,top=-1;
    for(const item of entries.values()){
      if(item.el.hidden||item.closing)continue;
      const value=Number(item.el.style.zIndex)||0;
      if(value>=top){top=value;best=item;}
    }
    return best?close(best.id):false;
  }
  function reconcile(){arrange();}
  function getSize(id){return sizes[id]?{...sizes[id]}:null;}
  function setSize(id,width,height){
    if(!DEFAULTS[id])return;
    if(!Number.isInteger(width)||!Number.isInteger(height))return;
    if(width<160||width>5000||height<160||height>5000)return;
    sizes[id]={width,height};queueSave(id);
  }
  function setWindowAnimations(value){
    animateWindows=!!value;
    try{localStorage.setItem('valWindowAnimations',animateWindows?'1':'0');}catch{}
    if(!animateWindows)for(const item of entries.values()){cancelAnim(item.el);cancelLayout(item.el);}
  }
  function queueSave(id){dirtySizes.add(id);clearTimeout(saveTimer);saveTimer=setTimeout(flush,420);}
  function flush(){
    clearTimeout(saveTimer);saveTimer=0;
    if(!prefsLoaded){needsSave=true;return;}
    if(saving){saveAgain=true;return;}
    const map={};
    for(const id of dirtySizes){
      const box=sizes[id];
      if(!DEFAULTS[id])continue;
      if(!Number.isInteger(box.width)||!Number.isInteger(box.height))continue;
      map[id]={width:box.width,height:box.height};
    }
    if(!Object.keys(map).length)return;
    for(const id of Object.keys(map))dirtySizes.delete(id);
    saving=true;
    fetch('/api/harness/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({windows:map})})
      .then(response=>{if(!response.ok)throw new Error('No se pudo guardar el tamaño.');return response.json();})
      .then(()=>{saving=false;retried=false;if(saveAgain){saveAgain=false;flush();}})
      .catch(()=>{for(const id of Object.keys(map))dirtySizes.add(id);saving=false;if(!retried){retried=true;setTimeout(()=>{saveAgain=false;flush();},1600);}});
  }
  function loadSizes(){
    fetch('/api/harness/preferences',{cache:'no-store'})
      .then(response=>response.ok?response.json():null)
      .then(data=>{
        const boxes=data&&data.windows;
        if(boxes&&typeof boxes==='object')for(const [id,box] of Object.entries(boxes)){
          if(!DEFAULTS[id]||!box||dirtySizes.has(id))continue;
          if(!Number.isInteger(box.width)||!Number.isInteger(box.height))continue;
          if(box.width<160||box.width>5000||box.height<160||box.height>5000)continue;
          sizes[id]={width:box.width,height:box.height};
        }
      })
      .catch(()=>{})
      .finally(()=>{
        prefsLoaded=true;
        arrange();
        if(needsSave){needsSave=false;flush();}
      });
  }
  window.VALWindows={register,open,close,toggle,isOpen,closeTop,raise,reconcile,arrange:scheduleArrange,getSize,setSize,setWindowAnimations,load:loadSizes};
  for(const [id,element] of [['settings',document.getElementById('drawer')],['model',document.getElementById('composerControls')],['tools',document.getElementById('toolsWindow')],['console',document.getElementById('consoleWindow')]])register(id,element);
  window.addEventListener('resize',scheduleArrange);
  window.addEventListener('val:browser-layout',scheduleArrange);
  loadSizes();
})();
