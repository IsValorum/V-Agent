"""code_check finds mistakes that parse fine and break when the code runs (they used to pass as OK)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))

import code_insight  # noqa: E402
import verify  # noqa: E402


def check(folder, name, text, extra=None):
    folder = Path(folder)
    for other, content in (extra or {}).items():
        (folder / other).parent.mkdir(parents=True, exist_ok=True)
        (folder / other).write_text(content, encoding='utf-8')
    path = folder / name
    path.write_text(text, encoding='utf-8')
    return verify.verificar_archivo(str(path))


class PythonTests(unittest.TestCase):
    def test_undefined_name_and_local_are_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'app.py', 'def total(items):\n    return sum(item.price for item in itmes)\n\n'
                                             'def counter():\n    count += 1\n    return count\n')
        self.assertFalse(report['ok'])
        joined = ' '.join(report['errores'])
        self.assertIn("undefined name 'itmes'", joined)
        self.assertIn('line 2', joined)

    def test_unused_import_is_only_a_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'tool.py', 'import os\nimport json\n\nprint(json.dumps({}))\n')
        self.assertTrue(report['ok'])
        self.assertTrue(any("'os' imported but unused" in w for w in report['avisos']), report['avisos'])

    def test_correct_code_stays_ok(self):
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'ok.py', 'import json\nfrom helper import twice\n\nprint(json.dumps(twice(2)))\n',
                           {'helper.py': 'def twice(x):\n    return 2 * x\n'})
        self.assertTrue(report['ok'], report)
        self.assertEqual(report['errores'], [])

    def test_a_module_nobody_has_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(code_insight, '_user_python', return_value=sys.executable):
                report = check(folder, 'needs.py', 'import json\nimport surely_not_a_module_xyz\nprint(json, surely_not_a_module_xyz)\n')
        self.assertTrue(any('surely_not_a_module_xyz' in w for w in report['avisos']), report['avisos'])

    def test_no_python_on_the_pc_means_no_guess(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(code_insight, '_user_python', return_value=None):
                report = check(folder, 'needs.py', 'import surely_not_a_module_xyz\nprint(surely_not_a_module_xyz)\n')
        self.assertFalse(any('surely_not_a_module_xyz' in w for w in report['avisos']))


class WebTests(unittest.TestCase):
    def test_page_loading_a_missing_script_or_style_fails(self):
        page = ('<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>'
                '<button id="go">Go</button><script src="app.js"></script></body></html>')
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'index.html', page, {'style.css': 'body{}'})
        self.assertFalse(report['ok'])
        joined = ' '.join(report['errores'])
        self.assertIn('styles.css', joined)
        self.assertIn('app.js', joined)

    def test_page_with_its_files_present_is_ok(self):
        page = ('<html><head><link rel="stylesheet" href="css/site.css?v=2"></head><body><img src="logo%20big.png">'
                '<a href="https://example.com/x.html">x</a><a href="#top">top</a><script src="app.js"></script></body></html>')
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'index.html', page, {'css/site.css': 'body{}', 'logo big.png': 'x',
                                                        'app.js': 'document.title="ok";\n'})
        self.assertTrue(report['ok'] is not False, report)
        self.assertEqual(report['errores'], [])

    def test_id_lookups_and_duplicate_ids_are_warned(self):
        page = ('<html><body><div id="score"></div><div id="score"></div><canvas id="game"></canvas>'
                '<script>const c=document.getElementById("gmae");const s=document.querySelector("#score");'
                'const made=document.createElement("p");made.id="later";document.getElementById("later");</script></body></html>')
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'game.html', page)
        joined = ' '.join(report['avisos'])
        self.assertIn('"gmae"', joined)
        self.assertIn('id "score" is used again', joined)
        self.assertNotIn('"later"', joined)
        self.assertNotIn('"score" but', joined)

    def test_relative_imports_that_point_nowhere(self):
        with tempfile.TemporaryDirectory() as folder:
            code_ok, _ = code_insight.javascript("import {a} from './lib.js';\nconst b=require('./util');\n",
                                                 str(Path(folder) / 'main.js'))
            Path(folder, 'lib.js').write_text('export const a=1;', encoding='utf-8')
            Path(folder, 'util.js').write_text('module.exports=1;', encoding='utf-8')
            code_fixed, _ = code_insight.javascript("import {a} from './lib.js';\nconst b=require('./util');\n",
                                                    str(Path(folder) / 'main.js'))
        self.assertEqual(len(code_ok), 2, code_ok)
        self.assertEqual(code_fixed, [])

    def test_css_url_to_a_missing_file_is_warned(self):
        with tempfile.TemporaryDirectory() as folder:
            report = check(folder, 'site.css', 'body{background:url("img/bg.png")}\n.a{background:url(data:image/png;base64,AA)}\n')
        self.assertTrue(report['ok'])
        self.assertTrue(any('img/bg.png' in w for w in report['avisos']), report['avisos'])


if __name__ == '__main__':
    unittest.main()
