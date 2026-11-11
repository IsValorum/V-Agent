/* ---------- eventos (solo los que no tienen handler previo) ---------- */
function bind(id, ev, fn) { const el = document.getElementById(id); if (el) el.addEventListener(ev, fn); }
bind("send", "click", ()=>busy?stopGeneration():sendMsg());
bind("input", "keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMsg(); } });
bind("newchat", "click", newConv);
bind("load", "click", loadModel);
bind("unload", "click", unloadModel);

const HELP={
  t_responseOpacity:['Opacidad','Intensidad del fondo de las respuestas. En 100 es sólido; en 0 desaparece.'],
  t_responseBlur:['Desenfoque del cristal','Difumina la imagen detrás de las respuestas. En 0 no aplica desenfoque.'],
  t_responseRadius:['Redondez','Redondea las esquinas de las tarjetas de respuesta.'],
  kvCache:['Caché KV','Guarda las claves y valores de la conversación. Menos bits reduce la memoria usada, pero puede reducir la precisión. Solo aparecen formatos admitidos por este modelo y motor. Se guarda por modelo en el equipo y se aplica al cargarlo manualmente.'],
  modelPath:['Archivo GGUF','Selecciona un modelo que ya tengas en tu equipo. Se registra su ubicación sin copiar sus pesos. Después podrás cargarlo junto al cuadro de mensaje.'],modelTemplate:['Plantilla Jinja','Si tienes una plantilla corregida para este modelo, selecciónala aquí. Automática busca chat_template.jinja junto al GGUF o usa la incluida en el modelo.'],modelName:['Nombre','Nombre que verás en el selector. No cambia el archivo original.'],
  t_accent:['Acento','Color de botones, detalles y elementos seleccionados.'],t_bg:['Base','Color que queda detrás de todo el fondo.'],t_panel:['Paneles','Color de la barra lateral, los ajustes y el cuadro de mensaje.'],t_text:['Texto','Color principal de lectura. Elige uno que contraste con el fondo.'],
  t_gradient:['Tipo de fondo','Liso usa un solo color. Degradado mezcla colores en una dirección; Radial parte de un centro y Bruma los reparte en manchas suaves.'],t_g1:['Color 1','Primer color del fondo. Se mezcla con los otros dos.'],t_g2:['Color 2','Segundo color del fondo.'],t_g3:['Color 3','Tercer color del fondo.'],t_strength:['Intensidad','Cuánto se ven los colores sobre la base. En 0 el fondo queda liso.'],t_angle:['Dirección','Gira el degradado o la bruma. No se aplica al fondo radial.'],t_backgroundBlur:['Difuminado del fondo','Suaviza la mezcla entre colores. No desenfoca los mensajes.'],t_grain:['Grano','Añade una textura muy fina al fondo. En 0 queda limpio.'],
  t_blur:['Desenfoque del cristal','Difumina lo que se ve detrás de los paneles. Se nota más cuando su opacidad es baja.'],t_alpha:['Barra lateral','Su opacidad: 100% la hace sólida; un valor menor deja ver el fondo.'],t_composerAlpha:['Cuadro de mensaje','Opacidad de la zona donde escribes y del fondo de tus mensajes.'],t_drawerAlpha:['Ajustes','Opacidad de este panel. Puedes bajarla para ver el fondo a través de él.'],t_border:['Bordes','Cuánto se marcan los límites de paneles y controles.'],t_shadow:['Sombra','Añade profundidad bajo los paneles. En 0 no hay sombra.'],t_radius:['Esquinas','Redondea los paneles y mensajes. En 0 las esquinas son rectas.'],t_sidebarWidth:['Ancho lateral','Espacio para el historial. En pantallas pequeñas se abre como un panel.'],t_chatWidth:['Ancho del chat','Anchura máxima de los mensajes y del cuadro de escritura.'],t_fontSize:['Tamaño de texto','Cambia el tamaño de los mensajes y del texto que escribes.'],t_font:['Letra','Tipografía del chat y de los controles. Los bloques de código conservan su letra de ancho fijo.'],t_density:['Espaciado','Compacto muestra más contenido; Amplio deja más espacio entre mensajes y controles.'],t_showMark:['Símbolo inicial','Muestra el pequeño símbolo de V-Agent cuando no hay mensajes.'],workspaceName:['Nombre','Nombre que aparece en tu barra lateral. Se guarda en el navegador y en el disco del agente.'],
  model:['Modelo','El archivo de inteligencia que responderá. Elegirlo no lo carga. Descarga el que esté en memoria y pulsa Cargar modelo.'],workProfile:['Perfil','Aplica los ajustes para código, trabajo con herramientas o investigación. Las herramientas y la fecha se activan por separado con sus casillas.'],effort:['Razonamiento','Cuánto trabajo dedica el modelo a resolver la tarea antes de responder. Profundo suele tardar más; puedes cambiarlo aquí.'],p_temp:['Temperatura','Cuánta variación hay en las respuestas. Un valor menor hace que cambien menos. Para código, el perfil parte de 0,60.'],p_topp:['Top P','Limita las opciones que el modelo considera al escribir. Puedes dejar el valor del perfil.'],p_topk:['Top K','Número máximo de opciones que considera para cada fragmento. 20 es el valor habitual de estos perfiles.'],p_minp:['Min P','Descarta opciones poco probables. En 0 no añade ese filtro.'],p_rep:['Repetición','1,00 deja la repetición sin penalizar. Subirlo puede deformar signos, nombres o indentación en el código.'],p_presence:['Presencia','Penaliza volver a usar elementos que ya aparecieron. Para código y herramientas se deja en 0.'],p_max:['Límite de respuesta','Máximo de fragmentos de texto que puede generar, incluido el razonamiento. Más permite respuestas largas; 0 usa el espacio disponible.'],p_seed:['Semilla','Un número fijo ayuda a repetir resultados. En 0 el agente no fija una semilla.'],p_rounds:['Rondas de herramientas','Cuántos pasos de consulta y respuesta puede encadenar el agente. La última ronda se reserva para la respuesta final.'],
  f_search:['Buscar','Permite localizar información y enlaces en internet.'],f_visit:['Leer páginas','Abre el texto de una página para comprobar su contenido; no se limita al resumen del buscador.'],f_files:['Archivos','Lista, lee y guarda texto. En Sandbox solo accede a la carpeta de trabajo; en Toda la PC puede usar otras rutas.'],pcAccess:['Acceso del agente','Carpeta limita los archivos al proyecto o chat. CMD puede ejecutarse con aislamiento de Windows si está disponible. Toda la PC permite usar otras rutas y comandos con tus permisos. Al reiniciar vuelve a Carpeta.'],f_shell:['Comandos','En Carpeta ejecuta CMD aislado, sin red y solo si la comprobación de Windows tiene éxito. En Toda la PC permite CMD y PowerShell con tus permisos.'],f_hf:['Hugging Face','Activa la CLI oficial y las transferencias de archivos para tu cuenta. Usa la sesión de HF del equipo sin mostrar su token. Las rutas locales respetan Sandbox o Acceso completo.'],f_sys:['Información del equipo','Consulta sistema operativo, memoria, discos y GPU.'],f_browser:['Navegador del agente','El agente usa la misma ventana de navegador que ves: puede abrir páginas, leer su texto, pulsar elementos y escribir en formularios. Tú puedes seguir usando la barra y la ventana. No es un iframe; las páginas no se incrustan dentro del chat.'],f_autobrowser:['Navegador autónomo','Abre un Edge headless propio para navegar, extraer, descargar, capturar pantalla y leer red/consola sin ocupar tu ventana. Usa su propio perfil; no ve tus pestañas personales salvo que se importen.'],f_web:['HTTP y descargas','Peticiones HTTP reales con cabeceras, cookies y cuerpo; descarga y guarda archivos; extrae HTML a Markdown. Solo en Agente estándar o completo.'],f_console:['Consola compartida','El agente puede ejecutar comandos en la misma consola persistente que ves, conservando carpeta y variables. Requiere Acceso completo. No es un terminal interactivo completo: los programas que piden entrada no funcionan.'],f_date:['Fecha y hora','Añade solo la fecha y hora actual del equipo cuando marcas esta casilla. No añade identidad ni instrucciones.'],s_ddg:['Internet','Activa o desactiva las dos herramientas de búsqueda y lectura.'],s_pc:['Mi equipo','Activa o desactiva las herramientas de archivos, comandos e información del equipo.'],
  draftSource:['MTP','Integrado usa la cabeza incluida en el modelo. Para una cabeza externa, selecciona el GGUF del mismo modelo. La elección se guarda por modelo.'],
  draftTokens:['Draft tokens','Cuántos tokens propone por adelantado y verifica el modelo. 0 lo desactiva. Los cambios se guardan y se aplican en la próxima carga, o con Aplicar y recargar.'],
  local:['Local','Los chats y el aspecto se guardan en el disco de este equipo. Puedes exportar el historial desde Ajustes. El navegador conserva las preferencias de herramientas.'],compose:['Escritura','Enter envía el mensaje. Shift + Enter añade una línea. El botón + abre adjuntos, búsqueda y herramientas.'],metrics:['Rendimiento','Generación: tokens que escribe por segundo. Lectura: tokens del contexto que procesa por segundo. En reposo se muestra la última medición. Las barras indican la memoria total usada por el equipo: VRAM en la tarjeta gráfica y RAM en el sistema. No es solo el consumo del modelo.'],mcp:['Conexiones','Los MCP conectan el agente con internet y con tu equipo. “Conectado” significa que el servidor está listo; las casillas deciden qué puede usar.'],context:['Contexto','Cantidad de texto que el modelo puede tener presente. Aumentarlo requiere más memoria. Se guarda por modelo y se aplica en su próxima carga manual.'],ctxInput:['Contexto','Cantidad de texto que el modelo puede tener presente, medida en tokens. Se guarda por modelo y se aplica en su próxima carga manual.'],
  load:['Cargar modelo','Carga únicamente el modelo seleccionado. Descarga antes el que esté en memoria. Si el motor está apagado, enciende el servicio.'],unload:['Descargar modelo','Detiene la respuesta si está generando y libera el modelo de la memoria. El motor permanece encendido y no carga otro modelo automáticamente.'],exportTheme:['Exportar tema','Guarda un archivo con tus colores y efectos. No incluye chats ni ajustes del modelo.'],importTheme:['Importar tema','Restaura los colores y efectos desde un archivo de tema de V-Agent.'],resetTheme:['Restablecer','Vuelve a los valores iniciales del modo claro u oscuro que estés editando.']
};
function helpButton(key) {
  const button=document.createElement('button');button.type='button';button.className='help-trigger';button.textContent='?';button.dataset.help=key;button.setAttribute('aria-label','Ayuda: '+HELP[key][0]);button.setAttribute('aria-expanded','false');return button;
}
for(const [key] of Object.entries(HELP)) {
  const control=document.getElementById(key);if(!control)continue;
  const label=document.querySelector('label[for="'+key+'"]');
  if(label){let wrapper=label.parentElement;if(!wrapper.classList.contains('field-label')){wrapper=document.createElement('span');wrapper.className='field-label';label.replaceWith(wrapper);wrapper.append(label);}wrapper.append(helpButton(key));}
  else if(control.closest('label.chk')){const label=control.closest('label');const line=document.createElement('div');line.className='check-line';label.replaceWith(line);line.append(label,helpButton(key));}
}
for(const [id,key] of [['localHelpAnchor','local'],['composeHelpAnchor','compose'],['metricsHelpAnchor','metrics'],['mcpHelpAnchor','mcp'],['contextHelpAnchor','context']])$('#'+id).append(helpButton(key));
for(const id of ['load','unload','exportTheme','importTheme','resetTheme']) {
  const control=$('#'+id);const wrapper=document.createElement('span');wrapper.className='action-with-help';control.replaceWith(wrapper);wrapper.append(control,helpButton(id));
}

let helpAnchor=null,helpPinned=false,helpTimer;
function hideHelp(){clearTimeout(helpTimer);const card=$('#helpCard');if(card.matches(':popover-open'))card.hidePopover();card.hidden=true;if(helpAnchor){helpAnchor.setAttribute('aria-expanded','false');helpAnchor.removeAttribute('aria-describedby');}helpAnchor=null;helpPinned=false;}
function showHelp(button,pin=false){
  clearTimeout(helpTimer);if(helpPinned&&helpAnchor!==button&&!pin)return;
  if(helpAnchor&&helpAnchor!==button){helpAnchor.setAttribute('aria-expanded','false');helpAnchor.removeAttribute('aria-describedby');}
  helpAnchor=button;helpPinned=pin;const [title,text]=HELP[button.dataset.help];$('#helpTitle').textContent=title;$('#helpText').textContent=text;
  const card=$('#helpCard');card.hidden=false;if(card.showPopover&&!card.matches(':popover-open'))card.showPopover();
  const box=button.getBoundingClientRect(),height=card.offsetHeight,width=card.offsetWidth;
  card.style.left=Math.max(12,Math.min(innerWidth-width-12,box.left+box.width/2-width/2))+'px';card.style.top=Math.max(12,Math.min(innerHeight-height-12,box.bottom+8+height<=innerHeight-12?box.bottom+8:box.top-height-8))+'px';
  button.setAttribute('aria-expanded','true');button.setAttribute('aria-describedby','helpCard');
}
document.querySelectorAll('.help-trigger').forEach(button=>{
  // Help opens explicitly; moving across a menu never opens/closes top-layer surfaces.
  button.addEventListener('focus',()=>{if(button.matches(':focus-visible'))showHelp(button,false);});
  button.addEventListener('blur',()=>{if(!helpPinned)hideHelp();});
  button.addEventListener('click',event=>{event.stopPropagation();if(helpPinned&&helpAnchor===button)hideHelp();else showHelp(button,true);});
});
$('#helpCard').addEventListener('pointerenter',()=>clearTimeout(helpTimer));$('#helpCard').addEventListener('pointerleave',()=>{if(!helpPinned)hideHelp();});
document.addEventListener('pointerdown',event=>{if(helpAnchor&&!event.target.closest('.help-trigger')&&!$('#helpCard').contains(event.target))hideHelp();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&helpAnchor){event.preventDefault();event.stopImmediatePropagation();hideHelp();}},true);
window.addEventListener('resize',hideHelp);document.addEventListener('scroll',event=>{if(helpAnchor&&!$('#helpCard').contains(event.target))hideHelp();},true);


let importBusy=false,importInfo=null,importVersion=0;
const importDialog=$('#addModelDialog');window.VALWindows?.register('import',importDialog);
function importPayload(){return {path:$('#modelPath').value.trim(),template_path:$('#modelTemplate').value.trim()||null};}
function setImportBusy(value){importBusy=value;for(const id of ['modelPath','modelTemplate','modelName','browseModel','browseTemplate','registerModel','cancelAddModel','closeAddModel'])$('#'+id).disabled=value;importDialog.setAttribute('aria-busy',String(value));}
function resetInspection(){importVersion++;importInfo=null;$('#modelInspection').hidden=true;$('#registerModel').textContent='Comprobar';$('#importStatus').textContent='';}
async function inspectImport(){
  const version=importVersion;setImportBusy(true);$('#importStatus').textContent='Comprobando archivo y plantilla…';
  try {
    const info=await requestJSON('/api/models/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(importPayload()),signal:AbortSignal.timeout(120000)});
    if(version!==importVersion)return;
    importInfo=info;$('#modelInspection').hidden=false;$('#modelName').value=info.name;$('#modelName').parentElement.hidden=!!info.already_registered;
    $('#modelInfo').textContent=info.already_registered?'Este modelo ya está en tu lista.':`${info.family||info.architecture||info.backend} · ${info.size_gib??(info.size_bytes/2**30).toFixed(2)} GB · Plantilla: ${info.template_name||info.template_source}`;
    $('#registerModel').textContent=info.already_registered?'Seleccionar':'Añadir';$('#importStatus').textContent=(info.warnings||[]).join(' ');
  }catch(error){$('#importStatus').textContent=error.message;}finally{setImportBusy(false);}
}
$('#addModel').onclick=()=>{if(busy||engineBusy)return;hideHelp();resetInspection();$('#modelPath').value='';$('#modelTemplate').value='';$('#modelName').value='';window.VALWindows?.open('import');$('#modelPath').focus();};
function closeImport(){if(importBusy)return;hideHelp();window.VALWindows?.close('import');$('#addModel').focus();}
$('#closeAddModel').onclick=$('#cancelAddModel').onclick=closeImport;
for(const id of ['modelPath','modelTemplate'])$('#'+id).addEventListener('input',resetInspection);
for(const [button,kind,field] of [['browseModel','model','modelPath'],['browseTemplate','template','modelTemplate']])$('#'+button).onclick=async()=>{
  setImportBusy(true);$('#importStatus').textContent='Elige el archivo en la ventana de Windows…';let chosen=false;
  try{const result=await requestJSON('/api/models/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind}),signal:AbortSignal.timeout(310000)});if(result.path){$('#'+field).value=result.path;resetInspection();chosen=true;}else $('#importStatus').textContent='';}
  catch(error){$('#importStatus').textContent=error.message;}finally{setImportBusy(false);}
  if(chosen&&$('#modelPath').value.trim())await inspectImport();
};
$('#registerModel').onclick=async()=>{
  if(importBusy)return;if(!importInfo){await inspectImport();return;}
  setImportBusy(true);$('#importStatus').textContent='Preparando el modelo…';
  try{
    const result=await requestJSON('/api/models/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...importPayload(),name:$('#modelName').value.trim()}),signal:AbortSignal.timeout(180000)});
    await loadModels();const id=result.model.id;
    if(!Array.from($('#model').options).some(option=>option.value===id))throw new Error('El modelo se añadió, pero no aparece en la lista. Pulsa Actualizar.');
    $('#model').value=id;S.model=id;syncModelPicker();syncContextSelection();restoreModelPreferences();saveSettings();
    setImportBusy(false);closeImport();note(result.status==='already_registered'?'Modelo seleccionado.':'Modelo añadido. Pulsa Cargar para usarlo.');
  }catch(error){$('#importStatus').textContent=error.message;}finally{setImportBusy(false);}
};
for(const id of ['modelPath','modelTemplate'])$('#'+id).addEventListener('keydown',event=>{if(event.key==='Enter'&&!importBusy){event.preventDefault();$('#registerModel').click();}});


setupProjectControl();
setupConvMenus();
setupSidebarChrome();
await restoreLocalSessions();
await refreshProjectAssignments();
setupModelWindow();
setupCompactSections();
setupSettingsHub();
watchAutomaticUpdates({requestJSON,uiText,note,setDrawer,selectSettingsCategory});
setupLoadSettings();
setupPluginManager();
await restoreEngine();
await restoreClientPreferences();
syncProjectButton();
syncComposerLabels();
loadModels();
renderConvs();
renderChat();
syncServerSwitches();
async function pollLoop() { await pollStats(); setTimeout(pollLoop,2500); }
pollLoop();
function finishBoot(force=false){
  document.body.classList.add("app-ready");
  const cover=document.getElementById("bootCover");if(!cover)return;
  const reduce=matchMedia("(prefers-reduced-motion: reduce)").matches;
  if(force||reduce){cover.remove();return;}
  const wait=Math.max(0,1000-performance.now());
  setTimeout(()=>{cover.classList.add("boot-leaving");setTimeout(()=>cover.remove(),660);},wait);
}
window.__finishBoot=finishBoot;
const inp = document.getElementById("input"); if (inp) inp.focus();finishBoot();
