"""Regression tests for draft continuation recovery, MCP fixes, tool budget, and localized update notices."""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'agent'), str(ROOT), str(ROOT / 'web_mcp')]
if 'STRATA_AGENT_DATA' not in os.environ:
    import atexit
    import shutil
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
    atexit.register(shutil.rmtree, os.environ['STRATA_AGENT_DATA'], True)

import agent
import browser_mcp
import buscador_mcp
import components
import draft_recovery
import http_tools_mcp
import mcp_prompt
import pc_mcp
import render_check
import tool_budget
from access_policy import AccessPolicy
from draft_store import DraftStore


class DraftRecoveryAndAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.policy = AccessPolicy(self.root)
        self.draft_id = 'a' * 32

    def tearDown(self):
        self.tmp.cleanup()

    def _seed_disk_draft(self, target_name='landing-page.html', raw='{"path":"landing-page.html","content":"<h1>Draft</h1>"}', args=None):
        drafts_dir = self.root / 'drafts'
        drafts_dir.mkdir(parents=True, exist_ok=True)
        file_path = f'drafts/{self.draft_id}-{target_name}'
        (drafts_dir / f'{self.draft_id}.json').write_text(
            json.dumps({
                'id': self.draft_id,
                'name': 'pc__fs_write',
                'status': 'interrupted',
                'args': {} if args is None else args,
                'raw': raw,
                'file_path': file_path,
            }),
            encoding='utf-8',
        )
        (self.root / file_path).write_text(raw, encoding='utf-8')
        return file_path

    def test_draft_store_prunes_prior_turn_draft_with_empty_args(self):
        self._seed_disk_draft('landing-page.html', args={})
        store = DraftStore(self.policy, lambda dest, text, **kw: dest.write_text(text, encoding='utf-8'))
        store.observe({
            'type': 'tool',
            'id': 'call_2',
            'name': 'pc__fs_write',
            'args': {'path': 'landing-page.html', 'content': '<h1>Final</h1>'},
        })
        store.observe({
            'type': 'tool_result',
            'id': 'call_2',
            'name': 'pc__fs_write',
            'status': 'completed',
            'ok': True,
        })
        self.assertFalse((self.root / 'drafts' / f'{self.draft_id}.json').exists())
        self.assertFalse((self.root / 'drafts' / f'{self.draft_id}-landing-page.html').exists())

    def test_pc_mcp_fs_read_draft_auto_resumes_and_fs_write_cleans_drafts(self):
        rel = self._seed_disk_draft('page.html', args={'path': 'page.html', 'content': '<h1>Recovered</h1>'})
        res = pc_mcp.call('fs_read', {'path': rel}, full_access=False, policy=self.policy)
        self.assertIn(f'[Draft auto-restored to recuperados/{self.draft_id}-page.html', res)
        self.assertIn('<h1>Recovered</h1>', res)
        self.assertTrue((self.root / 'recuperados' / f'{self.draft_id}-page.html').is_file())

        written = pc_mcp.call('fs_write', {'path': 'page.html', 'content': '<!doctype html><title>Ok</title><h1>Final</h1>'}, full_access=False, policy=self.policy)
        self.assertTrue(str(written).startswith('written: '))
        self.assertFalse((self.root / 'drafts' / f'{self.draft_id}.json').exists())
        self.assertIsNone(draft_recovery.pending_draft(self.policy))

    def test_pc_mcp_draft_resume_without_pending_returns_structured_error(self):
        out = json.loads(pc_mcp.call('draft_resume', {}, full_access=False, policy=self.policy))
        self.assertFalse(out['ok'])
        self.assertIn('error', out)

    def test_continuation_helper_and_agent_zero_tool_nudge(self):
        self.assertTrue(agent._is_continuation_request('Sigue trabajando', 'landing-page.html'))
        self.assertTrue(agent._is_continuation_request('Please continue the draft', ''))
        self.assertFalse(agent._is_continuation_request('2+2', 'landing-page.html'))

        self._seed_disk_draft('index.html', raw='{"path":"index.html","content":"<h1>Hi</h1>"}')
        prompts = []
        calls = {'n': 0}

        def stream(payload, control):
            calls['n'] += 1
            prompts.append(list(payload.get('messages') or []))
            if calls['n'] == 1:
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': 'Continúo con el archivo.'}}]})).encode()
                yield b'data: [DONE]'
            else:
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': 'Archivo completado.'}}]})).encode()
                yield b'data: [DONE]'

        tools = [{'type': 'function', 'function': {'name': 'pc__fs_write', 'description': 'Write file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}}]
        with patch.object(agent, 'VRAM_AUTO', False), \
             patch.object(agent, 'tokenizer_del_modelo', lambda _: None), \
             patch.object(agent, 'tools_for', lambda *a: tools), \
             patch.object(agent, 'engine_context', lambda *a: 8192), \
             patch.object(agent, 'engine_chat_stream', stream), \
             patch.object(agent.PROJECTS, 'workspace', lambda *a: self.policy):
            events = list(agent._run_chat_stream({
                'model': 'test',
                'conversation_id': 'c1',
                'messages': [{'role': 'user', 'content': 'Sigue trabajando'}],
                'rounds': 3,
            }))
        self.assertEqual(calls['n'], 2)
        self.assertTrue(any(m.get('role') == 'tool' and 'pc__draft_resume()' in str(m.get('content')) for m in prompts[1]))
        self.assertEqual([e for e in events if e.get('type') == 'done'][-1]['content'], 'Continúo con el archivo.\n\nArchivo completado.')

        # Unrelated query does NOT trigger a draft recovery nudge
        calls['n'] = 0
        with patch.object(agent, 'VRAM_AUTO', False), \
             patch.object(agent, 'tokenizer_del_modelo', lambda _: None), \
             patch.object(agent, 'tools_for', lambda *a: tools), \
             patch.object(agent, 'engine_context', lambda *a: 8192), \
             patch.object(agent, 'engine_chat_stream', stream), \
             patch.object(agent.PROJECTS, 'workspace', lambda *a: self.policy):
            list(agent._run_chat_stream({
                'model': 'test',
                'conversation_id': 'c1',
                'messages': [{'role': 'user', 'content': '2+2'}],
                'rounds': 3,
            }))
        self.assertEqual(calls['n'], 1)

    def test_large_draft_view_stays_within_light_budget_and_fs_copy_edit_clean(self):
        lines = [f'line {i}: <section id="s{i}">content {i}</section>' for i in range(1, 221)]
        big_html = '<!doctype html>\n<html>\n<body>\n' + '\n'.join(lines) + '\n<div id="faq">Cut here'
        rel = self._seed_disk_draft('landing-page.html', args={'path': 'landing-page.html', 'content': big_html})

        # Default fs_read on a large draft must stay <= 3400 chars (below Light 4000 limit) and show tail + target
        view = pc_mcp.call('fs_read', {'path': rel}, full_access=False, policy=self.policy)
        self.assertLessEqual(len(view), 3400)
        self.assertIn('landing-page.html', view)
        self.assertIn('fs_copy', view)
        self.assertIn('<div id="faq">Cut here', view)

        # Even if draft_recovery omits target_path (legacy 1.0.9 behavior), target filename is still derived
        real_resume = draft_recovery.resume_draft
        def legacy_resume(ws, did=None):
            res = real_resume(ws, did)
            res.pop('target_path', None)
            return res
        with patch.object(draft_recovery, 'resume_draft', legacy_resume):
            resume_json = json.loads(pc_mcp.call('draft_resume', {}, full_access=False, policy=self.policy))
        self.assertEqual(resume_json['target_path'], 'landing-page.html')
        self.assertIn('<div id="faq">Cut here', resume_json['tail_preview'])
        self.assertIn('fs_copy', resume_json['recommended_action'])

        # Default fs_read without max_chars stays below Light's 4000-char limit
        chunk = pc_mcp.call('fs_read', {'path': f'recuperados/{self.draft_id}-landing-page.html', 'offset': 0}, full_access=False, policy=self.policy)
        self.assertLessEqual(len(chunk), 3500)

        # fs_copy into landing-page.html cleans up resolved drafts/ snapshot automatically
        copied = pc_mcp.call('fs_copy', {
            'desde': f'recuperados/{self.draft_id}-landing-page.html',
            'destino': 'landing-page.html',
            'modo': 'nuevo',
        }, full_access=False, policy=self.policy)
        self.assertIn('landing-page.html', copied)
        self.assertFalse((self.root / 'drafts' / f'{self.draft_id}.json').exists())

        # Re-seed draft and verify fs_edit on target also cleans up resolved drafts/
        self._seed_disk_draft('landing-page.html', args={'path': 'landing-page.html', 'content': big_html})
        edited = pc_mcp.call('fs_edit', {
            'path': 'landing-page.html',
            'old_text': '<div id="faq">Cut here',
            'new_text': '<div id="faq">FAQ</div></body></html>',
        }, full_access=False, policy=self.policy)
        self.assertTrue(str(edited).startswith('edited: '))
        self.assertFalse((self.root / 'drafts' / f'{self.draft_id}.json').exists())

    def test_agent_recovers_in_turn_from_rejected_large_write_and_promise_stub(self):
        prompts = []
        calls = {'n': 0}

        def stream(payload, control):
            calls['n'] += 1
            prompts.append(list(payload.get('messages') or []))
            if calls['n'] == 1:
                # Truncated large fs_write draft (>512 chars, incomplete JSON)
                partial_args = '{"path":"landing-page.html","content":"<html>' + ('x' * 700)
                yield ('data: ' + json.dumps({'choices': [{'delta': {'tool_calls': [
                    {'index': 0, 'id': 'call_cut', 'type': 'function', 'function': {'name': 'pc__fs_write', 'arguments': partial_args}}
                ]}}]})).encode()
                yield ('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'length'}]})).encode()
                yield b'data: [DONE]'
            elif calls['n'] == 2:
                # Model emits an intermediate promise-to-act stub without calling any tool
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': 'El borrador está incompleto. Voy a escribir el archivo completo ahora.'}}]})).encode()
                yield ('data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})).encode()
                yield b'data: [DONE]'
            else:
                yield ('data: ' + json.dumps({'choices': [{'delta': {'content': 'Archivo completado correctamente.'}}]})).encode()
                yield b'data: [DONE]'

        tools = [
            {'type': 'function', 'function': {'name': 'pc__fs_write', 'description': 'Write file', 'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}},
            {'type': 'function', 'function': {'name': 'pc__draft_resume', 'description': 'Resume draft', 'parameters': {'type': 'object', 'properties': {}}}},
        ]
        with patch.object(agent, 'VRAM_AUTO', False), \
             patch.object(agent, 'tokenizer_del_modelo', lambda _: None), \
             patch.object(agent, 'tools_for', lambda *a: tools), \
             patch.object(agent, 'engine_context', lambda *a: 8192), \
             patch.object(agent, 'engine_chat_stream', stream), \
             patch.object(agent.PROJECTS, 'workspace', lambda *a: self.policy):
            events = list(agent._run_chat_stream({
                'model': 'test',
                'conversation_id': 'c1',
                'messages': [{'role': 'user', 'content': 'Crea una landing page completa en landing-page.html'}],
                'rounds': 6,
            }))
        self.assertEqual(calls['n'], 3)
        final = [e for e in events if e.get('type') == 'done'][-1]['content']
        self.assertNotIn('El archivo quedó como borrador', final)
        self.assertIn('Archivo completado correctamente.', final)
        self.assertTrue(any('pc__draft_resume()' in str(m.get('content')) for m in prompts[1] if m.get('role') == 'tool'))
        self.assertTrue(any('0 tool calls' in str(m.get('content')) for m in prompts[2] if m.get('role') == 'tool'))


class ToolBudgetAndMcpAuditTests(unittest.TestCase):
    def test_mcp_instructions_are_never_shortened_to_save_tokens(self):
        tools = [
            {'type': 'function', 'function': {
                'name': 'pc__fs_edit',
                'description': mcp_prompt.DESCRIPTIONS['pc__fs_edit'],
                'parameters': {'type': 'object', 'properties': {
                    'path': {'type': 'string', 'description': 'Relative or absolute path.', 'examples': ['app.py']},
                }},
            }},
            {'type': 'function', 'function': {
                'name': 'pc__draft_resume',
                'description': mcp_prompt.DESCRIPTIONS['pc__draft_resume'],
                'parameters': {'type': 'object', 'properties': {}},
            }},
        ]
        budgeted, info = tool_budget.escalera(tools, [{'role': 'user', 'content': 'hi'}], None, limite=1)
        self.assertEqual(info['nivel'], 0)
        self.assertEqual(budgeted[0]['function']['description'], mcp_prompt.DESCRIPTIONS['pc__fs_edit'])
        self.assertEqual(budgeted[0]['function']['parameters']['properties']['path']['examples'], ['app.py'])
        self.assertIn('appear once', tool_budget.SHORT_DESCRIPTIONS['pc__fs_edit'])
        self.assertIn('drafts/', tool_budget.SHORT_DESCRIPTIONS['pc__draft_resume'])
        self.assertIn('recuperados/', mcp_prompt.DESCRIPTIONS['pc__draft_resume'])
        self.assertEqual(tool_budget.SHORT_DESCRIPTIONS['pc__fs_edit'], mcp_prompt.DESCRIPTIONS['pc__fs_edit'])

    def test_browser_mcp_scheme_validation_snapshot_value_and_tab_close_wait(self):
        with self.assertRaises(ValueError):
            browser_mcp.open('file:///C:/Windows/win.ini', new_tab=True)
        with self.assertRaises(ValueError):
            browser_mcp.tabs(action='new', url='javascript:alert(1)')

        js = browser_mcp._snapshot_js(4000, 20)
        self.assertIn('/^(submit|button|reset)$/i', js)

        pages_seq = [
            [{'id': 'p1', 'url': 'https://a.example', 'title': 'A'}, {'id': 'p2', 'url': 'https://b.example', 'title': 'B'}],
            [{'id': 'p1', 'url': 'https://a.example', 'title': 'A'}, {'id': 'p2', 'url': 'https://b.example', 'title': 'B'}],
            [{'id': 'p1', 'url': 'https://a.example', 'title': 'A'}],
            [{'id': 'p1', 'url': 'https://a.example', 'title': 'A'}],
        ]
        idx = {'i': 0}

        def fake_list():
            cur = pages_seq[min(idx['i'], len(pages_seq) - 1)]
            idx['i'] += 1
            return cur

        class _CloseResp:
            def read(self, n=-1):
                return b'Target is closing'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        with patch.dict(browser_mcp.STATE, {'port': 9222, 'target': {'id': 'p2'}, 'pages': {}, 'cdp': None}, clear=False), \
             patch.object(browser_mcp, '_list_pages', fake_list), \
             patch.object(browser_mcp, '_connect_target', lambda item: browser_mcp.STATE.update(target=item)), \
             patch('urllib.request.urlopen', lambda url, timeout=5: _CloseResp()):
            out = json.loads(browser_mcp.tabs(action='close', index=1))
        self.assertTrue(out['ok'])
        self.assertEqual(out['remaining'], 1)
        self.assertEqual(out['tab_count'], 1)

    def test_buscador_and_http_tools_text_detection_and_english_profile(self):
        self.assertTrue(http_tools_mcp._is_text_response(b'<html>ok</html>', 'Text/HTML; Charset=UTF-8'))
        self.assertTrue(http_tools_mcp._is_text_response(b'plain utf8 text', ''))
        self.assertFalse(http_tools_mcp._is_text_response(b'\x89PNG\r\n\x1a\n\x00', ''))
        self.assertEqual(http_tools_mcp._fallback_name('https://example.com/a:b?x=1'), 'a_b')

        class _FakeRaw:
            def __init__(self, data):
                self._bio = io.BytesIO(data)
            def read(self, n=-1, decode_content=False):
                return self._bio.read(n)

        class _FakeSessionResp:
            def __init__(self, data, headers=None, status_code=200, encoding='utf-8'):
                self._data = data
                self.headers = headers or {}
                self.status_code = status_code
                self.is_redirect = False
                self.encoding = encoding
                self.raw = _FakeRaw(data)
            def raise_for_status(self):
                return None
            def iter_content(self, chunk_size=65536):
                yield self._data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        profile_json = json.dumps({
            'user': 'ada',
            'numFollowers': 10,
            'numFollowing': 2,
            'numModels': 3,
        }).encode('utf-8')
        with patch('requests.Session.get', return_value=_FakeSessionResp(profile_json, {'Content-Type': 'application/json'})):
            prof = buscador_mcp.hf_public_profile('https://huggingface.co/ada')
        self.assertIn('followers: 10', prof)
        self.assertNotIn('seguidores', prof)

        page_bytes = b'<html><body><h1>Hello World</h1><p>Content without content-type header.</p></body></html>'
        with patch.object(buscador_mcp, 'validate_public_url', lambda u: u), \
             patch('requests.Session.get', return_value=_FakeSessionResp(page_bytes, {})):
            page = buscador_mcp.read_public_page('https://example.com/no-ct')
        self.assertIn('Hello World', page)

    def test_render_check_errors_are_english(self):
        self.assertEqual(render_check.__name__, 'render_check')
        src = (ROOT / 'agent' / 'render_check.py').read_text(encoding='utf-8')
        for spanish in ('No existe', 'Solo admite', 'Falta ', 'Navegador no disponible'):
            self.assertNotIn(spanish, src)


class ComponentsAndUpdateNotificationTests(unittest.TestCase):
    def test_components_state_tracks_installed_manifest_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {
                'product': 'V-Agent',
                'channel': 'components',
                'app_version': '1.0.9',
                'revision': 3,
                'notes': 'Draft continuation & notification fixes',
                'files': [{'name': 'ui-patch.js', 'size': 10, 'sha256': 'a' * 64}],
            }
            active = root / 'active.json'
            active.write_text(json.dumps({'manifest': json.dumps(manifest), 'signature': 'sig'}), encoding='utf-8')
            with patch.object(components, '_active_file', lambda: active), \
                 patch.object(components, 'ROOT', root), \
                 patch.object(components, 'validate', lambda b, s, **kw: json.loads(b.decode('utf-8'))):
                mgr = components.Components(repository='IsValorum/V-Agent')
                self.assertEqual(mgr.state['revision'], 3)
                self.assertEqual(mgr.state['notes'], 'Draft continuation & notification fixes')
                reset = mgr.reset()
                self.assertEqual(reset['revision'], 0)
                self.assertEqual(reset['notes'], '')

    def test_locales_include_draft_and_update_notification_keys(self):
        locales = json.loads((ROOT / 'agent' / 'ui' / 'locales.json').read_text(encoding='utf-8'))
        for key in (
            'Nueva versión disponible',
            'Ver actualización',
            'Descartar aviso',
            'Notas de versión',
            'Actualización menor aplicada',
            'Borrador disponible',
            'Ver borrador',
            'Guardar borrador',
            'No hay un precompilado compatible publicado.',
            'Restaurado',
        ):
            self.assertIn(key, locales)
            for lang in ('en', 'pt', 'fr', 'de'):
                self.assertTrue(locales[key][lang], f'{key}:{lang}')

    def test_composer_draft_regex_preserves_full_extension(self):
        src = (ROOT / 'agent' / 'ui' / 'app' / 'composer.js').read_text(encoding='utf-8')
        match = re.search(r'const re=(/drafts[^;]+;/gi|[^\n]+/gi);', src)
        self.assertIsNotNone(match)
        sample = 'Borrador conservado en `drafts/5b8c0e71bbc7fbeabb63b3b0991a31e1-landing-page.html`.'
        js_re = re.compile(r'drafts[\\/]([0-9a-f]{32})(?:-([^\s`"\'<>,;)\]]+))?', re.I)
        found = js_re.search(sample)
        self.assertEqual(found.group(2).rstrip('.,;:!?'), 'landing-page.html')
        self.assertIn(r'''[^\s`"'<>,;)\]]+''', src)


if __name__ == '__main__':
    unittest.main()
