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
if __name__=='__main__':unittest.main()
