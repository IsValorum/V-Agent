# -*- coding: utf-8 -*-
"""Compact model-facing tool prose while preserving complete functional schemas.

The token limit is a soft target: never remove optional parameters, validation
rules or user-selected tools. fs_edit needs old_text/new_text or edits even
though its top-level JSON Schema only requires path. Costs use the active
model's tokenizer and template when the block is near the target.
"""
import hashlib
import json
import os
from pathlib import Path

LIMITE = int(os.environ.get("STRATA_AGENT_TOOL_BUDGET", "1000"))
# Medido con el tokenizador real de Qwen/Tiel (2026-11-03): 3.740 chars de JSON = 914 tokens y
# 2.472 chars = 601 tokens. Con esa recta se decide cuando hace falta medir de verdad, para no
# cargar el tokenizador (719 ms, +144 MB) en una conversacion que va sobrada de presupuesto.
CHARS_POR_TOKEN = 4.09
UMBRAL_MEDICION = 0.80
_TOKENIZADORES, _PLANTILLAS, _MEMORIA = {}, {}, {}

# Whole instructions, never sliced through a JSON/XML example or parameter name.
SHORT_DESCRIPTIONS = {
    'pc__file_history': 'List versions by path; pass a listed revision ID to restore.',
    'pc__code_check': 'Check syntax or list project checks; run=true needs full-PC access.',
    'pc__project_map': 'List project files and symbols.',
    'hf__hf_account': 'Read the authenticated HF account; never returns tokens.',
    'hf__hf_cli': 'Run official HF CLI args without hf. Inspect syntax with --help; use hf_transfer for files. No auth tokens/login/logout.',
    'hf__hf_transfer': 'Upload/download HF repo files; path is conversation-relative locally; filename is the remote file/path.',
    'pc__draft_resume': 'Resume the latest saved draft. No arguments.',
    'pc__fs_list': 'List a directory ("." or any relative/absolute directory path).',
    'pc__fs_read': 'Read a UTF-8 file (use fs_list for directories); linea=first line, ventana=line count; offset=character offset.',
    'pc__fs_write': 'Write UTF-8 text to a relative or absolute file path; creates parents and replaces existing files.',
    'pc__fs_edit': 'Replace old_text with new_text, or apply edits atomically.',
    'pc__fs_copy': 'Copy desde to destino; linea/hasta select lines; ancla sets insertion; cortar moves.',
    'pc__web_render': 'Run HTML; report console errors and WebGL, not visual quality.',
    'pc__shell_run': 'Run cmd or PowerShell; return exit code and output.',
    'pc__sys_info': 'Read CPU, OS, RAM, disks and GPU.',
    'duckduckgo__web_search': 'Search the web; return titles, URLs and snippets.',
    'duckduckgo__web_visit': 'Read URL; reuse page_id with offset=next_offset to continue.',
}

from mcp_prompt import DESCRIPTIONS as _CONTRACTS
for _name in ('pc__fs_edit','pc__fs_copy','pc__fs_manage','pc__console','pc__shell_run','pc__code_check','pc__web_render','web__http_request','web__download','autobrowser__open'):
    SHORT_DESCRIPTIONS[_name]=_CONTRACTS[_name]


def estimacion(tools):
    """Tokens estimados del bloque, por caracteres (sin cargar tokenizador)."""
    return round(len(json.dumps(tools, ensure_ascii=False, separators=(",", ":"))) / CHARS_POR_TOKEN)


def _tokenizer(tpath):
    """El tokenizador del modelo, cargado una sola vez (es el mismo que usa el motor)."""
    clave = str(tpath)
    if clave not in _TOKENIZADORES:
        import sys
        for extra in (str(__import__('runtime_paths').SOURCE_ROOT),str(__import__('runtime_paths').SOURCE_ROOT/'tools')):
            if extra not in sys.path:
                sys.path.insert(0, extra)
        import strata_tokenizer as ST
        _TOKENIZADORES[clave] = ST.Tokenizer.from_dir(tpath)
    return _TOKENIZADORES[clave]


def _plantilla(tpath):
    clave = str(tpath)
    fingerprint = _template_fingerprint(tpath)
    if clave not in _PLANTILLAS or _PLANTILLAS[clave][0] != fingerprint:
        import sys
        for extra in (str(__import__('runtime_paths').SOURCE_ROOT),):
            if extra not in sys.path:
                sys.path.insert(0, extra)
        from serve.frontend import ChatTemplate
        from pathlib import Path as P
        tpl = P(clave) / "chat_template.jinja"
        _PLANTILLAS[clave] = (fingerprint, ChatTemplate(tpl if tpl.exists() else __import__('runtime_paths').SOURCE_ROOT/'serve/chat_template.jinja'))
    return _PLANTILLAS[clave][1]


def _template_fingerprint(tpath):
    active = Path(tpath)/'chat_template.jinja'
    if not active.exists():
        active = __import__('runtime_paths').SOURCE_ROOT/'serve/chat_template.jinja'
    files = (active, active.with_name('chat_template.native.jinja'))
    return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else (str(path),None,None) for path in files)


def coste(mensajes, tools, tpath):
    """Tokens que añade el bloque de tools: la plantilla renderizada con y sin herramientas."""
    if not tools:
        return 0
    # Clave = hash del JSON ENTERO. Con un prefijo recortado a 4.000 caracteres, dos conjuntos que
    # empiezan igual (los mismos pc__* y luego dos tools web) chocaban y el segundo devolvia el
    # numero del primero: mediamos 8 tools creyendo medir 10.
    clave = (str(tpath), _template_fingerprint(tpath), hashlib.sha1(json.dumps(tools, sort_keys=True,
                                                 ensure_ascii=False).encode("utf-8")).hexdigest(),
             hashlib.sha1(json.dumps(mensajes, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest())
    if clave in _MEMORIA:
        return _MEMORIA[clave]
    tok = _tokenizer(tpath)
    tpl = _plantilla(tpath)
    try:
        from templates import formato_llamada
        template_tools = [{'type':'function','function':t} for t in tools] if formato_llamada(tpath,native=True)=='gemma' else tools
        con = tpl.render(mensajes, tools=template_tools, add_generation_prompt=True,
                         compact_tool_prompt=True, strata_native_tools=True, no_date=True, enable_thinking=False)
        sin = tpl.render(mensajes, tools=None, add_generation_prompt=True,
                         no_date=True, enable_thinking=False)
        n = len(tok.encode(con, parse_special=True)) - len(tok.encode(sin, parse_special=True))
    except Exception:
        n = -1                                   # una plantilla rara: no se corta la conversacion por esto
    if len(_MEMORIA) >= 256:
        _MEMORIA.pop(next(iter(_MEMORIA)))
    _MEMORIA[clave] = max(0, n)
    return _MEMORIA[clave]


def _sin_ruido(schema):
    """Remove display annotations while preserving parameter instructions."""
    if not isinstance(schema, dict):
        return schema
    salida = {}
    for k, v in schema.items():
        if k in ("title", "examples", "$comment"):
            continue
        if k in ("properties", "$defs", "definitions"):
            salida[k] = {nombre: _sin_ruido(prop) for nombre, prop in v.items()}
        elif k in ("items", "additionalProperties"):
            salida[k] = _sin_ruido(v)
        else:
            salida[k] = v
    return salida


def escalera(tools, mensajes, tpath, limite=None):
    """(tools, informe), targeting `limite` without changing functional contracts.

    Mientras la estimacion por caracteres quede lejos del limite no se carga el tokenizador (719 ms
    y +144 MB de RAM en la laptop): con los 8 MCP de hoy esto cuesta 0 en la conversacion.
    """
    limite = LIMITE if limite is None else int(limite)
    herramientas = json.loads(json.dumps(tools))
    informe = {"limite": limite, "nivel": 0, "token_antes": 0, "token_despues": 0,
               "recortes": "", "fuera": [], "aproximado": True}
    if limite <= 0 or not herramientas:
        informe["token_antes"] = informe["token_despues"] = estimacion(herramientas)
        return herramientas, informe
    estimado = estimacion(herramientas)
    informe["token_antes"] = estimado
    if estimado < limite * UMBRAL_MEDICION:
        informe["token_despues"] = estimado
        return herramientas, informe
    if not tpath or not (Path(tpath) / "vocab.json").exists():
        informe["token_despues"] = estimado
        informe["recortes"] = ("el bloque va justo de presupuesto y no hay tokenizador del modelo "
                               "para medirlo: revisa las descripciones de las tools")
        return herramientas, informe

    def n_tokens(lista):
        return coste([{"role": "user", "content": "hola"}], [t["function"] for t in lista], tpath)

    # Medida real antes de tocar nada: la estimacion por caracteres es conservadora y aqui puede
    # resultar que el bloque ya quepa, en cuyo caso no se recorta ni un campo.
    actual = n_tokens(herramientas)
    informe["token_antes"], informe["token_despues"], informe["aproximado"] = actual, actual, False
    if actual <= limite:
        return herramientas, informe

    for t in herramientas:
        fn = t["function"]
        fn["parameters"] = _sin_ruido(fn.get("parameters") or {})
    actual = n_tokens(herramientas)
    informe["nivel"], informe["recortes"] = 1, "anotaciones visuales fuera; instrucciones de parámetros conservadas"
    informe["token_despues"] = actual
    if actual > limite:
        for t in herramientas:
            d = str(t["function"].get("description") or "")
            t["function"]["description"] = SHORT_DESCRIPTIONS.get(t['function']['name'], d)
        informe["nivel"] = 2
        informe["recortes"] += " | instrucciones breves completas, sin cortar ejemplos"
        actual = n_tokens(herramientas)
    if actual > limite:
        informe['over_budget'] = True
        informe["recortes"] += " | presupuesto superado para conservar todas las funciones seleccionadas"
    informe["token_despues"] = actual
    return herramientas, informe


def resumen_informe(informe):
    if not informe or informe.get("nivel", 0) == 0:
        return ""
    partes = ["herramientas recortadas a nivel %d (%s)" % (informe["nivel"], informe["recortes"])]
    if informe.get("fuera"):
        partes.append("sin enviar: " + ", ".join(informe["fuera"]))
    partes.append("%d -> %d tokens (limite %d)"
                  % (informe["token_antes"], informe["token_despues"], informe["limite"]))
    return " | ".join(partes)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import agent, mcp_prompt
    if len(sys.argv) < 2:
        sys.exit("usage: tool_budget.py <model-id> [limit]")
    modelo = sys.argv[1]
    limite = int(sys.argv[2]) if len(sys.argv) > 2 else LIMITE
    tpath = Path(__file__).resolve().parents[1] / "seeds" / "model-assets" / modelo / "tokenizer"
    hub = agent.create_agent_hub()
    hub.start(wait=True)
    brutas = hub.openai_tools()
    hub.close()
    brutas = ([t for t in brutas if t["function"]["name"].startswith("pc__")]
              + [t for t in brutas if not t["function"]["name"].startswith("pc__")])
    compactas = mcp_prompt.compact_tools(brutas)      # lo que de verdad se manda en agent.tools_for
    mensajes = [{"role": "user", "content": "hola"}]
    print("limite %d tokens | tokenizador %s" % (limite, tpath.parent.name))
    for etiqueta, todas in (("brutas", brutas), ("compactas", compactas)):
        conjuntos = {"pc": [t for t in todas if t["function"]["name"].startswith("pc__")],
                     "web": [t for t in todas if not t["function"]["name"].startswith("pc__")],
                     "todo": todas}
        for nombre, lista in conjuntos.items():
            bruto = coste(mensajes, [t["function"] for t in lista], tpath)
            rec, info = escalera(lista, mensajes, tpath, limite=limite)
            print("  %-9s %-5s %2d tools | bloque %4d tokens | nivel %d -> %4d | fuera %s"
                  % (etiqueta, nombre, len(lista), bruto, info.get("nivel", 0),
                     info.get("token_despues", 0), info.get("fuera") or "-"))
    print("  coste por herramienta (compacta, sola en el bloque):")
    for t in compactas:
        print("    %-24s %4d" % (t["function"]["name"], coste(mensajes, [t["function"]], tpath)))
    rec, info = escalera(compactas, mensajes, tpath, limite=limite)
    if info.get("nivel", 0):
        print("  informe:", resumen_informe(info)[:400])
