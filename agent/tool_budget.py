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

from mcp_prompt import DESCRIPTIONS as _FULL_DESCRIPTIONS

# Keep complete tool instructions everywhere (including 1.0.9 Light mode); never replace them with short stubs.
SHORT_DESCRIPTIONS = dict(_FULL_DESCRIPTIONS)
SHORT_DESCRIPTIONS.setdefault('pc__fs_edit', _FULL_DESCRIPTIONS['pc__fs_edit'])
SHORT_DESCRIPTIONS.setdefault('pc__draft_resume', _FULL_DESCRIPTIONS['pc__draft_resume'])
_SHORT_CONTRACTS = {}


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
                         compact_tool_prompt=False, strata_native_tools=True, no_date=True, enable_thinking=False)
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
    """Preserve complete parameter descriptions and schema fields without stripping instructions."""
    if not isinstance(schema, dict):
        return schema
    return json.loads(json.dumps(schema))


def escalera(tools, mensajes, tpath, limite=None):
    """Return (tools, informe) with full MCP instructions preserved (never shortened to save tokens)."""
    limite = LIMITE if limite is None else int(limite)
    herramientas = json.loads(json.dumps(tools))
    estimado = estimacion(herramientas)
    informe = {"limite": limite, "nivel": 0, "token_antes": estimado, "token_despues": estimado,
               "recortes": "", "fuera": [], "aproximado": True}
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
