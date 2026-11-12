let modelSection='load';
function setModelSection(section){
  if(activeEngine==='api')section='generation';
  modelSection=section;
  document.querySelectorAll('[data-model-section]').forEach(panel=>panel.hidden=panel.dataset.modelSection!==section);
  for(const id of ['load','generation']){const button=$('#tab-'+id);if(button){button.setAttribute('aria-selected',String(id===section));button.tabIndex=id===section?0:-1;}}
}

function setupCompactSections(){
  const appearance=$('#settings-appearance'),tabs=document.createElement('div');tabs.className='section-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Secciones de configuración');
  const panels={};
  for(const [id,label] of [['look','Aspecto'],['layout','Distribución'],['history','Historial']]){
    const panel=document.createElement('div');panel.id='settings-'+id;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','settings-tab-'+id);panels[id]=panel;
    const tab=document.createElement('button');tab.id='settings-tab-'+id;tab.type='button';tab.setAttribute('role','tab');tab.setAttribute('aria-controls',panel.id);tab.textContent=label;
    tab.onclick=()=>{for(const [name,item] of Object.entries(panels)){item.hidden=name!==id;const button=$('#settings-tab-'+name);button.setAttribute('aria-selected',String(name===id));button.tabIndex=name===id?0:-1;}};tabs.append(tab);
  }
  const actions=appearance.querySelector('.theme-actions'),save=appearance.querySelector('.theme-save-line');
  for(const child of [...appearance.children]){
    if(child===actions||child===save)continue;
    const summary=child.querySelector(':scope > summary')?.textContent||'';
    const key=summary.startsWith('Historial')?'history':summary.startsWith('Distribución')||summary.startsWith('Botones')?'layout':'look';
    panels[key].append(child);
    if(child.matches('details'))child.open=key!=='look'||summary.startsWith('Colores');
  }
  panels.look.append(actions);appearance.prepend(tabs,...Object.values(panels));
  tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...tabs.children],current=buttons.indexOf(document.activeElement),index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[index].click();buttons[index].focus();});
  $('#settings-tab-look').click();
  const section=$('#controls-tools .sec'),connections=document.createElement('details');connections.className='settings-group';connections.id='mcpConnections';connections.innerHTML='<summary>Conexiones <span id="connectionsCount" class="mini"></span></summary>';
  const tokens=$('#mcpTokens');section.before(connections);connections.append(section);connections.after(tokens);section.querySelector('h3').hidden=true;
}

function setupModelWindow(){
  const model=$('#controls-model'),base=model.querySelector('.sec');model.hidden=false;
  const power=base.querySelector('.power-row'),select=$('#model'),library=base.querySelector('.model-library-actions');
  const top=document.createElement('div');top.className='model-top';
  const picker=document.createElement('div');picker.className='model-picker';
  const disclosure=document.createElement('details');disclosure.id='modelLibrary';const disclosureTitle=document.createElement('summary');
  document.getElementById('composerControls').classList.add('model-window');
  const head=document.createElement('div');head.className='model-picker-head';
  const title=base.querySelector('label[for=model]');title.className='model-picker-title';title.removeAttribute('for');title.textContent='Modelos';
  const count=document.createElement('span');count.id='modelCount';count.className='model-count';count.setAttribute('aria-live','polite');title.append(count);
  const filter=document.createElement('input');filter.id='modelFilter';filter.disabled=true;filter.type='search';filter.placeholder='Buscar modelo…';filter.setAttribute('aria-label','Buscar modelo');filter.className='model-search-input';filter.oninput=()=>renderModelOptions($('#model').value);
  disclosureTitle.append(title);head.append(filter,library);disclosure.append(disclosureTitle,head);
  const results=document.createElement('div');results.id='modelResults';results.className='model-results';results.setAttribute('role','listbox');results.setAttribute('aria-label','Modelos instalados');
  const summary=document.createElement('div');summary.className='model-selected-summary';
  const summaryLabel=document.createElement('span');summaryLabel.className='model-selected-label';summaryLabel.textContent='Seleccionado';
  const summaryText=document.createElement('div');summaryText.className='model-selected-text';
  const summaryName=document.createElement('strong');summaryName.id='modelSelectedName';const summaryMeta=document.createElement('small');summaryMeta.id='modelSelectedMeta';summaryText.append(summaryName,summaryMeta);
  const summaryState=document.createElement('span');summaryState.id='modelSelectedState';summaryState.className='model-selected-state';summaryState.hidden=true;const summaryAction=document.createElement('button');summaryAction.type='button';summaryAction.id='modelSummaryAction';summaryAction.className='model-summary-action';summaryAction.hidden=true;summary.append(summaryLabel,summaryText,summaryState,summaryAction);
  select.classList.add('model-native-hidden');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
  disclosure.append(results);picker.append(disclosure,summary,select);top.append(picker);
  document.getElementById('composerControls').addEventListener('fw:open',()=>{disclosure.open=false;});
  model.prepend(power,top);
  library.querySelector('#addModel').textContent='+ Añadir';library.querySelector('#addModel').title='Añadir modelo';library.querySelector('#refreshModels').title='Actualizar modelos';
  renderModelList($('#model').value);

  const grid=document.createElement('div');grid.className='model-grid';
  const load=document.createElement('section'),generation=document.createElement('section');
  load.id='model-load-pane';generation.id='model-generation-pane';load.dataset.modelSection='load';generation.dataset.modelSection='generation';
  load.setAttribute('role','tabpanel');generation.setAttribute('role','tabpanel');load.setAttribute('aria-labelledby','tab-load');generation.setAttribute('aria-labelledby','tab-generation');
  const context=$('#controls-context'),response=$('#controls-response');
  for(const pane of [context,response]){pane.hidden=false;delete pane.dataset.controlsPane;}
  const cache=$('#kvSettings');
  load.append(context,cache,$('#draftSettings'));generation.append(response);
  cache.querySelector('#kvCache').onchange=()=>{queueModelPreferences();syncKVSettings();};
  response.querySelector('details').open=true;
  const notice=document.createElement('div');notice.id='creatorNotice';notice.setAttribute('role','status');
  const actions=document.createElement('div');
  const reset=document.createElement('button');reset.id='creatorReset';reset.textContent='Valores del autor';reset.type='button';
  reset.onclick=()=>{
    const pref=modelPreferences[$('#model').value];if(!pref)return;
    S.sampling={...DEF_SAMPLING,...pref.creator.sampling};S.effort=pref.creator.effort||S.effort;
    S.profile='custom';syncProfileControls();queueModelPreferences();saveSettings();
  };
  const safe=document.createElement('button');safe.id='codeProtection';safe.textContent='Repetición 1,0 · código';safe.type='button';
  safe.title='Desactiva la penalización de repetición para conservar símbolos y patrones de código.';
  safe.onclick=()=>{S.sampling.repetition_penalty=1;syncProfileControls();queueModelPreferences();saveSettings();};
  actions.append(reset,safe);generation.prepend(notice,actions);generation.append($("#p_rounds").closest(".row"));
  const tabs=document.createElement('div');tabs.className='section-tabs';tabs.id='modelSectionTabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Ajustes del modelo');
  for(const [id,label] of [['load','Carga'],['generation','Generación']]){const button=document.createElement('button');button.type='button';button.id='tab-'+id;button.setAttribute('role','tab');button.setAttribute('aria-controls',id==='load'?load.id:generation.id);button.textContent=label;button.onclick=()=>setModelSection(id);tabs.append(button);}
  tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const id=event.key==='Home'?'load':event.key==='End'?'generation':modelSection==='load'?'generation':'load';setModelSection(id);$('#tab-'+id).focus();});
  grid.append(load,generation);model.insertBefore(tabs,base);model.insertBefore(grid,base);setupVisionSettings(load);
  const template=document.createElement('details');template.className='settings-group';template.innerHTML='<summary>Plantilla del modelo</summary>';template.append($('#templateRow'));load.append(template);template.id='templateSettings';
  setupEngineControls();setModelSection('load');
  base.classList.add('model-footer-static');base.querySelector('.row').classList.add('loaded-row');
  simplifyModelPanel();  // after the footer is marked: it holds the old duplicate load buttons
  $('#responseBtn').removeAttribute('title');$('#ctxBtn').removeAttribute('title');
  $('#controls-response #profileNote').hidden=true;
}
// One clear model card on top (the name opens the list; one main button), the context right under
// it, and the technical settings folded away. Before, the selection was confirmed in a box below a
// long list, there were two pairs of load buttons and the context sat ~1,100 px down the panel.
function simplifyModelPanel(){
  const root=$('#controls-model'),top=root.querySelector('.model-top'),picker=root.querySelector('.model-picker'),library=$('#modelLibrary'),summary=root.querySelector('.model-selected-summary');
  if(!top||!picker||!library||!summary||$('#modelCard'))return;
  const card=document.createElement('section');card.id='modelCard';card.className='model-card';
  const chooser=document.createElement('button');chooser.type='button';chooser.id='modelChooser';chooser.className='model-chooser';
  chooser.setAttribute('aria-haspopup','listbox');chooser.setAttribute('aria-expanded','false');chooser.setAttribute('aria-controls','modelResults');chooser.title=uiText('Elegir modelo');
  const chevron=document.createElement('span');chevron.className='model-chooser-chevron';chevron.setAttribute('aria-hidden','true');chevron.innerHTML='<svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>';
  chooser.append(summary.querySelector('.model-selected-text'),chevron);
  const actions=document.createElement('div');actions.className='model-card-actions';
  const state=document.createElement('span');state.id='modelLoadState';state.className='model-load-state';
  actions.append(state,$('#modelSummaryAction'));
  library.querySelector(':scope>summary').hidden=true;
  card.append(chooser,library,actions,$('#modelStatus'));
  summary.hidden=true;picker.prepend(card);
  chooser.onclick=()=>{library.open=!library.open;};
  library.addEventListener('toggle',()=>{chooser.setAttribute('aria-expanded',String(library.open));card.classList.toggle('choosing',library.open);if(library.open){const filter=$('#modelFilter');if(filter&&!filter.disabled)filter.focus({preventScroll:true});}});
  // Choosing closes the list and the card confirms it at once.
  $('#modelResults').addEventListener('click',event=>{if(!event.target.closest('.model-option:not(:disabled)'))return;library.open=false;card.classList.remove('picked');void card.offsetWidth;card.classList.add('picked');chooser.focus({preventScroll:true});});
  const context=$('#controls-context'),block=document.createElement('section');block.id='contextBlock';block.className='context-block';
  const head=document.createElement('div');head.className='context-block-head';
  const title=document.createElement('span');title.className='context-block-title';title.textContent=uiText('Contexto');
  const memory=document.createElement('span');memory.id='contextMemory';memory.className='context-memory';
  head.append(title,memory);block.append(head,context);top.after(block);
  const headline=$('#memoryHeadline'),copy=()=>{const text=(headline?.textContent||'').trim();memory.textContent=text?uiText('Memoria')+' '+text:'';};
  if(headline){copy();new MutationObserver(copy).observe(headline,{childList:true,characterData:true,subtree:true});}
  const tabs=$('#modelSectionTabs'),loadTab=$('#tab-load'),genTab=$('#tab-generation');
  if(loadTab)loadTab.textContent=uiText('Avanzado');
  if(tabs&&loadTab&&genTab)tabs.insertBefore(genTab,loadTab);
  const loadSettings=$('#modelLoadSettings');
  if(loadSettings&&!loadSettings.closest('details')){
    const group=document.createElement('details');group.className='settings-group';group.id='engineLoadGroup';
    const label=document.createElement('summary');label.textContent=uiText('Carga del motor');group.append(label);
    loadSettings.before(group);group.append(loadSettings);loadSettings.querySelector('h4')?.setAttribute('hidden','');
  }
  if($('#modelMemoryEstimate'))$('#modelMemoryEstimate').open=false;
  root.querySelector('.model-footer-static')?.classList.add('model-footer-hidden');
  setModelSection('generation');syncModelSelectionSummary();
}
function updateCreatorNotice(){
  const notice=$('#creatorNotice'),pref=modelPreferences[$('#model').value];if(!notice||!pref)return;
  const creator=pref.creator||{},values=creator.sampling||{};
  const changed=Object.keys(values).filter(key=>Math.abs(Number(values[key])-Number(S.sampling[key]))>1e-7);
  if(creator.effort&&creator.effort!==S.effort)changed.push('effort');
  notice.replaceChildren();notice.dataset.custom=String(changed.length>0);
  const label=document.createElement('span');
  label.textContent=creator.kind==='unpublished'?'Sin recomendación pública verificada; valores locales.':
    (changed.length?'Personalizado · difiere del autor: '+changed.map(key=>({effort:'razonamiento',temperature:'temperatura',top_p:'Top P',top_k:'Top K',min_p:'Min P',repetition_penalty:'repetición',presence_penalty:'presencia'})[key]||key).join(', ')+'. ':creator.label+'. ');
  notice.append(label);
  if(creator.source){const link=document.createElement('a');link.className='model-source';link.textContent='Fuente';link.href=creator.source;link.target='_blank';link.rel='noopener noreferrer';notice.append(link);}
  $('#creatorReset').disabled=!Object.keys(values).length;
}
function restoreModelPreferences(){
  const pref=modelPreferences[$('#model').value];if(!pref)return;
  S.sampling={...DEF_SAMPLING,...pref.sampling};S.effort=pref.effort;S.rounds=pref.rounds;S.profile='custom';
  S.model=$('#model').value;syncProfileControls();syncContextSelection();syncKVSettings();syncVisionSettings();updateCreatorNotice();syncLoadSettings();
}
function syncKVSettings(){
  const select=$('#kvCache');if(!select)return;
  const id=$('#model').value,info=modelKV[id]||{},options=info.options||[];
  const value=modelPreferences[id]?.kv??info.current;
  select.replaceChildren(...options.map(option=>new Option(option.label,option.value)));
  if(value&&!options.some(option=>option.value===value)){const item=new Option(value+' · no compatible',value);item.disabled=true;select.add(item);}
  if(value)select.value=value;
  select.disabled=busy||engineBusy||!options.length;
  const option=options.find(option=>option.value===value);
  requestMemoryEstimate();
  $('#kvStatus').textContent=option?option.description+(value!==info.current?' Se aplicará en la próxima carga manual.':''):info.error||'Selecciona un formato compatible.';
}
function queueModelPreferences(){
  const id=$('#model').value;if(!id)return;
  const settings={sampling:{...S.sampling},effort:S.effort,rounds:S.rounds,
    context:pendingModelContexts.get(id)??modelPreferences[id]?.context??modelContexts[id]??16384};
  if($('#kvCache')?.value)settings.kv=$('#kvCache').value;
  if(['llama','strata'].includes(activeEngine)&&document.getElementById('modelLoadSettings'))settings.load=structuredClone(loadCurrent);
  if(activeEngine==='llama'&&document.getElementById('modelDraftSettings'))settings.draft=structuredClone(draftCurrent);
  modelPreferences[id]={...modelPreferences[id],...structuredClone(settings)};pendingPreferences.set(id,settings);updateCreatorNotice();requestMemoryEstimate();
  clearTimeout(preferencesTimer);preferencesTimer=setTimeout(()=>flushModelPreferences().catch(error=>note(error.message)),350);
}
async function flushModelPreferences(){
  clearTimeout(preferencesTimer);
  if(preferencesSaving){await preferencesSaving;if(pendingPreferences.size)return flushModelPreferences();return;}
  if(!pendingPreferences.size)return;
  const batch=[...pendingPreferences];pendingPreferences.clear();
  preferencesSaving=(async()=>{
    for(let index=0;index<batch.length;index++){
      const [model,settings]=batch[index];
      try{await requestJSON('/api/models/preferences',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify({model,settings})});}
      catch(error){for(const [id,value] of batch.slice(index))if(!pendingPreferences.has(id))pendingPreferences.set(id,value);throw error;}
    }
  })();
  try{await preferencesSaving;}finally{preferencesSaving=null;}
}
addEventListener('pagehide',()=>{
  for(const [model,settings] of pendingPreferences)navigator.sendBeacon('/api/models/preferences',new Blob([JSON.stringify({model,settings})],{type:'application/json'}));
});
