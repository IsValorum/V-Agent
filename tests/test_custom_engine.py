import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'agent'),str(Path(__file__).resolve().parents[1])]
from engine_manager import EngineManager

class EngineCustomTests(unittest.TestCase):
 def test_custom_build_survives_official_switch_and_restart(self):
  with tempfile.TemporaryDirectory() as folder:
   exe=Path(folder)/'llama-server.exe';exe.write_bytes(b'test')
   manager=EngineManager.__new__(EngineManager);manager.file=Path(folder)/'engines.json';manager.settings={'active':'strata','llama':{}};manager.kind='strata';manager.snapshot=lambda:manager.settings
   with patch('engine_manager.subprocess.run',return_value=Mock(stdout=b'version: test-build\n',stderr=b'')):
    manager.configure({'engine':'llama','variant':'custom','executable':str(exe),'gpu_layers':'auto'})
   manager.configure({'engine':'llama','variant':'cuda','executable':'','gpu_layers':'auto'})
   self.assertEqual(manager.settings['llama']['executable'],str(exe))
   self.assertEqual(manager.settings['llama']['custom_build']['version'],'test-build')
   with patch('engine_manager.subprocess.run',return_value=Mock(stdout=b'version: test-build\n',stderr=b'')):
    manager.configure({'engine':'llama','variant':'custom','executable':manager.settings['llama']['executable'],'gpu_layers':'auto'})
   self.assertEqual(manager.executable(),exe)
   self.assertIn('test-build',manager.file.read_text())

 def test_live_metrics_accept_list_next_token_from_newer_llama(self):
  # llama.cpp b12xxx: "next_token" is a list. A dict-only parser broke /api/stats while generating.
  import io,json
  manager=EngineManager.__new__(EngineManager);manager.kind='llama';manager.loaded='m';manager.live=True;manager.last_usage={}
  for next_token in ([{'n_prompt_tokens':120,'n_decoded':30}],{'n_prompt_tokens':120,'n_decoded':30}):
   body=json.dumps([{'n_ctx':8192,'is_processing':True,'next_token':next_token}]).encode()
   with patch('engine_manager.urllib.request.urlopen',return_value=io.BytesIO(body)):
    result=manager.metrics()
   self.assertEqual(result['engine']['max_context'],8192)
   self.assertEqual((result['live']['prompt_tokens'],result['live']['generated']),(120,30))
  # b12250: the prompt count lives on the slot, next_token only carries n_decoded.
  body=json.dumps([{'n_ctx':8192,'is_processing':True,'n_prompt_tokens':900,'next_token':{'n_decoded':12}}]).encode()
  with patch('engine_manager.urllib.request.urlopen',return_value=io.BytesIO(body)):
   result=manager.metrics()
  self.assertEqual((result['live']['prompt_tokens'],result['live']['generated']),(900,12))
  # Live tokens/s from two samples of the same reply.
  manager._decode_mark=None
  for generated,clock in ((10,100.0),(70,102.0)):
   body=json.dumps([{'n_ctx':8192,'is_processing':True,'n_prompt_tokens':900,'next_token':{'n_decoded':generated}}]).encode()
   with patch('engine_manager.urllib.request.urlopen',return_value=io.BytesIO(body)),patch('engine_manager.time.monotonic',return_value=clock):
    result=manager.metrics()
  self.assertEqual(result['live']['tok_s'],30.0)

if __name__=='__main__':unittest.main()
