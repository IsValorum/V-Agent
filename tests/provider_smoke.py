"""Isolated app + real MCP loop through both wire protocols. Only loopback HTTP."""
import argparse,json,threading,urllib.request,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

class Fixture(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  raw=json.dumps({'data':[{'id':'local-fixture-pro','display_name':'Fixture Pro','context_length':200000,'max_tokens':8192},{'id':'local-fixture-mini','display_name':'Fixture Mini','context_length':65536},{'id':'local-fixture-unknown','display_name':'Fixture sin metadatos'}]}).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));claude=self.path.endswith('/messages')
  assert self.headers.get('Authorization')=='Bearer fixture-key'
  assert 'chat_template_kwargs' not in body and 'repetition_penalty' not in body
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
  if claude:
   assert 'temperature' not in body and 'top_p' not in body
   final=any(part.get('type')=='tool_result' for message in body['messages'] for part in message.get('content',[]) if isinstance(part,dict))
   if final:assert any('content' in part for message in body['messages'] for part in message.get('content',[]) if part.get('type')=='tool_result')
   events=[{'type':'message_start','message':{'usage':{'input_tokens':125,'output_tokens':0}}}]
   events+=([{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'Provider y MCP reales verificados.'}}] if final else [{'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'tool_smoke','name':'pc__fs_list','input':{}}},{'type':'content_block_delta','index':0,'delta':{'type':'input_json_delta','partial_json':'{"path":"."}'}}])
   events += [{'type':'message_delta','delta':{'stop_reason':'end_turn' if final else 'tool_use'},'usage':{'output_tokens':7}},{'type':'message_stop'}]
   for event in events:self.wfile.write(('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n').encode())
  else:
   final=any(m.get('role')=='tool' for m in body['messages'])
   delta={'content':'Provider y MCP reales verificados.'} if final else {'tool_calls':[{'index':0,'id':'tool_smoke','type':'function','function':{'name':'pc__fs_list','arguments':'{"path":"."}'}}]}
   packet={'choices':[{'delta':delta,'finish_reason':'stop' if final else 'tool_calls'}],'usage':{'prompt_tokens':125,'completion_tokens':7}}
   self.wfile.write(('data: '+json.dumps(packet)+'\n\ndata: [DONE]\n\n').encode())

def run(base):
 def post(path,body):
  request=urllib.request.Request(base+path,json.dumps(body).encode(),{'Content-Type':'application/json','Origin':base})
  with urllib.request.urlopen(request,timeout=90) as response:return response.read().decode()
 results=[]
 for protocol in ('openai','anthropic'):
  state=json.loads(post('/api/harness/configure',{'engine':'api','protocol':protocol,'base_url':'http://127.0.0.1:19386/'+protocol+'/v1','api_key':'fixture-key','name':'Demo '+('Claude' if protocol=='anthropic' else 'OpenAI'),'new_connection':True}))
  state=json.loads(post('/api/harness/connect',{}));identifier='api--'+state['api']['id']+'--local-fixture-pro'
  post('/api/load',{'model':identifier})
  stream=post('/api/chat',{'model':identifier,'conversation_id':'provider-smoke-'+uuid.uuid4().hex,'agent_profile':'light','messages':[{'role':'user','content':'List the workspace files.'}],'functions':{'files':True},'effort':'none','sampling':{'max_tokens':128}})
  assert 'Provider y MCP reales verificados.' in stream,stream[-1500:]
  assert 'tool_result' in stream and 'pc__fs_list' in stream,stream[-1500:]
  post('/api/unload',{})
  results.append({'protocol':protocol,'native_stream':True,'real_mcp_loop':True,'context':state['models'][0]['context']})
 print(json.dumps(results))

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--serve',action='store_true');parser.add_argument('--base',default='http://127.0.0.1:19385');args=parser.parse_args()
 if args.serve:ThreadingHTTPServer(('127.0.0.1',19386),Fixture).serve_forever()
 else:run(args.base)
