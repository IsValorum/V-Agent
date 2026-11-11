/* One motion policy for menu geometry; never observes streamed chat text. */
(()=>{
  const reduce=matchMedia('(prefers-reduced-motion: reduce)'),running=new WeakMap(),original=new WeakMap(),targets=new WeakMap();
  const timing={duration:620,easing:'cubic-bezier(.4,0,.2,1)'};
  function setDuration(value){const duration=Number(value);if(!Number.isInteger(duration)||duration<100||duration>1600)return;timing.duration=duration;document.documentElement.style.setProperty('--motion-duration',duration+'ms');}
  const visibility=new WeakMap();
  function cancelVisibility(el){const old=visibility.get(el);visibility.delete(el);old?.cancel();}
  // Glass menus skip live blur while they animate (see floating-windows.js); blur returns when still.
  function settle(el,motion){el.dataset.motion='1';const done=()=>setTimeout(()=>{if(visibility.get(el)!==motion||motion.playState==='finished')delete el.dataset.motion;},0);if(typeof motion.addEventListener==='function'){motion.addEventListener('finish',done);motion.addEventListener('cancel',done);}else motion.finished?.then?.(done,done);}
  function showPopover(el){
    const visible=el.matches(':popover-open'),closing=el.dataset.motionClosing==='true';
    if(visible&&!closing)return;
    const current=visible?getComputedStyle(el):null;
    const offset=el.dataset.side==='below'?'translateY(-8px)':'translateY(10px)';
    const from=visible?{opacity:current.opacity,transform:current.transform}:{opacity:0,transform:offset};
    cancelVisibility(el);delete el.dataset.motionClosing;
    if(!visible)el.showPopover();
    if(reduce.matches||!el.animate)return;
    const motion=el.animate([from,{opacity:1,transform:'translateY(0)'}],timing);visibility.set(el,motion);
    motion.onfinish=()=>{if(visibility.get(el)===motion)visibility.delete(el);};
    settle(el,motion);
  }
  function hidePopover(el,finished=()=>{},immediate=false){
    if(!el.matches(':popover-open')){finished();return;}
    if(el.dataset.motionClosing==='true'&&!immediate)return;
    const current=getComputedStyle(el),from={opacity:current.opacity,transform:current.transform};
    cancelVisibility(el);
    const finish=()=>{delete el.dataset.motionClosing;if(el.matches(':popover-open'))el.hidePopover();finished();};
    if(immediate||reduce.matches||!el.animate){finish();return;}
    el.dataset.motionClosing='true';
    const motion=el.animate([from,{opacity:0,transform:el.dataset.side==='below'?'translateY(-8px)':'translateY(10px)'}],timing);visibility.set(el,motion);settle(el,motion);
    motion.onfinish=()=>{if(visibility.get(el)!==motion)return;visibility.delete(el);finish();};
  }
  window.VALMotion={showPopover,hidePopover,setDuration};
  function stop(el){
    const motion=running.get(el);if(!motion)return;
    running.delete(el);motion.cancel();el.style.overflow=original.get(el)??'';original.delete(el);
  }
  function resize(el,start,end,finish){
    stop(el);
    if(reduce.matches||!el.animate||Math.abs(end-start)<1){finish?.();return;}
    const previous=el.style.overflow;original.set(el,previous);el.style.overflow='hidden';
    const motion=el.animate([{height:start+'px'},{height:end+'px'}],timing);running.set(el,motion);
    motion.onfinish=()=>{if(running.get(el)!==motion)return;el.style.overflow=previous;running.delete(el);original.delete(el);finish?.();};
    motion.oncancel=()=>{if(running.get(el)!==motion)return;el.style.overflow=previous;running.delete(el);original.delete(el);};
  }
  document.addEventListener('click',event=>{
    const summary=event.target.closest('summary');
    if(summary&&summary.parentElement.matches('#drawer details,#composerControls details,#chat details,#engineMetrics,#engineMetrics details')&&!reduce.matches){
      if(event.defaultPrevented)return;
      event.preventDefault();
      const details=summary.parentElement,start=details.getBoundingClientRect().height;
      const next=!(targets.get(details)??details.open);targets.set(details,next);
      stop(details);details.open=true;
      const end=next?details.getBoundingClientRect().height:summary.getBoundingClientRect().height;
      resize(details,start,end,()=>{details.open=next;targets.delete(details);});return;
    }
  },true);
})();
