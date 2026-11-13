import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "agent"), str(ROOT)]

import browser_mcp
import conversation_codec
import engine_manager
import pc_mcp


class PcMcpJobStatusTests(unittest.TestCase):
    def tearDown(self):
        with pc_mcp.JOBS_LOCK:
            for job in list(pc_mcp.JOBS.values()):
                proc = job.get("process")
                if proc and proc.poll() is None:
                    proc.kill()
            pc_mcp.JOBS.clear()

    def test_job_status_does_not_deadlock_on_background_job(self):
        class _Policy:
            root = Path(tempfile.gettempdir())
            full_pc = False

        raw = pc_mcp._start_background(
            {"command": f'"{sys.executable}" -c "import time; print(\'hello\'); time.sleep(0.05)"', "shell": "cmd"},
            _Policy(),
        )
        jid = json.loads(raw)["job_id"]
        out = {}
        err = {}

        def probe():
            try:
                out["value"] = json.loads(pc_mcp.job_status({"job_id": jid}))
            except Exception as exc:
                err["exc"] = exc

        worker = threading.Thread(target=probe, daemon=True)
        worker.start()
        worker.join(timeout=2.0)
        self.assertFalse(worker.is_alive(), "pc_mcp.job_status deadlocked on JOBS_LOCK")
        self.assertIsNone(err.get("exc"))
        self.assertEqual(out["value"]["job_id"], jid)
        wait_res = json.loads(pc_mcp.job_wait({"job_id": jid, "timeout": 5}))
        self.assertEqual(wait_res["exit_code"], 0)
        self.assertIn("hello", wait_res["output"])


class BrowserMcpReliabilityTests(unittest.TestCase):
    def test_network_reports_failed_request_url_from_request_will_be_sent(self):
        page = object.__new__(browser_mcp.CdpPage)
        page.closed = False
        page.lock = threading.RLock()
        page.request_urls = {"req-99": "https://example.test/broken.js"}
        page.events = [
            (1.0, "Network.loadingFailed", {"requestId": "req-99", "errorText": "net::ERR_NAME_NOT_RESOLVED"})
        ]
        with patch.object(browser_mcp, "_page", return_value=page):
            items = json.loads(browser_mcp.network())
        self.assertEqual(items[0]["url"], "https://example.test/broken.js")
        self.assertEqual(items[0]["error"], "net::ERR_NAME_NOT_RESOLVED")

    def test_navigate_raises_on_cdp_error_text(self):
        fake_page = MagicMock()
        fake_page.send.return_value = {"frameId": "F1", "errorText": "net::ERR_NAME_NOT_RESOLVED"}
        with patch.object(browser_mcp, "_page", return_value=fake_page):
            with self.assertRaises(browser_mcp.CdpError):
                browser_mcp._navigate("https://nonexistent.invalid/")

    def test_fill_file_input_uses_cdp_set_file_input_files(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
            tmp.write("probe")
            tmp_path = Path(tmp.name)
        try:
            calls = []
            fake_page = MagicMock()
            fake_page.evaluate.return_value = {"found": True, "tag": "INPUT", "type": "file"}

            def fake_send(method, params=None, timeout=30):
                calls.append((method, params))
                if method == "Runtime.evaluate":
                    return {"result": {"objectId": "obj-42"}}
                return {}

            fake_page.send.side_effect = fake_send
            with patch.object(browser_mcp, "_page", return_value=fake_page):
                res = json.loads(browser_mcp.fill("#file-upload", str(tmp_path)))
            self.assertTrue(res["ok"])
            self.assertEqual(res["files"], [str(tmp_path.resolve())])
            methods = [m for m, _ in calls]
            self.assertIn("DOM.setFileInputFiles", methods)
            set_files_params = dict(calls)[("DOM.setFileInputFiles")]
            self.assertEqual(set_files_params["objectId"], "obj-42")
            self.assertEqual(set_files_params["files"], [str(tmp_path.resolve())])
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_fill_file_input_rejects_missing_file_cleanly(self):
        fake_page = MagicMock()
        fake_page.evaluate.return_value = {"found": True, "tag": "INPUT", "type": "file"}
        with patch.object(browser_mcp, "_page", return_value=fake_page):
            res = json.loads(browser_mcp.fill("#file-upload", r"C:\__no_such_file_98765__.bin"))
        self.assertFalse(res["ok"])
        self.assertIn("File not found", res["error"])

    def test_snapshot_js_includes_shadow_dom_text_collector(self):
        js = browser_mcp._snapshot_js(5000, 30)
        self.assertIn("collectPageText", js)
        self.assertIn("r.host.shadowRoot", js)


class ContextCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(engine_manager, "DATA_ROOT", Path(self.tmp.name))
        self.patch.start()
        self.manager = engine_manager.EngineManager()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _run_server(self, handler_cls):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server

    def test_openai_responses_compact_endpoint_is_used_when_supported(self):
        seen_paths = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                seen_paths.append(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                _ = json.loads(self.rfile.read(n))
                body = json.dumps({
                    "object": "response.compaction",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": "Resumen compacto nativo."}]},
                    ],
                    "usage": {"input_tokens": 120, "output_tokens": 25},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = self._run_server(Handler)
        try:
            base = f"http://127.0.0.1:{srv.server_port}/v1"
            self.manager.configure({"engine": "api", "protocol": "openai", "base_url": base, "api_key": "k"})
            self.manager.online = True
            self.manager.remote_models = [{"id": "gpt-test", "display_name": "gpt-test"}]
            self.manager.loaded = self.manager.remote_identifier({"id": "gpt-test"})
            res = self.manager.compact_context(self.manager.loaded, [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "Mundo"}])
            self.assertEqual(res["method"], "openai_responses_compact")
            self.assertEqual(res["summary"], "Resumen compacto nativo.")
            self.assertEqual(res["usage"], {"prompt_tokens": 120, "completion_tokens": 25})
            self.assertEqual(seen_paths, ["/v1/responses/compact"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_openai_compatible_falls_back_cleanly_to_chat_completions_on_404(self):
        seen_paths = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                seen_paths.append(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                _ = json.loads(self.rfile.read(n))
                if self.path.endswith("/responses/compact"):
                    self.send_response(404)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                body = json.dumps({
                    "choices": [{"message": {"content": "Resumen DeepSeek compatible."}}],
                    "usage": {"prompt_tokens": 80, "completion_tokens": 18},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = self._run_server(Handler)
        try:
            base = f"http://127.0.0.1:{srv.server_port}/v1"
            self.manager.configure({"engine": "api", "protocol": "openai", "base_url": base, "api_key": "k"})
            self.manager.online = True
            self.manager.remote_models = [{"id": "deepseek-chat", "display_name": "deepseek-chat"}]
            self.manager.loaded = self.manager.remote_identifier({"id": "deepseek-chat"})
            res = self.manager.compact_context(self.manager.loaded, [{"role": "user", "content": "A"}, {"role": "assistant", "content": "B"}])
            self.assertEqual(res["method"], "api_chat_completions")
            self.assertEqual(res["summary"], "Resumen DeepSeek compatible.")
            self.assertEqual(seen_paths, ["/v1/responses/compact", "/v1/chat/completions"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_anthropic_messages_compaction(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                seen.append(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                _ = json.loads(self.rfile.read(n))
                body = json.dumps({
                    "content": [{"type": "text", "text": "Resumen Anthropic."}],
                    "usage": {"input_tokens": 55, "cache_read_input_tokens": 5, "output_tokens": 12},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = self._run_server(Handler)
        try:
            base = f"http://127.0.0.1:{srv.server_port}/v1"
            self.manager.configure({"engine": "api", "protocol": "anthropic", "base_url": base, "api_key": "k"})
            self.manager.online = True
            self.manager.remote_models = [{"id": "claude-test", "display_name": "claude-test"}]
            self.manager.loaded = self.manager.remote_identifier({"id": "claude-test"})
            res = self.manager.compact_context(self.manager.loaded, [{"role": "user", "content": "Hola"}])
            self.assertEqual(res["method"], "anthropic_messages")
            self.assertEqual(res["summary"], "Resumen Anthropic.")
            self.assertEqual(res["usage"], {"prompt_tokens": 60, "completion_tokens": 12})
            self.assertEqual(seen, ["/v1/messages"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_conversation_codec_expands_compacted_checkpoint_in_alternating_turns(self):
        hist = [
            {"role": "assistant", "content": "Resumen clave", "compacted": {"method_label": "API nativa"}},
            {"role": "user", "content": "Siguiente paso"},
        ]
        out = conversation_codec.model_history(hist)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])
        self.assertIn("Resumen clave", out[0]["content"])

    def test_local_compaction_summarizes_and_reduces_history_for_strata_and_llama(self):
        import agent as agent_mod
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n))
                seen.append((self.path, payload))
                body = json.dumps({
                    "choices": [{"message": {"content": "<think>borrador interno</think>\nObjetivo: compilar 1.0.9. Archivos: doc_extractor.py."}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 18},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = self._run_server(Handler)
        try:
            long_history = [
                {"role": "user", "content": "Analiza el código " + ("detalle " * 300)},
                {"role": "assistant", "content": "Resultado extenso " + ("línea " * 300), "tool_trace": [
                    {"executed": True, "name": "pc__fs_read", "args": {"path": "README.md"}, "result": "x" * 2000}
                ]},
                {"role": "user", "content": "Sigue con doc_extractor.py"},
            ]
            # 1) Strata local compaction (agent.compact_local_context)
            res_strata = agent_mod.compact_local_context("qwen-local", long_history, engine_port=srv.server_port)
            self.assertTrue(res_strata["ok"])
            self.assertEqual(res_strata["method"], "local_chat_completions")
            self.assertEqual(res_strata["method_label"], "Resumen con modelo local")
            self.assertNotIn("<think>", res_strata["summary"])
            self.assertIn("Objetivo: compilar 1.0.9.", res_strata["summary"])

            # 2) llama.cpp / Strata Rust local compaction (EngineManager.compact_context)
            self.manager.configure({"engine": "llama"})
            self.manager.online = True
            self.manager.loaded = "gemma-local.gguf"
            with patch.object(self.manager, "base", return_value=f"http://127.0.0.1:{srv.server_port}/v1"):
                res_llama = self.manager.compact_context("gemma-local.gguf", long_history)
            self.assertEqual(res_llama["method"], "local_chat_completions")
            self.assertNotIn("<think>", res_llama["summary"])
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[1][1]["chat_template_kwargs"], {"no_date": True, "enable_thinking": False})

            # 3) Verify real prompt compression on the next turn via conversation_codec
            raw_payload_chars = len(json.dumps(conversation_codec.model_history(long_history), ensure_ascii=False))
            compacted_history = [
                {"role": "assistant", "content": res_strata["summary"], "compacted": {"method": res_strata["method"], "method_label": res_strata["method_label"]}},
                {"role": "user", "content": "¿Cuál es el siguiente paso?"},
            ]
            compacted_payload_chars = len(json.dumps(conversation_codec.model_history(compacted_history), ensure_ascii=False))
            self.assertLess(compacted_payload_chars * 4, raw_payload_chars)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_ui_wires_compact_button_and_fixes_interrupted_params_label(self):
        chat_js = (ROOT / "agent/ui/app/chat.js").read_text(encoding="utf-8")
        panel_js = (ROOT / "agent/ui/app/model-panel.js").read_text(encoding="utf-8")
        composer_js = (ROOT / "agent/ui/app/composer.js").read_text(encoding="utf-8")
        self.assertIn("hasParsedArgs", chat_js)
        self.assertIn("id=\"ctxCompact\"", panel_js)
        self.assertIn("/api/harness/context/compact", composer_js)
        main_rs = (ROOT / "desktop/src-tauri/src/main.rs").read_text(encoding="utf-8")
        self.assertIn('value["product"]=="V-Agent"', main_rs)
        self.assertIn("autobrowser__fill", main_rs)


if __name__ == "__main__":
    unittest.main()
