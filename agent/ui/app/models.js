/* Modelos: discover GGUF models on Hugging Face (stats, rendered README, verified download) and
   move models with their settings between V-Agent, LM Studio and Unsloth Studio. */
(()=>{
  const T=text=>typeof uiText==='function'?uiText(text):text;
  const api=(url,body)=>requestJSON(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const bytes=n=>{n=Number(n)||0;if(n<2**20)return Math.max(1,Math.round(n/1024))+' KB';if(n<2**30)return (n/2**20).toFixed(0)+' MB';return (n/2**30).toFixed(n<10*2**30?2:1)+' GB';};
  const count=n=>{n=Number(n)||0;return n>=1e9?(n/1e9).toFixed(n>=1e10?0:1)+' B':n>=1e6?(n/1e6).toFixed(n>=1e7?0:1)+' M':n>=1e3?(n/1e3).toFixed(n>=1e4?0:1)+' k':String(n);};
  const date=value=>{if(!value)return '';const d=new Date(value);return isNaN(d)?'':d.toLocaleDateString(window.VALI18n?.language||undefined,{year:'numeric',month:'short',day:'numeric'});};
  const icon=path=>'<svg viewBox="0 0 24 24" aria-hidden="true">'+path+'</svg>';
  const ICONS={models:'<path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',down:'<path d="M12 4v11m-5-5 5 5 5-5M5 20h14"/>',heart:'<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z"/>',
    clock:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',chip:'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3"/>',ext:'<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',search:'<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>'};
  let win=null,transfer=null,current=null,hardware={vram_mib:0,ram_gib:0},jobs=[],folder='',poll=0,searchTimer=0,scanData=null,searchSeq=0;

  // ---------------------------------------------------------------- README rendering (safe subset)
  const TAGS=new Set(['p','div','span','a','img','br','hr','h1','h2','h3','h4','h5','h6','ul','ol','li','table','thead','tbody','tr','th','td','strong','em','b','i','u','s','del','code','pre','blockquote','details','summary','sup','sub','center','picture','source','kbd','small']);
  const ATTRS={a:['href','title'],img:['src','alt','width','height','title'],source:['srcset','media'],td:['colspan','rowspan','align'],th:['colspan','rowspan','align'],p:['align'],div:['align'],h1:['align'],h2:['align'],h3:['align']};
  function absolute(url,repo,raw){
    url=String(url||'').trim();if(!url||/^(javascript|data|vbscript):/i.test(url))return '';
    if(/^https?:\/\//i.test(url))return url.replace(/^http:/i,'https:');
    if(url.startsWith('#'))return '';
    const clean=url.replace(/^\.?\//,'');
    return 'https://huggingface.co/'+repo+(raw?'/resolve/main/':'/blob/main/')+clean;
  }
  function inline(text,repo){
    const codes=[];
    let out=esc(text).replace(/`([^`]+)`/g,(_,c)=>'\u0000'+(codes.push(c)-1)+'\u0000');
    out=out.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g,(_,alt,src)=>{const url=absolute(src.replace(/&amp;/g,'&'),repo,true);return url?'<img alt="'+alt+'" src="'+esc(url)+'">':alt;})
      .replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g,(_,label,href)=>{const url=absolute(href.replace(/&amp;/g,'&'),repo,false);return url?'<a href="'+esc(url)+'">'+label+'</a>':label;})
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g,(_,pre,url)=>pre+'<a href="'+url+'">'+url+'</a>')
      .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g,'$1<em>$2</em>').replace(/~~([^~]+)~~/g,'<del>$1</del>');
    // Inline HTML that READMEs commonly use (<img>, <a>, <br>, <sup>…) is restored and sanitized later.
    out=out.replace(/&lt;(\/?(?:img|a|br|sup|sub|b|i|u|strong|em|span|kbd|small|code|picture|source|center|div|p|details|summary|hr)\b(?:(?!&gt;|&lt;).)*?)&gt;/gi,(_,tag)=>'<'+tag.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&').replace(/\b(src|href)=(["'])([^"']*)\2/gi,(m,attr,q,url)=>attr+'="'+esc(absolute(url,repo,attr.toLowerCase()==='src'))+'"')+'>');
    return out.replace(/\u0000(\d+)\u0000/g,(_,i)=>'<code>'+codes[+i]+'</code>');
  }
  function markdown(source,repo){
    source=String(source||'').replace(/\r\n?/g,'\n').replace(/^---\n[\s\S]*?\n---\n/,'');
    const lines=source.split('\n');let html='',list=[],para=[];
    const flush=()=>{if(para.length){html+='<p>'+inline(para.join(' '),repo)+'</p>';para=[];}};
    const closeLists=(depth=0)=>{while(list.length>depth)html+='</'+list.pop().kind+'>';};
    const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
    for(let i=0;i<lines.length;i++){
      const line=lines[i];
      const fence=line.match(/^\s*(```|~~~)\s*([\w+-]*)/);
      if(fence){flush();closeLists();const body=[];i++;while(i<lines.length&&!lines[i].trim().startsWith(fence[1])){body.push(lines[i]);i++;}html+='<pre><code>'+esc(body.join('\n'))+'</code></pre>';continue;}
      if(/^\s*</.test(line)&&!/^\s*<(img|a|br|b|i|strong|em|sup|sub|code|span)\b/i.test(line)){flush();closeLists();const block=[line];while(i+1<lines.length&&lines[i+1].trim()){i++;block.push(lines[i]);}html+=block.join('\n').replace(/(src|href)=["']([^"']+)["']/gi,(_,attr,url)=>attr+'="'+esc(absolute(url,repo,attr.toLowerCase()==='src'))+'"');continue;}
      if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i+1])){
        flush();closeLists();html+='<table><thead><tr>'+cells(line).map(c=>'<th>'+inline(c,repo)+'</th>').join('')+'</tr></thead><tbody>';i++;
        while(i+1<lines.length&&lines[i+1].includes('|')&&lines[i+1].trim()){i++;html+='<tr>'+cells(lines[i]).map(c=>'<td>'+inline(c,repo)+'</td>').join('')+'</tr>';}
        html+='</tbody></table>';continue;
      }
      const heading=line.match(/^(#{1,6})\s+(.*?)\s*#*$/);
      if(heading){flush();closeLists();const level=Math.min(6,heading[1].length+1);html+='<h'+level+'>'+inline(heading[2],repo)+'</h'+level+'>';continue;}
      if(/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(line)){flush();closeLists();html+='<hr>';continue;}
      const item=line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
      if(item){
        flush();const depth=Math.floor(item[1].replace(/\t/g,'    ').length/2)+1,kind=/\d/.test(item[2])?'ol':'ul';
        while(list.length<depth){list.push({kind});html+='<'+kind+'>';}
        closeLists(depth);if(list[depth-1].kind!==kind){html+='</'+list.pop().kind+'>';list.push({kind});html+='<'+kind+'>';}
        html+='<li>'+inline(item[3].replace(/^\[( |x)\]\s*/i,(_,x)=>x.trim()?'☑ ':'☐ '),repo)+'</li>';continue;
      }
      if(/^\s*>/.test(line)){flush();closeLists();const quote=[];while(i<lines.length&&/^\s*>/.test(lines[i])){quote.push(lines[i].replace(/^\s*>\s?/,''));i++;}i--;html+='<blockquote>'+markdown(quote.join('\n'),repo)+'</blockquote>';continue;}
      if(!line.trim()){flush();closeLists();continue;}
      if(list.length&&/^\s{2,}\S/.test(line)){html=html.replace(/<\/li>$/,' '+inline(line.trim(),repo)+'</li>');continue;}
      closeLists();para.push(line.trim());
    }
    flush();closeLists();return html;
  }
  function sanitize(html){
    const doc=new DOMParser().parseFromString('<div>'+html+'</div>','text/html'),root=doc.body.firstChild;
    const walk=node=>{
      for(const child of [...node.childNodes]){
        if(child.nodeType===3)continue;
        if(child.nodeType!==1){child.remove();continue;}
        const tag=child.tagName.toLowerCase();
        if(!TAGS.has(tag)){if(['script','style','iframe','object','embed','form','input','button','textarea','select','svg','math','link','meta'].includes(tag))child.remove();else{walk(child);child.replaceWith(...child.childNodes);}continue;}
        const allowed=ATTRS[tag]||[];
        for(const attr of [...child.attributes]){
          const name=attr.name.toLowerCase();
          if(!allowed.includes(name)){child.removeAttribute(attr.name);continue;}
          if((name==='href'||name==='src')&&!/^https:\/\//i.test(attr.value))child.removeAttribute(attr.name);
          if(name==='srcset'&&!/^https:\/\//i.test(attr.value.trim()))child.removeAttribute(attr.name);
        }
        if(tag==='a'){child.target='_blank';child.rel='noopener noreferrer';}
        if(tag==='img'){child.loading='lazy';child.decoding='async';child.referrerPolicy='no-referrer';}
        walk(child);
      }
    };
    walk(root);return root.innerHTML;
  }
  const readmeHTML=(text,repo)=>sanitize(markdown(text,repo));

  // ---------------------------------------------------------------- window
  function build(){
    win=document.createElement('section');win.id='modelsWindow';win.setAttribute('role','dialog');win.setAttribute('aria-labelledby','modelsTitle');win.hidden=true;
    win.innerHTML='<header class="fw-head models-head"><h2 id="modelsTitle">Modelos</h2>'+
      '<button class="icon-btn" type="button" data-fw-close aria-label="Cerrar" title="Cerrar">×</button></header>'+
      '<div class="models-body">'+
      '<div class="models-pane" data-pane="discover">'+
        '<aside class="hub-list"><div class="hub-search"><span class="hub-search-icon">'+icon(ICONS.search)+'</span><input id="hubQuery" type="search" placeholder="Buscar en Hugging Face…" aria-label="Buscar modelos GGUF en Hugging Face" autocomplete="off"></div>'+
        '<div class="hub-filters"><select id="hubKind" aria-label="Tipo de modelo"><option value="text">Texto</option><option value="vision">Visión</option><option value="all">Todos</option></select>'+
        '<select id="hubSort" aria-label="Ordenar"><option value="downloads">Más descargados</option><option value="trending">Tendencia</option><option value="likes">Más valorados</option><option value="updated">Actualizados</option></select></div>'+
        '<div id="hubResults" class="hub-results" role="listbox" aria-label="Resultados"></div></aside>'+
        '<article id="hubDetail" class="hub-detail"><div class="hub-empty">'+icon(ICONS.models)+'<p>Elige un modelo para ver sus estadísticas, archivos y ficha.</p></div></article>'+
      '</div>'+
      '<div class="models-pane" data-pane="transfer" hidden>'+
        '<section class="transfer-block"><div class="transfer-head"><div><h3>Traer desde otras apps</h3><p class="mini" id="transferSources"></p></div><button id="transferScan" type="button">Buscar de nuevo</button></div>'+
        '<div class="transfer-tools"><label class="chk"><input type="checkbox" id="transferAll"> Seleccionar todo</label><span id="transferCount" class="mini"></span><button id="transferImport" type="button" disabled>Importar seleccionados</button></div>'+
        '<div id="transferList" class="transfer-list"></div><p id="transferStatus" class="mini" role="status"></p></section>'+
        '<section class="transfer-block"><h3>Enviar ajustes de V-Agent</h3><p class="mini">Parámetros de muestreo, contexto, caché KV y plantilla de chat del modelo elegido.</p>'+
        '<div class="transfer-export"><select id="exportModel" aria-label="Modelo de V-Agent"></select><button id="exportLm" type="button">A LM Studio</button><button id="exportUnsloth" type="button">A Unsloth Studio</button><button id="exportFile" type="button">Guardar archivo</button></div>'+
        '<div class="transfer-export"><input type="file" id="importFile" accept=".json,application/json" hidden><button id="importFileBtn" type="button" class="text-btn">Importar archivo de ajustes…</button></div>'+
        '<p id="exportStatus" class="mini" role="status"></p></section>'+
      '</div></div>'+
      '<footer class="models-foot"><span class="models-folder">'+icon(ICONS.down)+'<span id="hubFolder"></span></span><button id="hubFolderChange" type="button" class="text-btn">Cambiar carpeta</button><div id="hubJobs" class="hub-jobs"></div></footer>';
    document.body.append(win);
    const transferSection=document.createElement('details');transferSection.id='modelTransfer';transferSection.className='settings-group model-transfer';
    const transferTitle=document.createElement('summary');transferTitle.textContent=T('Importar y exportar');
    transfer=win.querySelector('[data-pane="transfer"]');transfer.hidden=false;transferSection.append(transferTitle,transfer);
    document.getElementById('controls-model').append(transferSection);
    transferSection.addEventListener('toggle',()=>{if(transferSection.open){scan();fillExportModels();}});
    window.VALWindows?.register('models',win,{onOpen:()=>{refreshJobs();if(!document.querySelector('#hubResults .hub-item'))search();},onClose:()=>clearInterval(poll)});
    const query=win.querySelector('#hubQuery');query.oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(search,380);};
    query.onkeydown=event=>{if(event.key==='Enter'){clearTimeout(searchTimer);search();}};
    win.querySelector('#hubSort').onchange=search;win.querySelector('#hubKind').onchange=search;
    win.querySelector('#hubFolderChange').onclick=changeFolder;
    transfer.querySelector('#transferScan').onclick=scan;
    transfer.querySelector('#transferAll').onchange=event=>{transfer.querySelectorAll('#transferList input[type=checkbox]:not(:disabled)').forEach(box=>box.checked=event.target.checked);syncTransfer();};
    transfer.querySelector('#transferImport').onclick=importSelected;
    transfer.querySelector('#exportLm').onclick=()=>exportTo('lmstudio');
    transfer.querySelector('#exportUnsloth').onclick=()=>exportTo('unsloth');
    transfer.querySelector('#exportFile').onclick=()=>exportTo('file');
    transfer.querySelector('#importFileBtn').onclick=()=>transfer.querySelector('#importFile').click();
    transfer.querySelector('#importFile').onchange=importFile;
    window.VALI18n?.observe?.(win);window.VALI18n?.observe?.(transferSection);
  }
  function open(tab){if(!win)build();if(tab==='transfer'){setChatControls('model');document.getElementById('modelTransfer').open=true;}else window.VALWindows?.open('models');}

  // ---------------------------------------------------------------- discover
  async function search(){
    const seq=++searchSeq,box=win.querySelector('#hubResults');
    box.setAttribute('aria-busy','true');if(!box.children.length)box.innerHTML='<p class="mini hub-note">'+esc(T('Buscando…'))+'</p>';
    try{
      const q=win.querySelector('#hubQuery').value.trim(),sort=win.querySelector('#hubSort').value,kind=win.querySelector('#hubKind').value;
      const data=await api('/api/harness/hub/search?q='+encodeURIComponent(q)+'&sort='+encodeURIComponent(sort)+'&kind='+encodeURIComponent(kind));
      if(seq!==searchSeq)return;
      if(!data.models.length){box.innerHTML='<p class="mini hub-note">'+esc(T('Sin resultados.'))+'</p>';return;}
      box.replaceChildren(...data.models.map(model=>{
        const [author,name]=model.id.split('/');const item=document.createElement('button');item.type='button';item.className='hub-item';item.setAttribute('role','option');item.dataset.repo=model.id;
        item.innerHTML='<span class="hub-item-name">'+esc(name)+'</span><span class="hub-item-author">'+esc(author)+'</span><span class="hub-item-stats"><span>'+icon(ICONS.down)+count(model.downloads)+'</span><span>'+icon(ICONS.heart)+count(model.likes)+'</span><span>'+esc(date(model.updated))+'</span></span>';
        item.onclick=()=>show(model.id);if(current?.id===model.id)item.setAttribute('aria-selected','true');return item;
      }));
    }catch(error){if(seq===searchSeq)box.innerHTML='<p class="mini hub-note" data-error="1">'+esc(error.message)+'</p>';}
    finally{if(seq===searchSeq)box.removeAttribute('aria-busy');}
  }
  function fit(size){
    const vram=(hardware.vram_mib||0)*2**20,ram=(hardware.ram_gib||0)*2**30;
    if(vram&&size<=vram*0.85)return ['gpu',T('Cabe en la GPU')];
    if(size<=vram*0.85+ram*0.55)return ['mixed',vram?T('GPU + RAM'):T('Cabe en RAM')];
    return ['big',T('Demasiado grande')];
  }
  async function show(repo){
    win.querySelectorAll('.hub-item').forEach(item=>item.setAttribute('aria-selected',String(item.dataset.repo===repo)));
    const box=win.querySelector('#hubDetail');box.setAttribute('aria-busy','true');
    box.innerHTML='<div class="hub-empty"><p>'+esc(T('Cargando ficha…'))+'</p></div>';
    try{
      const data=await api('/api/harness/hub/model?repo='+encodeURIComponent(repo));
      current=data;hardware=data.hardware||hardware;
      const chips=[[ICONS.down,count(data.downloads)+' '+T('descargas')],[ICONS.heart,count(data.likes)],[ICONS.clock,date(data.updated)],
        data.architecture&&[ICONS.chip,data.architecture],data.context&&[null,count(data.context)+' '+T('de contexto')],data.parameters&&[null,count(data.parameters).replace(' ','')+' '+T('parámetros')],data.license&&[null,data.license]].filter(Boolean);
      const files=data.files.length?data.files.map(file=>{
        const [kind,label]=fit(file.size);const job=jobs.find(j=>j.repo===data.id&&j.name===file.name);
        return '<tr data-file="'+esc(file.name)+'"><td><strong>'+esc(file.quant||file.name.split('/').pop().replace(/\.gguf$/i,''))+'</strong><small>'+esc(file.name.split('/').pop())+(file.parts.length>1?' · '+file.parts.length+' '+T('partes'):'')+'</small></td>'+
          '<td class="num">'+bytes(file.size)+'</td><td>'+(file.mmproj?'<span class="fit-badge" data-fit="vision">'+esc(T('Visión (mmproj)'))+'</span>':'<span class="fit-badge" data-fit="'+kind+'">'+esc(label)+'</span>')+'</td>'+
          '<td class="act">'+downloadCell(job)+'</td></tr>';
      }).join(''):'<tr><td colspan="4" class="mini">'+esc(T('Este repositorio no tiene archivos GGUF.'))+'</td></tr>';
      box.innerHTML='<header class="hub-detail-head"><div><span class="hub-detail-author">'+esc(data.author)+'</span><h3>'+esc(data.id.split('/')[1]||data.id)+'</h3></div>'+
        '<a class="hub-open" href="'+esc(data.url)+'" target="_blank" rel="noopener noreferrer">'+icon(ICONS.ext)+'<span>'+esc(T('Abrir en Hugging Face'))+'</span></a></header>'+
        '<div class="hub-chips">'+chips.map(([path,text])=>'<span class="hub-chip">'+(path?icon(path):'')+esc(text)+'</span>').join('')+(data.gated?'<span class="hub-chip" data-warn="1">'+esc(T('Acceso restringido'))+'</span>':'')+'</div>'+
        '<table class="hub-files"><thead><tr><th>'+esc(T('Archivo'))+'</th><th class="num">'+esc(T('Tamaño'))+'</th><th>'+esc(T('Tu equipo'))+'</th><th></th></tr></thead><tbody>'+files+'</tbody></table>'+
        '<div class="hub-readme markdown-prose">'+(data.readme?readmeHTML(data.readme,data.id):'<p class="mini">'+esc(T('Este modelo no publica una ficha (README).'))+'</p>')+'</div>';
      box.querySelectorAll('[data-download]').forEach(button=>button.onclick=()=>download(data.id,button.closest('tr').dataset.file));
      box.querySelectorAll('[data-cancel]').forEach(button=>button.onclick=()=>cancel(button.dataset.cancel));
      box.scrollTop=0;
    }catch(error){box.innerHTML='<div class="hub-empty"><p data-error="1">'+esc(error.message)+'</p></div>';}
    finally{box.removeAttribute('aria-busy');}
  }
  function downloadCell(job){
    if(!job||job.state==='cancelled')return '<button type="button" data-download>'+icon(ICONS.down)+'<span>'+esc(T('Descargar GGUF'))+'</span></button>';
    if(job.state==='done')return '<span class="hub-done">'+esc(T(job.model?'Añadido':'Descargado'))+'</span>';
    if(job.state==='error')return '<button type="button" data-download title="'+esc(job.error)+'">'+esc(T('Reintentar'))+'</button>';
    const pct=job.total?Math.floor(job.received*100/job.total):0;
    return '<div class="hub-progress"><progress max="100" value="'+pct+'"></progress><span>'+(job.state==='verifying'?esc(T('Verificando…')):pct+'%')+'</span><button type="button" class="text-btn" data-cancel="'+esc(job.id)+'">'+esc(T('Cancelar'))+'</button></div>';
  }
  async function download(repo,file){
    try{const data=await api('/api/harness/hub/download',{repo,file});applyJobs(data);startPolling();}catch(error){note(error.message);}
  }
  async function cancel(id){try{applyJobs(await api('/api/harness/hub/cancel',{id}));}catch(error){note(error.message);}}
  function applyJobs(data){
    const before=new Map(jobs.map(job=>[job.id,job.state]));
    jobs=data.jobs||[];folder=data.folder||folder;
    win.querySelector('#hubFolder').textContent=folder;win.querySelector('#hubFolder').title=folder;
    const active=jobs.filter(job=>['queued','downloading','verifying'].includes(job.state));
    win.querySelector('#hubJobs').innerHTML=active.map(job=>{const pct=job.total?Math.floor(job.received*100/job.total):0;return '<span class="hub-job" title="'+esc(job.repo+' · '+job.name)+'"><span>'+esc(job.name.split('/').pop())+'</span><progress max="100" value="'+pct+'"></progress><b>'+pct+'%</b></span>';}).join('');
    if(current)for(const row of win.querySelectorAll('#hubDetail tr[data-file]')){
      const job=jobs.find(j=>j.repo===current.id&&j.name===row.dataset.file);const cell=row.querySelector('.act');const html=downloadCell(job);
      if(cell.dataset.html!==html){cell.dataset.html=html;cell.innerHTML=html;cell.querySelector('[data-download]')?.addEventListener('click',()=>download(current.id,row.dataset.file));cell.querySelector('[data-cancel]')?.addEventListener('click',event=>cancel(event.currentTarget.dataset.cancel));}
    }
    for(const job of jobs){
      if(job.state==='done'&&before.has(job.id)&&before.get(job.id)!=='done'){note(T(job.model?'Modelo descargado y añadido.':'Archivo descargado.'));document.getElementById('refreshModels')?.click();}
      if(job.state==='error'&&before.get(job.id)!=='error'&&before.has(job.id))note(job.error);
    }
    if(!active.length)clearInterval(poll);
  }
  async function refreshJobs(){try{applyJobs(await api('/api/harness/hub/downloads'));if(jobs.some(job=>['queued','downloading','verifying'].includes(job.state)))startPolling();}catch{}}
  function startPolling(){clearInterval(poll);poll=setInterval(refreshJobs,1000);}
  async function changeFolder(){
    try{const picked=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'project'}),signal:AbortSignal.timeout(310000)});
      if(picked.path)applyJobs(await api('/api/harness/hub/folder',{path:picked.path}));}catch(error){note(error.message);}
  }

  // ---------------------------------------------------------------- import / export
  const SOURCE={lmstudio:'LM Studio',unsloth:'Unsloth Studio'};
  function summary(item){
    const parts=[];const s=item.sampling||{};
    if(item.context)parts.push(count(item.context)+' ctx');
    if(item.kv)parts.push('KV '+item.kv.toUpperCase());
    if(s.temperature!==undefined)parts.push('T '+s.temperature);
    if(s.top_p!==undefined)parts.push('top-p '+s.top_p);
    if(s.top_k!==undefined)parts.push('top-k '+s.top_k);
    if(s.min_p!==undefined)parts.push('min-p '+s.min_p);
    if(s.repetition_penalty!==undefined)parts.push(T('rep.')+' '+s.repetition_penalty);
    if(item.template)parts.push(T('plantilla propia'));
    return parts.join(' · ')||T('Sin ajustes guardados; usará los predeterminados.');
  }
  async function scan(){
    const list=transfer.querySelector('#transferList');list.innerHTML='<p class="mini hub-note">'+esc(T('Buscando modelos en este equipo…'))+'</p>';
    try{
      scanData=await api('/api/harness/external/scan');
      const sources=Object.entries(scanData.sources).map(([key,src])=>SOURCE[key]+': '+(src.available?src.folder:T('no encontrado'))).join(' · ');
      transfer.querySelector('#transferSources').textContent=sources;
      if(!scanData.models.length){list.innerHTML='<p class="mini hub-note">'+esc(T('No se encontraron modelos GGUF de LM Studio ni de Unsloth Studio.'))+'</p>';syncTransfer();return;}
      list.replaceChildren(...scanData.models.map((item,index)=>{
        const row=document.createElement('label');row.className='transfer-row';
        row.innerHTML='<input type="checkbox" data-index="'+index+'"><span class="transfer-main"><strong></strong><small></small></span><span class="transfer-source" data-source="'+item.source+'">'+SOURCE[item.source]+'</span><span class="transfer-size">'+bytes(item.size)+'</span>';
        row.querySelector('strong').textContent=item.name;row.querySelector('small').textContent=(item.registered?T('Ya está en V-Agent')+' · ':'')+summary(item);row.title=item.path;
        row.querySelector('input').onchange=syncTransfer;return row;
      }));
    }catch(error){list.innerHTML='<p class="mini hub-note" data-error="1">'+esc(error.message)+'</p>';}
    syncTransfer();
  }
  function selected(){return [...transfer.querySelectorAll('#transferList input:checked')].map(box=>scanData.models[+box.dataset.index]);}
  function syncTransfer(){const n=selected().length;transfer.querySelector('#transferImport').disabled=!n;transfer.querySelector('#transferCount').textContent=n?n+' '+T('seleccionados'):'';}
  async function importItems(items,status){
    status.textContent=T('Importando…');
    try{
      const data=await api('/api/harness/external/import',{items:items.map(item=>({path:item.path,name:item.name,sampling:item.sampling,context:item.context,kv:item.kv,template:item.template}))});
      const ok=data.results.filter(r=>!r.error),bad=data.results.filter(r=>r.error);
      const warnings=ok.flatMap(r=>r.warnings||[]);
      status.textContent=ok.length+' '+T('importados')+(bad.length?' · '+bad.length+' '+T('con error')+': '+bad.map(r=>r.error).join(' · '):'')+(warnings.length?' · '+warnings.join(' · '):'');
      document.getElementById('refreshModels')?.click();
      return data;
    }catch(error){status.textContent=error.message;}
  }
  async function importSelected(){const button=transfer.querySelector('#transferImport');button.disabled=true;await importItems(selected(),transfer.querySelector('#transferStatus'));await scan();}
  async function fillExportModels(){
    const select=transfer.querySelector('#exportModel');
    try{const data=await api('/api/models');const models=(data.models||data.data||[]).filter(m=>!m.remote);
      select.replaceChildren(...models.map(m=>{const o=document.createElement('option');o.value=m.id;o.textContent=m.display_name||m.gguf_name||m.id;return o;}));
      if(!models.length){const o=document.createElement('option');o.value='';o.textContent=T('No hay modelos locales');select.append(o);}
    }catch{}
  }
  async function exportTo(target){
    const model=transfer.querySelector('#exportModel').value,status=transfer.querySelector('#exportStatus');
    if(!model){status.textContent=T('Elige un modelo.');return;}
    try{
      const data=await api('/api/harness/external/export',{model,target});
      if(target==='file'){
        const blob=new Blob([JSON.stringify(data.file,null,2)],{type:'application/json'}),link=document.createElement('a');
        link.href=URL.createObjectURL(blob);link.download='v-agent-'+(data.file.models[0].name||'modelo').replace(/[^\p{L}\p{N}_.-]+/gu,'-').slice(0,60)+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
        status.textContent=T('Archivo de ajustes guardado.');
      }else status.textContent=T('Ajustes escritos en')+' '+data.written;
    }catch(error){status.textContent=error.message;}
  }
  async function importFile(event){
    const file=event.target.files[0];event.target.value='';if(!file)return;const status=transfer.querySelector('#exportStatus');
    try{
      const data=JSON.parse(await file.text());
      if(data.type!=='v-agent-model-settings'||!Array.isArray(data.models))throw new Error(T('No es un archivo de ajustes de V-Agent.'));
      await importItems(data.models,status);
    }catch(error){status.textContent=error.message;}
  }

  // ---------------------------------------------------------------- entry points
  function addSidebarEntry(){
    const extras=document.getElementById('sidebarExtras');if(!extras||document.getElementById('sidebarModels'))return !!extras;
    const button=document.createElement('button');button.id='sidebarModels';button.type='button';button.className='sidebar-extra';button.title=T('Descubrir, descargar, importar y exportar modelos');
    button.innerHTML=icon(ICONS.models)+'<span class="extra-text"><strong>'+esc(T('Modelos'))+'</strong></span>';
    button.onclick=()=>open('discover');extras.append(button);return true;
  }
  if(!addSidebarEntry()){const retry=setInterval(()=>{if(addSidebarEntry())clearInterval(retry);},300);setTimeout(()=>clearInterval(retry),8000);}
  window.VALModels={open,readmeHTML,setupTransfer:()=>{if(!win)build();}};
})();
