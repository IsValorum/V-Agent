/* Local UI localization. Never observes conversation content or tool output. */
(()=>{
  let language='es',catalog={},ready=false,queued=false;
  const records=new WeakMap(),attributes=new WeakMap(),roots=new Set(),observers=new Map(),reverse=new Map(),callbacks=new Set();
  const codes=new Set(['es','en','pt','fr','de']);
  const localeMap={es:'es-ES',en:'en-US',pt:'pt-BR',fr:'fr-FR',de:'de-DE'};
  function canonical(text){return catalog[text]?text:reverse.get(text)||text;}
  function t(value){
    const raw=String(value??''),text=canonical(raw.trim());
    if(language==='es')return raw.replace(raw.trim(),text);
    const exact=catalog[text]?.[language];if(exact)return raw.replace(raw.trim(),exact);
    let m;
    if((m=text.match(/^(\d+) modelos$/)))return m[1]+' '+t('modelos');
    if((m=text.match(/^([\d.,]+) tokens de contexto$/)))return m[1]+' '+t('tokens de contexto');
    if((m=text.match(/^Conectado · (\d+) herramientas$/)))return t('Conectado')+' · '+m[1]+' '+t('herramientas');
    if((m=text.match(/^(\d[\d.,]*) caracteres$/)))return m[1]+' '+t('caracteres');
    if((m=text.match(/^Ayuda: (.+)$/)))return ({en:'Help: ',pt:'Ajuda: ',fr:'Aide : ',de:'Hilfe: '})[language]+t(m[1]);
    if((m=text.match(/^Configurar respuesta: (.+)$/)))return t('Respuesta')+': '+t(m[1]);
    if((m=text.match(/^Modelo: (.*)\. (.+)$/)))return t('Modelo')+': '+m[1]+'. '+t(m[2]);
    if((m=text.match(/^Acceso del agente: (.+)\. Cambiar acceso$/)))return t('Acceso del agente')+': '+t(m[1])+'. '+t('Cambiar acceso');
    if((m=text.match(/^Modo del agente: (.+)\. Cambiar modo$/)))return t('Modo del agente')+': '+t(m[1])+'. '+t('Cambiar modo');
    if((m=text.match(/^Contexto: (.*)$/)))return t('Contexto')+': '+m[1].replace(/\btokens\b/g,t('tokens'));
    if((m=text.match(/^Archivados · (\d+)$/)))return t('Archivados')+' · '+m[1];
    if((m=text.match(/^Personalizado · difiere del autor: (.+)\.$/)))return t('Personalizado')+' · '+t('difiere del autor')+': '+m[1].split(', ').map(part=>t(part)).join(', ')+'.';
    if((m=text.match(/^Archivos limitados al proyecto: (.+)\. Comandos bloqueados\.$/)))return ({en:'Files limited to the project: ',pt:'Arquivos limitados ao projeto: ',fr:'Fichiers limités au projet : ',de:'Dateien auf das Projekt beschränkt: '})[language]+m[1]+({en:'. Commands blocked.',pt:'. Comandos bloqueados.',fr:'. Commandes bloquées.',de:'. Befehle blockiert.'})[language];
    if((m=text.match(/^Lado de (.+)$/)))return ({en:'Side: ',pt:'Lado de ',fr:'Côté : ',de:'Seite: '})[language]+t(m[1]);
    if((m=text.match(/^Subir (.+)$/)))return ({en:'Move up: ',pt:'Mover para cima: ',fr:'Monter : ',de:'Nach oben: '})[language]+t(m[1]);
    if((m=text.match(/^Bajar (.+)$/)))return ({en:'Move down: ',pt:'Mover para baixo: ',fr:'Descendre : ',de:'Nach unten: '})[language]+t(m[1]);
    if((m=text.match(/^Nueva versión de (.+)$/)))return t('Nueva versión de')+' '+m[1];
    if((m=text.match(/^Actualización menor aplicada: (.+)$/)))return t('Actualización menor aplicada')+': '+m[1];
    if((m=text.match(/^Actualizado: (.+)$/)))return ({en:'Updated: ',pt:'Atualizado: ',fr:'Mis à jour : ',de:'Aktualisiert: '})[language]+m[1];
    if((m=text.match(/^Restaurado: (.+)$/)))return ({en:'Restored: ',pt:'Restaurado: ',fr:'Restauré : ',de:'Wiederhergestellt: '})[language]+m[1];
    if((m=text.match(/^Borrador disponible: (.+)$/)))return t('Borrador disponible')+': '+m[1];
    if((m=text.match(/^(\d+) actualizaci(?:ón|ones) más del runtime$/)))return ({en:(m[1]==='1'?'{n} more runtime update':'{n} more runtime updates'),pt:(m[1]==='1'?'{n} atualização adicional do runtime':'{n} atualizações adicionais do runtime'),fr:(m[1]==='1'?'{n} mise à jour supplémentaire du runtime':'{n} mises à jour supplémentaires du runtime'),de:(m[1]==='1'?'{n} weitere Runtime-Aktualisierung':'{n} weitere Runtime-Aktualisierungen')})[language].replace('{n}',m[1]);
    if((m=text.match(/^(\d+) entradas$/)))return m[1]+' '+t('entradas');
    if((m=text.match(/^(\d+) comandos?$/)))return m[1]+' '+t('comandos');
    if((m=text.match(/^Cargando con (.+?)(…|\.\.\.)?$/)))return t('Cargando con')+' '+m[1]+(m[2]||'');
    if((m=text.match(/^Carpeta de plugins: (.+)$/)))return t('Carpeta de plugins')+': '+m[1];
    if((m=text.match(/^El modelo no se puede cargar: (.+)$/)))return ({en:'The model cannot be loaded: ',pt:'O modelo não pode ser carregado: ',fr:'Le modèle ne peut pas être chargé : ',de:'Das Modell kann nicht geladen werden: '})[language]+m[1];
    if((m=text.match(/^Error del motor \((.+)\)$/)))return ({en:'Engine error (',pt:'Erro do motor (',fr:'Erreur du moteur (',de:'Engine-Fehler ('})[language]+m[1]+')';
    if((m=text.match(/^Falló la carga y no se pudo liberar el modelo de respaldo: (.+)$/)))return ({en:'Loading failed and the fallback model could not be released: ',pt:'O carregamento falhou e não foi possível liberar o modelo de reserva: ',fr:'Le chargement a échoué et le modèle de secours n’a pas pu être libéré : ',de:'Laden fehlgeschlagen und das Ersatzmodell konnte nicht freigegeben werden: '})[language]+m[1];
    if((m=text.match(/^Las herramientas de este modelo no superaron la comprobación de plantilla: (.+)$/)))return ({en:'This model\'s tools failed the template check: ',pt:'As ferramentas deste modelo falharam a verificação do modelo: ',fr:'Les outils de ce modèle ont échoué au contrôle du modèle : ',de:'Die Tools dieses Modells haben die Vorlagenprüfung nicht bestanden: '})[language]+m[1];
    if((m=text.match(/^Contexto anterior restaurado en disco\. No se pudo recuperar el motor: (.+)$/)))return ({en:'Previous context restored on disk. Could not recover the engine: ',pt:'Contexto anterior restaurado no disco. Não foi possível recuperar o motor: ',fr:'Contexte précédent restauré sur le disque. Impossible de récupérer le moteur : ',de:'Vorheriger Kontext auf dem Datenträger wiederhergestellt. Engine konnte nicht wiederhergestellt werden: '})[language]+m[1];
    if((m=text.match(/^Strata devolvió un error HTTP (.+)$/)))return ({en:'Strata returned an HTTP error ',pt:'Strata retornou um erro HTTP ',fr:'Strata a renvoyé une erreur HTTP ',de:'Strata hat einen HTTP-Fehler zurückgegeben: '})[language]+m[1];
    if((m=text.match(/^No se pudo guardar la ejecución local: (.+)$/)))return ({en:'Could not save the local run: ',pt:'Não foi possível salvar a execução local: ',fr:'Impossible d’enregistrer l’exécution locale : ',de:'Der lokale Lauf konnte nicht gespeichert werden: '})[language]+m[1];
    if((m=text.match(/^No se pudo comprobar el modelo cargado: (.+)$/)))return ({en:'Could not check the loaded model: ',pt:'Não foi possível verificar o modelo carregado: ',fr:'Impossible de vérifier le modèle chargé : ',de:'Das geladene Modell konnte nicht geprüft werden: '})[language]+m[1];
    if((m=text.match(/^No se pudo añadir el modelo: (.+)$/)))return ({en:'Could not add the model: ',pt:'Não foi possível adicionar o modelo: ',fr:'Impossible d’ajouter le modèle : ',de:'Das Modell konnte nicht hinzugefügt werden: '})[language]+m[1];
    if((m=text.match(/^No se pudo iniciar la interfaz: (.+)$/)))return ({en:'Could not start the interface: ',pt:'Não foi possível iniciar a interface: ',fr:'Impossible de démarrer l’interface : ',de:'Die Oberfläche konnte nicht gestartet werden: '})[language]+m[1];
    if((m=text.match(/^No se pudo (cargar|guardar|descargar|cancelar|importar|adjuntar la imagen|comprobar la plantilla): (.+)$/)))return t('No se pudo '+m[1]+':')+' '+m[2];
    if((m=text.match(/^No se pudo completar la respuesta: (.+)$/)))return t('No se pudo completar la respuesta:')+' '+m[1];
    if((m=text.match(/^Plantilla jinja: (.+)$/)))return ({en:'Jinja template: ',pt:'Modelo Jinja: ',fr:'Modèle Jinja : ',de:'Jinja-Vorlage: '})[language]+m[1];
    if((m=text.match(/^Guardado pendiente; mantén la pestaña abierta\. (.+)$/)))return t('Guardado pendiente; mantén la pestaña abierta.')+' '+m[1];
    if((m=text.match(/^Administrador no elevado: (.+)$/)))return t('Administrador no elevado:')+' '+m[1];
    if((m=text.match(/^Guardado en (.+)$/)))return ({en:'Saved in ',pt:'Salvo em ',fr:'Enregistré dans ',de:'Gespeichert in '})[language]+m[1];
    if((m=text.match(/^Guardado\. La comprobación encontró errores en (.+)$/)))return ({en:'Saved. The check found errors in ',pt:'Salvo. A verificação encontrou erros em ',fr:'Enregistré. La vérification a trouvé des erreurs dans ',de:'Gespeichert. Die Prüfung hat Fehler gefunden in '})[language]+m[1];
    if((m=text.match(/^Guardado por recuperación del borrador\. (.+)$/)))return ({en:'Saved by draft recovery. ',pt:'Salvo por recuperação do rascunho. ',fr:'Enregistré par récupération du brouillon. ',de:'Durch Entwurfswiederherstellung gespeichert. '})[language]+m[1];
    if((m=text.match(/^Error del servidor \((\d+)\)\.$/)))return ({en:'Server error (',pt:'Erro do servidor (',fr:'Erreur du serveur (',de:'Serverfehler ('})[language]+m[1]+').';
    if((m=text.match(/^Respuesta no válida del servidor \((\d+)\)\.$/)))return ({en:'Invalid server response (',pt:'Resposta inválida do servidor (',fr:'Réponse du serveur invalide (',de:'Ungültige Serverantwort ('})[language]+m[1]+').';
    if((m=text.match(/^El chat cambió en otra ventana\. Conserva esta copia y vuelve a abrirlo\. La copia en conflicto quedó guardada en el disco local\.$/)))return t('El chat cambió en otra ventana. Conserva esta copia y vuelve a abrirlo.')+' '+t('La copia en conflicto quedó guardada en el disco local.');
    if((m=text.match(/^Comprimido · (\d+) msg · (.+)$/)))return t('Comprimido')+' · '+m[1]+' msg · '+t(m[2]);
    if((m=text.match(/^No se pudo leer la lista de modelos: (.+)$/)))return t('No se pudo leer la lista de modelos:')+' '+m[1];
    if((m=text.match(/^No se pudo (encender|apagar) el motor: (.+)$/)))return ({en:'Could not '+(m[1]==='encender'?'start':'stop')+' the engine: ',pt:'Não foi possível '+(m[1]==='encender'?'iniciar':'desligar')+' o motor: ',fr:'Impossible de '+(m[1]==='encender'?'démarrer':'arrêter')+' le moteur : ',de:'Engine konnte nicht '+(m[1]==='encender'?'gestartet':'gestoppt')+' werden: '})[language]+m[2];
    if((m=text.match(/^No se pudo guardar: (.+)$/)))return ({en:'Could not save: ',pt:'Não foi possível salvar: ',fr:'Impossible d’enregistrer : ',de:'Speichern fehlgeschlagen: '})[language]+m[1];
    if((m=text.match(/^No se pudo medir el coste de las herramientas: (.+)$/)))return ({en:'Could not measure tool token cost: ',pt:'Não foi possível medir o custo das ferramentas: ',fr:'Impossible de mesurer le coût des outils : ',de:'Werkzeug-Tokenkosten konnten nicht gemessen werden: '})[language]+m[1];
    if((m=text.match(/^Error: (.+)$/)))return t('Error: ')+m[1];
    if((m=text.match(/^Ningún modelo coincide con «(.+)»\.$/)))return t('Ningún modelo coincide con')+' «'+m[1]+'».';
    if((m=text.match(/^Aquí se conserva todo el resultado recibido\. El modelo recibió (.+)$/)))return t('Aquí se conserva todo el resultado recibido. El modelo recibió')+' '+m[1];
    if((m=text.match(/^Memoria (.+)$/)))return t('Memoria')+' '+t(m[1]);
    if((m=text.match(/^(.+) · no compatible$/)))return m[1]+' · '+t('no compatible');
    if((m=text.match(/^Archivo guardado\. \((.+)\)$/)))return t('Archivo guardado.')+' ('+m[1]+')';
    if((m=text.match(/^No se pudo abrir la carpeta \(Windows ([^)]+)\)\.$/)))return ({en:'Could not open folder (Windows ',pt:'Não foi possível abrir a pasta (Windows ',fr:'Impossible d’ouvrir le dossier (Windows ',de:'Ordner konnte nicht geöffnet werden (Windows '})[language]+m[1]+').';
    if((m=text.match(/^No se pudo abrir la guía: (.+)$/)))return ({en:'Could not open the user guide: ',pt:'Não foi possível abrir o guia: ',fr:'Impossible d’ouvrir le guide : ',de:'Anleitung konnte nicht geöffnet werden: '})[language]+m[1];
    if((m=text.match(/^No se pudo abrir el desinstalador: (.+)$/)))return ({en:'Could not open the uninstaller: ',pt:'Não foi possível abrir o desinstalador: ',fr:'Impossible d’ouvrir le programme de désinstallation : ',de:'Deinstallationsprogramm konnte nicht geöffnet werden: '})[language]+m[1];
    if(text.includes(' · '))return text.split(' · ').map(part=>t(part)).join(' · ');
    return raw;
  }
  function ignored(el){
    if(!el)return true;
    if(el.closest('script,style,pre,code,textarea,input,#convs,#chatTitle,#loadedTxt,#modelInfo,#engineQuickName,#projectList .project-item:not(:first-child),[data-user-content]'))return true;
    if(el.closest('#chat')&&!el.closest('.welcome'))return true;
    if(el.closest('#model')&&el.closest('option')?.value)return true;
    return false;
  }
  function textNode(node){
    if(!node.nodeValue?.trim()||ignored(node.parentElement))return;
    let entry=records.get(node);const current=node.nodeValue;
    if(!entry||current!==entry.output)entry={source:canonical(current.trim()),padding:current.match(/^\s*/)[0],end:current.match(/\s*$/)[0]};
    const output=entry.padding+t(entry.source)+entry.end;entry.output=output;records.set(node,entry);
    if(current!==output)node.nodeValue=output;
  }
  function element(el){
    if(ignored(el)&&!el.matches('input,textarea'))return;
    let map=attributes.get(el);if(!map){map=new Map();attributes.set(el,map);}
    for(const key of ['title','aria-label','placeholder']){
      const current=el.getAttribute(key);if(!current)continue;
      let entry=map.get(key);if(!entry||entry.output!==current)entry={source:canonical(current)};
      const output=t(entry.source);entry.output=output;map.set(key,entry);if(current!==output)el.setAttribute(key,output);
    }
  }
  function decorate(root){
    if(!root||!root.isConnected)return;
    if(root.nodeType===Node.TEXT_NODE){textNode(root);return;}
    if(root.nodeType!==Node.ELEMENT_NODE)return;
    element(root);const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT);
    let node;while((node=walker.nextNode())){if(node.nodeType===Node.TEXT_NODE)textNode(node);else element(node);}
  }
  function observe(root){
    if(!root||roots.has(root))return;roots.add(root);decorate(root);
    const observer=new MutationObserver(changes=>{
      // Only settings/composer labels are observed: streaming chat tokens never enter here.
      for(const change of changes){if(change.type==='characterData')textNode(change.target);else if(change.type==='attributes')element(change.target);else for(const node of change.addedNodes)decorate(node);}
    });
    observer.observe(root,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','aria-label','placeholder']});observers.set(root,observer);
  }
  function refresh(){for(const root of roots)decorate(root);}
  function setLanguage(next){
    if(!codes.has(next))throw new Error('Unsupported language');language=next;document.documentElement.lang=next;
    try{localStorage.setItem('valLanguage',next);}catch{}
    refresh();for(const callback of callbacks)callback(next);
  }
  async function init(next){
    if(!ready){const response=await fetch('/assets/locales.json');if(!response.ok)throw new Error('Translations unavailable');catalog=await response.json();
      for(const [source,translations] of Object.entries(catalog))for(const translated of Object.values(translations))if(!reverse.has(translated))reverse.set(translated,source);ready=true;
    }
    setLanguage(codes.has(next)?next:'es');
  }
  window.VALI18n={t,init,observe,refresh,setLanguage,onChange:callback=>callbacks.add(callback),get language(){return language;},get locale(){return localeMap[language];}};
})();
