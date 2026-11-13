import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path[:0]=['agent','web_mcp','.']
from agent_profiles import filter_enabled
from output_paths import prepare_output_paths
from access_policy import AccessPolicy,AccessDenied
import http_tools_mcp as http
class AgentAuditTests(unittest.TestCase):
 def test_complete_preserves_disabled_optional_tools(self):
  result=filter_enabled({'fs_read'},'advanced',True)
  self.assertIn('fs_read',result);self.assertNotIn('screen_capture',result);self.assertNotIn('start',result)
  for name in ('web_search','hf_cli','http_request','shell_run','console','open'):self.assertNotIn(name,result)
 def test_network_outputs_are_conversation_scoped(self):
  with tempfile.TemporaryDirectory() as tmp:
   ws=AccessPolicy(Path(tmp)/'chat')
   result=prepare_output_paths('web__download',{'url':'https://example.test/file.bin'},ws,False)
   self.assertEqual(Path(result['path']),ws.root/'downloads/file.bin')
   for tool,args in [('web__download',{'path':str(Path(tmp)/'outside')}),('web__http_request',{'save_path':str(Path(tmp)/'outside')}),('autobrowser__browser_download',{'path':str(Path(tmp)/'outside')})]:
    with self.assertRaises(AccessDenied):prepare_output_paths(tool,args,ws,False)
   with self.assertRaises(AccessDenied):prepare_output_paths('web__http_request',{'allow_private':True},ws,False)
 def test_failed_download_preserves_existing_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'file.bin';path.write_bytes(b'previous content')
   response=MagicMock();response.__enter__.return_value=response
   def chunks(*args):yield b'partial';raise OSError('network disconnected')
   response.iter_content.side_effect=chunks
   session=MagicMock();session.get.return_value=response
   with patch.object(http,'_url',return_value='https://example.test/file.bin'),patch.object(http.requests,'Session',return_value=session):
    with self.assertRaises(OSError):http.download('https://example.test/file.bin',str(path))
   self.assertEqual(path.read_bytes(),b'previous content');self.assertEqual(list(Path(tmp).glob('*.part')),[])
 def test_redirect_is_validated_before_following(self):
  response=MagicMock();response.url='https://public.example/page';response.headers={'Location':'http://127.0.0.1:19380/api/access'};response.is_redirect=True
  with patch.object(http,'_url',side_effect=ValueError('Private destination')) as validate:
   with self.assertRaises(ValueError):http._redirect_guard(False)(response)
   validate.assert_called_once_with('http://127.0.0.1:19380/api/access',False)
 def test_admin_status_never_requests_elevation(self):
  import admin_mcp
  with patch.dict(admin_mcp.STATE,{'client':None}),patch.object(admin_mcp,'_start',side_effect=AssertionError('Status must not elevate')):
   result=json.loads(admin_mcp.status())
  self.assertFalse(result['active']);self.assertFalse(result['admin'])
 def test_http_request_truncates_max_bytes_and_supports_readability(self):
  html=b'<html><head><style>body{color:red}</style></head><body><article><h1>Guide</h1><p>Useful body paragraph.</p></article><script>var x=1;</script></body></html>'
  big=b'header '+b'a'*5000
  for body,args,expect_trunc,expect_sub in [
   (big,{'max_bytes':1500,'format':'text'},True,'header '),
   (html,{'format':'readability'},False,'Useful body paragraph.'),
   (html,{'format':'text','extract':'readability'},False,'Useful body paragraph.'),
  ]:
   resp=MagicMock();resp.__enter__.return_value=resp
   resp.status_code=200;resp.url='https://public.example/page';resp.encoding='utf-8'
   resp.headers={'Content-Type':'text/html; charset=utf-8'}
   resp.iter_content.side_effect=lambda *a,b=body:iter([b[:2048],b[2048:]] if len(b)>2048 else [b])
   session=MagicMock();session.request.return_value=resp;session.hooks={'response':[]}
   with patch.object(http,'_url',return_value='https://public.example/page'),patch.object(http.requests,'Session',return_value=session):
    out=json.loads(http.http_request('https://public.example/page',**args))
   self.assertTrue(out['ok'])
   self.assertEqual(out['truncated'],expect_trunc)
   self.assertIn(expect_sub,out['text'])
   if args.get('extract')=='readability' or args.get('format')=='readability':
    self.assertNotIn('<style>',out['text'])
    self.assertNotIn('var x=1',out['text'])
  # Server-side bot/captcha challenge surfaces working alternatives.
  gate=http._server_gate_hint(200,'https://www.mojeek.com/search?q=x','text/html','JavaScript is required to complete this challenge ALTCHA')
  self.assertTrue(gate['server_blocked'])
  self.assertTrue(any('duckduckgo__web_search' in a for a in gate['alternatives']))
  sorry_gate=http._server_gate_hint(429,'https://www.google.com/sorry/index','text/html','Our systems have detected unusual traffic')
  self.assertTrue(sorry_gate['server_blocked'])
  cf_gate=http._server_gate_hint(403,'https://example.org/','text/html','Just a moment... Cloudflare challenge-platform')
  self.assertTrue(cf_gate['server_blocked'])
  wait_gate=http._server_gate_hint(200,'https://search.marginalia.nu/','text/html','Wait A Moment - seeing a lot of fairly aggressive bot activity. Please wait for 1 seconds before proceeding.')
  self.assertTrue(wait_gate['server_blocked'])
  self.assertEqual(wait_gate.get('gate_kind'),'interstitial')
  empty_gate=http._server_gate_hint(200,'https://search.marginalia.nu/','text/html','No search results found. Marginalia Search only supports queries in the English language.')
  self.assertFalse(empty_gate.get('server_blocked',False))
  self.assertTrue(empty_gate.get('empty_results'))
  big_gate=http._server_gate_hint(200,'https://search.marginalia.nu/','text/html','Wait A Moment ' + ('result item link ' * 200))
  self.assertIsNone(big_gate)
 def test_gate_hints_and_descriptions_omit_disabled_or_blocked_tools(self):
  import agent, mcp_prompt
  tools=[{'function':{'name':'web__http_request','parameters':{'type':'object','properties':{}}}},
         {'function':{'name':'autobrowser__open','parameters':{'type':'object','properties':{}}}},
         {'function':{'name':'pc__browser','parameters':{'type':'object','properties':{}}}}]
  compacted={t['function']['name']:t['function']['description'] for t in mcp_prompt.compact_tools(tools)}
  self.assertNotIn('duckduckgo__web_search',compacted['web__http_request'])
  self.assertNotIn('duckduckgo__web_search',compacted['autobrowser__open'])
  self.assertIn('pc__browser',compacted['autobrowser__open'])
  raw=json.dumps({'ok':True,'server_blocked':True,'gate_kind':'hard','blocked_reason':'gate','alternatives':['pc__browser (visible)','duckduckgo__web_search (search)','Public JSON APIs via web__http_request']})
  filtered=json.loads(agent._filter_server_gate_result('autobrowser__open',raw,{'autobrowser__open':{},'web__http_request':{}},blocked_tools={'duckduckgo__web_search'}))
  self.assertFalse(any('duckduckgo__web_search' in a for a in filtered['alternatives']))
  self.assertFalse(any('pc__browser' in a for a in filtered['alternatives']))
  self.assertIn('user_suggestion',filtered)
  self.assertIn('Do not retry',filtered['user_suggestion'])
  inter_raw=json.dumps({'ok':True,'server_blocked':True,'gate_kind':'interstitial','blocked_reason':'wait gate','alternatives':['pc__browser (visible)']})
  inter_filtered=json.loads(agent._filter_server_gate_result('autobrowser__open',inter_raw,{'autobrowser__open':{},'pc__browser':{}}))
  self.assertNotIn('Do not retry',inter_filtered['user_suggestion'])
  self.assertIn('temporary',inter_filtered['user_suggestion'])
 def test_code_check_syntax_error_returns_structured_ok_false_without_raising(self):
  import pc_mcp
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bad=root/'bad.py';bad.write_text('def broken(:\n pass\n',encoding='utf8')
   out=json.loads(pc_mcp.call('code_check',{'path':'bad.py'},policy=AccessPolicy(root)))
  self.assertFalse(out['ok'])
  self.assertEqual(out['verification']['status'],'failed')
 def test_http_request_accepts_dict_body_and_download_forwards_custom_headers(self):
  resp=MagicMock();resp.__enter__.return_value=resp
  resp.status_code=200;resp.url='https://public.example/api';resp.encoding='utf-8'
  resp.headers={'Content-Type':'application/json'}
  resp.iter_content.side_effect=lambda *a:iter([b'{"ok":true}'])
  session=MagicMock();session.request.return_value=resp;session.hooks={'response':[]}
  with patch.object(http,'_url',return_value='https://public.example/api'),patch.object(http.requests,'Session',return_value=session):
   out=json.loads(http.http_request('https://public.example/api',method='POST',body={'a':1}))
  self.assertTrue(out['ok'])
  self.assertEqual(session.request.call_args.kwargs['data'],b'{"a": 1}')
  self.assertEqual(session.request.call_args.kwargs['headers']['Content-Type'],'application/json')
  with tempfile.TemporaryDirectory() as tmp:
   dst=Path(tmp)/'doc.bin'
   dl_resp=MagicMock();dl_resp.__enter__.return_value=dl_resp;dl_resp.headers={'Content-Type':'application/octet-stream'}
   dl_resp.iter_content.side_effect=lambda *a:iter([b'1234'])
   dl_session=MagicMock();dl_session.get.return_value=dl_resp;dl_session.hooks={'response':[]}
   with patch.object(http,'_url',return_value='https://public.example/doc.bin'),patch.object(http.requests,'Session',return_value=dl_session):
    http.download('https://public.example/doc.bin',str(dst),headers={'Referer':'https://public.example/'})
   self.assertEqual(dl_session.get.call_args.kwargs['headers']['Referer'],'https://public.example/')
 def test_window_focus_reports_false_when_foreground_unchanged(self):
  import computer_mcp
  def fake_enum(cb, _):
   cb(101, 0); return 1
  with patch.object(computer_mcp.user32,'EnumWindows',side_effect=fake_enum),patch.object(computer_mcp.user32,'IsWindowVisible',return_value=1),patch.object(computer_mcp,'_window_text',return_value='Notepad'),patch.object(computer_mcp.user32,'ShowWindow'),patch.object(computer_mcp.user32,'BringWindowToTop'),patch.object(computer_mcp.user32,'SetForegroundWindow'),patch.object(computer_mcp,'_key'),patch.object(computer_mcp,'_active_window',return_value={'hwnd':999,'pid':1,'title':'V-Agent'}):
   res=json.loads(computer_mcp.window_focus('Notepad'))
  self.assertFalse(res['ok']);self.assertEqual(res['active']['hwnd'],999)
if __name__=='__main__':unittest.main()
