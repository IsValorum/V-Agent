#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
// Window resources follow the bundled VAL monogram collection.
use std::{io::{Read,Write},net::{TcpStream,SocketAddr},path::PathBuf,process::{Child,Command,Stdio},sync::{Arc,Mutex},time::Duration};
use std::os::windows::process::CommandExt;
use tauri::{AppHandle,LogicalPosition,LogicalSize,Manager,Url,Webview,WebviewUrl,WebviewWindowBuilder};
use tauri::webview::{PageLoadEvent,WebviewBuilder};

#[derive(serde::Serialize)]
struct BrowserState{open:bool,url:String}

#[link(name="dwmapi")]
extern "system" {
 fn DwmSetWindowAttribute(hwnd:*mut std::ffi::c_void,attribute:u32,value:*const std::ffi::c_void,size:u32)->i32;
}
// Suppress only the small caption icon; keep the taskbar icon and native controls.
#[link(name="user32")]
extern "system" {
 fn GetWindowLongPtrW(hwnd:*mut std::ffi::c_void,index:i32)->isize;
 fn SetWindowLongPtrW(hwnd:*mut std::ffi::c_void,index:i32,value:isize)->isize;
 fn SetWindowPos(hwnd:*mut std::ffi::c_void,after:*mut std::ffi::c_void,x:i32,y:i32,cx:i32,cy:i32,flags:u32)->i32;
 fn CreateIcon(instance:*mut std::ffi::c_void,width:i32,height:i32,planes:u8,bits:u8,and_bits:*const u8,xor_bits:*const u8)->*mut std::ffi::c_void;
 fn SendMessageW(hwnd:*mut std::ffi::c_void,message:u32,wparam:usize,lparam:isize)->isize;
 fn FindWindowW(class:*const u16,name:*const u16)->*mut std::ffi::c_void;
 fn GetWindowThreadProcessId(hwnd:*mut std::ffi::c_void,pid:*mut u32)->u32;
 fn AllowSetForegroundWindow(pid:u32)->i32;
}
fn apply_taskbar_identity(window:&tauri::WebviewWindow)->Result<(),String>{
 let hwnd=window.hwnd().map_err(|e|e.to_string())?;
 unsafe{
  use windows::Win32::System::Com::{CoCreateInstance,CLSCTX_INPROC_SERVER};
  use windows::Win32::UI::Shell::{ITaskbarList3,TaskbarList};
  let taskbar:ITaskbarList3=CoCreateInstance(&TaskbarList,None,CLSCTX_INPROC_SERVER).map_err(|e|e.to_string())?;
  taskbar.HrInit().map_err(|e|e.to_string())?;
  taskbar.SetThumbnailTooltip(windows::Win32::Foundation::HWND(hwnd.0),windows::core::w!("V-Agent")).map_err(|e|e.to_string())?;
 }
 Ok(())
}
fn caption_color(value:&str)->Result<u32,String>{
 if value.len()!=7||!value.starts_with('#'){return Err("Color de ventana no válido.".into());}
 let rgb=u32::from_str_radix(&value[1..],16).map_err(|_|"Color de ventana no válido.".to_string())?;
 Ok(((rgb>>16)&255)|(rgb&0xff00)|((rgb&255)<<16))
}
fn apply_window_appearance(window:&tauri::WebviewWindow,dark:bool,background:&str,radius:u32)->Result<(),String>{
 let color=caption_color(background)?;
 window.set_theme(Some(if dark{tauri::Theme::Dark}else{tauri::Theme::Light})).map_err(|e|e.to_string())?;
 let hwnd=window.hwnd().map_err(|e|e.to_string())?;
 let linear=|channel:u32|{let c=channel as f64/255.;if c<=0.04045{c/12.92}else{((c+0.055)/1.055).powf(2.4)}};
 let luminance=0.2126*linear(color&255)+0.7152*linear((color>>8)&255)+0.0722*linear((color>>16)&255);
 let foreground=if luminance>0.179{0u32}else{0x00ffffffu32};
 let corners=if radius<=8{3u32}else{2u32};
 // Optional Windows 11 attributes. Older Windows retains the native light/dark fallback.
 for (attribute,value) in [(35u32,color),(36,foreground),(34,color),(33,corners)]{
  unsafe{DwmSetWindowAttribute(hwnd.0,attribute,&value as *const u32 as *const std::ffi::c_void,4);}
 }
 Ok(())
}
#[tauri::command]
fn window_appearance(app:AppHandle,dark:bool,background:String,radius:u32)->Result<(),String>{
 if radius>40{return Err("Redondez fuera de rango.".into());}
 let window=app.get_webview_window("main").ok_or("No se encontró la ventana principal.")?;
 apply_window_appearance(&window,dark,&background,radius)
}

fn brand_icon(logo:&str)->Result<tauri::image::Image<'static>,String>{
 let rgba:&'static [u8]=match logo {
  "gold"=>include_bytes!("../icons/gold.rgba"),
  "silver"=>include_bytes!("../icons/silver.rgba"),
  "jade"=>include_bytes!("../icons/jade.rgba"),
  "blue"=>include_bytes!("../icons/blue.rgba"),
  "rose"=>include_bytes!("../icons/rose.rgba"),
  "ruby"=>include_bytes!("../icons/ruby.rgba"),
  "violet"=>include_bytes!("../icons/violet.rgba"),
  "ivory"=>include_bytes!("../icons/ivory.rgba"),
  _=>return Err("Unknown application icon.".into()),
 };
 Ok(tauri::image::Image::new(rgba,64,64))
}
const BRAND_APP_ID:&str="local.valharness.preview";
fn brand_ico(logo:&str)->Result<&'static [u8],String>{
 match logo {
  "gold"=>Ok(include_bytes!("../icons/gold.ico")),
  "silver"=>Ok(include_bytes!("../icons/silver.ico")),
  "jade"=>Ok(include_bytes!("../icons/jade.ico")),
  "blue"=>Ok(include_bytes!("../icons/blue.ico")),
  "rose"=>Ok(include_bytes!("../icons/rose.ico")),
  "ruby"=>Ok(include_bytes!("../icons/ruby.ico")),
  "violet"=>Ok(include_bytes!("../icons/violet.ico")),
  "ivory"=>Ok(include_bytes!("../icons/ivory.ico")),
  _=>Err("Unknown application icon.".into()),
 }
}
fn brand_property(store:&windows::Win32::UI::Shell::PropertiesSystem::IPropertyStore,pid:u32,value:&str)->windows::core::Result<()>{
 use std::mem::ManuallyDrop;
 use windows::{core::{GUID,PWSTR},Win32::{Foundation::{E_OUTOFMEMORY,PROPERTYKEY},System::{Com::{CoTaskMemAlloc,StructuredStorage::{PROPVARIANT,PROPVARIANT_0,PROPVARIANT_0_0,PROPVARIANT_0_0_0}},Variant::VT_LPWSTR}}};
 let text:Vec<u16>=value.encode_utf16().chain(Some(0)).collect();
 // The store copies the value, but PROPVARIANT owns VT_LPWSTR memory on drop: never point it at a Rust buffer.
 let memory=unsafe{CoTaskMemAlloc(text.len()*2)}.cast::<u16>();
 if memory.is_null(){return Err(E_OUTOFMEMORY.into());}
 unsafe{std::ptr::copy_nonoverlapping(text.as_ptr(),memory,text.len());}
 let variant=PROPVARIANT{Anonymous:PROPVARIANT_0{Anonymous:ManuallyDrop::new(PROPVARIANT_0_0{vt:VT_LPWSTR,wReserved1:0,wReserved2:0,wReserved3:0,Anonymous:PROPVARIANT_0_0_0{pwszVal:PWSTR(memory)}})}};
 unsafe{store.SetValue(&PROPERTYKEY{fmtid:GUID::from_u128(0x9f4c2855_9f79_4b39_a8d0_e1d42de1d5f3),pid},&variant)}
}
fn refresh_brand_shortcuts(icon:&std::path::Path)->Result<(),String>{
 use windows::{core::{Interface,PCWSTR},Win32::{System::Com::{CoCreateInstance,IPersistFile,CLSCTX_INPROC_SERVER,STGM_READWRITE},UI::Shell::{IShellLinkW,ShellLink,PropertiesSystem::IPropertyStore,SHChangeNotify,SHCNE_UPDATEITEM,SHCNF_PATHW}}};
 let exe=std::env::current_exe().map_err(|e|e.to_string())?;let wanted=exe.to_string_lossy().to_lowercase();
 let mut folders=Vec::new();if let Some(home)=std::env::var_os("USERPROFILE"){folders.push(PathBuf::from(home).join("Desktop"));}
 if let Some(roaming)=std::env::var_os("APPDATA"){let base=PathBuf::from(roaming);folders.push(base.join("Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar"));folders.push(base.join("Microsoft/Windows/Start Menu/Programs"));folders.push(base.join("Microsoft/Windows/Start Menu/Programs/V-Agent"));}
 let icon_w:Vec<u16>=icon.to_string_lossy().encode_utf16().chain(Some(0)).collect();
 for folder in folders{let Ok(files)=std::fs::read_dir(&folder)else{continue};for file in files.flatten(){let path=file.path();if path.extension().and_then(|v|v.to_str())!=Some("lnk"){continue;}
  let name=path.file_stem().unwrap_or_default().to_string_lossy().to_lowercase();if !folder.ends_with("TaskBar")&&!name.contains("v-agent")&&!name.contains("val agent"){continue;}
  let path_w:Vec<u16>=path.to_string_lossy().encode_utf16().chain(Some(0)).collect();
  unsafe{
   let link:IShellLinkW=CoCreateInstance(&ShellLink,None,CLSCTX_INPROC_SERVER).map_err(|e|e.to_string())?;let file:IPersistFile=link.cast().map_err(|e|e.to_string())?;
   if file.Load(PCWSTR(path_w.as_ptr()),STGM_READWRITE).is_err(){continue;}
   let mut target=[0u16;32768];if link.GetPath(&mut target,std::ptr::null_mut(),4).is_err(){continue;}
   let end=target.iter().position(|v|*v==0).unwrap_or(target.len());if String::from_utf16_lossy(&target[..end]).to_lowercase()!=wanted{continue;}
   link.SetIconLocation(PCWSTR(icon_w.as_ptr()),0).map_err(|e|e.to_string())?;
   let store:IPropertyStore=link.cast().map_err(|e|e.to_string())?;brand_property(&store,5,BRAND_APP_ID).map_err(|e|e.to_string())?;brand_property(&store,3,&format!("{},0",icon.display())).map_err(|e|e.to_string())?;store.Commit().map_err(|e|e.to_string())?;
   file.Save(PCWSTR(path_w.as_ptr()),true).map_err(|e|e.to_string())?;SHChangeNotify(SHCNE_UPDATEITEM,SHCNF_PATHW,Some(path_w.as_ptr().cast()),None);
  }
 }}Ok(())
}
fn apply_brand(window:&tauri::WebviewWindow,logo:&str)->Result<(),String>{
 use windows::Win32::{Foundation::HWND,UI::Shell::PropertiesSystem::{IPropertyStore,SHGetPropertyStoreForWindow}};
 let icon=brand_icon(logo)?;let ico=brand_ico(logo)?;let folder=user_data().join("branding");std::fs::create_dir_all(&folder).map_err(|e|e.to_string())?;
 let path=folder.join(format!("val-agent-{logo}-rounded-v2.ico"));if std::fs::read(&path).ok().as_deref()!=Some(ico){std::fs::write(&path,ico).map_err(|e|e.to_string())?;}
 window.set_icon(icon).map_err(|e|e.to_string())?;
 unsafe{let native=window.hwnd().map_err(|e|e.to_string())?;let store:IPropertyStore=SHGetPropertyStoreForWindow(HWND(native.0)).map_err(|e|e.to_string())?;
  brand_property(&store,5,BRAND_APP_ID).map_err(|e|e.to_string())?;brand_property(&store,2,&format!("\"{}\"",std::env::current_exe().unwrap().display())).map_err(|e|e.to_string())?;
  brand_property(&store,4,"V-Agent").map_err(|e|e.to_string())?;brand_property(&store,3,&format!("{},0",path.display())).map_err(|e|e.to_string())?;
 }
 refresh_brand_shortcuts(&path)
}
#[tauri::command]
fn window_brand_icon(app:AppHandle,logo:String)->Result<(),String>{
 let window=app.get_webview_window("main").ok_or("Main window unavailable.")?;apply_brand(&window,&logo)
}

fn web_url(value:&str)->Result<Url,String>{
 let text=value.trim();
 if text.is_empty(){return Err("Escribe una dirección web.".into());}
 let text=if text.contains("://"){text.to_string()}else{format!("https://{text}")};
 let url=Url::parse(&text).map_err(|_|"Dirección web no válida.".to_string())?;
 if !matches!(url.scheme(),"http"|"https"){return Err("Solo se permiten direcciones http o https.".into());}
 if url.port()==Some(19380)&&matches!(url.host_str(),Some("127.0.0.1")|Some("localhost")){
  return Err("La propia interfaz de VAL no se abre dentro del navegador.".into());
 }
 Ok(url)
}
fn internal_navigation(url:&Url)->bool{
 !(url.port()==Some(19380)&&matches!(url.host_str(),Some("127.0.0.1")|Some("localhost")))
}
fn valid_label(label:&str)->bool{
 label.len()>=7&&label.len()<=64&&label.starts_with("browser")&&label.chars().all(|value|value.is_ascii_alphanumeric()||value=='-'||value=='_')
}
fn tab(app:&AppHandle,label:&str)->Option<Webview>{app.get_webview(label)}
fn tab_state(app:&AppHandle,label:&str)->BrowserState{
 if let Some(view)=tab(app,label){
  BrowserState{open:true,url:view.url().map(|url|url.to_string()).unwrap_or_default()}
 }else{BrowserState{open:false,url:String::new()}}
}
fn set_bounds(view:&Webview,x:f64,y:f64,w:f64,h:f64)->Result<(),String>{
 if ![x,y,w,h].iter().all(|value|value.is_finite()){return Err("Medidas de navegador no válidas.".into());}
 view.set_position(LogicalPosition::new(x.max(0.),y.max(0.))).map_err(|error|error.to_string())?;
 view.set_size(LogicalSize::new(w.clamp(200.,4000.),h.clamp(120.,4000.))).map_err(|error|error.to_string())?;
 Ok(())
}

#[tauri::command]
async fn browser_tab_open(app:AppHandle,label:String,url:String,x:f64,y:f64,w:f64,h:f64)->Result<BrowserState,String>{
 if !valid_label(&label){return Err("Identificador de pestaña no válido.".into());}
 let target=web_url(&url)?;
 if let Some(view)=tab(&app,&label){
  set_bounds(&view,x,y,w,h)?;
  view.navigate(target).map_err(|error|error.to_string())?;
  let _=view.show();let _=view.set_focus();
 }else{
  let window=app.get_window("main").ok_or("No se encontró la ventana principal.")?;
  let app_handle=app.clone();
  let tab_label=label.clone();
  let view=window.add_child(
   WebviewBuilder::new(label.clone(),WebviewUrl::External(target))
    .on_navigation(|url|matches!(url.scheme(),"http"|"https"|"about")&&internal_navigation(url))
    .on_new_window(move|url,_features|{
     if matches!(url.scheme(),"http"|"https")&&internal_navigation(&url){
      if let Some(child)=tab(&app_handle,&tab_label){let _=child.navigate(url);}
     }
     tauri::webview::NewWindowResponse::Deny
    }),
   LogicalPosition::new(x.max(0.),y.max(0.)),
   LogicalSize::new(w.clamp(200.,4000.),h.clamp(120.,4000.))
  ).map_err(|error|error.to_string())?;
  let _=view.show();let _=view.set_focus();
 }
 Ok(tab_state(&app,&label))
}
#[tauri::command]
fn browser_tab_bounds(app:AppHandle,label:String,x:f64,y:f64,w:f64,h:f64)->Result<(),String>{
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 set_bounds(&view,x,y,w,h)
}
#[tauri::command]
fn browser_tab_show(app:AppHandle,label:String)->Result<BrowserState,String>{
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 view.show().map_err(|error|error.to_string())?;
 let _=view.set_focus();
 Ok(tab_state(&app,&label))
}
#[tauri::command]
fn browser_tab_hide(app:AppHandle,label:String)->Result<(),String>{
 if let Some(view)=tab(&app,&label){view.hide().map_err(|error|error.to_string())?;}
 Ok(())
}
#[tauri::command]
fn browser_tab_close(app:AppHandle,label:String)->Result<BrowserState,String>{
 if let Some(view)=tab(&app,&label){view.close().map_err(|error|error.to_string())?;}
 Ok(BrowserState{open:false,url:String::new()})
}
#[tauri::command]
fn browser_tab_state(app:AppHandle,label:String)->BrowserState{tab_state(&app,&label)}
#[tauri::command]
fn browser_tab_navigate(app:AppHandle,label:String,url:String)->Result<BrowserState,String>{
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 view.navigate(web_url(&url)?).map_err(|error|error.to_string())?;
 let _=view.show();let _=view.set_focus();
 Ok(tab_state(&app,&label))
}
#[tauri::command]
fn browser_tab_back(app:AppHandle,label:String)->Result<BrowserState,String>{
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 view.eval("history.back()").map_err(|error|error.to_string())?;
 Ok(tab_state(&app,&label))
}
#[tauri::command]
fn browser_tab_forward(app:AppHandle,label:String)->Result<BrowserState,String>{
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 view.eval("history.forward()").map_err(|error|error.to_string())?;
 Ok(tab_state(&app,&label))
}
#[tauri::command]
fn browser_tab_reload(app:AppHandle,label:String)->Result<BrowserState,String>{
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 view.eval("location.reload()").map_err(|error|error.to_string())?;
 Ok(tab_state(&app,&label))
}
#[tauri::command(rename_all="snake_case")]
async fn browser_tab_dom(app:AppHandle,label:String,action:String,selector:Option<String>,text:Option<String>,key:Option<String>,script:Option<String>,max_chars:Option<usize>)->Result<serde_json::Value,String>{
 const ACTIONS:[&str;6]=["snapshot","text","click","fill","press","eval"];
 if !ACTIONS.contains(&action.as_str()){return Err("Acción de navegador no admitida.".into());}
 let view=tab(&app,&label).ok_or("La pestaña del navegador no existe.")?;
 let js=r#"(() => {
  try {
    const action = __ACTION__;
    const selector = __SELECTOR__;
    const text = __TEXT__;
    const key = __KEY__;
    const script = __SCRIPT__;
    const maxChars = __MAX__;
    const clean = value => String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
    const visible = el => {
      const style = (el.ownerDocument.defaultView || window).getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const collectRoots = (root, out = []) => {
      if (!root) return out;
      out.push(root);
      for (const el of root.querySelectorAll('*')) {
        if (el.shadowRoot) collectRoots(el.shadowRoot, out);
        if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
          try { if (el.contentDocument) collectRoots(el.contentDocument, out); } catch (e) {}
        }
      }
      return out;
    };
    const findEl = (sel, root = document) => {
      if (!root || !sel) return null;
      let hit = null;
      try { hit = root.querySelector(sel); } catch (e) { return null; }
      if (hit) return hit;
      for (const el of root.querySelectorAll('*')) {
        if (el.shadowRoot) { hit = findEl(sel, el.shadowRoot); if (hit) return hit; }
        if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
          try { if (el.contentDocument) { hit = findEl(sel, el.contentDocument); if (hit) return hit; } } catch (e) {}
        }
      }
      return null;
    };
    if (action === 'snapshot' || action === 'text') {
      const roots = collectRoots(document);
      const textParts = [], seenText = new Set();
      const addChunk = raw => {
        const s = String(raw || '').trim();
        if (s && !seenText.has(s)) { seenText.add(s); textParts.push(s); }
      };
      addChunk(document.body ? document.body.innerText : '');
      for (const r of roots.slice(1)) {
        if (r.host && r.host.shadowRoot === r) {
          for (const child of r.childNodes) {
            if (child.nodeType === 1 && !['SCRIPT','STYLE','TEMPLATE'].includes(child.tagName)) {
              addChunk(child.innerText || child.textContent);
            } else if (child.nodeType === 3) {
              addChunk(child.nodeValue);
            }
          }
        } else if (r.body) {
          addChunk(r.body.innerText);
        }
      }
      const pageText = textParts.join('\n').slice(0, maxChars);
      const items = [];
      if (action === 'snapshot') {
        for (const r of roots) r.querySelectorAll('[data-val-ref]').forEach(el => el.removeAttribute('data-val-ref'));
        const token = 'val' + Date.now().toString(36);
        let count = 0;
        const nodes = [];
        for (const r of roots) for (const el of r.querySelectorAll('a[href],button,input,select,textarea,[role=button],[role=link],[role=textbox],[contenteditable=true],[onclick]')) nodes.push(el);
        for (const el of nodes) {
          if (count >= 60) break;
          if (!visible(el)) continue;
          const tag = el.tagName.toLowerCase();
          const type = clean(el.getAttribute('type') || el.getAttribute('role') || '');
          const label = clean(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.getAttribute('value') || el.getAttribute('placeholder') || '').slice(0, 120);
          const name = clean(el.getAttribute('name') || '');
          if (tag === 'a' && !label && !name) continue;
          const ref = token + '-' + (count + 1);
          el.setAttribute('data-val-ref', ref);
          const item = {
            selector: '[data-val-ref="' + ref + '"]',
            tag
          };
          if (type) item.type = type;
          if (label) item.text = label;
          if (name) item.name = name;
          if (el.href) item.href = String(el.href).slice(0, 300);
          if (el.disabled) item.disabled = true;
          if (el.checked) item.checked = true;
          items.push(item);
          count += 1;
        }
      }
      return {ok: true, title: document.title, url: location.href, text: pageText, items};
    }
    if (action === 'eval') {
      const raw = eval(script);
      let value = raw === undefined ? null : raw;
      try { JSON.stringify(value); } catch { value = String(raw); }
      return {ok: true, value};
    }
    if (!selector) return {ok: false, error: 'Missing selector.'};
    const el = findEl(selector);
    if (!el) return {ok: false, error: 'Element not found: ' + selector};
    el.scrollIntoView({block: 'center', inline: 'center'});
    if (action === 'click') {
      el.focus({preventScroll: true});
      const link = el.closest ? el.closest('a[href]') : null;
      const hadTarget = link ? link.getAttribute('target') : null;
      if (link && hadTarget && hadTarget !== '_self') link.setAttribute('target', '_self');
      el.click();
      if (link && hadTarget) link.setAttribute('target', hadTarget);
      return {ok: true, clicked: true, tag: el.tagName.toLowerCase()};
    }
    if (action === 'fill') {
      if (el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'file') {
        return {ok: false, error: 'WebView2 cannot programmatically set <input type="file"> paths; use autobrowser__open + autobrowser__fill for file uploads.'};
      }
      const value = text == null ? '' : text;
      el.focus({preventScroll: true});
      if (el.isContentEditable) {
        el.textContent = value;
        el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        return {ok: true, filled: true, value: String(el.textContent).slice(0, 200)};
      }
      const w = el.ownerDocument.defaultView || window;
      const proto = el instanceof w.HTMLTextAreaElement ? w.HTMLTextAreaElement.prototype : el instanceof w.HTMLSelectElement ? w.HTMLSelectElement.prototype : w.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(el, value); else el.value = value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return {ok: true, filled: true, value: String(el.value).slice(0, 200)};
    }
    if (action === 'press') {
      const pressed = key || 'Enter';
      el.focus({preventScroll: true});
      const keyCodes = {Enter: 13, Escape: 27, Tab: 9, Backspace: 8, ArrowUp: 38, ArrowDown: 40, ArrowLeft: 37, ArrowRight: 39};
      const code = pressed.length === 1 && /[a-z]/i.test(pressed) ? ('Key' + pressed.toUpperCase()) : pressed;
      const keyCode = keyCodes[pressed] ?? (pressed.length === 1 ? pressed.toUpperCase().charCodeAt(0) : 0);
      const options = {key: pressed, code, keyCode, which: keyCode, bubbles: true, cancelable: true};
      el.dispatchEvent(new KeyboardEvent('keydown', options));
      el.dispatchEvent(new KeyboardEvent('keypress', options));
      el.dispatchEvent(new KeyboardEvent('keyup', options));
      let submitted = false;
      if (pressed === 'Enter') {
        const form = el.form || el.closest('form');
        if (form) {
          try { form.requestSubmit(); submitted = true; } catch (error) {}
        } else {
          const scope = el.closest('form') || el.parentElement;
          const button = scope ? scope.querySelector('button[type=submit], button:not([type]), input[type=submit], [role=button]') : null;
          if (button) { button.click(); submitted = true; }
        }
      }
      return {ok: true, pressed: true, submitted};
    }
    return {ok: false, error: 'Acción no admitida.'};
  } catch (error) {
    return {ok: false, error: String(error && error.stack || error)};
  }
})()"#
 .replace("__ACTION__",&serde_json::to_string(&action).unwrap())
 .replace("__SELECTOR__",&serde_json::to_string(&selector).unwrap())
 .replace("__TEXT__",&serde_json::to_string(&text).unwrap())
 .replace("__KEY__",&serde_json::to_string(&key).unwrap())
 .replace("__SCRIPT__",&serde_json::to_string(&script).unwrap())
 .replace("__MAX__",&max_chars.unwrap_or(12000).clamp(500,20000).to_string());
 let (sender,receiver)=std::sync::mpsc::channel::<String>();
 view.eval_with_callback(js,move|value|{let _=sender.send(value);}).map_err(|error|error.to_string())?;
 let value=std::thread::spawn(move||receiver.recv_timeout(Duration::from_secs(15))).join()
  .map_err(|_|"El navegador no respondió.".to_string())?
  .map_err(|_|"El navegador no respondió a tiempo.".to_string())?;
 serde_json::from_str(&value).map_err(|error|format!("Respuesta de navegador no válida: {error}"))
}

fn status(port:u16)->Option<serde_json::Value>{
 let addr:SocketAddr=format!("127.0.0.1:{port}").parse().ok()?;
 let mut socket=TcpStream::connect_timeout(&addr,Duration::from_millis(200)).ok()?;
 socket.set_read_timeout(Some(Duration::from_millis(800))).ok()?;
 socket.write_all(b"GET /api/harness/state HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n").ok()?;
 let mut bytes=Vec::new();socket.take(32768).read_to_end(&mut bytes).ok()?;
 let text=String::from_utf8(bytes).ok()?;let body=text.split_once("\r\n\r\n")?.1;
 let value:serde_json::Value=serde_json::from_str(body).ok()?;
 if value["product"]=="VALAgent" || value["product"]=="VALHarness" || value["product"]=="V-Agent"{Some(value)}else{None}
}

fn core_path()->Option<PathBuf>{
 let exe=std::env::current_exe().ok()?;let folder=exe.parent()?;
 for path in [folder.join("core/strata-core.exe"),folder.join("backend/strata-core.exe")]{if path.is_file(){return Some(path)}}
 None
}

fn user_data()->PathBuf{
 let exe=std::env::current_exe().unwrap();let folder=exe.parent().unwrap();
 let config=folder.join("val-portable.json");
 if let Ok(text)=std::fs::read_to_string(config){if let Ok(value)=serde_json::from_str::<serde_json::Value>(&text){if let Some(path)=value["data_dir"].as_str(){let p=folder.join(path);let _=std::fs::create_dir_all(&p);return p}}}
 let p=PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_default()).join("V-Agent-Data");let _=std::fs::create_dir_all(&p);p
}

// Open only a previously validated conversation workspace, never an arbitrary path.
#[link(name="shell32")]
extern "system" {
 fn ShellExecuteW(hwnd:*mut std::ffi::c_void,operation:*const u16,file:*const u16,parameters:*const u16,directory:*const u16,show:i32)->isize;
}
#[tauri::command]
fn open_sandbox_folder(app:AppHandle,conversation_id:String)->Result<(),String>{
 if conversation_id.is_empty()||conversation_id.len()>80||!conversation_id.bytes().all(|b|b.is_ascii_lowercase()||b.is_ascii_digit()||b==b'_'||b==b'-')||!conversation_id.as_bytes()[0].is_ascii_alphanumeric(){return Err("Identificador de conversación no válido.".into());}
 let base=user_data().join("workspaces/conversations");
 let root=std::fs::canonicalize(&base).map_err(|_|"No existe la carpeta del Sandbox.".to_string())?;
 let dir=std::fs::canonicalize(base.join(&conversation_id)).map_err(|_|"No existe la carpeta de esta conversación.".to_string())?;
 if dir.parent()!=Some(root.as_path())||!dir.is_dir(){return Err("La carpeta del Sandbox no es válida.".into());}
 show_folder(&app,&base.join(&conversation_id))
}

#[tauri::command]
fn open_engine_folder(app:AppHandle,folder:String)->Result<(),String>{
 let dir=match folder.as_str(){
  "bundled"=>std::env::current_exe().map_err(|e|e.to_string())?.parent().ok_or("No se encontró la carpeta del ejecutable.")?.join("core/_internal/runtime"),
  "updates"=>user_data().join("engine-updates"),
  _=>return Err("Carpeta desconocida.".into()),
 };
 if !dir.is_dir(){return Err("La carpeta de motores no está disponible.".into());}
 show_folder(&app,&dir)
}

fn show_folder(app:&AppHandle,dir:&std::path::Path)->Result<(),String>{
 let file:Vec<u16>=dir.as_os_str().to_string_lossy().encode_utf16().chain(Some(0)).collect();
 let class:Vec<u16>="Shell_TrayWnd".encode_utf16().chain(Some(0)).collect();
 let owner=app.get_webview_window("main").ok_or("No se encontró la ventana principal.")?.hwnd().map_err(|e|e.to_string())?;
 unsafe{
  // Explorer often reuses its existing process. Permit that process to take focus.
  let tray=FindWindowW(class.as_ptr(),std::ptr::null());let mut pid=0u32;
  if !tray.is_null(){GetWindowThreadProcessId(tray,&mut pid);if pid!=0{AllowSetForegroundWindow(pid);}}
  let result=ShellExecuteW(owner.0,std::ptr::null(),file.as_ptr(),std::ptr::null(),std::ptr::null(),1);
  if result<=32{return Err(format!("No se pudo abrir la carpeta (Windows {result})."));}
 }
 Ok(())
}

#[tauri::command]
fn open_guide()->Result<(),String>{
 let url="http://127.0.0.1:19380/guide.html";
 Command::new("rundll32").args(["url.dll,FileProtocolHandler",url]).creation_flags(0x08000000).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().map(|_|()).map_err(|error|format!("No se pudo abrir la guía: {error}"))
}
#[tauri::command]
fn open_uninstaller()->Result<(),String>{
 let executable=std::env::current_exe().map_err(|e|e.to_string())?;
 let uninstaller=executable.parent().ok_or("No se encontró la carpeta de V-Agent.")?.join("uninstall.exe");
 if !uninstaller.is_file(){return Err("No se encontró el desinstalador. Esta instalación puede ser portátil.".into());}
 Command::new(&uninstaller).current_dir(executable.parent().unwrap()).spawn().map(|_|()).map_err(|e|format!("No se pudo abrir el desinstalador: {e}"))
}
fn main(){
 unsafe{let _=windows::Win32::UI::Shell::SetCurrentProcessExplicitAppUserModelID(windows::core::w!("local.valharness.preview"));}
 let owned:Arc<Mutex<Option<Child>>>=Arc::new(Mutex::new(None));
 let setup_child=owned.clone();
 let app=tauri::Builder::default()
 .plugin(tauri_plugin_single_instance::init(|app,_,_|{if let Some(window)=app.get_webview_window("main"){let _=window.show();let _=window.unminimize();let _=window.set_focus();}}))
 .invoke_handler(tauri::generate_handler![open_sandbox_folder,open_engine_folder,open_guide,open_uninstaller,window_appearance,window_brand_icon,browser_tab_open,browser_tab_bounds,browser_tab_show,browser_tab_hide,browser_tab_close,browser_tab_state,browser_tab_navigate,browser_tab_back,browser_tab_forward,browser_tab_reload,browser_tab_dom])
 .setup(move|app|{
  let (width,height)=app.primary_monitor()?.map(|monitor|{
   let area=monitor.work_area();let scale=monitor.scale_factor();
   ((area.size.width as f64/scale-40.).min(1280.).max(320.),(area.size.height as f64/scale-72.).min(820.).max(240.))
  }).unwrap_or((1100.,700.));
  let migration=std::fs::read_to_string(user_data().join("ui-storage-migration.json")).ok()
   .and_then(|text|serde_json::from_str::<serde_json::Value>(&text).ok())
   .and_then(|value|serde_json::to_string(&value).ok())
   .map(|json|format!("try{{const d={json};for(const k in d){{if(localStorage.getItem(k)===null)localStorage.setItem(k,String(d[k]));}}}}catch{{}}"));
  let ui_preferences=std::fs::read_to_string(user_data().join("settings/ui-preferences.json")).ok().and_then(|v|serde_json::from_str::<serde_json::Value>(&v).ok()).unwrap_or_default();
  let theme=&ui_preferences["theme"];let theme_mode=theme["mode"].as_str().unwrap_or("night");
  let background=theme[theme_mode]["bg"].as_str().unwrap_or("#11171c");
  let rgb=u32::from_str_radix(background.trim_start_matches('#'),16).unwrap_or(0x11171c);
  let background_color=tauri::window::Color(((rgb>>16)&255) as u8,((rgb>>8)&255) as u8,(rgb&255) as u8,255);
  let mut builder=WebviewWindowBuilder::new(app,"main",WebviewUrl::App("v-agent.html".into())).title("V-Agent").inner_size(width,height).min_inner_size(width.min(760.),height.min(480.)).center().maximized(true).visible(false).decorations(false).disable_drag_drop_handler().background_color(background_color);
  // Explicit live-window icon also updates the taskbar, independent of Explorer's executable cache.
  let preferences=std::fs::read_to_string(user_data().join("settings/app-preferences.json")).ok().and_then(|v|serde_json::from_str::<serde_json::Value>(&v).ok()).unwrap_or_default();
  let decoration=&preferences["decoration"];
  let icon_choice=decoration["appIcon"].as_str().filter(|v|*v!="follow").or_else(||decoration["logo"].as_str()).unwrap_or("gold");
  builder=builder.icon(brand_icon(icon_choice).or_else(|_|brand_icon("gold"))?)?;
  if let Some(script)=migration{builder=builder.initialization_script(script);}
  builder=builder.on_page_load(|window,payload|{if matches!(payload.event(),PageLoadEvent::Finished){let _=window.show();let _=window.maximize();}});
  let _window=builder.build()?;
  if let Err(error)=apply_taskbar_identity(&_window){eprintln!("Windows taskbar: {error}");}
  if let Err(error)=apply_brand(&_window,icon_choice){eprintln!("Windows icon: {error}");}
  if let Ok(text)=std::fs::read_to_string(user_data().join("settings/ui-preferences.json")){
   if let Ok(record)=serde_json::from_str::<serde_json::Value>(&text){
    let theme=&record["theme"];let mode=theme["mode"].as_str().unwrap_or("night");
    if let Some(background)=theme[mode]["panel"].as_str(){let _=apply_window_appearance(&_window,mode!="day",background,theme[mode]["radius"].as_u64().unwrap_or(12).min(40) as u32);}
   }
  }
  let child=setup_child.clone();
  std::thread::spawn(move||{
   let port=19380u16;
   if status(port).is_none(){
    let result=if let Some(core)=core_path(){
     Command::new(core).args(["--port",&port.to_string()]).arg("--data-dir").arg(user_data()).env("V_AGENT_DESKTOP_PID",std::process::id().to_string()).env("V_AGENT_DESKTOP_EXE",std::env::current_exe().unwrap_or_default()).creation_flags(0x08000000).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn()
    }else if cfg!(debug_assertions){
     let root=PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().to_path_buf();
     Command::new(root.join(".venv/Scripts/python.exe")).arg(root.join("backend.py")).args(["--port",&port.to_string()]).current_dir(&root).creation_flags(0x08000000).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn()
    }else{Err(std::io::Error::new(std::io::ErrorKind::NotFound,"No se encontró core/strata-core.exe junto a la aplicación."))};
    match result{Ok(process)=>{*child.lock().unwrap()=Some(process);},Err(error)=>{let logs=user_data().join("logs");let _=std::fs::create_dir_all(&logs);let _=std::fs::write(logs.join("desktop-error.log"),format!("No se pudo iniciar el servicio local: {error}\n"));}}
   }
  });Ok(())
 }).build(tauri::generate_context!()).expect("No se pudo iniciar V-Agent");
 app.run(move|_,event|{if matches!(event,tauri::RunEvent::Exit){
  if let Some(mut process)=owned.lock().unwrap().take(){
   // Allow disconnected streams to save their final draft before closing our tree.
   std::thread::sleep(Duration::from_millis(700));
   if matches!(process.try_wait(),Ok(None)){let _=Command::new("taskkill").args(["/F","/T","/PID",&process.id().to_string()]).creation_flags(0x08000000).stdout(Stdio::null()).stderr(Stdio::null()).status();let _=process.wait();}
  }
 }});
}
