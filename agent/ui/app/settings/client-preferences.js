async function restoreClientPreferences(){
  try{uiPreferences=await requestJSON('/api/harness/preferences');}catch{try{uiPreferences.language=localStorage.getItem('valLanguage')||'es';}catch{}}
  try{
    pcAccess=await requestJSON('/api/access');
    if((S.pcAccessMode==='full_pc'||S.pcAccessMode==='sandbox')&&pcAccess.mode!==S.pcAccessMode){
      pcAccess=await requestJSON('/api/access',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:S.pcAccessMode})});
      presupuestoFirmado='';
    }
  }catch{}
  S.agentProfile=uiPreferences.agent_profile||S.agentProfile||'balanced';if($('#agentProfile')){$('#agentProfile').value=S.agentProfile;$('#agentProfile').dispatchEvent(new Event('val-profile-restored'));}syncAgentModeSeat();
  if(!['ask','auto','run'].includes(S.permissionMode)){S.permissionMode='ask';saveSettings();}
  syncFunctionControls();if(typeof syncAccessControls==='function')syncAccessControls();
  if(typeof pollMCP==='function')pollMCP();
  applyDecoration(uiPreferences.decoration);
  const duration=uiPreferences.animation_ms??620;window.VALMotion?.setDuration(duration);$('#animationSpeed').value=duration;$('#animationSpeedValue').textContent=duration+' ms';
  if(!window.VALI18n){$('#uiLanguage').disabled=true;return;}
  try{await window.VALI18n.init(uiPreferences.language);}catch{uiPreferences.language='es';window.VALI18n.setLanguage('es');$('#uiLanguage').disabled=true;$('#languageSaveState').textContent='No se pudieron cargar las traducciones.';}uiPreferences.language=window.VALI18n.language;$('#uiLanguage').value=uiPreferences.language;
  const selectors=['#thinkingMenu','#permissionMenu','#searchToggle','#mobileMenu','.top-actions','#drawer','#composerControls','#composerAddMenu','#helpCard','#addModelDialog','#projectDialog','#viewer .dlg-head','#editMessageDialog','#engineCard','#gear','#newchat','.side-head','.sidebar-local','#sidebarExtras','#sidebarResizer','#sidebarReopen','#sidebar .sidebar-chrome','#convSearch','#projectsNav','.composer-foot','#agentModeBtn','#agentModeMenu','#agentModeSegments','#agentModeWarning','#convMenu','#projectMenu','#updateStack','#browserDock','#consoleWindow','#toolsWindow','#engineOptionsWindow','#engineConfigWindow','#transferWindow','#viewer','#vframe','#scopeBtn','#responseBtn','#modelBtn','#mcpBtn','#ctxBtn','#input','#attach','#projectBtn','#send','#themeBtn','#followBtn','.help-trigger','#chatActions','#attachments','#st-ram-meter','#st-vram-meter','#preparationProgress','#modelPreparation','#browserTabs','#browserNewTab','#browserDockFullscreen','#browserDockClose','#browserBack','#browserUrl','#browserBookmark','#browserListClose','#toast','#dismissToast','#editMessageInput','.welcome','.history-empty','#toastText'];
  for(const selector of selectors)document.querySelectorAll(selector).forEach(el=>window.VALI18n.observe(el));
  translateRegionLabels();
  window.VALI18n.onChange(()=>{document.querySelectorAll('.welcome,.history-empty').forEach(el=>window.VALI18n.observe(el));syncComposerLabels();syncPreparationView();syncContextMeter();if(lastToolBudget)pintarPresupuesto(lastToolBudget);if(!currentId)$('#chatTitle').textContent=uiText('Nuevo chat');if(!loadedModel&&$('#loadedTxt'))$('#loadedTxt').textContent=uiText(modelStateKnown?'Ninguno':'Comprobando…');for(const el of document.querySelectorAll('[data-ui-label]'))el.textContent=uiText(el.dataset.uiLabel);translateRegionLabels();window.refreshChatTranslations?.();window.refreshModelPanelTranslations?.();window.refreshLoadSettingsTranslations?.();window.VALI18n.refresh();});
  syncSettingsSummary();window.VALI18n.refresh();
}

function cancelPendingEngineEdits(){
  if(!engineSnapshot||engineBusy||!engineFormDirty())return;
  const cfg=engineSnapshot.llama||{},strata=engineSnapshot.strata||{},rust=engineSnapshot.rust||{},maya=engineSnapshot.maya||{};
  $('#engineKind').value=activeEngine;
  $('#llamaVariant').value=cfg.variant||'cuda';$('#llamaExecutable').value=cfg.executable||'';$('#llamaLayers').value=cfg.gpu_layers||'auto';
  if($('#strataVariant'))$('#strataVariant').value=strata.variant||'official';if($('#strataExecutable'))$('#strataExecutable').value=strata.executable||'';
  if($('#rustVariant'))$('#rustVariant').value=rust.variant||'official';if($('#rustExecutable'))$('#rustExecutable').value=rust.executable||'';
  if($('#mayaRoot'))$('#mayaRoot').value=maya.root||'';if($('#mayaExecutable'))$('#mayaExecutable').value=maya.executable||'';if($('#mayaBackend'))$('#mayaBackend').value=maya.backend||'auto';
  syncApiConnections();$('#engineKind').onchange();syncEngineCapabilities();
}
