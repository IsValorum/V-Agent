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
  manager=EngineManager.__new__(EngineManager);manager.kind='llama';manager.loaded='m';manager.live=True;manager.last_usage={};manager.llama_key='k'
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

 def test_all_four_local_engines_support_and_preserve_custom_builds(self):
  import json,kv_settings,runtime_paths
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   settings_root=root/'settings';settings_root.mkdir()
   runtime_root=root/'runtime';runtime_root.mkdir()
   strata_exe=root/'custom-strata'/'strata-poly-custom.exe';strata_exe.parent.mkdir();strata_exe.write_bytes(b'strata')
   rust_exe=root/'custom-rust'/'strata-custom.exe';rust_exe.parent.mkdir();rust_exe.write_bytes(b'rust')
   llama_exe=root/'custom-llama'/'llama-server.exe';llama_exe.parent.mkdir();llama_exe.write_bytes(b'llama')
   maya_repo=root/'my-maya-repo';(maya_repo/'serve').mkdir(parents=True)
   (maya_repo/'maya.py').write_text('# maya',encoding='utf-8')
   (maya_repo/'serve'/'server.py').write_text('# srv',encoding='utf-8')
   maya_exe=maya_repo/'build-cuda'/'Release'/'maya-ds4.exe';maya_exe.parent.mkdir(parents=True);maya_exe.write_bytes(b'maya')
   maya_py=root/'custom-venv'/'python.exe';maya_py.parent.mkdir();maya_py.write_bytes(b'py')

   manager=EngineManager.__new__(EngineManager)
   manager.file=settings_root/'engines.json'
   manager.settings={'active':'strata','llama':{},'strata':{},'rust':{},'maya':{}}
   manager.kind='strata'
   manager.snapshot=lambda:manager.settings

   with patch.object(runtime_paths,'SETTINGS_ROOT',settings_root),patch.object(runtime_paths,'RUNTIME_ROOT',runtime_root):
    # 1. Strata custom build + preservation on official switch
    with patch('engine_manager.subprocess.run',return_value=Mock(stdout=b'version: strata-custom-1\n',stderr=b'')):
     manager.configure({'engine':'strata','variant':'custom','executable':f'"{strata_exe}"'})
    self.assertEqual(manager.executable(),strata_exe)
    self.assertTrue(manager.installed_engines()['strata'])
    self.assertEqual(runtime_paths.active_engine_executable('strata',runtime_root/'strata/strata-poly.exe'),strata_exe)
    manager.configure({'engine':'strata','variant':'official','executable':''})
    self.assertEqual(manager.settings['strata']['executable'],str(strata_exe))
    self.assertEqual(manager.settings['strata']['custom_build']['version'],'strata-custom-1')

    # Check custom-named Strata Poly binary still gets valid KV options
    gguf=root/'model.gguf';gguf.write_bytes(b'GGUF')
    cfg_file=root/'strata-test.json'
    cfg_file.write_text(json.dumps({'exe':str(strata_exe),'_val_managed_engine':True,'args':['--model',str(gguf)]}),encoding='utf-8')
    with patch.object(kv_settings,'_shape',return_value=('gemma4',[128,128])):
     kv_info=kv_settings.describe(cfg_file)
    self.assertEqual([o['value'] for o in kv_info['options']],['fp16','int8','int8k'])

    # 2. Strata Rust custom build + preservation on official switch
    with patch('engine_manager.subprocess.run',return_value=Mock(stdout=b'version: rust-custom-2\n',stderr=b'')):
     manager.configure({'engine':'rust','variant':'custom','executable':str(rust_exe)})
    self.assertEqual(manager.executable(),rust_exe)
    self.assertTrue(manager.installed_engines()['rust'])
    manager.configure({'engine':'rust','variant':'official','executable':''})
    self.assertEqual(manager.settings['rust']['executable'],str(rust_exe))

    # 3. llama.cpp custom build marks installed even without official installs
    with patch('engine_manager.subprocess.run',return_value=Mock(stdout=b'version: llama-custom-3\n',stderr=b'')):
     manager.configure({'engine':'llama','variant':'custom','executable':str(llama_exe),'gpu_layers':'auto'})
    self.assertTrue(manager.installed_engines()['llama-custom'])

    # 4. Project Maya custom build resolved automatically from subfolder / binary without clone/cmake
    with patch('engine_manager.subprocess.run',return_value=Mock(stdout=b'version: maya-ds4-custom\n',stderr=b'')):
     manager.configure({'engine':'maya','maya_root':str(maya_exe.parent),'maya_executable':str(maya_exe),'maya_python':str(maya_py),'maya_backend':'cuda'})
    self.assertEqual(manager.settings['maya']['root'],str(maya_repo.resolve()))
    self.assertEqual(manager.executable(),maya_exe)
    self.assertTrue(manager.installed_engines()['maya'])
    self.assertEqual(manager.builds()['maya']['executable'],str(maya_exe))

if __name__=='__main__':unittest.main()
