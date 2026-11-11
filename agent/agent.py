"""V-Agent: harness local con streaming. La API pública usa 127.0.0.1:19380 y el motor local 19382.

Las tools vienen de los servidores MCP de data/mcp.json; cada chat habilita solo
las marcadas por el modo y la interfaz. El agente ejecuta el bucle de tool calls y
envía eventos SSE al cliente Tauri (razonamiento, herramientas y texto en vivo).
"""
import datetime
import difflib
import hashlib
import re
import http.client
import select
import socket
import json
import os
import subprocess
import sys
import threading
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse
import webbrowser
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from runtime_paths import CONFIG_ROOT,SOURCE_ROOT,DATA_ROOT,SETTINGS_ROOT,LOG_ROOT,command
ROOT = CONFIG_ROOT
sys.path.insert(0, str(SOURCE_ROOT))
sys.path.insert(0, str(SOURCE_ROOT / "agent"))
from model_import import inspect_local_model, register_local_model, pick_local_file
from serve.mcp import hub_from_config  # noqa: E402
from serve.frontend import declared_tool_name
from serve import models as registry
from ui_preferences import AppearanceStore
import vram_policy
import verify
import templates
import tool_contract
from model_preferences import STORE as MODEL_PREFERENCES
from local_store import SESSIONS, RunJournal, Conflict
import tool_budget
import draft_settings
import kv_settings
import vision_settings
from projects import PROJECTS
from tool_markup import strip_tool_markup, CallFilter, complete_json_call, complete_draft_call, recover_text_calls, OPEN, CLOSE, LT, GT
from mcp_prompt import compact_tools, check_search_arguments, validate_tool_arguments
from model_preparation import ModelPreparation
from draft_store import DraftStore, read_draft
from access_policy import AccessPolicy, AccessDenied, PC_PRIVATE_ARGS, conversation_id, workspace_signature
import hardware_stats
ACCESS = AccessPolicy()
PC_ACCESS_KEY = secrets.token_urlsafe(32)
APPEARANCE = AppearanceStore(SETTINGS_ROOT / "ui-preferences.json")
PREPARATION = ModelPreparation()
ACTIVE_CONTEXT_RUN = {}

ENGINE_PORT = 19382
STRATA = f"http://127.0.0.1:{ENGINE_PORT}"
PROFILE_PATH = ROOT / "agent" / "model-profiles.json"
MCP_CONFIG = str(DATA_ROOT/"mcp.json")
WEB_MCP = str(DATA_ROOT/"engine-mcp.json")
DEFAULT_CONFIG = str(ROOT/"strata-qwen36-apex.json")
VRAM_AUTO = os.environ.get("STRATA_AGENT_VRAM_AUTO", "1") != "0"   # ver agent/vram_policy.py

# Barrera de bucle descontrolado. Medido el 2026-11-03: tras guardar el fichero pedido, el
# modelo siguio emitiendo 56 versiones distintas del mismo HTML (108 bloques, 166.871
# caracteres) hasta llenar los 65.536 tokens de contexto. Con el tope de salida quitado por
# pedido del usuario hace falta esto, que es una barrera de comportamiento y no un limite de
# longitud: si repite el trabajo o sigue escribiendo despues de haberlo guardado, se corta.
REFLEXIONES_MAX = 3           # fallos de FORMA seguidos (el harness no ejecuto nada) antes de parar
COMPROBACIONES_MAX = 5        # fallos de CONTENIDO seguidos (la herramienta se ejecuto y devolvio
                              # un error con la prueba delante: old_text repetido, NO APLICADO por el
                              # lint, consola rota). Aqui el modelo SI que avanza: cada ronda descarta
                              # una hipotesis, y cortarlo a la 3 era dejar a medias lo que se ve en
                              # SWE-agent (sus "requeries" tambien son sobre el fichero ya tocado).
PARECIDO_MIN = 0.95           # similitud a partir de la cual dos contenidos son "la misma version"

# Los umbrales salen de lo que ya hacen los harness abiertos, medido en sus repos el 2026-11-03:
# aider `max_reflections = 3` por mensaje de usuario (coders/base_coder.py), SWE-agent
# `max_requeries = 3` antes de salir, Roo Code `ToolRepetitionDetector` para a las 3 llamadas
# identicas consecutivas (DEFAULT_CONSECUTIVE_MISTAKE_LIMIT = 3) y OpenHands manda un aviso en
# el tercer error igual y se queda STUCK al cuarto. Aca no hay tope de tokens por pedido, asi
# que el freno tiene que ser de comportamiento: repetición + no escribir sin guardar.


def _parecido(a, b):
    """Si dos contenidos son la misma cosa con retoques (el caso de las 56 versiones).

    SequenceMatcher sobre los primeros 20.000 caracteres: quick_ratio descarta lo claramente
    distinto sin coste, y el ratio completo solo se pide cuando el recorte ya se parece.
    """
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    if a == b:
        return True
    cortado = 20000
    x, y = a[:cortado], b[:cortado]
    m = difflib.SequenceMatcher(None, x, y, autojunk=False)
    if m.quick_ratio() < PARECIDO_MIN:
        return False
    return m.ratio() >= PARECIDO_MIN


READ_ONLY_TOOLS = {
    'pc__fs_read', 'pc__fs_list', 'pc__fs_search', 'pc__sys_info', 'pc__project_map',
    'pc__code_check', 'pc__web_render', 'pc__file_history', 'hf__hf_account',
    'duckduckgo__web_search', 'duckduckgo__web_visit', 'web__http_request',
    'autobrowser__snapshot', 'autobrowser__text', 'autobrowser__screenshot',
    'autobrowser__cookies', 'autobrowser__network', 'autobrowser__browser_console',
    'autobrowser__wait', 'pc__job_wait', 'pc__job_status', 'pc__job_list', 'admin__status', 'computer__screen_capture', 'computer__ocr_image', 'computer__window_list',
}


def tool_is_observational(name, args):
    """True when repeating the call does not change the world.

    Mutating calls clear the duplicate guard so a later read/snapshot is allowed;
    observational calls stay guarded for the whole turn. This keeps large models
    from polling the same page/job/output and re-sending prefill.
    """
    if name == 'pc__fs_manage':
        return args.get('action') == 'stat'
    if name == 'web__http_request':
        return str(args.get('method') or 'GET').upper() in ('GET', 'HEAD')
    if name == 'autobrowser__tabs':
        return args.get('action', 'list') == 'list'
    return name in READ_ONLY_TOOLS and not (name == 'pc__file_history' and args.get('revision'))


def nota_presupuesto(rnd, rounds):
    """El aviso de presupuesto que acompana al ultimo resultado de la ronda.

    Es el patron de Goose (`ops_maxturns.rs`): la nota solo sale cuando se ha gastado la mitad de
    las rondas, no en cada vuelta, para no gastar contexto ni educar al modelo cada dos mensajes.
    """
    if rnd == rounds - 2:
        return ("\n[Tool budget reached. Answer now from results; do not call tools. "
                "Round %d/%d. Do not repeat completed calls.]" % (rnd + 1, rounds))
    if rounds >= 4 and rnd * 2 >= rounds - 1:
        return ("\n[Round %d/%d. Finish remaining work; reuse existing results.]" % (rnd + 1, rounds))
    return ""


def volcar_salida(trace_id, texto, workspace):
    """Vuelca una salida larga de herramienta y devuelve su ruta relativa.

    Goose vuelca los resultados enormes a un fichero y dice donde estan; aqui igual, para que el
    modelo la lea por partes con fs_read en lugar de perder el excedente por truncado.
    """
    try:
        nombre = re.sub(r"[^A-Za-z0-9_.-]", "_", str(trace_id))
        ruta = f"outputs/{nombre}-{secrets.token_hex(5)}.txt"
        write_workspace_text(workspace.path(ruta), texto)
        return ruta
    except Exception:
        return None


def presupuesto_resultado():
    """Cuantos caracteres de una salida de herramienta se mandan al modelo.

    Era fijo en 12.000, que sobre una ventana de 16K se comia ~3.000 tokens (una quinta parte del
    contexto) en cada vuelta. Unsloth baja el tope segun la ventana del modelo
    (`_tool_result_char_budget`); aqui igual, con el `max_context` que declara el motor: ~10 % de la
    ventana, entre 2.500 y 12.000 caracteres.
    """
    global _PRESUPUESTO_CACHE
    ahora = time.time()
    if _PRESUPUESTO_CACHE and ahora - _PRESUPUESTO_CACHE[0] < 60:
        return _PRESUPUESTO_CACHE[1]
    contexto = 0
    try:
        contexto = int((engine_health() or {}).get("max_context") or 0)
    except Exception:
        contexto = 0
    limite = int(min(12000, max(2500, contexto * 0.10 * 4.1))) if contexto else 12000
    _PRESUPUESTO_CACHE = (ahora, limite)
    return limite


_PRESUPUESTO_CACHE = ()


def cuenta_de_fallos(forma, contenido, ok, executed, status,
                     techo_forma=None, techo_contenido=None):
    """(forma, contenido, motivo) despues del resultado de una herramienta.

    Distingue los dos fallos que antes valian lo mismo:
      * FORMA: el harness no llego a ejecutar nada (herramienta desconocida, argumentos que no
        pasan el esquema, la misma llamada repetida, presupuesto). Repetirlo no cambia el mundo:
        a las 3 se corta, que es el tope de aider / Roo / SWE-agent.
      * CONTENIDO: la herramienta se ejecuto y devolvio su prueba ("old_text aparece 3 veces",
        "NO APLICADO: el cambio deja errores nuevos", la consola del navegador). Aqui cada
        intento descarta una hipotesis sobre un fichero que ya existe, y cortarlo a las 3 dejaba
        a medias justo la edicion dirigida que queremos. Tope aparte y mas holgado.

    Un resultado correcto pone los dos a cero: el contador es de fallos SEGUIDOS.
    """
    techo_forma = REFLEXIONES_MAX if techo_forma is None else int(techo_forma)
    techo_contenido = COMPROBACIONES_MAX if techo_contenido is None else int(techo_contenido)
    if ok:
        return 0, 0, ""
    if status not in ("blocked", "error", "interrupted"):
        return forma, contenido, ""
    if executed:
        forma, contenido = 0, contenido + 1
        if contenido >= techo_contenido:
            return forma, contenido, ("%d herramientas seguidas se ejecutaron y devolvieron error; "
                                      "seguir probando a ciegas no lo resuelve" % contenido)
    else:
        contenido, forma = 0, forma + 1
        if forma >= techo_forma:
            return forma, contenido, ("%d llamadas seguidas rechazadas antes de ejecutarse "
                                      "(herramienta, argumentos o llamada repetida)" % forma)
    return forma, contenido, ""


def _cierre_bucle(control, previo, guardado_en_turno):
    """El aviso con el que se cierra una respuesta cortada por la barrera (los dos caminos).

    `previo` es lo unico util que se conserva del texto cortado, recortado a 900 caracteres.
    """
    if guardado_en_turno:
        cierre = ("Lo guardado en este turno sigue en %s. Revisa el último error en la lista de "
                  "herramientas o pide un cambio concreto." % guardado_en_turno)
    else:
        cierre = ("No se guardó nada: la respuesta se repetía en versiones sucesivas. "
                  "Di una ruta concreta para la herramienta, o pulsa Guardar en el bloque que sirva. "
                  "Si ya lo guardaste, comprueba con pc__web_render y edita solo lo que falle.")
    recado = "\n\n(Se corto la respuesta: " + (control.bucle or "un bucle") + ". " + cierre + ")"
    return (previo + recado) if previo else recado.strip()


PORT = int(os.environ.get("STRATA_HARNESS_PORT","19380"))
TAURI_ORIGINS = ('http://tauri.localhost','https://tauri.localhost','tauri://localhost')
def ui_origin_allowed(origin, port=None):
    target = PORT if port is None else port
    return origin in (f'http://127.0.0.1:{target}', f'http://localhost:{target}', *TAURI_ORIGINS)
HUB = None
PLANTILLA_ULTIMA = {}         # veredicto de la plantilla jinja de la ultima carga, por modelo
ULTIMO_PRESUPUESTO = {}       # informe del presupuesto de tools de la ultima tanda medida
_TOKENIZADORES_MEDIDOS = {}   # id de modelo -> carpeta del tokenizador (o None)
ENGINE_LOCK = threading.Lock()
_SERVER_PROCESS = None
SERVER_LOG = LOG_ROOT / "engine-server.log"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


class ModelStateError(RuntimeError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def http_json(url, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def strata_post(path, payload, timeout=600):
    """POST a los endpoints de control de Strata con el Origin que exigen."""
    req = urllib.request.Request(
        STRATA + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Origin": STRATA,
                 "Referer": STRATA + "/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            error_body = json.load(e)
            detail = error_body.get("error")
            message = detail.get("message") if isinstance(detail, dict) else detail
            if not message and error_body.get("status") == "busy":
                message = "El motor sigue ocupado. Detén la respuesta antes de descargar el modelo."
        except (ValueError, AttributeError):
            message = None
        raise ModelStateError(message or f"Strata devolvió un error HTTP {e.code}", e.code) from None


def installed_models():
    """List installed configs even when the Strata HTTP server is off."""
    try:
        data = http_json(STRATA + "/api/models", timeout=5)
        models = data["models"]
        online = True
    except (OSError, ValueError, KeyError):
        models = registry.discover(ROOT)
        online = False
    try:
        default = json.loads(Path(DEFAULT_CONFIG).read_text(encoding="utf-8-sig")).get("model_name")
    except (OSError, ValueError):
        default = None
    profile_data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    ignored = set(profile_data.get("ignored_models", []))
    models = [model for model in models if model["id"] not in ignored]
    for model in models:
        model["gguf_name"] = Path(model["path"]).name if model.get("path") and Path(model["path"]).suffix.lower() == ".gguf" else None
        model["agent_profiles"] = profile_data["models"].get(model["id"], {}).get("profiles", profile_data["profiles"])
        model["vision_settings"] = vision_settings.describe(model["config"])
        model["text_only"] = profile_data["models"].get(model["id"], {}).get("text_only", True)
        model["draft"] = draft_settings.describe(model["config"])
        model['kv'] = kv_settings.describe(model['config'])
        base = model['agent_profiles']['code']
        model['preferences'] = MODEL_PREFERENCES.get(model['id'], {
            'sampling':base['sampling'], 'effort':base['effort'], 'rounds':base['rounds'],
            'context':model.get('context') or 16384,'kv':model['kv']['current']})
    loaded = next((m["id"] for m in models if m.get("status") == "loaded"), None)
    return {"loaded_model": loaded, "loaded": loaded is not None, "preparation": PREPARATION.snapshot(), "manual_loading": True, "data": models, "models": models, "current": next((m["id"] for m in models if m.get("current")), None), "engine_online": online, "default_model": default,
            "profiles": profile_data["profiles"], "profile_version": profile_data["version"]}


def selected_model(name):
    models = registry.discover(ROOT)
    target = registry.resolve(models, name)
    if target is None:
        raise ValueError("Ese modelo no está instalado. Actualiza la lista y elige uno disponible.")
    if target["status"] == "unavailable":
        raise ValueError("El modelo no se puede cargar: " + (target.get("problem") or target["id"]))
    return target


def engine_health():
    try:
        health = http_json(STRATA + "/health", timeout=3)
        return health if health.get("status") == "ok" else None
    except (OSError, ValueError, AttributeError):
        return None


def ensure_engine(config):
    """Called only by an explicit control action, never by a GET."""
    if PREPARATION.snapshot().get("active"):
        PREPARATION.check_cancelled()
    if engine_health():
        return
    process = _SERVER_PROCESS
    if not port_pid() and (process is None or process.poll() is not None):
        process = start_server(config, lazy=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if PREPARATION.snapshot().get("active"):
            PREPARATION.check_cancelled()
        if engine_health():
            return
        if process is not None and process.poll() is not None:
            raise RuntimeError("Strata no pudo arrancar. Revisa agent/engine-server.log.")
        time.sleep(.5)
    raise RuntimeError("Strata no respondió al arrancar. Revisa agent/engine-server.log.")


def require_loaded_model(name):
    """A chat never loads or switches a model as a side effect."""
    if PREPARATION.snapshot().get("active"):
        raise ModelStateError("El modelo todavía se está preparando. Espera a que termine la carga.")
    health = engine_health()
    if not health or not health.get("loaded"):
        raise ModelStateError("No hay ningún modelo cargado. Selecciona uno y pulsa Cargar modelo en Motor.")
    actual = health.get("model")
    if name in (None, "", "any", "default") or name == actual:
        return actual
    target = selected_model(name)
    if target["id"] != actual:
        raise ModelStateError("El modelo seleccionado no está cargado. Descarga el modelo en memoria y carga el seleccionado.")
    return actual


def unload_agent_model():
    health = engine_health()
    if health is None and port_pid():
        raise ModelStateError("El motor no responde todavía. Espera a que termine su operación antes de descargar el modelo.", 503)
    if health and health.get("loaded"):
        result = strata_post("/api/models/unload", {}, timeout=120)
        if result.get("status") not in ("unloaded", "not loaded"):
            raise ModelStateError("El motor no confirmó la descarga del modelo.")
        health = engine_health()
        if health and health.get("loaded"):
            raise ModelStateError("El modelo sigue en memoria. Espera a que termine la operación e inténtalo de nuevo.")
    PREPARATION.clear()
    return {"status": "unloaded", "loaded": False, "loaded_model": None, "engine_online": health is not None}


def plantilla_en_carga(target):
    """Cada carga de modelo comprueba SU plantilla jinja, individualmente, y re-aplica la
    correccion de su repo si falta.

    El motor elige la plantilla en serve/server.py (model_config): `<tokenizer>/chat_template.jinja`
    y, si no existe, la general de `serve/chat_template.jinja`. Con la general, o con la version
    incrustada en el GGUF, las llamadas a herramienta salen en el dialecto equivocado: son las
    correcciones que van al perfil de Hugging Face modelo por modelo, no una plantilla universal.

    Nunca bloquea la carga: sin red se compara contra el registro local
    (agent/template-provenance.json) y se informa.
    """
    config = target.get("config") or ""
    try:
        modelo = json.loads(Path(config).read_text(encoding="utf-8-sig")).get("model_name") or target["id"]
    except (OSError, ValueError):
        modelo = target["id"]
    try:
        est = templates.resumen_para_carga(modelo, config)
        if est.get("estado") in ("sin_plantilla", "correccion_no_aplicada", "desactualizada"):
            antes = est.get("estado")
            r = templates.aplicar(modelo, config)
            print("[plantilla] %s: %s -> %s" % (modelo, antes, r.get("accion")), flush=True)
            est = templates.resumen_para_carga(modelo, config)
            est["reaplicada"] = r.get("aplicada", False)
            est["reaplicacion"] = r.get("accion")
        print("[plantilla] %s: %s" % (modelo, est.get("linea")), flush=True)
        template_path, _, _ = templates.config_plantilla(config)
        est['tools'] = tool_contract.check_template(template_path)
        print('[tools] %s: %s' % (modelo, 'protocol OK' if est['tools']['ok'] else est['tools'].get('error')), flush=True)
        PLANTILLA_ULTIMA[modelo] = est
        return est
    except Exception as error:
        linea = "plantilla: no se pudo comprobar (%s)" % str(error)[:90]
        est = {"modelo": modelo, "estado": "error", "linea": linea, "detalle": str(error)[:200]}
        print("[plantilla] " + linea, flush=True)
        return est


def load_agent_model(name, context=None):
    target = selected_model(name)
    health = engine_health()
    if health and health.get("loaded"):
        if health.get("model") != target["id"]:
            raise ModelStateError("Descarga primero el modelo que está en memoria con Descargar modelo.")
        if context is not None and engine_context() != context:
            raise ModelStateError("El modelo está en memoria. Usa Aplicar y recargar para cambiar su contexto.")
        # Ya esta en memoria: la plantilla se leyo al hacer el switch, asi que si falta la
        # correccion se aplica al disco y se avisa de que hay que recargar para que cuente.
        est = plantilla_en_carga(target)
        aviso = ("Descarga y vuelve a cargar el modelo para que use la plantilla re-aplicada."
                 if est.get("reaplicada") else None)
        return {"status": "loaded", "model": {**target, "status": "loaded", "current": True},
                "loaded_model": target["id"], "loaded": True, "engine_online": True,
                "preparation": PREPARATION.snapshot(), "template": est,
                **({"warning": aviso} if aviso else {})}
    if health and not health.get("loaded") and current_model()[0] == target["id"]:
        # A manual reload must reread optional encoder, KV and template settings.
        # Windows can hide the listener PID, so mtime-vs-PID is not reliable.
        stop_engine()
    PREPARATION.begin(target["id"])
    done = threading.Event()
    # The load POST may be blocked inside native initialization. Closing only
    # this verified Strata process tree releases that request, GPU and RAM.
    def watch_cancel():
        while not done.wait(.1):
            if PREPARATION.cancelled.is_set():
                try:
                    stop_engine(force=True, clear_preparation=False)
                except Exception:
                    pass  # The load worker retries and reports cleanup errors.
    watcher = threading.Thread(target=watch_cancel, daemon=True)
    watcher.start()
    context_change = None
    kv_change = None
    try:
        wanted_kv = MODEL_PREFERENCES.get(target['id'], {'sampling':{},'effort':'high'}).get('kv')
        if wanted_kv is not None:
            kv_change = kv_settings.apply(target['config'],wanted_kv)
            if kv_change and health and current_model()[0] == target['id']:
                stop_engine(clear_preparation=False)
        if context is not None and target.get("context") != context:
            _, context_change = set_context_for(target["config"], context)
            if health and current_model()[0] == target["id"]:
                # The idle server still holds the old settings for its current model.
                stop_engine(clear_preparation=False)
        PREPARATION.read_weights(target["config"])
        PREPARATION.check_cancelled()
        # La plantilla se comprueba ANTES de arrancar el motor: el servidor lee
        # <tokenizer>/chat_template.jinja al levantar el modelo, y esa lectura no se repite
        # si el proceso ya estaba en marcha con la copia mala.
        plantilla = plantilla_en_carga(target)
        PREPARATION.check_cancelled()
        ensure_engine(target["config"])
        PREPARATION.check_cancelled()
        PREPARATION.update(stage="loading", message="Inicializando el modelo en el motor…")
        result = strata_post("/api/models/load", {"model": target["id"]}, timeout=900)
        PREPARATION.check_cancelled()
        health = engine_health()
        if not health or not health.get("loaded") or health.get("model") != target["id"]:
            raise ModelStateError("El motor no confirmó la carga del modelo seleccionado.", 502)
        actual_context = engine_context() if context is not None else result.get("context")
        if context is not None and actual_context != context:
            raise ModelStateError("El motor no confirmó el límite de contexto solicitado.", 502)
        PREPARATION.settle(target["config"], port_pid())
        PREPARATION.finish()
    except Exception as error:
        done.set()
        watcher.join()
        if context_change is not None or kv_change is not None:
            try:
                if context_change is not None:vram_policy.restore_config(context_change)
                if kv_change is not None:vram_policy.restore_config(kv_change)
                if not PREPARATION.cancelled.is_set() and current_model()[0] == target["id"]:
                    # Discard the temporary settings held by the server after a failed load.
                    stop_engine(force=True, clear_preparation=False)
            except Exception as cleanup:
                message = "Falló la carga y no se pudo restaurar la configuración anterior: " + str(cleanup)
                PREPARATION.fail(message)
                raise ModelStateError(message, 502) from error
        if PREPARATION.cancelled.is_set():
            try:
                stop_engine(force=True, clear_preparation=False)
            except Exception as cleanup:
                PREPARATION.fail("No se pudo terminar de cancelar: " + str(cleanup))
                raise ModelStateError(PREPARATION.snapshot()["message"], 502) from None
            PREPARATION.finish_cancelled()
            return {"status": "cancelled", "loaded": False, "loaded_model": None,
                    "engine_online": False, "preparation": PREPARATION.snapshot()}
        # A failed native switch can restore a fallback. Manual mode stays empty.
        health = engine_health()
        if health and health.get("loaded"):
            try:
                unload_agent_model()
            except Exception as cleanup:
                PREPARATION.fail(error)
                raise ModelStateError("Falló la carga y no se pudo liberar el modelo de respaldo: " + str(cleanup), 502) from None
        PREPARATION.fail(error)
        raise
    finally:
        done.set()
        watcher.join()
    return {**result, "loaded_model": target["id"], "loaded": True, "engine_online": True,
            "context": actual_context, "preparation": PREPARATION.snapshot(), "template": plantilla}



def configure_model_draft(body):
    if not isinstance(body, dict) or not body.get("model"):
        raise ValueError("Selecciona un modelo.")
    target = selected_model(body.get("model"))
    health = engine_health()
    was_loaded = bool(health and health.get("loaded") and health.get("model") == target["id"])
    reload_model = body.get("reload") is True and was_loaded
    info, before, changed = draft_settings.save(target["config"], body.get("source", ""), body.get("tokens"))
    try:
        if reload_model:
            stop_engine()
            result = load_agent_model(target["id"])
            if isinstance(result, dict) and result.get("status") == "cancelled":
                return {"draft": info, "reloaded": False, "cancelled": True, "pending": False}
    except Exception:
        from model_import import _atomic_json
        _atomic_json(Path(target["config"]), before)
        raise
    return {"draft": info, "reloaded": reload_model, "pending": was_loaded and changed and not reload_model}


def start_engine(name=None):
    config = selected_model(name)["config"] if name else DEFAULT_CONFIG
    ensure_engine(config)
    return {"status": "running", "engine_online": True}


def is_engine_process(process):
    expected = os.path.normcase(str((SOURCE_ROOT / "serve" / "server.py").resolve()))
    try:
        return ("strata-server" in process.cmdline() and Path(process.exe()).resolve()==Path(sys.executable).resolve()) or any(os.path.normcase(os.path.abspath(arg)) == expected for arg in process.cmdline()[1:] if not arg.startswith("--"))
    except (OSError, ValueError):
        return False


def stop_engine(force=False, clear_preparation=True):
    """Stop only the verified Strata server tree, including its model and MCP children."""
    import psutil
    pid = port_pid()
    process = None
    if pid:
        process = psutil.Process(pid)
    elif _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is None:
        process = psutil.Process(_SERVER_PROCESS.pid)
    if process is None:
        # Windows can report PID 0 for a live listener. Never treat that as
        # proof that Strata stopped: recover only an unambiguous, verified
        # server tree with our exact script path and private port.
        candidates = {}
        for candidate in psutil.process_iter():
            try:
                args = candidate.cmdline()
                if not is_engine_process(candidate) or "--port" not in args:
                    continue
                if args[args.index("--port") + 1] != str(ENGINE_PORT):
                    continue
                parent = candidate.parent()
                root = parent if parent and is_engine_process(parent) else candidate
                candidates[root.pid] = root
            except (psutil.Error, OSError, ValueError, IndexError):
                continue
        if len(candidates) == 1:
            process = next(iter(candidates.values()))
        elif candidates or engine_health():
            raise RuntimeError("No se pudo identificar de forma segura el proceso de Strata. El motor sigue encendido.")
        else:
            if clear_preparation:
                PREPARATION.clear()
            return {"status": "stopped", "engine_online": False}
    if not is_engine_process(process):
        raise RuntimeError("El puerto interno 8082 pertenece a otro programa; no se ha detenido.")
    if not force and engine_health():
        # The server refuses this when an inference is active; never kill it mid-answer.
        result = strata_post("/api/models/unload", {}, timeout=120)
        if result.get("status") == "busy":
            raise RuntimeError("Hay una respuesta en curso. Espera a que termine para apagar el motor.")
    parent = process.parent()
    if parent and is_engine_process(parent):
        process = parent  # Include the virtualenv's Python launcher, when present.
    result = subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode and process.is_running():
        raise RuntimeError("No se pudo detener Strata.")
    deadline = time.monotonic() + 10
    while port_pid() and time.monotonic() < deadline:
        time.sleep(.2)
    if port_pid() or engine_health():
        raise RuntimeError("Strata sigue cerrándose. Comprueba el estado en unos segundos.")
    if clear_preparation:
        PREPARATION.clear()
    return {"status": "stopped", "engine_online": False}


def current_model():
    try:
        m = http_json(STRATA + "/api/models", timeout=10)
        for e in m.get("models", []):
            if e.get("current"):
                return e.get("id"), e.get("config")
    except Exception:
        pass
    try:
        return http_json(STRATA + "/health", timeout=5).get("model"), None
    except Exception:
        return None, None


def port_pid(port=ENGINE_PORT):
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, encoding="utf-8", errors="replace", timeout=10, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for line in out.splitlines():
            if len(line.split()) >= 5 and line.split()[1].rsplit(":", 1)[-1] == str(port) and "LISTENING" in line:
                return int(line.split()[-1])
    except Exception:
        pass
    return None


def wait_health(timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if http_json(STRATA + "/health", timeout=3).get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def set_context_for(cfg_path, tokens):
    """Aplica el contexto pedido y la politica de VRAM a UN config (el del modelo cargado).

    Antes se reescribian los 18 configs: cambiar el contexto de un modelo cambiaba el de
    todos los que no estan cargados, y sus reservas quedaban sin sentido.
    """
    kv = kv_of(cfg_path)
    try:
        a = json.load(open(str(cfg_path), encoding="utf-8")).get("args") or []
        cur = int(a[a.index("--vram-reserve-mib") + 1]) if "--vram-reserve-mib" in a else None
    except Exception:
        cur = None
    p = vram_policy.plan(tokens, kv, cur)
    return p, vram_policy.apply_to_config(str(cfg_path), p)


def kv_of(cfg_path):
    try:
        a = json.load(open(str(cfg_path), encoding="utf-8")).get("args") or []
        return a[a.index("--kv") + 1] if "--kv" in a else "fp16"
    except Exception:
        return "fp16"


def start_server(cfg, lazy=False):
    global _SERVER_PROCESS
    argv = command("strata-server", "--engine", "strata",
               "--config", str(cfg), "--host", "127.0.0.1", "--port", str(ENGINE_PORT), "--mcp-config", WEB_MCP)
    if lazy:
        argv.append("--lazy")
    env = os.environ.copy()
    env.setdefault("POLY_DATE_INJECT", "1")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with SERVER_LOG.open("a", encoding="utf-8") as log:
        _SERVER_PROCESS = subprocess.Popen(argv, cwd=str(ROOT), creationflags=flags, env=env,
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    return _SERVER_PROCESS


def wait_port_free(port=ENGINE_PORT, seconds=40):
    """Espera a que el puerto del motor se libere de verdad.

    Sin esto pasaba: `taskkill` manda, pero el proceso viejo tarda en morir; se lanzaba el
    servidor nuevo, fallaba con "port 8082 is already in use", y `wait_health` contestaba
    OK por culpa del VIEJO, que seguia con el contexto anterior. El cambio de contexto
    parecia aplicado y no lo estaba.
    """
    t0 = time.time()
    while time.time() - t0 < seconds:
        if port_pid(port) is None:
            return True
        time.sleep(0.5)
    return False


def kill_server_tree():
    """MATa al servidor y a su motor (el engine es hijo; sin /T puede quedar con la VRAM)."""
    pid = port_pid()
    if not pid:
        return False
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, encoding="utf-8", errors="replace", timeout=30, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return True


def change_context(tokens, name=None):
    """Save the selected model's context and preserve the engine's loaded state."""
    health = engine_health()
    if health is None and port_pid():
        raise ModelStateError("El motor no responde. Espera a que termine su operación.", 503)
    current, current_cfg = current_model() if health else (None, None)
    loaded = bool(health and health.get("loaded"))
    if loaded and not current:
        raise ModelStateError("No se pudo identificar el modelo en memoria.", 503)

    target = selected_model(name) if name else None
    cfg = target["config"] if target else current_cfg or DEFAULT_CONFIG
    model = target["id"] if target else current
    if model is None:
        model = json.loads(Path(cfg).read_text(encoding="utf-8-sig")).get("model_name")
    # The server caches the active config even when unloaded. Refresh only that
    # config, using a lazy startup so an empty engine stays empty.
    refresh = bool(health and model == current)
    reload_model = refresh and loaded
    plan, info = set_context_for(cfg, tokens)
    stopped = False
    try:
        if refresh:
            stop_engine()
            stopped = True
            ensure_engine(cfg)
            if reload_model:
                strata_post("/api/models/load", {"model": model}, timeout=900)
                ready = engine_health()
                if not ready or not ready.get("loaded") or ready.get("model") != model or engine_context() != tokens:
                    raise RuntimeError("El motor no confirmó el modelo y contexto solicitados.")
    except Exception as error:
        vram_policy.restore_config(info)
        if stopped:
            try:
                stop_engine(force=True)
                ensure_engine(cfg)
                if reload_model:
                    strata_post("/api/models/load", {"model": model}, timeout=900)
            except Exception as rollback:
                raise RuntimeError(f"Contexto anterior restaurado en disco. No se pudo recuperar el motor: {rollback}") from error
        raise

    now = vram_policy.current(ENGINE_PORT) if reload_model else {}
    return {"status": "ok", "context": tokens, "model": model, "plan": plan,
            "reloaded": reload_model, "engine_online": health is not None,
            "engine": {"expert_slots": now.get("expert_slots"), "reserve_mib": now.get("reserve_mib"),
                       "vram_free_mib": now.get("vram_free_mib"), "context": tokens if reload_model else None}}


def engine_context():
    """El contexto que el motor tiene de verdad, para no fiarse de un health de otra copia."""
    try:
        st = http_json(STRATA + "/v1/status", timeout=8)
        return (st.get("context") or {}).get("native") or None
    except Exception:
        return None


def set_vram_reserve(reserve_mib):
    """`POST /v1/vram` en el motor: recolma la cache de expertos sin reiniciar nada."""
    out = vram_policy.resize(ENGINE_PORT, reserve_mib)
    return {"status": "ok", "applied": out, "plan_16k_128k": [
        {"context": t, "reserve_mib": vram_policy.reserve_for(t)} for t in (16384, 32768, 65536, 98304, 131072)]}


LANGUAGE_RULE = "Reply in the language of the user's latest message, even when tool results use another language."
_LANGUAGE_HINTS = {
    "Spanish": (set("áéíóúñ¿¡"), {"el", "la", "los", "las", "que", "de", "y", "en", "por", "para", "es", "una", "un", "con", "dime", "cómo", "qué"}),
    "Portuguese": (set("ãõç"), {"não", "você", "de", "que", "e", "o", "a", "em", "para", "uma", "com", "como", "isso"}),
    "French": (set("èêàùç"), {"le", "la", "les", "et", "est", "une", "des", "pour", "avec", "dans", "que", "vous"}),
    "German": (set("äöüß"), {"der", "die", "das", "und", "ist", "nicht", "mit", "ein", "eine", "für", "wie", "bitte"}),
    "English": (set(), {"the", "and", "is", "to", "of", "what", "please", "with", "for", "this", "how", "you"}),
}


def language_rule(messages):
    """Name the language: small models follow "Reply in Spanish" far better than "the user's language".

    Falls back to the generic rule when the latest user text is too short or ambiguous to tell.
    """
    text = ""
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            text = content if isinstance(content, str) else " ".join(
                str(p.get("text", "")) for p in content or [] if isinstance(p, dict))
            break
    text = text.split("\n\n[Adjuntos]\n")[0][:2000].lower()
    words = re.findall(r"[a-záéíóúñãõçèêàùäöüß]+", text)
    if len(words) < 3:
        return LANGUAGE_RULE
    scores = {name: sum(w in vocab for w in words) + 2 * sum(ch in marks for ch in text)
              for name, (marks, vocab) in _LANGUAGE_HINTS.items()}
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < 2 or ranked[0] < ranked[1] * 1.5:
        return LANGUAGE_RULE
    return "Reply in %s, even when tool results or web pages use another language." % best


def date_line():
    now = datetime.datetime.now()
    return f"[Fecha y hora actual: {now.strftime('%Y-%m-%d %H:%M')} ({DIAS[now.weekday()]})]"


def with_date(messages):
    """La fecha va al final del ultimo mensaje de usuario, nunca delante del historial.

    Un system nuevo en messages[0] cambia todo el prefijo y el motor vuelve a leer el
    prompt entero: medido aqui, `5098/0` reutilizados y 4,7 s de lectura al cruzar el
    borde del minuto (y esa lectura no esta dentro del "generated in" del registro, por
    eso el tok/s de escritura parecia normal). Colgando la fecha del ultimo turno solo
    cambia la cola: la vuelta siguiente dentro del mismo minuto reutiliza todo.
    Con contenido que no es texto (imagenes) se omite: no hay forma de colgarlo sin
    romper la caché.
    """
    out = [dict(m) if isinstance(m, dict) else m for m in messages]
    block = date_line()
    for m in reversed(out):
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                if not c.rstrip().endswith(block):
                    m["content"] = c + "\n\n" + block
            return out
    return out


_DISK = {"t": 0.0, "read": 0, "write": 0}


def context_usage(metrics, loaded):
    """Measured prompt + output tokens; cache reuse is already part of the prompt."""
    engine = metrics.get("engine") or {}
    live = metrics.get("live") or {}
    requests = metrics.get("requests") or []
    limit = engine.get("context") or engine.get("max_context")
    limit = int(limit) if isinstance(limit, (int, float)) and limit > 0 else None
    prompt = generated = source = None
    if loaded:
        if live.get("state") in ("reading", "generating", "decoding"):
            prompt = live.get("prompt_tokens")
            generated = live.get("generated") or 0
            source = "live"
        elif requests:
            last = requests[0]
            prompt = last.get("prompt_tokens")
            generated = last.get("output_tokens")
            source = "last"
    known = all(isinstance(value, (int, float)) and value >= 0 for value in (prompt, generated))
    used = int(prompt) + int(generated) if known else None
    return {"used": used, "limit": limit,
            "percent": round(used * 100 / limit, 1) if used is not None and limit else None,
            "prompt_tokens": int(prompt) if known else None,
            "completion_tokens": int(generated) if known else None,
            "source": source if known else None}


def create_agent_hub():
    from extensions import enabled_configs, RESERVED
    # Legacy custom entries are imported disabled by extensions.configs(). Never
    # start them directly from mcp.json, especially when sandbox is selected.
    block=json.loads(Path(MCP_CONFIG).read_text(encoding='utf-8-sig'))
    servers={name:cfg for name,cfg in (block.get('mcpServers') or {}).items() if name in RESERVED}
    if ACCESS.snapshot()['mode']=='full_pc':servers.update(enabled_configs())
    else:enabled_configs()  # Import legacy entries without enabling them.
    hub = hub_from_config({'mcpServers':servers})
    if hub:
        # Keep the full returned text for inspection. The model's cap is separate.
        hub.settings["max_result_chars"] = 0
        hub.settings["max_rounds"] = 50
        for name in ('pc','hf'):
            if name in hub.servers:hub.servers[name].cfg.setdefault('env', {})['STRATA_PC_ACCESS_KEY'] = PC_ACCESS_KEY
    return hub


def stats():
    out = {"preparation": PREPARATION.snapshot()}
    try:
        m = http_json(STRATA + "/metrics", timeout=5)
    except Exception:
        m = {}
    eng = m.get("engine") or {}
    live = m.get("live") or {}
    reqs = m.get("requests") or []
    last = reqs[0] if reqs else {}
    try:
        h = http_json(STRATA + "/health", timeout=5)
        out["engine_online"] = True
        out["loaded"] = bool(h.get("loaded"))
        out["model"] = h.get("model")
    except Exception:
        out["loaded"] = False
        out["engine_online"] = False
    out["model"] = out.get("model") or eng.get("model")
    out["context"] = eng.get("context") or eng.get("max_context")
    out["context_usage"] = context_usage(m, out["loaded"])
    out["live"] = {"state": live.get("state"), "tok_s": live.get("tok_s"),
                   "mean": live.get("tok_s_mean"), "prefill": live.get("prefill_tok_s_mean"),
                   "generated": live.get("generated")}
    out["last"] = {"decode": last.get("decode_tok_s"), "prompt_ms": last.get("prompt_ms"),
                   "prompt_read": last.get("prompt_read"), "prefill": last.get("prompt_per_second"),
                   "hit": last.get("hit_rate"), "file_mb": last.get("file_mb")}
    vr = eng.get("vram") or {}
    out["expert"] = {"slots": eng.get("expert_slots"), "mib": eng.get("expert_cache_mib"),
                     "reserve_mib": vr.get("reserve_mib"), "free_mib": vr.get("vram_free_mib"),
                     "slots_full": vr.get("expert_slots_full"), "mib_full": vr.get("expert_cache_full_mib")}
    measured = hardware_stats.snapshot()
    out.update(measured)
    hardware = m.get("hardware") or {}
    if isinstance(hardware.get("gpu_mem_total"), (int, float)) and hardware["gpu_mem_total"] > 0:
        source = {"util": hardware.get("gpu_util"), "vram_mib": hardware.get("gpu_mem_used") / 2 ** 20 if isinstance(hardware.get("gpu_mem_used"), (int,float)) else None,
                  "vram_total_mib": hardware["gpu_mem_total"] / 2 ** 20, "temp": hardware.get("gpu_temp"), "power": hardware.get("gpu_power")}
        for key,value in source.items():
            if value is not None:out.setdefault("gpu",{})[key]=value
    return out


def tokenizer_del_modelo(model):
    """La carpeta del tokenizador del modelo en memoria, para medir tokens como los mide el motor.

    Es la misma que usa `serve/server.py` (`load_tokenizer(cfg["tokenizer"])`), asi que el numero
    que da este modulo es el que el motor va a pagar de verdad. None si el modelo no la tiene.
    """
    if model in _TOKENIZADORES_MEDIDOS:
        return _TOKENIZADORES_MEDIDOS[model]
    ruta = None
    try:
        cfg = json.loads(Path(selected_model(model)["config"]).read_text(encoding="utf-8-sig"))
        carpeta = Path(cfg.get("tokenizer") or "")
        if (carpeta / "vocab.json").exists():
            ruta = carpeta
    except Exception:
        ruta = None
    _TOKENIZADORES_MEDIDOS[model] = ruta
    return ruta


def tools_for(fn, tpath=None, agent_profile="balanced"):
    global ULTIMO_PRESUPUESTO
    enabled = set()
    if fn.get("search"):
        enabled.add("web_search")
    if fn.get("visit"):
        enabled.add("web_visit")
    if fn.get("files"):
        enabled.update({"fs_list", "fs_read", "fs_write", "fs_edit", "fs_copy", "fs_search", "fs_manage", "web_render", "draft_resume", "file_history", "code_check", "project_map"})
    if fn.get("browser"):
        enabled.add("browser")
    if fn.get("web"):
        enabled.update({"http_request","download"})
    if fn.get("autobrowser"):
        enabled.update({"open","navigate","snapshot","text","click","fill","press","eval","wait","screenshot","cookies","network","browser_console","browser_download","tabs","close"})
    full_access = ACCESS.snapshot()['mode'] == 'full_pc'
    if fn.get("shell"):
        enabled.add('shell_run')
        if full_access:enabled.update({"job_wait","job_status","job_list","job_stop"})
    if fn.get("console") and full_access:
        enabled.add("console")
    if fn.get("sys"):
        enabled.add("sys_info")
    if fn.get("hf"):
        enabled.update({"hf_account","hf_cli","hf_transfer"})
    if agent_profile == 'advanced' and full_access:
        if fn.get('admin'):enabled.update({'start','status','run','stop'})
        if fn.get('computer'):enabled.update({'screen_capture','ocr_image','window_list','window_focus','mouse_move','mouse_click','mouse_scroll','keyboard_type','keyboard_key'})
    from agent_profiles import external_allowed,filter_enabled
    enabled=filter_enabled(enabled,agent_profile,full_access)
    external=set()
    if external_allowed(agent_profile,full_access):
        from extensions import enabled_configs
        external=set(enabled_configs())
    if not enabled and not external:
        ULTIMO_PRESUPUESTO.clear()
        ULTIMO_PRESUPUESTO.update({"limite": tool_budget.LIMITE, "nivel": 0, "token_antes": 0,
                                   "token_despues": 0, "recortes": "", "fuera": [], "aproximado": True})
        return []
    if not HUB:
        return []
    tools = compact_tools([t for t in HUB.openai_tools() if (t["function"]["name"].split("__")[-1] in enabled and t["function"]["name"].split("__")[0] in ("pc","hf","duckduckgo","web","autobrowser","admin","computer")) or t["function"]["name"].split("__")[0] in external])
    if not full_access:
        descriptions = {'pc__fs_list': 'List sandbox files; use relative paths.',
                        'pc__fs_read': 'Read sandbox UTF-8 text; offset continues by character; linea is a 1-based line, ventana is the line count.',
                        'pc__fs_write': 'Write sandbox UTF-8 text; use relative paths.',
                        'pc__fs_edit': 'Replace exact blocks in a sandbox file: old_text/new_text or edits=[...] (all or nothing); old_text must match verbatim.',
                        'pc__fs_copy': 'Copy or move text between sandbox files by line number, without the model retyping it.',
                        'pc__web_render': 'Render sandbox HTML; report console errors and scene/camera/instance diagnostics. Not a visual quality guarantee.',
                        'pc__shell_run': 'Run CMD in the isolated workspace. No network, PowerShell or background jobs. If unavailable, the command is not run.'}
        for tool in tools:
            fn = tool['function']
            if fn['name'] in descriptions:
                fn['description'] = descriptions[fn['name']]
    from agent_profiles import tools_for_profile,distinct_tools
    tools=distinct_tools(tools_for_profile(tools,agent_profile))
    # Presupuesto duro del bloque de tools (ver agent/tool_budget.py): mientras quede lejos del
    # limite no se mueve nada ni se carga el tokenizador; si se acerca, se recorta por niveles.
    try:
        tools, ULTIMO_PRESUPUESTO = tool_budget.escalera(tools, [{"role": "user", "content": "hola"}], tpath)
        if ULTIMO_PRESUPUESTO.get("nivel"):
            print("[presupuesto] %s" % tool_budget.resumen_informe(ULTIMO_PRESUPUESTO), flush=True)
    except Exception as error:
        print("[presupuesto] omitido: %s" % str(error)[:90], flush=True)
    return tools


def web_tool_aliases(allowed, routes):
    """Recover an incorrect MCP prefix for unambiguous, enabled web reads."""
    qualified = [name.split("__", 1) for name in routes if "__" in name]
    namespaces = {server for server, _ in qualified}
    aliases = {}
    for canonical in ("duckduckgo__web_search", "duckduckgo__web_visit"):
        if canonical not in allowed or canonical not in routes:
            continue
        server, suffix = canonical.split("__", 1)
        if sum(tool == suffix for _, tool in qualified) != 1 or suffix in routes:
            continue
        for other in namespaces - {server}:
            alias = other + "__" + suffix
            if not declared_tool_name(alias, routes):
                aliases[alias] = canonical
    return aliases


def resolve_tool(name, routes, aliases):
    """Clean model tool names and resolve them against the current hub."""
    raw = name or ""
    clean = raw.strip().strip('"\'')
    for junk in ("</parameter>", "</function>", "</tool_call>", "</tool_call", "<", ">"):
        clean = clean.replace(junk, "")
    clean = clean.strip().strip('"\'')
    return declared_tool_name(clean, routes) or aliases.get(clean, clean)



def unknown_tool_text(name, allowed=None):
    routes = allowed if allowed is not None else {}
    names = ", ".join(sorted(routes)) or "(ninguna)"
    return f"error: tool unavailable: {name!r}. Enabled tools: {names}"


class GenerationControl:
    """Close only this request's upstream socket when its browser disconnects."""
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.connection = None
        self.bucle = ""      # motivo por el que la barrera corto la respuesta, si la corto

    def attach(self, connection):
        with self.lock:
            self.connection = connection
        if self.cancelled.is_set():
            self.cancel()

    def detach(self, connection):
        with self.lock:
            if self.connection is connection:
                self.connection = None

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            connection = self.connection
        sock = connection.sock if connection else None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def engine_chat_stream(payload, control):
    connection = http.client.HTTPConnection("127.0.0.1", ENGINE_PORT, timeout=1800)
    try:
        if control.cancelled.is_set():
            return
        connection.connect()
        control.attach(connection)
        if control.cancelled.is_set():
            return
        connection.request("POST", "/v1/chat/completions", json.dumps(payload).encode(),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        # The engine sends Connection: close. Keep the response's socket available
        # after HTTPConnection transfers ownership, including while prefill blocks.
        if connection.sock is None and response.fp is not None:
            connection.sock = response.fp.raw._sock
        with response:
            if control.cancelled.is_set():
                control.cancel()
                return
            if response.status != 200:
                detail = response.read().decode("utf-8", "replace")
                raise RuntimeError(f"Error del motor ({response.status}): {detail[:1000]}")
            for line in response:
                if control.cancelled.is_set():
                    return
                yield line
    finally:
        control.detach(connection)
        connection.close()


def final_tool_text(text):
    """Ver agent/tool_markup.py: admite la llamada en la misma linea y la marca sin cerrar."""
    return strip_tool_markup(text)


def _formato_esperado(plantilla=None):
    """Give the model one valid example in its own template's format."""
    if plantilla is not None and templates.formato_llamada(plantilla, native=True) == 'glm':
        return 'Use your template syntax: <tool_call>tool_name<arg_key>argument</arg_key><arg_value>value</arg_value></tool_call>'
    if plantilla is not None and templates.formato_llamada(plantilla, native=True) == 'dsml':
        return 'Use your template syntax: <｜DSML｜tool_calls><｜DSML｜invoke name="tool_name"><｜DSML｜parameter name="argument" string="true">value</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>'
    if plantilla is not None and templates.formato_llamada(plantilla, native=True) == 'lfm2':
        return "Use your template syntax: <|tool_call_start|>[tool_name(argument='value')]<|tool_call_end|>"
    if plantilla is not None and templates.formato_llamada(plantilla, native=True) == 'gemma':
        return 'Use your template\'s syntax: <|tool_call>call:tool_name{argument:<|"|>value<|"|>}<tool_call|>'
    if plantilla is not None and templates.formato_llamada(plantilla, native=True) == "xml":
        return ("Use your template's syntax: " + OPEN + "\n"
                + LT + "function=tool_name" + GT + "\n"
                + LT + "parameter=argument" + GT + "value" + LT + "/parameter" + GT + "\n"
                + LT + "/function" + GT + "\n" + CLOSE)
    return ("Emit valid JSON on its own line: " + OPEN + "\n"
            + '{"name":"tool_name","arguments":{"argument":"value"}}\n' + CLOSE)


def _responde_huerfanas(mensajes):
    """Cerrar las llamadas a herramienta que se quedaron sin respuesta en el historial.

    Si una vuelta se corto por la barrera o por cancelar, puede quedar en el historial un mensaje
    del asistente con `tool_calls` sin su `role: tool` correspondiente. La plantilla del modelo no
    sabe que hacer con eso (y el motor lo rechaza o lo renderiza raro), y el modelo tiende a
    reintentar la llamada colgada. Goose responde esas llamadas huérfanas con "This tool call was
    not handled"; aqui se contesta en castellano y con la verdad por delante: no se ejecuto.
    """
    if not any(m.get("role") == "assistant" and m.get("tool_calls") for m in mensajes):
        return mensajes
    salida = []
    for i, m in enumerate(mensajes):
        salida.append(m)
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        contestadas = set()
        for siguiente in mensajes[i + 1:]:
            if siguiente.get("role") != "tool":
                break
            contestadas.add(siguiente.get("tool_call_id"))
        for c in m["tool_calls"]:
            cid = c.get("id") or ""
            if cid in contestadas:
                continue
            nombre = ((c.get("function") or {}).get("name") or "la herramienta").split("__")[-1]
            salida.append({"role": "tool", "tool_call_id": cid, "content":
                           "no ejecutada: la respuesta anterior se corto antes de llamar a %s. "
                           "No la des por hecha; decide si hace falta ahora." % nombre})
    return salida


def run_chat_stream(body, control=None):
    workspace = PROJECTS.workspace(ACCESS,body["conversation_id"]) if body.get("conversation_id") else None
    journal = DraftStore(workspace, write_workspace_text)
    stream = _run_chat_stream(body, control)
    try:
        for event in stream:
            if isinstance(event, dict):
                journal.observe(event)
                if event.get("type") == "done":
                    def base(record):
                        return Path(str((record.get("args") or {}).get("path") or "").replace("\\", "/")).name
                    # A failed attempt later saved under the same name is not a lost draft.
                    saved = {base(r) for r in journal.records.values()
                             if r["status"] == "completed" and r.get("name") == "pc__fs_write"}
                    files = [r["file_path"] for r in journal.records.values()
                             if r.get("file_path") and r["status"] != "completed" and base(r) not in saved]
                    if files:
                        suffix = "Borrador conservado en " + ", ".join(chr(96) + path + chr(96) for path in files) + "."
                        event["content"] = event.get("content", "").rstrip() + "\n\n" + suffix
                        yield {"type": "content_fixed", "text": event["content"]}
            yield event
    finally:
        stream.close()
        journal.flush()


def _run_chat_stream(body, control=None):
    """Genera eventos: reasoning, content, tool, round, done, error."""
    control = control or GenerationControl()
    chat_id = body.get("conversation_id")
    workspace = PROJECTS.workspace(ACCESS,chat_id) if chat_id is not None else ACCESS
    ticket = {"id": chat_id, "signature": workspace_signature(PC_ACCESS_KEY, chat_id)} if chat_id is not None else None
    messages = list(body.get("messages") or [])
    messages = _responde_huerfanas(messages)
    from plugins import prompt_block
    # Una sola regla fija (no rompe la caché): sin ella, tras leer paginas o salidas en ingles
    # los modelos pequeños contestan en ingles a quien escribio en español.
    plugin_instructions = "\n\n".join(x for x in (language_rule(messages), prompt_block()) if x)
    if plugin_instructions:
        if messages and messages[0].get('role') == 'system':
            messages[0] = {**messages[0], 'content': messages[0].get('content', '') + '\n\n' + plugin_instructions}
        else:
            messages.insert(0, {'role': 'system', 'content': plugin_instructions})
    if (body.get("functions") or {}).get("date"):
        messages = with_date(messages)
    model = body.get("model") or "any"
    profiles = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    model_profiles = profiles["models"].get(model, {}).get("profiles", profiles["profiles"])
    preset = model_profiles.get(body.get("profile") or "code", model_profiles["code"])
    effort = body.get("effort") or preset["effort"]
    sampling = {**preset["sampling"], **(body.get("sampling") or {})}
    plantilla_del_modelo = tokenizer_del_modelo(model)
    from agent_profiles import normalize,PROFILES
    agent_profile=normalize(body.get("agent_profile"))
    tools = tools_for(body.get("functions") or {}, plantilla_del_modelo,agent_profile)
    if tools and plantilla_del_modelo:
        contract = tool_contract.check_template(plantilla_del_modelo / 'chat_template.jinja')
        if not contract['ok']:
            raise RuntimeError('Las herramientas de este modelo no superaron la comprobación de plantilla: ' +
                               contract.get('error', 'protocolo incompatible') + '. El chat sin MCP sigue disponible.')
    if workspace is not ACCESS and any(t['function']['name'] == 'pc__draft_resume' for t in tools):
        from draft_recovery import pending_draft, resume_draft
        pending = pending_draft(workspace)
        recovery_state = ''
        if body.get('resume_draft'):
            restored = resume_draft(workspace, body['resume_draft'])
            recovery_state = 'Recovered working file: ' + restored['path'] + '. ' + restored['note']
        elif pending:
            snapshot, (_, saved_content, complete) = pending
            recovery_state = (
                'Recovery state for this conversation: a saved file draft is available (' +
                str(len(saved_content)) + ' characters; ' + ('complete' if complete else 'interrupted prefix') +
                '). If asked to continue or recover it, call pc__draft_resume() and work on the returned file. '
                'Preserve saved code; read and edit the relevant sections. Ignore it for unrelated requests.')
        if recovery_state:
            if messages and messages[0].get('role') == 'system':
                messages[0] = {**messages[0], 'content': messages[0].get('content', '') + '\n' + recovery_state}
            else:
                messages.insert(0, {'role': 'system', 'content': recovery_state})
    if workspace is not ACCESS and (body.get('functions') or {}).get('files'):
        from context_policy import project_messages
        messages,context_projection=project_messages(messages,workspace)
    full = []

    # La reserva se ajusta para el contexto que se va a usar, no para el techo: con una
    # charla corta la cache de expertos recupera ~213 expertos y escribe mas rapido; con
    # una larga deja sitio para la KV y los grafos. STRATA_AGENT_VRAM_AUTO=0 lo apaga.
    if VRAM_AUTO:
        try:
            st = vram_policy.current(ENGINE_PORT)
            if st.get("loaded") and st.get("context"):
                move = vram_policy.tune(ENGINE_PORT, messages, int(st["context"]))
                if move.get("applied"):
                    print("[vram] reserva %s -> %s MiB, cache %s expertos"
                          % (move.get("from"), move.get("to"), move.get("expert_slots")), flush=True)
        except Exception as e:
            print("[vram] ajuste omitido: %s" % str(e)[:90], flush=True)

    # Reserve the last round for an answer; keep schemas so the engine can parse attempts.
    rounds = min(100, max(2, int(body.get("rounds") or 50)))
    allowed = {t["function"]["name"]: t["function"].get("parameters") or {} for t in tools}
    routes = HUB.routes() if HUB and tools else {}
    aliases = web_tool_aliases(allowed, routes)
    guardado_en_turno = None      # ruta guardada con exito en esta vuelta, si la hubo
    denegada = None               # herramienta que el usuario rechazo; corta el turno
    escrituras_fallidas = 0       # fs_write grandes que fallaron en este turno (1 reintento)
    llamadas_hechas = {}          # (herramienta, argumentos) ya ejecutados: la misma llamada
                                  # repetida es el bucle que se vio, y no aporta nada
    fallos_forma = 0              # fallos de FORMA seguidos (no se ejecuto nada): tope 3
    fallos_contenido = 0          # fallos de CONTENIDO seguidos (ejecuto y devolvio la prueba): tope 5
    guardados_previos = {}        # ruta -> ultimo contenido guardado: para la "otra version" igual
    wrap_up = False
    for rnd in range(rounds):
        final_round = bool(tools) and (wrap_up or rnd == rounds - 1)
        if control.cancelled.is_set():
            return
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "chat_template_kwargs": {"no_date": True, "enable_thinking": effort != "none", "preserve_thinking": True,
                                     "compact_tool_prompt": fallos_forma == 0, "strata_native_tools": True},
        }
        for k in ("temperature", "top_p", "top_k", "min_p", "repetition_penalty",
                  "presence_penalty", "frequency_penalty", "max_tokens"):
            v = sampling.get(k)
            if v is not None and v != "":
                payload[k] = v
        seed = sampling.get("seed")
        if isinstance(seed, int) and seed > 0:
            payload["seed"] = seed
        if effort != "none":
            payload["reasoning_effort"] = effort
        if tools and not wrap_up:
            payload["tools"] = tools
            payload["strata_tool_drafts"] = True
        if body.get("native_stream") is True and not tools:
            # No tool orchestration is needed. Preserve native SSE frames without
            # decoding and encoding every token through a second JSON protocol.
            frame = []
            empty_frames = 0
            for raw in engine_chat_stream(payload, control):
                frame.append(raw)
                if not raw.strip():
                    trozo = b"".join(frame)
                    if b'"reasoning_content"' not in trozo and re.search(rb'"content"\s*:\s*"(?:(?:\\[nrt])|\s)*"',trozo):empty_frames+=1
                    elif b'"content"' in trozo:empty_frames=0
                    if empty_frames>64:
                        control.bucle='repeated empty output'
                        yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                        return
                    yield trozo
                    frame.clear()
            if frame and not control.cancelled.is_set():
                yield b"".join(frame)
            return
        calls = {}
        drafts = {}

        def draft_event(key, name, delta, *, raw=False):
            if key not in drafts:
                drafts[key] = {"id": f"tool_{rnd + 1}_draft_{len(drafts) + 1}",
                               "name": "mcp__draft", "raw": raw}
            draft = drafts[key]
            if name:
                draft["name"] = resolve_tool(name, routes, aliases)
            draft["chars"] = draft.get("chars", 0) + len(delta)
            if raw:
                if "fingerprint" not in draft:
                    draft["fingerprint"] = hashlib.sha256()
                    draft["started"] = False
                piece = delta if draft["started"] else delta.lstrip()
                draft["started"] = draft["started"] or bool(piece)
                draft["fingerprint"].update(piece.encode("utf-8"))
                draft.setdefault("parts", []).append(piece)
                if draft["name"] == "mcp__draft":
                    draft["prefix"] = (draft.get("prefix", "") + piece)[:256]
                    match = re.match(r'<function=\s*"([^"\n]+)"\s*,\s*"arguments"\s*:', draft["prefix"])
                    if match:
                        candidate = resolve_tool(match[1], routes, aliases)
                        if candidate in allowed:
                            draft["name"] = candidate
            return {"type": "tool_draft", "id": draft["id"], "name": draft["name"],
                    "delta": delta, "round": rnd + 1, "status": "drafting"}

        finish_reason = None
        content_parts = []
        blank_tail = 0
        reasoning_parts = []
        f_content, f_reason = CallFilter(), CallFilter()   # para que la marca cruda no se vea ni un instante
        stream = engine_chat_stream(payload, control)
        for raw in stream:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get("error"):
                error = obj["error"]
                raise RuntimeError(error.get("message", "El motor interrumpió la respuesta.") if isinstance(error, dict) else str(error))
            draft = obj.get("strata_tool_draft")
            if isinstance(draft, dict) and draft.get("id"):
                yield draft_event(draft["id"], draft.get("name"), draft.get("delta", ""), raw=True)
            complete = obj.get("strata_tool_complete")
            if isinstance(complete, dict) and isinstance(complete.get("arguments"), dict):
                slot = next((call for call in calls.values() if call["id"] == complete.get("id")), None)
                if slot is not None and slot["name"] == complete.get("name"):
                    slot["arguments"] = json.dumps(complete["arguments"], ensure_ascii=False)
            if isinstance(obj.get("usage"), dict):
                yield {"type": "usage", "usage": obj["usage"], "round": rnd + 1}
            if isinstance(obj.get("timings"), dict):
                yield {"type": "timings", "timings": obj["timings"], "round": rnd + 1}
            ch = (obj.get("choices") or [{}])[0]
            finish_reason = ch.get("finish_reason") or finish_reason
            d = ch.get("delta") or {}
            if d.get("reasoning_content"):
                reasoning_parts.append(d["reasoning_content"])
                show = f_reason.feed(d["reasoning_content"])
                if show:
                    yield {"type": "reasoning", "text": show}
                if tools and f_reason.empty_openers >= 3:
                    finish_reason = "tool_loop"
                    break
            if d.get("content"):
                fragment=d["content"]
                blank_tail=0 if fragment.strip() else blank_tail+fragment.count("\n")
                if blank_tail>64:
                    control.bucle="repeated empty output";finish_reason="tool_loop";break
                content_parts.append(d["content"])
                show = f_content.feed(d["content"])
                if show:
                    yield {"type": "content", "text": show}
                if tools and f_content.empty_openers >= 3:
                    finish_reason = "tool_loop"
                    break
            for tc in d.get("tool_calls") or []:
                index = tc.get("index", 0)
                slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                delta = fn.get("arguments") or ""
                slot["arguments"] += delta
                key = slot.setdefault("draft_key", slot["id"] or f"index_{index}")
                prior = drafts.get(key)
                if not prior or not prior["raw"]:
                    yield draft_event(key, slot["name"], delta)
                slot["trace_id"] = drafts[key]["id"]

        stream.close()          # si la barrera corto la lectura, se suelta la peticion al motor
        if control.cancelled.is_set():
            return
        if control.bucle:
            # Se corto un desborde: la vuelta se cierra con un resumen util, no con las
            # versiones sin usar que venia acumulando.
            texto = "".join(content_parts)
            limpio, _ = final_tool_text(texto)
            previo = (limpio[:900].rstrip() + " ...") if len(limpio) > 900 else limpio
            full.append(_cierre_bucle(control, previo, guardado_en_turno))
            final = "".join(full)
            yield {"type": "content_fixed", "text": final}
            yield {"type": "done", "content": final, "reasoning_content": "".join(reasoning_parts)}
            return
        tail_reason, tail_content = f_reason.flush(), f_content.flush()   # lo retenido por si la marca venia partida
        if tail_reason:
            yield {"type": "reasoning", "text": tail_reason}
        if tail_content:
            yield {"type": "content", "text": tail_content}
        ordered = [calls[k] for k in sorted(calls)]
        large_write_drafts = {d["id"] for d in drafts.values()
                              if d["name"] == "pc__fs_write" and d["chars"] >= 512}
        for call in ordered:
            call["name"] = resolve_tool(call["name"], routes, aliases)
            try:
                parsed_args = json.loads(call["arguments"] or "{}")
            except ValueError:
                parsed_args = None
            if parsed_args == {} and not final_round and finish_reason in ("stop", "tool_calls"):
                draft = drafts.get(call["draft_key"], {})
                if draft.get("parts") and draft["name"] == call["name"] and call["name"] in allowed:
                    # The native parser reports {} for a flat envelope. Only
                    # recover fields from the raw draft with this same call ID.
                    flat = complete_json_call("".join(draft["parts"]), allowed, aliases, flat_only=True)
                    if flat and flat[0] == call["name"]:
                        parsed_args = flat[1]
            call["args_valid"] = isinstance(parsed_args, dict)
            call["parsed_args"] = {k: v for k, v in parsed_args.items() if k not in PC_PRIVATE_ARGS} if call["args_valid"] else {}
        raw_content = "".join(content_parts)
        raw_reasoning = "".join(reasoning_parts)
        eof_drafts = None
        if finish_reason == "stop" and not final_round and not ordered:
            eof_drafts = {d["fingerprint"].digest(): d["name"] for d in drafts.values()
                          if d.get("fingerprint") is not None and d["name"] in allowed}
        recovered, content, attempted = recover_text_calls(raw_content, allowed, eof_drafts=eof_drafts, aliases=aliases)
        thought_calls, reasoning, thought_attempted = recover_text_calls(raw_reasoning, allowed, terminal=True, aliases=aliases)
        cut_call = finish_reason in ("length", "content_filter", "tool_loop") and bool(ordered or attempted or thought_attempted)
        if reasoning != raw_reasoning:
            yield {"type": "reasoning_fixed", "text": reasoning}
        if final_round:
            for draft in drafts.values():
                yield {"type": "tool_result", "id": draft["id"], "name": draft["name"], "ok": False,
                       "executed": False, "status": "blocked", "result": "Se alcanzó el límite de rondas."}
            if ordered or drafts or attempted or thought_attempted or not content.strip():
                suffix = ("El modelo no pudo completar otra llamada. Las acciones pendientes quedaron sin ejecutar."
                          if wrap_up else "Se alcanzó el límite de rondas de herramientas. Las llamadas pendientes quedaron sin ejecutar.")
                content = content.rstrip() + ("\n\n" if content.strip() or any(full) else "") + suffix
            final = "".join(full) + content
            if content != raw_content:
                yield {"type": "content_fixed", "text": final}
            yield {"type": "done", "content": final}
            return

        full.append(content)
        if content != raw_content:
            yield {"type": "content_fixed", "text": "".join(full)}
        if cut_call:
            ordered = []
        elif not ordered and allowed:
            ordered = recovered or (thought_calls if not content.strip() else [])
            if not ordered and finish_reason in ("stop", "tool_calls"):
                for draft in drafts.values():
                    decoded = complete_draft_call("".join(draft.get("parts", [])), allowed, aliases)
                    if decoded:
                        name, args = decoded
                        args = {k: v for k, v in args.items() if k not in PC_PRIVATE_ARGS}
                        ordered.append({"id": "", "name": name, "arguments": json.dumps(args, ensure_ascii=False),
                                        "args_valid": True, "parsed_args": args, "trace_id": draft["id"]})
        # A recovered textual call can correspond to the unfinished native
        # draft of the same tool. Preserve its card while transitioning to execution.
        used = {c["trace_id"] for c in ordered if c.get("trace_id")}
        for call in ordered:
            if call.get("trace_id"):
                continue
            candidate = next((draft for draft in drafts.values()
                              if draft["id"] not in used and draft["name"] == call["name"]), None)
            if candidate:
                call["trace_id"] = candidate["id"]
                used.add(candidate["id"])
        rejected = [draft for draft in drafts.values() if draft["id"] not in used]
        draft_error = ("Se alcanzó el límite de generación antes de completar la llamada."
                       if finish_reason == "length" else
                       "El borrador no contiene una llamada completa con el formato esperado.")
        for draft in rejected:
            yield {"type": "tool_result", "id": draft["id"], "name": draft["name"],
                   "result": draft_error + " La herramienta no se ejecutó.",
                   "ok": False, "executed": False, "status": "error"}
        if not ordered:
            if any(d["id"] in large_write_drafts for d in rejected):
                final = "".join(full).rstrip()
                final += ("\n\n" if final else "") + "El archivo quedó como borrador. Ábrelo en la llamada Guardar archivo para copiarlo o descargarlo."
                yield {"type": "content_fixed", "text": final}
                yield {"type": "done", "content": final, "reasoning_content": reasoning}
                return
            if tools and (attempted or thought_attempted or cut_call or rejected or finish_reason == "tool_calls"):
                fallos_forma += 1
                fallos_contenido = 0
                if finish_reason == "tool_loop":
                    detail = "El modelo repitió el inicio de la llamada sin escribir argumentos."
                elif cut_call:
                    detail = "La llamada quedó interrumpida por el límite de generación."
                else:
                    detail = "El modelo emitió una llamada con formato o argumentos inválidos."
                retry = fallos_forma < REFLEXIONES_MAX and rnd < rounds - 2
                if not rejected:
                    trace_id = f"tool_{rnd + 1}_invalid"
                    yield {"type": "tool", "id": trace_id, "name": "mcp__invalid_call", "args": {},
                           "round": rnd + 1, "status": "running"}
                    yield {"type": "tool_result", "id": trace_id, "name": "mcp__invalid_call",
                           "result": detail + " La llamada no se ejecutó.", "ok": False, "executed": False,
                           "status": "error", "elapsed_ms": 0}
                if rnd < rounds - 1:
                    # Tool feedback carries recovery instructions without
                    # inventing a user message or executing the malformed call.
                    if retry:
                        instruction = ("Call not executed. Retry only if needed, with complete arguments. "
                                       "In JSON strings, escape quotes, backslashes and newlines. "
                                       + _formato_esperado(plantilla_del_modelo))
                    else:
                        wrap_up = True
                        instruction = ("Call not executed. Answer without further tool calls. "
                                       "Provide requested text or code in chat. State which actions remain undone.")
                    messages.append({"role": "assistant", "content": content, "reasoning_content": reasoning})
                    messages.append({"role": "tool", "content": instruction})
                    if content.strip():
                        full.append("\n\n")
                        yield {"type": "content", "text": "\n\n"}
                    continue
                suffix = detail + " La llamada no se ejecutó."
                final = "".join(full).rstrip()
                final = (final + "\n\n" if final else "") + suffix
                yield {"type": "content_fixed", "text": final}
                yield {"type": "done", "content": final, "reasoning_content": reasoning}
                return
            yield {"type": "done", "content": "".join(full), "reasoning_content": reasoning}
            return

        for call in ordered:
            call["parsed_args"] = {key: value for key, value in call["parsed_args"].items() if key not in PC_PRIVATE_ARGS}
        messages.append({
            "role": "assistant",
            "content": content,
            "reasoning_content": reasoning,
            "tool_calls": [{"id": c["id"] or f"call_{i}", "type": "function",
                            "function": {"name": c["name"], "arguments": json.dumps(c["parsed_args"], ensure_ascii=False)}}
                           for i, c in enumerate(ordered)]})
        failed_file = False
        for i, c in enumerate(ordered):
            if control.cancelled.is_set():
                return
            args = c["parsed_args"]
            name = c["name"]
            trace_id = c.get("trace_id") or f"tool_{rnd + 1}_{i + 1}"
            yield {"type": "tool", "id": trace_id, "call_id": c["id"] or f"call_{i}",
                   "name": name, "args": args, "round": rnd + 1, "status": "validating"}
            started = time.monotonic()
            ok = executed = False
            source_truncated = False
            source_chars = None
            status = "error"
            firma = (name, hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode("utf-8")).digest())
            try:
                if denegada:
                    # Tras un "no" del usuario no se pide ni ejecuta nada mas en este turno.
                    text = "error: NOT EXECUTED: the user denied an earlier tool call in this turn."
                    status = "blocked"
                elif name not in allowed:
                    text = "error: tool is not enabled for this conversation. Do not retry it unless the user enables it."
                    status = "blocked"
                elif not c["args_valid"]:
                    text = "error: los argumentos de la herramienta deben ser un objeto JSON válido."
                elif firma in llamadas_hechas:
                    # La misma llamada exacta, otra vez: es el bucle observado (versiones del
                    # mismo fichero) y cada vuelta cuesta prefill y contexto.
                    text = ("error: esa llamada exacta ya se ejecuto en esta conversacion y devolvio: %s. "
                            "No la repitas igual: usa el resultado anterior, cambia los argumentos o termina."
                            % str(llamadas_hechas[firma])[:160])
                    status, ok = "blocked", False
                elif name == "pc__fs_write" and args.get("path") in guardados_previos and \
                        _parecido(args.get("content"), guardados_previos[args["path"]]):
                    # No es la llamada exacta, pero el contenido es la misma version con retoques:
                    # SWE-agent directamente no deja crear sobre un fichero que ya existe.
                    text = ("error: content is almost identical to the version saved at %s "
                            "(similarity >= %d%%). Do not rewrite the whole file; edit only the affected block "
                            "using pc__fs_edit (exact, unique old_text), then validate with the appropriate checker. "
                            "For HTML use pc__web_render to inspect console errors."
                            % (args["path"], int(PARECIDO_MIN * 100)))
                    status, ok = "blocked", False
                elif HUB and name in HUB.routes():
                    validate_tool_arguments(allowed[name], args, strict=name.startswith(("pc__","hf__","duckduckgo__")))
                    check_search_arguments(name, args)
                    from output_paths import prepare_output_paths
                    call_args = prepare_output_paths(name,args,workspace,ACCESS.snapshot()['mode']=='full_pc')
                    if name.startswith(('pc__','hf__')):
                        full_access = ACCESS.snapshot()['mode'] == 'full_pc'
                        if name.startswith('pc__'):workspace.check_tool(name.split('__', 1)[1], call_args, full_access)
                        if ticket is not None:
                            call_args['_pc_workspace'] = ticket
                        if full_access:
                            call_args['_pc_access_key'] = PC_ACCESS_KEY
                    yield {"type": "tool_state", "id": trace_id, "name": name, "status": "running"}
                    if control.cancelled.is_set():
                        return
                    from tool_approvals import APPROVALS,needs_approval
                    mode=body.get('permission_mode','ask')
                    if mode not in ('ask','auto','run','full'):mode='ask'
                    full_pc = ACCESS.snapshot()['mode'] == 'full_pc'
                    # The light profile insists on a prompt per command, so it never keeps grants.
                    remember_in = chat_id if agent_profile != "light" else None
                    if needs_approval(mode,name,args,agent_profile,full_pc) and not APPROVALS.granted(remember_in,name):
                        approval=APPROVALS.create(name,args,remember_in)
                        yield approval
                        if not APPROVALS.wait(approval['id'],control.cancelled):
                            if not control.cancelled.is_set():denegada = name
                            raise AccessDenied('User denied or cancelled this tool call. Do not retry it without new authorization.')
                    executed = True
                    res = HUB.call(name, call_args, cancel=control.cancelled)
                    if isinstance(res, dict):
                        text = str(res.get("text") or "")
                        ok = res.get("ok") is not False
                        source_truncated = bool(res.get("truncated"))
                        source_chars = res.get("chars")
                    else:
                        text, ok = str(res), True
                    if not ok and not text.lower().startswith("error:"):
                        text = "error: " + (text or "La herramienta devolvió un error.")
                    status = "completed" if ok else "error"
                else:
                    text = unknown_tool_text(c["name"], allowed)
            except Exception as error:
                if control.cancelled.is_set():
                    text, status = "error: " + str(error), "interrupted"
                elif isinstance(error, AccessDenied):
                    # Visto el 2026-11-03: bloqueado el fs_write de una ruta absoluta y el
                    # modelo escribio despues "escrito: ... (21.723 caracteres)" como si
                    # hubiera funcionado. El mensaje no dejaba claro que no paso nada.
                    text = "error: NOT EXECUTED: " + str(error) + " Respect the denied operation; do not retry it without new authorization."
                    status = "blocked"
                else:
                    text, status = "error: " + str(error), "error"
            limite = min(presupuesto_resultado(),PROFILES[agent_profile]['result_chars'])
            limit_note = nota_presupuesto(rnd, rounds) if i == len(ordered) - 1 else ""
            if len(text) > limite - len(limit_note):
                # Como hace Goose (`large_response_handler`): la salida larga no se tira, se vuelca
                # a un fichero de la carpeta de trabajo y se le dice la ruta. El modelo puede leerla
                # por partes con fs_read en vez de quedarse con la cabecera truncada.
                destino = volcar_salida(trace_id, text, workspace)
                if destino:
                    limit_note += ("\n[La salida completa esta en %s: leela por partes con fs_read "
                                   "(offset) en vez de pedirla otra vez.]" % destino)
            result_limit = max(0, limite - len(limit_note))
            if source_truncated and "outputs/" not in limit_note and name != "pc__fs_read":
                # El propio servidor MCP recorto la salida (pc_mcp CAP / web_visit por paginas): lo que
                # falta no esta en ningun lado, asi que se le dice como se continua en vez de dejarle
                # releer el mismo trozo.
                limit_note += ("\n[El servidor recorto esta salida: continua donde se corto (fs_read con "
                               "offset, o web_visit con el mismo page_id y offset=next_offset) en lugar de "
                               "repetir la llamada igual.]")
                result_limit = max(0, limite - len(limit_note))
            model_text = text[:result_limit] + limit_note
            yield {"type": "tool_result", "id": trace_id, "name": name,
                   "result": text, "model_result": model_text, "ok": ok,
                   "executed": executed, "status": status, "denied": bool(denegada) and not executed,
                   "elapsed_ms": round((time.monotonic() - started) * 1000),
                   "chars": len(text), "model_chars": len(model_text),
                   "truncated": len(text) > result_limit,
                   "source_truncated": source_truncated, "source_chars": source_chars}
            file_content = args.get("content")
            if not ok and name == "pc__fs_write" and not denegada and (
                    trace_id in large_write_drafts or isinstance(file_content, str) and len(file_content) >= 512):
                # One correction attempt before giving up: ending at the first failure left fixable
                # mistakes (a wrong path) unrecovered. A second failure stops the turn so a long file
                # is not regenerated in a loop.
                escrituras_fallidas += 1
                if escrituras_fallidas >= 2:
                    failed_file = True
                else:
                    model_text += ("\n[Recovery: the file was NOT saved. Fix only the cause above and call "
                                   "fs_write once more with the same content.]")
            if ok and name in ("pc__fs_write", "pc__fs_edit", "pc__fs_append"):
                # A partir de aqui, seguir escribiendo ficheros es el desborde que vimos:
                # el trabajo ya esta en disco y lo que viene son versiones de recambio.
                guardado_en_turno = str((c["parsed_args"] or {}).get("path") or name)
                if name == "pc__fs_write" and (c["parsed_args"] or {}).get("path"):
                    guardados_previos[guardado_en_turno] = str(c["parsed_args"].get("content") or "")[:20000]
            if ok:
                # A successful change invalidates earlier observations. Keep the
                # current signature so an immediate duplicate write stays blocked.
                if not tool_is_observational(name, args):
                    llamadas_hechas.clear()
                llamadas_hechas[firma] = text[:200]
            fallos_forma, fallos_contenido, motivo = cuenta_de_fallos(
                fallos_forma, fallos_contenido, ok, executed, status)
            if motivo:
                control.bucle = motivo
            if control.cancelled.is_set():
                return
            messages.append({"role": "tool", "tool_call_id": c["id"] or f"call_{i}", "content": model_text})
        if denegada:
            final = "".join(full).rstrip()
            final += ("\n\n" if final else "") + ("No he ejecutado `%s` porque denegaste el permiso. "
                                                  "Dime cómo quieres continuar." % denegada.split("__")[-1])
            yield {"type": "content_fixed", "text": final}
            yield {"type": "done", "content": final, "reasoning_content": reasoning}
            return
        if failed_file:
            final = "".join(full).rstrip()
            final += ("\n\n" if final else "") + "No se pudo guardar el archivo. Puedes copiarlo o descargarlo desde la llamada Guardar archivo."
            yield {"type": "content_fixed", "text": final}
            yield {"type": "done", "content": final, "reasoning_content": reasoning}
            return
        if control.bucle:
            # La vuelta se para con el aviso, no con otra ronda de prefill sobre lo mismo.
            final = "".join(full) + _cierre_bucle(control, "", guardado_en_turno)
            yield {"type": "content_fixed", "text": final}
            yield {"type": "done", "content": final, "reasoning_content": ""}
            return
        if content.strip():
            full.append("\n\n")
            yield {"type": "content", "text": "\n\n"}

    yield {"type": "done", "content": "".join(full)}


def con_ejecucion(veredicto, ruta):
    """Meter la pagina en el navegador sin cabeza y mezclar eso con lo que dijo el estatico.

    El analizador estatico atrapa API mal escritas; esto atrapa lo que solo se ve al ejecutar
    (ReferenceError, import que falla, escena que no llega a montar). La evidencia son los errores
    de consola reales, con fichero y linea, para poder editar solo ese punto con fs_edit.
    """
    try:
        import render_check
    except ImportError as error:
        veredicto["ejecucion"] = {"ok": None, "aviso": "sin comprobacion en navegador: %s" % str(error)[:110]}
        return veredicto
    try:
        info = render_check.resumen(ruta)
    except Exception as error:
        veredicto["ejecucion"] = {"ok": None, "aviso": "el navegador fallo: %s" % str(error)[:110]}
        return veredicto
    if info.get("error"):
        veredicto["ejecucion"] = {"ok": None, "aviso": "no se pudo abrir la pagina: %s" % info["error"]}
        return veredicto
    errores = info.get("errores") or []
    veredicto["ejecucion"] = {"ok": bool(info.get("ok")), "navegador": info.get("navegador"),
                              "nodos": info.get("nodos"), "canvas": info.get("canvas"),
                              "webgl": bool(info.get("webgl")), "errores": errores,
                              "resumen": info.get("resumen")}
    if errores:
        veredicto["ok"] = False
        veredicto["errores"] = list(veredicto.get("errores") or []) + [
            "ejecutado en %s: %s" % (info.get("navegador"), e.replace("\n", " ")[:220]) for e in errores[:4]]
    elif not info.get("canvas") and str(ruta).lower().endswith((".html", ".htm")):
        veredicto.setdefault("avisos", []).append(
            "ejecutado en %s: la pagina no crea ningun canvas" % info.get("navegador"))
    return veredicto


def write_workspace_text(destination, content, *, create_only=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=destination.parent,
                                         prefix=".strata-write-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        if create_only:
            os.link(temporary, destination)
        else:
            temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def guardar_y_verificar(path, content, workspace, *, create_only=False):
    """El harness escribe el fichero y lo verifica, sin depender de que el modelo acierte.

    La ruta pasa por la misma politica de acceso que las herramientas del PC: relativa
    dentro de la carpeta de trabajo, absoluta solo con 'Toda la PC' activado. Despues de
    escribir se comprueba de verdad (sintaxis con node + reglas estaticas) y se devuelve el
    veredicto, para que la interfaz lo pueda mostrar y, si falla, reenviarselo al modelo.
    """
    destino = workspace.path(path, full_access=(ACCESS.mode == "full_pc"))
    if not create_only:
        from file_versions import VERSIONS
        VERSIONS.capture(destino,workspace.root)
    write_workspace_text(destino, content, create_only=create_only)
    if destino.suffix.lower() in (".html", ".htm", ".js", ".mjs", ".cjs", ".py", ".json"):
        veredicto = verify.verificar_archivo(str(destino))
        if destino.suffix.lower() in (".html", ".htm"):
            veredicto = con_ejecucion(veredicto, str(destino))   # y ejecutarla de verdad
    else:
        veredicto = {"ok": None, "checked": False, "errores": [], "avisos": ["No checker configured for this extension."], "info": {}}
    return {"status": "saved", "path": str(destino), "bytes": destino.stat().st_size,
            "chars": len(content), "verificacion": veredicto}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, *args):
        pass

    def end_headers(self):
        origin = self.headers.get('Origin')
        if ui_origin_allowed(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self):
        origin = self.headers.get('Origin')
        if not ui_origin_allowed(origin):
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', self.headers.get('Access-Control-Request-Headers') or 'Content-Type')
        self.send_header('Access-Control-Max-Age', '86400')
        self.end_headers()

    def _json(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def proxy_engine(self):
        """Keep the existing OpenAI-compatible API at the same public address as the Agent UI."""
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in ("host", "connection", "content-length", "origin", "referer")}
        headers.update(Origin=STRATA, Referer=STRATA + "/")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if self.command == "POST" else None
        request = urllib.request.Request(STRATA + self.path, data=body, headers=headers, method=self.command)
        try:
            try:
                response = urllib.request.urlopen(request, timeout=1800)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in ("connection", "transfer-encoding", "server", "date"):
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                stream = "text/event-stream" in response.headers.get("Content-Type", "")
                while True:
                    chunk = response.readline() if stream else response.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except urllib.error.URLError:
            self._json(503, {"error": "El motor está apagado o no responde. Enciéndelo desde Ajustes - Modelo."})
        finally:
            self.close_connection = True

    def engine_route(self):
        return self.path.startswith(("/v1/", "/slots")) or self.path in (
            "/health", "/api/health", "/metrics", "/models", "/props", "/mcp", "/api/models/current")

    def do_GET(self):
        if self.path == '/api/v1/sessions':
            SESSIONS.recover_runs()
            self._json(200, {'version':1,'sessions':SESSIONS.list()})
            return
        if self.path == '/api/vision/status':
            try:
                status=http_json(STRATA+'/v1/status',timeout=3)
                self._json(200,{'model':status.get('model'),'vision':status.get('vision',{'enabled':False})})
            except (OSError,ValueError):self._json(200,{'model':None,'vision':{'enabled':False}})
            return
        if urllib.parse.urlsplit(self.path).path == '/api/projects':
            try:
                query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                self._json(200,PROJECTS.snapshot(query.get('conversation_id',[None])[0]))
            except (ValueError,OSError) as error:self._json(400,{'error':str(error)})
            return
        if self.path == '/api/v1/capabilities':
            self._json(200, {'version':1,'storage':'local','sessions':True,'run_journal':True,'file_versions':True,
                             'diagnostics':['python','json','javascript','html','toml','xml','yaml','project_checks'],'projects':True,'optional_vision':True,'context_projection':'selective_cpu',
                             'native_turn':True,'browser_required':False})
            return
        if self.engine_route():
            self.proxy_engine()
            return
        if self.path in ("/guide.html", "/guide"):
            raw = (SOURCE_ROOT / "agent" / "guide.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path in ("/", "/index.html"):
            raw = (SOURCE_ROOT / "agent" / "index.html").read_bytes()
            appearance = json.dumps(APPEARANCE.get(), ensure_ascii=False).replace("<", chr(92) + "u003c").encode("utf-8")
            raw = raw.replace(b'<script id="savedAppearance" type="application/json">null</script>',
                              b'<script id="savedAppearance" type="application/json">' + appearance + b'</script>', 1)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        elif urllib.parse.urlsplit(self.path).path == "/api/ui/theme":
            client_id = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("client_id", [None])[0]
            self._json(200, APPEARANCE.get(client_id))
        elif urllib.parse.urlsplit(self.path).path == "/api/mcp":
            from sandbox_exec import status as isolation_status
            access = ACCESS.snapshot();isolation=isolation_status()
            info = {**(HUB.status() if HUB else {"servers": [], "tools": 0}), 'access': {**access,'isolation':isolation,'shell_available':access['mode']=='full_pc' or isolation['available']}}
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query, keep_blank_values=True)
            activas = (q.get("on", [None])[0])
            funciones = {"search": True, "visit": True, "files": True, "sys": True, "shell": True, "hf":False, "web":False, "autobrowser":False, "browser":False, "console":False, "computer":False, "admin":False}
            if activas is not None:
                elegidas = {x.strip() for x in activas.split(",") if x.strip()}
                funciones = {k: (k in elegidas) for k in funciones}
            try:
                # Cuanto cuesta el bloque de tools con lo que hay activado ahora mismo.
                herramientas = tools_for(funciones, tokenizer_del_modelo((engine_health() or {}).get("model")),q.get("agent_profile",["balanced"])[0])
                info["presupuesto"] = dict(ULTIMO_PRESUPUESTO or {})
                info["presupuesto"]["tools"] = len(herramientas)
                info["presupuesto"]["limite_por_defecto"] = tool_budget.LIMITE
                info["presupuesto"]["activadas"] = sorted(k for k, v in funciones.items() if v)
            except Exception as error:
                info["presupuesto"] = {"error": str(error)[:160]}
            self._json(200, info)
        elif self.path == "/api/access":
            from sandbox_exec import status as isolation_status
            access=ACCESS.snapshot();isolation=isolation_status()
            self._json(200, {**access,'isolation':isolation,'shell_available':access['mode']=='full_pc' or isolation['available']})
        elif self.path == "/api/models":
            try:
                self._json(200, installed_models())
            except Exception as e:
                self._json(500, {"error": str(e)})
        elif self.path == "/api/chat/status":
            self._json(200, {"busy": ENGINE_LOCK.locked()})
        elif self.path == '/api/context/usage':
            run = dict(ACTIVE_CONTEXT_RUN)
            if not run:
                self._json(200, {'run_id':None,'usage':None})
                return
            try:
                metrics=http_json(STRATA+'/metrics',timeout=2)
                usage=context_usage(metrics,True)
                self._json(200,{**run,'usage':usage} if run==ACTIVE_CONTEXT_RUN else {'run_id':None,'usage':None})
            except (OSError,ValueError):
                self._json(200,{**run,'usage':None})
        elif self.path == "/api/load/status":
            self._json(200, PREPARATION.snapshot())
        elif self.path == "/api/stats":
            self._json(200, stats())
        elif urllib.parse.urlsplit(self.path).path == "/api/template":
            # Que plantilla jinja tiene cada modelo, y si es la correccion de su repo.
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if q.get('aplicar', ['0'])[0] == '1':
                self._json(405, {'error':'Use POST /api/template to apply a template.'})
                return
            try:
                if q.get("todas", ["0"])[0] == "1":
                    self._json(200, {"modelos": templates.comprobar_todo()})
                else:
                    nombre = (q.get("model", [None])[0]) or (engine_health() or {}).get("model")
                    if not nombre:
                        self._json(400, {"error": "no hay modelo cargado y no se indicó model="})
                        return
                    target = selected_model(nombre)
                    config = target.get("config") or ""
                    try:
                        mod = json.loads(Path(config).read_text(encoding="utf-8-sig")).get("model_name") or target["id"]
                    except (OSError, ValueError):
                        mod = target["id"]
                    self._json(200, templates.resumen_para_carga(mod, config))
            except Exception as e:
                self._json(500, {"error": str(e)[:300]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global HUB
        if self.path.startswith('/api/'):
            origin = self.headers.get('Origin')
            if origin is not None and not ui_origin_allowed(origin):
                self._json(403, {'error': 'Origen no autorizado.'})
                return
            if self.headers.get_content_type() != 'application/json':
                self._json(415, {'error': 'Se requiere JSON.'})
                return
        if self.path in ('/api/projects/select','/api/projects/remove','/api/models/vision'):
            if not ui_origin_allowed(self.headers.get('Origin')):
                self._json(403,{'error':'Usa los controles de la interfaz para cambiar el proyecto o visión.'});return
            if not ENGINE_LOCK.acquire(blocking=False):
                self._json(409,{'error':'Detén la generación antes de cambiar esta configuración.'});return
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=16384:raise ValueError('Solicitud no válida.')
                body=json.loads(self.rfile.read(size))
                if self.path=='/api/projects/select':
                    self._json(200,PROJECTS.select(body['conversation_id'],body.get('project_id'),body.get('path')))
                elif self.path=='/api/projects/remove':
                    self._json(200,PROJECTS.remove(body['project_id']))
                else:
                    target=selected_model(body.get('model'))
                    self._json(200,{'vision':vision_settings.configure(target['config'],body),'pending':bool(engine_health())})
            except (ValueError,OSError,KeyError,TypeError) as error:self._json(400,{'error':str(error)})
            finally:ENGINE_LOCK.release()
            return
        if self.path == '/api/models/preferences':
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 < size <= 16384:raise ValueError('Solicitud no válida.')
                body = json.loads(self.rfile.read(size))
                target = selected_model(body.get('model'))
                settings = body.get('settings')
                if isinstance(settings,dict) and 'kv' in settings:kv_settings.validate(target['config'],settings['kv'])
                saved = MODEL_PREFERENCES.save(target['id'],body.get('settings'))
                self._json(200, {'model':target['id'],'settings':saved})
            except (ValueError, TypeError, KeyError) as error:
                self._json(400, {'error':str(error)})
            except OSError as error:
                self._json(500, {'error':'No se pudieron guardar los ajustes: '+str(error)})
            return
        if self.path == '/api/workspace/open':
            if not ui_origin_allowed(self.headers.get('Origin')):
                self._json(403, {'error':'Usa los controles de V-Agent para abrir la carpeta.'});return
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=1024:raise ValueError('Solicitud no válida.')
                body=json.loads(self.rfile.read(size));ident=conversation_id(body.get('conversation_id'))
                if not SESSIONS.get(ident):raise ValueError('Primero abre o guarda una conversación.')
                workspace=ACCESS.for_conversation(ident)
                if body.get('prepare_only') is not True:os.startfile(str(workspace.root))
                self._json(200,{'path':str(workspace.root)})
            except (ValueError, OSError, KeyError, TypeError, AccessDenied) as error:self._json(400,{'error':str(error)})
            return
        if self.path == '/api/v1/files/read':
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=16384:raise ValueError('Solicitud no válida.')
                body=json.loads(self.rfile.read(size));workspace=PROJECTS.workspace(ACCESS,body['conversation_id'])
                path=workspace.path(body['path'],ACCESS.mode=='full_pc')
                if not path.is_file():
                    # Old files may live in the conversation sandbox after a project was assigned.
                    path=ACCESS.for_conversation(body['conversation_id']).path(body['path'],ACCESS.mode=='full_pc')
                if not path.is_file():raise ValueError('El archivo ya no existe o no es un archivo de texto.')
                if path.stat().st_size>4*1024*1024:raise ValueError('El archivo supera 4 MB; ábrelo con la herramienta de archivos.')
                text=path.read_text(encoding='utf-8-sig',errors='replace')
                self._json(200,{'path':str(path),'text':text,'bytes':path.stat().st_size})
            except (ValueError,OSError,KeyError,TypeError) as error:self._json(400,{'error':str(error)})
            return
        if self.path == '/api/v1/files/history':
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=16384:raise ValueError('Solicitud no válida.')
                body=json.loads(self.rfile.read(size));workspace=PROJECTS.workspace(ACCESS,body['conversation_id'])
                path=workspace.path(body['path'],ACCESS.mode=='full_pc')
                from file_versions import VERSIONS
                result=VERSIONS.restore(path,workspace.root,body['revision']) if body.get('revision') else VERSIONS.history(path,workspace.root)
                self._json(200,{'result':result})
            except (ValueError,OSError,KeyError) as error:self._json(400,{'error':str(error)})
            return
        if self.path in ('/api/v1/sessions/save','/api/v1/sessions/import','/api/v1/sessions/delete'):
            try:
                size=int(self.headers.get('Content-Length') or 0)
                if not 0<size<=64*1024*1024:raise ValueError('Sesión demasiado grande o vacía.')
                body=json.loads(self.rfile.read(size))
                if self.path.endswith('/save'):
                    self._json(200, {'session':SESSIONS.save(body['session'],body.get('revision'))})
                elif self.path.endswith('/delete'):
                    SESSIONS.delete(body['id'],body['revision']);self._json(200,{'deleted':True})
                else:
                    errors=[]
                    from ui_preferences import atomic_json
                    atomic_json(SESSIONS.root/'imports'/(secrets.token_hex(16)+'.json'),body.get('sessions',[]))
                    for chat in body.get('sessions',[]):
                        try:SESSIONS.save(chat,importing=True)
                        except (ValueError,TypeError,KeyError) as error:errors.append(str(error))
                    self._json(200,{'sessions':SESSIONS.list(),'errors':errors})
            except Conflict as error:
                from ui_preferences import atomic_json
                atomic_json(SESSIONS.root/'conflicts'/(secrets.token_hex(16)+'.json'),body.get('session',body))
                self._json(409,{'error':str(error)+' La copia en conflicto quedó guardada en el disco local.'})
            except (ValueError,TypeError,KeyError) as error:self._json(400,{'error':str(error)})
            except OSError as error:self._json(500,{'error':str(error)})
            return
        if self.path in ('/api/draft', '/api/draft/resume'):
            try:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict) or not body.get("conversation_id"):
                    raise ValueError("Abre la conversación del borrador.")
                workspace = PROJECTS.workspace(ACCESS,body["conversation_id"])
                if self.path.endswith('/resume'):
                    from draft_recovery import resume_draft
                    self._json(200, resume_draft(workspace, body.get('draft_id')))
                else:
                    self._json(200, read_draft(workspace, body.get("draft_id")))
            except (AccessDenied, ValueError) as error:
                self._json(400, {"error": str(error)})
            except FileNotFoundError:
                self._json(404, {"error": "Este borrador no tiene copia en disco. Usa el texto conservado en la tarjeta."})
            return
        if self.path in ('/api/save', '/api/verify'):
            # Guardar y verificar los las hace el harness: el modelo escribe codigo, pero la
            # comprobacion de que arranca no puede depender de que el modelo acierte.
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._json(400, {'error': 'JSON no valido'})
                return
            if not isinstance(body, dict):
                self._json(400, {"error": "Solicitud no válida."})
                return
            ruta = str(body.get("path") or "").strip()
            if not ruta:
                self._json(400, {'error': 'falta path'})
                return
            try:
                workspace = PROJECTS.workspace(ACCESS,body.get('conversation_id'))
                if self.path == '/api/save':
                    contenido = str(body.get("content") or "")
                    if not contenido.strip():
                        self._json(400, {'error': 'falta content'})
                        return
                    self._json(200, guardar_y_verificar(ruta, contenido, workspace, create_only=body.get("create_only") is True))
                else:
                    destino = workspace.path(ruta, full_access=(ACCESS.mode == "full_pc"))
                    if not destino.is_file():
                        raise FileNotFoundError(destino)
                    veredicto = verify.verificar_archivo(str(destino))
                    if destino.suffix.lower() in (".html", ".htm"):
                        veredicto = con_ejecucion(veredicto, str(destino))
                    self._json(200, {"status": "verified", "path": str(destino),
                                     "verificacion": veredicto})
            except AccessDenied as error:
                self._json(403, {'error': str(error)})
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except FileExistsError:
                self._json(409, {'error': 'Ya existe un archivo con ese nombre. Puedes descargar el borrador.'})
            except FileNotFoundError as error:
                self._json(404, {'error': 'no existe: %s' % str(error)[:160]})
            except Exception as error:
                self._json(500, {'error': 'no se pudo completar: %s' % str(error)[:200]})
            return
        if self.path == "/api/template":
            # "Aplicar la plantilla del repo": reescribe el chat_template.jinja de ESE modelo con
            # el que publica su repo, y deja constancia en agent/template-provenance.json.
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not 0 < n <= 16384:
                    raise ValueError('Invalid request size.')
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError('Invalid request.')
            except Exception:
                self._json(400, {"error": "JSON no valido"})
                return
            if not ENGINE_LOCK.acquire(blocking=False):
                self._json(409, {'error':'Detén la respuesta o la carga antes de aplicar plantillas.'})
                return
            try:
                if (body.get("accion") or "") == "todas":
                    modelos = []
                    for cfg in sorted(ROOT.glob("strata-*.json")):
                        try:
                            mod = json.loads(cfg.read_text(encoding="utf-8-sig")).get("model_name") or cfg.stem
                            modelos.append(templates.aplicar(mod, cfg))
                        except Exception as one:
                            modelos.append({"modelo": cfg.stem, "estado": "error", "detalle": str(one)[:200]})
                    self._json(200, {"modelos": modelos})
                else:
                    nombre = body.get("model") or (engine_health() or {}).get("model")
                    if not nombre:
                        self._json(400, {"error": "falta model y no hay modelo cargado"})
                        return
                    target = selected_model(nombre)
                    self._json(200, plantilla_en_carga(target))
            except Exception as error:
                self._json(500, {"error": str(error)[:300]})
            finally:
                ENGINE_LOCK.release()
            return
        if self.path == '/api/access':
            # Only the explicit same-origin UI action grants full-PC access.
            if not ui_origin_allowed(self.headers.get('Origin')):
                self._json(403, {'error': 'Cambia el acceso desde los controles de MCPs.'})
                return
            if not ENGINE_LOCK.acquire(blocking=False):
                self._json(409, {'error': 'Detén la respuesta antes de cambiar el acceso.'})
                return
            try:
                length = int(self.headers.get('Content-Length') or 0)
                if not 0 < length <= 1024:
                    raise ValueError('Solicitud no válida.')
                body = json.loads(self.rfile.read(length))
                from sandbox_exec import status as isolation_status
                access=ACCESS.set_mode(body.get('mode'))
                from extensions import reconcile
                reconcile(HUB, access['mode']=='full_pc')
                isolation=isolation_status()
                self._json(200, {**access,'isolation':isolation,'shell_available':access['mode']=='full_pc' or isolation['available']})
            except (ValueError, TypeError, AttributeError) as error:
                self._json(400, {'error': str(error)})
            finally:
                ENGINE_LOCK.release()
            return
        if self.engine_route():
            self.proxy_engine()
            return
        if self.path == "/api/load/cancel":
            # Deliberately independent of ENGINE_LOCK: the load owns that lock.
            try:
                size = int(self.headers.get('Content-Length') or 0)
                if not 0 < size <= 1024:
                    raise ValueError('Solicitud no válida.')
                body = json.loads(self.rfile.read(size))
                request_id = body.get('request_id') if isinstance(body, dict) else None
                if not isinstance(request_id, str) or not request_id:
                    raise ValueError('Falta el identificador de la carga.')
                self._json(202, PREPARATION.request_cancel(request_id))
            except (ValueError, TypeError) as error:
                self._json(409, {'error': str(error)})
            return
        if self.path == "/api/ui/theme":
            origin = self.headers.get("Origin")
            if origin and not ui_origin_allowed(origin):
                self._json(403, {"error": "Origen no permitido."})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(415, {"error": "Se esperaba JSON."})
                return
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if not 0 < size <= 65536:raise ValueError("Solicitud no válida o demasiado grande.")
                self._json(200, APPEARANCE.save(json.loads(self.rfile.read(size))))
            except (ValueError, UnicodeError) as error:
                self._json(400, {"error": str(error)})
            except OSError:
                self._json(500, {"error": "No se pudo guardar el aspecto en el disco del agente."})
            return
        if self.path in ("/api/models/inspect", "/api/models/register", "/api/models/pick"):
            origin = self.headers.get("Origin")
            if origin and not ui_origin_allowed(origin):
                self._json(403, {"error": "Origen no permitido."})
                return
            if self.headers.get_content_type() != "application/json":
                self._json(415, {"error": "Se esperaba una solicitud JSON."})
                return
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if not 0 < size <= 65536:
                    raise ValueError("Solicitud no válida o demasiado grande.")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Solicitud no válida.")
                if self.path.endswith("/pick"):
                    result = pick_local_file(body.get("kind", "model"))
                elif self.path.endswith("/inspect"):
                    result = inspect_local_model(body.get("path"), body.get("template_path"))
                else:
                    result = register_local_model(body.get("path"), body.get("name"), body.get("template_path"))
                self._json(200, result)
            except (ValueError, OSError, UnicodeError) as error:
                self._json(400, {"error": str(error)})
            except Exception as error:
                self._json(500, {"error": "No se pudo añadir el modelo: " + str(error)})
            return
        if self.path in ("/api/models/load", "/api/models/unload"):
            self.path = "/api/load" if self.path.endswith("/load") else "/api/unload"
        if self.path in ("/api/unload", "/api/load", "/api/context", "/api/vram",
                         "/api/engine/start", "/api/engine/stop", "/api/mcp/reconnect", "/api/models/draft"):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                body = {}
            if not ENGINE_LOCK.acquire(blocking=False):
                self._json(409, {"error": "Otra operación del motor está en curso. Espera a que termine."})
                return
            try:
                if self.path == "/api/mcp/reconnect":
                    if HUB:
                        HUB.close()
                    HUB = create_agent_hub()
                    if HUB:
                        HUB.start(wait=True)
                    self._json(200, HUB.status() if HUB else {"servers": [], "tools": 0})
                elif self.path == "/api/engine/start":
                    self._json(200, start_engine((body or {}).get("model")))
                elif self.path == "/api/engine/stop":
                    self._json(200, stop_engine())
                elif self.path == "/api/unload":
                    self._json(200, unload_agent_model())
                elif self.path == "/api/load":
                    name = (body or {}).get("model")
                    if not name:
                        self._json(400, {"error": "falta model"})
                        return
                    context = (body or {}).get("context")
                    if context is not None and (type(context) is not int or not 2048 <= context <= 262144):
                        self._json(400, {"error": "contexto fuera de rango (2048-262144)"})
                        return
                    self._json(200, load_agent_model(name, context) if context is not None else load_agent_model(name))
                elif self.path == "/api/models/draft":
                    self._json(200, configure_model_draft(body))
                elif self.path == "/api/context":
                    tokens = int((body or {}).get("tokens") or 0)
                    if not 2048 <= tokens <= 262144:
                        self._json(400, {"error": "contexto fuera de rango (2048-262144)"})
                        return
                    self._json(200, change_context(tokens, (body or {}).get("model")))
                elif self.path == "/api/vram":
                    v = (body or {}).get("reserve_mib")
                    self._json(200, set_vram_reserve(None if v is None else int(v)))
                else:
                    self._json(404, {"error": "not found"})
            except ModelStateError as e:
                self._json(e.status, {"error": str(e)})
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": str(e)})
            finally:
                ENGINE_LOCK.release()
            return
        if self.path not in ("/api/chat",'/api/v1/turn'):
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0<n<=64*1024*1024:raise ValueError('Solicitud vacía o demasiado grande.')
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            self._json(400, {"error": str(e)})
            return
        try:
            if not isinstance(body, dict):
                raise ValueError("Solicitud no válida.")
            if "conversation_id" not in body:
                # API clients that do not supply a conversation get a fresh scope.
                body["conversation_id"] = "api-" + secrets.token_hex(16)
            conversation_id(body["conversation_id"])
        except ValueError as error:
            self._json(400, {"error": str(error)})
            return
        if not ENGINE_LOCK.acquire(blocking=False):
            self._json(409, {"error": "El motor está cambiando de estado. Espera a que termine."})
            return
        try:
            body["model"] = require_loaded_model(body.get("model"))
            if self.path=='/api/v1/turn':
                from conversation_codec import model_history
                profiles=json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
                profile=profiles['models'].get(body['model'],{}).get('profiles',profiles['profiles'])['code']
                preferences=MODEL_PREFERENCES.get(body['model'],{'sampling':profile['sampling'],'effort':profile['effort'],'rounds':profile['rounds']})
                body['sampling']={**preferences['sampling'],**(body.get('sampling') or {})}
                body.setdefault('effort',preferences['effort']);body.setdefault('rounds',preferences['rounds'])
                chat=SESSIONS.get(body['conversation_id']) or {'id':body['conversation_id'],'messages':[],'title':'Chat'}
                text=body.get('text')
                if not isinstance(text,str) or not text.strip():raise ValueError('Falta el mensaje.')
                chat['messages'].append({'role':'user','content':text});chat['title']=chat.get('title') or text[:48]
                chat['ts']=int(time.time()*1000)
                saved=SESSIONS.save(chat,chat.get('revision',0))
                body['messages']=model_history(saved['messages'])
        except (ModelStateError, ValueError) as error:
            ENGINE_LOCK.release()
            self._json(error.status if isinstance(error, ModelStateError) else 400, {"error": str(error)})
            return
        except Exception as error:
            ENGINE_LOCK.release()
            self._json(503, {"error": "No se pudo comprobar el modelo cargado: " + str(error)})
            return
        control = GenerationControl()
        watch_done = threading.Event()

        def watch_client():
            while not watch_done.wait(0.25) and not control.cancelled.is_set():
                try:
                    readable, _, _ = select.select([self.connection], [], [], 0)
                    if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                        control.cancel()
                        return
                except (OSError, ValueError):
                    control.cancel()
                    return

        threading.Thread(target=watch_client, daemon=True, name="agent-client-watch").start()
        stream = run_chat_stream(body, control)
        try:run_journal = RunJournal(body, SESSIONS)
        except Exception as error:
            watch_done.set();control.cancel();stream.close()
            ENGINE_LOCK.release();self._json(503,{'error':'No se pudo guardar la ejecución local: '+str(error)});return
        ACTIVE_CONTEXT_RUN.update(run_id=run_journal.id,model=body['model'],conversation_id=body['conversation_id'])
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("X-Strata-Conversation-Id", body["conversation_id"])
            self.send_header('X-Strata-Run-Id',run_journal.id)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            raw_stream = False
            for ev in stream:
                if isinstance(ev, bytes):
                    raw_stream = True
                    run_journal.append(ev)
                    self.wfile.write(ev)
                else:
                    packet=("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode()
                    run_journal.append(packet)
                    self.wfile.write(packet)
                self.wfile.flush()
            if not raw_stream:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
        except Exception as e:
            try:
                self.wfile.write(("data: " + json.dumps({"type": "error", "text": str(e)}) + "\n\n").encode())
                self.wfile.flush()
            except Exception:
                pass
        finally:
            ACTIVE_CONTEXT_RUN.clear()
            watch_done.set()
            control.cancel()
            stream.close()
            try:
                run_journal.close('closed')
                if self.path == '/api/v1/turn':
                    SESSIONS.recover_runs(run_journal.id)
            finally:ENGINE_LOCK.release()
        self.close_connection = True



def main():
    global HUB
    if '--background' in sys.argv:
        # Sign-in startup serves the UI only; the engine remains a manual action.
        os.environ['STRATA_AGENT_NO_OPEN'] = '1'
        log = open(LOG_ROOT/'agent-launch.log','a',encoding='utf-8',buffering=1)
        sys.stdout = sys.stderr = log
    for attempt in range(60):
        srv = None
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            legacy = None
            break
        except OSError:
            if srv:
                srv.server_close()
            if attempt == 59:
                raise
            time.sleep(.5)

    try:
        HUB = create_agent_hub()
        if HUB:
            HUB.start(wait=True)
    except Exception as e:
        print("MCP no disponible:", e)
    try:
        http_json(STRATA + "/v1/models", timeout=10)
        print("Strata OK en", STRATA)
    except Exception:
        print("AVISO: Strata no responde en", STRATA, "- puedes encenderlo desde Ajustes → Modelo.")
    print(f"V-Agent en http://127.0.0.1:{PORT}")
    if not os.environ.get("STRATA_AGENT_NO_OPEN"):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
