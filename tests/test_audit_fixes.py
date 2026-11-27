"""Fixes from the code audit of 1.1.16: registry MCP names, oversized document parts."""
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import doc_extractor  # noqa: E402
import extensions  # noqa: E402


class RegistryNames(unittest.TestCase):
    def test_every_registry_name_becomes_a_valid_local_name(self):
        for raw in ('io.github/foo', '1abc', 'a//b', '__x__', 'x' * 50, '', None):
            name = extensions._server_name(raw)
            self.assertTrue(extensions.validate_servers({name: {'url': 'https://example.com/mcp'}}), raw)


class DocumentParts(unittest.TestCase):
    def test_a_part_larger_than_the_limit_is_refused(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('content.xml', b'<a>' + b' ' * 4096 + b'</a>')
        with zipfile.ZipFile(io.BytesIO(data.getvalue())) as zf:
            self.assertEqual(len(doc_extractor._zip_read(zf, 'content.xml')), 4103)
            with self.assertRaises(ValueError):
                doc_extractor._zip_read(zf, 'content.xml', limit=1024)


class ModelMoves(unittest.TestCase):
    def test_a_different_file_with_the_same_name_and_size_is_never_deleted(self):
        import tempfile
        import model_mover
        with tempfile.TemporaryDirectory() as folder:
            src, dest = Path(folder) / 'a' / 'm.gguf', Path(folder) / 'b' / 'm.gguf'
            src.parent.mkdir(); dest.parent.mkdir()
            src.write_bytes(b'new version!'); dest.write_bytes(b'old version!')
            mover = model_mover.ModelMover(lambda: folder, lambda *a: {})
            with self.assertRaises(ValueError):
                mover._move_one(src, dest, src.stat().st_size)
            self.assertEqual(src.read_bytes(), b'new version!')
            dest.write_bytes(b'new version!')
            mover._move_one(src, dest, src.stat().st_size)    # a true duplicate: the source goes
            self.assertFalse(src.exists())


class FileVersionLimits(unittest.TestCase):
    def test_versions_per_file_are_capped(self):
        import tempfile
        from file_versions import FileVersions
        with tempfile.TemporaryDirectory() as folder:
            store = FileVersions(Path(folder) / 'versions')
            store.KEEP = 3
            target = Path(folder) / 'w' / 'f.txt'
            target.parent.mkdir()
            for n in range(6):
                target.write_text(str(n), encoding='utf-8')
                store.capture(target, target.parent)
            self.assertEqual(len(store.history(target, target.parent)), 3)


class EngineOptionRemoval(unittest.TestCase):
    def test_removing_a_flag_without_value_keeps_the_next_flag(self):
        import engine_options
        args = ['--model', 'm.gguf', '--no-mmap', '--kv', 'q8_0']
        self.assertEqual(engine_options.without('strata', args, ['flag__no_mmap']), ['--model', 'm.gguf', '--kv', 'q8_0'])


class ListeningPort(unittest.TestCase):
    def test_the_listener_is_found_whatever_the_windows_language(self):
        from unittest import mock
        import agent
        table = ('  TCP    0.0.0.0:135     0.0.0.0:0      ESCUCHANDO   1820\n'
                 '  TCP    127.0.0.1:19382 0.0.0.0:0      ABHÖREN      4242\n'
                 '  TCP    127.0.0.1:50000 127.0.0.1:19382 ESTABLISHED 77\n')
        with mock.patch('subprocess.check_output', return_value=table):
            self.assertEqual(agent.port_pid(19382), 4242)


class RunJournals(unittest.TestCase):
    def test_a_temporary_chat_leaves_no_history_and_no_run(self):
        import tempfile
        from local_store import RunJournal, Sessions
        with tempfile.TemporaryDirectory() as folder:
            sessions = Sessions(Path(folder))
            run = RunJournal({'conversation_id': 'tmp-abc', 'temporary': True,
                              'messages': [{'role': 'user', 'content': 'hola'}]}, sessions)
            run.append(b'data: {}\n\n')
            run.close('closed')
            self.assertIsNone(sessions.get('tmp-abc'))
            self.assertFalse(run.root.exists())

    def test_spent_runs_are_removed_after_a_day(self):
        import json
        import tempfile
        import time
        from local_store import RunJournal, Sessions
        with tempfile.TemporaryDirectory() as folder:
            sessions = Sessions(Path(folder))
            run = RunJournal({'conversation_id': 'chat-1', 'messages': [{'role': 'user', 'content': 'hola'}]}, sessions)
            run.close('closed')
            meta = json.loads((run.root / 'meta.json').read_text(encoding='utf-8'))
            meta.update(acknowledged=True, created=time.time() - 2 * 86400)
            (run.root / 'meta.json').write_text(json.dumps(meta), encoding='utf-8')
            sessions.recover_runs()
            self.assertFalse(run.root.exists())


class KvCacheRefused(unittest.TestCase):
    def test_a_refused_kv_format_is_named_not_the_architecture(self):
        from engine_manager import load_failure
        log = ("E llama_init_from_model: FP8 cache is not supported for architecture 'bailingmoe3'\n"
               "E cmn  common_init_: failed to create context with model 'm.gguf'\n")
        message = load_failure('llama.cpp', log)
        self.assertIn('no admite la caché KV FP8', message)
        self.assertIn('Q8_0', message)



if __name__ == '__main__':
    unittest.main()
