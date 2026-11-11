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

def estimate_facts(facts,context,kv,settings,kind='llama',gpu_layers='auto',caps=None):
    m=facts['metadata'];a=str(m.get('general.architecture',''));v=effective(settings,caps);slots=v['parallel'] if kind=='llama' else 1
    def num(key,default=0):
        x=m.get(a+'.'+key,default)
        return x if isinstance(x,(int,float)) and not isinstance(x,bool) else default
    layers=int(num('block_count'));embed=int(num('embedding_length'));heads=num('attention.head_count');kvheads=m.get(a+'.attention.head_count_kv',heads)
    kd=num('attention.key_length',embed/heads if heads else 0);vd=num('attention.value_length',kd)
    bpe={'fp16':2,'f16':2,'bf16':2,'q8_0':34/32,'int8':1,'q4_0':18/32,'int8k':1.5,'k8v4':.78125}.get(kv,2)
    notes=[];cache=None;state=0
    if layers and kd and vd and kvheads:
        if isinstance(kvheads,list):headsum=sum(float(h) for h in kvheads if isinstance(h,(int,float)) and h>0)
        else:
            interval=int(num('full_attention_interval'))
            attention_layers=max(1,layers//interval) if interval else layers
            headsum=attention_layers*float(kvheads)
            if interval:notes.append('Arquitectura híbrida: KV solo para las capas de atención completa.')
        cache=math.ceil(context/256)*256*slots*headsum*(kd+vd)*bpe
        interval=int(num('full_attention_interval'));inner=num('ssm.inner_size');size=num('ssm.state_size');groups=num('ssm.group_count');kernel=num('ssm.conv_kernel')
        if inner and size:
            recurrent=max(0,layers-(layers//interval if interval else layers))
            # Gated delta recurrent matrix plus convolution history; checkpoints copy recurrent state.
            matrix=inner*size;conv=max(0,kernel-1)*(inner+2*groups*size)
            state=recurrent*(matrix+conv)*4*slots*(1+v['checkpoints'])
        if num('attention.sliding_window'):notes.append('KV de ventana estimada a contexto completo: cota conservadora.')
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
