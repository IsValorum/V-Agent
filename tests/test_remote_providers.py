"""No external key/account: real HTTP/SSE at the provider boundary."""
import json,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path[:0]=['agent','.']
import engine_manager
from remote_protocols import claude_payload,ClaudeStream,model_info,openai_payload

class RemoteProvidersTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(engine_manager,'DATA_ROOT',Path(self.tmp.name));self.patch.start();self.manager=engine_manager.EngineManager()
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def test_connections_isolate_keys_and_models_and_reload(self):
  m=self.manager
  a=m.configure({'engine':'api','protocol':'openai','base_url':'https://one.example/custom/v2','api_key':'secret-one','new_connection':True,'name':'One'})['api']['id']
  m.configure({'engine':'api','protocol':'anthropic','base_url':'https://two.example/v1','api_key':'secret-two','new_connection':True,'name':'Two'})
  self.assertEqual(m.key(),'secret-two');self.assertNotIn('secret',m.file.read_text());self.assertNotIn('api_key',m.snapshot()['api'])
  m.configure({'engine':'api','connection_id':a});self.assertEqual(m.key(),'secret-one');self.assertEqual(m.url('/models'),'https://one.example/custom/v2/models')
  reloaded=engine_manager.EngineManager();self.assertEqual(len(reloaded.snapshot()['connections']),2);self.assertEqual(reloaded.key(),'secret-one')
  m.configure({'engine':'api','connection_id':a,'base_url':'https://changed.example/v1'});self.assertEqual(m.key(),'')
 def test_failed_validation_preserves_connection(self):
  m=self.manager;m.configure({'engine':'api','base_url':'https://one.example/v1','api_key':'keep'})
  before=json.loads(m.file.read_text())
  with self.assertRaises(ValueError):m.configure({'engine':'api','base_url':'https://bad.example','timeout':2,'api_key':'bad'})
  self.assertEqual(m.settings,before);self.assertEqual(m.key(),'keep')
 def test_context_never_guesses_from_names(self):
  self.assertIsNone(model_info({'id':'claude-future-million'}, {})['context'])
  info=model_info({'id':'m','max_input_tokens':200000,'max_tokens':64000},{'m':{'context':100000}})
  self.assertEqual((info['context'],info['reported_context'],info['context_source']),(100000,200000,'manual'))
 def test_official_openai_limits_and_optional_sampling(self):
  payload={'model':'test','max_tokens':256,'temperature':.6,'top_p':.95,'seed':0,'frequency_penalty':0,'presence_penalty':0}
  safe=openai_payload(payload,'https://api.openai.com/v1')
  self.assertEqual(safe,{'model':'test','max_completion_tokens':256})
  compatible=openai_payload(payload,'https://compatible.example/v1',True)
  self.assertEqual(compatible['max_tokens'],256);self.assertEqual(compatible['temperature'],.6);self.assertNotIn('seed',compatible)
 def test_claude_payload_tool_history_images_and_removed_parameters(self):
  payload={'model':'claude-test','max_tokens':0,'temperature':.4,'top_p':.9,'messages':[{'role':'system','content':'Date only.'},{'role':'user','content':[{'type':'text','text':'inspect'},{'type':'image_url','image_url':{'url':'data:image/png;base64,YQ=='}}]},{'role':'assistant','content':None,'tool_calls':[{'id':'t1','function':{'name':'pc__fs_list','arguments':'{"path":"."}'}}]},{'role':'tool','tool_call_id':'t1','content':'real output'}],'tools':[{'function':{'name':'pc__fs_list','parameters':{'type':'object','properties':{'path':{'type':'string'}}}}}],'tool_choice':'auto'}
  body=claude_payload(payload,'2026-10-21',4096)
  self.assertEqual(body['max_tokens'],4096);self.assertNotIn('temperature',body);self.assertNotIn('top_p',body)
  self.assertEqual(body['messages'][-1]['content'][0]['tool_use_id'],'t1');self.assertEqual(body['messages'][1]['content'][0]['input'],{'path':'.'})
  self.assertEqual(body['messages'][0]['content'][1]['source']['type'],'base64');self.assertEqual(body['tools'][0]['input_schema']['type'],'object')
 def test_claude_wire_auth_pagination_stream_and_context(self):
  requests=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    requests.append((self.path,dict(self.headers),None));second='after_id=' in self.path
    raw=json.dumps({'data':[{'id':'c2' if second else 'c1','max_input_tokens':120000,'max_tokens':4096}],'has_more':not second,'last_id':'c2' if second else 'c1'}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,dict(self.headers),body))
    self.send_response(200);self.end_headers()
    events=[{'type':'message_start','message':{'usage':{'input_tokens':12,'cache_read_input_tokens':3,'output_tokens':0}}},{'type':'content_block_start','index':2,'content_block':{'type':'tool_use','id':'call1','name':'pc__fs_list','input':{}}},{'type':'content_block_delta','index':2,'delta':{'type':'input_json_delta','partial_json':'{"path":"."}'}},{'type':'message_delta','delta':{'stop_reason':'tool_use'},'usage':{'output_tokens':5}},{'type':'message_stop'}]
    for event in events:self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode())
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  class Control:
   cancelled=threading.Event()
   def attach(self,*args):pass
   def detach(self,*args):pass
  try:
   m=self.manager;m.configure({'engine':'api','protocol':'anthropic','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'local-test'})
   m.connect();self.assertEqual(len(m.remote_models),2);self.assertEqual(requests[0][1]['Authorization'],'Bearer local-test')
   identifier=m.remote_identifier(m.remote_models[0]);m.load({'id':identifier},None,None)
   output=b''.join(m.stream({'model':'c1','messages':[{'role':'user','content':'inspect'}],'temperature':.9},Control())).decode()
   self.assertIn('tool_calls',output);self.assertIn('[DONE]',output);self.assertEqual(requests[-1][0],'/v1/messages');self.assertNotIn('temperature',requests[-1][2]);self.assertEqual(m.last_usage['prompt_tokens'],15)
   m.remote_context(identifier,60000);self.assertEqual(m.metrics()['engine']['max_context'],60000);m.remote_context(identifier,None);self.assertEqual(m.metrics()['engine']['max_context'],120000)
   self.assertTrue(m.release_remote()['engine_online'])
  finally:server.shutdown();server.server_close()
 def test_stream_errors_are_failures_not_empty_success(self):
  with self.assertRaises(ValueError):ClaudeStream().packet({'type':'error','error':{'message':'overloaded'}})
if __name__=='__main__':unittest.main()
