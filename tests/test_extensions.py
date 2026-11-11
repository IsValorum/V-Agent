import base64,io,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'agent'),str(Path(__file__).resolve().parents[1])]
import extensions as x
class ExtensionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(x,'ROOT',Path(self.tmp.name));self.patch.start()
 def tearDown(self):self.patch.stop();self.tmp.cleanup()
 def test_import_disabled_no_execution_and_validation(self):
  with patch('subprocess.Popen',side_effect=AssertionError('Must not execute')):
   self.assertFalse(x.register({'mcpServers':{'example':{'command':'npx','args':['-y','example@1.0.0']}}})[0]['enabled'])
   self.assertEqual(x.enabled_configs(),{})
  for block in ({'pc':{'command':'x'}},{'bad__name':{'command':'x'}},{'a':{'url':'file:///bad'}},{'a':{'url':'https://test/mcp','type':'sse'}},{'a':{'command':'x','env':{'key':'REPLACE_ME'}}}):
   with self.assertRaises(ValueError):x.validate_servers(block)
 def test_full_access_required_for_external(self):
  x.register({'mcpServers':{'example':{'command':'python','args':[]}}})
  with self.assertRaises(ValueError):x.toggle('example',True,None,False)

 def test_catalog_only_downloads_metadata(self):
  def response(url,*a,**kw):
   url=getattr(url,'full_url',url)
   data={'servers':[{'server':{'name':'org/test','description':'Test','version':'1','remotes':[{'type':'streamable-http','url':'https://example.com/mcp'}]}}]} if 'registry.' in url else {'plugins':[{'name':'sample','source':'./plugins/sample'}]}
   return io.BytesIO(json.dumps(data).encode())
  with patch.object(x.urllib.request,'urlopen',response),patch('subprocess.Popen',side_effect=AssertionError('Catalog must not execute')):
   catalog=x.Catalog();catalog.refresh(True)
   for _ in range(200):
    if not catalog.busy:break
    time.sleep(.01)
   self.assertFalse(catalog.busy);self.assertEqual(len(catalog.snapshot()['items']),2)
   result=x.prepare_plugin({'name':'org/test','source':'mcp'})
   self.assertEqual(result['manifest']['mcpServers']['org_test']['url'],'https://example.com/mcp')
   self.assertEqual(x.configs(),{})
 def test_custom_mcp_survives_corrupt_state_and_has_backup(self):
  x.register({'mcpServers':{'first':{'command':'python','args':['-V']}}})
  x.register({'mcpServers':{'second':{'command':'python','args':['-V']}}})
  self.assertTrue((Path(self.tmp.name)/'installed.json.bak').exists())
  (Path(self.tmp.name)/'installed.json').write_text('{bad',encoding='utf8')
  self.assertEqual(set(x.configs()),{'first'})
  x.register({'mcpServers':{'third':{'command':'python','args':['-V']}}})
  self.assertIn('third',x.configs())
 def test_manual_mcp_json_migrates_once(self):
  root=Path(self.tmp.name);data=root/'data';data.mkdir();(data/'mcp.json').write_text(json.dumps({'mcpServers':{'manual':{'command':'python','args':['-V']},'pc':{'command':'ignored'},'bundled':{'command':'x','_val_bundled':True}}}),encoding='utf8')
  with patch.object(x,'DATA_ROOT',data):
   self.assertEqual(set(x.configs()),{'manual'})
   self.assertFalse(x.configs()['manual']['enabled'])
   (x.ROOT/'installed.json').write_text('{}',encoding='utf8')
   self.assertEqual(x.configs(),{})

if __name__=='__main__':unittest.main()
