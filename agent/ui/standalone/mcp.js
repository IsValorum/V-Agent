/* Local MCP defaults. Does not activate tools or modify their schemas. */
(()=>{
  const fields={
    duckduckgo:[
      ['region','Región','select',[['wt-wt','Global'],['sv-es','El Salvador'],['us-en','United States'],['uk-en','United Kingdom'],['es-es','España'],['mx-es','México'],['ar-es','Argentina'],['de-de','Deutschland'],['fr-fr','France'],['br-pt','Brasil'],['pt-pt','Portugal'],['jp-jp','日本']]],
      ['language','Idioma de búsqueda','select',[['auto','Según la región'],['es','Español'],['en','English'],['pt','Português'],['fr','Français'],['de','Deutsch'],['ja','日本語']]],
      ['timelimit','Antigüedad','select',[['','Sin límite'],['d','Último día'],['w','Última semana'],['m','Último mes'],['y','Último año']]],
      ['count','Cantidad de resultados','number',[1,10]],
      ['safesearch','Filtro de contenido','select',[['on','Estricto'],['moderate','Moderado'],['off','Desactivado']]],
      ['filter_ads','Excluir anuncios identificados','checkbox'],
      ['timeout','Tiempo de espera por petición (s)','number',[5,30]],
      ['visit_tokens','Web Visit · tokens por página ≈ (0 = sin límite)','number',[0,1000000]],
      ['include_links','Web Visit · incluir enlaces','checkbox'],
      ['include_tables','Web Visit · incluir tablas','checkbox'],
      ['max_result_chars','Límite de salida (caracteres, 0 = sin límite)','number',[0,1000000]],
    ],
    documents:[
      ['extract_mode','Modo de extracción predeterminado','select',[['auto','Automático (Markdown + tablas)'],['markdown','Markdown estructurado'],['text','Texto plano'],['tables','Solo tablas']]],
      ['max_pages','Páginas máx. en PDF (0 = sin límite)','number',[0,5000]],
      ['max_chars','Caracteres máx. por lectura (0 = sin límite)','number',[0,1000000]],
      ['include_tables','Extraer tablas como Markdown','checkbox'],
      ['ocr_scanned','OCR en páginas escaneadas (Windows OCR)','checkbox'],
      ['include_metadata','Incluir metadatos del documento','checkbox'],
    ],
    pc:[['command_timeout','Comandos · espera predeterminada (s)','number',[5,300]],['max_result_chars','Límite de salida (caracteres)','number',[1000,1000000]]],
    hf:[['command_timeout','CLI · espera predeterminada (s)','number',[5,300]],['max_result_chars','Límite de salida (caracteres)','number',[1000,1000000]]],
  };
  async function requestJSON(url,init){const response=await fetch(url,init);const data=await response.json();if(!response.ok||data.error)throw new Error(data.error||('HTTP '+response.status));return data;}
  let loaded=null,loading=null;
  const t=value=>window.VALI18n?.t(value)||value;
  async function load(){
    if(loading)return loading;
    loading=(async()=>{try{loaded=await requestJSON('/api/harness/mcp-options');for(const server in fields)for(const [key] of fields[server]){const input=document.getElementById('mcpopt-'+server+'-'+key);if(input.type==='checkbox')input.checked=loaded[server][key];else input.value=loaded[server][key];}document.getElementById('saveMCPOptions').disabled=false;document.getElementById('mcpOptionsState').textContent='';}catch(error){document.getElementById('mcpOptionsState').textContent=t('No se pudieron cargar los ajustes.')+' '+error.message;}finally{loading=null;}})();return loading;
  }
  window.setupMCPOptions=()=>{
    const host=document.createElement('details');host.id='mcpOptions';host.className='settings-group';
    host.innerHTML='<summary>Configuración de MCPs</summary><div class="mcp-options-body"><p class="mini">Se aplican a las próximas llamadas. No activa herramientas.</p><div id="mcpOptionsFields"></div><div class="mcp-options-actions"><button id="saveMCPOptions" type="button" disabled>Guardar ajustes</button><span id="mcpOptionsState" class="mini" role="status"></span></div></div>';
    document.getElementById('settings-tools').insertBefore(host,document.getElementById('settingsToolsHost'));
    for(const [server,title] of [['duckduckgo','Web Search / Web Visit'],['documents','Extractor de PDF y documentos'],['pc','PC · archivos y código'],['hf','Hugging Face']]){
      const group=document.createElement('details');group.className='mcp-option-server';const summary=document.createElement('summary');summary.textContent=title;group.append(summary);
      const content=document.createElement('div');content.className='mcp-option-fields';
      for(const [key,label,type,values] of fields[server]){
        const row=document.createElement('label');row.className='setting-row';const text=document.createElement('span');text.textContent=label;
        const input=document.createElement(type==='select'?'select':'input');input.id='mcpopt-'+server+'-'+key;input.dataset.server=server;input.dataset.option=key;
        if(type==='select')for(const [value,title] of values){const option=document.createElement('option');option.value=value;option.textContent=title;input.append(option);}
        else{input.type=type;if(values){input.min=values[0];input.max=values[1];input.step='1';}}
        row.append(text,input);content.append(row);
      }
      if(server==='duckduckgo'){
        const hint=document.createElement('p');hint.className='mini';hint.textContent='El buscador combina país e idioma. Otro idioma puede usar su región principal. Web Visit usa un presupuesto aproximado: 4 caracteres por token. Pon 0 = sin límite para extraer la página completa. Los resultados ya son orgánicos; se excluyen anuncios marcados.';content.append(hint);
      }else if(server==='documents'){
        const hint=document.createElement('p');hint.className='mini';hint.textContent='Admite PDF (texto, tablas y OCR opcional), Word (.docx), Excel (.xlsx), PowerPoint (.pptx), OpenDocument, EPUB, RTF, HTML, XML y CSV. Pon 0 = sin límite en páginas o caracteres. También se aplica cuando Web Visit abre un PDF o documento remoto.';content.append(hint);
      }
      group.append(content);document.getElementById('mcpOptionsFields').append(group);
    }
    host.addEventListener('toggle',()=>{if(host.open&&!loaded)load();});
    document.getElementById('saveMCPOptions').onclick=async()=>{
      const button=document.getElementById('saveMCPOptions'),status=document.getElementById('mcpOptionsState'),body={};
      for(const server in fields){body[server]={};for(const [key,,type] of fields[server]){const input=document.getElementById('mcpopt-'+server+'-'+key);if(!input.checkValidity()){input.reportValidity();return;}body[server][key]=type==='checkbox'?input.checked:type==='number'?Number(input.value):input.value;}}
      button.disabled=true;
      try{loaded=await requestJSON('/api/harness/mcp-options',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});status.textContent=t('Guardado en este equipo');}
      catch(error){status.textContent=t('No se pudieron guardar los ajustes.');}finally{button.disabled=false;}
    };
    window.VALI18n?.observe?.(host);
  };
})();
