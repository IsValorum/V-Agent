"""Small shared model facts. Never read weight data or decode tokenizer vocabulary."""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from gguf_reader import GGUFFile
from runtime_paths import DATA_ROOT
from ui_preferences import atomic_json

_memory={}
_lock=threading.RLock()
_expert=re.compile(r'\.ffn_(gate|up|down|gate_up)_exps\.weight$')

def inspect(path):
    path=Path(path).resolve();stat=path.stat()
    key=[os.path.normcase(str(path)),stat.st_size,stat.st_mtime_ns,3]
    ident=hashlib.sha256(key[0].encode()).hexdigest()
    with _lock:
        item=_memory.get(ident)
        if item and item['key']==key:return item['facts']
        target=DATA_ROOT/'cache/gguf-catalog'/f'{ident}.json'
        try:
            item=json.loads(target.read_text(encoding='utf8'))
            if item['key']==key and isinstance(item['facts'].get('metadata'),dict):
                _memory[ident]=item;return item['facts']
        except (OSError,ValueError,KeyError,TypeError,AttributeError):pass
        gguf=GGUFFile(path,skip_tokenizer=True);meta=gguf.metadata
        arch=str(meta.get('general.architecture') or '')
        keys=['general.architecture','general.name','general.basename','general.size_label','split.count']
        keys += [arch+'.'+name for name in ('context_length','block_count','expert_count','expert_used_count',
                 'nextn_predict_layers','embedding_length','rope.dimension_count','attention.key_length',
                 'attention.key_length_swa','attention.value_length','attention.value_length_swa',
                 'attention.key_length_mla','attention.value_length_mla','attention.kv_lora_rank',
                 'attention.head_count','attention.head_count_kv','attention.sliding_window',
                 'attention.sliding_window_pattern','attention.shared_kv_layers','attention.recurrent_layers',
                 'full_attention_interval','shortconv.l_cache','kda.head_dim',
                 'ssm.conv_kernel','ssm.state_size','ssm.group_count','ssm.time_step_rank','ssm.inner_size')]
        ordered=sorted(gguf.tensors,key=lambda t:t.offset)
        split_count=meta.get('split.count',1)
        data_end=max(0,stat.st_size-gguf.data_start) if not isinstance(split_count,int) or split_count<=1 else None
        dense=experts=0
        for idx,tensor in enumerate(ordered):
            size=tensor.expected_bytes()
            if size is None:
                end=ordered[idx+1].offset if idx+1<len(ordered) else data_end
                size=max(0,end-tensor.offset) if end is not None else 0
            if _expert.search(tensor.name):experts+=size
            else:dense+=size
        facts={'metadata':{k:meta[k] for k in keys if k in meta},'types':gguf.by_type(),
               'head':any('nextn' in t.name or 'mtp.' in t.name for t in gguf.tensors),
               'dense_bytes':dense,'expert_bytes':experts}
        item={'key':key,'facts':facts};_memory[ident]=item
        try:target.parent.mkdir(parents=True,exist_ok=True);atomic_json(target,item)
        except OSError:pass  # A read-only cache must not hide installed models.
        return facts
