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
  ds_off=openai_payload({'model':'deepseek-flash','reasoning_effort':'none'},'https://api.deepseek.com/v1')
  self.assertEqual(ds_off,{'model':'deepseek-flash','thinking':{'type':'disabled'}})
  ds_max=openai_payload({'model':'deepseek-flash','reasoning_effort':'xhigh','messages':[{'role':'assistant','content':'','tool_calls':[{'id':'c1'}]}]},'https://api.deepseek.com/v1')
  self.assertEqual(ds_max['thinking'],{'type':'enabled'});self.assertEqual(ds_max['reasoning_effort'],'max')
  self.assertEqual(ds_max['messages'][0]['reasoning_content'],'')
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
   m.connect();self.assertEqual(len(m.remote_models),2);get_h={k.lower():v for k,v in requests[0][1].items()};self.assertEqual(get_h['x-api-key'],'local-test');self.assertEqual(get_h['anthropic-version'],'2023-06-01');self.assertTrue(get_h['user-agent'].startswith('V-Agent/'));self.assertEqual(get_h['accept-encoding'],'identity')
   identifier=m.remote_identifier(m.remote_models[0]);m.load({'id':identifier},None,None)
   output=b''.join(m.stream({'model':'c1','messages':[{'role':'user','content':'inspect'}],'temperature':.9},Control())).decode()
   stream_headers=requests[-1][1]
   self.assertEqual(stream_headers['x-api-key'],'local-test');self.assertEqual(stream_headers['anthropic-version'],'2023-06-01');self.assertTrue(stream_headers['User-Agent'].startswith('V-Agent/'))
   self.assertEqual(stream_headers['Accept'],'text/event-stream');self.assertEqual(stream_headers['Cache-Control'],'no-cache');self.assertEqual(stream_headers['Accept-Encoding'],'identity');self.assertFalse(any(k.lower().startswith('x-stainless-') for k in stream_headers))
   self.assertIn('tool_calls',output);self.assertIn('[DONE]',output);self.assertEqual(requests[-1][0],'/v1/messages');self.assertNotIn('temperature',requests[-1][2]);self.assertEqual(m.last_usage['prompt_tokens'],15)
   m.remote_context(identifier,60000);self.assertEqual(m.metrics()['engine']['max_context'],60000);self.assertEqual(m.loaded,identifier);m.remote_context(identifier,None);self.assertEqual(m.metrics()['engine']['max_context'],120000)
   restarted=engine_manager.EngineManager()
   self.assertTrue(restarted.online);self.assertEqual(restarted.loaded,identifier)
   self.assertTrue(m.release_remote()['engine_online'])
   restarted_after_release=engine_manager.EngineManager()
   self.assertTrue(restarted_after_release.online);self.assertIsNone(restarted_after_release.loaded)
  finally:server.shutdown();server.server_close()
 def test_no_output_limit_sends_the_models_maximum_and_falls_back_when_refused(self):
  # "No limit" (max_tokens 0) must not leave the provider's small default in place: reasoning used it up
  # and the reply ended empty. When the provider refuses the value, the request is repeated without it.
  requests=[];refuse={'on':False}
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    raw=json.dumps({'data':[{'id':'known','context_length':200000,'max_tokens':100000},{'id':'unknown','context_length':1048576}]}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
    if refuse['on'] and 'max_tokens' in body:
     raw=json.dumps({'error':{'message':'max_tokens must be less than or equal to 8192'}}).encode()
     self.send_response(400);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
    self.send_response(200);self.end_headers()
    self.wfile.write(b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  class Control:
   cancelled=threading.Event()
   def attach(self,*args):pass
   def detach(self,*args):pass
  try:
   m=self.manager;m.configure({'engine':'api','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'local-test'});m.connect()
   ids={model['id']:m.remote_identifier(model) for model in m.remote_models}
   def ask(model,limit=0):
    m.load({'id':ids[model]},None,None)
    return b''.join(m.stream({'model':model,'messages':[{'role':'user','content':'x'*3500}],'max_tokens':limit},Control())).decode()
   ask('known');self.assertEqual(requests[-1]['max_tokens'],100000)
   ask('unknown');self.assertEqual(requests[-1]['max_tokens'],32000)  # OpenCode's fallback when the provider does not say
   ask('known',2048);self.assertEqual(requests[-1]['max_tokens'],2048)  # a limit the user set is kept
   refuse['on']=True;before=len(requests)
   self.assertIn('"ok"',ask('unknown'))
   self.assertEqual([('max_tokens' in r) for r in requests[before:]],[True,False])
   ask('unknown');self.assertNotIn('max_tokens',requests[-1])  # remembered for this model
  finally:server.shutdown();server.server_close()
 def test_provider_refusal_keeps_its_status_and_retry_after(self):
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    raw=json.dumps({'data':[{'id':'m','context_length':8192}]}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']))
    raw=json.dumps({'error':{'message':'Overloaded'}}).encode()
    self.send_response(529);self.send_header('Retry-After','7');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  class Control:
   cancelled=threading.Event()
   def attach(self,*args):pass
   def detach(self,*args):pass
  try:
   m=self.manager;m.configure({'engine':'api','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'local-test'});m.connect()
   m.load({'id':m.remote_identifier(m.remote_models[0])},None,None)
   with self.assertRaises(engine_manager.ProviderHTTPError) as caught:
    b''.join(m.stream({'model':'m','messages':[{'role':'user','content':'x'}]},Control()))
   self.assertEqual((caught.exception.status,caught.exception.retry_after_ms),(529,7000))
   self.assertIn('(529): el proveedor está saturado ahora mismo',str(caught.exception))
  finally:server.shutdown();server.server_close()
  self.assertEqual(engine_manager.retry_after_ms({'retry-after-ms':'1500'}),1500)
  self.assertIsNone(engine_manager.retry_after_ms({}))
 def test_stream_errors_are_failures_not_empty_success(self):
  with self.assertRaises(ValueError):ClaudeStream().packet({'type':'error','error':{'message':'overloaded'}})
if __name__=='__main__':unittest.main()

class ProviderContextTests(unittest.TestCase):
 """A provider model declares far more context than a local engine runs (here 1,048,576)."""
 def test_using_a_provider_model_ignores_the_local_context_range(self):
  import os,http.client
  os.environ.setdefault('STRATA_AGENT_DATA',tempfile.mkdtemp(prefix='va-test-'))
  sys.path[:0]=['tools']
  import agent
  calls=[]
  server=ThreadingHTTPServer(('127.0.0.1',0),agent.Handler);port=server.server_address[1]
  threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.shutdown)
  def post(remote):
   with patch.object(agent,'REMOTE_ENGINE',lambda:remote),patch.object(agent,'load_agent_model',lambda *a:calls.append(a) or {'loaded':True}):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
    c.request('POST','/api/load',json.dumps({'model':'api--deepseek','context':1048576}),{'Content-Type':'application/json'})
    r=c.getresponse();r.read();c.close();return r.status
  self.assertEqual(post(True),200);self.assertEqual(calls[-1],('api--deepseek',))
  self.assertEqual(post(False),400)  # local engines keep their range
 def test_provider_context_preference_is_saved(self):
  from model_preferences import ModelPreferences
  with tempfile.TemporaryDirectory() as d:
   store=ModelPreferences(Path(d)/'prefs.json');store.save('api--deepseek',{'context':1048576})
   self.assertEqual(store.records['api--deepseek']['context'],1048576)

class ProviderProtocolHeadersTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.prev=engine_manager.DATA_ROOT;engine_manager.DATA_ROOT=Path(self.temp.name)
  self.manager=engine_manager.EngineManager()
 def tearDown(self):
  engine_manager.DATA_ROOT=self.prev;self.temp.cleanup()
 def test_presets_user_agent_opencode_session_openrouter_azure_and_betas(self):
  import http.server,json,threading,uuid
  from remote_protocols import DEFAULT_OPENROUTER_REFERER,build_provider_headers,infer_provider_preset,parse_extra_headers
  self.assertEqual(infer_provider_preset('openai','https://openrouter.ai/api/v1'),'openrouter')
  self.assertEqual(infer_provider_preset('openai','https://opencode.ai/zen/v1'),'opencode')
  self.assertEqual(infer_provider_preset('openai','https://myres.openai.azure.com/openai/deployments/gpt4o'),'azure')
  cleaned=parse_extra_headers({'X-Stainless-Lang':'python','x-stainless-os':'Windows','X-Custom':'ok'})
  self.assertEqual(cleaned,{'X-Custom':'ok'})
  captured=[]
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*_):pass
   def do_GET(self):
    captured.append(('GET',self.path,{k:v for k,v in self.headers.items()}))
    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
    self.wfile.write(json.dumps({'data':[{'id':'m1','context_length':32768}]}).encode())
   def do_POST(self):
    self.rfile.read(int(self.headers.get('Content-Length','0')))
    captured.append(('POST',self.path,{k:v for k,v in self.headers.items()}))
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
    if self.path.endswith('/messages'):
     self.wfile.write(b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n')
    else:
     self.wfile.write(b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
  server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
  threading.Thread(target=server.serve_forever,daemon=True).start()
  class Control:
   cancelled=threading.Event()
   def attach(self,_):pass
   def detach(self,_):pass
  try:
   base=f'http://127.0.0.1:{server.server_address[1]}/v1'
   m=self.manager
   m.configure({'engine':'api','provider_preset':'opencode','protocol':'openai','base_url':base,'api_key':'k-oc','user_agent':'opencode/1.0.0','extra_headers':{'X-Stainless-Runtime':'node','X-Proxy-Tag':'alpha'}})
   m.connect();ident=m.remote_identifier(m.remote_models[0]);m.load({'id':ident},None,None)
   b''.join(m.stream({'model':'m1','messages':[{'role':'user','content':'a'}]},Control(),conversation_id='conv-1'))
   b''.join(m.stream({'model':'m1','messages':[{'role':'user','content':'b'}]},Control(),conversation_id='conv-1'))
   b''.join(m.stream({'model':'m1','messages':[{'role':'user','content':'c'}]},Control(),conversation_id='conv-2'))
   posts=[h for meth,_,h in captured if meth=='POST']
   self.assertEqual(posts[0]['User-Agent'],'opencode/1.0.0')
   self.assertEqual(posts[0]['X-Proxy-Tag'],'alpha')
   self.assertFalse(any(k.lower().startswith('x-stainless-') for k in posts[0]))
   s1_a,s1_b,s2=posts[0]['x-opencode-session'],posts[1]['x-opencode-session'],posts[2]['x-opencode-session']
   self.assertEqual(uuid.UUID(s1_a).version,4);self.assertEqual(s1_a,s1_b);self.assertNotEqual(s1_a,s2)
   reloaded=engine_manager.EngineManager();self.assertEqual(reloaded.session_uuid('conv-1'),s1_a)
   or_h=build_provider_headers({'provider_preset':'openrouter','protocol':'openai','base_url':'https://openrouter.ai/api/v1'},'k-or',stream=True,extra_headers={'Accept':'application/json','Accept-Encoding':'gzip'})
   self.assertEqual(or_h['HTTP-Referer'],DEFAULT_OPENROUTER_REFERER);self.assertEqual(or_h['X-Title'],'V-Agent')
   self.assertEqual(or_h['Accept'],'text/event-stream');self.assertEqual(or_h['Cache-Control'],'no-cache');self.assertEqual(or_h['Accept-Encoding'],'identity')
   m.configure({'engine':'api','provider_preset':'opencode','protocol':'openai','base_url':base,'api_key':'k-oc','send_session_id':False})
   self.assertNotIn('x-opencode-session',m.headers(stream=True,session_id=s1_a))
   m.configure({'engine':'api','provider_preset':'azure','protocol':'openai','base_url':base,'api_key':'k-az','azure_api_version':'2024-10-21'})
   self.assertIn('api-version=2024-10-21',m.url('/chat/completions'))
   az_h=m.headers(stream=True);self.assertEqual(az_h['api-key'],'k-az');self.assertNotIn('Authorization',az_h)
   m.configure({'engine':'api','provider_preset':'anthropic','protocol':'anthropic','base_url':base,'api_key':'k-cl','anthropic_beta':'prompt-caching-2024-07-31,output-128k-2025-02-19','auth_mode':'bearer'})
   cl_h=m.headers(stream=True);self.assertEqual(cl_h['Authorization'],'Bearer k-cl');self.assertNotIn('x-api-key',cl_h)
   self.assertEqual(cl_h['anthropic-version'],'2023-06-01');self.assertEqual(cl_h['anthropic-beta'],'prompt-caching-2024-07-31,output-128k-2025-02-19')
  finally:server.shutdown();server.server_close()

 def test_gzip_fallback_classic_azure_compaction_session_and_latin1_guard(self):
  import gzip,http.server,json,threading
  from remote_protocols import build_provider_headers,extract_azure_deployment
  self.assertEqual(extract_azure_deployment('https://res.openai.azure.com/openai/deployments/gpt4o'),'gpt4o')
  with self.assertRaises(ValueError):
   build_provider_headers({'protocol':'openai','base_url':'https://openrouter.ai/api/v1','x_title':'V-Agent — Español 🚀'},'k')
  posts=[]
  class ProxyHandler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*_):pass
   def do_GET(self):
    if '/openai/deployments/gpt4o/models' in self.path:
     self.send_response(404);self.send_header('Content-Type','application/json');self.end_headers()
     self.wfile.write(b'{"error":{"message":"Resource not found"}}');return
    payload=gzip.compress(json.dumps({'data':[{'id':'gz-model','context_length':32768}]}).encode())
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Encoding','gzip');self.end_headers()
    self.wfile.write(payload)
   def do_POST(self):
    self.rfile.read(int(self.headers.get('Content-Length','0')))
    posts.append((self.path,{k:v for k,v in self.headers.items()}))
    if self.path.endswith('/responses/compact'):
     self.send_response(404);self.end_headers();return
    # Simulate non-stream JSON response (e.g. compaction) compressed with gzip despite identity
    if self.headers.get('Accept')!='text/event-stream':
     body=gzip.compress(json.dumps({'choices':[{'message':{'content':'Resumen comprimido'}}]}).encode())
     self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Encoding','gzip');self.end_headers()
     self.wfile.write(body);return
    sse=gzip.compress(b'data: {"choices":[{"delta":{"content":"hola"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Encoding','gzip');self.end_headers()
    self.wfile.write(sse)
  srv=http.server.ThreadingHTTPServer(('127.0.0.1',0),ProxyHandler)
  threading.Thread(target=srv.serve_forever,daemon=True).start()
  class Control:
   cancelled=threading.Event()
   def attach(self,_):pass
   def detach(self,_):pass
  try:
   root=f'http://127.0.0.1:{srv.server_address[1]}'
   m=self.manager
   # 1. Classic Azure deployment URL connects cleanly even if /models returns 404
   m.configure({'engine':'api','protocol':'openai','base_url':root+'/openai/deployments/gpt4o','api_key':'k-az','azure_api_version':'2024-10-21'})
   snap=m.connect();self.assertEqual([x['id'] for x in snap['api']['models']],['gpt4o'])
   # 2. Gzip fallback on GET /models AND gzip-compressed SSE stream
   m.configure({'engine':'api','provider_preset':'opencode','protocol':'openai','base_url':root+'/gzip-compact/v1','api_key':'k-oc'})
   m.connect();ident=m.remote_identifier(m.remote_models[0]);m.load({'id':ident},None,None)
   stream_out=b''.join(m.stream({'model':'gz-model','messages':[{'role':'user','content':'hi'}]},Control(),conversation_id='conv-z')).decode()
   self.assertIn('hola',stream_out);self.assertIn('[DONE]',stream_out)
   # 3. compact_context forwards x-opencode-session and decodes gzip response
   res=m.compact_context(ident,[{'role':'user','content':'uno'},{'role':'assistant','content':'dos'}],conversation_id='conv-z')
   self.assertEqual(res['summary'],'Resumen comprimido')
   self.assertEqual(posts[-1][1]['x-opencode-session'],posts[0][1]['x-opencode-session'])
  finally:srv.shutdown();srv.server_close()

 def test_openrouter_reasoning_delta_field(self):
  import agent,json,threading
  from unittest import mock
  chunks=[
   b'data: {"choices":[{"delta":{"reasoning":"Paso 1. "}}]}\n\n',
   b'data: {"choices":[{"delta":{"reasoning":"Paso 2."}}]}\n\n',
   b'data: {"choices":[{"delta":{"content":"Respuesta final."},"finish_reason":"stop"}]}\n\n',
   b'data: [DONE]\n\n',
  ]
  control=agent.GenerationControl()
  with mock.patch.object(agent,'engine_chat_stream',return_value=(c for c in chunks)):
   events=list(agent.run_chat_stream({'model':'test','messages':[{'role':'user','content':'hola'}],'reasoning_effort':'medium','functions':{}},control))
  reasons=''.join(e['text'] for e in events if e.get('type')=='reasoning')
  contents=''.join(e['text'] for e in events if e.get('type')=='content')
  done=[e for e in events if e.get('type')=='done']
  self.assertIn('Paso 1.',reasons);self.assertIn('Paso 2.',reasons);self.assertEqual(contents,'Respuesta final.')
  self.assertTrue(done and 'Paso 1.' in done[0].get('reasoning_content',''))
