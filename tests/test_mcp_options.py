import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'agent'),str(ROOT/'web_mcp')]
from mcp_options import MCPOptions,defaults

class MCPOptionsTests(unittest.TestCase):
    def test_persistence_and_workers_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'options.json';writer=MCPOptions(path);worker=MCPOptions(path)
            self.assertEqual(worker.get(),defaults())
            writer.save({'duckduckgo':{'count':3,'visit_tokens':256},'pc':{'command_timeout':25}})
            self.assertEqual(worker.get()['duckduckgo']['count'],3)
            writer.save({'duckduckgo':{'count':7}})
            self.assertEqual(worker.get()['duckduckgo']['count'],7)
            self.assertEqual(worker.get()['duckduckgo']['visit_tokens'],256)
            self.assertEqual(worker.get()['pc']['command_timeout'],25)
    def test_validation_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            store=MCPOptions(Path(folder)/'options.json');before=store.save({'pc':{'command_timeout':45}})
            for body in ({'pc':{'command_timeout':True}},{'duckduckgo':{'visit_tokens':0}},{'pc':{'root':'C:\\'}},{'unknown':{}},{'duckduckgo':{'count':1.5}}):
                with self.assertRaises(ValueError):store.save(body)
                self.assertEqual(store.get(),before)
    def test_visit_preserves_json_and_continuation(self):
        import buscador_mcp as web
        settings={**defaults()['duckduckgo'],'visit_tokens':256,'max_result_chars':1000}
        with patch.object(web,'options',return_value=settings),patch.object(web,'read_public_page',return_value='quoted "text"\n'*1000):
            first=web.web_visit('https://example.com')
            data=json.loads(first);self.assertLessEqual(len(first),1000);self.assertTrue(data['has_more'])
            second=json.loads(web.web_visit('https://example.com',offset=data['next_offset'],page_id=data['page_id']))
            self.assertEqual(second['offset'],len(data['content']))
            self.assertEqual(data['content']+second['content'],('quoted "text"\n'*1000)[:second['next_offset']])
    def test_search_defaults_and_explicit_overrides(self):
        import buscador_mcp as web
        settings={**defaults()['duckduckgo'],'count':3,'region':'de-de','timelimit':'w','language':'en'}
        with patch.object(web,'options',return_value=settings),patch.object(web,'search',return_value=[]) as search:
            web.web_search('docs')
            self.assertEqual(search.call_args.kwargs['count'],3)
            self.assertEqual(search.call_args.kwargs['region'],'us-en')
            self.assertEqual(search.call_args.kwargs['timelimit'],'w')
            web.web_search('docs',region='mx-es',timelimit='d')
            self.assertEqual(search.call_args.kwargs['region'],'mx-es')
            self.assertEqual(search.call_args.kwargs['timelimit'],'d')
    def test_search_filters_marked_ads(self):
        import busqueda_local as local
        results=[{'title':'Ad','href':'https://ads.example','sponsored':True},{'title':'Docs','href':'https://docs.python.org','body':'Python'}]
        class Client:
            def __init__(self,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def text(self,*args,**kwargs):return results
        with patch('ddgs.DDGS',Client):
            self.assertEqual([x['title'] for x in local.search('Python',filter_ads=True)],['Docs'])
            self.assertEqual(len(local.search('Python',filter_ads=False)),2)

if __name__=='__main__':unittest.main()
