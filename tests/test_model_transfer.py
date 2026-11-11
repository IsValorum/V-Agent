import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path[:0]=['agent','tools','.']
import desktop_runtime
import model_import
import kv_settings


class ModelTransferTests(unittest.TestCase):
    def test_each_engine_receives_its_own_model_id_and_settings(self):
        preferences=Mock()
        settings={'sampling':{'temperature':0.4,'repetition_penalty':1.0},'context':32768,'kv':'q8_0'}
        info={'identifier':'local-123','template':''}
        result={'status':'registered','model':{'id':'llama--local-123'}}
        with patch.object(desktop_runtime,'inspect_llama_import',return_value=info),patch.object(desktop_runtime,'register_llama_import',return_value=result):
            for kind in ('llama','rust'):
                with self.subTest(kind=kind):
                    actual=desktop_runtime.import_external_model('model.gguf','Model',settings,kind,preferences)
                    self.assertEqual(actual['id'],kind+'--local-123')
                    preferences.save.assert_called_with(actual['id'],settings)
        with patch.object(model_import,'register_local_model',return_value={'status':'added','model':{'id':'model','config':'model.json'}}),patch.object(kv_settings,'describe',return_value={'options':[{'value':'q8_0'}]}):
            actual=desktop_runtime.import_external_model('model.gguf','Model',settings,'strata',preferences)
        self.assertEqual(actual['id'],'model')
        preferences.save.assert_called_with('model',settings)

    def test_unsupported_cache_is_not_saved(self):
        preferences=Mock()
        with patch.object(desktop_runtime,'inspect_llama_import',return_value={'identifier':'local-1','template':''}),patch.object(desktop_runtime,'register_llama_import',return_value={'status':'registered'}):
            result=desktop_runtime.import_external_model('model.gguf','Model',{'kv':'bf16'},'rust',preferences)
        preferences.save.assert_not_called()
        self.assertTrue(result['warnings'])

    def test_existing_strata_template_is_not_silently_overwritten(self):
        preferences=Mock()
        with tempfile.TemporaryDirectory() as tmp,patch.object(desktop_runtime,'DATA_ROOT',Path(tmp)),patch.object(model_import,'_path',return_value=Path('model.gguf')),patch.object(model_import,'_existing',return_value={'id':'model'}),patch.object(model_import,'register_local_model',return_value={'status':'already_registered','model':{'id':'model','config':'model.json'}}):
            result=desktop_runtime.import_external_model('model.gguf','Model',{'template':'{{ messages }}'},'strata',preferences)
        self.assertTrue(any('plantilla existente' in warning for warning in result['warnings']))

    def test_remote_api_does_not_claim_local_registration(self):
        with self.assertRaises(ValueError):
            desktop_runtime.import_external_model('model.gguf','Model',{},'api',Mock())


if __name__=='__main__':unittest.main()
