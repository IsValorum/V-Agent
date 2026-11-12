import sys,unittest,threading,json
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['agent','.']
from agent_profiles import filter_enabled,distinct_tools,PROFILES
from tool_approvals import needs_approval,APPROVALS
from mcp_prompt import compact_tools,DESCRIPTIONS
from verification_evidence import evidence
class AgentDesignTests(unittest.TestCase):
 def test_light_console_requires_scope_and_approval(self):
  self.assertIn('console',filter_enabled({'console'},'light',True))
  self.assertNotIn('console',filter_enabled({'console'},'light',False))
  for mode in ('full','auto','ask'):
   self.assertTrue(needs_approval(mode,'pc__console',{'action':'run','command':'echo test'},'light'))
  # "Automatic" is honoured in every profile (it used to prompt anyway in Light).
  self.assertFalse(needs_approval('run','pc__console',{'action':'run','command':'echo test'},'light'))
  self.assertFalse(needs_approval('run','pc__code_check',{'run':True,'check':'test'},'light'))
  self.assertFalse(needs_approval('auto','pc__console',{'action':'status'},'light'))
  self.assertFalse(needs_approval('auto','pc__code_check',{'run':True,'check':'syntax'},'light'))
  self.assertTrue(needs_approval('full','pc__code_check',{'run':True,'check':'test'},'light'))
  self.assertTrue(all(p['rounds']==50 for p in PROFILES.values()))
 def test_exact_alias_hidden_only_when_replacement_available(self):
  tools=[{'function':{'name':n}} for n in ('autobrowser__open','autobrowser__navigate','autobrowser__snapshot','pc__browser','web__download')]
  self.assertEqual(len(distinct_tools(tools)),4)
  self.assertEqual(distinct_tools([tools[1]]),[tools[1]])
 def test_operational_parameter_instructions_survive_compaction(self):
  tool={'function':{'name':'pc__fs_copy','parameters':{'type':'object','properties':{'ancla':{'type':'string','description':'Destination line or range, e.g. 24-31.'}}}}}
  result=compact_tools([tool])[0]['function']
  self.assertIn('24-31',result['parameters']['properties']['ancla']['description'])
  self.assertIn('selected text',result['description'])
  from tool_budget import _sin_ruido,SHORT_DESCRIPTIONS
  self.assertIn('description',_sin_ruido(result['parameters'])['properties']['ancla'])
  self.assertIn('appear once',SHORT_DESCRIPTIONS['pc__fs_edit'])
 def test_verification_never_claims_task_success(self):
  cases=[({'checked':True,'ok':True},'syntax','passed'),({'checked':False,'ok':None},'syntax','not_run'),({'executed':False},'project','not_run'),({'executed':True,'exit_code':0},'project','passed'),({'executed':True,'exit_code':None,'timed_out':True},'project','inconclusive'),({'ok':True},'runtime','passed'),({'error':'timeout'},'runtime','inconclusive')]
  for report,kind,status in cases:
   result=evidence(report,kind)['verification'];self.assertEqual(result['status'],status);self.assertIsNone(result['task_success']);self.assertTrue(result['scope'])
 def test_real_agent_light_console_waits_even_with_full_permission_mode(self):
  import agent
  from contextlib import ExitStack
  class Hub:
   calls=0
   def routes(self):return {'pc__console':(None,'console')}
   def call(self,*args,**kwargs):self.calls+=1;return {'ok':True,'text':'Command finished.'}
  for allowed in (False,True):
   hub=Hub();rounds=[0]
   def stream(payload,control):
    rounds[0]+=1
    delta={'tool_calls':[{'index':0,'id':'call_console','type':'function','function':{'name':'pc__console','arguments':'{"action":"run","command":"echo test"}'}}]} if rounds[0]==1 else {'content':'Finished.'}
    yield ('data: '+json.dumps({'choices':[{'delta':delta}]})).encode()
    yield b'data: [DONE]'
   tools=[{'type':'function','function':{'name':'pc__console','parameters':{'type':'object','properties':{'action':{'type':'string'},'command':{'type':'string'}},'required':['action']}}}]
   with ExitStack() as stack:
    for name,value in [('HUB',hub),('VRAM_AUTO',False),('tokenizer_del_modelo',lambda _:None),('tools_for',lambda *args:tools),('engine_context',lambda *args:8192),('engine_chat_stream',stream)]:stack.enter_context(patch.object(agent,name,value))
    approvals=0
    for event in agent._run_chat_stream({'model':'test','agent_profile':'light','messages':[{'role':'user','content':'Run echo test'}],'permission_mode':'full','rounds':3}):
     if event['type']=='approval':self.assertEqual(hub.calls,0);approvals+=1;APPROVALS.resolve(event['id'],allowed)
    self.assertEqual(approvals,1);self.assertEqual(hub.calls,1 if allowed else 0)
if __name__=='__main__':unittest.main()
