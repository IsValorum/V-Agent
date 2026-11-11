const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const media={matches:false},context={window:{},document:{addEventListener(){},documentElement:{style:{setProperty(key,value){this[key]=value;}}}},matchMedia:()=>media,requestAnimationFrame:f=>f(),getComputedStyle:e=>({opacity:e.opacity,transform:'none'})};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../agent/ui/standalone/motion.js'),'utf8'),context);
const api=context.window.VALMotion;
function element(){return {open:false,dataset:{},style:{},opacity:'1',animations:[],matches(){return this.open;},showPopover(){this.open=true;},hidePopover(){this.open=false;},animate(frames,timing){const animation={frames,timing,cancel(){this.cancelled=true;}};this.animations.push(animation);return animation;}};}
let e=element(),closed=0;
api.showPopover(e);assert(e.open);assert.equal(e.animations[0].timing.duration,620);
api.hidePopover(e,()=>closed++);assert(e.open,'Keep popover visible for its exit animation');assert.equal(closed,0);assert.equal(e.dataset.motionClosing,'true');
e.animations.at(-1).onfinish();assert(!e.open);assert.equal(closed,1);
e=element();closed=0;api.showPopover(e);api.hidePopover(e,()=>closed++);const staleExit=e.animations.at(-1);
api.showPopover(e);staleExit.onfinish();assert(e.open,'Old exit must not hide a reopened menu');assert.equal(closed,0);assert(!e.dataset.motionClosing);
api.hidePopover(e,()=>closed++);api.hidePopover(e,()=>closed++,true);assert(!e.open);assert.equal(closed,1);
api.setDuration(1000);e=element();api.showPopover(e);assert.equal(e.animations[0].timing.duration,1000);assert.equal(context.document.documentElement.style['--motion-duration'],'1000ms');api.setDuration(-1);e=element();api.showPopover(e);assert.equal(e.animations[0].timing.duration,1000);
media.matches=true;e=element();api.showPopover(e);assert(e.open);assert.equal(e.animations.length,0);api.hidePopover(e);assert(!e.open);
console.log('Menu entry/exit, interrupted closing and reduced motion passed.');
