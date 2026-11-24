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
    {'key': 'batch_mtp', 'flag': '--batch-mtp', 'kind': 'bool', 'group': 'performance', 'archs': ['qwen35moe', 'clover_moe'],
     'label': 'Borrador en respuestas simultáneas', 'help': 'Con varias respuestas a la vez, cada una usa también el bloque que adivina.'},
    {'key': 'loop_bf16', 'flag': '--loop-bf16', 'off': '--no-loop-bf16', 'kind': 'switch', 'group': 'performance', 'archs': ['inkling2_loop', 'inkling2'],
     'label': 'Controladores de bucle en BF16', 'help': 'Inkling 2: usa BF16 en los controladores de bucle en lugar de F32.'},
    {'key': 'prompt_int8', 'flag': '--prompt-int8', 'off': '--no-prompt-int8', 'kind': 'switch', 'group': 'performance', 'archs': ['inkling2_loop', 'inkling2'],
     'label': 'Lectura de prompt en INT8 (RTX 20)', 'help': 'Inkling 2 en GPU Turing (RTX 20): usa núcleos tensoriales INT8 para acelerar la lectura del prompt.'},
    {'key': 'draft_vocab', 'flag': '--draft-vocab', 'kind': 'int', 'min': 1, 'max': 1048576, 'group': 'performance',
     'label': 'Vocabulario del borrador', 'help': 'El bloque que adivina elige entre los primeros N tokens del vocabulario.'},
    {'key': 'no_graphs', 'flag': '--no-graphs', 'kind': 'bool', 'group': 'performance',
     'label': 'Sin grafos CUDA', 'help': 'Lanza los kernels uno a uno. Solo para diagnosticar problemas.'},
    {'key': 'vram_pool', 'flag': '--vram-pool', 'kind': 'bool', 'group': 'memory',
     'label': 'Reservar la VRAM al cargar', 'help': 'Toma de una vez la VRAM libre (menos la reserva) para la caché de expertos.'},
    {'key': 'kv_whole', 'flag': '--kv-whole', 'kind': 'bool', 'group': 'memory',
     'label': 'Caché KV completa al cargar', 'help': 'Reserva la VRAM de todo el contexto al cargar en vez de según se use.'},
    {'key': 'kv_resident', 'flag': '--kv-resident', 'kind': 'int', 'min': 0, 'max': 4194304, 'group': 'memory',
     'label': 'Celdas KV residentes en VRAM', 'help': 'Celdas de atención que permanecen en VRAM mientras el resto pasa desde RAM (0 = todas en VRAM).'},
    {'key': 'attn_requant', 'flag': '--attn-requant', 'kind': 'choice', 'choices': ['off', 'q5_0', 'q4_0', 'iq4_nl'], 'group': 'memory', 'archs': ['inkling2_loop', 'inkling2'],
     'label': 'Recuantizar atención (Inkling 2)', 'help': 'Inkling 2: recuantiza las matrices de atención al cargar (q5_0, q4_0 o iq4_nl) para reducir VRAM.'},
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
    {'key': 'expert_gpu', 'flag': '--expert-gpu', 'kind': 'int', 'min': 0, 'max': 63, 'group': 'gpu', 'archs': ['inkling2_loop', 'inkling2'],
     'label': 'GPU secundaria para expertos', 'help': 'Inkling 2: índice de la GPU CUDA adicional donde colocar los expertos que no caben en la primera.'},
    {'key': 'expert_gpu_reserve_mib', 'flag': '--expert-gpu-reserve-mib', 'kind': 'int', 'min': 0, 'max': 1048576, 'group': 'gpu', 'archs': ['inkling2_loop', 'inkling2'],
     'label': 'Reserva VRAM en GPU de expertos (MiB)', 'help': 'VRAM libre reservada en la GPU secundaria de expertos (por defecto 512 MiB).'},
    {'key': 'no_gpu_experts', 'flag': '--no-gpu-experts', 'kind': 'bool', 'group': 'gpu',
     'label': 'Todos los expertos en la CPU', 'help': 'No guarda expertos en VRAM (menos VRAM, más lento).'},
    {'key': 'any_node', 'flag': '--any-node', 'kind': 'bool', 'group': 'gpu',
     'label': 'Hilos en cualquier nodo NUMA', 'help': 'Solo para equipos con varios nodos de memoria.'},
    {'key': 'tail_skip', 'flag': '--tail-skip', 'kind': 'int', 'min': 0, 'max': 1024, 'group': 'experimental',
     'label': 'Omitir expertos poco usados (posición)', 'help': 'Experimental: salta un experto de fuera de VRAM poco relevante. Puede bajar la calidad.'},
    {'key': 'route_top', 'flag': '--route-top', 'kind': 'int', 'min': 0, 'max': 1024, 'group': 'experimental',
     'label': 'Límite de expertos enrutados', 'help': 'Experimental: descarta expertos a partir de la posición N+1 en VRAM o CPU (0 = sin límite).'},
    {'key': 'skip_weight', 'flag': '--skip-weight', 'kind': 'float', 'min': 0, 'max': 1, 'group': 'experimental',
     'label': 'Omitir expertos por peso', 'help': 'Experimental: alternativa a la anterior por peso del enrutador. Puede bajar la calidad.'},
    {'key': 'cache_bias', 'flag': '--cache-bias', 'kind': 'float', 'min': 0, 'max': 10, 'group': 'experimental', 'archs': ['qwen35moe', 'clover_moe', 'inkling2_loop', 'inkling2'],
     'label': 'Preferir expertos en VRAM', 'help': 'Experimental (qwen35moe / Inkling 2): favorece a los expertos ya en VRAM. Puede bajar la calidad.'},
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

# Project Maya's settings panel (maya_engine) owns these; anything else its executable lists is offered as an extra.
MAYA_MANAGED = ('--backend', '--cache-gb', '--chunk', '--config', '--context', '--cpu-threads', '--dflash', '--drafting',
                '--dspark', '--dspark-conf', '--engine', '--expert-cache', '--glm-pack', '--gpus', '--kv', '--kv-cache',
                '--kv-resident', '--kv-streaming', '--max-context', '--mmap-experts', '--model', '--model-dir',
                '--models-dir', '--mtp', '--mtp-max-t', '--no-vision', '--pack', '--parallel', '--ple-gguf', '--prefill',
                '--prefill-chunk', '--reserve-gb', '--reserve-mib', '--suffix-draft', '--tp', '--turbo', '--vision',
                '--vram-reserve-mib', '--gguf-dir', '--download-model', '--setup', '--no-start')
CATALOG = {'llama': LLAMA, 'strata': STRATA, 'rust': RUST}
# Engines whose options are only the ones their executable lists (no fixed catalog), with the flags
# V-Agent already sets for them elsewhere.
DISCOVERED_ONLY = {'maya': frozenset(MAYA_MANAGED)}
ENGINES = tuple(CATALOG) + tuple(DISCOVERED_ONLY)
GROUPS = [('performance', 'Rendimiento'), ('memory', 'Memoria y caché'), ('gpu', 'GPU y CPU'),
          ('context', 'Contexto extendido (RoPE)'), ('adapters', 'Adaptadores y razonamiento'),
          ('experimental', 'Experimental'), ('extra', 'Otras opciones del motor')]
KEYS = {option['key'] for options in CATALOG.values() for option in options}

# Flags managed directly by V-Agent or meant only for CLI/debug/auth/sampling — never exposed as generic extras.
_RESERVED_FLAGS = frozenset({
    '--help', '--version', '--serve', '--model', '--models-dir', '--host', '--port', '--addr', '--open',
    '--api-key', '--api-keys', '--allowed-hosts', '--usage-log', '--max-waiting', '--max-per-key',
    '--max-tokens', '--ctx', '--ctx-size', '--max-context', '--kv', '--cache-type-k', '--cache-type-v',
    '--n-gpu-layers', '--gpu-layers', '--fit', '--fit-target', '--fit-ctx', '--ctx-checkpoints',
    '--batch-size', '--ubatch-size', '--n-cpu-moe', '--parallel', '--slots', '--mmproj', '--no-mmproj',
    '--chat-template', '--chat-template-file', '--chat-template-kwargs', '--jinja', '--no-jinja',
    '--webui', '--no-webui', '--alias', '--vram-reserve-mib', '--prompt-cache', '--draft-model', '--no-draft',
    '--gpu', '--tokens', '--max-new', '--follow', '--top-probs', '--dump-layers', '--check-batch',
    '--check-stagger', '--eos-ids', '--temperature', '--temp', '--top-k', '--top-p', '--min-p', '--seed',
    '--images', '--image-pad', '--metrics', '--verbose', '--log-disable', '--log-file', '--log-colors',
    '--log-timestamps', '--log-prefix', '--log-verbosity', '--ssl-key-file', '--ssl-cert-file',
    '--timeout', '--threads-http', '--path', '--api-prefix', '--public', '--offline', '--hf-repo',
    '--hf-file', '--hf-token', '--model-url', '--model-draft', '--lora-scaled', '--control-vector',
    '--control-vector-scaled', '--control-vector-layer-range', '--expert-profile', '--pinned-session',
})
_EXTRA_KEY_RE = re.compile(r'^flag__[a-z0-9_]{2,64}$')
# Flag lines in clap (Strata, Strata Rust: indented) and llama.cpp (column 0, short aliases like "-ctk, ") help.
# Description continuation lines are indented far deeper, so they never match.
_EXTRA_LINE_RE = re.compile(r'^\s{0,8}(?:-[a-zA-Z0-9][a-zA-Z0-9-]{0,7},\s*)*(--[a-z][a-z0-9-]{2,48})(?:,\s*--[a-z][a-z0-9-]{2,48})*(?:(?:\s+|=)(<[^>]+>|[A-Z][A-Z0-9_/.:|-]{0,20}|\[[^\]]+\]|\{[^}]+\}))?(?:\s{2,}(.+))?$')
# Matched by the filters below but known to be harmless and useful (Strata Rust keeps earlier reasoning cached).
_EXTRA_ALLOWED = frozenset({'--preserve-thinking'})
# An argument that names a file, folder, address or secret: never offered as a free-text extra.
_UNSAFE_ARG_RE = re.compile(r'(?i)(file|path|dir|fname|url|host|addr|port|key|token|secret|regex|json|cmd|prog|exe)')
# Flags that read or write files, open network services or change logging, whatever their argument says.
_UNSAFE_FLAG_RE = re.compile(r'(file|path|dir|url|host|addr|port|key|token|secret|log|save|load|dump|lora|control-vector|'
                             r'grammar|json-schema|override|chat-template|template|mmproj|model|hf-|draft|spec|slot|api|ssl|webui|'
                             r'embd|embedding|rerank|pooling|cls|image|audio|tts|vocoder|props|metrics|cache-type|rpc|'
                             # commands that print and exit, and sampling the request itself sets
                             r'list|completion|bash|usage|version|help|check|escape|interactive|conversation|prompt|'
                             r'predict|sampler|top-|min-p|typical|xtc|repeat|penalty|mirostat|dry-|temp|seed|ignore-eos|'
                             r'logit|n-probs|verbos|sampling|adaptive|infill|video|'
                             # server exposure and remote access: never switched on from a generic list
                             r'cors|mcp|tool|auth|connect|proxy|remote|public|listen|bind|tags|sse|ui-|'
                             # what V-Agent reads back (reasoning split, chat parsing) and presets that download models
                             r'reasoning|think|chat|parsing|prefill-assistant|default|fim|preset|sleep|idle)')


def discover_extra_options(kind, text):
    """Automatically surface newly added engine CLI flags from --help without requiring a V-Agent update."""
    if not text or kind not in ENGINES:
        return []
    known = set(_RESERVED_FLAGS) | DISCOVERED_ONLY.get(kind, frozenset())
    for opt in CATALOG.get(kind, []):
        known.add(opt['flag'])
        if opt.get('off'):
            known.add(opt['off'])
    found, seen = [], set()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        m = _EXTRA_LINE_RE.match(line)
        if not m:
            continue
        flag, arg_tok, desc = m.group(1), m.group(2), (m.group(3) or '').strip()
        if flag in known or flag in seen or flag.startswith('--no-'):
            continue
        if flag not in _EXTRA_ALLOWED and (_UNSAFE_FLAG_RE.search(flag[2:]) or (arg_tok and _UNSAFE_ARG_RE.search(arg_tok))):
            continue
        seen.add(flag)
        key = 'flag__' + flag[2:].replace('-', '_')
        if not _EXTRA_KEY_RE.fullmatch(key):
            continue
        # clap writes the description on the lines below the flag, deeper indented; llama.cpp continues its
        # description the same way.  Read them for the text and a "possible values" list.
        indent = len(line) - len(line.lstrip())
        more = []
        for follow in lines[index + 1:index + 8]:
            if not follow.strip() or len(follow) - len(follow.lstrip()) <= indent or _EXTRA_LINE_RE.match(follow) and \
                    len(follow) - len(follow.lstrip()) <= indent + 8:
                break
            more.append(follow.strip())
        full = ' '.join([desc] + more).strip()
        base = {'key': key, 'flag': flag, 'group': 'extra', 'label': flag, 'help': full[:180] or flag, 'supported': True}
        opt = _extra_kind(arg_tok, full)
        if opt is None:
            continue
        found.append({**base, **opt})
        if len(found) >= 32:
            break
    return found


_INT_TOKENS = frozenset({'N', 'INT', 'NUM', 'NUMBER', 'COUNT', 'SIZE', 'MIB', 'MB', 'SECONDS', 'MS'})


def _extra_kind(arg_tok, desc):
    """How the interface edits a discovered flag: switch, list of values, number or text (None: not offered)."""
    possible = re.search(r'possible values:\s*([A-Za-z0-9_.,\s-]+?)\s*(?:\]|$)', desc)
    values = [v.strip() for v in possible.group(1).split(',') if v.strip()] if possible else []
    if not arg_tok or (arg_tok.startswith('[') and arg_tok.endswith(']') and arg_tok[1:2] == '<'):
        # no value, or an optional one ("--flag [<X>]"): the flag alone turns it on
        return {'kind': 'bool'}
    listed = re.fullmatch(r'[\[{<]\s*([A-Za-z0-9_.-]+(?:\s*[|,/]\s*[A-Za-z0-9_.-]+)+)\s*[\]}>]', arg_tok)
    if listed:
        values = [v.strip() for v in re.split(r'[|,/]', listed.group(1)) if v.strip()]
    if values:
        if all(v in ('true', 'false') for v in values):
            return {'kind': 'choice', 'choices': ['true', 'false']}
        return {'kind': 'choice', 'choices': values[:24]}
    span = re.fullmatch(r'<\s*(-?\d+)\s*\.{2,3}\s*(-?\d+)\s*>', arg_tok)
    if span and int(span.group(1)) <= int(span.group(2)):
        return {'kind': 'int', 'min': int(span.group(1)), 'max': int(span.group(2))}
    if arg_tok.strip('<>').upper() in _INT_TOKENS:
        # "N" with a decimal default, or described as a factor or a share, takes decimals
        if re.search(r'default:\s*-?\d+\.\d|\b(factor|scale|scaling|ratio|share|probability|fraction)\b', desc, re.I):
            return {'kind': 'float', 'min': -1e9, 'max': 1e9}
        return {'kind': 'int', 'min': -1, 'max': 2 ** 31 - 1}
    if arg_tok.strip('<>').upper() in ('F', 'FLOAT', 'RATIO', 'FACTOR', 'SCALE'):
        return {'kind': 'float', 'min': -1e9, 'max': 1e9}
    return {'kind': 'text', 'pattern': r'[^"\r\n;|`&<>]{1,160}'}


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
    supported_opts = [o for o in options if o['supported']] + discover_extra_options(kind, text)
    return {'engine': kind, 'groups': [{'id': g, 'label': label} for g, label in GROUPS],
            'options': supported_opts, 'probed': bool(text)}


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
    unknown = {k for k in values if k not in KEYS and not _EXTRA_KEY_RE.fullmatch(str(k))}
    if unknown:
        raise ValueError('Opción del motor desconocida: ' + ', '.join(sorted(unknown)))
    result = dict(previous or {})
    for key, value in values.items():
        if key not in KEYS and _EXTRA_KEY_RE.fullmatch(str(key)):
            if value is None or value == '':
                result.pop(key, None)
            elif type(value) is bool:
                if value:
                    result[key] = True
                else:
                    result.pop(key, None)
            elif isinstance(value, (int, float)):
                if value != value or value in (float('inf'), float('-inf')):
                    raise ValueError(f'Valor no válido para «{key}».')
                result[key] = value
            else:
                text_val = str(value).strip()
                if not text_val:
                    result.pop(key, None)
                elif not re.fullmatch(r'[^"\r\n;|`&<>]{1,160}', text_val):
                    raise ValueError(f'Valor no válido para «{key}».')
                else:
                    result[key] = text_val
            continue
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


def _arch_ok(option, arch):
    archs = option.get('archs')
    return not archs or not arch or str(arch).lower() in archs


def arguments(kind, values, text, arch=None):
    """Command-line arguments for the saved options this executable supports (others are skipped)."""
    args = []
    for option in CATALOG.get(kind, []) + discover_extra_options(kind, text):
        value = (values or {}).get(option['key'])
        if value is None or not supported(option, text) or not _arch_ok(option, arch):
            continue
        if option['key'].startswith('flag__') and option['kind'] in ('int', 'float') and isinstance(value, str):
            try:
                value = float(value) if option['kind'] == 'float' else int(value)
            except ValueError:
                continue
        if option['key'].startswith('flag__') and option['kind'] == 'choice' and type(value) is bool:
            value = 'true' if value else 'false'
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
    key_set = set(keys)
    options = [o for o in CATALOG.get(kind, []) if o['key'] in key_set]
    flags = {o['flag'] for o in options} | {o['off'] for o in options if o.get('off')}
    valueless = {o['flag'] for o in options if o['kind'] in ('bool', 'switch')} | {o['off'] for o in options if o.get('off')}
    for k in key_set:
        if _EXTRA_KEY_RE.fullmatch(str(k)):
            flags.add('--' + k[6:].replace('_', '-'))
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


def apply(kind, args, values, text, previous=(), arch=None):
    """For a saved argument list (Strata configs): drop what V-Agent applied last time (`previous` keys)
    and what is set now, then add the current values. Returns (args, keys applied now) so the caller can
    remember them; flags the config had on its own and the user never touched are kept."""
    values = values or {}
    all_opts = CATALOG.get(kind, []) + discover_extra_options(kind, text)
    applied = [o['key'] for o in all_opts if values.get(o['key']) is not None and supported(o, text) and _arch_ok(o, arch)]
    return without(kind, args, set(previous) | set(applied)) + arguments(kind, values, text, arch=arch), applied


def conflicts(kind, values, kv):
    """A combination the engine refuses, said before it is started; None when fine."""
    if kind == 'llama' and (values or {}).get('flash_attn') == 'off' and str(kv or '').startswith(('q', 'iq')):
        return ('La caché KV cuantizada (' + str(kv) + ') necesita Flash Attention: ponlo en Automático o Activado en '
                'Ajustes avanzados del motor, o usa la caché FP16.')
    return None
