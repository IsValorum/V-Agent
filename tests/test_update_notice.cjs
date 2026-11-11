const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('agent/ui/app/core-connection.js','utf8');
const watch=source.slice(source.indexOf('async function watchAutomaticUpdates'));
const elements=[],events=[];
function element(tag){return {tag,hidden:false,dataset:{},children:[],setAttribute(){},append(...items){this.children.push(...items)}};}
let timers=0,opened=false;
const context={document:{createElement:element,body:{append(node){elements.push(node)}},dispatchEvent(event){events.push(event)},getElementById(){return null}},
  CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail}},
  setTimeout(fn){if(timers++)throw new Error('stop test');fn()},loadUiPatch(){}};
vm.createContext(context);vm.runInContext(watch,context);
const requestJSON=async path=>{if(path.endsWith('/components'))throw new Error('components offline');return {checked_at:1,available:{version:'1.2.3'},ready:null,busy:false};};
context.watchAutomaticUpdates({requestJSON,uiText:x=>x,note(){},setDrawer(){opened=true},selectSettingsCategory(){}}).catch(error=>{
  assert.equal(error.message,'stop test');
  const notice=elements[0];assert.equal(notice.hidden,false);assert.equal(notice.dataset.version,'1.2.3');
  assert.equal(events[0].detail.available.version,'1.2.3');notice.children[2].onclick();assert(opened);
  notice.children[3].onclick();assert.equal(notice.hidden,true);
  console.log('Signed app update is visible, opens settings and can be dismissed.');
});
