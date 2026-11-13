"""Conservative pre-load memory estimates from GGUF headers, without reading weights."""
import math,subprocess,time,threading
from pathlib import Path
from gguf_catalog import inspect
from load_settings import effective
GIB=2**30
_hardware=(0,{})
_hw_lock=threading.Lock()
def hardware():
    global _hardware
    with _hw_lock:
        if time.monotonic()-_hardware[0]<15:return _hardware[1]
        import psutil
        ram=psutil.virtual_memory();result={'ram_available':ram.available,'ram_total':ram.total,'gpu_available':None,'gpu_total':None}
        try:
            r=subprocess.run(['nvidia-smi','--query-gpu=memory.free,memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            parts=r.stdout.splitlines()[0].split(',');result.update(gpu_available=int(parts[0])*2**20,gpu_total=int(parts[1])*2**20)
        except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):pass
        _hardware=(time.monotonic(),result);return result

_KV_BPE={'fp16':(2,2),'f16':(2,2),'bf16':(2,2),'q8_0':(34/32,34/32),'int8':(1,1),'q4_0':(18/32,18/32),'int8k':(1,2),'k8v4':(1,18/32)}

def _meta_num(meta,arch,key,default=0):
    val=meta.get(arch+'.'+key,default)
    return val if isinstance(val,(int,float)) and not isinstance(val,bool) else default

def _layer_kv_heads(meta,arch,layers,kvheads,interval):
    recurrent=meta.get(arch+'.attention.recurrent_layers')
    if isinstance(kvheads,list):
        return [float(h) if isinstance(h,(int,float)) and not isinstance(h,bool) and h>0 else 0.0 for h in kvheads[:layers]]+[0.0]*max(0,layers-len(kvheads))
    h=float(kvheads)
    if h<=0:return [0.0]*layers
    if isinstance(recurrent,list) and len(recurrent)>=layers:
        return [0.0 if recurrent[i] else h for i in range(layers)]
    if interval>0:
        if layers<interval:return [h]+[0.0]*(layers-1)
        return [h if (i+1)%interval==0 else 0.0 for i in range(layers)]
    return [h]*layers

def _swa_layer_mask(meta,arch,layers,layer_heads,window):
    if window<=0:return [False]*layers
    pattern=meta.get(arch+'.attention.sliding_window_pattern')
    if isinstance(pattern,list) and pattern:
        return [bool(pattern[i%len(pattern)]) for i in range(layers)]
    pos=[h for h in layer_heads if h>0]
    if len(set(pos))>1:
        low=min(pos)
        return [h>low for h in layer_heads]
    if arch.startswith(('gemma4','gemma3')):
        return [(i+1)%6!=0 for i in range(layers)]
    if arch.startswith('gemma2'):
        return [i%2==0 for i in range(layers)]
    return [True]*layers

def _recurrent_floats(meta,arch,embed,heads):
    inner=_meta_num(meta,arch,'ssm.inner_size');size=_meta_num(meta,arch,'ssm.state_size')
    groups=_meta_num(meta,arch,'ssm.group_count');kernel=_meta_num(meta,arch,'ssm.conv_kernel')
    if inner and size:
        return inner*size+max(0,kernel-1)*(inner+2*groups*size)
    kda=_meta_num(meta,arch,'kda.head_dim')
    if kda and heads:
        return heads*kda*kda+3*max(0,kernel-1)*heads*kda
    l_cache=int(_meta_num(meta,arch,'shortconv.l_cache'))
    if l_cache>1 and embed:
        return (l_cache-1)*embed
    return 0

def estimate_facts(facts,context,kv,settings,kind='llama',gpu_layers='auto',caps=None):
    m=facts['metadata'];a=str(m.get('general.architecture',''));v=effective(settings,caps);slots=v['parallel'] if kind=='llama' else 1
    def num(key,default=0):return _meta_num(m,a,key,default)
    layers=int(num('block_count'));embed=int(num('embedding_length'));heads=num('attention.head_count');kvheads=m.get(a+'.attention.head_count_kv',heads)
    lora=num('attention.kv_lora_rank');rope=num('rope.dimension_count')
    kd=num('attention.key_length') or num('attention.key_length_mla') or ((lora+rope) if lora else (embed/heads if heads else 0))
    vd=num('attention.value_length') or num('attention.value_length_mla') or kd
    kd_swa=num('attention.key_length_swa') or kd;vd_swa=num('attention.value_length_swa') or num('attention.key_length_swa') or vd
    kbpe,vbpe=_KV_BPE.get(kv,(2,2))
    per_layer_rec=_recurrent_floats(m,a,embed,heads)
    kv_defined=(a+'.attention.head_count_kv' in m) or bool(heads)
    interval=int(num('full_attention_interval'))
    layer_heads=_layer_kv_heads(m,a,layers,kvheads,interval) if (layers and kv_defined) else [0.0]*layers
    has_attn=any(h>0 for h in layer_heads)
    notes=[];cache=None;state=0
    if layers and ((has_attn and kd and vd) or (not has_attn and per_layer_rec>0)):
        shared_kv=max(0,int(num('attention.shared_kv_layers')))
        kv_limit=max(0,layers-shared_kv)
        window=max(0,int(num('attention.sliding_window')))
        swa_mask=_swa_layer_mask(m,a,layers,layer_heads,window)
        full_cells=math.ceil(context/256)*256
        swa_cells=min(full_cells,math.ceil((window+v['batch'])/256)*256) if window else full_cells
        used_swa=False;per_slot_bytes=0
        for i in range(kv_limit):
            h=layer_heads[i]
            if h<=0:continue
            if swa_mask[i]:
                per_slot_bytes+=swa_cells*h*(kd_swa*kbpe+vd_swa*vbpe);used_swa=True
            else:
                per_slot_bytes+=full_cells*h*(kd*kbpe+vd*vbpe)
        cache=slots*per_slot_bytes
        rec_list=m.get(a+'.attention.recurrent_layers')
        if isinstance(rec_list,list) and len(rec_list)>=layers:
            recurrent=sum(1 for flag in rec_list[:layers] if flag)
        elif layer_heads:
            recurrent=sum(1 for h in layer_heads if h<=0)
        else:
            recurrent=layers
        if recurrent>0 and (has_attn or interval>0):
            notes.append('Arquitectura híbrida: KV solo para las capas de atención completa.')
        if recurrent>0 and per_layer_rec>0:
            state=recurrent*per_layer_rec*4*slots*(1+v['checkpoints'])
        if used_swa:notes.append('Caché SWA acotada a la ventana deslizante del modelo.')
    else:notes.append('No hay metadatos suficientes para estimar la caché KV.')
    weights=int(facts.get('dense_bytes',0)+facts.get('expert_bytes',0))
    buffers=max(96*2**20,96*2**20+v['ubatch']*max(embed,1024)*32+v['batch']*max(embed,1024)*4)
    if kind=='strata':
        buffers=max(buffers,int((caps or {}).get('prompt_batch',1024)*1.4*2**20))
        # Expert streaming differs fundamentally from all-weights-on-GPU llama.cpp.
        gpu_weights=int(facts.get('dense_bytes',weights));notes.append('Strata mueve expertos entre RAM y VRAM; la caché de expertos añade consumo variable.')
    else:
        ratio=0 if str(gpu_layers)=='0' else min(1,max(0,int(gpu_layers))/max(1,layers)) if str(gpu_layers).isdigit() else 1
        gpu_weights=weights*ratio
        moe=0 if v['auto'] else v.get('cpu_moe',0)
        if moe and layers and facts.get('expert_bytes'):
            # --n-cpu-moe keeps the experts of the first N layers in RAM.
            gpu_weights=max(0,gpu_weights-facts['expert_bytes']*min(1,moe/layers))
            notes.append('Parte de los expertos MoE se queda en la RAM (--n-cpu-moe).')
    cpu=str(gpu_layers)=='0';total=None if cache is None else weights+cache+state+buffers
    gpu=None if total is None else 0 if cpu else gpu_weights+cache+state+buffers
    if m.get('split.count',1)>1:notes.append('Archivo GGUF dividido: estimación parcial de pesos.');total=None;gpu=None
    notes.append('Buffers aproximados; visión, draft, controladores y asignaciones temporales pueden añadir memoria.')
    return {'estimated':True,'weights':weights,'kv':cache,'recurrent':state,'buffers':buffers,'total':total,'gpu_full_offload':gpu,'cpu_weights':weights-gpu_weights,'context_per_slot':context,'slots':slots,'kv_type':kv,'effective':v,'notes':notes,'architecture':a,
            'block_count':layers,'moe':bool(facts.get('expert_bytes'))}

def estimate(model,context,kv,settings,kind,layers,caps=None):
    result=estimate_facts(inspect(Path(model['path'])),context,kv,settings,kind,layers,caps)
    result['hardware']=hardware();return result
