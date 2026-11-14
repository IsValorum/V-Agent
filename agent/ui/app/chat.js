/* ---------- chat ---------- */

const chatView = $("#chat");
let followStream = true, programScrollTop = null, selectingChat = false;
let scrollIntent=0,scrollIntentUntil=0,touchScrollY=null;
function userScrollIntent(direction){scrollIntent=direction;scrollIntentUntil=performance.now()+700;if(direction<0)setFollow(false);}
chatView.dataset.follow = "true";
function chatHasSelection(root=chatView) {
  const selection = window.getSelection();
  return Boolean(selection && !selection.isCollapsed &&
    (root.contains(selection.anchorNode) || root.contains(selection.focusNode)));
}
function nearBottom(chat) { return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 40; }
function setFollow(value) {
  followStream = value;
  chatView.dataset.follow = String(value);
  $("#followBtn").classList.toggle("show", busy && messages.length>0 && !value && !nearBottom(chatView));
}
function scrollDown(force=false) {
  if (!force) {
    if (chatHasSelection()) setFollow(false);
    if (selectingChat || !followStream) {
      if (!followStream) setFollow(false);
      return;
    }
  }
  const target = chatView.scrollHeight - chatView.clientHeight;
  if (target <= 0 || Math.abs(chatView.scrollTop - target) < 1) return;
  chatView.scrollTop = target;
  programScrollTop = chatView.scrollTop;
}
chatView.addEventListener("scroll", () => {
  const snapped = programScrollTop !== null && Math.abs(chatView.scrollTop - programScrollTop) < 1;
  programScrollTop = null;
  if (chatHasSelection() || selectingChat) setFollow(false);
  else if (!snapped && scrollIntent>0 && performance.now()<scrollIntentUntil && nearBottom(chatView)) setFollow(true);
  else if (!snapped && chatView.scrollHeight - chatView.scrollTop - chatView.clientHeight > 120) setFollow(false);
});
chatView.addEventListener("wheel", event => {
  const nested=event.target.closest('pre');
  if(event.deltaY>0&&nested&&nested.scrollHeight-nested.scrollTop-nested.clientHeight>1)return;
  if(event.deltaY)userScrollIntent(Math.sign(event.deltaY));
  if (chatHasSelection()) setFollow(false);
  else if (event.deltaY>0 && nearBottom(chatView)) setFollow(true);
}, {passive:true});
chatView.addEventListener('touchstart',event=>{touchScrollY=event.touches[0]?.clientY??null;},{passive:true});
chatView.addEventListener('touchmove',event=>{const y=event.touches[0]?.clientY;if(touchScrollY!==null&&y!==undefined&&Math.abs(y-touchScrollY)>1)userScrollIntent(Math.sign(touchScrollY-y));touchScrollY=y??null;},{passive:true});
chatView.addEventListener('touchend',()=>{touchScrollY=null;},{passive:true});
chatView.addEventListener("keydown", event => { if (["PageUp","Home","ArrowUp"].includes(event.key)) userScrollIntent(-1);else if(['PageDown','End','ArrowDown'].includes(event.key))userScrollIntent(1); });
chatView.addEventListener("pointerdown", event => {
  if (event.pointerType === "mouse" && event.button === 0 && !event.target.closest("button,a,input,textarea,summary")) {
    scrollIntent=0;scrollIntentUntil=0;
    selectingChat = true;
  }
});
window.addEventListener("pointerup", () => { selectingChat = false; });
window.addEventListener("pointercancel", () => { selectingChat = false; });
window.addEventListener("blur", () => { selectingChat = false; });
document.addEventListener("selectionchange", () => { if (chatHasSelection()) setFollow(false); });
$("#followBtn").onclick = () => { setFollow(true); scrollDown(true); };
/* el boton se sienta encima del compositor, que cambia de alto mientras escribes */
(function placeFollow() { const box = $("#composerBox"), b = $("#followBtn"); if (!box || !b) return;
  const move = () => { b.style.bottom = (box.offsetHeight + 14) + "px"; };
  move(); if (window.ResizeObserver) new ResizeObserver(move).observe(box); else addEventListener("resize", move); })();
function renderWelcome() {
  // No greeting or logo in the chat (owner's choice); the composer placeholder carries the hint.
  $("#chat").replaceChildren();syncWelcomeHint();
}
function syncWelcomeHint(){
  const input=$('#input');if(!input)return;
  const state=$('#modelBtn')?.dataset.state;
  input.placeholder=uiText(state==='off'||state==='empty'?'Carga un modelo para empezar…':state==='preparing'?'El modelo se está preparando…':'Mensaje…');
}


function userMessageRawText(message) {const c=message?.content;return Array.isArray(c)?c.map(p=>(p&&typeof p==='object'?p.text||'':String(p||''))).join('\n'):String(c||'');}
function displayUserText(message) {return userMessageRawText(message).split('\n\n[Adjuntos]\n')[0];}
function attachmentSummary(message) {
  const files=userMessageRawText(message).split('\n\n[Adjuntos]\n')[1];
  return [...(files?[...files.matchAll(/^--- (.+) ---$/gm)].map(match=>match[1]):[]),...(message.images||[]).map(image=>image.name)].join(', ');
}
function responseVersion(message) {
  const version={content:message.content||'',reasoning_content:message.reasoning_content||''};
  for(const key of ['tool_trace','status','error','usage','performance','model','model_name','generated_at'])if(message[key])version[key]=message[key];
  return version;
}
function selectResponseVersion(index,offset) {
  if(busy||engineBusy)return;
  const message=messages[index],variants=message.variants||[];
  const selected=Math.max(0,Math.min(variants.length-1,(message.variantIndex??variants.length-1)+offset));
  const response={role:'assistant',...variants[selected],variants,variantIndex:selected};
  if(index<messages.length-1){
    messages=JSON.parse(JSON.stringify(messages.slice(0,index)));messages.push(response);currentId=null;persistConv();
    const branch=convs.find(c=>c.id===currentId);if(branch){branch.title+=' · variante';saveConvsLS();renderConvs();}
  }else {messages[index]=response;persistConv();}
  renderChat();
}
function messageActions(row,message,index) {
  const actions=document.createElement('div');actions.className='message-actions';
  const button=(text,title,action)=>{const element=document.createElement('button');element.type='button';element.textContent=text;element.title=title;element.onclick=action;actions.append(element);return element;};
  button(uiText('Copiar'),uiText('Copiar el texto del mensaje'),()=>navigator.clipboard.writeText(String(message.content||'')).then(()=>note('Copiado.')).catch(()=>note('No se pudo copiar. Selecciona el texto y pulsa Ctrl+C.'))).disabled=!message.content;
  if(message.role==='user')button(uiText('Editar'),uiText('Editar y reenviar en una copia del chat'),()=>openMessageEditor(index)).disabled=busy||engineBusy;
  if(message.role==='assistant') {
    if(message.variants?.length>1) {
      const selected=message.variantIndex??message.variants.length-1;
      const previous=button('‹',uiText('Respuesta anterior'),()=>selectResponseVersion(index,-1));previous.setAttribute('aria-label',uiText('Respuesta anterior'));previous.disabled=busy||engineBusy||selected===0;
      const count=document.createElement('span');count.className='version-count';count.textContent=`${selected+1} / ${message.variants.length}`;count.setAttribute('aria-label',uiText('Respuesta')+' '+(selected+1)+' / '+message.variants.length);actions.append(count);
      const next=button('›',uiText('Respuesta siguiente'),()=>selectResponseVersion(index,1));next.setAttribute('aria-label',uiText('Respuesta siguiente'));next.disabled=busy||engineBusy||selected===message.variants.length-1;
    }
    if(index===messages.length-1&&messages.slice(0,index).some(m=>m.role==='user'))button(uiText('Regenerar'),uiText('Generar otra respuesta y conservar esta versión'),()=>regenerateResponse(index)).disabled=busy||engineBusy;
  }
  row.append(actions);
}
function toolName(call) {return String(call.name||'').split('__').at(-1);}
// While a file is being written the model streams JSON ("<p>\n  <div class=\"x\">..."). Show the
// text as it will land in the file. Incremental: only the newly received tail is decoded, and an
// escape cut between two chunks waits for the next one.
const draftViews=new WeakMap();
function readableDraft(call) {
  const raw=call.draftText||'';
  let state=draftViews.get(call);
  // Not stored on the call: tool traces are saved with the conversation.
  if(!state||state.raw.length>raw.length||!raw.startsWith(state.raw.slice(0,64))){state={start:-1,pos:0,out:'',raw:''};draftViews.set(call,state);}
  state.raw=raw;
  if(state.start<0){const match=/"(?:content|text)"\s*:\s*"/.exec(raw);if(!match)return raw;state.start=state.pos=match.index+match[0].length;}
  if(state.done)return state.out;
  const escapes={n:'\n',t:'\t',r:'\r','"':'"','\\':'\\','/':'/',b:'\b',f:'\f'};let i=state.pos,out='';
  while(i<raw.length){
    const ch=raw[i];
    if(ch==='"'){state.done=true;break;}
    if(ch!=='\\'){out+=ch;i++;continue;}
    const next=raw[i+1];if(next===undefined)break;
    if(next==='u'){const hex=raw.slice(i+2,i+6);if(hex.length<4)break;out+=String.fromCharCode(parseInt(hex,16)||0xfffd);i+=6;continue;}
    out+=escapes[next]??next;i+=2;
  }
  state.out+=out;state.pos=i;return state.out;
}
function toolTitle(call) {
  const name=toolName(call);
  return uiText(({hf_account:'Cuenta de Hugging Face',hf_cli:'Hugging Face CLI',hf_transfer:'Archivos de Hugging Face',web_search:'Web Search',web_visit:'Web Visit',fs_list:'Listar archivos',fs_read:'Leer archivo',doc_read:'Leer documento',fs_write:'Guardar archivo',fs_edit:'Editar archivo',fs_copy:'Copiar texto',draft_resume:'Continuar borrador',file_history:'Versiones del archivo',code_check:'Comprobar código',project_map:'Mapa del proyecto',web_render:'Renderizar HTML',invalid_call:'Llamada inválida',draft:'Herramienta',shell_run:'Comandos',sys_info:'Información del equipo'})[name]||name||'Herramienta');
}
function toolState(call) {
  return uiText(({drafting:'Redactando',validating:'Validando',running:'Ejecutando',completed:'Resultado recibido',error:'Error',blocked:'No ejecutada',interrupted:'Interrumpida',missing:'Sin resultado recibido'})[call.status]||(Object.hasOwn(call,'result')?(call.ok===false?'Error':'Resultado recibido'):'Sin resultado guardado'));
}
async function downloadToolDraft(filename,text,mime='text/plain;charset=utf-8',options={}) {
  const content=String(text??'');
  const invoke=window.__TAURI__?.core?.invoke;
  if(invoke){
    const savedPath=await invoke('save_export_file',{filename,content});
    if(!savedPath)return null;
    if(!options.silent)note(uiText('Guardado en')+' '+savedPath);
    return savedPath;
  }
  const url=URL.createObjectURL(new Blob([content],{type:mime}));
  const link=document.createElement('a');link.href=url;link.download=filename;link.hidden=true;
  document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1500);
  if(!options.silent)note(uiText('Archivo guardado.')+' ('+filename+')');
  return filename;
}
window.downloadToolDraft=downloadToolDraft;
function fileFromDraft(call) {
  if(!/^fs_write(?:$|[",])/.test(toolName(call)))return null;
  let args=call.args||{};
  if(typeof args.content!=='string'&&call.draftText) {
    const draft=call.draftText.trim();
    try {
      const decoded=JSON.parse(draft.replace(/^<tool_call>\s*|\s*<\/tool_call>$/g,''));
      args={...(decoded.arguments||decoded)};
      if(typeof args.content!=='string'&&typeof decoded.text==='string')args.content=decoded.text;
    } catch {
      // A complete string can be read even if the outer object did not close.
      const content=draft.match(/[{,]\s*"(?:content|text)"\s*:\s*("(?:[^"\\]|\\[\s\S])*")/);
      const path=draft.match(/[{,]\s*"path"\s*:\s*("(?:[^"\\]|\\[\s\S])*")/);
      try {
        if(content)args={content:JSON.parse(content[1]),path:path?JSON.parse(path[1]):null};
      } catch {}
      if(typeof args.content!=='string') {
        const html=draft.match(/<!DOCTYPE\s+html[\s\S]*?<\/html>/i);
        if(html) {
          try {args={content:JSON.parse('"'+html[0]+'"'),path:path?JSON.parse(path[1]):'archivo-recuperado.html'};}
          catch {
            if(html[0].includes('\n')&&!html[0].includes('\\"'))args={content:html[0],path:'archivo-recuperado.html'};
          }
        }
      }
    }
  }
  if(typeof args.content!=='string'||!args.content)return null;
  const filename=typeof args.path==='string'?args.path.split(/[\\/]/).pop():null;
  return {filename:filename||'archivo-recuperado.txt',content:args.content};
}
function draftActions(heading,call,text) {
  const actions=document.createElement('span');actions.className='tool-recovery-actions';
  const action=(label,run)=>{
    const button=document.createElement('button');button.type='button';button.className='text-btn';
    button.textContent=uiText(label);button.onclick=()=>run(button);actions.append(button);
  };
  const copy=(value)=>navigator.clipboard.writeText(value).then(()=>note('Borrador copiado.')).catch(()=>note('No se pudo copiar. Usa Descargar borrador.'));
  const file=fileFromDraft(call);
  if(file){
    action('Guardar en este chat',async button=>{
      if(!currentId){note('Abre la conversación para guardar su borrador.');return;}
      button.disabled=true;
      button.textContent=uiText('Guardando…');
      try {
        const result=await requestJSON('/api/save',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({path:file.filename,content:file.content,conversation_id:currentId,create_only:true})
        });
        button.textContent=uiText('Guardado');
        button.title=result.path||file.filename;
        call.recovery={path:result.path||file.filename,result:'Guardado por recuperación del borrador. '+(result.path||file.filename)};
        persistConv();
        note((result.verificacion?.ok===false?'Guardado. La comprobación encontró errores en ':'Guardado en ')+(result.path||file.filename));
      } catch(error) {
        button.disabled=false;
        button.textContent=uiText('Guardar en este chat');
        note(error.message);
      }
    });
    action('Ver código',()=>openViewer(file.filename.split('.').at(-1),file.content));
    action('Copiar código',()=>copy(file.content));
    action('Descargar archivo',()=>{downloadToolDraft(file.filename,file.content).catch(error=>note(error?.message||String(error)));});
  }
  if(call.draft_id&&call.status!=='completed')action('Continuar borrador',async()=>{
    if(busy||engineBusy){note('Detén la generación antes de continuar un borrador.');return;}
    if(!S.functions.files){note('Activa Archivos en MCPs para continuar el borrador.');return;}
    if(!$('#input').value.trim())$('#input').value='Continue from the recovered draft. Preserve the existing work and fix or complete only what is needed.';
    await sendMsg(call.draft_id);
  });
  if(call.draft_id)action('Recuperar del disco',async button=>{
    if(!currentId){note('Abre la conversación del borrador.');return;}
    button.disabled=true;button.textContent=uiText('Recuperando…');
    try {
      const saved=await requestJSON('/api/draft',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({conversation_id:currentId,draft_id:call.draft_id})
      });
      call.draftText=saved.raw;
      call.draftChars=saved.raw.length;
      if(saved.args&&Object.keys(saved.args).length)call.args=saved.args;
      persistConv();
      const section=heading.closest('.tool-trace');
      if(section?._trace)updateToolTrace(section,section._trace);
      note('Borrador recuperado del disco. Ya puedes guardarlo o descargarlo.');
    } catch(error) {button.disabled=false;button.textContent=uiText('Recuperar del disco');note(error.message);}
  });
  action('Copiar borrador',()=>copy(text));
  action('Descargar borrador',()=>{downloadToolDraft('llamada-borrador.txt',text).catch(error=>note(error?.message||String(error)));});
  heading.append(actions);
}
async function openFileHistory(path){
  if(busy||!currentId){note('Espera a que termine la ejecución.');return;}
  const chatId=currentId,dialog=document.createElement('dialog');dialog.style.cssText='max-width:min(700px,92vw);max-height:80vh;background:var(--panel);color:var(--text);border:1px solid var(--border);border-radius:var(--radius);padding:20px';
  const title=document.createElement('h3');title.textContent=path;dialog.append(title);
  const close=document.createElement('button');close.textContent=uiText('Cerrar');close.onclick=()=>dialog.close();dialog.append(close);
  dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
  try{
    const data=await requestJSON('/api/v1/files/history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:chatId,path})});
    if(!data.result.length){const text=document.createElement('p');text.textContent=uiText('Sin versiones anteriores registradas.');dialog.append(text);}
    for(const version of data.result){const row=document.createElement('p'),label=document.createElement('span'),restore=document.createElement('button');label.textContent=new Date(version.created*1000).toLocaleString()+' · '+version.bytes+' bytes ';restore.textContent=uiText('Restaurar');restore.onclick=async()=>{
      restore.disabled=true;try{const saved=await requestJSON('/api/v1/files/history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:chatId,path,revision:version.id})});const diff=document.createElement('pre');diff.textContent=saved.result.diff;dialog.append(diff);note('Versión restaurada; el estado anterior también quedó guardado.');}catch(error){note(error.message);restore.disabled=false;}
    };row.append(label,restore);dialog.append(row);}
  }catch(error){note(error.message);dialog.close();}
}

function renderToolTrace(row,trace) {
  if(!trace?.length)return null;
  const section=document.createElement('section');section.className='tool-trace';section.setAttribute('aria-label',uiText('Actividad de herramientas'));row.append(section);
  updateToolTrace(section,trace);return section;
}
function updateToolTrace(section,trace) {
  section._trace=trace;
  let overview=section.querySelector('.tool-overview');if(!overview){overview=document.createElement('div');overview.className='tool-overview';overview.title=uiText('Llamadas solicitadas. Cada bloque indica si se ejecutó y muestra su resultado.');section.prepend(overview);}
  const search=trace.filter(call=>toolName(call)==='web_search').length,visit=trace.filter(call=>toolName(call)==='web_visit').length;
  const running=trace.some(call=>['running','drafting','validating'].includes(call.status));
  overview.dataset.running=String(running);
  if(running)section._started=section._started||Date.now();else delete section._started;
  const seconds=section._started?Math.max(0,Math.round((Date.now()-section._started)/1000)):0;
  overview.textContent=running?uiText('Ejecutando')+' · '+seconds+' s':(search||visit)?`Web Search: ${search} · Web Visit: ${visit}`:trace.length+' '+uiText(trace.length===1?'herramienta':'herramientas');
  trace.forEach((call,index)=>{
    const id=call.id||'legacy-'+index;
    let card=[...section.querySelectorAll(':scope > .tool')].find(element=>element.dataset.traceId===id);
    if(!card){
      card=document.createElement('details');card.className='tool';card.dataset.traceId=id;card.open=false;
      const summary=document.createElement('summary'),name=document.createElement('strong'),hint=document.createElement('span'),state=document.createElement('span');name.className='tool-name';hint.className='tool-hint';state.className='tool-status';summary.append(name,hint,state);
      const body=document.createElement('div');body.className='tool-body';card.append(summary,body);section.append(card);
    }
    card.dataset.status=call.status||'legacy';card.querySelector('.tool-name').dataset.uiLabel=toolTitle(call);card.querySelector('.tool-name').textContent=uiText(toolTitle(call));
    const args=call.args&&typeof call.args==='object'?call.args:{};
    card.querySelector('.tool-hint').textContent=String(args.url||args.query||args.path||args.command||'');
    const progress = call.status === 'drafting' && call.draftChars ? ' · ' + formatTokens(call.draftChars) + ' caracteres' : '';
    const failedState=['error','blocked','interrupted','missing'].includes(call.status);
    const duration=Number.isFinite(call.elapsed_ms)?(call.elapsed_ms<1000?call.elapsed_ms+' ms':(call.elapsed_ms/1000).toFixed(1)+' s'):'';
    const stateLabel=failedState?toolState(call)+(duration?' · '+duration:''):call.status==='running'||call.status==='drafting'||call.status==='validating'?toolState(call)+progress:duration;
    card.querySelector('.tool-status').dataset.uiLabel=stateLabel;card.querySelector('.tool-status').textContent=uiText(stateLabel);
    const body=card.querySelector('.tool-body');
    if (call.status === 'drafting') {
      let preview = body.querySelector('.tool-draft-preview');
      if (!preview) {
        const label = document.createElement('div');
        label.className = 'tool-block-head';
        label.textContent = 'Argumentos en directo';
        preview = document.createElement('pre');
        preview.className = 'tool-draft-preview';
        preview.tabIndex = 0;
        preview._followDraft=true;
        let direction=0,intentUntil=0,touchY=null;
        const intent=value=>{direction=value;intentUntil=performance.now()+700;if(value<0)preview._followDraft=false;else if(value>0&&preview.scrollHeight-preview.scrollTop-preview.clientHeight<22)preview._followDraft=true;};
        preview.addEventListener('wheel',event=>{if(event.deltaY)intent(Math.sign(event.deltaY));},{passive:true});
        preview.addEventListener('keydown',event=>{if(['PageUp','Home','ArrowUp'].includes(event.key))intent(-1);else if(['PageDown','End','ArrowDown'].includes(event.key))intent(1);});
        preview.addEventListener('pointerdown',()=>{direction=0;preview._followDraft=false;});
        preview.addEventListener('touchstart',event=>{touchY=event.touches[0]?.clientY??null;},{passive:true});
        preview.addEventListener('touchmove',event=>{const y=event.touches[0]?.clientY;if(touchY!==null&&y!==undefined&&Math.abs(y-touchY)>1)intent(Math.sign(touchY-y));touchY=y??null;},{passive:true});
        preview.addEventListener('scroll',()=>{const bottom=preview.scrollHeight-preview.scrollTop-preview.clientHeight<22;if(direction>0&&performance.now()<intentUntil&&bottom)preview._followDraft=true;else if(!bottom)preview._followDraft=false;});
        body.replaceChildren(label, preview);
      }
      const follow = preview._followDraft && !chatHasSelection(preview) && !selectingChat;
      setLiveText(preview, readableDraft(call) || 'Esperando argumentos…');
      if (follow) preview.scrollTop = preview.scrollHeight;
      return;
    }
    // Keep expanded cards and text selections intact during unrelated streamed tokens.
    const signature=JSON.stringify(call);if(card._traceSignature===signature)return;card._traceSignature=signature;body.replaceChildren();
    if(['fs_write','fs_edit','fs_copy'].includes(toolName(call))&&(args.path||args.destino)){
      const history=document.createElement('button');history.type='button';history.className='text-btn';history.textContent=uiText('Versiones / deshacer');
      history.onclick=()=>openFileHistory(args.path||args.destino);body.append(history);
    }
    const meta=document.createElement('div');meta.className='tool-meta';meta.textContent=String(call.name||'')+(call.round?' · '+uiText('Ronda')+' '+call.round:'');body.append(meta);
    const block=(title,text)=>{const heading=document.createElement('div');heading.className='tool-block-head';const label=document.createElement('span');label.textContent=title;heading.append(label);const pre=document.createElement('pre');pre.tabIndex=0;pre.textContent=text;body.append(heading,pre);return heading;};
    const failed=call.ok===false||['error','blocked','interrupted','missing'].includes(call.status);
    const hasParsedArgs=args&&typeof args==='object'&&Object.keys(args).length>0;
    if (call.draftText && failed && !hasParsedArgs) {
      const title = uiText(call.draftChars > call.draftText.length ? 'Borrador antiguo · tramo disponible' : 'Borrador recibido');
      const heading=block(title,call.draftText);
      draftActions(heading,call,call.draftText);
    } else {
      const params=JSON.stringify(args,null,2);
      const heading=block(uiText('Parámetros'),params);
      if(failed&&fileFromDraft(call))draftActions(heading,call,params);
    }
    if(call.draft_warning){const warning=document.createElement('p');warning.className='tool-note';warning.textContent=call.draft_warning;body.append(warning);}
    if(Object.hasOwn(call,'result')) {
      const result=String(call.result??'');const heading=block(uiText('Resultado')+' · '+formatTokens(result.length)+' '+uiText('caracteres'),result);
      const copy=document.createElement('button');copy.type='button';copy.className='text-btn';copy.textContent=uiText('Copiar');copy.setAttribute('aria-label',uiText('Copiar resultado de ')+toolTitle(call));copy.onclick=()=>navigator.clipboard.writeText(result).then(()=>note('Resultado copiado.')).catch(()=>note('No se pudo copiar. Selecciona el resultado y pulsa Ctrl+C.'));heading.append(copy);
      if(call.recovery){const recovered=document.createElement('p');recovered.className='tool-note';recovered.textContent=call.recovery.result;body.append(recovered);}
      if(!result){const empty=document.createElement('p');empty.className='tool-note';empty.textContent=uiText('La herramienta devolvió un resultado vacío.');body.append(empty);}
      if(call.source_truncated){const note=document.createElement('p');note.className='tool-note';note.textContent='El servidor MCP entregó este resultado recortado'+(call.source_chars?' ('+formatTokens(call.source_chars)+' caracteres originales).':'.');body.append(note);}
      if(call.truncated&&typeof call.model_result==='string') {
        const note=document.createElement('p');note.className='tool-note';note.textContent='Aquí se conserva todo el resultado recibido. El modelo recibió '+formatTokens(call.model_result.length)+' de '+formatTokens(result.length)+' caracteres.';body.append(note);
        const sent=document.createElement('details');sent.className='model-result';const summary=document.createElement('summary');summary.textContent=uiText('Ver lo enviado al modelo');const pre=document.createElement('pre');pre.tabIndex=0;pre.textContent=call.model_result;sent.append(summary,pre);body.append(sent);
      }
    }else{
      const pending=document.createElement('p');pending.className='tool-note';pending.textContent=uiText(call.status==='running'?'Esperando resultado…':call.status==='interrupted'?'Se detuvo la respuesta antes de recibir el resultado.':call.status==='missing'?'No llegó el resultado de esta llamada.':'Este chat no guardó el resultado. Regenera la respuesta para registrar nuevas llamadas.');body.append(pending);
    }
  });
  const completedTargets=new Set(trace.filter(c=>c.status==='completed'&&c.ok!==false&&(['fs_write','fs_edit'].includes(toolName(c))&&c.args?.path||toolName(c)==='fs_copy'&&c.args?.destino)).map(c=>String(toolName(c)==='fs_copy'?c.args.destino:c.args.path).split(/[\\/]/).pop().toLowerCase()));
  const callTarget=c=>c.args?.path?String(c.args.path).split(/[\\/]/).pop():c.file_path?String(c.file_path).split(/[\\/]/).pop().replace(/^[0-9a-f]{32}-/i,''):'';
  const pendingCall=!running?trace.findLast(c=>{
    const failed=c.ok===false||['error','blocked','interrupted','missing'].includes(c.status);
    if(!failed||toolName(c)!=='fs_write')return false;
    const t=callTarget(c).toLowerCase();
    return (!t||!completedTargets.has(t))&&Boolean(c.draft_id||fileFromDraft(c));
  }):null;
  section.querySelector('.draft-recovery-banner')?.remove();
  if(pendingCall){
    const file=fileFromDraft(pendingCall),target=callTarget(pendingCall)||file?.filename||'';
    const banner=document.createElement('div');banner.className='draft-recovery-banner';
    const info=document.createElement('div');info.className='draft-recovery-info';
    const label=document.createElement('span');label.textContent=uiText('Borrador disponible');info.append(label);
    if(target){const code=document.createElement('code');code.textContent=target;info.append(code);}
    const buttons=document.createElement('div');buttons.className='draft-recovery-buttons';
    if(pendingCall.draft_id){
      const cont=document.createElement('button');cont.type='button';cont.className='soft-btn primary';cont.textContent=uiText('Continuar borrador');
      cont.onclick=async()=>{
        if(busy||engineBusy){note('Detén la generación antes de continuar un borrador.');return;}
        if(!S.functions.files){note('Activa Archivos en MCPs para continuar el borrador.');return;}
        if(!$('#input').value.trim())$('#input').value='Continue from the recovered draft. Preserve the existing work and fix or complete only what is needed.';
        await sendMsg(pendingCall.draft_id);
      };
      buttons.append(cont);
    }
    if(file){
      const view=document.createElement('button');view.type='button';view.className='soft-btn';view.textContent=uiText('Ver código');
      view.onclick=()=>openViewer(file.filename.split('.').at(-1),file.content);
      buttons.append(view);
    }
    banner.append(info,buttons);section.append(banner);
  }
}
if(!window.__valToolTicker)window.__valToolTicker=setInterval(()=>{for(const section of document.querySelectorAll('#chat .tool-trace')){if(!section._started)continue;const overview=section.querySelector('.tool-overview');if(overview)overview.textContent=uiText('Ejecutando')+' · '+Math.max(0,Math.round((Date.now()-section._started)/1000))+' s';}},1000);
function recordToolEvent(trace,event) {
  let call=event.id?trace.find(item=>item.id===event.id):null;
  if(!call&&event.type==='tool_result')call=trace.findLast(item=>item.name===event.name&&!Object.hasOwn(item,'result'));
  if(!call){call={id:event.id||'tool-'+(trace.length+1),name:event.name,args:event.args||{}};trace.push(call);}
  const {type,delta,...fields}=event;
  Object.assign(call,fields);
  if (type === 'tool_draft' && typeof delta === 'string') {
    call.draftChars = (call.draftChars || 0) + delta.length;
    call.draftText = (call.draftText || '') + delta;
  }
  if (type === 'tool_result' && event.ok === true) {
    delete call.draftText;
    delete call.draftChars;
  }
  if(type==='tool'&&!call.status)call.status='running';
  return call;
}

let renderedMessages=new WeakMap();
function refreshChatTranslations(){if(!busy){renderedMessages=new WeakMap();renderChat();}}
window.refreshChatTranslations=refreshChatTranslations;
function showResponseModel(row,message){
  let label=row.querySelector(':scope > .response-model');
  if(!label){label=document.createElement('div');label.className='response-model';row.append(label);}
  const id=typeof message.model==='string'?message.model:'',storedName=typeof message.model_name==='string'?message.model_name:'';
  const name=storedName||(id&&(modelNames[id]||id))||uiText('Modelo no registrado');
  label.textContent=name;label.dataset.model=id;label.dataset.unknown=String(!id&&!storedName);
  label.title=id||uiText('Esta respuesta no guardó qué modelo la generó.');
  label.setAttribute('aria-label',uiText('Modelo que generó la respuesta: ')+name);
}
function updateResponsePerformance(generation,timings,live=false){
  if(!timings||typeof timings!=='object')return;
  // Almost everything came from the prompt cache: there is no reading speed to show, say so instead.
  if(!live&&Number.isFinite(timings.cache_n)&&timings.cache_n>0&&Number.isFinite(timings.prompt_n)&&timings.prompt_n<8)(generation.performance??={}).prefillCached=true;
  for(const [key,source] of [['decode','predicted_per_second'],['prefill','prompt_per_second']]){
    const value=timings[source];if(typeof value==='number'&&Number.isFinite(value)&&value>0&&value<1e9&&(!live||!generation.exactPerformance?.[key])){(generation.performance??={})[key]=value;if(!live)(generation.exactPerformance??={})[key]=true;}
  }
}
function showResponseMetrics(row,performance){
  const valid=value=>typeof value==='number'&&Number.isFinite(value)&&value>0&&value<1e9;
  let el=row.querySelector(':scope > .response-metrics');
  if(!valid(performance?.decode)&&!valid(performance?.prefill)&&!performance?.prefillCached){el?.remove();return;}
  if(!el){el=document.createElement('div');el.className='response-metrics';row.append(el);}
  el.hidden=false;el.replaceChildren();
  for(const [key,label] of [['decode','Generación'],['prefill','Lectura']])if(valid(performance[key])){
    const group=document.createElement('span'),small=document.createElement('small'),value=document.createElement('strong'),unit=document.createElement('em');
    small.textContent=uiText(label);value.textContent=key==='decode'?performance[key].toFixed(1):Math.round(performance[key]).toLocaleString(window.VALI18n?.locale||'es-ES');unit.textContent='tok/s';group.append(small,value,unit);el.append(group);
  }
  if(!valid(performance?.prefill)&&performance?.prefillCached){
    const group=document.createElement('span'),small=document.createElement('small'),value=document.createElement('strong');
    small.textContent=uiText('Lectura');value.textContent=uiText('desde caché');group.append(small,value);el.append(group);
  }
}
function messageFileList(message) {
  if(message.role!=='assistant'||!Array.isArray(message.tool_trace))return [];
  const out=[],seen=new Set();
  for(const call of message.tool_trace){
    const name=toolName(call),args=call.args&&typeof call.args==='object'?call.args:{};
    if(!['fs_write','fs_edit','fs_copy','fs_manage'].includes(name))continue;
    if(call.ok===false||['error','blocked','interrupted','missing'].includes(call.status))continue;
    if(!Object.hasOwn(call,'result')&&call.status!=='completed')continue;
    let path='';
    if(name==='fs_copy')path=args.destino||args.desde||'';
    else if(name==='fs_manage'){if(!['move','copy'].includes(String(args.action||'')))continue;path=args.destination||'';}
    else path=args.path||'';
    if(typeof path!=='string'||!path.trim())continue;
    const normalized=path.split(String.fromCharCode(92)).join('/');
    const key=normalized.toLowerCase();if(seen.has(key))continue;seen.add(key);
    const parts=normalized.split('/').filter(Boolean);
    const fallback=name==='fs_write'&&typeof args.content==='string'&&args.content.length<=1024*1024?args.content:'';out.push({path,name:parts.at(-1)||path,folder:parts.slice(-2,-1)[0]||'',text:fallback});
    if(out.length>=8)break;
  }
  return out;
}
function renderMessageFiles(row,message) {
  const files=messageFileList(message);
  let box=row.querySelector(':scope > .message-files');
  if(!files.length){box?.remove();return;}
  const signature=files.map(file=>file.path).join('|');
  if(box&&box.dataset.signature===signature)return;
  if(!box){box=document.createElement('div');box.className='message-files';box.setAttribute('aria-label',uiText('Archivos creados o editados'));row.querySelector(':scope > .bubble')?.after(box);}
  box.dataset.signature=signature;box.replaceChildren();
  for(const file of files){
    const chip=document.createElement('button');chip.type='button';chip.className='file-chip';
    chip.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6V3Zm8 0v5h4M9 13h6M9 17h4"/></svg>';
    const text=document.createElement('span');text.className='file-chip-text';
    const name=document.createElement('strong');name.textContent=file.name;
    const folder=document.createElement('small');folder.textContent=file.folder||uiText('archivo');
    text.append(name,folder);chip.append(text);
    chip.setAttribute('aria-label',uiText('Abrir')+' '+file.name);
    chip.onclick=()=>openFileAttachment(file);
    box.append(chip);
  }
}
async function openFileAttachment(file) {
  if(!currentId){note(uiText('Abre la conversación del archivo.'));return;}
  try{
    const data=await requestJSON('/api/v1/files/read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:currentId,path:file.path})});
    const extension=(file.name.split('.').pop()||'').toLowerCase();
    openViewer(extension,data.text);
  }catch(error){if(file.text){const extension=(file.name.split('.').pop()||'').toLowerCase();openViewer(extension,file.text);}else note(error.message);}
}
let composerMoveAnimation=null;
function updateComposerPosition(empty){
  const wrap=$('#chatwrap'), box=$('#composerBox'), next=String(empty);
  if(wrap.dataset.empty===next)return;
  const from=box.getBoundingClientRect();
  composerMoveAnimation?.cancel();
  wrap.dataset.empty=next;
  const to=box.getBoundingClientRect(), delta=from.top-to.top;
  if(Math.abs(delta)>1 && box.animate && !matchMedia('(prefers-reduced-motion: reduce)').matches){
    const duration=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--motion-duration'))||620;
    composerMoveAnimation=box.animate([{transform:`translateY(${delta}px)`},{transform:'translateY(0)'}],{duration,easing:'cubic-bezier(.4,0,.2,1)'});
    composerMoveAnimation.onfinish=()=>{composerMoveAnimation=null;};
  }
}
(function reserveComposerSpace(){
  const box=$('#composerBox'),wrap=$('#chatwrap');
  const update=()=>wrap.style.setProperty('--composer-height',box.offsetHeight+'px');
  update();if(window.ResizeObserver)new ResizeObserver(update).observe(box);else addEventListener('resize',update);
})();
function renderChat(skipIndex=-1) {
  syncContextMeter();
  updateComposerPosition(!messages.length);
  const chat=$('#chat'),views=new Map();
  for(const row of chat.querySelectorAll('.msg[data-index]'))for(const card of row.querySelectorAll('details.tool[open]'))views.set(row.dataset.index+':'+card.dataset.traceId,{sent:!!card.querySelector('.model-result[open]'),scroll:[...card.querySelectorAll('pre')].map(pre=>pre.scrollTop)});
  if(!messages.length){renderWelcome();return;}
  let position = 0;
  messages.forEach((message,index)=>{
    if(index===skipIndex)return;
    const row=renderedMessages.get(message)||document.createElement('div');
    const cached=renderedMessages.has(message);
    row.className='msg '+(message.compacted?'compacted':message.role==='user'?'user':'assistant');row.dataset.index=index;
    if(!cached){
    if(message.compacted){
      const card=document.createElement('details');card.className='compact-card';
      const summary=document.createElement('summary');
      const info=message.compacted;
      summary.textContent=uiText('Contexto comprimido')+' · '+(info.compressed_count||0)+' '+uiText('mensajes')+' · '+uiText(info.method_label||info.method||'API');
      const body=document.createElement('div');body.className='compact-body bubble';
      renderRich(body,String(message.content||''));
      card.append(summary,body);row.append(card);
    }else{
    if(message.role==='assistant') {
      if(message.reasoning_content){const think=document.createElement('details');think.className='think';const summary=document.createElement('summary');summary.textContent=uiText('Pensamiento');const content=document.createElement('div');content.className='think-body';renderRich(content,message.reasoning_content);think.append(summary,content);row.append(think);}
    }
    const bubble=document.createElement('div');bubble.className='bubble';
    if(message.role==='user'){bubble.textContent=displayUserText(message);const names=attachmentSummary(message);if(names)bubble.textContent+='\n📎 '+names;}
    else renderRich(bubble,String(message.content||''));row.append(bubble);
    if(message.role==='assistant'){
      const trace=renderToolTrace(row,message.tool_trace);
      if(trace)bubble.before(trace);
    }
    if(message.status){const state=document.createElement('div');state.className='response-state'+(message.status==='error'?' err':'');state.textContent=message.status==='stopped'?uiText('Respuesta detenida.'):message.error||uiText('No se pudo completar la respuesta.');row.append(state);}
    }
    renderedMessages.set(message,row);
    }
    if(message.role==='assistant'&&!message.compacted)renderMessageFiles(row,message);
    row.querySelector(':scope > .message-actions')?.remove();
    if(message.role==='assistant'&&!message.compacted){showResponseMetrics(row,message.performance);showResponseModel(row,message);}
    if(!message.compacted)messageActions(row,message,index);
    const current = chat.childNodes[position++];
    if (current !== row) chat.insertBefore(row, current || null);
    for(const card of row.querySelectorAll('details.tool')){const view=views.get(index+':'+card.dataset.traceId);if(view){card.open=true;const sent=card.querySelector('.model-result');if(sent)sent.open=view.sent;card.querySelectorAll('pre').forEach((pre,i)=>pre.scrollTop=view.scroll[i]||0);}}
  });
  while (chat.childNodes.length > position) chat.lastChild.remove();
  scrollDown();
}
function addAssistantBox() {
  const row=document.createElement('div');row.className='msg assistant';
  row.innerHTML='<details class="think" hidden><summary>Razonamiento</summary><div class="think-body"></div></details><div class="bubble"></div><div class="response-metrics" hidden><span><small></small><strong class="rm-decode">—</strong><em>tok/s</em></span><span><small></small><strong class="rm-prefill">—</strong><em>tok/s</em></span></div>';
  const thinkSummary=row.querySelector('.think summary');if(thinkSummary)thinkSummary.textContent=uiText('Pensamiento');$('#chat').append(row);scrollDown();return row;
}
let editingMessageIndex=null;
function openMessageEditor(index) {
  if(busy||engineBusy||messages[index]?.role!=='user')return;
  editingMessageIndex=index;$('#editMessageInput').value=displayUserText(messages[index]);$('#editMessageDialog').showModal();$('#editMessageInput').focus();
}
$('#cancelMessageEdit').onclick=$('#closeMessageEdit').onclick=()=>$('#editMessageDialog').close();
$('#saveMessageEdit').onclick=()=>{
  const index=editingMessageIndex,text=$('#editMessageInput').value.trim();
  if(busy||engineBusy||index===null||!text)return;
  if(!requireModelForChat())return;
  const original=messages[index],rawOriginal=userMessageRawText(original),suffix=rawOriginal.includes('\n\n[Adjuntos]\n')?'\n\n[Adjuntos]\n'+rawOriginal.split('\n\n[Adjuntos]\n').slice(1).join('\n\n[Adjuntos]\n'):'';
  messages=JSON.parse(JSON.stringify(messages.slice(0,index)));messages.push({role:'user',content:text+suffix,...(original.images?{images:structuredClone(original.images)}:{})});currentId=null;
  $('#editMessageDialog').close();persistConv();const branch=convs.find(c=>c.id===currentId);if(branch){branch.title+=' · '+uiText('edición');saveConvsLS();renderConvs();}
  setFollow(true);generateResponse();
};

function dismissToast() {
  clearTimeout(toastTimer);
  $("#toast").hidden = true;
}
$("#dismissToast").onclick = dismissToast;
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("#toast").hidden && !chatControlsOpen() && !helpAnchor && !window.VALWindows?.isOpen('settings') && !document.querySelector('dialog[open]')) {
    event.preventDefault(); event.stopImmediatePropagation(); dismissToast();
  }
}, true);
function note(text) {
  $("#toastText").textContent = uiText(text); $("#toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(dismissToast, 6500);
}
