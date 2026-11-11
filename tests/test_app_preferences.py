import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from app_preferences import AppPreferences
class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'settings/client.json';self.store=AppPreferences(self.path)
    def tearDown(self):self.tmp.cleanup()
    def test_defaults_and_persistence(self):
        self.assertEqual(self.store.get()['language'],'es');self.store.save({'language':'de'});self.assertEqual(AppPreferences(self.path).get()['language'],'de')
    def test_invalid_changes_leave_saved_value(self):
        self.store.save({'language':'pt'})
        for body in ({'language':'invalid'},{'language':'en','temperature':2},{'language':['en']},None):
            with self.assertRaises((ValueError,TypeError)):self.store.save(body)
            self.assertEqual(self.store.get()['language'],'pt')
    def test_bad_file_falls_back(self):
        self.path.parent.mkdir(parents=True);self.path.write_text('{bad');self.assertEqual(self.store.get()['language'],'es')
    def test_corrupt_file_is_preserved_when_saving(self):
        self.path.parent.mkdir(parents=True);self.path.write_text('{bad',encoding='utf8')
        self.store.save({'language':'en'})
        copies=list(self.path.parent.glob('client.json.corrupt-*'))
        self.assertEqual(len(copies),1);self.assertEqual(copies[0].read_text(encoding='utf8'),'{bad')
        self.assertEqual(self.store.get()['language'],'en')
    def test_recovers_backup_before_saving(self):
        self.store.save({'language':'fr'});self.store.save({'animation_ms':1000})
        self.path.write_text('{bad',encoding='utf8')
        self.assertEqual(self.store.get()['language'],'fr')
        self.store.save({'agent_profile':'light'})
        self.assertEqual(self.store.get()['language'],'fr');self.assertEqual(self.store.get()['agent_profile'],'light')
        self.assertEqual(len(list(self.path.parent.glob('client.json.corrupt-*'))),1)
    def test_motion_is_persistent_and_independent_of_language(self):
        self.assertEqual(self.store.get()['animation_ms'],620)
        self.store.save({'language':'en','animation_ms':1000})
        self.store.save({'language':'fr'})
        self.assertEqual(AppPreferences(self.path).get(),{'language':'fr','animation_ms':1000,'agent_profile':'balanced','decoration':{},'windows':{},'tour_done':False})
        for value in (0,1601,True,620.5,'620'):
            with self.assertRaises(ValueError):self.store.save({'animation_ms':value})
        self.assertEqual(self.store.get()['animation_ms'],1000)
    def test_decoration_persists_without_overwriting_other_preferences(self):
        self.store.save({'language':'en','animation_ms':220})
        d={'style':'none','color':'#96e4ce','intensity':45}
        self.store.save({'decoration':d})
        self.assertEqual(AppPreferences(self.path).get()['decoration'],d)
        self.assertEqual(self.store.get()['animation_ms'],220)
        with self.assertRaises(ValueError):self.store.save({'decoration':{'style':'bad'}})
    def test_window_sizes_persist_and_reject_invalid_geometry(self):
        self.store.save({'windows':{'settings':{'width':520,'height':600}}})
        self.store.save({'language':'en'})
        self.assertEqual(AppPreferences(self.path).get()['windows']['settings'],{'width':520,'height':600})
        for value in ({'settings':{'width':-1,'height':600}},{'bad':{'width':300,'height':300}},{'model':{'width':True,'height':400}}):
            with self.assertRaises(ValueError):self.store.save({'windows':value})
    def test_window_updates_merge_independent_panels(self):
        self.store.save({'windows':{'model':{'width':300,'height':600}}})
        self.store.save({'windows':{'tools':{'width':350,'height':550}}})
        self.assertEqual(self.store.get()['windows'],{'model':{'width':300,'height':600},'tools':{'width':350,'height':550}})
    def test_logo_and_options_persist_without_changing_permissions(self):
        self.store.save({'agent_profile':'light','language':'es'})
        design={'style':'none','intensity':36,'color':'#d2ad78','palette':'gold','logo':'jade','motif':'corners','background':'collection','version':2}
        self.store.save({'decoration':design})
        self.assertEqual(AppPreferences(self.path).get()['decoration'],design)
        self.assertEqual(self.store.get()['agent_profile'],'light')
        for key,value in [('logo','../other'),('motif','unknown'),('background','https://other'),('palette','other'),('version',True)]:
            with self.assertRaises(ValueError):self.store.save({'decoration':{**design,key:value}})
        self.store.save({'decoration':{'style':'none','intensity':25,'color':'#00ff00'}})
        self.assertEqual(self.store.get()['agent_profile'],'light')
    def test_amoled_and_logo_size_round_trip(self):
        self.store.save({'agent_profile':'light','language':'de'})
        for style in ('none',):
            for color in ('gold','silver','jade','blue','rose','ruby','violet','ivory'):
                design={'style':style,'intensity':36,'color':'#80b6df','palette':color,'logo':color,'amoled':True,'logoSize':360,'appIcon':color,'showGreeting':False}
                self.store.save({'decoration':design})
                self.assertEqual(AppPreferences(self.path).get()['decoration'],design)
        for key,value in [('showGreeting',0),('appIcon','../bad'),('amoled','true'),('amoled',1),('logoSize',63),('logoSize',361),('logoSize',True)]:
            with self.assertRaises(ValueError):self.store.save({'decoration':{**design,key:value}})
        self.assertEqual(self.store.get()['agent_profile'],'light')
        self.assertEqual(self.store.get()['language'],'de')
if __name__=='__main__':unittest.main()
