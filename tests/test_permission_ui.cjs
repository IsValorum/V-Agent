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
 console.log('Profiles preserve access, approvals and tool selection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
