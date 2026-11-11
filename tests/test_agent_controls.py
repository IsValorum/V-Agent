import sys,tempfile,threading,unittest,json
from unittest.mock import patch
from contextlib import ExitStack
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'agent')]
from thinking_policy import inspect_template,apply
from tool_approvals import Approvals,needs_approval

class ControlsTests(unittest.TestCase):
    def test_template_modes_and_payload(self):
        binary=inspect_template('{% if enable_thinking is defined and enable_thinking %}think{% endif %}')
        self.assertEqual(binary['choices'],['none','think'])
        payload={'reasoning_effort':'xhigh','chat_template_kwargs':{'preserve_thinking':True}}
        apply(payload,'none',binary);self.assertNotIn('reasoning_effort',payload);self.assertFalse(payload['chat_template_kwargs']['enable_thinking'])
        levels=inspect_template("{% if reasoning_effort in ['low','medium','high','xhigh','none'] %}{{ reasoning_effort }}{% endif %}")
        self.assertIn('xhigh',levels['choices']);apply(payload,'xhigh',levels)
        self.assertEqual(payload['chat_template_kwargs']['reasoning_effort'],'xhigh')
        fixed=inspect_template("{% set enable_thinking = true %}{{ enable_thinking }}")
        self.assertEqual(fixed['choices'],[]);apply(payload,'high',fixed)
        self.assertNotIn('enable_thinking',payload['chat_template_kwargs']);self.assertNotIn('reasoning_effort',payload)
    def test_permission_classification(self):
        self.assertTrue(needs_approval('ask','duckduckgo__web_search',{}))
        # Ask mode: isolated local reads pass, writes, sensitive names and full-PC reads still ask.
        self.assertFalse(needs_approval('ask','pc__fs_read',{'path':'notes.md'}))
        self.assertTrue(needs_approval('ask','pc__fs_read',{'path':'.env'}))
        self.assertTrue(needs_approval('ask','pc__fs_read',{'path':'notes.md'},full_access=True))
        self.assertTrue(needs_approval('ask','pc__fs_write',{'path':'notes.md'}))
        self.assertFalse(needs_approval('auto','pc__fs_read',{'path':'file.txt'}))
        self.assertTrue(needs_approval('auto','pc__fs_write',{}))
        self.assertTrue(needs_approval('auto','unknown__tool',{}))
        self.assertTrue(needs_approval('auto','pc__code_check',{'run':True,'check':'test'}))
        self.assertFalse(needs_approval('run','pc__fs_write',{}))
    def test_approval_wait_resolve_cancel_and_expire(self):
        broker=Approvals();request=broker.create('pc__fs_write',{'path':'test.txt'})
        answer=[];thread=threading.Thread(target=lambda:answer.append(broker.wait(request['id'],threading.Event())))
        thread.start();broker.resolve(request['id'],True);thread.join(2)
        self.assertEqual(answer,[True]);self.assertFalse(broker.pending)
        with self.assertRaises(ValueError):broker.resolve(request['id'],True)
        request=broker.create('pc__shell_run',{});cancel=threading.Event();cancel.set()
        self.assertFalse(broker.wait(request['id'],cancel));self.assertFalse(broker.pending)
    def test_always_allow_is_per_chat_and_per_tool(self):
        broker=Approvals();request=broker.create('pc__fs_write',{},'chat-a')
        self.assertTrue(request['rememberable'])
        broker.resolve(request['id'],True,True)
        self.assertTrue(broker.granted('chat-a','pc__fs_write'))
        self.assertFalse(broker.granted('chat-b','pc__fs_write'))
        self.assertFalse(broker.granted('chat-a','pc__shell_run'))
        denied=broker.create('pc__shell_run',{},'chat-a');broker.resolve(denied['id'],False,True)
        self.assertFalse(broker.granted('chat-a','pc__shell_run'))
        self.assertFalse(broker.create('pc__fs_write',{})['rememberable'])
    def test_failed_large_write_gets_one_retry_before_stopping(self):
        import agent
        for failures,expect_stop in ((1,False),(2,True)):
            class Hub:
                calls=0
                def routes(self):return {'pc__fs_write':(None,'fs_write')}
                def call(self,name,args,**kwargs):
                    self.calls+=1
                    return {'ok':False,'text':'error: disk busy'} if self.calls<=failures else {'ok':True,'text':'escrito: page.html'}
            hub=Hub();rounds=[0]
            def stream(payload,control):
                rounds[0]+=1
                content='<p>'+'x'*900+'</p>'+str(rounds[0])
                delta={'tool_calls':[{'index':0,'id':'w%d'%rounds[0],'type':'function','function':{'name':'pc__fs_write','arguments':json.dumps({'path':'page.html','content':content})}}]} if rounds[0]<=2 else {'content':'Listo.'}
                yield ('data: '+json.dumps({'choices':[{'delta':delta}]})).encode()
                yield b'data: [DONE]'
            tools=[{'type':'function','function':{'name':'pc__fs_write','parameters':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']}}}]
            with ExitStack() as stack:
                for name,value in [('HUB',hub),('VRAM_AUTO',False),('tokenizer_del_modelo',lambda _:None),('tools_for',lambda *args:tools),('engine_context',lambda *args:8192),('engine_chat_stream',stream)]:stack.enter_context(patch.object(agent,name,value))
                events=list(agent._run_chat_stream({'model':'test','messages':[{'role':'user','content':'Write page'}],'permission_mode':'run','rounds':5}))
            final=[e for e in events if e.get('type')=='done'][-1]['content']
            self.assertEqual(hub.calls,2)
            self.assertEqual('No se pudo guardar el archivo' in final,expect_stop)
    def test_language_rule_names_the_language(self):
        import agent
        rule=lambda text:agent.language_rule([{'role':'user','content':text}])
        self.assertIn('Spanish',rule('Visita la web y resúmeme su contenido, por favor.'))
        self.assertIn('English',rule('Please visit the page and tell me what it says'))
        self.assertEqual(rule('Hola'),agent.LANGUAGE_RULE)
    def test_linux_rooted_path_maps_into_isolated_folder(self):
        from access_policy import AccessPolicy,AccessDenied
        with tempfile.TemporaryDirectory() as folder:
            policy=AccessPolicy(Path(folder))
            self.assertEqual(policy.path('/flowtrack.html',False),Path(folder).resolve()/'flowtrack.html')
            for outside in ('C:\\Windows\\win.ini','//server/share/x','/../escape.txt'):
                with self.assertRaises((AccessDenied,ValueError)):policy.path(outside,False)
    def test_multiple_code_blocks_are_not_a_tool_loop(self):
        import agent
        content='```html\n<p>Test</p>\n```\n```css\np{color:red}\n```\n```js\nconsole.log(1)\n```'
        def stream(payload,control):
            yield ('data: '+json.dumps({'choices':[{'delta':{'content':content}}]})).encode()
            yield b'data: [DONE]'
        control=agent.GenerationControl()
        with patch.object(agent,'VRAM_AUTO',False),patch.object(agent,'tokenizer_del_modelo',lambda _:None),patch.object(agent,'tools_for',lambda *args:[]),patch.object(agent,'engine_context',lambda *args:8192),patch.object(agent,'engine_chat_stream',stream):
            events=list(agent._run_chat_stream({'model':'test','messages':[{'role':'user','content':'Give HTML, CSS and JS'}]},control))
        self.assertFalse(control.bucle)
        self.assertEqual(next(e['content'] for e in events if e['type']=='done'),content)
    def test_timings_reach_tool_orchestration_stream(self):
        import agent
        def stream(payload,control):
            yield ('data: '+json.dumps({'choices':[{'delta':{'content':'Complete'},'finish_reason':'stop'}], 'timings':{'predicted_per_second':53.4,'prompt_per_second':1002}})).encode()
            yield b'data: [DONE]'
        with patch.object(agent,'VRAM_AUTO',False),patch.object(agent,'tokenizer_del_modelo',lambda _:None),patch.object(agent,'tools_for',lambda *args:[]),patch.object(agent,'engine_context',lambda *args:8192),patch.object(agent,'engine_chat_stream',stream):
            events=list(agent._run_chat_stream({'model':'test','messages':[{'role':'user','content':'Hello'}]}))
        self.assertEqual(next(e['timings']['predicted_per_second'] for e in events if e['type']=='timings'),53.4)
        self.assertEqual(next(e['content'] for e in events if e['type']=='done'),'Complete')
    def test_native_stream_keeps_code_blocks_and_stops_empty_frame_loops(self):
        import agent
        for empty in (False,True):
            content='\n' if empty else ('```html\n<p>Test</p>\n```\n'*10)
            emitted=[]
            def stream(payload,control):
                for i in range(100 if empty else 1):
                    emitted.append(i)
                    yield ('data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n').encode()
                    yield b'\n'
            control=agent.GenerationControl()
            with patch.object(agent,'VRAM_AUTO',False),patch.object(agent,'tokenizer_del_modelo',lambda _:None),patch.object(agent,'tools_for',lambda *args:[]),patch.object(agent,'engine_context',lambda *args:8192),patch.object(agent,'engine_chat_stream',stream):
                output=b''.join(agent._run_chat_stream({'model':'test','messages':[{'role':'user','content':'Code'}],'native_stream':True},control))
            if empty:self.assertTrue(control.bucle);self.assertLess(len(emitted),100)
            else:self.assertFalse(control.bucle);self.assertIn(b'<p>Test</p>',output)
    def test_real_agent_loop_pauses_before_call_and_denial_never_executes(self):
        import agent
        from tool_approvals import APPROVALS
        class Hub:
            calls=0
            def routes(self):return {'pc__fs_write':(None,'fs_write')}
            def call(self,*args,**kwargs):self.calls+=1;return {'ok':True,'text':'file content'}
        for allow in (False,True):
            hub=Hub();rounds=[0]
            def stream(payload,control):
                rounds[0]+=1
                delta={'tool_calls':[{'index':0,'id':'test_call','type':'function','function':{'name':'pc__fs_write','arguments':'{"path":"file.txt","content":"x"}'}}]} if rounds[0]==1 else {'content':'Finished.'}
                yield ('data: '+json.dumps({'choices':[{'delta':delta}]})).encode()
                yield b'data: [DONE]'
            tools=[{'type':'function','function':{'name':'pc__fs_write','parameters':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']}}}]
            with ExitStack() as stack:
                for name,value in [('HUB',hub),('VRAM_AUTO',False),('tokenizer_del_modelo',lambda _:None),('tools_for',lambda *args:tools),('engine_context',lambda *args:8192),('engine_chat_stream',stream)]:stack.enter_context(patch.object(agent,name,value))
                approvals=0
                for event in agent._run_chat_stream({'model':'test','messages':[{'role':'user','content':'Write file'}],'permission_mode':'ask','rounds':3}):
                    if event['type']=='approval':
                        self.assertEqual(hub.calls,0);approvals+=1;APPROVALS.resolve(event['id'],allow)
                self.assertEqual(approvals,1)
                self.assertEqual(hub.calls,1 if allow else 0)

if __name__=='__main__':unittest.main()
