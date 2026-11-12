# -*- coding: utf-8 -*-
"""render_check: abrir el HTML del agente en un navegador sin cabeza y traer la evidencia.

Por que esto y no fiarse del texto del modelo. Los harness abiertos ya no creen en el "queda
precioso": Cline y Roo exigen verificar ejecutando, OpenHands para el run si algo no cuadra, y
Vercel agent-browser trabaja con resumenes de ~280 caracteres en vez de arboles de accesibilidad
de miles de tokens. Aqui la evidencia son tres lineas: cuantos nodos tiene el documento, si el
canvas abrio WebGL de verdad y si la consola tiro errores.

Que navegador usa, por orden:
  1. `STRATA_AGENT_BROWSER` si el usuario senala uno,
  2. chrome-headless-shell (Google Chrome for Testing, descargado en la carpeta browser/:
     284 MB descomprimido, sin instalacion, sin interfaz, con vk_swiftshader.dll para WebGL por
     software),
  3. Chrome / Edge / Brave ya instalados.
No se uso Lightpanda (76 MB, "16x mas ligero"): no publica binario de Windows y no pinta WebGL,
que es justo lo que hay que comprobar. Tampoco browser-use/Stagehand/agent-browser: piden Chrome
propio o ~700 MB de Node, y hablan CDP por debajo - aqui se habla CDP directamente.

Sesion. El navegador se abre UNA vez y se queda vivo entre renderizados (lo que relanza el
navegador en cada prueba, como hacia esta primera version, cuesta 22-29 s; reutilizarlo baja a
1-2 s). El websocket de DevTools si es nuevo en cada llamada, que es mas simple y igual de
rapido. A los INACTIVO_S segundos sin uso se cierra solo para no dejar 300 MB de RAM ocupados
mientras el modelo trabaja, y al cerrar el agente se cierra tambien (atexit).

Fugas. Edge y Chrome no viven como hijos del proceso que lanzamos: el de la linea de comandos se
va y deja el navegador real re-origindose. Por eso `taskkill /T` sobre nuestro pid no mataba nada
y en la primera prueba quedaron 16 msedge.exe vivos. La senal que identifica a LOS NUESTROS sin
tocar el navegador del usuario es el `--user-data-dir` del perfil: por ahi se cierran.
"""
import atexit
import base64
import json
import os
import pathlib
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

TIEMPO_CARGA_MS = int(os.environ.get("STRATA_AGENT_RENDER_MS", "2200"))
INACTIVO_S = int(os.environ.get("STRATA_AGENT_BROWSER_IDLE", "45"))
# Techo de pared de una comprobacion. Medido: una pagoda de ~20k voxels tarda 30-80 s en montarse
# con SwiftShader (la GPU no participa), y dejar que el modelo espere un minuto por cada prueba es
# peor que no probar. Al pasarse, se dice claro que tardo y se puede reintentar con mas espera.
TECHO_S = int(os.environ.get("STRATA_AGENT_RENDER_MAX_S", "45"))
# Con `mantener` a falso el navegador se cierra despues de cada prueba: la sesion caliente ahorra
# medio segundo, pero deja 55 MB de RAM y CPU de SwiftShader compitiendo con la inferencia, y eso
# en esta laptop vale mas que medio segundo.
MANTENER = os.environ.get("STRATA_AGENT_BROWSER_KEEPALIVE", "0") == "1"
# Cuanto mas grande el lenzo, mas pixeles tiene que pintar SwiftShader (CPU) y mas tarda la
# prueba; con 800x450 se ve el mismo error de consola en una cuarta parte del trabajo.
VENTANA = tuple(int(x) for x in os.environ.get("STRATA_AGENT_BROWSER_WINDOW", "800,450").split(","))
from runtime_paths import SOURCE_ROOT, DATA_ROOT
RAIZ = SOURCE_ROOT/"agent"
# The profile is user data: never inside the program folder (read-only or replaced on update).
PERFIL = pathlib.Path(os.environ.get("STRATA_AGENT_BROWSER_PROFILE", str(DATA_ROOT / "cache" / "render-profile")))
SHELLS = (str(RAIZ.parent / "browser" / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"),)
NAVEGADORES = SHELLS + (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
)
# Ruido del driver o del propio cromo, no de la pagina: con SwiftShader "GPU stall due to
# ReadPixels" aparece en cada snapshot y no significa que la escena este rota.
RUIDO = ("gpu stall", "readpixels", "deprecation", "autofill", "devtools",
         "webgl-0x", "fallback to", "networkservice")

SONDA_PINTURA = """new Promise((res) => requestAnimationFrame(() => {
  // readPixels tiene que ir DENTRO del frame: fuera, el backbuffer ya esta limpio y devuelve
  // ceros incluso en una escena que se ve perfecta (falso positivo medido el 2026-11-03).
  const c = document.querySelector('canvas');
  let gl = null;
  try { gl = c && (c.getContext('webgl2') || c.getContext('webgl')); } catch (e) {}
  if (!gl) return res({pixeles_pintados: null});
  try {
    const w = Math.min(gl.drawingBufferWidth, 400), h = Math.min(gl.drawingBufferHeight, 400);
    const px = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    let distintos = 0;
    for (let i = 0; i < px.length; i += 4 * 733) { if (px[i] || px[i+1] || px[i+2]) distintos++; }
    res({pixeles_pintados: distintos});
  } catch (e) { res({pixeles_pintados: -1}); }
}))"""

SONDA = """(() => {
  const c = document.querySelector('canvas');
  let gl = null, version = null, contexto = 'ninguno';
  if (c) {
    try { gl = c.getContext('webgl2'); if (gl) contexto = 'webgl2'; } catch (e) {}
    if (!gl) { try { gl = c.getContext('webgl'); if (gl) contexto = 'webgl'; } catch (e) {} }
    if (gl) version = String(gl.getParameter(gl.VERSION)) + ' | ' + String(gl.getParameter(gl.RENDERER));
  }
  let frames = null;
  if (c && gl) frames = performance.now();
  return {
    titulo: document.title || '',
    nodos: document.getElementsByTagName('*').length,
    canvas: document.querySelectorAll('canvas').length,
    dimensiones: c ? [c.width, c.height] : null,
    contexto_webgl: contexto, webgl: version, tiempo_ms: frames,
    three: (window.THREE ? String(window.THREE.REVISION) : null),
    scripts: document.querySelectorAll('script').length,
    imagenes_rotas: Array.from(document.images || []).filter(i => i.complete && i.naturalWidth === 0).length,
    cuerpo: (document.body ? (document.body.innerText || '').slice(0, 140) : '')
  };
})()"""


def navegador():
    """El navegador sin cabeza a usar: el senalado, el shell descargado, o el instalado que haya."""
    senalado = os.environ.get("STRATA_AGENT_BROWSER")
    if senalado and pathlib.Path(senalado).exists():
        return senalado
    for ruta in NAVEGADORES:
        if pathlib.Path(ruta).exists():
            return ruta
    return None


def _puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    n = s.getsockname()[1]
    s.close()
    return n


def _json(puerto, ruta, espera=.5):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (puerto, ruta), timeout=espera) as r:
        return json.loads(r.read())


def _cierra_por_perfil():
    """Cerrar el navegador buscando nuestro perfil en la linea de comandos (Edge se re-origina)."""
    import psutil
    marcados, nombre = [], ""
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            nombre = (p.info["name"] or "").lower()
        except Exception:
            continue
        if str(PERFIL) in cmd and nombre in ("msedge.exe", "chrome.exe", "chrome-headless-shell.exe",
                                             "brave.exe", "headless_shell.exe"):
            marcados.append(p)
    targets={p.pid:p for p in marcados}
    for p in marcados:
        try:
            for hijo in p.children(recursive=True):
                targets[hijo.pid]=hijo
        except Exception:
            pass
    for p in reversed(list(targets.values())):
        try:
            p.kill()
        except Exception:
            pass
    # Windows keeps profile files locked until the processes have actually exited.
    psutil.wait_procs(list(targets.values()),timeout=5)
    return len(marcados)


class Sesion:
    """El navegador vivo, con su perfil propio y su puerto de DevTools."""

    def __init__(self):
        self.proceso = None
        self.puerto = 0
        self.usado = 0.0
        self.fallo = ""
        self.hijos = 0

    def vivo(self):
        return bool(self.proceso) and self.proceso.poll() is None

    def abre(self):
        ruta = navegador()
        if not ruta:
            self.fallo = "no hay navegador sin cabeza: instala chrome-headless-shell o activa Edge"
            return False
        PERFIL.mkdir(parents=True, exist_ok=True)
        self.puerto = _puerto_libre()
        argumentos = [ruta, "--headless=new", "--disable-gpu", "--no-sandbox",
                      "--disable-extensions", "--disable-component-extensions-with-background-pages",
                      "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
                      "--remote-debugging-port=%d" % self.puerto, "--user-data-dir=" + str(PERFIL),
                      "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader",
                      "--window-size=%d,%d" % VENTANA, "about:blank"]
        try:
            self.proceso = subprocess.Popen(argumentos, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Thread(target=_vigilante, name="render-inactivo", daemon=True).start()
        except OSError as error:
            self.fallo = "no se pudo lanzar %s: %s" % (pathlib.Path(ruta).name, str(error)[:120])
            return False
        self.ruta = ruta
        # 15 s, no 40: si el navegador no expone DevTools en ese margen es que no va a exponerlos,
        # y esperar cuarenta segundos en cada intento congela la conversacion.
        fin = time.time() + 15
        while time.time() < fin:
            try:
                _json(self.puerto, "/json/version", espera=.4)
                self.usado = time.time()
                return True
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(.08)
        self.fallo = "el navegador no abrio DevTools en el puerto %d" % self.puerto
        self.cierra()
        return False

    def cierra(self):
        process = self.proceso
        if process is not None:
            try:
                self.hijos = _cierra_por_perfil()
            except Exception:
                pass
            try:
                if process.poll() is None:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=15,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                process.wait(timeout=5)
            except Exception:
                pass
        self.proceso = None
        self.puerto = 0


def _vigilante():
    """Cierra el navegador si nadie lo usa, aunque no vuelva a llamarse.

    Sin esto el cierre por inactividad solo se evaluaba DENTRO de render(): si el agente dejaba de
    comprobar paginas, los cinco procesos del shell se quedaban abiertos comiendo RAM durante el
    resto de la sesion (y eso es justo lo que no puede competir con la inferencia).
    """
    while True:
        time.sleep(5)
        if not _SESION.vivo():
            return
        if time.time() - _SESION.usado > INACTIVO_S:
            with _CANDADO:
                if time.time() - _SESION.usado > INACTIVO_S:
                    _SESION.cierra()
            return


_SESION = Sesion()
_CANDADO = threading.RLock()
atexit.register(_SESION.cierra)


# La vista previa de V-Agent abre el HTML en un iframe con sandbox="allow-scripts allow-modals" y
# origen opaco (blob:). Ahi localStorage, sessionStorage, cookies, IndexedDB y Cache Storage lanzan
# SecurityError y window.open devuelve null. Abierta como file:// todo eso funciona, asi que el
# detector decia "0 errores" mientras la vista previa fallaba. Se reproducen las mismas reglas antes
# de que corra el primer script de la pagina: un acceso protegido con try/catch sigue sin error,
# igual que en la vista previa; uno sin proteger sale como error con el mismo texto del navegador.
SANDBOX_VISTA_PREVIA = r"""(() => {
  const texto = (prop, dueno) => "Failed to read the '" + prop + "' property from '" + dueno +
    "': The document is sandboxed and lacks the 'allow-same-origin' flag.";
  const niega = (obj, prop, dueno, setter) => {
    try {
      const fallo = () => { throw new DOMException(texto(prop, dueno), 'SecurityError'); };
      Object.defineProperty(obj, prop, setter ? {configurable: true, get: fallo, set: fallo} : {configurable: true, get: fallo});
    } catch (e) {}
  };
  niega(window, 'localStorage', 'Window');
  niega(window, 'sessionStorage', 'Window');
  niega(Document.prototype, 'cookie', 'Document', true);
  try {
    IDBFactory.prototype.open = function () {
      throw new DOMException("Failed to execute 'open' on 'IDBFactory': access to the IndexedDB API is denied in this context.", 'SecurityError');
    };
  } catch (e) {}
  try {
    for (const m of ['open', 'has', 'keys', 'match', 'delete']) {
      CacheStorage.prototype[m] = function () {
        return Promise.reject(new DOMException('An attempt was made to break through the security policy of the user agent.', 'SecurityError'));
      };
    }
  } catch (e) {}
  window.open = function (url) {
    console.warn("Blocked opening '" + (url || '') + "' in a new window because the request was made in a sandboxed frame whose 'allow-popups' permission is not set.");
    return null;
  };
})();"""
PISTA_VISTA_PREVIA = ("la vista previa de V-Agent aisla la pagina (iframe sandbox sin allow-same-origin): "
                      "localStorage, sessionStorage, cookies e IndexedDB lanzan SecurityError. "
                      "Envuelve su uso en try/catch y usa un respaldo en memoria.")


def _evento(msg, consola, errores):
    m = msg.get("method")
    if m == "Runtime.consoleAPICalled":
        p = msg.get("params", {})
        texto = " ".join(str(a.get("value", a.get("description", a.get("type", ""))))[:150]
                         for a in p.get("args", []))
        consola.append("%s: %s" % (p.get("type", "log"), texto[:220]))
    elif m == "Runtime.exceptionThrown":
        d = msg.get("params", {}).get("exceptionDetails", {})
        des = (d.get("exception") or {}).get("description") or d.get("text") or ""
        # La linea (CDP la da desde 0) deja al modelo ir con fs_read(linea=...) al punto exacto.
        donde = ((d.get("url") or "").split("/")[-1] or "pagina")[:34]
        if isinstance(d.get("lineNumber"), int):
            donde += ":%d" % (d["lineNumber"] + 1)
        errores.append("%s: %s" % (donde, str(des)[:230]))
    elif m == "Log.entryAdded":
        e = msg.get("params", {}).get("entry", {})
        if e.get("level") == "error":
            url=(e.get('url') or '').split('?',1)[0].split('#',1)[0]
            if url.endswith('/favicon.ico'):
                return
            errores.append("%s: %s%s" % (e.get("source", "?"), str(e.get("text", ""))[:230],
                                         ' ('+url[:160]+')' if url else ''))


def _navega(url, espera_ms, captura, pintura=False, segundos=TECHO_S, diagnostics=False, vista_previa=False):
    """Una pasada CDP: navegar, esperar, sondear y capturar. El navegador sigue vivo despues."""
    import asyncio
    import websockets

    async def correr():
        consola, errores, n = [], [], [0]
        target = None
        fin = time.time() + 15
        while time.time() < fin and target is None:
            try:
                for t in _json(_SESION.puerto, "/json/list", espera=.4):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        target = t
                        break
            except (urllib.error.URLError, OSError, ValueError):
                await asyncio.sleep(.08)
        if not target:
            return {"_error": "la pestana del navegador no responde"}
        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=None,
                                      close_timeout=2, open_timeout=12) as ws:
            async def llama(metodo, params=None, escucha=None):
                n[0] += 1
                mid = n[0]
                await ws.send(json.dumps({"id": mid, "method": metodo, "params": params or {}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 25))
                    if escucha:
                        escucha(msg)
                    else:
                        _evento(msg, consola, errores)
                    if msg.get("id") == mid:
                        if "error" in msg:
                            return {"_error": msg["error"].get("message")}
                        return msg.get("result", {})

            cargado = [False]

            def escucha(msg):
                _evento(msg, consola, errores)
                if msg.get("method") == "Page.loadEventFired":
                    cargado[0] = True

            for dominio in ("Runtime.enable", "Log.enable", "Page.enable"):
                await llama(dominio, escucha=escucha)
            inyectado = None
            if vista_previa:
                inyectado = (await llama("Page.addScriptToEvaluateOnNewDocument",
                                         {"source": SANDBOX_VISTA_PREVIA}, escucha=escucha)).get("identifier")
            await llama("Page.navigate", {"url": url}, escucha=escucha)
            # Se espera al loadEventFired real, no un numero fijo de segundos: con el navegador
            # todavia ocupado por la captura anterior, el sondeo caia en un documento vacio
            # (nodos 0) y la prueba salia como rota si no estaba.
            fin = time.time() + max(1.0, espera_ms / 1000.0)
            while time.time() < fin and not cargado[0]:
                try:
                    escucha(json.loads(await asyncio.wait_for(ws.recv(), .25)))
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    break
            try:
                for _ in range(8):
                    escucha(json.loads(await asyncio.wait_for(ws.recv(), .08)))
            except Exception:
                pass

            # Muchas de estas paginas montan la escena DESPUES del load (el pagoda pinta antes
            # "Growing the garden..." y luego crea el canvas): se sondea hasta que haya canvas o
            # hasta agotar el presupuesto, en vez de mirar una vez y dar por roto lo que va a lo
            # suyo. Medido: sin esto el pagoda salia con 0 canvas y sin WebGL.
            Hay_canvas = "document.querySelectorAll('canvas').length > 0"
            fin_canvas = time.time() + max(1.0, espera_ms / 1000.0)
            while time.time() < fin_canvas:
                try:
                    r = await llama("Runtime.evaluate", {"expression": Hay_canvas, "returnByValue": True},
                                    escucha=escucha)
                    if (r.get("result") or {}).get("value"):
                        break
                except Exception:
                    break
                try:
                    escucha(json.loads(await asyncio.wait_for(ws.recv(), .3)))
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    break
            probe = await llama("Runtime.evaluate", {"expression": SONDA, "returnByValue": True,
                                                    "awaitPromise": True}, escucha=escucha)
            if not ((probe.get("result") or {}).get("value") or {}).get("nodos"):
                await asyncio.sleep(.9)
                probe = await llama("Runtime.evaluate", {"expression": SONDA, "returnByValue": True,
                                                          "awaitPromise": True}, escucha=escucha)
            if pintura:
                extra = await llama("Runtime.evaluate", {"expression": SONDA_PINTURA, "returnByValue": True,
                                                         "awaitPromise": True}, escucha=escucha)
                valor = (probe.get("result") or {}).get("value") or {}
                valor.update((extra.get("result") or {}).get("value") or {})
            if diagnostics:
                import components
                expression=components.resource('scene_probe.js',RAIZ/'scene_probe.js').read_text(encoding='utf-8')
                extra=await llama('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True},escucha=escucha)
                valor=(probe.get('result') or {}).get('value') or {}
                valor['scene_diagnostics']=(extra.get('result') or {}).get('value') or {'available':False,'reason':'Probe could not complete.'}
            shot = await llama("Page.captureScreenshot", {"format": "jpeg", "quality": 55}) \
                if captura else {}
            if inyectado:
                # La sesion del navegador puede seguir viva: la siguiente URL no debe heredarlo.
                await llama("Page.removeScriptToEvaluateOnNewDocument", {"identifier": inyectado}, escucha=escucha)
            return {"info": (probe.get("result") or {}).get("value") or {},
                    "consola": consola[-16:], "errores": errores[:12], "captura": shot.get("data")}

    return _con_plazo(lambda: asyncio.run(correr()), max(8, segundos))


def _con_plazo(trabajo, segundos):
    """Ejecutar el trabajo con un plazo de pared de verdad.

    `asyncio.wait_for` no cortaba: lo que tarda es el propio navegador montando la escena (medido:
    77 s con la pagoda de ~20k voxels en SwiftShader, sin GPU), y ese bloqueo no es una corutina
    nuestra. Con un hilo aparte y plazo, si se pasa se MATA la sesion - eso desbloquea el websocket
    y el hilo muere solo - y el agente recupera el control en el tiempo pedido.
    """
    caja = {}

    def correr_en_hilo():
        try:
            caja["r"] = trabajo()
        except BaseException as error:
            caja["e"] = error

    hilo = threading.Thread(target=correr_en_hilo, name="render-plazo", daemon=True)
    hilo.start()
    hilo.join(segundos)
    if hilo.is_alive():
        _SESION.cierra()
        hilo.join(6)
        return {"_error": ("la pagina no termino de montarse en %d s (SwiftShader sin GPU: la escena "
                           "es pesada). Reintenta con espera_ms mayor, comprueba otra cosa, o abrela "
                           "tú en la Vista previa.") % segundos}
    if "e" in caja:
        return {"_error": "CDP: %s" % str(caja["e"])[:180]}
    return caja.get("r") or {"_error": "sin resultado"}


def render(url, espera_ms=TIEMPO_CARGA_MS, captura=False, pintura=False, mantener=None, diagnostics=False, vista_previa=None):
    """Abrir `url` (file:// o http) y devolver la evidencia de la pagina, reusando el navegador.

    `captura` cuesta ~7 s en SwiftShader (leer todo el lenzo) y `pintura` otros 2-3 s de
    sincronizacion del WebGL, asi que vienen desactivadas: con los nodos, el contexto WebGL y la
    consola se tiene ya la evidencia que importa. Se piden solo cuando hace falta la prueba fisica.
    """
    with _CANDADO:
        if not _SESION.vivo() or (time.time() - _SESION.usado > INACTIVO_S):
            _SESION.cierra()
            if not _SESION.abre():
                return {"ok": False, "error": _SESION.fallo or "no se pudo abrir el navegador"}
        # El techo va con lo que se pidio, sin suelo de 45 s: la comprobacion automatica que se
        # hace despues de escribir usa una espera corta (los errores de arranque - import que
        # falla, SyntaxError, variable sin definir en el modulo - salen en el primer segundo, y
        # esperar 45 s a que una escena de 20k voxels se monte no es informacion, es ruido.
        # Scene checks can observe another animation frame and inspect up to
        # 40k instances. This is a deadline, not a mandatory delay on fast pages.
        overhead = 11 if diagnostics else 7
        if vista_previa is None:
            # Los archivos locales son los que el usuario abre en la vista previa aislada.
            vista_previa = url.lower().startswith("file:")
        resultado = _navega(url, espera_ms, captura, pintura, min(TECHO_S, espera_ms / 1000.0 + overhead),
                            diagnostics=diagnostics, vista_previa=vista_previa)
        _SESION.usado = time.time()
        if mantener is None:
            mantener = MANTENER
        if not mantener:
            _SESION.cierra()
    if "_error" in resultado:
        _SESION.cierra()
        return {"ok": False, "error": resultado["_error"]}
    info = resultado.get("info") or {}
    reales = [e for e in (resultado.get("errores") or []) if not any(x in e.lower() for x in RUIDO)]
    salida = {"ok": bool(info.get("nodos")) and not reales,
              "navegador": pathlib.Path(getattr(_SESION, "ruta", navegador() or "nada")).name,
              "url": url, "titulo": info.get("titulo"), "nodos": info.get("nodos"),
              "canvas": info.get("canvas"), "dimensiones_canvas": info.get("dimensiones"),
              "contexto_webgl": info.get("contexto_webgl"), "webgl": info.get("webgl"),
              "pixeles_pintados": info.get("pixeles_pintados"), "three": info.get("three"),
              "scripts": info.get("scripts"), "imagenes_rotas": info.get("imagenes_rotas"),
              "texto_visible": info.get("cuerpo"), "errores": reales,
              "consola": resultado.get("consola") or [],
              "ruido_del_navegador": len(resultado.get("errores") or []) - len(reales),
              "sesion_abierta": _SESION.vivo(), "vista_previa_aislada": bool(vista_previa)}
    if any("sandboxed" in e or "IndexedDB API is denied" in e for e in reales):
        salida["pista"] = PISTA_VISTA_PREVIA
    if diagnostics:
        salida['scene_diagnostics']=info.get('scene_diagnostics') or {'available':False,'reason':'Not observed.'}
        if any(issue.get('severity')=='error' for issue in salida['scene_diagnostics'].get('issues',[])):salida['ok']=False
    if not info.get("canvas"):
        salida["aviso"] = "la pagina no tiene canvas"
    elif not info.get("webgl"):
        salida["aviso"] = "hay canvas pero no abrio contexto WebGL"
    elif info.get("pixeles_pintados") is not None and info["pixeles_pintados"] <= 0:
        salida["aviso"] = "WebGL activo pero el lienzo no pinta ningun color: probable escena en negro"
    if info.get("imagenes_rotas"):
        salida["aviso"] = (salida.get("aviso", "") + " %d imagen(es) rotas" % info["imagenes_rotas"]).strip()
    if captura and resultado.get("captura"):
        destino = os.environ.get("STRATA_AGENT_RENDER_DIR")
        if destino:
            try:
                pathlib.Path(destino).mkdir(parents=True, exist_ok=True)
                nombre = pathlib.Path(urllib.request.url2pathname(url.split("file://")[-1])).stem[:48] or "pagina"
                archivo = pathlib.Path(destino) / (nombre + ".jpg")
                archivo.write_bytes(base64.b64decode(resultado["captura"]))
                salida["captura"] = str(archivo)
                salida["captura_bytes"] = archivo.stat().st_size
            except Exception as error:
                salida["aviso_captura"] = "no se guardo la captura: %s" % str(error)[:70]
    return salida


def sintaxis_js(codigo, module=False, mantener=False):
    """Compilar JavaScript sin ejecutarlo, en el navegador incluido (para PCs sin Node.js).

    Clasico: Runtime.compileScript. Modulo: V8 no compila modulos por CDP, asi que se compila el
    cuerpo como funcion asincrona tras quitar import/export (await de nivel superior incluido);
    eso detecta los errores de sintaxis normales, no los de las propias lineas import/export.
    Devuelve {"comprobado": bool, "error": texto o None}.
    """
    import asyncio
    import re as _re
    fuente = codigo
    if module:
        conserva = lambda m: '\n' * m.group(0).count('\n')  # mismas lineas: el numero de error cuadra
        fuente = _re.sub(r'''^[ \t]*import\s*(?:[\w$*{][\s\S]*?\bfrom\s*)?(['"])[^'"\n]*\1[ \t]*;?''', conserva, fuente, flags=_re.M)
        fuente = _re.sub(r'''^[ \t]*export\s*(?:\*[^'"\n]*|\{[^}]*\})\s*(?:from\s*(['"])[^'"\n]*\1)?[ \t]*;?''', conserva, fuente, flags=_re.M)
        fuente = _re.sub(r'^([ \t]*)export\s+default\s+', r'\1void ', fuente, flags=_re.M)
        fuente = _re.sub(r'^([ \t]*)export\s+(?=(?:async\s+)?(?:function|class|const|let|var)\b)', r'\1', fuente, flags=_re.M)
        fuente = _re.sub(r'\bimport\.meta\b', '({url:""})', fuente)
        fuente = '(async function(){\n' + fuente + '\n})'

    async def correr(puerto):
        import websockets
        destino = None
        for _ in range(60):
            try:
                destino = next((t for t in _json(puerto, "/json/list", espera=.4)
                                if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
            except (urllib.error.URLError, OSError, ValueError):
                destino = None
            if destino:
                break
            await asyncio.sleep(.1)
        if not destino:
            return {"comprobado": False, "error": "la pestana del navegador no responde"}
        async with websockets.connect(destino["webSocketDebuggerUrl"], max_size=None, close_timeout=2,
                                      open_timeout=12) as ws:
            await ws.send(json.dumps({"id": 0, "method": "Runtime.enable"}))
            await ws.send(json.dumps({"id": 1, "method": "Runtime.compileScript",
                                      "params": {"expression": fuente, "sourceURL": "code.js",
                                                 "persistScript": False}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if msg.get("id") == 1:
                    break
        if "error" in msg:
            return {"comprobado": False, "error": str(msg["error"].get("message"))[:200]}
        detalle = (msg.get("result") or {}).get("exceptionDetails")
        if not detalle:
            return {"comprobado": True, "error": None}
        texto = ((detalle.get("exception") or {}).get("description") or detalle.get("text") or "SyntaxError").split("\n")[0]
        linea = (detalle.get("lineNumber") or 0) + (0 if module else 1)
        return {"comprobado": True, "error": "line %d: %s" % (max(1, linea), texto[:300])}

    with _CANDADO:
        if not _SESION.vivo() or (time.time() - _SESION.usado > INACTIVO_S):
            _SESION.cierra()
            if not _SESION.abre():
                return {"comprobado": False, "error": _SESION.fallo or "no se pudo abrir el navegador"}
        try:
            resultado = _con_plazo(lambda: asyncio.run(correr(_SESION.puerto)), 30)
        except Exception as error:
            resultado = {"comprobado": False, "error": str(error)[:200]}
        _SESION.usado = time.time()
        if not (MANTENER or mantener):
            _SESION.cierra()
    if not isinstance(resultado, dict) or "_error" in resultado:
        return {"comprobado": False, "error": (resultado or {}).get("_error", "sin respuesta") if isinstance(resultado, dict) else "sin respuesta"}
    return resultado


def render_de_archivo(ruta, espera_ms=TIEMPO_CARGA_MS, captura=False, pintura=False, mantener=None, diagnostics=False):
    p = pathlib.Path(ruta)
    if not p.exists():
        return {"ok": False, "error": "no existe %s" % ruta}
    return render(p.resolve().as_uri(), espera_ms=espera_ms, captura=captura, pintura=pintura,
                  mantener=mantener,diagnostics=diagnostics)


def resumen(ruta, espera_ms=TIEMPO_CARGA_MS, captura=False, pintura=False, mantener=None, diagnostics=False):
    """La evidencia en tres lineas cortas, para devolversela al modelo sin inflar el contexto."""
    r = render_de_archivo(ruta, espera_ms=espera_ms, captura=captura, pintura=pintura, mantener=mantener,diagnostics=diagnostics)
    from verification_evidence import evidence
    if r.get("error"):
        return evidence({"ok": False, "error": r["error"], "resumen": "Runtime verification inconclusive: %s. This does not prove the page is broken." % r["error"]},"runtime")
    lineas = ["comprobado en %s sin cabeza (%s)" % (r["navegador"], (r.get("url") or "").split("/")[-1]),
              "  documento: %s nodos, %s canvas %s, WebGL %s%s"
              % (r.get("nodos"), r.get("canvas"), r.get("dimensiones_canvas") or "",
                 (r.get("webgl") or "sin abrir").split(" | ")[0],
                 (", three.js r%s" % r["three"]) if r.get("three") else ""),
              "  lienzo: %s" % ("pinta (muestreados %d puntos con color)" % r["pixeles_pintados"]
                                if (r.get("pixeles_pintados") or 0) > 0
                                else (r.get("aviso") if r.get("pixeles_pintados") is not None
                                      else "%s, contexto %s" % (r.get("dimensiones_canvas") or "sin canvas",
                                                                r.get("contexto_webgl"))))]
    if diagnostics:
        diag=r.get('scene_diagnostics') or {}
        if diag.get('issues'):
            # One plain line first: buried inside the JSON, small models overlooked collisions.
            lineas.append('  SCENE ISSUES: '+' | '.join(('%s (%s): %s'%(i.get('kind'),i.get('severity'),i.get('message') or ''))[:240]
                                                        for i in diag['issues'][:4]))
        if diag.get('available') or diag.get('framework'):
            lineas.append('  scene diagnostics: '+json.dumps(diag,ensure_ascii=False,separators=(',',':')))
        if diag.get('issues'):
            source=pathlib.Path(ruta).read_text(encoding='utf-8',errors='replace').splitlines()
            hints=[{'line':i,'text':line.strip()[:180]} for i,line in enumerate(source,1) if any(token in line for token in ('InstancedMesh','setMatrixAt','.count'))][:18]
            lineas.append('  source locations to inspect (not an automatic diagnosis): '+json.dumps(hints,ensure_ascii=False,separators=(',',':')))
    if r.get("errores"):
        lineas.append("  ERRORES de la pagina (%d): %s" % (len(r["errores"]), " | ".join(r["errores"][:4])))
        if r.get("pista"):
            lineas.append("  causa: " + r["pista"])
    else:
        lineas.append("  errores de consola: ninguno")
    if r.get("texto_visible"):
        lineas.append("  texto visible: %r" % r["texto_visible"][:80])
    if r.get("captura"):
        lineas.append("  captura jpeg: %s (%d KB)" % (r["captura"], max(1, r.get("captura_bytes", 0) // 1024)))
    if r.get("ruido_del_navegador"):
        lineas.append("  (%d avisos del driver WebGL, no de la pagina)" % r["ruido_del_navegador"])
    r=evidence(r,"runtime")
    lineas.append("Verification scope: "+r["verification"]["scope"])
    r["resumen"] = "\n".join(lineas)
    return r


def estado():
    """Lo que ve la interfaz: que navegador hay, si la sesion esta abierta y cuanto pesa."""
    ruta = navegador()
    pesos = 0
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
            try:
                cmd = " ".join(p.info["cmdline"] or [])
            except Exception:
                continue
            if str(PERFIL) in cmd:
                pesos += p.info["memory_info"].rss or 0
    except Exception:
        pass
    return {"navegador": pathlib.Path(ruta).name if ruta else None,
            "ruta": ruta, "sesion_abierta": _SESION.vivo(),
            "puerto": _SESION.puerto or None, "ram_mib": round(pesos / 1048576, 1),
            "inactivo_segundos": round(time.time() - _SESION.usado, 1) if _SESION.vivo() else None,
            "se_cierra_a_los": INACTIVO_S, "perfil": str(PERFIL)}


def cierra_sesion():
    with _CANDADO:
        _SESION.cierra()
    return estado()


if __name__ == "__main__":
    import sys
    objetivo = sys.argv[1] if len(sys.argv) > 1 else str(RAIZ / "sandbox" / "voxel_jp" / "index.html")
    os.environ.setdefault("STRATA_AGENT_RENDER_DIR", str(PERFIL / "renders"))
    for pasada in (1, 2, 3):
        m = time.perf_counter()
        r = resumen(objetivo)
        print("[pasada %d] %.1f s" % (pasada, time.perf_counter() - m))
        print(r.get("resumen") or json.dumps(r, ensure_ascii=False)[:400])
    print("estado:", json.dumps(estado(), ensure_ascii=False))
    print("al cerrar:", json.dumps(cierra_sesion(), ensure_ascii=False))
