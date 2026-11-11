"""Real Ling Tiny tool tests in isolated per-chat folders; no shell or HF writes."""
import json
import os
from pathlib import Path
import sys
import urllib.request
import uuid

BASE='http://127.0.0.1:19381'
# Path to a small GGUF on your machine (the original runs used Ling 3 Tiny IQ4_XS).
MODEL=os.environ.get('V_AGENT_TEST_MODEL') or sys.exit('Set V_AGENT_TEST_MODEL to the path of a small GGUF model.')
def post(path,body,timeout=300):
    return urllib.request.urlopen(urllib.request.Request(BASE+path,json.dumps(body).encode(),{'Content-Type':'application/json','Origin':BASE}),timeout=timeout)
def main():
    with post('/api/harness/configure',{'engine':'llama','variant':'cuda','gpu_layers':'all'}) as response:json.load(response)
    with post('/api/models/register',{'path':MODEL}) as response:model=json.load(response)['model']['id']
    cases=[('light','run',{'files':True},'Create profile-test.txt with exactly LIGHT OK, then read it using fs_read and report the content.'),
           ('balanced','run',{'files':True},'Create calculator.py with a function add(a,b) that returns a - b. Then use fs_edit to replace a - b with a + b. Finally use code_check to check syntax. Do each operation with a tool, then finish.'),
           ('advanced','ask',{'sys':True},'Call pc__sys_info once and report the CPU model. Do not call any other tool.')]
    report=[]
    try:
        with post('/api/load',{'model':model,'context':4096},600) as response:assert json.load(response)['loaded']
        for profile,permission,functions,prompt in cases:
            events=[];body={'model':model,'conversation_id':'ling-'+uuid.uuid4().hex,'messages':[{'role':'user','content':prompt}],
              'functions':functions,'effort':'none','sampling':{'temperature':0,'max_tokens':512},'rounds':8,'agent_profile':profile,'permission_mode':permission}
            with post('/api/chat',body) as response:
                for line in response:
                    if not line.startswith(b'data: '):continue
                    try:event=json.loads(line[6:])
                    except ValueError:continue
                    events.append(event)
                    if event.get('type')=='approval':
                        with post('/api/harness/approval',{'id':event['id'],'allowed':True}) as approved:json.load(approved)
            results=[e for e in events if e.get('type')=='tool_result'];names=[e['name'] for e in results]
            Path('build/ling-'+profile+'-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
            print([(e['name'],e.get('ok'),str(e.get('result',''))[:260]) for e in results],flush=True)
            assert results and all(e.get('ok') for e in results),events[-4:]
            assert len(results)<=6,'Unexpected repetition: '+str(names)
            if profile=='balanced':assert {'pc__fs_write','pc__fs_edit','pc__code_check'}<=set(names),names
            elif profile=='advanced':assert sum(e.get('type')=='approval' for e in events)==1
            else:assert {'pc__fs_write','pc__fs_read'}<=set(names)
            report.append({'profile':profile,'tools':names,'approvals':sum(e.get('type')=='approval' for e in events),'errors':0})
            Path('build/ling-'+profile+'-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps(report[-1]),flush=True)
        Path('build/ling-profiles-report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    finally:
        with post('/api/unload',{}) as response:json.load(response)

if __name__=='__main__':main()
