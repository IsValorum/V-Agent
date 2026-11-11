import json,os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from local_store import Sessions

class PerformanceRecovery(unittest.TestCase):
 def test_recovers_measured_rates_per_response(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);sessions=Sessions(root);sessions.save({'id':'chat-1','title':'Test','ts':1,'messages':[{'role':'user','content':'Hi'}]})
   run_id='a'*32;run=root/'runs'/run_id;run.mkdir(parents=True)
   (run/'meta.json').write_text(json.dumps({'id':run_id,'conversation_id':'chat-1','revision':1,'pid':os.getpid()+100000,'model':'test'}),encoding='utf8')
   events=[{'choices':[{'delta':{'content':'Answer'},'finish_reason':'stop'}],'timings':{'predicted_per_second':53.4,'prompt_per_second':1002}}]
   (run/'events.sse').write_text(''.join('data: '+json.dumps(e)+'\n\n' for e in events),encoding='utf8')
   sessions.recover_runs(run_id)
   result=sessions.get('chat-1')['messages'][-1]
   self.assertEqual(result['performance'],{'decode':53.4,'prefill':1002})
   self.assertEqual(result['content'],'Answer')
if __name__=='__main__':unittest.main()
