"""Model-driven tool battery against a running core (a real model chooses the tools).

Usage: tool_battery.py BASE DATA_DIR ENGINE MODEL_ID OUT.json
Runs the 5 quick cases (write, edit, copy/paste lines, diagnose and fix, restore a version: about
2 minutes). Set SUITE_FULL=1 for all 13 cases, or SUITE_ONLY=1,4,9 for specific ones. Use a
throw-away data folder: the cases create files in its per-chat workspaces.
"""
import json, os, subprocess, sys, threading, time, urllib.error, urllib.request, uuid
from pathlib import Path

BASE, DATA, ENGINE, MODEL, OUT = sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4], Path(sys.argv[5])
H = {'Content-Type': 'application/json', 'Origin': BASE}
FUNCS = {'search': False, 'visit': False, 'files': True, 'shell': False, 'sys': True, 'hf': False, 'date': True,
         'browser': False, 'console': False, 'web': False, 'autobrowser': False, 'computer': False, 'admin': False}

def post(path, body, timeout=900):
    return json.load(urllib.request.urlopen(urllib.request.Request(BASE + path, json.dumps(body).encode(), H), timeout=timeout))

def folder(chat):
    path = DATA / 'workspaces' / 'conversations' / chat
    path.mkdir(parents=True, exist_ok=True)
    return path

def chat(chat_id, messages, cut_after_draft=0):
    """Run one turn; auto-approve; optionally cut the connection after N draft deltas (like the Stop button)."""
    body = {'model': MODEL, 'conversation_id': chat_id, 'messages': messages, 'functions': FUNCS, 'effort': 'high',
            'profile': 'custom', 'rounds': 30, 'permission_mode': 'auto', 'agent_profile': 'light', 'native_stream': True}
    tools, results, text, drafts = [], [], '', 0
    req = urllib.request.Request(BASE + '/api/chat', json.dumps(body).encode(), H)
    with urllib.request.urlopen(req, timeout=1500) as response:
        for raw in response:
            if not raw.startswith(b'data: '):
                continue
            try:
                ev = json.loads(raw[6:])
            except ValueError:
                continue
            kind = ev.get('type')
            if kind == 'approval':
                threading.Thread(target=lambda i=ev['id']: post('/api/harness/approval', {'id': i, 'allowed': True})).start()
            elif kind == 'tool':
                tools.append(ev.get('name', '').split('__')[-1])
            elif kind == 'tool_result':
                results.append((ev.get('name', '').split('__')[-1], str(ev.get('result', ''))[:300]))
            elif kind == 'tool_draft':
                drafts += 1
                if cut_after_draft and drafts >= cut_after_draft:
                    response.close()
                    break
            elif kind == 'content':
                text += ev.get('text', '') or ''
            elif kind == 'done':
                text = ev.get('content') or text
            elif kind == 'error':
                text += ' [ERROR] ' + str(ev.get('error') or ev.get('message'))
    if cut_after_draft:
        for _ in range(60):
            if not json.load(urllib.request.urlopen(BASE + '/api/chat/status', timeout=5)).get('busy'):
                break
            time.sleep(0.5)
    return {'tools': tools, 'results': results, 'text': text.strip()}

def run(name, setup, turns, check):
    cid = 'suite-' + uuid.uuid4().hex[:10]
    work = folder(cid)
    for rel, content in (setup or {}).items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(content, encoding='utf-8')
    messages, record, t = [], {'case': name, 'turns': []}, time.time()
    try:
        for turn in turns:
            prompt, cut = turn if isinstance(turn, tuple) else (turn, 0)
            messages.append({'role': 'user', 'content': prompt})
            out = chat(cid, messages, cut)
            record['turns'].append(out)
            messages.append({'role': 'assistant', 'content': out['text'] or '(sin texto)'})
        tools = [x for o in record['turns'] for x in o['tools']]
        # fs_write of an .html page is checked in the headless browser by V-Agent itself.
        if any(n == 'fs_write' and 'chrome' in r for o in record['turns'] for n, r in o['results']):
            tools.append('auto_render')
        if any(n in ('fs_write', 'fs_edit') and 'Syntax checked' in r for o in record['turns'] for n, r in o['results']):
            tools.append('auto_syntax')
        ok, note = check(work, tools, record['turns'][-1]['text'])
        record.update(ok=bool(ok), note=note, tools=tools)
    except Exception as error:
        record.update(ok=False, note='excepción: %s' % error, tools=[])
    record['seconds'] = round(time.time() - t)
    print(('OK   ' if record['ok'] else 'FALLO') + ' %-34s %4ss  herramientas=%s  %s' % (name, record['seconds'], record['tools'], record['note']), flush=True)
    return record

def read(work, rel):
    p = work / rel
    return p.read_text(encoding='utf-8', errors='replace') if p.is_file() else None

def node_ok(path):
    return subprocess.run(['node', '--check', str(path)], capture_output=True).returncode == 0

CASES = [
    ('1 escribir archivo', None,
     ['Crea un archivo notas.txt con tres líneas: uno, dos y tres (cada palabra en su línea).'],
     lambda w, t, a: (read(w, 'notas.txt') and [l.strip() for l in read(w, 'notas.txt').strip().splitlines()] == ['uno', 'dos', 'tres'] and 'fs_write' in t,
                      'contenido=%r' % (read(w, 'notas.txt') or '')[:40])),
    ('2 leer una línea', {'datos.txt': 'alfa\nbeta\ngamma\ndelta\n'},
     ['¿Qué palabra hay en la línea 3 del archivo datos.txt? Léelo para responder.'],
     lambda w, t, a: ('fs_read' in t and 'gamma' in a.lower(), 'respuesta=%r' % a[:60])),
    ('3 listar y resumir carpeta', {'app.py': 'print("hola")\n', 'README.md': '# Demo\n', 'src/util.js': 'export const x=1;\n'},
     ['Mira qué archivos hay en la carpeta de trabajo y dime en una frase de qué trata el proyecto.'],
     lambda w, t, a: (any(x in t for x in ('fs_list', 'project_map', 'fs_search')) and 'app.py' in a, 'respuesta=%r' % a[:70])),
    ('4 buscar texto', {'a.py': '# TODO revisar\nx = 1\n', 'b.py': 'y = 2\n', 'docs/c.md': 'TODO: documentar\n'},
     ['¿En qué archivos de la carpeta aparece la palabra TODO? Búscalo.'],
     lambda w, t, a: ('fs_search' in t and 'a.py' in a and 'c.md' in a and 'b.py' not in a, 'respuesta=%r' % a[:70])),
    ('5 editar (arreglar bug)', {'calc.py': 'def suma(a, b):\n    return a - b\n\nprint(suma(2, 3))\n'},
     ['La función suma de calc.py resta en vez de sumar. Corrígela en el archivo.'],
     lambda w, t, a: ('a + b' in (read(w, 'calc.py') or '') and 'a - b' not in read(w, 'calc.py') and ('fs_edit' in t or 'fs_write' in t),
                      'usa fs_edit=%s' % ('fs_edit' in t))),
    ('6 copiar y pegar líneas', {'origen.txt': 'L1\nL2\nL3\nL4\nL5\n', 'destino.txt': 'INICIO\n'},
     ['Copia las líneas 2 a 4 de origen.txt y pégalas al final de destino.txt, sin borrar nada de origen.txt.'],
     lambda w, t, a: ([l.strip() for l in (read(w, 'destino.txt') or '').strip().splitlines()] == ['INICIO', 'L2', 'L3', 'L4']
                      and (read(w, 'origen.txt') or '').count('L') == 5, 'destino=%r herramienta fs_copy=%s' % ((read(w, 'destino.txt') or '')[:40], 'fs_copy' in t))),
    ('7 copiar y mover archivos', {'informe.txt': 'datos\n'},
     ['Haz una copia de informe.txt llamada respaldo.txt y después mueve informe.txt a una carpeta nueva llamada archivo.'],
     lambda w, t, a: ((w / 'respaldo.txt').is_file() and (w / 'archivo' / 'informe.txt').is_file() and not (w / 'informe.txt').exists(),
                      'fs_manage=%s' % ('fs_manage' in t))),
    ('8 diagnosticar y arreglar JS', {'roto.js': 'function saludo(nombre {\n  return "Hola " + nombre;\n}\nconsole.log(saludo("Ana"));\n'},
     ['El archivo roto.js tiene errores. Revisa su sintaxis con la herramienta de verificación, corrígelo y vuelve a verificarlo.'],
     lambda w, t, a: (node_ok(w / 'roto.js') and 'code_check' in t, 'node --check ok=%s' % node_ok(w / 'roto.js'))),
    ('9 HTML y verificación en navegador', None,
     ['Crea pagina.html con un botón que al pulsarlo cambie el texto de un párrafo, y comprueba en el navegador que funciona sin errores.'],
     lambda w, t, a: (read(w, 'pagina.html') and ('web_render' in t or 'auto_render' in t), 'web_render=%s auto=%s' % ('web_render' in t, 'auto_render' in t))),
    ('10 restaurar versión anterior', None,
     ['Crea config.json con el contenido {"modo": "claro"}.',
      'Cambia el modo de config.json a "oscuro".',
      'Me arrepentí: restaura config.json a la versión anterior usando el historial de versiones del archivo.'],
     lambda w, t, a: ('claro' in (read(w, 'config.json') or '') and 'file_history' in t, 'contenido=%r' % (read(w, 'config.json') or '')[:40])),
    ('11 retomar escritura interrumpida', None,
     [('Escribe un archivo largo informe.md con 40 secciones numeradas, cada una con un título y dos frases.', 60),
      'La escritura anterior se cortó. Retoma el borrador guardado y termina el archivo informe.md.'],
     lambda w, t, a: ((read(w, 'informe.md') or '').count('#') >= 10 and 'draft_resume' in t, 'draft_resume=%s secciones=%d' % ('draft_resume' in t, (read(w, 'informe.md') or '').count('#')))),
    ('12 escribir fuera de la carpeta', None,
     ['Guarda un archivo en C:\\Windows\\prueba_vagent.txt con el texto hola.'],
     lambda w, t, a: (not Path(r'C:\Windows\prueba_vagent.txt').exists() and t.count('fs_write') <= 3 and len(a) > 10,
                      'intentos=%d respuesta=%r' % (t.count('fs_write'), a[:70]))),
    ('13 script Python verificado', None,
     ['Crea un script primos.py que imprima los números primos menores que 50 y verifica que su sintaxis es correcta.'],
     lambda w, t, a: (read(w, 'primos.py') and subprocess.run([sys.executable, '-m', 'py_compile', str(w / 'primos.py')], capture_output=True).returncode == 0 and ('code_check' in t or 'auto_syntax' in t),
                      'code_check=%s auto=%s' % ('code_check' in t, 'auto_syntax' in t))),
]

print('== motor:', ENGINE, '| modelo:', MODEL, flush=True)
print('configurar:', post('/api/harness/configure', {'engine': ENGINE}).get('active'), flush=True)
t = time.time()
print('carga:', post('/api/load', {'model': MODEL, 'context': 32768}, 1500).get('loaded'), '%.0fs' % (time.time() - t), flush=True)
only = os.environ.get('SUITE_ONLY') or (None if os.environ.get('SUITE_FULL') else '1,5,6,8,10')
records = []
try:
    for case in CASES:
        if only and not any(case[0].startswith(x + ' ') for x in only.split(',')):
            continue
        records.append(run(*case))
finally:
    try:
        post('/api/unload', {})
    except Exception:
        pass
OUT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding='utf-8')
print('== resultado: %d/%d' % (sum(r['ok'] for r in records), len(records)), flush=True)
