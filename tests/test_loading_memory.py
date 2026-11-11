import sys,unittest,copy,tempfile
from pathlib import Path
sys.path[:0]=[str(Path('agent').resolve()),str(Path('tools').resolve())]
from load_settings import validate,effective,arguments
from memory_estimate import estimate_facts
class LoadingMemoryTests(unittest.TestCase):
 def test_auto_uses_one_slot_checkpoints_and_engine_batches(self):
  caps={'checkpoints':True,'fit':True,'batch':1024,'ubatch':256}
  a=arguments({},8192,caps);self.assertEqual(a,['--ctx-size','8192','--parallel','1','--ctx-checkpoints','1','--fit','on'])
  self.assertEqual(effective({},caps)['ubatch'],256)
 def test_manual_context_is_per_slot(self):
  a=arguments({'auto':False,'parallel':4,'batch':256,'ubatch':64,'checkpoints':2},8192,{'checkpoints':True})
  self.assertEqual(a[:4],['--ctx-size','32768','--parallel','4']);self.assertIn('--batch-size',a);self.assertEqual(a[-2:],['--ctx-checkpoints','2'])
 def test_invalid_and_unsupported_settings(self):
  for v in ({'parallel':True},{'checkpoints':65},{'batch':32,'ubatch':64},{'auto':1},{'unknown':0}):
   with self.assertRaises(ValueError):validate(v)
  with self.assertRaises(ValueError):arguments({'auto':False,'checkpoints':4},8192,{'checkpoints':False})
 def test_fit_mode_lets_llama_place_layers_with_a_margin(self):
  from load_settings import gpu_layers
  caps={'checkpoints':True,'fit':True,'fit_target':True,'cpu_moe':True}
  self.assertEqual(gpu_layers({},'all'),'auto')  # --fit cannot move layers that are pinned
  a=arguments({'fit_target':2048},8192,caps);self.assertEqual(a[-4:],['--fit','on','--fit-target','2048'])
  self.assertNotIn('--fit-target',arguments({},8192,caps))
 def test_manual_mode_sets_layers_and_moe_experts_by_hand(self):
  from load_settings import gpu_layers
  caps={'checkpoints':True,'fit':True,'fit_target':True,'cpu_moe':True}
  manual={'auto':False,'gpu_layers':30,'cpu_moe':12}
  self.assertEqual(gpu_layers(manual,'auto'),'30');self.assertEqual(gpu_layers({'auto':False},'99'),'99')  # -1 = engine setting
  a=arguments(manual,8192,caps);self.assertIn('--n-cpu-moe',a);self.assertEqual(a[a.index('--n-cpu-moe')+1],'12');self.assertEqual(a[-2:],['--fit','off'])
  with self.assertRaises(ValueError):arguments(manual,8192,{'checkpoints':True,'fit':True})  # build without --n-cpu-moe
  for bad in ({'gpu_layers':-2},{'cpu_moe':1000},{'fit_target':-1}):
   with self.assertRaises(ValueError):validate(bad)
  self.assertEqual(validate({'auto':True,'parallel':1})['gpu_layers'],-1)  # older saved settings keep working
 def test_moe_experts_on_cpu_lower_the_gpu_estimate(self):
  f=self.facts();f['expert_bytes']=8*2**30
  full=estimate_facts(f,8192,'fp16',{'auto':False},gpu_layers='8');half=estimate_facts(f,8192,'fp16',{'auto':False,'cpu_moe':4},gpu_layers='8')
  self.assertAlmostEqual(full['gpu_full_offload']-half['gpu_full_offload'],4*2**30,delta=2**20);self.assertEqual(half['block_count'],8);self.assertTrue(half['moe'])
 def facts(self):return {'metadata':{'general.architecture':'test','test.block_count':8,'test.embedding_length':1024,'test.attention.head_count':8,'test.attention.head_count_kv':2,'test.attention.key_length':128,'test.attention.value_length':128},'dense_bytes':2**30,'expert_bytes':0}
 def test_kv_tracks_context_slots_and_quantization(self):
  f=self.facts();v={'auto':False,'parallel':1}
  a=estimate_facts(f,8192,'fp16',v);b=estimate_facts(f,16384,'fp16',v);c=estimate_facts(f,8192,'fp16',{**v,'parallel':4});q=estimate_facts(f,8192,'q8_0',v)
  self.assertEqual(b['kv'],a['kv']*2);self.assertEqual(c['kv'],a['kv']*4);self.assertAlmostEqual(q['kv']/a['kv'],(34/32)/2)
 def test_hybrid_checkpoints_add_recurrent_memory(self):
  f=self.facts();f['metadata'].update({'test.full_attention_interval':4,'test.ssm.inner_size':1024,'test.ssm.state_size':128,'test.ssm.conv_kernel':4,'test.ssm.group_count':8})
  a=estimate_facts(f,8192,'fp16',{'auto':False,'checkpoints':1});b=estimate_facts(f,8192,'fp16',{'auto':False,'checkpoints':3});self.assertGreater(a['recurrent'],0);self.assertEqual(b['recurrent'],a['recurrent']*2)
 def test_unknown_kv_is_unavailable_not_zero(self):
  f={'metadata':{},'dense_bytes':1000};m=estimate_facts(f,8192,'fp16',{});self.assertIsNone(m['kv']);self.assertIsNone(m['total'])
if __name__=='__main__':unittest.main()
