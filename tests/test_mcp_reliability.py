import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0]=['agent','web_mcp','.']
from access_policy import AccessPolicy
import busqueda_local
import pc_mcp
import verify
from draft_recovery import extract_file, resume_draft
from draft_store import DraftStore
from tool_contract import check_template


class SearchTests(unittest.TestCase):
    def test_computer_and_admin_need_explicit_selection(self):
        import agent
        from unittest.mock import MagicMock
        hub=MagicMock()
        hub.openai_tools.return_value=[{'type':'function','function':{'name':name,'description':'','parameters':{'type':'object','properties':{}}}} for name in ('computer__screen_capture','admin__start','pc__fs_read')]
        with patch.object(agent,'HUB',hub),patch.object(agent.ACCESS,'snapshot',return_value={'mode':'full_pc'}),patch('extensions.enabled_configs',return_value={}):
            for selections,expected in [({'files':True},{'pc__fs_read'}),({'computer':True},{'computer__screen_capture'}),({'admin':True},{'admin__start'})]:
                actual={item['function']['name'] for item in agent.tools_for(selections,agent_profile='advanced')}
                self.assertEqual(actual,expected)

    def test_fast_fallback_and_filtering(self):
        calls=[]
        class Client:
            def __init__(self,**kw):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def text(self,query,**kwargs):
                calls.append(kwargs)
                if kwargs['backend']=='duckduckgo':return [{'title':'Ad','href':'https://googleadservices.com/x','is_ad':True}]
                if kwargs['backend']=='yahoo':return [{'title':'Python','href':'https://python.org/','body':'Official docs'}]
                raise AssertionError('Unnecessary fallback')
        with patch('ddgs.DDGS',Client):
            results=busqueda_local.search('Python',count=5,region='us-en',strict_errors=True)
        self.assertEqual([c['backend'] for c in calls],['duckduckgo','yahoo'])
        self.assertEqual(calls[0]['max_results'],8);self.assertEqual(results[0]['link'],'https://python.org/')

    def test_glm_template_uses_its_own_tool_parser(self):
        template='''{% for m in messages %}{{ m.content }}{% if m.tool_calls %}{% for c in m.tool_calls %}<tool_call>{{ c.function.name }}{% for k,v in c.function.arguments.items() %}<arg_key>{{ k }}</arg_key><arg_value>{{ v if v is string else (v|tojson) }}</arg_value>{% endfor %}</tool_call>{% endfor %}{% endif %}{% endfor %}'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'chat_template.jinja';path.write_text(template,encoding='utf8')
            result=check_template(path)
        self.assertTrue(result['ok'],result)

    def test_dsml_and_lfm_templates_use_their_own_parsers(self):
        cases=[
          '''{% for m in messages %}{{ m.content }}{% if m.tool_calls %}<｜DSML｜tool_calls>{% for c in m.tool_calls %}<｜DSML｜invoke name="{{ c.function.name }}">{% for k,v in c.function.arguments.items() %}<｜DSML｜parameter name="{{ k }}" string="{{ 'true' if v is string else 'false' }}">{{ v if v is string else (v|tojson) }}</｜DSML｜parameter>{% endfor %}</｜DSML｜invoke>{% endfor %}</｜DSML｜tool_calls>{% endif %}{% endfor %}''',
          '''{% for m in messages %}{{ m.content }}{% if m.tool_calls %}<|tool_call_start|>[{% for c in m.tool_calls %}{{ c.function.name }}({% for k,v in c.function.arguments.items() %}{{ k }}={{ v|tojson }}{{ ',' if not loop.last }}{% endfor %}){{ ',' if not loop.last }}{% endfor %}]<|tool_call_end|>{% endif %}{% endfor %}''']
        for template in cases:
            with self.subTest(template=template[:50]), tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'chat_template.jinja';path.write_text(template,encoding='utf8')
                result=check_template(path)
                self.assertTrue(result['ok'],result)


class EditingTests(unittest.TestCase):
    def test_syntax_checks_report_real_scope(self):
        for name,content in [('test.py','def broken(:\n pass'),('test.json','{"x":}')]:
            report=verify.verificar_contenido(content,name)
            self.assertTrue(report['checked']);self.assertFalse(report['ok']);self.assertFalse(report['info']['runtime_checked'])
        unknown=verify.verificar_contenido('const x: number = 1','test.ts')
        self.assertFalse(unknown['checked']);self.assertIsNone(unknown['ok'])

    def test_edit_retains_crlf_and_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'test.txt'; path.write_bytes(b'\xef\xbb\xbfalpha\r\nbeta\r\n')
            pc_mcp.call('fs_edit',{'path':'test.txt','old_text':'beta','new_text':'changed\nmore'},policy=AccessPolicy(root))
            self.assertEqual(path.read_bytes(),b'\xef\xbb\xbfalpha\r\nchanged\r\nmore\r\n')

    def test_failed_batch_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'test.txt';path.write_text('alpha beta',encoding='utf8')
            with self.assertRaises(ValueError):
                pc_mcp.call('fs_edit',{'path':'test.txt','edits':[{'old_text':'alpha','new_text':'new'}, {'old_text':'missing','new_text':'x'}]},policy=AccessPolicy(root))
            self.assertEqual(path.read_text(encoding='utf8'),'alpha beta')

    def test_line_view_does_not_skip_partially_displayed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'long.txt';path.write_text('a'*5000+'\n'+'b'*5000+'\nlast\n',encoding='utf8')
            policy=AccessPolicy(root)
            result=pc_mcp.call('fs_read',{'path':'long.txt','linea':1},policy=policy)
            self.assertIn('linea=2',result)
            self.assertNotIn('b'*100,result)
    def test_one_long_line_can_continue_by_character(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'long.txt';path.write_text('first\n'+'z'*10000,encoding='utf8')
            policy=AccessPolicy(root)
            result=pc_mcp.call('fs_read',{'path':'long.txt','linea':2},policy=policy)
            import re
            offset=int(re.search(r'offset=(\d+)',result)[1])
            self.assertEqual(pc_mcp.call('fs_read',{'path':'long.txt','offset':offset,'max_chars':10},policy=policy)[:10],'z'*10)

    def test_stopped_draft_preserves_received_content(self):
        with tempfile.TemporaryDirectory() as directory:
            policy=AccessPolicy(Path(directory));write=lambda path,text:(path.parent.mkdir(parents=True,exist_ok=True),path.write_text(text,encoding='utf8'))
            store=DraftStore(policy,write)
            raw='{"name":"pc__fs_write","arguments":{"path":"example.py","content":"print(\\"hola\\")\\nvalue = '
            event={'id':'call-1','name':'pc__fs_write','type':'tool_draft','delta':raw}
            store.observe(event);store.flush()
            recovered=resume_draft(policy,event['draft_id'])
            self.assertFalse(recovered['complete'])
            self.assertEqual(policy.path(recovered['path']).read_text(encoding='utf8'),'print("hola")\nvalue = ')
            self.assertEqual(extract_file({'raw':raw})[1],'print("hola")\nvalue = ')

    def test_denied_write_leaves_no_draft_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            policy=AccessPolicy(Path(directory));write=lambda path,text:(path.parent.mkdir(parents=True,exist_ok=True),path.write_text(text,encoding='utf8'))
            store=DraftStore(policy,write);args={'path':'secret.txt','content':'private'}
            # A blocked first attempt, then the same file denied by the user.
            store.observe({'id':'a','name':'pc__fs_write','type':'tool','args':{**args,'path':'/abs/secret.txt'},'status':'validating'})
            store.observe({'id':'a','name':'pc__fs_write','type':'tool_result','status':'blocked','ok':False,'executed':False})
            store.observe({'id':'b','name':'pc__fs_write','type':'tool','args':args,'status':'validating'})
            store.observe({'id':'b','name':'pc__fs_write','type':'tool_result','status':'blocked','ok':False,'executed':False,'denied':True})
            store.flush()
            leftovers=[p.name for p in Path(directory).rglob('*') if p.is_file()]
            self.assertEqual(leftovers,[])

    def test_write_reports_syntax_errors_for_config_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            policy=AccessPolicy(Path(directory))
            for name,text in (('a.yaml','k: [1, 2\nx: 3\n'),('a.toml','[t\nk = 1\n'),('a.xml','<r><a></r>')):
                result=pc_mcp.call('fs_write',{'path':name,'content':text},policy=policy)
                self.assertIn('Syntax check failed',result,name)
    def test_java_is_compiled_not_run(self):
        import shutil as sh
        if not sh.which('javac'):self.skipTest('javac not installed')
        bad=verify.verificar_contenido('public class A { void f(){ int x = 1 } }','A.java')
        good=verify.verificar_contenido('public class A { void f(){ int x = 1; } }','A.java')
        self.assertFalse(bad['ok']);self.assertTrue(good['ok'])
    def test_listing_hides_internal_drafts_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'drafts').mkdir();(root/'notes.txt').write_text('x',encoding='utf8')
            listing=pc_mcp.call('fs_list',{'path':'.'},policy=AccessPolicy(root))
            self.assertIn('notes.txt',listing);self.assertNotIn('drafts',listing)

if __name__=='__main__':unittest.main()
