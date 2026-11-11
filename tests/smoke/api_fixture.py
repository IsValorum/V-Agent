"""Local-only API transport + real MCP roundtrip; no external account or model."""
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import urllib.request
import urllib.error
import uuid
BASE='http://127.0.0.1:19381'
requests=[]
class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        raw=b'{"data":[{"id":"fixture-model"}]}';self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
        assert self.headers.get('Authorization')=='Bearer fixture-only-key'
        assert 'strata_tool_drafts' not in body and 'chat_template_kwargs' not in body
        assert not any(m.get('role')=='system' for m in body['messages'])
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        if len(requests)==1:
            packet={'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call-fixture','type':'function','function':{'name':'pc__fs_list','arguments':'{"path":"."}'}}]},'finish_reason':'tool_calls'}]}
        else:
            assert any(m['role']=='tool' for m in body['messages'])
            packet={'choices':[{'delta':{'content':'API y herramienta verificadas.'},'finish_reason':'stop'}],'usage':{'prompt_tokens':123,'completion_tokens':5,'total_tokens':128}}
        self.wfile.write(('data: '+json.dumps(packet)+'\n\ndata: [DONE]\n\n').encode())

def post(path,body,timeout=40):
    req=urllib.request.Request(BASE+path,json.dumps(body).encode(),{'Content-Type':'application/json','Origin':BASE})
    try:return urllib.request.urlopen(req,timeout=timeout)
    except urllib.error.HTTPError as error:raise RuntimeError(error.read().decode()) from error

def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with post('/api/harness/configure',{'engine':'api','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only-key'}) as r:json.load(r)
        with post('/api/harness/connect',{}) as r:state=json.load(r)
        assert state['api']['has_key'] and 'api_key' not in state['api']
        with post('/api/load',{'model':'api--fixture-model'}) as r:json.load(r)
        with post('/api/chat',{'model':'api--fixture-model','conversation_id':'qa-api-'+uuid.uuid4().hex,'messages':[{'role':'user','content':'Inspect the workspace.'}],'functions':{'files':True},'effort':'none','sampling':{'max_tokens':64}}) as r:stream=r.read().decode()
        assert 'API y herramienta verificadas.' in stream and 'tool_result' in stream,stream[-2000:]
        assert len(requests)==2,len(requests)
        from pathlib import Path
        assert b'fixture-only-key' not in Path(state['data_dir']).joinpath('credentials/api-key.dpapi').read_bytes()
        print(json.dumps({'api_stream':True,'real_mcp_roundtrip':True,'no_strata_parameters_to_api':True,'no_hidden_system_prompt':True,'encrypted_key':True}))
        with post('/api/unload',{}) as r:json.load(r)
        with post('/api/harness/configure',{'engine':'strata'}) as r:json.load(r)
    finally:
        try:
            with post('/api/unload',{}) as r:json.load(r)
            with post('/api/harness/configure',{'engine':'strata'}) as r:json.load(r)
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
