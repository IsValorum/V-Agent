"""Faults found in the 2026-11-12 audit: each one stays fixed."""
import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

if 'STRATA_AGENT_DATA' not in os.environ:
    import atexit, shutil
    os.environ['STRATA_AGENT_DATA'] = tempfile.mkdtemp(prefix='va-test-')
    atexit.register(shutil.rmtree, os.environ['STRATA_AGENT_DATA'], True)
sys.path[:0] = ['agent', '.', 'tools']


class DnsRebindingTests(unittest.TestCase):
    def test_only_loopback_host_names_are_served(self):
        import agent
        server = ThreadingHTTPServer(('127.0.0.1', 0), agent.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)

        def status(host):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            connection.putrequest('GET', '/api/v1/sessions', skip_host=True)
            if host is not None:
                connection.putheader('Host', host)
            connection.endheaders()
            response = connection.getresponse(); response.read(); connection.close()
            return response.status

        for host in ('127.0.0.1:%d' % port, 'localhost:%d' % port, '127.0.0.1', '[::1]:%d' % port, 'LOCALHOST'):
            self.assertEqual(status(host), 200, host)
        for host in ('evil.example:%d' % port, 'evil.example', '127.0.0.1.evil.example', '', None):
            self.assertEqual(status(host), 421, host)

    def test_malformed_chat_requests_get_a_clear_400(self):
        import json
        import agent
        server = ThreadingHTTPServer(('127.0.0.1', 0), agent.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        for body in (b'{', b'[]', json.dumps({'messages': 'x'}).encode(), json.dumps({'messages': ['x']}).encode()):
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
            connection.request('POST', '/api/chat', body, {'Content-Type': 'application/json'})
            response = connection.getresponse(); response.read(); connection.close()
            self.assertEqual(response.status, 400, body)


class ApprovalTests(unittest.TestCase):
    def test_restoring_a_version_is_a_write_that_asks(self):
        from tool_approvals import needs_approval
        self.assertTrue(needs_approval('ask', 'pc__file_history', {'path': 'a.txt', 'revision': 'r1'}))
        self.assertFalse(needs_approval('ask', 'pc__file_history', {'path': 'a.txt'}))  # listing stays a read
        self.assertTrue(needs_approval('auto', 'pc__file_history', {'path': 'a.txt', 'revision': 'r1'}))

    def test_sensitive_files_are_seen_in_every_path_argument(self):
        from tool_approvals import needs_approval
        self.assertTrue(needs_approval('ask', 'pc__fs_read', {'path': '.env'}))
        self.assertTrue(needs_approval('auto', 'pc__fs_copy', {'desde': 'id_rsa', 'destino': 'x.txt'}))
        self.assertTrue(needs_approval('auto', 'pc__fs_manage', {'path': 'x', 'destination': 'secret.pem'}))


class LlamaKeyTests(unittest.TestCase):
    def test_llama_server_gets_a_private_key_and_the_core_sends_it(self):
        from engine_manager import EngineManager
        manager = EngineManager.__new__(EngineManager)
        manager.kind = 'llama'; manager.llama_key = 'k123'; manager.settings = {}
        self.assertEqual(manager.headers().get('Authorization'), 'Bearer k123')
        source = Path('agent/engine_manager.py').read_text(encoding='utf-8')
        self.assertIn("argv+=['--api-key',self.llama_key]", source)


class StrataSupportTests(unittest.TestCase):
    def test_engine_refusal_is_reported_in_spanish_and_cached(self):
        import model_import
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / 'strata-poly.exe'; exe.write_bytes(b'')
            model = Path(folder) / 'm.gguf'; model.write_bytes(b'')
            answer = type('P', (), {'communicate': lambda self, timeout=None: (b"strata-poly: m.gguf is a 'bailingmoe3' model, which this engine does not run\n", b''),
                                    'kill': lambda self: None})()
            model_import._REJECTIONS.clear()
            with patch.object(model_import, 'LOG_ROOT', Path(folder) / 'logs'), \
                 patch.object(model_import.subprocess, 'Popen', return_value=answer) as popen:
                self.assertEqual(model_import.strata_rejection(exe, model), 'bailingmoe3')
                self.assertEqual(model_import.strata_rejection(exe, model), 'bailingmoe3')
                self.assertEqual(popen.call_count, 1)  # asked once
            self.assertIn('bailingmoe3', model_import.unsupported_message('bailingmoe3'))
            model_import._REJECTIONS.clear()


class LoopMessageTests(unittest.TestCase):
    def test_cut_message_does_not_claim_a_rewrite(self):
        import agent
        control = type('C', (), {'bucle': '3 llamadas seguidas rechazadas antes de ejecutarse'})()
        text = agent._cierre_bucle(control, '', None)
        self.assertNotIn('Guardar', text)
        self.assertNotIn('versiones sucesivas', text)
        control.bucle = 'repeated empty output'
        self.assertIn('respuestas vacías', agent._cierre_bucle(control, '', None))


if __name__ == '__main__':
    unittest.main()
