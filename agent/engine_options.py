"""Every load option of llama.cpp, Strata and Strata Rust that V-Agent does not already manage itself.

One catalog per engine: key, the engine's flag, kind of value, limits, plain-language label and help,
and the group it is shown in. An option is offered only when the installed executable lists its flag
in `--help` (builds differ: some llama.cpp builds have --mlock/--no-mmap, newer ones --load-mode).
Values are saved per model (`preferences['engine']`), validated here and turned into arguments at load.
`None` (or a missing key) means "the engine's own default": nothing is passed.

A separate V cache format (--cache-type-v) is left out on purpose: llama.cpp refuses K and V caches of
different formats (tested with every combination, Flash Attention on and off).

Flags V-Agent already sets from its own controls (context, KV format, layers, batch, slots, --fit,
checkpoints, draft model, MTP for Strata, vision, template, VRAM reserve) are deliberately not here.
"""
from functools import lru_cache
import re
import subprocess

# kind: 'int' | 'float' | 'choice' | 'bool' (flag present when True) | 'switch' (flag / no-flag) | 'text'
LLAMA = [
    # Performance
    {'key': 'flash_attn', 'flag': '--flash-attn', 'kind': 'choice', 'choices': ['auto', 'on', 'off'], 'group': 'performance',
     'label': 'Flash Attention', 'help': 'Atención más rápida y con menos memoria. Auto la activa cuando la GPU la admite. Una caché KV cuantizada (q8_0, q4_0) la necesita.'},
    {'key': 'threads', 'flag': '--threads', 'kind': 'int', 'min': 1, 'max': 512, 'group': 'performance',
     'label': 'Hilos de CPU al generar', 'help': 'Núcleos que usa la CPU mientras escribe la respuesta.'},
    {'key': 'threads_batch', 'flag': '--threads-batch', 'kind': 'int', 'min': 1, 'max': 512, 'group': 'performance',
     'label': 'Hilos de CPU al leer el prompt', 'help': 'Núcleos que usa la CPU al procesar el prompt.'},
    {'key': 'cont_batching', 'flag': '--cont-batching', 'off': '--no-cont-batching', 'kind': 'switch', 'group': 'performance',
     'label': 'Lotes continuos', 'help': 'Mezcla peticiones en curso con nuevas (útil con varios slots).'},
    {'key': 'warmup', 'flag': '--warmup', 'off': '--no-warmup', 'kind': 'switch', 'group': 'performance',
     'label': 'Calentamiento al cargar', 'help': 'Ejecuta una pasada vacía al cargar para que la primera respuesta no sea lenta.'},
    {'key': 'repack', 'flag': '--repack', 'off': '--no-repack', 'kind': 'switch', 'group': 'performance',
     'label': 'Reempaquetar pesos', 'help': 'Reorganiza los pesos para la CPU al cargar (más rápido en CPU, carga algo más lenta).'},
    {'key': 'op_offload', 'flag': '--op-offload', 'off': '--no-op-offload', 'kind': 'switch', 'group': 'performance',
     'label': 'Operaciones del host en la GPU', 'help': 'Lleva a la GPU operaciones de tensores que están en la RAM.'},
    {'key': 'prio', 'flag': '--prio', 'kind': 'choice', 'choices': ['-1', '0', '1', '2', '3'], 'group': 'performance',
     'labels': {'-1': 'Baja', '0': 'Normal', '1': 'Media', '2': 'Alta', '3': 'Tiempo real'},
     'label': 'Prioridad del proceso', 'help': 'Prioridad del motor frente a otros programas del equipo.'},
    # Memory
    {'key': 'load_mode', 'flag': '--load-mode', 'kind': 'choice', 'choices': ['auto', 'none', 'mmap', 'mlock', 'mmap+mlock', 'dio'],
     'group': 'memory', 'label': 'Modo de carga del modelo',
     'help': 'mmap lee el archivo según se necesita; mlock lo fija en RAM para que Windows no lo mueva al disco.'},
    {'key': 'mlock', 'flag': '--mlock', 'kind': 'bool', 'group': 'memory',
     'label': 'Fijar el modelo en RAM (mlock)', 'help': 'Impide que el sistema mueva el modelo al archivo de paginación.'},
    {'key': 'no_mmap', 'flag': '--no-mmap', 'kind': 'bool', 'group': 'memory',
     'label': 'Cargar el modelo entero (sin mmap)', 'help': 'Lee todo el archivo al cargar en vez de mapearlo.'},
    {'key': 'lazy_mode', 'flag': '--lazy-mode', 'kind': 'choice', 'choices': ['auto', 'on', 'off'], 'group': 'memory',
     'label': 'Lectura bajo demanda de tensores grandes', 'help': 'Lee del disco solo las filas que se usan de tensores muy grandes.'},
    {'key': 'kv_offload', 'flag': '--kv-offload', 'off': '--no-kv-offload', 'kind': 'switch', 'group': 'memory',
     'label': 'Caché KV en la GPU', 'help': 'Desactívalo para dejar la caché KV en la RAM y liberar VRAM (más lento).'},
    {'key': 'kv_unified', 'flag': '--kv-unified', 'off': '--no-kv-unified', 'kind': 'switch', 'group': 'memory',
     'label': 'Caché KV compartida entre slots', 'help': 'Un solo búfer KV para todos los slots paralelos.'},
    {'key': 'swa_full', 'flag': '--swa-full', 'kind': 'bool', 'group': 'memory',
     'label': 'Caché SWA completa', 'help': 'Para modelos con ventana deslizante: guarda todo el contexto (más memoria, menos recálculo).'},
    {'key': 'cache_ram', 'flag': '--cache-ram', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'Caché de prompts en RAM (MiB)', 'help': 'Memoria para conservar prompts anteriores y retomarlos sin releerlos. 0 la desactiva.'},
    {'key': 'cache_reuse', 'flag': '--cache-reuse', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'Reutilizar caché desde (tokens)', 'help': 'Tamaño mínimo de un trozo de prompt repetido para reutilizarlo desplazando la caché.'},
    {'key': 'context_shift', 'flag': '--context-shift', 'off': '--no-context-shift', 'kind': 'switch', 'group': 'memory',
     'label': 'Desplazar contexto al llenarse', 'help': 'Descarta lo más antiguo en vez de cortar la respuesta cuando se llena el contexto.'},
    # GPU
    {'key': 'device', 'flag': '--device', 'kind': 'text', 'pattern': r'[A-Za-z0-9_, ]{1,120}', 'group': 'gpu',
     'label': 'Dispositivos', 'help': 'Lista de dispositivos separados por comas (por ejemplo CUDA0,CUDA1).'},
    {'key': 'split_mode', 'flag': '--split-mode', 'kind': 'choice', 'choices': ['none', 'layer', 'row', 'tensor'], 'group': 'gpu',
     'label': 'Reparto entre varias GPU', 'help': 'Por capas (layer), por filas (row) o por tensores; none usa una sola GPU.'},
    {'key': 'main_gpu', 'flag': '--main-gpu', 'kind': 'int', 'min': 0, 'max': 63, 'group': 'gpu',
     'label': 'GPU principal', 'help': 'La GPU que usa el modelo con reparto none, o la de los resultados intermedios.'},
    {'key': 'tensor_split', 'flag': '--tensor-split', 'kind': 'text', 'pattern': r'\d+(\.\d+)?(,\d+(\.\d+)?){0,63}', 'group': 'gpu',
     'label': 'Proporción por GPU', 'help': 'Parte del modelo para cada GPU, separada por comas (por ejemplo 3,1).'},
    {'key': 'cpu_moe', 'flag': '--cpu-moe', 'kind': 'bool', 'group': 'gpu',
     'label': 'Todos los expertos MoE en la CPU', 'help': 'Deja en RAM todos los expertos y en la GPU el resto del modelo.'},
    {'key': 'override_tensor', 'flag': '--override-tensor', 'kind': 'text', 'pattern': r'[^\s"]{1,400}', 'group': 'gpu',
     'label': 'Ubicación de tensores (avanzado)', 'help': 'Patrón=búfer, por ejemplo exps=CPU para dejar expertos en la CPU.'},
    {'key': 'numa', 'flag': '--numa', 'kind': 'choice', 'choices': ['distribute', 'isolate', 'numactl'], 'group': 'gpu',
     'label': 'Optimización NUMA', 'help': 'Solo para equipos con varios nodos de memoria (varios procesadores).'},
    # Context (RoPE / YaRN)
    {'key': 'rope_scaling', 'flag': '--rope-scaling', 'kind': 'choice', 'choices': ['none', 'linear', 'yarn'], 'group': 'context',
     'label': 'Escalado RoPE', 'help': 'Método para usar más contexto del que el modelo trae de serie.'},
    {'key': 'rope_freq_base', 'flag': '--rope-freq-base', 'kind': 'float', 'min': 1, 'max': 1e9, 'group': 'context',
     'label': 'Frecuencia base de RoPE', 'help': 'Por defecto la del modelo. Solo cámbiala si el autor lo indica.'},
    {'key': 'rope_freq_scale', 'flag': '--rope-freq-scale', 'kind': 'float', 'min': 0.0001, 'max': 1, 'group': 'context',
     'label': 'Factor de escala de RoPE', 'help': 'Amplía el contexto por 1/N (0.25 = cuatro veces).'},
    {'key': 'yarn_orig_ctx', 'flag': '--yarn-orig-ctx', 'kind': 'int', 'min': 0, 'max': 4194304, 'group': 'context',
     'label': 'YaRN: contexto original', 'help': 'Contexto con el que se entrenó el modelo (0 = el del archivo).'},
    {'key': 'yarn_ext_factor', 'flag': '--yarn-ext-factor', 'kind': 'float', 'min': -1, 'max': 100, 'group': 'context',
     'label': 'YaRN: factor de extrapolación', 'help': '-1 usa el valor del modelo.'},
    {'key': 'yarn_attn_factor', 'flag': '--yarn-attn-factor', 'kind': 'float', 'min': -1, 'max': 100, 'group': 'context',
     'label': 'YaRN: factor de atención', 'help': '-1 usa el valor del modelo.'},
    # Adapters and reasoning
    {'key': 'lora', 'flag': '--lora', 'kind': 'text', 'pattern': r'[^"\r\n]{1,600}', 'group': 'adapters',
     'label': 'Adaptadores LoRA', 'help': 'Ruta de uno o varios archivos LoRA GGUF, separados por comas.'},
    {'key': 'reasoning_budget', 'flag': '--reasoning-budget', 'kind': 'int', 'min': -1, 'max': 1048576, 'group': 'adapters',
     'label': 'Presupuesto de razonamiento (tokens)', 'help': '-1 sin límite; 0 termina el razonamiento enseguida.'},
]

STRATA = [
    {'key': 'threads', 'flag': '--threads', 'kind': 'int', 'min': 1, 'max': 512, 'group': 'performance',
     'label': 'Hilos de CPU para expertos', 'help': 'Hilos para los expertos que no caben en VRAM (por defecto, 70 % de los núcleos).'},
    {'key': 'window', 'flag': '--window', 'kind': 'int', 'min': 1, 'max': 65536, 'group': 'performance',
     'label': 'Ventana de tokens por paso', 'help': 'Máximo de tokens que pasan por el modelo a la vez al escribir.'},
    {'key': 'prompt_batch', 'flag': '--prompt-batch', 'kind': 'int', 'min': 16, 'max': 65536, 'group': 'performance',
     'label': 'Tokens de prompt por lote', 'help': 'Tokens del prompt leídos a la vez (por defecto 1024; unos 1,4 MiB de VRAM cada uno).'},
    {'key': 'lookup', 'flag': '--lookup', 'kind': 'int', 'min': 1, 'max': 1024, 'group': 'performance',
     'label': 'Adivinar repeticiones (tokens)', 'help': 'Si se repiten los últimos N tokens, propone lo que siguió la otra vez (acelera código repetitivo).'},
    {'key': 'batch', 'flag': '--batch', 'kind': 'int', 'min': 1, 'max': 64, 'group': 'performance',
     'label': 'Respuestas simultáneas', 'help': 'Respuestas que se escriben a la vez, cada una con su propia secuencia.'},
    {'key': 'batch_mtp', 'flag': '--batch-mtp', 'kind': 'bool', 'group': 'performance',
     'label': 'Borrador en respuestas simultáneas', 'help': 'Con varias respuestas a la vez, cada una usa también el bloque que adivina.'},
    {'key': 'draft_vocab', 'flag': '--draft-vocab', 'kind': 'int', 'min': 1, 'max': 1048576, 'group': 'performance',
     'label': 'Vocabulario del borrador', 'help': 'El bloque que adivina elige entre los primeros N tokens del vocabulario.'},
    {'key': 'no_graphs', 'flag': '--no-graphs', 'kind': 'bool', 'group': 'performance',
     'label': 'Sin grafos CUDA', 'help': 'Lanza los kernels uno a uno. Solo para diagnosticar problemas.'},
    {'key': 'vram_pool', 'flag': '--vram-pool', 'kind': 'bool', 'group': 'memory',
     'label': 'Reservar la VRAM al cargar', 'help': 'Toma de una vez la VRAM libre (menos la reserva) para la caché de expertos.'},
    {'key': 'kv_whole', 'flag': '--kv-whole', 'kind': 'bool', 'group': 'memory',
     'label': 'Caché KV completa al cargar', 'help': 'Reserva la VRAM de todo el contexto al cargar en vez de según se use.'},
    {'key': 'ram_experts_mib', 'flag': '--ram-experts-mib', 'kind': 'int', 'min': 0, 'max': 4194304, 'group': 'memory',
     'label': 'RAM para expertos (MiB)', 'help': 'RAM reservada para los expertos que no están en VRAM, también al responder.'},
    {'key': 'lock_experts', 'flag': '--lock-experts', 'kind': 'bool', 'group': 'memory',
     'label': 'Fijar expertos en RAM', 'help': 'Impide que el sistema mueva al disco los expertos que están en RAM.'},
    {'key': 'expert_swaps', 'flag': '--expert-swaps', 'kind': 'int', 'min': 0, 'max': 4096, 'group': 'memory',
     'label': 'Expertos en tránsito', 'help': 'Expertos muy usados que se suben a VRAM mientras escribe.'},
    {'key': 'stage_mib', 'flag': '--stage-mib', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'VRAM de paso para expertos (MiB)', 'help': 'VRAM por la que pasan los expertos de fuera de la caché al leer el prompt.'},
    {'key': 'stage_ahead', 'flag': '--stage-ahead', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'Copiar expertos por adelantado desde (tokens)', 'help': 'A partir de N tokens, el lote copia los expertos antes de enrutar.'},
    {'key': 'stage_read_mib', 'flag': '--stage-read-mib', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'Búfer de paso en lecturas largas (MiB)', 'help': 'Hasta cuánto crece el búfer de paso en un prompt de varios lotes.'},
    {'key': 'cpu_share', 'flag': '--cpu-share', 'kind': 'float', 'min': 0, 'max': 1, 'group': 'memory',
     'label': 'Parte de expertos que calcula la CPU', 'help': 'Fracción (0–1) de esos expertos que calcula la CPU mientras tanto.'},
    {'key': 'prompt_cache_every', 'flag': '--prompt-cache-every', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'Punto de control cada (tokens)', 'help': 'Guarda un punto de control cada N tokens de prompt, además del final.'},
    {'key': 'conversation_cache_mib', 'flag': '--conversation-cache-mib', 'kind': 'int', 'min': 0, 'max': 4194304, 'group': 'memory',
     'label': 'RAM para conversaciones aparcadas (MiB)', 'help': 'Permite alternar varias conversaciones sin volver a leer su prompt.'},
    {'key': 'conversation_cache_slots', 'flag': '--conversation-cache-slots', 'kind': 'int', 'min': 0, 'max': 256, 'group': 'memory',
     'label': 'Conversaciones aparcadas', 'help': 'Máximo de conversaciones guardadas en RAM (por defecto 4).'},
    {'key': 'conversation_cache_min_tokens', 'flag': '--conversation-cache-min-tokens', 'kind': 'int', 'min': 0, 'max': 4194304,
     'group': 'memory', 'label': 'Aparcar desde (tokens)', 'help': 'Una conversación más corta no se guarda.'},
    {'key': 'conversation_cache_min_free_mib', 'flag': '--conversation-cache-min-free-mib', 'kind': 'int', 'min': 0, 'max': 4194304,
     'group': 'memory', 'label': 'RAM libre mínima para aparcar (MiB)', 'help': 'Solo guarda conversaciones mientras quede esta RAM física libre.'},
    {'key': 'layer_split', 'flag': '--layer-split', 'kind': 'text', 'pattern': r'[0-9.,: ]{1,120}', 'group': 'gpu',
     'label': 'Reparto de capas entre GPU', 'help': 'Capas del modelo repartidas entre las GPU CUDA que ve el proceso.'},
    {'key': 'no_gpu_experts', 'flag': '--no-gpu-experts', 'kind': 'bool', 'group': 'gpu',
     'label': 'Todos los expertos en la CPU', 'help': 'No guarda expertos en VRAM (menos VRAM, más lento).'},
    {'key': 'any_node', 'flag': '--any-node', 'kind': 'bool', 'group': 'gpu',
     'label': 'Hilos en cualquier nodo NUMA', 'help': 'Solo para equipos con varios nodos de memoria.'},
    {'key': 'tail_skip', 'flag': '--tail-skip', 'kind': 'int', 'min': 0, 'max': 1024, 'group': 'experimental',
     'label': 'Omitir expertos poco usados (posición)', 'help': 'Experimental: salta un experto de fuera de VRAM poco relevante. Puede bajar la calidad.'},
    {'key': 'skip_weight', 'flag': '--skip-weight', 'kind': 'float', 'min': 0, 'max': 1, 'group': 'experimental',
     'label': 'Omitir expertos por peso', 'help': 'Experimental: alternativa a la anterior por peso del enrutador. Puede bajar la calidad.'},
    {'key': 'cache_bias', 'flag': '--cache-bias', 'kind': 'float', 'min': 0, 'max': 10, 'group': 'experimental',
     'label': 'Preferir expertos en VRAM', 'help': 'Experimental (qwen35moe): favorece a los expertos ya en VRAM. Puede bajar la calidad.'},
]

RUST = [
    {'key': 'mtp', 'flag': '--mtp', 'kind': 'int', 'min': 1, 'max': 16, 'group': 'performance',
     'label': 'Borrador MTP (tokens por paso)', 'help': 'Decodificación especulativa con la cabeza MTP del modelo. Sin valor, desactivado.'},
    {'key': 'chunk', 'flag': '--chunk', 'kind': 'int', 'min': 0, 'max': 65536, 'group': 'performance',
     'label': 'Tokens de prompt por lote', 'help': 'Trozo de prefill en tokens (0 = token a token).'},
    {'key': 'threads', 'flag': '--threads', 'kind': 'int', 'min': 1, 'max': 512, 'group': 'performance',
     'label': 'Hilos de CPU para expertos', 'help': 'Hilos para los expertos que corren en la CPU.'},
    {'key': 'parallel', 'flag': '--parallel', 'kind': 'int', 'min': 1, 'max': 4, 'group': 'performance',
     'label': 'Respuestas simultáneas', 'help': 'Cada una tiene su propia caché KV del tamaño del contexto.'},
    {'key': 'vram_margin', 'flag': '--vram-margin', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'memory',
     'label': 'VRAM libre que se deja (MB)', 'help': 'VRAM que queda libre tras colocar los expertos (por defecto 512).'},
    {'key': 'cache_ram', 'flag': '--cache-ram', 'kind': 'int', 'min': 0, 'max': 4194304, 'group': 'memory',
     'label': 'RAM para conversaciones (MB)', 'help': 'Guarda estados de conversaciones anteriores para retomarlas sin releer el prompt.'},
    {'key': 'backend', 'flag': '--backend', 'kind': 'choice', 'choices': ['cuda', 'vulkan'], 'group': 'gpu',
     'label': 'Backend de GPU', 'help': 'CUDA (NVIDIA) o Vulkan. Por defecto CUDA si está disponible.'},
    {'key': 'device', 'flag': '--device', 'kind': 'text', 'pattern': r'\d{1,2}(,\d{1,2}){0,15}', 'group': 'gpu',
     'label': 'GPU a usar', 'help': 'Índice de GPU, o varios separados por comas para repartir las capas.'},
    {'key': 'lora', 'flag': '--lora', 'kind': 'text', 'pattern': r'[^"\r\n]{1,600}', 'group': 'adapters',
     'label': 'Adaptador LoRA', 'help': 'Archivo LoRA GGUF como ruta:escala (por ejemplo C:\\lora.gguf:1.0).'},
    {'key': 'llama_numerics', 'flag': '--llama-numerics', 'kind': 'bool', 'group': 'experimental',
     'label': 'Números como llama.cpp', 'help': 'Iguala la aritmética de llama.cpp para comparar resultados. Más lento.'},
    {'key': 'fixed_experts', 'flag': '--fixed-experts', 'kind': 'bool', 'group': 'experimental',
     'label': 'Expertos fijos', 'help': 'Coloca los expertos en orden y no los mueve, para repetir pruebas exactas.'},
]

CATALOG = {'llama': LLAMA, 'strata': STRATA, 'rust': RUST}
GROUPS = [('performance', 'Rendimiento'), ('memory', 'Memoria y caché'), ('gpu', 'GPU y CPU'),
          ('context', 'Contexto extendido (RoPE)'), ('adapters', 'Adaptadores y razonamiento'), ('experimental', 'Experimental')]
KEYS = {option['key'] for options in CATALOG.values() for option in options}


@lru_cache(maxsize=16)
def _help(path, size, mtime, args):
    try:
        run = subprocess.run([path, *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return run.stdout + run.stderr
    except (OSError, subprocess.SubprocessError):
        return ''


def help_text(kind, exe):
    """The executable's own option list (cached by file size and date)."""
    from pathlib import Path
    exe = Path(exe)
    if not exe.is_file():
        return ''
    stat = exe.stat()
    return _help(str(exe), stat.st_size, stat.st_mtime_ns, ('serve', '--help') if kind == 'rust' else ('--help',))


def supported(option, text):
    """The flag is listed as an option (not just mentioned in another option's description)."""
    return bool(re.search(r'(^|[\s,])' + re.escape(option['flag']) + r'(?=[\s,=\[<]|$)', text, re.M))


def catalog(kind, text):
    """The options this executable has, with their groups, for the interface."""
    options = [{**option, 'supported': supported(option, text)} for option in CATALOG.get(kind, [])]
    return {'engine': kind, 'groups': [{'id': g, 'label': label} for g, label in GROUPS],
            'options': [o for o in options if o['supported']], 'probed': bool(text)}


def _check(option, value):
    kind = option['kind']
    if value is None:
        return None
    if kind in ('bool', 'switch'):
        if type(value) is not bool:
            raise ValueError(f"«{option['label']}» debe ser sí o no.")
        return value
    if kind == 'choice':
        value = str(value)
        if value not in option['choices']:
            raise ValueError(f"Valor no válido para «{option['label']}».")
        return value
    if kind in ('int', 'float'):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == 'int' and int(value) != value):
            raise ValueError(f"«{option['label']}» debe ser un número{' entero' if kind == 'int' else ''}.")
        value = int(value) if kind == 'int' else float(value)
        if not option['min'] <= value <= option['max']:
            raise ValueError(f"«{option['label']}» debe estar entre {option['min']} y {option['max']}.")
        return value
    value = str(value).strip()
    if not value:
        return None
    if not re.fullmatch(option['pattern'], value):
        raise ValueError(f"Valor no válido para «{option['label']}».")
    return value


def validate(values, previous=None):
    """Merge and check saved options. Keys may belong to any engine (one model can move between them)."""
    if not isinstance(values, dict):
        raise ValueError('Opciones del motor no válidas.')
    unknown = set(values) - KEYS
    if unknown:
        raise ValueError('Opción del motor desconocida: ' + ', '.join(sorted(unknown)))
    result = dict(previous or {})
    for key, value in values.items():
        errors, checked, matched = [], None, False
        for options in CATALOG.values():
            option = next((o for o in options if o['key'] == key), None)
            if not option:
                continue
            try:
                checked = _check(option, value)
                matched = True
                break
            except ValueError as error:
                errors.append(error)
        if not matched:
            raise errors[0]
        if checked is None:
            result.pop(key, None)
        else:
            result[key] = checked
    return result


def arguments(kind, values, text):
    """Command-line arguments for the saved options this executable supports (others are skipped)."""
    args = []
    for option in CATALOG.get(kind, []):
        value = (values or {}).get(option['key'])
        if value is None or not supported(option, text):
            continue
        try:
            value = _check(option, value)
        except ValueError:
            continue
        if value is None:
            continue
        if option['kind'] == 'bool':
            if value:
                args.append(option['flag'])
        elif option['kind'] == 'switch':
            args.append(option['flag'] if value else option['off'])
        else:
            args += [option['flag'], str(value)]
    return args


def without(kind, args, keys):
    """`args` without the flags (and their values) of these catalog keys."""
    options = [o for o in CATALOG.get(kind, []) if o['key'] in set(keys)]
    flags = {o['flag'] for o in options} | {o['off'] for o in options if o.get('off')}
    valueless = {o['flag'] for o in options if o['kind'] in ('bool', 'switch')} | {o['off'] for o in options if o.get('off')}
    kept, skip = [], False
    for item in args:
        if skip:
            skip = False
            continue
        if item in flags:
            skip = item not in valueless
            continue
        kept.append(item)
    return kept


def apply(kind, args, values, text, previous=()):
    """For a saved argument list (Strata configs): drop what V-Agent applied last time (`previous` keys)
    and what is set now, then add the current values. Returns (args, keys applied now) so the caller can
    remember them; flags the config had on its own and the user never touched are kept."""
    values = values or {}
    applied = [o['key'] for o in CATALOG.get(kind, []) if values.get(o['key']) is not None and supported(o, text)]
    return without(kind, args, set(previous) | set(applied)) + arguments(kind, values, text), applied


def conflicts(kind, values, kv):
    """A combination the engine refuses, said before it is started; None when fine."""
    if kind == 'llama' and (values or {}).get('flash_attn') == 'off' and str(kv or '').startswith(('q', 'iq')):
        return ('La caché KV cuantizada (' + str(kv) + ') necesita Flash Attention: ponlo en Automático o Activado en '
                'Ajustes avanzados del motor, o usa la caché FP16.')
    return None
