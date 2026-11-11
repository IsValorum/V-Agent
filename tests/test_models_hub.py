import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path[:0] = ['agent', '.', 'tools']
import external_models
import model_hub
from projects import ProjectStore


class LMStudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.lm = home / '.lmstudio'
        self.models = self.lm / 'models'
        gguf = self.models / 'pub' / 'Repo-GGUF' / 'model-Q4_K_M.gguf'
        gguf.parent.mkdir(parents=True)
        gguf.write_bytes(b'GGUF' + b'\0' * 64)
        (gguf.parent / 'mmproj-model-f16.gguf').write_bytes(b'GGUF')
        self.gguf = gguf
        config = self.lm / '.internal' / 'user-concrete-model-default-config' / 'pub' / 'Repo-GGUF' / 'model-Q4_K_M.gguf.json'
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({'preset': '', 'operation': {'fields': [
            {'key': 'llm.prediction.temperature', 'value': 0.4},
            {'key': 'llm.prediction.topPSampling', 'value': {'checked': True, 'value': 0.9}},
            {'key': 'llm.prediction.minPSampling', 'value': {'checked': False, 'value': 0.2}},
            {'key': 'llm.prediction.promptTemplate', 'value': {'type': 'jinja', 'jinjaPromptTemplate': {'template': '{{ messages }}'}}}]},
            'load': {'fields': [{'key': 'llm.load.contextLength', 'value': 32768},
                                {'key': 'llm.load.llama.kCacheQuantizationType', 'value': {'checked': True, 'value': 'q8_0'}}]}}))
        self.config = config
        patches = [mock.patch.object(external_models, 'LMSTUDIO', self.lm),
                   mock.patch.object(external_models, 'UNSLOTH', home / '.unsloth' / 'studio'),
                   mock.patch.object(external_models, 'HF_CACHE', home / 'hf')]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_reads_settings_and_skips_projectors(self):
        models = external_models.scan()['models']
        self.assertEqual([m['name'] for m in models], ['model-Q4_K_M'])
        item = models[0]
        self.assertEqual(item['context'], 32768)
        self.assertEqual(item['kv'], 'q8_0')
        self.assertEqual(item['sampling'], {'temperature': 0.4, 'top_p': 0.9})  # unchecked min-p is ignored
        self.assertEqual(item['template'], '{{ messages }}')

    def test_export_merges_into_lmstudio_config(self):
        external_models.export_lmstudio(str(self.gguf), {'sampling': {'temperature': 0.7, 'top_k': 20}, 'context': 8192, 'kv': 'fp16'})
        data = json.loads(self.config.read_text())
        fields = {f['key']: f['value'] for f in data['operation']['fields'] + data['load']['fields']}
        self.assertEqual(fields['llm.prediction.temperature'], 0.7)
        self.assertEqual(fields['llm.prediction.topKSampling'], 20)
        self.assertEqual(fields['llm.load.contextLength'], 8192)
        self.assertEqual(fields['llm.load.llama.kCacheQuantizationType'], {'checked': True, 'value': 'f16'})
        self.assertIn('llm.prediction.promptTemplate', fields)  # untouched fields stay
        self.assertEqual(sum(f['key'] == 'llm.prediction.temperature' for f in data['operation']['fields']), 1)

    def test_export_refuses_models_outside_lmstudio(self):
        with self.assertRaises(ValueError):
            external_models.export_lmstudio(str(Path(self.tmp.name) / 'elsewhere.gguf'), {})


class UnslothTests(unittest.TestCase):
    def test_reads_scan_folders_and_per_model_params_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            studio = home / '.unsloth' / 'studio'
            studio.mkdir(parents=True)
            folder = home / 'models'
            folder.mkdir()
            (folder / 'a-Q8_0.gguf').write_bytes(b'GGUF')
            db = sqlite3.connect(studio / 'studio.db')
            db.execute('create table scan_folders (id, path, created_at, recursive)')
            db.execute('create table chat_settings (key, value_json, updated_at)')
            db.execute('create table app_settings (key, value_json, updated_at)')
            db.execute('insert into scan_folders values (1, ?, "", 0)', (str(folder),))
            db.execute('insert into chat_settings values ("inferenceParamsByModel", ?, "")',
                       (json.dumps({str(folder): {'temperature': 0.3, 'topK': -1.0, 'maxTokens': 4096.0}}),))
            db.commit()
            db.close()
            with mock.patch.object(external_models, 'UNSLOTH', studio), mock.patch.object(external_models, 'LMSTUDIO', home / 'none'), \
                    mock.patch.object(external_models, 'HF_CACHE', home / 'hf'):
                models = external_models.scan()['models']
                self.assertEqual(len(models), 1)
                self.assertEqual(models[0]['sampling'], {'temperature': 0.3, 'top_k': 0, 'max_tokens': 4096})
                target = external_models.export_unsloth('Mi modelo', {'sampling': {'temperature': 0.5}})
                self.assertEqual(json.loads(Path(target).read_text(encoding='utf-8'))['params']['temperature'], 0.5)


class HubTests(unittest.TestCase):
    def test_split_files_are_grouped_and_validated(self):
        info = {'id': 'a/b', 'siblings': [
            {'rfilename': 'm-Q4_K_M-00002-of-00002.gguf', 'size': 5, 'lfs': {'sha256': 'b' * 64, 'size': 5}},
            {'rfilename': 'm-Q4_K_M-00001-of-00002.gguf', 'size': 7, 'lfs': {'sha256': 'a' * 64, 'size': 7}},
            {'rfilename': 'mmproj-F16.gguf', 'size': 3}, {'rfilename': 'README.md', 'size': 1}]}
        with mock.patch.object(model_hub, '_request', side_effect=[json.dumps(info).encode(), b'# Hola']):
            data = model_hub.details('a/b')
        self.assertEqual(data['readme'], '# Hola')
        main = data['files'][0]
        self.assertEqual((main['name'], main['size'], main['quant'], len(main['parts'])), ('m-Q4_K_M-00001-of-00002.gguf', 12, 'Q4_K_M', 2))
        self.assertTrue(data['files'][1]['mmproj'])
        for bad in ('../x.gguf', 'a/../../b.gguf', 'x.exe', ''):
            with self.assertRaises(ValueError):
                model_hub._file(bad)
        for bad in ('a', 'a/b/c', '../a', 'a/..'):
            with self.assertRaises(ValueError):
                model_hub._repo(bad)

    def test_token_is_not_forwarded_to_other_hosts(self):
        handler = model_hub._NoAuthRedirect()
        request = urllib.request.Request('https://huggingface.co/a/b/resolve/main/x.gguf', headers={'Authorization': 'Bearer secret'})
        same = handler.redirect_request(request, None, 302, 'Found', {}, 'https://huggingface.co/other')
        other = handler.redirect_request(request, None, 302, 'Found', {}, 'https://cdn-lfs.example.org/x')
        self.assertEqual(same.get_header('Authorization'), 'Bearer secret')
        self.assertIsNone(other.get_header('Authorization'))


class ProjectAddTests(unittest.TestCase):
    def test_add_project_without_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ProjectStore(Path(tmp) / 'projects.json')
            folder = Path(tmp) / 'Mi proyecto'
            folder.mkdir()
            first = store.add(str(folder))
            again = store.add(str(folder))
            self.assertEqual(first['added']['id'], again['added']['id'])
            self.assertEqual(len(again['projects']), 1)
            self.assertEqual(again['conversations'], {})
            with self.assertRaises(ValueError):
                store.add(str(Path(tmp) / 'missing'))


if __name__ == '__main__':
    unittest.main()
