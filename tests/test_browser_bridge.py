import sys,threading,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from browser_bridge import BrowserBridge

class BrowserBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge=BrowserBridge()
    def tearDown(self):
        self.bridge.close()
    def test_request_is_taken_once_and_resolved(self):
        result={}
        def call():
            try:result['value']=self.bridge.request('snapshot',{'max_chars':100},5)
            except Exception as error:result['error']=error
        worker=threading.Thread(target=call);worker.start()
        for _ in range(40):
            items=self.bridge.take()
            if items:break
            time.sleep(0.02)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['action'],'snapshot')
        self.assertEqual(items[0]['args'],{'max_chars':100})
        self.assertEqual(self.bridge.take(),[])
        self.assertTrue(self.bridge.resolve(items[0]['id'],{'ok':True,'text':'hola'}))
        worker.join(2)
        self.assertEqual(result.get('value'),{'ok':True,'text':'hola'})
    def test_errors_and_timeouts_are_reported(self):
        with self.assertRaises(TimeoutError):self.bridge.request('open',{},1)
        result={}
        def call():
            try:self.bridge.request('click',{},3)
            except Exception as error:result['error']=error
        worker=threading.Thread(target=call);worker.start()
        for _ in range(40):
            items=self.bridge.take()
            if items:break
            time.sleep(0.02)
        self.assertTrue(self.bridge.resolve(items[0]['id'],None,'No hay ventana del navegador.'))
        worker.join(2)
        self.assertIsInstance(result.get('error'),ValueError)
    def test_unknown_result_is_ignored(self):
        self.assertFalse(self.bridge.resolve('missing',{'x':1}))
    def test_close_releases_waiters(self):
        result={}
        def call():
            try:self.bridge.request('open',{},10)
            except Exception as error:result['error']=str(error)
        worker=threading.Thread(target=call);worker.start()
        time.sleep(0.05);self.bridge.close();worker.join(2)
        self.assertIn('cerró',result.get('error',''))

if __name__=='__main__':unittest.main()
