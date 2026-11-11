import copy,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from ui_preferences import AppearanceStore,COLORS,RANGES,ENUMS,validate_theme

def theme():
    value={'mode':'night','name':'VAL Agent'}
    for mode in ('night','day'):
        value[mode]={**dict.fromkeys(COLORS,'#123456'),**{k:low for k,(low,_) in RANGES.items()},**{k:values[0] for k,values in ENUMS.items()},'showMark':True}
    return value

class AppearanceTests(unittest.TestCase):
    def test_existing_theme_gains_new_fields_without_resetting_colors(self):
        old=theme()
        for mode in ('night','day'):
            old[mode].pop('responseOpacity');old[mode].pop('responseBlur');old[mode].pop('responseRadius');old[mode].pop('textShadow');old[mode].pop('outsideOpacity')
        restored=validate_theme(old)
        self.assertEqual(restored['night']['responseOpacity'],82);self.assertEqual(restored['night']['responseBlur'],8);self.assertEqual(restored['day']['responseRadius'],16);self.assertEqual(restored['night']['textShadow'],0);self.assertEqual(restored['night']['outsideOpacity'],70);self.assertEqual(restored['day']['outsideOpacity'],82)
        self.assertEqual(restored['day']['panel'],'#123456')
    def test_levels_and_opacity_persist_per_theme_without_overwriting_other_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'appearance.json';store=AppearanceStore(path);value=theme()
            store.save({'theme':value,'changed':[],'client_id':'appearance-client-01','sequence':1})
            value['night'].update(outsideOpacity=34,radius=24,textShadow=72,responseOpacity=54,responseBlur=18,responseRadius=22)
            store.save({'theme':value,'changed':['night.outsideOpacity','night.radius','night.textShadow','night.responseOpacity','night.responseBlur','night.responseRadius'],'client_id':'appearance-client-01','sequence':2})
            saved=AppearanceStore(path).get()['theme']
            self.assertEqual(saved['night']['responseOpacity'],54);self.assertEqual(saved['night']['responseBlur'],18);self.assertEqual(saved['night']['responseRadius'],22);self.assertEqual(saved['night']['textShadow'],72);self.assertEqual(saved['night']['outsideOpacity'],34)
            self.assertEqual(saved['night']['panel'],'#123456')
            for key,invalid in [('responseOpacity',101),('responseBlur',33),('responseRadius',37),('outsideOpacity',101)]:
                bad=copy.deepcopy(value);bad['night'][key]=invalid
                with self.assertRaises(ValueError):validate_theme(bad)
if __name__=='__main__':unittest.main()
