"""Regression suite for the exhaustive 7-server MCP audit and codebase reliability/UI fixes."""

from __future__ import annotations

import json
import math
import os
import secrets
import shutil
import socket
import struct
import sys
import tempfile
import threading
import unittest
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "agent" / "ui"
sys.path[:0] = [str(ROOT), str(ROOT / "agent"), str(ROOT / "web_mcp")]

if "STRATA_AGENT_DATA" not in os.environ:
    import atexit

    os.environ["STRATA_AGENT_DATA"] = tempfile.mkdtemp(prefix="va-audit-data-")
    atexit.register(shutil.rmtree, os.environ["STRATA_AGENT_DATA"], True)
os.environ.setdefault("VAL_ADMIN_NO_ELEVATE", "1")

import agent as agent_mod
import desktop_runtime
import engine_manager
import hf_mcp
import render_check
import runtime_paths
from access_policy import AccessPolicy, workspace_signature
from mcp_prompt import compact_tools, validate_tool_arguments
from serve import frontend, logit_bias, mcp as serve_mcp, prometheus, replicas, runconfig, server, structured, telemetry
from serve.mcp import hub_from_config


def _tiny_png_bytes() -> bytes:
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * 16 for _ in range(16))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class _AuditHttpHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/page1":
            body = b"""<!doctype html><html><head><title>Page One</title></head><body>
            <h1>Hello Audit</h1>
            <form action="/done" method="get">
              <input id="q" name="q" placeholder="Search">
              <button type="submit">Go</button>
            </form>
            <iframe srcdoc="<input id='fi'><button id='fb' onclick='this.textContent=document.getElementById(&quot;fi&quot;).value'>FBtn</button>"></iframe>
            <div id="host"></div>
            <script>
              const s = document.getElementById('host').attachShadow({mode:'open'});
              s.innerHTML = '<button id="sbtn" data-done="ShadowDone" onclick="this.textContent=this.dataset.done">SBtn</button>';
              console.log('audit-console-1');
              fetch('/api/ping').catch(()=>{});
            </script></body></html>"""
            ctype = "text/html; charset=utf-8"
        elif self.path == "/page2":
            body = b'<!doctype html><html><head><title>Page Two</title></head><body><p>Second tab</p><script>console.warn("tab2-warn");</script></body></html>'
            ctype = "text/html; charset=utf-8"
        elif self.path == "/api/ping":
            body = b'{"pong":true}'
            ctype = "application/json"
        elif self.path == "/err500":
            body = b"server exploded"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/api/ping")
            self.end_headers()
            return
        else:
            body = b"<!doctype html><html><title>Done</title><body>Done</body></html>"
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        data_in = self.rfile.read(length).decode("utf-8", "replace")
        payload = json.dumps({"body": data_in, "x_test": self.headers.get("X-Test")}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class McpSevenServerAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = Path(tempfile.mkdtemp(prefix="va-mcp-suite-"))
        cls.data_dir = cls.tmp_dir / "data"
        cls.data_dir.mkdir(parents=True, exist_ok=True)
        cls.pc_key = secrets.token_hex(16)
        cls.chat_id = f"audit-{uuid.uuid4().hex[:8]}"
        cls.ticket = {"id": cls.chat_id, "signature": workspace_signature(cls.pc_key, cls.chat_id)}
        # Match the subprocess workspace path resolved from STRATA_AGENT_DATA=cls.data_dir.
        cls.ws = cls.data_dir / "workspaces" / "conversations" / cls.chat_id
        cls.ws.mkdir(parents=True, exist_ok=True)
        (cls.ws / "tiny.png").write_bytes(_tiny_png_bytes())

        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _AuditHttpHandler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.srv.server_port}"

        env_data = str(cls.data_dir)
        cls.hub = hub_from_config(
            {
                "mcpServers": {
                    "pc": {
                        "command": runtime_paths.command("pc")[0],
                        "args": runtime_paths.command("pc")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data, "STRATA_PC_ACCESS_KEY": cls.pc_key},
                    },
                    "hf": {
                        "command": runtime_paths.command("hf")[0],
                        "args": runtime_paths.command("hf")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data, "STRATA_PC_ACCESS_KEY": cls.pc_key},
                    },
                    "duckduckgo": {
                        "command": runtime_paths.command("web")[0],
                        "args": runtime_paths.command("web")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data},
                    },
                    "web": {
                        "command": runtime_paths.command("webtools")[0],
                        "args": runtime_paths.command("webtools")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data},
                    },
                    "autobrowser": {
                        "command": runtime_paths.command("autobrowser")[0],
                        "args": runtime_paths.command("autobrowser")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data, "STRATA_AGENT_NO_OPEN": "1"},
                    },
                    "admin": {
                        "command": runtime_paths.command("admin")[0],
                        "args": runtime_paths.command("admin")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data, "VAL_ADMIN_NO_ELEVATE": "1"},
                    },
                    "computer": {
                        "command": runtime_paths.command("computer")[0],
                        "args": runtime_paths.command("computer")[1:],
                        "env": {"STRATA_AGENT_DATA": env_data},
                    },
                }
            }
        )
        cls.hub.start(wait=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.hub.close()
        finally:
            cls.srv.shutdown()
            cls.srv.server_close()
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _call(self, name: str, args: dict) -> dict:
        payload = dict(args)
        if name.startswith(("pc__", "hf__")):
            payload["_pc_workspace"] = self.ticket
            payload["_pc_access_key"] = self.pc_key
        return self.hub.call(name, payload)

    def test_tool_exposure_and_small_model_schema_coercion(self):
        all_raw = self.hub.openai_tools()
        raw_names = {t["function"]["name"] for t in all_raw}
        fn_all = {
            "search": True,
            "visit": True,
            "files": True,
            "browser": True,
            "web": True,
            "autobrowser": True,
            "shell": True,
            "console": True,
            "sys": True,
            "hf": True,
            "admin": True,
            "computer": True,
        }
        old_mode = agent_mod.ACCESS.snapshot().get("mode", "sandbox")
        try:
            with patch.object(agent_mod, "HUB", self.hub), patch("extensions.enabled_configs", return_value={}):
                agent_mod.ACCESS.set_mode("full_pc")
                offered_adv = agent_mod.tools_for(fn_all, agent_profile="advanced")
                offered_light = agent_mod.tools_for(fn_all, agent_profile="light")
        finally:
            agent_mod.ACCESS.set_mode(old_mode)

        allowed_adv = {t["function"]["name"] for t in offered_adv}
        allowed_light = {t["function"]["name"] for t in offered_light}
        self.assertEqual(allowed_adv, raw_names - {"autobrowser__navigate"})
        self.assertIn("autobrowser__evaluate", allowed_adv)
        self.assertTrue({"duckduckgo__web_search", "pc__fs_read", "pc__sys_info", "pc__shell_run"}.issubset(allowed_light))
        self.assertTrue(all("parameters" in t["function"] for t in compact_tools(offered_adv)))

        schemas = {t["function"]["name"]: t["function"]["parameters"] for t in all_raw}
        tab_args = {"index": "1", "switch": "false", "action": "switch"}
        validate_tool_arguments(schemas["autobrowser__tabs"], tab_args, strict=True)
        self.assertEqual(tab_args["index"], 1)
        self.assertIs(tab_args["switch"], False)

        fill_args = {"selector": "#q", "text": "123"}
        validate_tool_arguments(schemas["autobrowser__fill"], fill_args, strict=True)
        self.assertEqual(fill_args["text"], "123")

        http_args = {"url": self.base_url, "headers": '{"X-Test":"ok"}', "timeout": "10"}
        validate_tool_arguments(schemas["web__http_request"], http_args, strict=True)
        self.assertEqual(http_args["headers"], {"X-Test": "ok"})
        self.assertEqual(http_args["timeout"], 10.0)

        for fn_name, bad_args, expect_sub in (
            ("pc__shell_run", {"cmd": "dir"}, "Allowed arguments:"),
            ("autobrowser__open", {"url": "https://a.com", "wait": True}, "Allowed arguments:"),
            ("pc__fs_manage", {"action": "chmod", "path": "a.txt"}, "expected one of:"),
            ("autobrowser__tabs", {"action": "switch", "index": "abc"}, "expected integer or null"),
            ("pc__fs_read", {"path": "a.txt", "linea": True}, "expected integer"),
            ("hf__hf_cli", {"args": ["models", 123]}, "expected string"),
        ):
            with self.subTest(fn=fn_name, bad_args=bad_args):
                with self.assertRaises(ValueError) as ctx:
                    validate_tool_arguments(schemas[fn_name], dict(bad_args), strict=True)
                self.assertIn(expect_sub, str(ctx.exception))

    def test_pc_hf_web_admin_computer_tools_end_to_end(self):
        self.assertEqual(
            hf_mcp.redact("Use hf_transfer for files and token hf_1234567890abcdef"),
            "Use hf_transfer for files and token [REDACTED]",
        )
        r_hf = self._call("hf__hf_cli", {"args": ["hf", "version"]})
        self.assertTrue(r_hf["ok"], r_hf["text"])
        r_hf_url = self._call(
            "hf__hf_transfer", {"action": "download", "repo_id": "https://huggingface.co/Qwen/Qwen2.5-0.5B", "path": "dl"}
        )
        self.assertFalse(r_hf_url["ok"])
        self.assertIn("owner/name", r_hf_url["text"])

        self._call("pc__fs_write", {"path": "a.txt", "content": "uno\ndos\ntres\n"})
        r_list = self._call("pc__fs_list", {})
        self.assertTrue(r_list["ok"] and "a.txt" in r_list["text"], r_list["text"])

        r_bin = self._call("pc__fs_read", {"path": "tiny.png"})
        self.assertFalse(r_bin["ok"])
        self.assertIn("binary", r_bin["text"])

        r_l0 = self._call("pc__fs_read", {"path": "a.txt", "linea": 0, "ventana": 2})
        self.assertFalse(r_l0["ok"])
        self.assertIn("1-based", r_l0["text"])

        r_off = self._call("pc__fs_read", {"path": "a.txt", "offset": -1})
        self.assertFalse(r_off["ok"])
        self.assertIn("offset must be >= 0", r_off["text"])

        r_cp = self._call(
            "pc__fs_copy", {"desde": "a.txt", "destino": "b.txt", "linea": 1, "hasta": 2, "modo": "nuevo", "cortar": False}
        )
        self.assertTrue(r_cp["ok"] and "copiadas" in r_cp["text"] and "movidas" not in r_cp["text"], r_cp["text"])

        r_mv = self._call(
            "pc__fs_copy", {"desde": "a.txt", "destino": "c.txt", "linea": 1, "hasta": 1, "modo": "nuevo", "cortar": True}
        )
        self.assertTrue(r_mv["ok"] and "movida" in r_mv["text"], r_mv["text"])

        r_con = self._call("pc__console", {"action": "status"})
        self.assertFalse(r_con["ok"])
        self.assertIn("pc__shell_run", r_con["text"])

        r_br = self._call("pc__browser", {"action": "snapshot"})
        self.assertFalse(r_br["ok"])
        self.assertIn("autobrowser", r_br["text"])

        r_sh = self._call("pc__shell_run", {"command": "echo hello_audit", "timeout": 0})
        self.assertTrue(r_sh["ok"] and "hello_audit" in r_sh["text"], r_sh["text"])

        r_ck0 = self._call("computer__mouse_click", {"x": 10, "y": 10, "clicks": 0})
        self.assertFalse(r_ck0["ok"])
        self.assertIn("clicks must be between 1 and 3", r_ck0["text"])

        r_sc0 = self._call("computer__mouse_scroll", {"amount": 0})
        self.assertFalse(r_sc0["ok"])
        self.assertIn("amount cannot be 0", r_sc0["text"])

        r_priv = self._call("web__http_request", {"url": f"{self.base_url}/api/ping"})
        self.assertFalse(r_priv["ok"])
        self.assertIn("allow_private", r_priv["text"])

        r_post = self._call(
            "web__http_request",
            {"url": f"{self.base_url}/post", "method": "POST", "headers": {"X-Test": "v1"}, "body": "hello=1", "allow_private": True},
        )
        self.assertTrue(r_post["ok"], r_post["text"])
        p_data = json.loads(r_post["text"])
        self.assertEqual(json.loads(p_data.get("text", "{}")).get("x_test"), "v1")

        r_500 = self._call("web__http_request", {"url": f"{self.base_url}/err500", "allow_private": True})
        self.assertTrue((not r_500["ok"]) or json.loads(r_500["text"]).get("status") == 500)

        r_red = self._call("web__http_request", {"url": f"{self.base_url}/redir", "allow_private": True})
        self.assertTrue(r_red["ok"] and "/api/ping" in r_red["text"], r_red["text"])

        r_adm = self._call("admin__status", {})
        self.assertTrue(r_adm["ok"], r_adm["text"])

    def test_autobrowser_iframe_shadow_dom_tabs_and_network_preservation(self):
        r_open = self._call("autobrowser__open", {"url": f"{self.base_url}/page1"})
        self.assertTrue(r_open["ok"] and "Page One" in r_open["text"], r_open["text"])

        net1 = json.loads(self._call("autobrowser__network", {})["text"])
        con1 = json.loads(self._call("autobrowser__browser_console", {})["text"])
        self.assertGreaterEqual(len(net1), 1)
        self.assertTrue(any("audit-console-1" in x.get("text", "") for x in con1), con1)

        r_eval = self._call("autobrowser__evaluate", {"script": 'document.querySelector("h1").textContent'})
        self.assertTrue(r_eval["ok"] and "Hello Audit" in r_eval["text"], r_eval["text"])

        snap = json.loads(self._call("autobrowser__snapshot", {})["text"])
        iframe_btns = [it for it in snap["items"] if it.get("text") == "FBtn"]
        iframe_inps = [it for it in snap["items"] if it.get("tag") == "input" and it.get("name") != "q"]
        shadow_btns = [it for it in snap["items"] if it.get("text") == "SBtn"]
        self.assertTrue(iframe_inps and iframe_btns and shadow_btns, snap["items"])

        self._call("autobrowser__fill", {"selector": iframe_inps[0]["selector"], "text": "IframeOK"})
        self._call("autobrowser__click", {"selector": iframe_btns[0]["selector"]})
        chk_if = json.loads(
            self._call("autobrowser__evaluate", {"script": 'document.querySelector("iframe").contentDocument.getElementById("fb").textContent'})["text"]
        )
        self.assertEqual(chk_if.get("value"), "IframeOK")

        self._call("autobrowser__click", {"selector": shadow_btns[0]["selector"]})
        chk_sh = json.loads(
            self._call("autobrowser__evaluate", {"script": 'document.getElementById("host").shadowRoot.getElementById("sbtn").textContent'})["text"]
        )
        self.assertEqual(chk_sh.get("value"), "ShadowDone")

        r_tab2 = self._call("autobrowser__tabs", {"action": "new", "url": f"{self.base_url}/page2", "switch": False})
        tab2_data = json.loads(r_tab2["text"])
        self.assertIs(tab2_data.get("switched"), False)
        self.assertEqual(tab2_data.get("tab_count"), 2)
        self.assertNotEqual(tab2_data.get("active_index"), tab2_data.get("new_tab_index"))

        net_after = json.loads(self._call("autobrowser__network", {})["text"])
        self.assertGreaterEqual(len(net_after), len(net1))

        r_bad_tab = self._call("autobrowser__tabs", {"action": "new", "url": "javascript:alert(1)", "switch": False})
        self.assertFalse(r_bad_tab["ok"])
        tabs_list = json.loads(self._call("autobrowser__tabs", {"action": "list"})["text"])
        self.assertEqual(tabs_list.get("count"), 2)

        r_close_inact = self._call("autobrowser__tabs", {"action": "close", "index": tab2_data["new_tab_index"]})
        close_inact = json.loads(r_close_inact["text"])
        self.assertEqual(close_inact.get("remaining"), 1)
        self.assertEqual(close_inact.get("active_index"), 0)

        eval_after_close = json.loads(self._call("autobrowser__evaluate", {"script": "location.pathname"})["text"])
        self.assertEqual(eval_after_close.get("value"), "/page1")
        net_after_close = json.loads(self._call("autobrowser__network", {})["text"])
        self.assertGreaterEqual(len(net_after_close), len(net1))

        r_close = self._call("autobrowser__close", {})
        self.assertTrue(r_close["ok"])
        tabs_after_close = json.loads(self._call("autobrowser__tabs", {"action": "list"})["text"])
        self.assertEqual(tabs_after_close.get("count"), 0)


class ServeAndAgentAuditTests(unittest.TestCase):
    def test_replicas_gpu_groups_and_replica_cfg_without_args(self):
        self.assertEqual(replicas.gpu_groups({"replicas": [{"gpus": [0, 1]}, {"gpus": [2]}]}), [[0, 1], [2]])
        cfg = replicas.replica_cfg({"args": None, "replicas": [{"gpus": [0], "args": ["--fast"]}]}, 0, [0])
        self.assertIn("--fast", cfg["args"])

    def test_replica_pool_heal_synchronizes_under_lock(self):
        started = []

        class _DeadEngine:
            batch = 0

            def alive(self):
                return False

            def restart(self):
                started.append(threading.get_ident())

        pool = object.__new__(replicas.ReplicaEngine)
        pool.engines = [_DeadEngine()]
        pool.router = replicas.Router(1)
        pool.inflight = [0]
        pool.routed = [0]
        pool.heal_at = [0.0]
        pool.healing = {}
        pool.lock = threading.Lock()
        # Concurrent calls must spawn only one restart attempt for the same dead replica.
        threads = [threading.Thread(target=pool.heal) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2)
        deadline = 0
        while pool.healing.get(0) and deadline < 50:
            threading.Event().wait(0.02)
            deadline += 1
        self.assertEqual(len(started), 1)
        view = pool.replica_view()
        self.assertEqual(len(view), 1)

    def test_serve_mcp_call_survives_missing_mcp_options_import(self):
        hub = serve_mcp.McpHub.__new__(serve_mcp.McpHub)
        hub.settings = {"timeout_s": 5.0, "max_result_chars": 100, "max_rounds": 1}
        srv = type(
            "_Srv",
            (),
            {"name": "demo", "call": lambda self, tool, args, timeout, cancel=None: {"content": [{"type": "text", "text": "x" * 150}]}},
        )()
        hub._routes = {"demo__ping": (srv, "ping")}
        hub.routes = lambda: hub._routes
        saved = sys.modules.get("mcp_options")
        try:
            sys.modules["mcp_options"] = None  # force ImportError in serve.mcp.call
            res = hub.call("demo__ping", {})
        finally:
            if saved is not None:
                sys.modules["mcp_options"] = saved
            else:
                sys.modules.pop("mcp_options", None)
        self.assertTrue(res["ok"])
        self.assertTrue(res["truncated"])

    def test_structured_extract_json_handles_internal_backticks(self):
        raw = '```json\n{"code": "```python\\nprint(1)\\n```", "ok": true}\n```'
        extracted = structured._extract_json(raw)
        self.assertEqual(json.loads(extracted), {"code": "```python\nprint(1)\n```", "ok": True})

    def test_prometheus_histogram_and_runconfig_reject_non_finite_and_bool(self):
        h = prometheus.Histogram()
        h.observe(math.nan)
        h.observe(math.inf)
        h.observe(True)
        self.assertEqual(h.sum, 0.0)
        self.assertEqual(h.n, 0)
        with self.assertRaises(ValueError):
            runconfig._number("temperature", float("nan"), "temperature")
        with self.assertRaises(ValueError):
            runconfig._number("temperature", True, "temperature")

    def test_logit_bias_normalize_thread_safe(self):
        errors = []

        def run():
            try:
                for _ in range(30):
                    out = logit_bias.normalize({"1": 2.0, "5": -1.5}, vocab_size=10)
                    if out != {1: 2.0, 5: -1.5}:
                        errors.append(out)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        ts = [threading.Thread(target=run) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=2)
        self.assertEqual(errors, [])

    def test_frontend_non_dict_chat_template_kwargs_raises_value_error(self):
        with self.assertRaises(ValueError):
            frontend.openai_to_messages({"messages": [{"role": "user", "content": "hi"}], "chat_template_kwargs": ["bad"]})

    def test_server_midstream_engine_errors_emit_sse_not_http_503(self):
        import http.client
        from http.server import HTTPServer
        import tempfile

        tok = server.ByteTokenizer()
        with tempfile.TemporaryDirectory() as td:
            tpl_path = Path(td) / "midstream_tpl.jinja"
            tpl_path.write_text("{% for m in messages %}{{ m.content }}{% endfor %}", encoding="utf-8")
            tpl = frontend.ChatTemplate(str(tpl_path))
            svc = server.Service(server.MockEngine(tok, "hi"), tok, tpl)

            def fail_midstream(*args, **kwargs):
                yield "ping", None
                raise server.EngineNonFinite("nan logits")

            svc.run = fail_midstream
            handler_cls = server.make_handler(svc)
            for path, payload, marker in (
                ("/v1/chat/completions", {"stream": True, "messages": [{"role": "user", "content": "hi"}]}, "data: [DONE]"),
                ("/v1/responses", {"stream": True, "input": "hi"}, "response.failed"),
                ("/v1/messages", {"stream": True, "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}, "event: error"),
            ):
                with self.subTest(path=path):
                    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
                    srv.timeout = 3.0
                    t = threading.Thread(target=srv.handle_request, daemon=True)
                    t.start()
                    conn = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=3.0)
                    try:
                        conn.request("POST", path, json.dumps(payload), {"Content-Type": "application/json", "Connection": "close"})
                        resp = conn.getresponse()
                        raw = resp.read().decode("utf-8", "replace")
                        self.assertEqual(resp.status, 200)
                        self.assertIn("nan logits", raw)
                        self.assertIn(marker, raw)
                        self.assertNotIn("HTTP/1.", raw)
                    finally:
                        conn.close()
                        t.join(timeout=3.0)
                        srv.server_close()

    def test_engine_manager_compact_context_unwraps_api_prefix(self):
        captured = []

        def make_mgr(fallback_chat=False, conn_id="openai", with_remote=True):
            def fake_post(path, payload, extra_headers=None, timeout=120):
                captured.append((path, payload))
                if path == "/responses/compact":
                    if fallback_chat:
                        return 404, '{"error":{"message":"not found"}}'
                    return 200, json.dumps({
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": "resumen compacto"}]}],
                        "usage": {"input_tokens": 120, "output_tokens": 25},
                    })
                return 200, json.dumps({
                    "choices": [{"message": {"content": "resumen fallback"}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 25},
                })

            mgr = object.__new__(engine_manager.EngineManager)
            mgr.kind = "api"
            mgr.loaded = "api--openai--deepseek-chat"
            mgr.settings = {
                "api": {
                    "id": conn_id,
                    "protocol": "openai",
                    "base_url": "https://api.example.test/v1",
                    "api_key": "sk-test",
                    "selected_model": "deepseek-chat",
                }
            }
            mgr.remote_models = [{"id": "deepseek-chat", "provider": "openai", "protocol": "openai"}] if with_remote else []
            mgr._post_json = fake_post
            return mgr

        res = make_mgr(False).compact_context("api--openai--deepseek-chat", [{"role": "user", "content": "hola"}], instructions="mantener hechos")
        self.assertTrue(res["ok"])
        self.assertEqual(res["method"], "openai_responses_compact")
        self.assertEqual(captured[-1][0], "/responses/compact")
        self.assertEqual(captured[-1][1]["model"], "deepseek-chat")

        res_fb = make_mgr(True, conn_id="legacy", with_remote=False).compact_context(
            "api--openai--deepseek-chat", [{"role": "user", "content": "hola"}], instructions="mantener hechos"
        )
        self.assertTrue(res_fb["ok"])
        self.assertEqual(res_fb["method"], "api_chat_completions")
        self.assertEqual(captured[-1][0], "/chat/completions")
        self.assertEqual(captured[-1][1]["model"], "deepseek-chat")

    def test_render_check_retains_pintura_and_diagnostics(self):
        fake = {
            "info": {
                "url": "http://127.0.0.1/test.html",
                "navegador": "Edge",
                "nodos": 5,
                "canvas": 1,
                "dimensiones_canvas": "300x150",
                "webgl": "ok",
                "contexto_webgl": "webgl2",
                "pixeles_pintados": 8,
                "scene_diagnostics": {"available": True, "issues": []},
            },
            "consola": [],
            "errores": [],
        }
        with patch.object(render_check, "_navega", return_value=fake), patch.object(render_check._SESION, "vivo", return_value=True):
            out = render_check.render("http://127.0.0.1/test.html", pintura=True, diagnostics=True, mantener=True)
        self.assertEqual(out["pixeles_pintados"], 8)
        self.assertTrue(out["scene_diagnostics"]["available"])

    def test_desktop_runtime_read_json_dict_rejects_non_dict(self):
        import atexit
        import io
        import tempfile
        import types
        import extensions

        with tempfile.TemporaryDirectory() as td:
            profile_path = Path(td) / "profiles.json"
            profile_path.write_text('{"profiles":{"code":{"sampling":{}}}}', encoding="utf-8")

            class _BaseHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    pass

                def do_POST(self):
                    pass

            noop = lambda *a, **kw: None
            fake_agent = types.SimpleNamespace(
                Handler=_BaseHandler,
                PORT=0,
                ENGINE_LOCK=threading.Lock(),
                VRAM_AUTO=True,
                PROFILE_PATH=profile_path,
                MODEL_PREFERENCES=types.SimpleNamespace(creators={}),
                PREPARATION=types.SimpleNamespace(snapshot=lambda: {}),
                kv_settings=types.SimpleNamespace(FORMATS={}, validate=lambda c, v: v),
                installed_models=lambda: {"data": [], "models": []},
                selected_model=lambda m: {},
                engine_health=lambda: {"loaded": False},
                current_model=lambda: (None, None),
                load_agent_model=noop,
                unload_agent_model=noop,
                change_context=noop,
                start_engine=noop,
                stop_engine=noop,
                stats=lambda: {},
                require_loaded_model=lambda m=None: m,
                engine_context=lambda: 16384,
                engine_chat_stream=iter([]),
                tokenizer_del_modelo=noop,
                configure_model_draft=noop,
                ui_origin_allowed=lambda o, p: True,
            )
            fake_mgr = types.SimpleNamespace(kind="strata", builds={}, loaded=None, online=False, settings={})
            fake_updates = types.SimpleNamespace(check=lambda *a, **kw: {"releases": {}})
            with patch.object(desktop_runtime, "EngineManager", return_value=fake_mgr), \
                 patch.object(desktop_runtime, "Updates", return_value=fake_updates), \
                 patch.object(extensions.Catalog, "refresh", return_value=None), \
                 patch.object(atexit, "register"):
                desktop_runtime.install(fake_agent)

            h = object.__new__(fake_agent.Handler)
            h.headers = {"Content-Length": "4"}
            h.rfile = io.BytesIO(b"[12]")
            with self.assertRaises(ValueError):
                h._read_json_dict(1024, "invalid")
            h.headers = {"Content-Length": "7"}
            h.rfile = io.BytesIO(b'{"a":1}')
            self.assertEqual(h._read_json_dict(1024, "invalid"), {"a": 1})

    def test_telemetry_disk_negative_delta_clamped(self):
        tel = object.__new__(telemetry.Telemetry)

        class _Counters:
            def __init__(self, r, w):
                self.read_bytes = r
                self.write_bytes = w

        vals = [_Counters(1000, 1000), _Counters(200, 300)]

        class _Ps:
            def disk_io_counters(self):
                return vals.pop(0)

        tel.ps = _Ps()
        tel._disk_prev = None
        with patch.object(telemetry.time, "time", side_effect=[10.0, 11.0]):
            self.assertEqual(tel._disk(), (None, None))
            self.assertEqual(tel._disk(), (0.0, 0.0))

    def test_ui_locales_and_load_settings_order_invariants(self):
        locales = json.loads((UI / "locales.json").read_text(encoding="utf-8"))
        for key, row in locales.items():
            self.assertTrue(isinstance(row, dict) and all(row.get(lang) for lang in ("en", "pt", "fr", "de")), f"Incomplete locale entry: {key!r}")
        css = (UI / "styles" / "panels.css").read_text(encoding="utf-8")
        self.assertIn("#contextCompactBox", css)
        mp = (UI / "app" / "model-panel.js").read_text(encoding="utf-8")
        ls = (UI / "app" / "load-settings.js").read_text(encoding="utf-8")
        self.assertIn("function attachLoadSettingsToPanel()", mp)
        self.assertIn("attachLoadSettingsToPanel()", ls)


if __name__ == "__main__":
    unittest.main()
