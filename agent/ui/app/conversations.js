/* ---------- conversaciones ---------- */
function selectedConversation() {
  return convs.find(chat => chat.id === currentId);
}
async function openConversationSandbox(){
  if(!currentId){note(uiText('Envía un mensaje para crear la conversación y su carpeta.'));return;}
  try{await flushSessionSaves();const native=!!window.__TAURI__?.core?.invoke;const id=currentId;await requestJSON('/api/workspace/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:id,prepare_only:native})});if(native)await window.__TAURI__.core.invoke('open_sandbox_folder',{conversationId:id});}
  catch(error){note(uiText(typeof error==='string'?error:(error?.message||String(error))));}
}
$('#openSandbox').onclick=openConversationSandbox;
function syncWorkspacePath() {
  const root = pcAccess.workspaces || pcAccess.root + "\\conversations";
  $("#sandboxPath").textContent = currentId ? uiText("Sandbox de este chat")+": "+root+"\\"+currentId+(selectedProjectChat===currentId&&selectedProject?" · "+uiText("Proyecto activo")+": "+selectedProject.path:"") : uiText("La carpeta se crea al enviar el primer mensaje.");
  $("#sandboxPath").hidden = false;
}
async function refreshProjectAssignments(){
  try{
    const data=await requestJSON('/api/projects');
    projectAssignments=data.conversations||{};
    projectNames=Object.fromEntries((data.projects||[]).map(project=>[project.id,project]));
    renderConvs();
  }catch{}
}
document.addEventListener('input',event=>{if(event.target?.id==='convSearch')renderConvs();});
function renderConvs() {
  const box = $("#convs"), current = selectedConversation();
  const wasOpen = $("#archivedChats")?.open;
  // Title search, shown once the list is long enough to need it; accents and case are ignored.
  const fold=text=>String(text||'').normalize('NFD').replace(/\p{Diacritic}/gu,'').toLocaleLowerCase();
  const search=$('#convSearch');if(search){search.hidden=convs.length<=5&&!search.value;}
  const query=fold(search?.value.trim());
  const sorted = [...convs].sort((a, b) => b.ts - a.ts).filter(chat=>!query||fold(chat.title==='Nuevo chat'?uiText('Nuevo chat'):chat.title).includes(query));
  const active = sorted.filter(chat => !chat.archived);
  const archived = sorted.filter(chat => chat.archived);
  const row = chat => {
    const el = document.createElement("div");
    el.className = "conv" + (chat.id === currentId ? " active" : "");
    el.innerHTML = '<span class="t"></span><button class="conv-more" type="button" aria-haspopup="menu" aria-label="Opciones de la conversación">⋯</button>';
    el.querySelector(".t").textContent = chat.title==='Nuevo chat'?uiText('Nuevo chat'):(chat.title || uiText("Sin título"));
    el.setAttribute("tabindex", "0");
    el.setAttribute("role", "button");
    el.setAttribute("aria-label", chat.title==='Nuevo chat'?uiText('Nuevo chat'):(chat.title || uiText("Sin título")));
    el.setAttribute("aria-current", String(chat.id === currentId));
    el.onclick = () => openConv(chat.id);
    el.onkeydown = event => {
      if (event.target === el && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        openConv(chat.id);
      }
    };
    const more=el.querySelector('.conv-more');more.setAttribute('aria-label',uiText('Opciones de la conversación'));more.onclick = event => { event.stopPropagation(); showConvMenu(event.currentTarget,chat); };
    return el;
  };
  const groups=new Map(),normal=[];
  for(const chat of active){
    const project=projectNames[projectAssignments[chat.id]];
    if(project){if(!groups.has(project.id))groups.set(project.id,[]);groups.get(project.id).push(chat);}
    else normal.push(chat);
  }
  // Projects live in their own section: one compact row each (chats inside when expanded). With no
  // project the section is just its title and a "+", so it costs a single line.
  const projectsNav=document.getElementById('projectsNav');
  if(projectsNav){
    const openIds=new Set([...projectsNav.querySelectorAll('details[open]')].map(item=>item.dataset.project));
    const projects=Object.values(projectNames).sort((a,b)=>(a.name||'').localeCompare(b.name||''));
    projectsNav.replaceChildren(...projects.map(project=>{
      const chats=groups.get(project.id)||[];
      const item=document.createElement('details');item.className='project-entry';item.dataset.project=project.id;
      item.open=openIds.has(project.id)||chats.some(chat=>chat.id===currentId);
      const head=document.createElement('summary');head.title=project.path;
      head.innerHTML='<svg class="project-folder" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h7l2 2h9v11H3V7Zm0 0V4h7l2 3"/></svg><span class="project-name"></span><span class="project-count"></span>';
      head.querySelector('.project-name').textContent=project.name;head.querySelector('.project-count').textContent=chats.length||'';
      const add=document.createElement('button');add.type='button';add.className='project-new';add.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
      add.title=uiText('Nuevo chat en este proyecto');add.setAttribute('aria-label',add.title);
      add.onclick=event=>{event.preventDefault();event.stopPropagation();startProjectChat(project);};
      const more=document.createElement('button');more.type='button';more.className='conv-project-more';more.textContent='⋯';more.setAttribute('aria-label',uiText('Opciones del proyecto'));more.setAttribute('aria-haspopup','menu');
      more.onclick=event=>{event.preventDefault();event.stopPropagation();showProjectMenu(more,project);};
      head.append(add,more);item.append(head);
      const list=document.createElement('div');list.className='project-chats';
      if(chats.length)list.append(...chats.map(row));
      else{const empty=document.createElement('div');empty.className='history-empty';empty.textContent=uiText('Sin chats');list.append(empty);}
      item.append(list);return item;
    }));
    projectsNav.hidden=!projects.length;
  }
  box.replaceChildren(...normal.map(row));
  $("#convCount").textContent = normal.length;
  $("#chatTitle").textContent = (current?.title==='Nuevo chat'?uiText('Nuevo chat'):current?.title) || uiText("Nuevo chat");
  if (!normal.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = uiText(archived.length ? "Sin chats activos" : "Sin chats");
    box.append(empty);
  }
  if (archived.length) {
    const folder = document.createElement("details"), title = document.createElement("summary");
    folder.id = "archivedChats";
    folder.open = Boolean(wasOpen || current?.archived);
    title.textContent = uiText("Archivados") + " · " + archived.length;
    folder.append(title, ...archived.map(row));
    box.append(folder);
  }
  syncWorkspacePath();
}
async function exportConversation(chat){
  if(!chat)return;
  const data={type:'strata-conversation',version:1,conversation:chat};
  const title=(chat.title||'chat').replace(/[^\p{L}\p{N}_-]+/gu,'-').slice(0,70);
  try{await downloadToolDraft('strata-'+title+'.json',JSON.stringify(data,null,2),'application/json');}
  catch(error){note(uiText(typeof error==='string'?error:(error?.message||String(error))));}
}
function archiveConversation(chat){
  if(!chat||busy)return;
  chat.archived=!chat.archived;saveConvsLS();renderConvs();
  note(uiText(chat.archived?'Chat archivado.':'Chat restaurado.'));
}
async function removeProject(project){
  if(!project)return;
  if(!await valConfirm({title:'¿Quitar este proyecto de V-Agent?',message:'Los archivos del proyecto no se borran.',confirm:'Quitar'}))return;
  try{
    const data=await requestJSON('/api/projects/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:project.id})});
    projectAssignments=data.conversations||{};projectNames=Object.fromEntries((data.projects||[]).map(item=>[item.id,item]));
    if(selectedProject?.id===project.id){selectedProject=null;selectedProjectChat=currentId;const btn=document.getElementById('projectBtn');if(btn){btn.querySelector('span').textContent=uiText('Sin proyecto');btn.dataset.selected='false';btn.title=uiText('Carpeta independiente de esta conversación');}}
    renderConvs();document.getElementById('closeProject')?.click();note(uiText('Proyecto quitado.'));
  }catch(error){note(error.message);}
}
function setupConvMenus(){
  const menu=document.createElement('div');menu.id='convMenu';menu.className='agent-small-menu conv-menu';menu.setAttribute('popover','manual');menu.setAttribute('role','menu');
  const icons={archive:'M4 7h16M5 7v13h14V7M3 3h18v4H3ZM9 12h6',export:'M12 3v12m-4-4 4 4 4-4M5 16v5h14v-5',delete:'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6m4-6v6'};
  for(const [action,label] of [['archive','Archivar'],['export','Exportar'],['delete','Borrar']]){const button=document.createElement('button');button.type='button';button.dataset.action=action;button.setAttribute('role','menuitem');button.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+icons[action]+'"/></svg><span></span>';button.querySelector('span').textContent=uiText(label);menu.append(button);}
  document.body.append(menu);
  const projectMenu=document.createElement('div');projectMenu.id='projectMenu';projectMenu.className='agent-small-menu conv-menu';projectMenu.setAttribute('popover','manual');projectMenu.setAttribute('role','menu');
  const projectRemove=document.createElement('button');projectRemove.type='button';projectRemove.setAttribute('role','menuitem');projectRemove.textContent=uiText('Quitar proyecto');projectMenu.append(projectRemove);document.body.append(projectMenu);
  document.addEventListener('pointerdown',event=>{for(const id of ['convMenu','projectMenu']){const item=document.getElementById(id);if(item?.matches(':popover-open')&&!event.target.closest('#'+id+',.conv-more,.conv-project-more'))window.VALMotion.hidePopover(item);}});
  document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;for(const id of ['convMenu','projectMenu']){const item=document.getElementById(id);if(item?.matches(':popover-open'))window.VALMotion.hidePopover(item);}});
  menu.querySelector('[data-action=delete]').onclick=()=>{window.VALMotion.hidePopover(menu);if(convMenuChat)delConv(convMenuChat.id);};
  menu.querySelector('[data-action=archive]').onclick=()=>{window.VALMotion.hidePopover(menu);if(convMenuChat)archiveConversation(convMenuChat);};
  menu.querySelector('[data-action=export]').onclick=()=>{window.VALMotion.hidePopover(menu);if(convMenuChat)exportConversation(convMenuChat);};
  projectRemove.onclick=()=>{window.VALMotion.hidePopover(projectMenu);if(projectMenuProject)removeProject(projectMenuProject);};
  return {menu,projectMenu,projectRemove};
}
let convMenuChat=null,projectMenuProject=null,chatTrail=[],chatTrailCursor=-1;
function syncChatTrail(){
  const back=document.getElementById('chatBack'),forward=document.getElementById('chatForward');
  if(back)back.disabled=chatTrailCursor<=0;
  if(forward)forward.disabled=chatTrailCursor<0||chatTrailCursor>=chatTrail.length-1;
}
async function navigateChat(step){
  const next=chatTrailCursor+step;
  if(next<0||next>=chatTrail.length)return;
  chatTrailCursor=next;
  await openConv(chatTrail[next],false);
  syncChatTrail();
}
function showConvMenu(anchor,chat){
  convMenuChat=chat;const menu=document.getElementById('convMenu');if(!menu)return;if(menu.matches(':popover-open'))window.VALMotion.hidePopover(menu);
  const archive=menu.querySelector('[data-action=archive]');if(archive)archive.querySelector('span').textContent=uiText(chat.archived?'Restaurar':'Archivar');
  showAgentMenu(menu,anchor);
}
function startProjectChat(project){
  if(busy){note(uiText('Espera a que termine la respuesta para abrir otra conversación.'));return;}
  newConv();window.__chooseProject?.({project_id:project.id});
}
function showProjectMenu(anchor,project){
  projectMenuProject=project;const menu=document.getElementById('projectMenu');if(!menu)return;if(menu.matches(':popover-open'))window.VALMotion.hidePopover(menu);showAgentMenu(menu,anchor);
}
async function openConv(id,remember=true) {
  if (busy) { note(uiText("Espera a que termine la respuesta para cambiar de conversación.")); return; }
  if(conflictedSessions.has(id)){try{const data=await requestJSON('/api/v1/sessions');const saved=data.sessions.find(c=>c.id===id);if(!saved)throw new Error('El chat ya no está disponible.');const idx=convs.findIndex(c=>c.id===id);if(idx>=0)convs[idx]=saved;else convs.unshift(saved);savedSessionBodies.set(id,JSON.stringify(sessionBody(saved)));conflictedSessions.delete(id);}catch(error){note(error.message);return;}}
  setSidebar(false); attachments = []; renderAttachments();
  const c = convs.find((x) => x.id === id); if (!c) return;
  if(remember&&chatTrail[chatTrailCursor]!==id){chatTrail=chatTrail.slice(0,chatTrailCursor+1);chatTrail.push(id);chatTrailCursor=chatTrail.length-1;syncChatTrail();}
  currentId = id; messages = JSON.parse(JSON.stringify(c.messages || []));
  renderChat(); renderConvs();syncProjectButton();
}
async function delConv(id) {
  if (busy) { note(uiText("Espera a que termine la respuesta para borrar una conversación.")); return; }
  if (!await valConfirm({title:'¿Borrar esta conversación?',message:'Se eliminará de este equipo y no se puede deshacer. Si solo quieres ocultarla, usa Archivar.',confirm:'Borrar',danger:true})) return;
  if(sessionsReady){try{await flushSessionSaves();const chat=convs.find(c=>c.id===id);if(chat)await requestJSON('/api/v1/sessions/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,revision:chat.revision??0})});}catch(error){note(error.message);return;}}
  pendingSessionSaves.delete(id);savedSessionBodies.delete(id);
  convs = convs.filter((c) => c.id !== id);delete projectAssignments[id];
  if(currentId===id){chatTrail=[];chatTrailCursor=-1;syncChatTrail();}
  if (currentId === id) { currentId = null; messages = []; $("#chat").innerHTML = ""; }
  saveConvsLS(); renderConvs(); renderChat();
}
function newConv() {
  if (busy) { note(uiText("Espera a que termine la respuesta para abrir otra conversación.")); return; }
  currentId = null; messages = []; attachments = []; renderAttachments();selectedProject=null;selectedProjectChat=null;
  chatTrail=[];chatTrailCursor=-1;syncChatTrail();
  const project=$('#projectBtn');if(project){project.querySelector('span').textContent=uiText('Sin proyecto');project.dataset.selected='false';project.title=uiText('Carpeta independiente de esta conversación');}
  if(pcAccess.mode==='sandbox')$('#accessStatus').textContent=uiText('Archivos limitados a la carpeta de este chat. Comandos bloqueados.');
  renderChat(); renderConvs();syncProjectButton();
  $("#input").value = ""; resizeInput(); setSidebar(false); $("#input").focus();
}
function applySidebarCollapsed(value){
  const collapsed=Boolean(value);document.body.classList.toggle('sidebar-collapsed',collapsed);
  try{localStorage.setItem('valSidebarCollapsed',collapsed?'1':'0');}catch{}
  const toggle=document.getElementById('sidebarToggle');if(toggle){toggle.setAttribute('aria-label',uiText(collapsed?'Mostrar barra lateral':'Ocultar barra lateral'));toggle.title='';}
}
function setupSidebarChrome(){
  const toggle=document.getElementById('sidebarToggle'),reopen=document.getElementById('sidebarReopen');
  toggle?.addEventListener('click',()=>applySidebarCollapsed(true));
  reopen?.addEventListener('click',()=>applySidebarCollapsed(false));
  document.getElementById('chatBack')?.addEventListener('click',()=>navigateChat(-1));
  document.getElementById('chatForward')?.addEventListener('click',()=>navigateChat(1));
  try{applySidebarCollapsed(localStorage.getItem('valSidebarCollapsed')==='1');}catch{applySidebarCollapsed(false);}
  syncChatTrail();
  const resizer=document.getElementById('sidebarResizer'),sidebar=document.getElementById('sidebar');
  if(resizer&&sidebar){
    let startX=0,startWidth=0,dragging=false,lastWidth=0;
    const widthAt=(event)=>Math.max(200,Math.min(340,Math.round(startWidth+event.clientX-startX)));
    const stop=()=>{if(!dragging)return;dragging=false;resizer.classList.remove('dragging');document.body.style.cursor='';document.body.style.userSelect='';TH[TH.mode].sidebarWidth=lastWidth;const range=document.getElementById('t_sidebarWidth');if(range)range.value=lastWidth;applyTheme();};
    resizer.addEventListener('pointerdown',event=>{if(bodyClassCollapsed())return;event.preventDefault();startX=event.clientX;startWidth=sidebar.getBoundingClientRect().width;lastWidth=startWidth;dragging=true;resizer.classList.add('dragging');resizer.setPointerCapture(event.pointerId);document.body.style.cursor='col-resize';document.body.style.userSelect='none';});
    resizer.addEventListener('pointermove',event=>{if(!dragging)return;lastWidth=widthAt(event);document.documentElement.style.setProperty('--sidebar-width',lastWidth+'px');});
    resizer.addEventListener('pointerup',stop);resizer.addEventListener('pointercancel',stop);
    resizer.addEventListener('dblclick',()=>{lastWidth=246;document.documentElement.style.setProperty('--sidebar-width','246px');TH[TH.mode].sidebarWidth=246;applyTheme();});
    resizer.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();let width=TH[TH.mode].sidebarWidth||246;if(event.key==='ArrowLeft')width-=8;else if(event.key==='ArrowRight')width+=8;else if(event.key==='Home')width=200;else width=340;width=Math.max(200,Math.min(340,width));document.documentElement.style.setProperty('--sidebar-width',width+'px');TH[TH.mode].sidebarWidth=width;applyTheme();});
  }
  const widthRow=document.getElementById('t_sidebarWidth');if(widthRow)widthRow.closest('.row')?.setAttribute('hidden','hidden');
}
function bodyClassCollapsed(){return document.body.classList.contains('sidebar-collapsed');}
function persistConv() {
  if (!messages.length) return;
  const firstUser = messages.find((m) => m.role === "user");
  const title = (firstUser ? userMessageRawText(firstUser) : "Conversación").replace(/\[Adjuntos\][\s\S]*/, "").slice(0, 48) || "Conversación";
  if (!currentId) { currentId = crypto.randomUUID(); convs.push({ id: currentId, title, ts: Date.now(), messages: [] }); }
  const c = convs.find((x) => x.id === currentId);
  if (c) { if(c.title==='Nuevo chat')c.title=title; c.messages = JSON.parse(JSON.stringify(messages)); c.ts = Date.now();if(messages.at(-1)?.run_id)c.last_run=messages.at(-1).run_id; }
  saveConvsLS(); renderConvs();
}
