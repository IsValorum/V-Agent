"""Interface faults found in the 2026-11-12 visual audit: each one stays fixed."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if 'STRATA_AGENT_DATA' not in os.environ:
    import atexit
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
    atexit.register(shutil.rmtree, os.environ['STRATA_AGENT_DATA'], True)
sys.path[:0] = ['agent', '.', 'tools']
UI = Path('agent/ui')


def node(script):
    # Through stdin: the translation catalogue is too long for a Windows command line.
    return subprocess.run(['node', '-'], input=script, capture_output=True, text=True, encoding='utf-8', timeout=30).stdout.strip()


class DateNoteTests(unittest.TestCase):
    def test_the_date_note_never_ends_up_in_a_written_file(self):
        import agent, pc_mcp
        self.assertIn('not part of the user', agent.date_line())
        for text in ('hola\n\n' + agent.date_line(), 'hola\n\n[Fecha y hora actual: 2026-11-11 20:00 (miércoles)]'):
            self.assertEqual(pc_mcp.DATE_NOTE.sub('', text), 'hola')
        quoted = 'un texto que cita [Fecha y hora actual: 2026-11-11 20:00 (lunes)] en medio\n'
        self.assertEqual(pc_mcp.DATE_NOTE.sub('', quoted), quoted)


class DefaultToolsTests(unittest.TestCase):
    def test_a_fresh_install_can_work_with_files_and_search(self):
        source = (UI / 'app/startup.js').read_text(encoding='utf-8')
        defaults = re.search(r'const DEF_FUNCS = (\{[^}]+\})', source)[1]
        values = dict(re.findall(r'(\w+):\s*(true|false)', defaults))
        for key in ('files', 'sys', 'search', 'visit'):
            self.assertEqual(values[key], 'true', key)
        for key in ('shell', 'console', 'admin', 'computer'):  # need full access or are risky
            self.assertEqual(values[key], 'false', key)


class WindowsNameTests(unittest.TestCase):
    def test_windows_11_is_not_shown_as_windows_10(self):
        source = Path('agent/hardware_stats.py').read_text(encoding='utf-8')
        self.assertIn("int(build) >= 22000", source)


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class FormattingTests(unittest.TestCase):
    def test_parameter_counts_use_billions(self):
        source = (UI / 'app/models.js').read_text(encoding='utf-8')
        count = re.search(r'const count=(n=>\{.*?\};)', source)[1]
        out = node('const count=' + count + 'console.log([9197e6,35.6e9,5.7e6,664].map(count).join("|"))')
        self.assertEqual(out, '9.2 B|36 B|5.7 M|664')

    def test_core_texts_are_translated_part_by_part(self):
        source = (UI / 'app/shell.js').read_text(encoding='utf-8')
        parts = re.search(r'(function uiParts\(text\)\{.*?\n\})', source, re.S)[1]
        catalog = json.loads((UI / 'locales.json').read_text(encoding='utf-8'))
        script = ('const C=' + json.dumps(catalog, ensure_ascii=False) + ';const uiText=t=>(C[t]||{}).en||t;' + parts +
                  'console.log(uiParts("RTX 4050 · driver 621.01 · necesita el controlador NVIDIA 581.42 o posterior · llama.cpp CUDA recomendado"))')
        self.assertEqual(node(script), 'RTX 4050 · driver 621.01 · needs NVIDIA driver 581.42 or newer · llama.cpp CUDA recommended')

    def test_every_engine_recommendation_phrase_is_translated(self):
        import engine_recommendations
        catalog = json.loads((UI / 'locales.json').read_text(encoding='utf-8'))
        result = engine_recommendations.recommend({}, {})
        texts = [row['reason'] for row in result['engines']] + [result['summary']]
        for text in texts:
            for part in text.split(' · '):
                key = re.sub(r'\d+(?:[.,]\d+)?', '{n}', part)
                self.assertTrue(part in catalog or key in catalog, part)


class LayoutTests(unittest.TestCase):
    def test_browser_never_squeezes_the_chat_below_a_usable_width(self):
        tools = (UI / 'app/tools.js').read_text(encoding='utf-8')
        css = (UI / 'styles/panels.css').read_text(encoding='utf-8')
        self.assertIn('const CHAT_MIN=520', tools)
        self.assertIn("classList.toggle('browser-overlay'", tools)
        self.assertIn('body.browser-open.browser-overlay #chatwrap{margin-right:0;}', css)

    def test_controls_without_a_size_follow_the_panel_scale(self):
        css = (UI / 'styles/base.css').read_text(encoding='utf-8')
        self.assertIn(':where(.settings-page,section.fw,dialog,#updateStack) :is(button:not(.icon-btn),select,input,textarea) { font-size:11px; }', css)


class ModelPanelTests(unittest.TestCase):
    def test_the_panel_has_one_card_and_the_old_footer_is_hidden(self):
        panel = (UI / 'app/model-panel.js').read_text(encoding='utf-8')
        marked = panel.index("base.classList.add('model-footer-static')")
        self.assertGreater(panel.index('simplifyModelPanel();', marked), marked)  # after the footer exists
        self.assertIn("setModelSection('generation')", (UI / 'app/controls.js').read_text(encoding='utf-8'))

    def test_switching_engine_keeps_the_same_model_file(self):
        controls = (UI / 'app/model-controls.js').read_text(encoding='utf-8')
        self.assertIn("models.find(m=>path&&String(m.path||'').toLowerCase()===path)", controls)

    def test_apply_appears_only_for_a_changed_loaded_model(self):
        composer = (UI / 'app/composer.js').read_text(encoding='utf-8')
        self.assertIn("$('#ctxApply').hidden=!(loadedModel&&loadedModel===$('#model').value&&pendingModelContexts.has(loadedModel));", composer)

    def test_reading_from_cache_is_said_not_hidden(self):
        chat = (UI / 'app/chat.js').read_text(encoding='utf-8')
        self.assertIn('prefillCached', chat)
        self.assertIn("uiText('desde caché')", chat)


class StateConsistencyTests(unittest.TestCase):
    def test_settings_changes_keep_the_composer_switches_in_step(self):
        startup = (UI / 'app/startup.js').read_text(encoding='utf-8')
        self.assertIn("document.getElementById('searchToggle')?.setAttribute('aria-pressed', String(!!S.functions.search));", startup)

    def test_a_stopped_reply_keeps_its_last_measure(self):
        self.assertIn('const finalUsage=lastUsage||', (UI / 'app/composer.js').read_text(encoding='utf-8'))

    def test_api_mode_hides_the_local_context_block(self):
        self.assertIn("$('#contextBlock').hidden=remote", (UI / 'app/engine-controls.js').read_text(encoding='utf-8'))
        self.assertIn('#contextBlock){display:none!important;}', (UI / 'styles/panels.css').read_text(encoding='utf-8'))

    def test_a_refused_engine_change_resets_the_selector(self):
        engine = (UI / 'app/engine-controls.js').read_text(encoding='utf-8')
        self.assertIn("$('#engineKind').value=activeEngine", engine)
        self.assertIn('Descarga el modelo actual antes de cambiar de motor.', engine)

    def test_the_memory_warning_is_shown_under_the_context(self):
        self.assertIn('contextMemoryWarning', (UI / 'app/load-settings.js').read_text(encoding='utf-8'))

    def test_api_connection_errors_are_plain_words(self):
        self.assertIn("'No se pudo conectar con '", Path('agent/desktop_runtime.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
