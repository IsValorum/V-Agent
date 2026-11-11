# -*- coding: utf-8 -*-
"""Plantillas Jinja de cada modelo, por modelo individual.

Cada GGUF lleva su chat_template incrustada, y en el perfil de Hugging Face del usuario hay
repos con la plantilla CORREGIDA para llamadas a herramientas (los arreglos que el cuantizado
no toca). El motor elige la plantilla asi (serve/server.py, model_config):

    tpath = config["tokenizer"];  tpl = tpath / "chat_template.jinja"
    ChatTemplate(tpl if tpl.exists() else ROOT / "serve/chat_template.jinja")

Si el fichero no esta, se usa la plantilla general de serve/, que no es la del modelo: las
llamadas a herramienta salen en el dialecto equivocado. Y si el fichero esta pero es la
version nativa (la incrustada en el GGUF) en vez de la corregida del repo, pasa lo mismo con
mas seguridad: parece que hay plantilla propia y no hay correccion.

Este modulo comprueba, y si hace falta re-aplica, la plantilla del repo ANTES de cada carga
de modelo. La red es opcional: sin conexion se compara solo contra el registro local
(agent/template-provenance.json) y la carga no se bloquea nunca por eso.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from runtime_paths import CONFIG_ROOT,SOURCE_ROOT
ROOT = CONFIG_ROOT
REGISTRO = ROOT / "agent" / "template-provenance.json"
CACHE = ROOT / "agent" / ".template-hf-cache.json"
PLANTILLA_GENERAL = SOURCE_ROOT / "serve" / "chat_template.jinja"
FICHERO = "chat_template.jinja"
LT, GT = chr(60), chr(62)      # los angulos se construyen: los literales de marca se pierden al editar
CACHE_HORA_S = 6 * 3600
USER_AGENT = "strata-agent-templates/1.0"


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_de(p):
    try:
        return sha256_bytes(Path(p).read_bytes())
    except OSError:
        return None


def config_plantilla(config_path):
    """Ruta de la plantilla que usara ese config, y la carpeta del tokenizer."""
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    tdir = Path(cfg.get("tokenizer") or "")
    return tdir / FICHERO, tdir, cfg


def leer_registro():
    try:
        datos = json.loads(REGISTRO.read_text(encoding="utf-8"))
        return datos if isinstance(datos, list) else []
    except (OSError, ValueError):
        return []


def escribir_registro(datos):
    tmp = REGISTRO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(REGISTRO)


def entrada_de(modelo, registro=None):
    """La fila del registro que corresponde a este model_name (comparacion tolerante)."""
    registro = registro if registro is not None else leer_registro()
    blanco = (modelo or "").strip().lower().replace("_", "-")
    for e in registro:
        if (e.get("model") or "").strip().lower().replace("_", "-") == blanco:
            return e
    return None


def candidato_repo(path_gguf, autor="IsValorum"):
    """El repo por el nombre del fichero, que sigue la convencion del perfil:
    'MiniCPM-V-4.7-35B-A3B.APEX-I-MiniPlus-V2.1.gguf' -> 'IsValorum/...-APEX-I-MiniPlus-V2.1-GGUF'."""
    if not path_gguf:
        return None
    nombre = Path(path_gguf).stem
    if "." not in nombre:
        return None
    nombre = re.sub(r"\.(APEX|VAL|GGUF)", r"-\1", nombre)  # quant tags in file names, not the product name
    for sufijo in ("-GGUF", "-MLX", ""):
        candidato = "%s/%s%s" % (autor, nombre, sufijo)
        if existe_repo(candidato):
            return candidato
    return None


def repo_de(modelo, config_path=None, registro=None):
    """El repo del modelo: el del registro, si no, el que anuncie el propio fichero del GGUF,
    y si no, el que se deduzca de su nombre de fichero."""
    e = entrada_de(modelo, registro)
    if e and e.get("repo"):
        return e["repo"]
    if not config_path:
        return None
    gguf = ""
    try:
        args = json.loads(Path(config_path).read_text(encoding="utf-8-sig")).get("args") or []
        for i, a in enumerate(args):
            if a in ("--model", "--native") and i + 1 < len(args):
                gguf = args[i + 1]
    except (OSError, ValueError):
        return None
    if not gguf:
        return None
    try:
        with open(gguf, "rb") as f:
            leido = f.read(400000)          # la metadata va detras de la cabecera
    except OSError:
        return None
    for tag in (b"general.source_url", b"tokenizer.ggml.pre_source_url", b"general.basename"):
        i = leido.find(tag)
        if i < 0:
            continue
        m = re.search(rb"(https?://hugging\.co/[^/\"'\s]+/[^\"'\s]+)", leido[i:i + 400])
        if m:
            url = m.group(1).decode("utf-8", "replace")
            return url.split("huggingface.co/", 1)[-1].rstrip("/.,")
    return candidato_repo(gguf)


def _cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guarda_cache(d):
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CACHE)


def existe_repo(repo):
    """Si el repo esta en HF (se cachea: es una peticion por modelo, no por carga)."""
    cache = _cache()
    clave = "repo:" + repo
    viejo = cache.get(clave)
    if viejo and time.time() - viejo.get("comprobado", 0) < 7 * 86400:
        return bool(viejo.get("existe"))
    try:
        req = urllib.request.Request("https://huggingface.co/api/models/" + repo,
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            existe = r.status == 200
    except urllib.error.HTTPError as e:
        existe = False if e.code == 404 else bool(viejo.get("existe") if viejo else False)
    except Exception:
        return bool(viejo.get("existe")) if viejo else False       # sin red: no se inventa
    cache[clave] = {"existe": existe, "comprobado": int(time.time())}
    _guarda_cache(cache)
    return existe


def plantilla_del_repo(repo, revision=None, forzar=False):
    """{'motivo': 'ok'|'sin_fichero'|'sin_red', 'sha256', 'cuerpo', 'revision'} para el
    chat_template.jinja publicado en el repo. Nunca lanza: la carga de un modelo no puede
    depender de que HF responda."""
    cache = _cache()
    clave = "%s@%s" % (repo, revision or "main")
    viejo = cache.get(clave)
    if viejo and not forzar and time.time() - viejo.get("comprobado", 0) < CACHE_HORA_S:
        return viejo
    ruta = "/".join(["https://huggingface.co", repo, "resolve", revision or "main", FICHERO])
    try:
        req = urllib.request.Request(ruta, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            cuerpo = r.read()
            commit = r.headers.get("X-Repo-Commit") or ""
    except urllib.error.HTTPError as e:
        resultado = {"motivo": "sin_fichero" if e.code == 404 else "sin_red", "sha256": None,
                     "revision": None, "http": e.code}
    except Exception:
        resultado = {"motivo": "sin_red", "sha256": None, "revision": None}
    else:
        empieza = cuerpo[:60].lstrip().lower()
        if len(cuerpo) < 200 or empieza.startswith((b"<!doctype", b"<html", b"{\"error")):
            resultado = {"motivo": "sin_fichero", "sha256": None, "revision": None}
        else:
            resultado = {"motivo": "ok", "sha256": sha256_bytes(cuerpo), "cuerpo": cuerpo,
                         "revision": commit, "bytes": len(cuerpo)}
    if resultado.get("motivo") == "ok" or resultado.get("motivo") == "sin_fichero":
        cache[clave] = {k: v for k, v in resultado.items() if k != "cuerpo"}
        cache[clave]["comprobado"] = int(time.time())
        _guarda_cache(cache)
    return resultado


def estado(modelo, config_path):
    """Que plantilla tiene este modelo, y si es la correccion de su repo."""
    activo, tdir, cfg = config_plantilla(config_path)
    e = entrada_de(modelo)
    nativa = tdir / "chat_template.native.jinja"
    sha_local = sha256_de(activo)
    sha_nativa = sha256_de(nativa)
    repo = (e or {}).get("repo") or repo_de(modelo, config_path)
    out = {"modelo": modelo, "config": str(config_path), "repo": repo,
           "archivo": str(activo), "existe": sha_local is not None,
           "sha_local": sha_local, "sha_nativa": sha_nativa, "revision": (e or {}).get("revision"),
           "json_tool_calls": (e or {}).get("json_tool_calls"),
           # Como quiere ESTE modelo sus llamadas (json o <function=..>), leido de su propia
           # plantilla. No es una opcion del harness: si mandamos el ejemplo del otro formato se
           # pierde la ronda. Verificado modelo por modelo, no supuesto.
           "formato": formato_llamada(tdir, native=True),
           "bytes": activo.stat().st_size if activo.exists() else 0,
           "estado": "", "detalle": ""}
    if sha_local is None:
        general = PLANTILLA_GENERAL.exists()
        out["estado"] = "sin_plantilla"
        out["detalle"] = ("el motor usara serve/chat_template.jinja (la plantilla general), que no es "
                          "la de este modelo: las llamadas a herramienta salen en el dialecto equivocado"
                          if general else "no hay plantilla en la carpeta del tokenizer")
        return out
    if not repo:
        out["estado"] = "sin_repo"
        out["detalle"] = "no se sabe de que repo va este modelo; no hay correccion que comprobar"
        return out
    info = plantilla_del_repo(repo, (e or {}).get("revision"))
    sha_repo = info.get("sha256")
    out["sha_repo"] = sha_repo
    if info.get("motivo") == "sin_fichero":
        out["estado"] = "sin_correccion_en_repo"
        out["detalle"] = ("%s no publica %s: la plantilla de este modelo va incrustada en el GGUF y esa "
                          "es la copia local" % (repo, FICHERO))
        return out
    if info.get("motivo") == "sin_red":
        registrado = (e or {}).get("sha256")
        if registrado and registrado == sha_local:
            out["estado"] = "aplicada"
            out["detalle"] = "sin red: coincide con el sha registrado del repo (%s)" % sha_local[:12]
        else:
            out["estado"] = "sin_comprobacion"
            out["detalle"] = "sin red y sin registro comparable: se confia en la copia local"
        return out
    if sha_repo == sha_local:
        out["estado"] = "aplicada"
        out["revision"] = info.get("revision") or out.get("revision")
        if sha_nativa and sha_local == sha_nativa:
            out["detalle"] = "la del repo coincide con la incrustada en el GGUF: no hay correccion que aplicar"
        else:
            out["detalle"] = "la plantilla corregida del repo es la que esta activa"
        return out
    if sha_nativa and sha_local == sha_nativa:
        out["estado"] = "correccion_no_aplicada"
        out["detalle"] = ("el fichero activo es la plantilla incrustada en el GGUF (%d B); el repo publica "
                          "una corregida (%s) y no se ha aplicado" % (out["bytes"], sha_repo[:12]))
        return out
    out["estado"] = "desactualizada"
    out["detalle"] = ("el fichero activo (%s) no es el del repo (%s): el repo tiene una version nueva "
                      "o la copia local se ha modificado a mano" % ((sha_local or "")[:12], sha_repo[:12]))
    return out


def aplicar(modelo, config_path, dry_run=False):
    """Baja la plantilla del repo y la deja como la activa de ese modelo (temporal + replace)."""
    est = estado(modelo, config_path)
    repo = est.get("repo")
    resultado = {**est, "accion": "", "aplicada": False}
    if est["estado"] == "aplicada":
        resultado["accion"] = "nada: ya esta la del repo"
        resultado["aplicada"] = True
        return resultado
    if est["estado"] == "sin_correccion_en_repo":
        resultado["accion"] = "nada: el repo no publica plantilla corregida"
        resultado["aplicada"] = True
        return resultado
    if not repo:
        resultado["accion"] = "no hay repo que consultar"
        return resultado
    info = plantilla_del_repo(repo, None, forzar=True)
    cuerpo, sha, commit = info.get("cuerpo"), info.get("sha256"), info.get("revision")
    if not cuerpo:
        resultado["accion"] = ("no se pudo bajar %s de %s (%s); se deja la copia local"
                               % (FICHERO, repo, info.get("motivo")))
        return resultado
    resultado["sha_repo"] = sha
    if sha != sha256_de(Path(resultado["archivo"])):
        resultado["revision"] = commit
    if dry_run:
        resultado["accion"] = "ensayo: se escribiria %s (%d B, sha %s)" % (resultado["archivo"], len(cuerpo), sha[:12])
        return resultado
    destino = Path(resultado["archivo"])
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        respaldo = destino.with_name("chat_template.stale.jinja")
        if not respaldo.exists():
            respaldo.write_bytes(destino.read_bytes())
    tmp = destino.with_suffix(".jinja.tmp")
    tmp.write_bytes(cuerpo)
    tmp.replace(destino)
    registro = leer_registro()
    e = entrada_de(modelo, registro)
    fila = dict(e or {"model": modelo})
    nativa = destino.parent / "chat_template.native.jinja"
    fila.update({"repo": repo, "revision": commit or "main",
                 "files": sorted(set((fila.get("files") or []) + [FICHERO])),
                 "sha256": sha, "active_path": str(destino),
                 "different_from_embedded": bool(sha256_de(nativa) and sha != sha256_de(nativa)),
                 "json_tool_calls": fila.get("json_tool_calls",
                                             bool(re.search(r"tool", cuerpo.decode("utf-8", "replace"), re.I)))})
    if e is None:
        registro.append(fila)
    escribir_registro(sorted(registro, key=lambda x: (x.get("model") or "").lower()))
    resultado["accion"] = "aplicada la plantilla del repo (%d B, sha %s, revision %s)" % (len(cuerpo), sha[:12], (commit or "main")[:12])
    resultado["aplicada"] = True
    resultado["estado"] = "aplicada"
    resultado["bytes"] = len(cuerpo)
    return resultado


def formato_llamada(tpath, *, native=False):
    """Report the effective tool format, including the agent's native syntax overlay."""
    if not tpath:
        return "json"
    try:
        fuente = (Path(tpath) / FICHERO).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "json"
    if native:
        original = Path(tpath) / "chat_template.native.jinja"
        if original.is_file():
            from serve.frontend import native_tool_template
            fuente = native_tool_template(fuente, original.read_text(encoding="utf-8"))
    if '<|tool_call>' in fuente and 'call:' in fuente:
        return 'gemma'
    if '<arg_key>' in fuente and '<arg_value>' in fuente:
        return 'glm'
    if '｜DSML｜invoke' in fuente:
        return 'dsml'
    if '<|tool_call_start|>' in fuente and '<|tool_call_end|>' in fuente:
        return 'lfm2'
    declaracion = re.search(r"(?s)(For each function call.{0,420}|If you choose to call a function.{0,620})",
                           fuente)
    texto = declaracion.group(0) if declaracion else fuente[:6000]
    if LT + "function=" in texto or LT + "parameter=" in texto:
        return "xml"
    return "json"


def comprobar_todo():
    """Una pasada por las 18 configs, para la consola y para 'Comprobar todas'."""
    salida = []
    for cfg in sorted(ROOT.glob("strata-*.json")):
        try:
            modelo = json.loads(cfg.read_text(encoding="utf-8-sig")).get("model_name") or cfg.stem.replace("strata-", "")
            salida.append(estado(modelo, cfg))
        except Exception as error:
            salida.append({"modelo": cfg.stem, "estado": "error", "detalle": str(error)[:200]})
    return salida


def resumen_para_carga(modelo, config_path):
    """Lo que se muestra al cargar: la veredicto en una linea, sin romper la carga."""
    try:
        est = estado(modelo, config_path)
    except Exception as error:
        return {"estado": "error", "linea": "plantilla: no se pudo comprobar (%s)" % str(error)[:80]}
    textos = {"aplicada": "plantilla del repo aplicada (%s, %d B) en %s"
              % ((est.get("sha_local") or "")[:12], est["bytes"], est["archivo"]),
              "sin_plantilla": "FALTA la plantilla del modelo: el motor usara la general de serve/",
              "correccion_no_aplicada": "activa la incrustada del GGUF: falta la correccion del repo",
              "desactualizada": "la copia local no es la del repo: hay version nueva",
              "sin_repo": "sin repo registrado: se usa la copia local (%d B)" % est["bytes"],
              "sin_correccion_en_repo": "el repo no publica plantilla: se usa la incrustada (%d B)" % est["bytes"],
              "sin_comprobacion": "sin red: se confia en la copia local (%d B)" % est["bytes"]}
    return {**est, "estado": est["estado"], "linea": textos.get(est["estado"], est["detalle"])}


if __name__ == "__main__":
    import sys
    accion = sys.argv[1] if len(sys.argv) > 1 else "estado"
    if accion == "estado":
        for r in comprobar_todo():
            print("%-30s %-22s %s" % ((r.get("modelo") or "")[:30], r.get("estado"), r.get("detalle", "")[:90]))
    else:
        modelo, cfg = sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None
        if cfg is None:
            cfg = str(next(ROOT.glob("strata-*%s*.json" % modelo.replace("-", "*"))))
        print(json.dumps(aplicar(modelo, cfg), ensure_ascii=False, indent=2))
