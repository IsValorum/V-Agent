"""Exercise import, listing and export for all engines without loading model weights."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',required=True)
    parser.add_argument('--engine-state',required=True,help='Existing engine-updates/active.json (read only).')
    args=parser.parse_args()
    model=str(Path(args.model).resolve())
    with tempfile.TemporaryDirectory(prefix='v-agent-transfer-') as tmp:
        root=Path(tmp);(root/'engine-updates').mkdir()
        shutil.copyfile(args.engine_state,root/'engine-updates'/'active.json')
        api_port,engine_port=free_port(),free_port()
        env=dict(os.environ,STRATA_AGENT_DATA=tmp,V_AGENT_NO_AUTO_UPDATE='1',STRATA_HARNESS_PORT=str(api_port),PYTHONPATH='agent;tools;.')
        boot=("import runtime_paths;runtime_paths.bootstrap();import agent,desktop_runtime;"
              f"agent.ENGINE_PORT={engine_port};agent.STRATA='http://127.0.0.1:{engine_port}';"
              "desktop_runtime.install(agent);agent.main()")
        def request(path,body=None):
            data=None if body is None else json.dumps(body).encode()
            req=urllib.request.Request(f'http://127.0.0.1:{api_port}'+path,data=data,
                                       headers={'Content-Type':'application/json','Origin':'http://tauri.localhost'})
            with urllib.request.urlopen(req,timeout=90) as response:return json.load(response)
        for engine in ('strata','rust','llama'):
            (root/'engines.json').write_text(json.dumps({'active':engine,'llama':{'variant':'cuda','gpu_layers':'auto'},'api':{}}),encoding='utf8')
            proc=subprocess.Popen([sys.executable,'-c',boot],cwd=Path(__file__).resolve().parents[2],env=env,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(45):
                    try:request('/api/access');break
                    except OSError:
                        if proc.poll() is not None:raise RuntimeError('The isolated backend stopped.')
                        time.sleep(1)
                else:raise RuntimeError('The isolated backend did not start.')
                imported=request('/api/harness/external/import',{'items':[{'path':model,'name':'LFM test',
                    'sampling':{'temperature':0.42,'repetition_penalty':1.0},'context':24576,'kv':'fp16'}]})['results'][0]
                if imported.get('error'):raise RuntimeError(engine+': '+imported['error'])
                models=request('/api/models')['data']
                matches=[entry for entry in models if entry['id']==imported['id']]
                assert len(matches)==1,(engine,imported,[(m['id'],m.get('path')) for m in models])
                same=[entry for entry in models if os.path.normcase(entry.get('path') or '')==os.path.normcase(model)]
                assert len(same)==1,(engine,len(same))
                pref=matches[0]['preferences']
                assert pref['sampling']['temperature']==0.42 and pref['context']==24576 and pref['kv']=='fp16',(engine,pref)
                exported=request('/api/harness/external/export',{'model':imported['id'],'target':'file'})['file']['models'][0]
                assert exported['context']==24576 and exported['sampling']['temperature']==0.42,(engine,exported)
                print(json.dumps({'engine':engine,'id':imported['id'],'visible_count':len(same),'exported':True}),flush=True)
            finally:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                else:proc.terminate()
                proc.wait(timeout=10)


if __name__=='__main__':main()
