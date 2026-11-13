import base64,json,sys,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from pc_mcp import _format_browser_snapshot,_clean_snapshot_href
import browser_mcp

class BrowserSnapshotFormatTests(unittest.TestCase):
    def test_snapshot_keeps_selectors_inside_result_limit(self):
        items=[{'selector':'[data-val-ref="r-%d"]'%i,'tag':'a','type':'','text':'Element %d'%i,'href':'https://example.com/%d'%i} for i in range(100)]
        result={'ok':True,'title':'Test','url':'https://example.com/','text':'x'*20000,'items':items}
        output=_format_browser_snapshot(result,12000)
        self.assertLessEqual(len(output),7800)
        self.assertIn('Interactive elements:',output)
        self.assertIn('[data-val-ref="r-1"]',output)
        self.assertIn('text truncated',output)
    def test_text_only_uses_budget(self):
        result={'ok':True,'title':'Long','url':'https://example.com/','text':'y'*20000,'items':[]}
        output=_format_browser_snapshot(result,12000)
        self.assertLessEqual(len(output),7800)
        self.assertIn('y'*1000,output)
    def test_error_is_readable(self):
        output=_format_browser_snapshot({'ok':False,'error':'no window'},12000)
        self.assertIn('no window',output)
    def test_cleans_bing_tracking_redirects_and_utm_params(self):
        encoded='a1'+base64.urlsafe_b64encode(b'https://example.org/docs?utm_source=bing&id=7').decode().rstrip('=')
        bing_url=f'https://www.bing.com/ck/a?!&&p=123&u={encoded}&ntb=1'
        self.assertEqual(_clean_snapshot_href(bing_url),'https://example.org/docs?id=7')
    def test_autobrowser_snapshot_trims_to_budget_and_caps_items(self):
        fake_page=MagicMock()
        fake_page.evaluate.return_value={
            'ok':True,'title':'T','url':'https://example.org','text':'hello',
            'items':[{'selector':f'[data-val-ref="v-{i}"]','tag':'a','text':'Item '*15,'href':'https://example.org/'+'x'*120} for i in range(80)]
        }
        with patch.object(browser_mcp,'_page',return_value=fake_page):
            raw=browser_mcp.snapshot(max_chars=1200,max_items=60)
        data=json.loads(raw)
        self.assertLess(len(data['items']),80)
        self.assertGreater(data['more_items'],0)
        self.assertLessEqual(len(json.dumps(data['items'])),6000)
        with patch.object(Path,'is_file',return_value=False),patch.dict('os.environ',{'VAL_BROWSER_PATH':'','VAL_EDGE_PATH':''}):
            with self.assertRaises(browser_mcp.CdpError) as err:
                browser_mcp._edge_path()
        self.assertIn('Edge',str(err.exception))
    def test_autobrowser_click_reports_new_tab_and_press_reports_navigation_submit(self):
        old_page=MagicMock();new_page=MagicMock()
        old_page.evaluate.side_effect=[
            'https://www.bing.com/search?q=a',
            {'ok':True,'tag':'a','text':'Result'},
            'https://www.bing.com/search?q=b',
            {'ok':True,'pressed':'Enter','submitted':False},
            'https://www.bing.com/search?q=b&form=QBRE',
        ]
        new_page.evaluate.side_effect=['complete','https://www.idealo.es/','Idealo','Idealo normal text']
        pages_calls=[
            [{'id':'t0','url':'https://www.bing.com/search?q=a'}],
            [{'id':'t0','url':'https://www.bing.com/search?q=a'},{'id':'t1','url':'https://www.idealo.es/'}],
            [{'id':'t0','url':'https://www.bing.com/search?q=a'},{'id':'t1','url':'https://www.idealo.es/'}],
            [{'id':'t0','url':'https://www.bing.com/search?q=a'},{'id':'t1','url':'https://www.idealo.es/'}],
            [{'id':'t0','url':'https://www.bing.com/search?q=b'}],
            [{'id':'t0','url':'https://www.bing.com/search?q=b'}],
        ]
        with patch.object(browser_mcp,'_page',return_value=old_page),patch.object(browser_mcp,'_list_pages',side_effect=pages_calls),patch.object(browser_mcp,'_connect_target',return_value=new_page):
            clicked=json.loads(browser_mcp.click('[data-val-ref="r1"]'))
        self.assertTrue(clicked['new_tab']);self.assertEqual(clicked['url'],'https://www.idealo.es/');self.assertEqual(clicked['tab_index'],1);self.assertEqual(clicked['active_index'],1);self.assertEqual(clicked['tab_count'],2)
        old_page.evaluate.side_effect=['https://www.bing.com/search?q=b',{'ok':True,'pressed':'Enter','submitted':False},'https://www.bing.com/search?q=new','complete','https://www.bing.com/search?q=new','Bing','Bing results']
        with patch.object(browser_mcp,'_page',return_value=old_page),patch.object(browser_mcp,'_list_pages',return_value=[{'id':'t0'}]):
            pressed=json.loads(browser_mcp.press('Enter','input[name=q]'))
        self.assertTrue(pressed['submitted']);self.assertTrue(pressed['navigated']);self.assertEqual(pressed['url'],'https://www.bing.com/search?q=new')
    def test_autobrowser_cookies_summarizes_by_default(self):
        fake_page=MagicMock()
        fake_page.send.return_value={'cookies':[{'name':'OParams','value':'x'*2000,'domain':'.bing.com','path':'/','secure':True,'httpOnly':True,'session':False}]}
        with patch.object(browser_mcp,'_page',return_value=fake_page):
            summary=json.loads(browser_mcp.cookies())
            full=json.loads(browser_mcp.cookies(include_values=True))
        self.assertEqual(summary['count'],1);self.assertEqual(summary['domains'],{'.bing.com':1})
        self.assertNotIn('value',summary['cookies'][0]);self.assertEqual(summary['cookies'][0]['value_len'],2000)
        self.assertEqual(full['cookies'][0]['value'],'x'*2000)
    def test_autobrowser_tabs_new_reports_active_index_and_server_gate_alternatives(self):
        fake_page=MagicMock();fake_page.evaluate.return_value='https://example.org/'
        pages=[{'id':'p0','url':'https://a.test','title':'A'},{'id':'p1','url':'https://example.org/','title':'B'}]
        with patch.dict(browser_mcp.STATE,{'port':9222,'target':pages[1]}),patch.object(browser_mcp,'_start'),patch.object(browser_mcp,'_http_json',return_value=pages[1]),patch.object(browser_mcp,'_connect_target',return_value=fake_page),patch.object(browser_mcp,'_navigate',return_value=fake_page),patch.object(browser_mcp,'_list_pages',return_value=pages):
            opened=json.loads(browser_mcp.tabs('new','https://example.org/'))
            listed=json.loads(browser_mcp.tabs('list'))
        self.assertEqual(opened['active_index'],1);self.assertTrue(opened['switched']);self.assertEqual(opened['tab_count'],2)
        self.assertEqual(listed['active_index'],1);self.assertTrue(listed['tabs'][1]['active'])
        hint=browser_mcp._server_gate_hint('https://duckduckgo.com/static-pages/home-error/418.html','DuckDuckGo - Protection. Privacy. Peace of mind.')
        self.assertTrue(hint['server_blocked']);self.assertIn('pc__browser',hint['alternatives'][0])
    def test_press_retries_when_autocomplete_consumes_first_enter(self):
        page=MagicMock()
        url=['https://www.bing.com/']
        calls=[]
        def eval_fn(expr):
            if expr=='location.href':return url[0]
            if expr=='document.readyState':return 'complete'
            if expr=='document.title':return 'Bing'
            if 'document.body.innerText' in expr:return 'Search results'
            calls.append(expr)
            if len(calls)==1:return {'ok':True,'pressed':'Enter','submitted':False}
            url[0]='https://www.bing.com/search?q=test'
            return {'ok':True,'pressed':'Enter','submitted':True}
        page.evaluate.side_effect=eval_fn
        with patch.object(browser_mcp,'_page',return_value=page),patch.object(browser_mcp,'_list_pages',return_value=[{'id':'t0'}]):
            out=json.loads(browser_mcp.press('Enter','input[name=q]'))
        self.assertTrue(out['submitted']);self.assertTrue(out['navigated']);self.assertEqual(len(calls),2)
    def test_autobrowser_open_flags_google_sorry_and_cloudflare_challenge(self):
        for target_url,title,body in [
            ('https://www.google.com/sorry/index?continue=x','https://www.google.com/sorry/index','Our systems have detected unusual traffic from your computer network.'),
            ('https://example.com/cdn-cgi/challenge-platform','Just a moment...','Enable JavaScript and cookies to continue challenge-platform'),
            ('https://search.marginalia.nu/search?query=test','agent harness - Marginalia Search','Wait A Moment — The search engine is currently seeing a lot of fairly aggressive bot activity. Please wait for 1 seconds before proceeding.'),
            ('https://example.org/app','App','Checking your browser before accessing this site...'),
        ]:
            fake_page=MagicMock()
            fake_page.evaluate.side_effect=[target_url,title,body]
            with patch.object(browser_mcp,'_navigate',return_value=fake_page),patch.object(browser_mcp,'_list_pages',return_value=[{'id':'p0'}]):
                opened=json.loads(browser_mcp.open(target_url))
            self.assertTrue(opened.get('server_blocked'),msg=target_url)
            self.assertIn('user_suggestion',opened)
        snap_js=browser_mcp._snapshot_js(12000,50)
        self.assertIn('shadowRoot',snap_js);self.assertIn('contentDocument',snap_js)
        self.assertIn('shadowRoot',browser_mcp._FIND_EL_JS);self.assertIn('contentDocument',browser_mcp._FIND_EL_JS)
    def test_autobrowser_marginalia_real_results_and_empty_results_not_blocked(self):
        real_page=MagicMock()
        real_page.evaluate.side_effect=[
            'https://search.marginalia.nu/search?query=agent+harness',
            'agent harness - Marginalia Search',
            {'head':'Wait A Moment hidden banner\nAgent Harness | Atomic CRM','len':2500,'links':5},
        ]
        with patch.object(browser_mcp,'_navigate',return_value=real_page),patch.object(browser_mcp,'_list_pages',return_value=[{'id':'p0'}]):
            opened=json.loads(browser_mcp.open('https://search.marginalia.nu/search?query=agent+harness'))
        self.assertFalse(opened.get('server_blocked',False))
        self.assertFalse(opened.get('empty_results',False))
        empty_page=MagicMock()
        empty_page.evaluate.side_effect=[
            'https://search.marginalia.nu/search?query=agente',
            'agente - Marginalia Search',
            {'head':'No search results found. Marginalia Search only supports queries in the English language.','len':120,'links':0},
        ]
        with patch.object(browser_mcp,'_navigate',return_value=empty_page),patch.object(browser_mcp,'_list_pages',return_value=[{'id':'p0'}]):
            opened_empty=json.loads(browser_mcp.open('https://search.marginalia.nu/search?query=agente'))
        self.assertFalse(opened_empty.get('server_blocked',False))
        self.assertTrue(opened_empty.get('empty_results'))
        wait_page=MagicMock()
        wait_page.evaluate.side_effect=[
            'https://search.marginalia.nu/search?query=test',
            'test - Marginalia Search',
            {'head':'Wait A Moment - seeing a lot of fairly aggressive bot activity.','len':90,'links':0},
        ]
        with patch.object(browser_mcp,'_navigate',return_value=wait_page),patch.object(browser_mcp,'_list_pages',return_value=[{'id':'p0'}]):
            opened_wait=json.loads(browser_mcp.open('https://search.marginalia.nu/search?query=test'))
        self.assertTrue(opened_wait.get('server_blocked'))
        self.assertEqual(opened_wait.get('gate_kind'),'interstitial')

if __name__=='__main__':unittest.main()
