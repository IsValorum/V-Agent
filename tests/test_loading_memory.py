import sys,unittest,copy,tempfile,struct
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path('agent').resolve()),str(Path('tools').resolve())]
from load_settings import validate,effective,arguments
from memory_estimate import estimate_facts
import gguf_catalog
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
 def test_gemma4_swa_keeps_kv_bounded_even_without_explicit_pattern(self):
  pattern=[True,True,True,True,True,False]*5
  kvheads=[8,8,8,8,8,2]*5
  base={'general.architecture':'gemma4','gemma4.block_count':30,'gemma4.embedding_length':2816,'gemma4.attention.head_count':16,'gemma4.attention.head_count_kv':kvheads,'gemma4.attention.key_length':512,'gemma4.attention.value_length':512,'gemma4.attention.key_length_swa':256,'gemma4.attention.sliding_window':1024}
  thinking={'metadata':{**base,'gemma4.attention.value_length_swa':256,'gemma4.attention.sliding_window_pattern':pattern},'dense_bytes':1684968568,'expert_bytes':11220746240}
  xl={'metadata':dict(base),'dense_bytes':1684968568,'expert_bytes':11220746240}
  caps={'prompt_batch':1024,'batch':1024,'ubatch':256,'checkpoints':True}
  m1=estimate_facts(thinking,109568,'fp16',{},kind='strata',caps=caps)
  m2=estimate_facts(xl,109568,'fp16',{},kind='strata',caps=caps)
  self.assertEqual(m1['kv'],2663383040)
  self.assertEqual(m2['kv'],m1['kv'])
  self.assertAlmostEqual(m1['total']/2**30,15.90,places=2)
  self.assertIn('Caché SWA acotada a la ventana deslizante del modelo.',m1['notes'])
 def test_shared_kv_and_gemma_patterns_reduce_active_kv(self):
  m={'general.architecture':'gemma4','gemma4.block_count':12,'gemma4.embedding_length':2048,'gemma4.attention.head_count':8,'gemma4.attention.head_count_kv':4,'gemma4.attention.key_length':256,'gemma4.attention.value_length':256,'gemma4.attention.sliding_window':1024}
  full=estimate_facts({'metadata':dict(m),'dense_bytes':1000},8192,'fp16',{'auto':False,'batch':256,'ubatch':64})
  shared=estimate_facts({'metadata':{**m,'gemma4.attention.shared_kv_layers':4},'dense_bytes':1000},8192,'fp16',{'auto':False,'batch':256,'ubatch':64})
  self.assertLess(shared['kv'],full['kv'])
  g2={'general.architecture':'gemma2','gemma2.block_count':4,'gemma2.attention.head_count':8,'gemma2.attention.head_count_kv':4,'gemma2.attention.key_length':128,'gemma2.attention.value_length':128,'gemma2.attention.sliding_window':1024}
  r2=estimate_facts({'metadata':g2,'dense_bytes':1000},8192,'fp16',{'auto':False,'batch':256,'ubatch':64})
  expected_g2=2*4*8192*(128*4)+2*4*1280*(128*4)
  self.assertEqual(r2['kv'],expected_g2)
 def test_lfm2moe_bailingmoe3_qwen_recurrent_and_pure_ssm(self):
  lfm={'metadata':{'general.architecture':'lfm2moe','lfm2moe.block_count':40,'lfm2moe.embedding_length':2048,'lfm2moe.attention.head_count':32,'lfm2moe.attention.head_count_kv':[0,0,8,0]*10,'lfm2moe.attention.key_length':64,'lfm2moe.attention.value_length':64,'lfm2moe.shortconv.l_cache':3},'dense_bytes':1000,'expert_bytes':2000}
  rl=estimate_facts(lfm,8192,'fp16',{'auto':False,'checkpoints':0})
  self.assertEqual(rl['recurrent'],30*2*2048*4)
  bai={'metadata':{'general.architecture':'bailingmoe3','bailingmoe3.block_count':24,'bailingmoe3.embedding_length':2048,'bailingmoe3.attention.head_count':16,'bailingmoe3.attention.head_count_kv':[0,0,0,1]*6,'bailingmoe3.attention.key_length':576,'bailingmoe3.attention.value_length':128,'bailingmoe3.kda.head_dim':128,'bailingmoe3.ssm.conv_kernel':4},'dense_bytes':1000,'expert_bytes':2000}
  rb_i8k=estimate_facts(bai,8192,'int8k',{'auto':False,'checkpoints':0})
  rb_k8v4=estimate_facts(bai,8192,'k8v4',{'auto':False,'checkpoints':0})
  self.assertEqual(rb_i8k['kv'],6*8192*(576*1+128*2))
  self.assertEqual(rb_k8v4['kv'],6*8192*(576*1+128*(18/32)))
  self.assertEqual(rb_i8k['recurrent'],18*(16*128*128+3*3*16*128)*4)
  qwen={'metadata':{'general.architecture':'qwen4exp','qwen4exp.block_count':41,'qwen4exp.attention.head_count':16,'qwen4exp.attention.head_count_kv':2,'qwen4exp.attention.key_length':256,'qwen4exp.attention.value_length':256,'qwen4exp.attention.recurrent_layers':[True]*30+[False]*11,'qwen4exp.ssm.inner_size':4096,'qwen4exp.ssm.state_size':128,'qwen4exp.ssm.group_count':16,'qwen4exp.ssm.conv_kernel':4},'dense_bytes':1000}
  rq=estimate_facts(qwen,8192,'fp16',{'auto':False,'checkpoints':0})
  self.assertEqual(rq['kv'],11*2*8192*(256*4))
  self.assertEqual(rq['recurrent'],30*(4096*128+3*(4096+2*16*128))*4)
  pure_ssm={'metadata':{'general.architecture':'mamba','mamba.block_count':16,'mamba.ssm.inner_size':1024,'mamba.ssm.state_size':64,'mamba.ssm.group_count':1,'mamba.ssm.conv_kernel':4},'dense_bytes':1000}
  rp=estimate_facts(pure_ssm,8192,'fp16',{'auto':False,'checkpoints':0})
  self.assertEqual(rp['kv'],0);self.assertGreater(rp['recurrent'],0);self.assertIsNotNone(rp['total'])
 def test_gguf_catalog_uses_offset_span_for_unknown_quant_types(self):
  def pack_str(s):
   b=s.encode('utf8');return struct.pack('<Q',len(b))+b
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);gguf_path=root/'unknown_quant.gguf'
   hdr=bytearray(b'GGUF')
   hdr+=struct.pack('<IQQ',3,2,1)
   hdr+=pack_str('general.architecture')+struct.pack('<I',8)+pack_str('qwen35')
   hdr+=pack_str('t0.weight')+struct.pack('<IQIQ',1,64,142,0)
   hdr+=pack_str('t1.weight')+struct.pack('<IQIQ',1,4,0,64)
   pad=(-len(hdr))%32;hdr+=b'\x00'*pad
   data=b'\x00'*(64+16)
   gguf_path.write_bytes(bytes(hdr)+data)
   with patch.object(gguf_catalog,'DATA_ROOT',root):
    gguf_catalog._memory.clear()
    facts=gguf_catalog.inspect(gguf_path)
   self.assertEqual(facts['dense_bytes'],80)
 def test_kv_settings_gemma4_supports_int8_even_without_swa_key_length(self):
  import json,kv_settings
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);gguf=root/'g4.gguf';gguf.write_bytes(b'GGUF')
   cfg=root/'cfg.json'
   cfg.write_text(json.dumps({'exe':'strata-poly.exe','args':['--model',str(gguf)]}),encoding='utf8')
   meta={'general.architecture':'gemma4','gemma4.attention.key_length':512}
   with patch('gguf_catalog.inspect',return_value={'metadata':meta}):
    info=kv_settings.describe(cfg)
   self.assertEqual([o['value'] for o in info['options']],['fp16','int8','int8k'])
 def test_hardware_accounts_for_reclaimable_engine_vram(self):
  import subprocess as sp
  import memory_estimate
  from types import SimpleNamespace
  mib=2**20
  memory_estimate._idle_gpu_used=None
  memory_estimate.invalidate_hardware_cache()
  def fake_run(cmd,**_kwargs):
   q=cmd[1] if len(cmd)>1 else ''
   if 'memory.free' in q:return SimpleNamespace(stdout='1900, 6141\n')
   if 'compute-apps' in q:return SimpleNamespace(stdout='4242, 4050\n9999, 100\n')
   return SimpleNamespace(stdout='')
  with patch('memory_estimate.subprocess.run',side_effect=fake_run):
   idle=memory_estimate.hardware(force=True)
   self.assertEqual(idle['gpu_reclaimable'],0)
   self.assertEqual(idle['gpu_effective_available'],1900*mib)
   with_engine=memory_estimate.hardware(reclaimable_bytes=3500*mib,engine_pids=[4242],force=True)
   self.assertEqual(with_engine['gpu_reclaimable'],4050*mib)
   self.assertEqual(with_engine['gpu_effective_available'],5950*mib)
   external_only=memory_estimate.hardware(engine_pids=[1111],force=True)
   self.assertGreaterEqual(external_only['gpu_effective_available'],1900*mib)
  # Vulkan / WDDM fallback when compute-apps reports [N/A]
  def fake_vulkan(cmd,**_kwargs):
   q=cmd[1] if len(cmd)>1 else ''
   if 'memory.free' in q:return SimpleNamespace(stdout='1800, 6141\n')
   if 'compute-apps' in q:return SimpleNamespace(stdout='4242, [N/A]\n')
   return SimpleNamespace(stdout='')
  with patch('memory_estimate.subprocess.run',side_effect=fake_vulkan):
   vulkan=memory_estimate.hardware(reclaimable_bytes=4000*mib,engine_pids=[4242],force=True)
   self.assertEqual(vulkan['gpu_effective_available'],min(6141*mib,1800*mib+4000*mib))
  memory_estimate._idle_gpu_used=None;memory_estimate.invalidate_hardware_cache()
if __name__=='__main__':unittest.main()
