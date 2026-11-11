let sessionsReady=false,sessionFlush=null,sessionTimer=null;
const pendingSessionSaves=new Map(),savedSessionBodies=new Map(),conflictedSessions=new Set();
function sessionBody(chat){const value=structuredClone(chat);delete value.revision;return value;}
function queueSessionSaves(){
  if(!sessionsReady)return;
  // Every edit here belongs to the selected chat. Do not clone the entire archive.
  for(const chat of currentId?[selectedConversation()].filter(Boolean):[]){
    if(conflictedSessions.has(chat.id))continue;
    const text=JSON.stringify(sessionBody(chat));
    if(savedSessionBodies.get(chat.id)!==text)pendingSessionSaves.set(chat.id,sessionBody(chat));
  }
  clearTimeout(sessionTimer);sessionTimer=setTimeout(()=>flushSessionSaves().catch(error=>note('Guardado pendiente; mantén la pestaña abierta. '+error.message)),250);
}
async function flushSessionSaves(){
  clearTimeout(sessionTimer);
  if(sessionFlush){await sessionFlush;if(pendingSessionSaves.size)return flushSessionSaves();return;}
  sessionFlush=(async()=>{
    while(pendingSessionSaves.size){
      const [id,body]=pendingSessionSaves.entries().next().value;pendingSessionSaves.delete(id);
      const local=convs.find(c=>c.id===id);if(!local)continue;
      try{
        const result=await requestJSON('/api/v1/sessions/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session:body,revision:local.revision??0})});
        local.revision=result.session.revision;savedSessionBodies.set(id,JSON.stringify(body));
      }catch(error){if(error.status===409){conflictedSessions.add(id);note(error.message);continue;}pendingSessionSaves.set(id,body);throw error;}
    }
  })();
  try{await sessionFlush;}finally{sessionFlush=null;}
}
$('#exportSessions').onclick=async()=>{try{await flushSessionSaves();const data=await requestJSON('/api/v1/sessions');downloadToolDraft('strata-historial.json',JSON.stringify({version:1,sessions:data.sessions},null,2));}catch(error){note(error.message);}};
$('#importSessions').onclick=()=>$('#sessionsFile').click();
$('#sessionsFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{const value=JSON.parse(await file.text());const sessions=Array.isArray(value)?value:value.sessions||[value.conversation||value];const result=await requestJSON('/api/v1/sessions/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sessions})});convs=result.sessions;savedSessionBodies.clear();for(const chat of convs)savedSessionBodies.set(chat.id,JSON.stringify(sessionBody(chat)));renderConvs();note(result.errors?.length?'Importación parcial; la copia original se conserva en disco.':'Historial importado sin sobrescribir conversaciones existentes.');}catch(error){note(error.message);}finally{event.target.value='';}};

async function restoreLocalSessions(){
  try{
    const localCopy=structuredClone(convs);if(localCopy.length&&!readStorage('strataBrowserBackupV1',null))writeStorage('strataBrowserBackupV1',localCopy);
    let data=await requestJSON('/api/v1/sessions');
    const migrationKey='strataDiskSessionMigrationV1';
    if(localCopy.length&&!readStorage(migrationKey,false)){
      data=await requestJSON('/api/v1/sessions/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sessions:localCopy})});
      if(data.errors?.length){note('Algunos chats no se importaron. La copia del navegador se conserva.');}
      else writeStorage(migrationKey,true);
    }
    convs=data.sessions||[];
    for(const chat of convs)savedSessionBodies.set(chat.id,JSON.stringify(sessionBody(chat)));
    sessionsReady=true;
  }catch(error){note('No se pudo abrir el historial del disco. Se conserva la copia del navegador.');}
}
addEventListener('pagehide',()=>{
  if(!sessionsReady)return;
  for(const [id,body] of pendingSessionSaves){const chat=convs.find(c=>c.id===id);if(chat)navigator.sendBeacon('/api/v1/sessions/save',new Blob([JSON.stringify({session:body,revision:chat.revision??0})],{type:'application/json'}));}
});
