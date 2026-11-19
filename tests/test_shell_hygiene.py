"""The terminal tools give any model a clean, non-interactive console (no harness-specific fine-tune needed)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path[:0] = ['agent', '.']
import pc_mcp  # noqa: E402
import shell_hygiene as h  # noqa: E402
from access_policy import AccessPolicy  # noqa: E402


class CleanTests(unittest.TestCase):
    def test_escape_codes_progress_bars_padding_and_repeats(self):
        raw = ('\x1b[31mRED\x1b[0m done\r\n' + ''.join('\rprogress %d%%' % i for i in range(100)) + '\nfinished   \n'
               + 'same line\n' * 9 + '\x1b]0;window title\x07tail')
        self.assertEqual(h.clean(raw), 'RED done\nprogress 99%\nfinished\nsame line\n[previous line repeated 8 more times]\ntail')

    def test_ordinary_output_is_untouched(self):
        text = 'line 1\n\n  indented line\nline 1'
        self.assertEqual(h.clean(text), text)

    def test_powershell_clixml_errors_become_readable(self):
        raw = ('#< CLIXML\r\n<Objs Version="1.1.0.1"><S S="Error">En línea: 3 Carácter: 8_x000D__x000A_</S>'
               '<S S="Error">El token \'&amp;&amp;\' no es válido._x000D__x000A_</S></Objs>')
        self.assertEqual(h.clean(raw), "En línea: 3 Carácter: 8\nEl token '&&' no es válido.")

    def test_old_console_code_page_is_read_correctly(self):
        self.assertEqual(h.decode('Carácter'.encode('utf-8')), 'Carácter')
        self.assertEqual(h.decode('Carácter'.encode('cp850')), 'Carácter')

    def test_long_output_keeps_head_and_tail_and_points_to_the_saved_file(self):
        text = 'HEAD\n' + 'x' * 50000 + '\nTHE ERROR AT THE END'
        fitted = h.fit_output(text, 8000, lambda full: 'outputs/shell-1.txt')
        self.assertLessEqual(len(fitted), 8000)
        self.assertTrue(fitted.startswith('HEAD'))
        self.assertTrue(fitted.endswith('THE ERROR AT THE END'))
        self.assertIn('outputs/shell-1.txt', fitted)
        self.assertEqual(h.fit_output('short', 8000, lambda full: 'unused'), 'short')

    def test_mixed_encodings_are_read_line_by_line(self):
        mixed = 'canción OK\n'.encode('utf-8') + 'Carácter'.encode('cp850') + b'\n'
        self.assertEqual(h.decode(mixed), 'canción OK\nCarácter\n')

    def test_environment_never_changes_what_a_program_does(self):
        # PYTHONUTF8 made a script reading a cp1252 file fail; PAGER=cat needs a cat.exe Windows lacks.
        for name in ('CI', 'PYTHONUTF8', 'PAGER'):
            self.assertNotIn(name, h.QUIET_ENV)

    def test_for_loops_in_several_lines_need_double_percent(self):
        self.assertIn('%%i', h.command_notes('for %i in (a b) do echo %i\necho end', 'cmd'))
        self.assertEqual(h.command_notes('for %%i in (a b) do echo %%i\necho end', 'cmd'), '')
        self.assertEqual(h.command_notes('for %i in (a b) do echo %i', 'cmd'), '')

    def test_binary_and_utf16_output(self):
        self.assertTrue(h.decode(bytes(range(256)) * 40).startswith('[binary output: 10240 bytes not shown'))
        self.assertEqual(h.decode('Nombre  Versión\r\n'.encode('utf-16-le')), 'Nombre  Versión\r\n')
        self.assertEqual(h.decode('﻿Name\r\n'.encode('utf-16-le')), 'Name\r\n')
        self.assertEqual(h.decode('café\n'.encode('utf-8')), 'café\n')

    def test_batch_script_runs_every_line_and_keeps_the_exit_code(self):
        script = h.batch_script('echo one\necho two\n')
        self.assertTrue(script.startswith('@echo off\r\nchcp 65001 >nul\r\n'))
        self.assertIn('echo one\r\necho two\r\n', script)
        self.assertTrue(script.endswith('exit /b %errorlevel%\r\n'))


class HintTests(unittest.TestCase):
    def test_linux_commands_get_their_windows_equivalent(self):
        for stderr, name, expected in (
                ("'ls' is not recognized as an internal or external command,", 'ls', 'dir'),
                ('"cat" no se reconoce como un comando interno o externo,', 'cat', 'type FILE'),
                ("grep : The term 'grep' is not recognized as the name of a cmdlet", 'grep', 'findstr'),
                ('which: command not found', 'which', 'where')):
            hint = h.failure_hint(name, stderr)
            self.assertIn('`%s` is a Linux command' % name, hint)
            self.assertIn(expected, hint)

    def test_a_missing_program_is_not_guessed(self):
        self.assertIn('`cargo` is not installed or not on PATH', h.failure_hint('cargo build', "'cargo' is not recognized"))

    def test_keyboard_git_and_timeout(self):
        self.assertIn('without keyboard input', h.failure_hint('python a.py', 'EOFError: EOF when reading a line'))
        self.assertIn('Git needs credentials', h.failure_hint('git push', 'fatal: could not read Username for https://github.com'))
        self.assertIn('background=true', h.failure_hint('npm run dev', '', timed_out=True))
        self.assertNotIn('background=true', h.failure_hint('python a.py', '', timed_out=True, sandboxed=True))
        self.assertEqual(h.failure_hint('python a.py', 'ZeroDivisionError: division by zero'), '')

    def test_bash_habits(self):
        cases = {('./build.sh', '"." no se reconoce como un comando interno'): './name is bash',
                 ('python3 a.py', "'python3' is not recognized"): 'use python',
                 ('$ npm test', '"$" no se reconoce'): 'without a prompt sign',
                 ('```\nnpm test\n```', '"```" no se reconoce'): 'markdown fences',
                 ('mkdir -p a/b', 'La sintaxis del comando no es correcta.'): 'drop -p',
                 ('FOO=1 python a.py', '"FOO" no se reconoce'): 'set NAME=value&& command',
                 ('curl -s https://x', 'faltan uno o varios de los parámetros obligatorios:  Uri.'): 'curl.exe',
                 ('echo a && echo b', "El token '&&' no es un separador de instrucciones válido"): 'no && or ||'}
        for (command, error), expected in cases.items():
            self.assertIn(expected, h.failure_hint(command, error), command)

    def test_bash_backgrounding_is_refused_before_it_blocks_the_call(self):
        # A real model sent `python -m http.server 8765 &` twelve times: each call waited the whole time limit.
        for command in ('python -m http.server 8765 &', 'nohup npm run dev', 'npm run dev &  '):
            self.assertIn('background=true', h.background_idiom(command, 'cmd'), command)
            self.assertIn('isolated mode', h.background_idiom(command, 'cmd', sandboxed=True), command)
        for command in ('npm ci && npm test', 'echo a & echo b', 'echo ^&', 'python app.py'):
            self.assertEqual(h.background_idiom(command, 'cmd'), '', command)
        self.assertEqual(h.background_idiom('Start-Process npm &', 'powershell'), '')

    def test_a_hint_already_given_as_a_note_is_not_repeated(self):
        note = h.command_notes('echo a && echo b', 'powershell')
        hint = h.failure_hint('echo a && echo b', "is not a valid statement separator")
        self.assertEqual(h.add_hint('result' + note, hint), 'result' + note)

    def test_quiet_environment_never_sets_ci(self):
        # CI=true makes some builds treat warnings as errors: it must not be forced on the user's projects.
        self.assertNotIn('CI', h.QUIET_ENV)
        self.assertEqual(h.QUIET_ENV['PYTHONUNBUFFERED'], '1')
        self.assertEqual(h.QUIET_ENV['GIT_TERMINAL_PROMPT'], '0')


class NoteTests(unittest.TestCase):
    """Bash syntax that cmd reads differently, noted even when the command 'succeeded'."""

    def test_notes_for_bash_syntax_in_cmd(self):
        self.assertIn('single quotes', h.command_notes("python -c 'print(42)'", 'cmd'))
        self.assertIn('%NAME%', h.command_notes('echo $HOME', 'cmd'))
        self.assertIn('";" does not separate', h.command_notes('cd src; dir', 'cmd'))
        self.assertIn('NUL', h.command_notes('python a.py > /dev/null', 'cmd'))
        self.assertIn('no && or ||', h.command_notes('npm ci && npm test', 'powershell'))
        # Same names as Unix tools, other Windows programs (a real model fell into each one), noted only when
        # this PC really runs the Windows program (with Git's Unix tools first on PATH it does not).
        from unittest import mock
        with mock.patch.object(h, '_windows_tool', return_value=True):
            self.assertIn('Windows FIND', h.command_notes('python --version && find . -name "*.py"', 'cmd'))
            self.assertIn('Windows TIMEOUT', h.command_notes('timeout 5 npm test', 'cmd'))
        with mock.patch.object(h, '_windows_tool', return_value=False):
            self.assertEqual(h.command_notes('find . -name "*.py"', 'cmd'), '')
            self.assertEqual(h.command_notes('timeout 5 npm test', 'cmd'), '')
        self.assertIn('start with /', h.command_notes(r'mkdir -v src\utils', 'cmd'))

    def test_no_note_for_correct_commands(self):
        for command in ('python -c "import os;print(os.environ[\'X\'])"', 'echo "price: $5"', 'git commit -m "a; b"',
                        'npm ci && npm test', 'dir /b', 'set FOO=1&& echo %FOO%', 'find "TODO" app.py', 'timeout /t 3',
                        r'set PATH=%PATH%;C:\tools&& where tool',
                        r'mkdir src\utils', r'del /q build\*.tmp'):
            self.assertEqual(h.command_notes(command, 'cmd'), '', command)
        self.assertEqual(h.command_notes("Write-Output 'a && b'; Get-Date", 'powershell'), '')


@unittest.skipUnless(sys.platform == 'win32', 'Windows shell')
class ShellToolTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.policy = AccessPolicy(self.root)

    def tearDown(self):
        self.folder.cleanup()

    def run_shell(self, args):
        try:
            return pc_mcp.call('shell_run', args, full_access=True, policy=self.policy)
        except Exception as error:
            return str(error)

    def test_model_sees_clean_output_and_a_hint_for_missing_keyboard(self):
        (self.root / 'bar.py').write_text('import sys\nfor i in range(50):\n    sys.stdout.write("\\r\\x1b[32m%d%%\\x1b[0m" % (i * 2))\nprint("\\nok")\n', encoding='utf-8')
        (self.root / 'ask.py').write_text('input("Name? ")\n', encoding='utf-8')
        out = self.run_shell({'command': '"%s" bar.py' % sys.executable})
        self.assertIn('[stdout]\n98%\nok', out)
        self.assertNotIn('\x1b', out)
        out = self.run_shell({'command': '"%s" ask.py' % sys.executable})
        self.assertIn('without keyboard input', out)
        out = self.run_shell({'command': 'definitely-not-a-program-xyz --version'})
        self.assertIn('is not installed or not on PATH', out)

    def test_trailing_ampersand_is_not_run_and_answers_at_once(self):
        started = time.monotonic()
        out = self.run_shell({'command': '"%s" -c "import time; time.sleep(30)" &' % sys.executable, 'timeout': 20})
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn('Not run', out)
        self.assertIn('background=true', out)

    def test_every_line_of_a_multi_line_command_runs(self):
        out = self.run_shell({'command': 'echo first\necho second\necho third'})
        self.assertIn('first\nsecond\nthird', out)
        out = self.run_shell({'command': 'echo ok\nexit /b 3'})
        self.assertIn('exit=3', out)

    def test_huge_output_is_saved_and_its_end_is_shown(self):
        (self.root / 'big.py').write_text('for i in range(20000):\n    print("line", i)\nraise SystemExit("FAILED AT THE END")\n', encoding='utf-8')
        out = self.run_shell({'command': '"%s" big.py' % sys.executable})
        self.assertLess(len(out), 9000)
        self.assertIn('FAILED AT THE END', out)
        saved = list((self.root / 'outputs').glob('shell-*.txt'))
        self.assertEqual(len(saved), 1)
        self.assertIn('line 19999', saved[0].read_text(encoding='utf-8'))

    def start_job(self, script, body):
        (self.root / script).write_text(body, encoding='utf-8')
        return json.loads(pc_mcp.call('shell_run', {'command': '"%s" %s' % (sys.executable, script), 'background': True},
                                      full_access=True, policy=self.policy))['job_id']

    def job(self, tool, **args):
        return json.loads(pc_mcp.call(tool, args, full_access=True, policy=self.policy))

    def test_job_wait_returns_as_soon_as_a_server_is_ready(self):
        jid = self.start_job('server.py', 'import time\nprint("starting")\ntime.sleep(1.5)\nprint("Server READY on :5173")\ntime.sleep(60)\n')
        try:
            started = time.monotonic()
            view = self.job('job_wait', job_id=jid, timeout=30, until='ready')
            self.assertLess(time.monotonic() - started, 10)
            self.assertTrue(view['until_found'])
            self.assertEqual(view['status'], 'running')
            self.assertIn('Server READY', view['output'])
        finally:
            self.job('job_stop', job_id=jid)

    def test_job_wait_with_a_word_that_never_comes_returns_when_the_job_goes_quiet(self):
        # A real model passed until="text it prints when ready" literally and waited 300 s on a ready server.
        from unittest import mock
        jid = self.start_job('quiet.py', 'import time\nprint("Serving HTTP on :: port 8765")\ntime.sleep(60)\n')
        try:
            with mock.patch.object(pc_mcp, 'JOB_QUIET', 2):
                started = time.monotonic()
                view = self.job('job_wait', job_id=jid, timeout=60, until='text it prints when ready')
            self.assertLess(time.monotonic() - started, 15)
            self.assertFalse(view['until_found'])
            self.assertIn('Serving HTTP', view['output'])
            self.assertIn('quiet', view['note'])
        finally:
            self.job('job_stop', job_id=jid)

    def test_long_logs_keep_their_latest_lines_and_checks_return_only_new_output(self):
        jid = self.start_job('chatty.py', 'import time\nfor i in range(25000):\n    print("log line", i, "y" * 10)\n'
                                          'print("LATE ERROR: port in use")\ntime.sleep(60)\n')
        try:
            view = self.job('job_wait', job_id=jid, timeout=30, until='LATE ERROR')
            self.assertTrue(view['until_found'], view['output'][-300:])
            self.assertIn('LATE ERROR: port in use', view['output'])
            self.assertLessEqual(len(view['output']), pc_mcp.JOB_REPLY + 200)
            self.assertEqual(self.job('job_status', job_id=jid)['output'], '')  # nothing new since the last check
        finally:
            self.job('job_stop', job_id=jid)

    def test_background_job_output_arrives_while_it_runs(self):
        (self.root / 'slow.py').write_text('import time\nfor i in range(4):\n    print("tick", i)\n    time.sleep(1)\n', encoding='utf-8')
        job = json.loads(pc_mcp.call('shell_run', {'command': '"%s" slow.py' % sys.executable, 'background': True},
                                     full_access=True, policy=self.policy))
        try:
            seen = ''
            for _ in range(40):
                state = json.loads(pc_mcp.call('job_status', {'job_id': job['job_id']}, full_access=True, policy=self.policy))
                seen += state['output']  # each check returns only what is new
                if 'tick 1' in seen:
                    break
                time.sleep(.1)
            self.assertEqual(state['status'], 'running', 'the job finished before its output was seen')
            self.assertIn('tick 0', seen)
        finally:
            pc_mcp.call('job_stop', {'job_id': job['job_id']}, full_access=True, policy=self.policy)


if __name__ == '__main__':
    unittest.main()
