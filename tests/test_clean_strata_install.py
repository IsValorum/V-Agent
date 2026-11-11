import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'agent'),str(ROOT/'tools'),str(ROOT)]
import model_import


class CleanStrataInstall(unittest.TestCase):
    def test_unknown_architecture_can_be_inspected_without_a_bundled_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=root/'model.gguf';model.write_bytes(b'gguf')
            profiles=root/'profiles.json';profiles.write_text('{"ignored_models":[]}',encoding='utf8')
            metadata={'general.architecture':'future_arch','tokenizer.chat_template':'{{ messages }}'}
            with patch.object(model_import,'ROOT',root),patch.object(model_import,'PROFILES',profiles),patch.object(model_import,'_metadata',return_value=metadata):
                result=model_import.inspect_local_model(str(model))
            self.assertEqual(result['architecture'],'future_arch')
            self.assertTrue(result['warnings'])

    def test_import_uses_downloaded_engine_without_old_default_config(self):
        import engine_updates, strata_tokenizer
        from serve import frontend
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=root/'model.gguf';model.write_bytes(b'gguf')
            profiles=root/'profiles.json'
            presets={name:{'sampling':{}} for name in ('code','agent')}
            profiles.write_text(json.dumps({'profiles':presets,'models':{}}),encoding='utf8')
            engine=root/'download'/'strata-poly.exe';engine.parent.mkdir();engine.write_bytes(b'engine')
            info={'path':str(model),'name':'Model','architecture':'lfm2moe','trained_context':32768}
            def extract(_path,output):Path(output,'tokenizer').mkdir()
            tokenizer=type('Tokenizer',(),{'special_ids':{},'encode':lambda *a,**kw:[1]})()
            with patch.object(model_import,'ROOT',root),patch.object(model_import,'PROFILES',profiles),patch.object(model_import,'ASSETS',root/'assets'),patch.object(model_import,'LOG_ROOT',root),patch.object(model_import,'inspect_local_model',return_value=info),patch.object(model_import,'_metadata',return_value={'tokenizer.chat_template':'{{ messages }}'}),patch.object(engine_updates,'executable',return_value=engine),patch.object(strata_tokenizer,'extract',side_effect=extract),patch.object(strata_tokenizer.Tokenizer,'from_dir',return_value=tokenizer),patch.object(frontend.ChatTemplate,'render',return_value='hello'):
                result=model_import.register_local_model(str(model))
            config=json.loads(Path(result['model']['config']).read_text(encoding='utf8'))
            self.assertEqual(config['exe'],str(engine))
            self.assertEqual(config['port'],19382)
            self.assertTrue(config['_val_managed_engine'])
            self.assertIn(str(engine.parent),config['lib_dirs'])

    def test_start_without_models_provides_actionable_error_without_launching(self):
        import agent
        with patch.object(agent.registry,'discover',return_value=[]),patch.object(agent,'ensure_engine') as launch:
            with self.assertRaisesRegex(ValueError,'Añade un modelo'):
                agent.start_engine()
            launch.assert_not_called()

    def test_start_without_selection_uses_an_available_model(self):
        import agent
        models=[{'status':'unavailable','config':'bad.json'},{'status':'available','config':'good.json'}]
        with patch.object(agent.registry,'discover',return_value=models),patch.object(agent,'ensure_engine') as launch:
            self.assertEqual(agent.start_engine()['status'],'running')
            launch.assert_called_once_with('good.json')

    def test_managed_vision_encoder_tracks_engine_without_overwriting_custom(self):
        import runtime_paths
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);active=root/'new'/'strata-vision.exe'
            with patch.object(runtime_paths,'DATA_ROOT',root),patch.object(runtime_paths,'RUNTIME_ROOT',root/'runtime'),patch.object(runtime_paths,'strata_vision_executable',return_value=active):
                self.assertEqual(runtime_paths._managed_vision_encoder(str(root/'runtime'/'strata'/'strata-vision.exe')),str(active))
                self.assertEqual(runtime_paths._managed_vision_encoder(str(root/'engine-updates'/'strata'/'old'/'strata-vision.exe')),str(active))
                self.assertEqual(runtime_paths._managed_vision_encoder(str(root/'custom'/'strata-vision.exe')),str(root/'custom'/'strata-vision.exe'))


if __name__=='__main__':unittest.main()
