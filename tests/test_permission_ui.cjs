const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('agent/ui/app/shell.js','utf8');
const begin=source.indexOf('async function setAgentMode('),end=source.indexOf('function setupAgentModeSeat()',begin);
assert(begin>=0&&end>begin);
const calls=[];
const context={AGENT_MODES:{light:{},balanced:{},advanced:{}},busy:false,engineBusy:false,
 S:{agentProfile:'balanced',permissionMode:'ask',functions:{shell:false,computer:false,admin:true}},
 pcAccess:{mode:'sandbox'},showAgentModeWarning:async()=>true,saveSettings(){},syncFunctionControls(){},
 syncServerSwitches(){},syncAgentControls(){},syncAgentModeSeat(){},syncAccessControls(){},
 presupuestoFirmado:'',consultarPresupuesto(){},note(){},AbortSignal:{timeout(){return null;}},requestJSON:async(url)=>{calls.push(url);return{};}};
vm.createContext(context);vm.runInContext(source.slice(begin,end),context);
(async()=>{
 const original=JSON.stringify(context.S.functions);
 await context.setAgentMode('advanced',{silent:true});
 assert.equal(context.pcAccess.mode,'sandbox');assert.equal(context.S.permissionMode,'ask');
 assert.equal(JSON.stringify(context.S.functions),original);assert(!calls.includes('/api/harness/admin/start'));
 context.pcAccess.mode='full_pc';context.S.permissionMode='auto';
 await context.setAgentMode('light',{silent:true});
 assert.equal(context.pcAccess.mode,'full_pc');assert.equal(context.S.permissionMode,'auto');
 assert.equal(JSON.stringify(context.S.functions),original);
 const settingsSource=fs.readFileSync('agent/ui/app/settings.js','utf8');
 const uBegin=settingsSource.indexOf('function updateToolCount()'),uEnd=settingsSource.indexOf('function pintarPresupuesto(',uBegin);
 assert(uBegin>=0&&uEnd>uBegin);
 let displayedCount='';
 const sCtx={S:{agentProfile:'advanced',functions:{files:true,search:true,visit:true,sys:true,shell:true,hf:false,browser:true,console:true,web:true,autobrowser:true,computer:true,admin:true}},
  pcAccess:{mode:'full_pc',isolation:{available:true}},presupuestoFirmado:'',lastToolBudget:null,presupuestoTimer:null,
  $:sel=>({set textContent(v){if(sel==='#toolCount')displayedCount=String(v);}}),uiText:s=>s,clearTimeout(){},setTimeout(){}};
 vm.createContext(sCtx);vm.runInContext(settingsSource.slice(uBegin,uEnd),sCtx);
 sCtx.updateToolCount();
 assert.equal(displayedCount,'53');
 sCtx.lastToolBudget={tools:53};
 sCtx.updateToolCount();
 assert.equal(displayedCount,'53');
 console.log('Profiles preserve access, approvals and tool selection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
