import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from pc_mcp import _format_browser_snapshot

class BrowserSnapshotFormatTests(unittest.TestCase):
    def test_snapshot_keeps_selectors_inside_result_limit(self):
        items=[{'selector':'[data-val-ref="r-%d"]'%i,'tag':'a','type':'','text':'Elemento %d'%i,'href':'https://example.com/%d'%i} for i in range(100)]
        result={'ok':True,'title':'Prueba','url':'https://example.com/','text':'x'*20000,'items':items}
        output=_format_browser_snapshot(result,12000)
        self.assertLessEqual(len(output),7800)
        self.assertIn('Elementos interactivos:',output)
        self.assertIn('[data-val-ref="r-1"]',output)
        self.assertIn('texto recortado',output)
    def test_text_only_uses_budget(self):
        result={'ok':True,'title':'Larga','url':'https://example.com/','text':'y'*20000,'items':[]}
        output=_format_browser_snapshot(result,12000)
        self.assertLessEqual(len(output),7800)
        self.assertIn('y'*1000,output)
    def test_error_is_readable(self):
        output=_format_browser_snapshot({'ok':False,'error':'sin ventana'},12000)
        self.assertIn('sin ventana',output)

if __name__=='__main__':unittest.main()
