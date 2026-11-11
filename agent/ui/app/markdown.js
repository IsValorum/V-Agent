/* ---------- markdown + código ---------- */
function escHTML(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

function inlineMD(s) {
  const codes = [];
  let text = escHTML(s).replace(/`([^`]+)`/g, (_, code) => "\u0000" + (codes.push(code)-1) + "\u0000");
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => '<a target="_blank" rel="noopener noreferrer" href="' + url.replace(/"/g, "&quot;").replace(/'/g, "&#39;") + '">' + label + '</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return text.replace(/\u0000(\d+)\u0000/g, (_, i) => "<code>" + codes[+i] + "</code>");
}
function mdHTML(text) {
  const lines = text.split("\n"); let html = "", list = "";
  const closeList = () => { if (list) { html += "</"+list+">"; list = ""; } };
  const cells = line => line.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
  for (let i=0; i<lines.length; i++) {
    const line = lines[i];
    if (line.includes("|") && i+1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[i+1])) {
      closeList(); html += "<table><thead><tr>"+cells(line).map(c => "<th>"+inlineMD(c)+"</th>").join("")+"</tr></thead><tbody>"; i++;
      while (i+1<lines.length && lines[i+1].includes("|") && lines[i+1].trim()) { i++; html += "<tr>"+cells(lines[i]).map(c => "<td>"+inlineMD(c)+"</td>").join("")+"</tr>"; }
      html += "</tbody></table>"; continue;
    }
    const li = line.match(/^\s*(?:([-*])|\d+[.)])\s+(.*)$/);
    if (li) { const kind=li[1]?"ul":"ol"; if (list !== kind) { closeList(); list=kind; html+="<"+kind+">"; } html+="<li>"+inlineMD(li[2])+"</li>"; continue; }
    closeList();
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { const lv=h[1].length+1; html+=`<h${lv}>`+inlineMD(h[2])+`</h${lv}>`; }
    else if (/^>\s?/.test(line)) html+="<blockquote>"+inlineMD(line.replace(/^>\s?/,""))+"</blockquote>";
    else if (!line.trim()) html+="<br>";
    else html+="<div>"+inlineMD(line)+"</div>";
  }
  closeList(); return html;
}


const richViews=new WeakMap();
const PREVIEW_LANGS=new Set(['html','svg','javascript','css']);
function codeLanguage(label,code=''){
  const value=String(label||'').trim().split(/\s+/)[0].toLowerCase().replace(/^\{\.?|\}$/g,'');
  const aliases={htm:'html',html5:'html',xhtml:'html','text/html':'html','index.html':'html',js:'javascript',mjs:'javascript',node:'javascript','application/javascript':'javascript',py:'python',sh:'bash','image/svg+xml':'svg'};
  if(value)return aliases[value]||value;
  const start=code.trimStart();
  if(/^<svg\b/i.test(start))return 'svg';
  if(/^<!doctype\s+html\b|^<(?:html|head|body|div|main|section|style|script)\b/i.test(start))return 'html';
  return '';
}
function rawCodeEnd(text,start,root){
  // Skip raw-text elements, comments and CDATA, preserving exact source offsets.
  const tags=/<!--[\s\S]*?(?:-->|$)|<!\[CDATA\[[\s\S]*?(?:\]\]>|$)|<(script|style|textarea|title)\b[^>]*>[\s\S]*?(?:<\/\1\s*>|$)|<\/?([a-z][\w:-]*)\b(?:[^"'<>]|"[^"]*"|'[^']*')*>/gi;
  tags.lastIndex=start;let match,depth=0;
  while((match=tags.exec(text))){
    if(match[1]){
      if(match.index===start&&match[1].toLowerCase()===root)return {end:tags.lastIndex,complete:new RegExp('</'+root+'\\s*>$','i').test(match[0])};
      continue;
    }
    if(!match[2]||match[2].toLowerCase()!==root)continue;
    const closing=/^<\//.test(match[0]),selfClosing=/\/>$/.test(match[0]);
    if(closing){if(root==='html'||--depth<=0)return {end:tags.lastIndex,complete:true};}
    else if(!selfClosing)depth++;
    else if(depth===0)return {end:tags.lastIndex,complete:true};
  }
  return {end:text.length,complete:false};
}
function splitRawCode(text,streaming){
  const result=[],roots=/<!doctype\s+html\b[^>]*>|<(html|svg|head|body|main|section|article|div|form|style|script)\b(?:[^"'<>]|"[^"]*"|'[^']*')*>/gi;
  let offset=0,match;
  while((match=roots.exec(text))){
    const lineStart=text.lastIndexOf('\n',match.index-1)+1;
    if(text.slice(lineStart,match.index).trim())continue;
    const root=(match[1]||'html').toLowerCase(),end=rawCodeEnd(text,match.index,root);
    if(match.index>offset)result.push({kind:'text',text:text.slice(offset,match.index)});
    const trailing=/^\r?\n/.exec(text.slice(end.end));if(trailing)end.end+=trailing[0].length;
    result.push({kind:'code',lang:root==='svg'?'svg':'html',text:text.slice(match.index,end.end),partial:streaming&&!end.complete,raw:true});
    offset=end.end;roots.lastIndex=offset;if(offset===text.length)break;
  }
  if(offset<text.length)result.push({kind:'text',text:text.slice(offset)});
  if(!result.length&&text)result.push({kind:'text',text});
  // Infer other unfenced languages only for source-only messages.
  if(result.length===1&&result[0].kind==='text'){
    const source=text.trimStart();let lang='';
    if(/^(?:#!.*python[^\n]*\n|(?:from\s+[\w.]+\s+import\s+|import\s+\w+|(?:async\s+)?def\s+\w+\s*\())/.test(source))lang='python';
    else if(/^(?:(?:export\s+)?(?:async\s+)?function\s+\w+\s*\(|(?:const|let|var)\s+[\w$]+\s*=)/.test(source))lang='javascript';
    else if(/^(?::root|[.#][\w-]+)\s*\{/.test(source)&&/:\s*[^;\n]+;/.test(source))lang='css';
    if(lang)result[0]={kind:'code',lang,text,partial:streaming,raw:true};
  }
  return result;
}
function richSegments(text,streaming=false){
  const result=[],fences=/^[ \t]{0,3}(\x60{3,}|~{3,})([^\r\n]*)\r?\n/gm;
  let offset=0,match;
  while((match=fences.exec(text))){
    if(match.index<offset)continue;
    if(match.index>offset)result.push(...splitRawCode(text.slice(offset,match.index),streaming));
    const marker=match[1],bodyStart=fences.lastIndex;
    const closer=new RegExp('^[ \\t]{0,3}'+marker[0]+'{'+marker.length+',}[ \\t]*(?:\\r?\\n|$)','gm');
    closer.lastIndex=bodyStart;const end=closer.exec(text),code=text.slice(bodyStart,end?end.index:text.length);
    result.push({kind:'code',lang:codeLanguage(match[2],code),text:code,partial:streaming&&!end});
    offset=end?closer.lastIndex:text.length;fences.lastIndex=offset;if(offset===text.length)break;
  }
  if(offset<text.length)result.push(...splitRawCode(text.slice(offset),streaming));
  const merged=[];
  for(const part of result){
    const last=merged.at(-1),gap=merged.at(-2);
    if(part.kind==='code'&&part.raw&&last?.kind==='code'&&last.raw&&last.lang===part.lang){last.text+=part.text;last.partial=part.partial;}
    else if(part.kind==='code'&&part.raw&&last?.kind==='text'&&!last.text.trim()&&gap?.kind==='code'&&gap.raw&&gap.lang===part.lang){gap.text+=last.text+part.text;gap.partial=part.partial;merged.pop();}
    else merged.push(part);
  }
  return merged;
}
function setLiveText(element, value) {
  const node = element.firstChild;
  if (node?.nodeType === Node.TEXT_NODE && node === element.lastChild) {
    if (value === node.data) return;
    if (value.startsWith(node.data)) {
      node.appendData(value.slice(node.length));
      return;
    }
  }
  element.textContent = value;
}
function codeBlock(lang,code,partial=false){
  const wrap=document.createElement('div');wrap.className='codeblock';
  const head=document.createElement('div');head.className='codehead';
  head.innerHTML='<span class="lang"></span><span class="code-progress" hidden>En curso</span><button class="copy" type="button">Copiar</button><button class="save" type="button" title="Guardar el bloque en un fichero y comprobar que arranca">Guardar</button><button class="eye" type="button" title="Abrir visor de código">Ver código</button><button class="preview" type="button">Vista previa</button>';
  head.querySelector('.code-progress').textContent=uiText('En curso');
  head.querySelector('.copy').textContent=uiText('Copiar');
  const saveButton=head.querySelector('.save');saveButton.textContent=uiText('Guardar');saveButton.title=uiText('Guardar el bloque en un fichero y comprobar que arranca');
  const eyeButton=head.querySelector('.eye');eyeButton.textContent=uiText('Ver código');eyeButton.title=uiText('Abrir visor de código');
  head.querySelector('.preview').textContent=uiText('Vista previa');
  const pre=document.createElement('pre'),source=document.createElement('code');pre.append(source);
  const saveRow=document.createElement('div');saveRow.className='saverow';saveRow.hidden=true;
  wrap.append(head,saveRow,pre);
  wrap._setCode=(language,value,incomplete)=>{
    wrap._codeSource={lang:codeLanguage(language,value),code:value,partial:incomplete};
    head.querySelector('.lang').textContent=wrap._codeSource.lang||uiText('código');
    head.querySelector('.code-progress').hidden=!incomplete;
    head.querySelector('.preview').hidden=!PREVIEW_LANGS.has(wrap._codeSource.lang);
    setLiveText(source, value);
    refreshOpenViewer(wrap);
  };
  head.querySelector('.copy').onclick=()=>navigator.clipboard.writeText(wrap._codeSource.code).then(()=>{head.querySelector('.copy').textContent=uiText('Copiado');setTimeout(()=>head.querySelector('.copy').textContent=uiText('Copiar'),1200);}).catch(()=>note('No se pudo copiar. Selecciona el código y pulsa Ctrl+C.'));
  head.querySelector('.eye').onclick=()=>openViewer(wrap._codeSource.lang,wrap._codeSource.code,wrap);
  head.querySelector('.preview').onclick=()=>{openViewer(wrap._codeSource.lang,wrap._codeSource.code,wrap);previewViewer();};
  // Guardar lo hace el harness, no el modelo: escribe el fichero y comprueba de verdad que
  // arranca. Si falla, el error se convierte en la orden de corrección (con la ruta ya dicha).
  head.querySelector('.save').onclick=()=>{
    if(!saveRow.hidden){saveRow.hidden=true;return;}
    saveRow.hidden=false;saveRow.replaceChildren();
    const lang=(wrap._codeSource||{}).lang||'';
    const nombre=({html:'index.html',css:'styles.css',javascript:'script.js',python:'main.py',json:'data.json',typescript:'main.ts',ts:'main.ts',markdown:'notes.md',bash:'script.sh'})[lang]||'archivo.txt';
    const inp=document.createElement('input');inp.type='text';inp.className='savepath';inp.value=nombre;
    inp.title=uiText('Ruta relativa dentro de la carpeta de trabajo del agente (absoluta solo con "Toda la PC")');
    const go=document.createElement('button');go.type='button';go.textContent=uiText('Guardar y comprobar');
    const salida=document.createElement('span');salida.className='saveout';
    go.onclick=async()=>{
      go.disabled=true;salida.dataset.bad='';salida.textContent=uiText('Comprobando…');
      try{
        const r=await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({path:inp.value.trim(),content:wrap._codeSource.code,conversation_id:currentId})});
        const d=await r.json();
        if(!r.ok||d.error){salida.dataset.bad='1';salida.textContent=uiText('No se guardó:')+' '+(d.error||r.status);return;}
        const v=d.verificacion||{};const ej=v.ejecucion||{};
        if(v.ok===null||v.checked===false){salida.textContent=uiText('Guardado en')+' '+d.path+'. '+uiText('Sin comprobar:')+' '+(v.avisos?.length?v.avisos:v.errores||[]).join(' · ');return;}
        if(v.ok){salida.textContent=uiText('Guardado en')+' '+d.path+' ('+d.bytes+' bytes): '+uiText('sintaxis sin errores')
          +(ej.ok?' '+uiText('y ejecutada en')+' '+ej.navegador+', '+ej.nodos+' '+uiText('nodos, sin errores de consola'):'')+'.';return;}
        salida.dataset.bad='1';
        salida.textContent=uiText('Guardado en')+' '+d.path+'. '+uiText('Errores de comprobación:')+' '+(v.errores||[]).join(' · ');
        const fix=document.createElement('button');fix.type='button';fix.textContent=uiText('Que lo corrija');
        fix.onclick=()=>{
          $('#input').value='El archivo '+d.path+' presenta estos errores de comprobación: '+
            (v.errores||[]).join(' · ')+((v.avisos||[]).length?' Avisos: '+v.avisos.join(' · '):'')+
            '. Corrige el archivo existente, conserva el resto y verifica el cambio. Si faltan herramientas, muestra el cambio necesario.';
          saveRow.hidden=true;sendMsg();
        };
        saveRow.append(fix);
      }catch(e){salida.dataset.bad='1';salida.textContent=uiText('Fallo al guardar:')+' '+e;}
      finally{go.disabled=false;}
    };
    saveRow.append(inp,go,salida);inp.focus();inp.select();
  };
  wrap._setCode(lang,code,partial);return wrap;
}
function renderMarkdownProse(view,text){
  const blocks=text.split(/\n[ \t]*\n/),previous=view.proseBlocks||[],next=[];
  view.node.className='markdown-prose';
  blocks.forEach((source,index)=>{
    const block=previous[index]||{node:document.createElement('div')};
    if(block.source!==source){block.node.innerHTML=mdHTML(source);block.source=source;}
    if(view.node.childNodes[index]!==block.node)view.node.insertBefore(block.node,view.node.childNodes[index]||null);
    next.push(block);
  });
  while(view.node.childNodes.length>next.length)view.node.lastChild.remove();
  view.proseBlocks=next;
}
function renderRich(el,text,{streaming=false}={}){
  el.classList.add('md');text=String(text||'');
  const parts=richSegments(text,streaming),previous=richViews.get(el)||[],next=[];
  parts.forEach((part,index)=>{
    let view=previous[index];
    if(!view||view.kind!==part.kind||view.lang!==part.lang)view={kind:part.kind,lang:part.lang,node:part.kind==='code'?codeBlock(part.lang,part.text,part.partial):document.createElement('div')};
    if(view.text!==part.text||view.streaming!==streaming||view.partial!==part.partial){
      if(part.kind==='code')view.node._setCode(part.lang,part.text,part.partial);
      else renderMarkdownProse(view,part.text);
      view.text=part.text;view.streaming=streaming;view.partial=part.partial;
    }
    if(el.childNodes[index]!==view.node)el.insertBefore(view.node,el.childNodes[index]||null);
    next.push(view);
  });
  while(el.childNodes.length>next.length)el.lastChild.remove();
  richViews.set(el,next);
}
let viewerCode='',viewerLang='',viewerSource=null,viewerPreviewCode=null,viewerURL=null,viewerTicket=null,viewerWaiting=false;
function previewStatus(text='',error=false){
  const status=$('#vstatus');status.textContent=text;status.hidden=!text;status.dataset.error=String(error);
}
function clearPreview(){
  viewerTicket=null;viewerWaiting=false;
  const old=$('#vframe'),frame=document.createElement('iframe');
  frame.id='vframe';frame.title=uiText('Vista previa del código');frame.setAttribute('sandbox','allow-scripts allow-modals');
  frame.style.display='none';old.replaceWith(frame);
  if(viewerURL){URL.revokeObjectURL(viewerURL);viewerURL=null;}
  previewStatus();
}
function refreshOpenViewer(source){
  if(viewerSource!==source||!$('#viewer').open)return;
  const value=source._codeSource;viewerCode=value.code;viewerLang=value.lang;
  $('#vcode').textContent=viewerCode;
  $('#vtitle').textContent=uiText('Código')+(viewerLang?' · '+viewerLang:'')+(value.partial?' · '+uiText('en curso'):'');
  $('#vtabPrev').textContent=uiText(viewerPreviewCode!==null&&viewerPreviewCode!==viewerCode?'Actualizar vista':'Vista previa');
  if(viewerWaiting&&!value.partial)previewViewer();
}
function openViewer(lang,code,source=null){
  viewerLang=codeLanguage(lang,code);viewerCode=code;viewerSource=source;viewerPreviewCode=null;
  hideHelp();closeChatControls(false);
  $('#vtitle').textContent=uiText('Código')+(viewerLang?' · '+viewerLang:'')+(source?._codeSource.partial?' · '+uiText('en curso'):'');
  clearPreview();$('#vcode').textContent=code;$('#vcode').style.display='block';
  $('#vtabPrev').hidden=!PREVIEW_LANGS.has(viewerLang);$('#vtabPrev').style.display='';$('#vtabPrev').textContent=uiText('Vista previa');
  $('#vtabCode').setAttribute('aria-pressed','true');$('#vtabPrev').setAttribute('aria-pressed','false');
  if(!$('#viewer').open)$('#viewer').showModal();
}
function previewViewer(){
  // Never run a half-written page/script. A requested preview opens once its
  // block is complete, without restarting a timer on every streamed token.
  clearPreview();
  $('#vtabCode').setAttribute('aria-pressed','false');$('#vtabPrev').setAttribute('aria-pressed','true');
  $('#vcode').style.display='none';
  if(viewerSource?._codeSource.partial){
    viewerWaiting=true;previewStatus(uiText('Esperando a que termine el bloque…'));return;
  }
  let doc=viewerCode;
  if(viewerLang==='svg')doc='<!doctype html><html><body>'+viewerCode+'</body></html>';
  else if(viewerLang==='css')doc='<!doctype html><html><head><style>'+viewerCode+'</style></head><body><h1>'+uiText('Vista previa')+'</h1><p>'+uiText('Texto de ejemplo.')+'</p><button>'+uiText('Botón')+'</button></body></html>';
  else if(viewerLang==='javascript'){
    const closeScript='<'+'/script>',source=viewerCode.replace(/<\/script/gi,'<\\/script');
    doc='<!doctype html><html><body><pre id="log" style="font:12px monospace;white-space:pre-wrap"></pre><script>(()=>{const output=(...a)=>{document.getElementById("log").textContent+=a.join(" ")+"\\n"};console.log=output;console.error=output;window.onerror=(m)=>output("Error: "+m);})();'+closeScript+'<script>'+source+closeScript+'</body></html>';
  }
  const ticket=crypto.randomUUID();viewerTicket=ticket;
  // The monitor belongs only to the local preview, not to the copied code or
  // model prompt. Opaque-origin sandboxing remains in place.
  const closeScript='<'+'/script>';
  const monitor='<script>(()=>{const send=(state,detail="")=>parent.postMessage({strataPreview:'+JSON.stringify(ticket)+',state,detail},"*");window.addEventListener("error",e=>send("error",e.message||"Error al ejecutar el código"));window.addEventListener("unhandledrejection",e=>send("error",String(e.reason?.message||e.reason||"Promesa rechazada")));window.addEventListener("DOMContentLoaded",()=>{const body=document.body,visible=body&&[...body.querySelectorAll("*")].some(e=>!e.matches("script,style,link,meta,template")&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0);send(visible||body?.innerText.trim()?"ready":"empty");});})();'+closeScript;
  const opening=/<head\b[^>]*>/i.exec(doc)||/<html\b[^>]*>/i.exec(doc)||/<!doctype\b[^>]*>/i.exec(doc);
  doc=opening?doc.slice(0,opening.index+opening[0].length)+monitor+doc.slice(opening.index+opening[0].length):monitor+doc;
  viewerURL=URL.createObjectURL(new Blob([doc],{type:'text/html;charset=utf-8'}));
  $('#vframe').src=viewerURL;$('#vframe').style.display='block';previewStatus(uiText('Cargando vista previa…'));
  viewerPreviewCode=viewerCode;$('#vtabPrev').textContent=uiText('Vista previa');
}
window.addEventListener('message',event=>{
  if(event.source!==$('#vframe').contentWindow||event.data?.strataPreview!==viewerTicket||!viewerTicket)return;
  if(event.data.state==='error')previewStatus(uiText('Error en la vista previa:')+' '+String(event.data.detail?uiText(event.data.detail):uiText('No se pudo ejecutar el código.')).slice(0,500),true);
  else if($('#vstatus').dataset.error!=='true'){
    if(event.data.state==='ready')previewStatus();
    else if(event.data.state==='empty')previewStatus(uiText('El bloque no contiene elementos visibles. Revisa que incluya el HTML completo.'));
  }
});
$('#vtabCode').onclick=()=>{viewerWaiting=false;previewStatus();$('#vcode').style.display='block';$('#vframe').style.display='none';$('#vtabCode').setAttribute('aria-pressed','true');$('#vtabPrev').setAttribute('aria-pressed','false');};
$('#vtabPrev').onclick=previewViewer;
$('#vcopy').onclick=()=>navigator.clipboard.writeText(viewerCode).then(()=>note('Código copiado.')).catch(()=>note('No se pudo copiar. Selecciona el código y pulsa Ctrl+C.'));
$('#vclose').onclick=()=>$('#viewer').close();
$('#viewer').addEventListener('close',()=>{clearPreview();viewerSource=null;viewerPreviewCode=null;});
