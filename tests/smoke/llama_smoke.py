"""Real bundled llama.cpp smoke test with a disposable tiny GGUF, not user weights."""
import json
from pathlib import Path
import urllib.request
import uuid
BASE='http://127.0.0.1:19380'
MODEL=Path(__file__).resolve().parents[2]/'.test-models'/'SmolLM2-135M-Instruct-Q4_K_M.gguf'
def get(path):
    with urllib.request.urlopen(BASE+path,timeout=20) as r:return json.load(r)
def post(path,body):
    req=urllib.request.Request(BASE+path,json.dumps(body).encode(),{'Content-Type':'application/json','Origin':BASE})
    return urllib.request.urlopen(req,timeout=90)
def main():
    with post('/api/harness/configure',{'engine':'llama','variant':'cpu','gpu_layers':'0'}) as r:json.load(r)
    with post('/api/models/register',{'path':str(MODEL)}) as r:model=json.load(r)['model']['id']
    try:
        with post('/api/context',{'model':model,'tokens':2048}) as r:assert not json.load(r)['reloaded']
        assert not get('/api/harness/state')['loaded_model']
        with post('/api/load',{'model':model,'context':2048}) as r:assert json.load(r)['loaded']
        assert get('/api/stats')['context_usage']['limit']==2048
        with post('/api/chat',{'model':model,'conversation_id':'qa-llama-'+uuid.uuid4().hex,'messages':[{'role':'user','content':'Say hello.'}],'effort':'none','functions':{},'sampling':{'max_tokens':12,'temperature':0}}) as r:stream=r.read().decode()
        assert '"type": "content"' in stream,stream[-1000:]
        assert get('/api/stats')['context_usage']['used']>0
        with post('/api/context',{'model':model,'tokens':4096}) as r:assert json.load(r)['reloaded']
        assert get('/api/stats')['context_usage']['limit']==4096
        print(json.dumps({'frozen_real_generation':True,'context_save_does_not_load':True,'context_reload':4096,'context_usage':get('/api/stats')['context_usage']}))
    finally:
        with post('/api/unload',{}) as r:json.load(r)
        with post('/api/harness/configure',{'engine':'strata'}) as r:json.load(r)
if __name__=='__main__':main()
